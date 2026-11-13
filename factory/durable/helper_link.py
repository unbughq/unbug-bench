"""Helper machines, real transport (ARCHITECTURE.md "Helper machines").

The case worker holds no Boat credentials, so it cannot lease a helper itself. It talks to the control
VM the way everything else does: through files on its own disk that the control side reads and writes
over `boat ssh`. Three parts:

  SpoolPool   (case worker)  the HelperPool of helpers.py: lease/run/release become small request files in
                             ~/durable/helpers/<attempt>/req and wait for the answer in .../res.
  Broker      (control VM)   while a GATES attempt polls, lists the requests, leases a helper per `lease`
                             through BoatPool (same release install and verify as case workers), pushes the
                             case tree, runs the sealed job on it over ssh, writes the answer back, and
                             deletes the helper on `release`, or when the attempt ends or goes quiet.
  serve/main  (helper)       `python3 -B factory/durable/helper_link.py run`: one job frame on stdin, one
                             sealed result line on stdout (helpers.execute with the real check and run):
                             G5/G6/G7 checkpoints run bin/checkpoint; a G10 try runs run.hosted_try and
                             returns its model spend for the case ledger.

No new engine step: the broker lives inside the executor's poll loop, so recorded workflows replay
unchanged. Off unless runtime config has "helpers" (nothing writes the spool config otherwise).
A request is answered once; a claim written by an earlier controller process with no answer is answered
as lost, so the case worker requeues that job (helpers.run_jobs) instead of waiting for a dead relay.
"""
from __future__ import annotations

import io
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from pathlib import Path

_FACTORY = Path(__file__).resolve().parents[1]
if str(_FACTORY) not in sys.path:
    sys.path.insert(0, str(_FACTORY))

from durable import helpers  # noqa: E402
from durable.contract import RELEASE_ROOT, WORKER_ROOT, WorkerLease, attempt_id  # noqa: E402

HELPER_COMMAND = ("python3", "-B", "factory/durable/helper_link.py")   # + run; cwd RELEASE_ROOT
HELPER_CASE = re.compile(r"case-.*-h[0-9]+")   # BoatPool case id of a helper: <case>-h<k>
CASE_DIR = "helper-case"                       # on a helper: ~/helper-case/<lease>/ holds the case tree
NAME = re.compile(r"L[0-9]+(\.J[0-9]+|\.R)?")


def spool_rel(key: str) -> str:
    return f"{WORKER_ROOT}/helpers/{attempt_id(key)}"


def helper_case_id(case_id: str, name: str) -> str:
    return f"{case_id}-h{name[1:]}"


# ---- case worker -------------------------------------------------------------------------------

def read_config(root):
    """{cap, min_per_copy, job_timeout_s, usd_per_hour?} the control side wrote for this attempt, or None (off)."""
    try:
        value = json.loads((Path(root) / "config.json").read_text())
        ok = (isinstance(value, dict) and type(value["cap"]) is int and value["cap"] > 0
              and type(value["job_timeout_s"]) in (int, float) and value["job_timeout_s"] > 0
              and (value.get("usd_per_hour") is None or (type(value["usd_per_hour"]) in (int, float) and value["usd_per_hour"] >= 0))
              and (value["min_per_copy"] is None or (set(value["min_per_copy"]) == {"cpus", "mem_gib"}
                                                     and all(type(v) is int and v > 0 for v in value["min_per_copy"].values()))))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return value if ok else None


class SpoolPool:
    """helpers.HelperPool over the spool. Handles are lease names (L1, L2, ...)."""

    def __init__(self, root, case_dir, *, job_timeout_s, lease_timeout_s=1800.0, poll_s=1.0, sleep=time.sleep):
        self.root, self.case_dir = Path(root), Path(case_dir)
        self.job_timeout_s, self.lease_timeout_s, self.poll_s, self.sleep = job_timeout_s, lease_timeout_s, poll_s, sleep
        self._n, self._lock = 0, threading.Lock()

    def _name(self, prefix=""):
        with self._lock:
            self._n += 1
            return f"{prefix}{self._n}"

    def _post(self, name, request):
        (self.root / "req").mkdir(parents=True, exist_ok=True)
        tmp = self.root / "req" / f".{name}.tmp"
        tmp.write_text(json.dumps(request))
        os.replace(tmp, self.root / "req" / f"{name}.json")   # listed only once complete

    def _wait(self, name, timeout):
        path, end = self.root / "res" / f"{name}.json", time.monotonic() + timeout
        while True:
            try:
                answer = json.loads(path.read_text())
                path.unlink(missing_ok=True)
                for suffix in (".json", ".claim"): (self.root / "req" / f"{name}{suffix}").unlink(missing_ok=True)
                return answer if isinstance(answer, dict) else {}
            except (OSError, ValueError):
                pass
            if time.monotonic() >= end: return None
            self.sleep(self.poll_s)

    def lease(self):
        name = f"L{self._name()}"
        tar = self.root / "req" / f"{name}.case.tgz"
        tar.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar.with_suffix(".part"), "w:gz") as t: t.add(self.case_dir, arcname=".")
        tar.with_suffix(".part").replace(tar)
        self._post(name, {"op": "lease"})
        answer = self._wait(name, self.lease_timeout_s)
        tar.unlink(missing_ok=True)
        if not answer or answer.get("ok") is not True: raise helpers.HelperUnavailable(str((answer or {}).get("error")))
        return name

    def run(self, handle, job, key):
        name = f"{handle}.J{self._name()}"
        self._post(name, {"op": "job", "lease": handle, "job": job, "key": key.hex()})
        answer = self._wait(name, self.job_timeout_s + 300)
        if not answer or answer.get("ok") is not True: raise helpers.HelperDied(str((answer or {}).get("error")))
        return answer["sealed"]

    def release(self, handle, dead):
        name = f"{handle}.R"
        self._post(name, {"op": "release", "lease": handle, "dead": dead})
        self._wait(name, 300)   # the control side deletes the machine; a lost answer is not ours to retry


# ---- helper machine ------------------------------------------------------------------------------

def _check(job, case):
    """Refuse unless this machine's copy of every input is the one the job names. A try job's remaining
    conditions (seed, minutes, model, calibration identity) are checked by run.hosted_try before any call."""
    import run
    from durable.checkpoints import verdict_code
    if (verdict_code() != job["release"] or (job["bench"] is not None and run.bench_manifest() != job["bench"])
            or run.case_hash(type("C", (), {"case": case})) != job["case"]):
        raise helpers.HelperRefused("inputs differ from the job's")
    if job.get("kind") == "try": return
    from calibration import tree_digest
    if helpers.digest_of(tree_digest(_guard(job, case))) != job["guard"]:
        raise helpers.HelperRefused("guard differs from the job's")
    _scenarios(job, case)


def _guard(job, case):
    import run
    where, rel = job["guard_at"]
    return (case if where == "case" else run.BENCH) / rel


def _scenarios(job, case):
    """The case tree's scenario directories the job names by digest, in its order: base first (every
    serial checkpoint starts there), then G5's key scenario, if any."""
    from calibration import tree_digest
    dirs = [case / "base", *sorted(p for p in (case / "scenarios").glob("*") if p.is_dir())]
    found = {helpers.digest_of(tree_digest(d)): d for d in dirs}
    named = [found.get(s) for s in job["scenarios"]]
    if not named or named[0] != case / "base" or None in named: raise helpers.HelperRefused("scenarios differ from the job's")
    return named


def _prepare(workers):
    import factory_pool
    marker = Path.home() / ".helper-prepared"
    if not marker.exists() or marker.read_text() != str(workers):
        if not factory_pool.prepare(workers, fresh=True): raise RuntimeError("bench setup did not complete")
        marker.write_text(str(workers))


def _env(job):
    """The case worker's UNBUG_* values, exactly (absent ones removed)."""
    env = {k: v for k, v in os.environ.items() if k not in job.get("env", {})}
    env.update({k: v for k, v in job.get("env", {}).items() if v is not None})
    return env


def _run(job, case):
    """bin/checkpoint exactly as run.checkpoint invokes it; returns the directory it wrote."""
    import run
    import checkpoint_evidence
    _prepare(job["workers"])
    args = [str(run.BENCH / "bin/checkpoint")] + [x for s in _scenarios(job, case) for x in ("--scenario", str(s))]
    if job["workers"] > 1: args += ["--factory-workers", str(job["workers"])]
    args += ["--guard", str(_guard(job, case)), "--runs", str(job["runs"]), "--stress", "--seed", str(job["seed"]), "--label", job["label"]]
    p = subprocess.run(args, capture_output=True, text=True, env=_env(job), timeout=job.get("timeout_s"))
    receipts = [l[len(checkpoint_evidence.RECEIPT_PREFIX):] for l in p.stdout.splitlines() if l.startswith(checkpoint_evidence.RECEIPT_PREFIX)]
    if p.returncode or len(receipts) != 1: raise RuntimeError("checkpoint failed")
    return Path(json.loads(receipts[0])["path"]).parent


def _try_context(job, case, work):
    """The case worker's run context for one try, rebuilt from the job (helpers.try_context): its args,
    models and roles, router batch and deadline. Money: a fresh budget ledger whose attempt ceiling is
    the try's up-front authority, so the helper cannot spend past what the case side sized for it."""
    import types
    import run
    x = job["context"]
    for d in ("logs", "transcripts"): (work / d).mkdir(parents=True, exist_ok=True)
    c = run.Ctx()
    c.case_id, c.work, c.case, c.bench_root, c.card = x["case_id"], work, case, run.BENCH, dict(x["card"])
    a = run.argument_parser().parse_args(["--source", "port"])
    for k, v in x["args"].items(): setattr(a, k, v)
    a.helper_workers, a.resume = 0, None   # a helper never dispatches further; a try is never a resume here
    deadline = x["deadline_epoch"] or time.time() + job.get("timeout_s", 14400)
    a.agent_timeout = max(0.001, deadline - time.time())
    a.case_budget = float(job["authority_usd"])
    c.args, c.seed, c.t0, c.models, c.stopped = a, x["seed"], time.time() - 1, x["models"], False
    if x.get("router_accounts") is not None: c.router_accounts = x["router_accounts"]
    c.batch_id, c.job_id, c.batch_deadline = x["batch"]
    c.manifest0 = run.bench_manifest()
    c.ledger = work / "continuation-budget.json"
    c.engine = types.SimpleNamespace(kind="gates", round=None, key=f"{x['attempt']}/helper/{helpers.try_key(job)}",
                                     source_binding={}, ceiling_usd=float(job["authority_usd"]), baseline_spent_usd=0.0,
                                     deadline_epoch=deadline, deadline_monotonic=time.monotonic() + max(0.0, deadline - time.time()))
    c.stress_checkpoint = lambda: True
    if (case / "statement.md").is_file(): c.statement = (case / "statement.md").read_text()
    return c


def _run_try(job, case):
    """One G10 try exactly as calibrate authors and scores it (run.hosted_try), behind a fresh pilot user
    and wall made by the serial make_pilots. Returns its sealed files plus spend.json, the try's model
    spend for the case's ledger. A try that fails after it may have called a model still returns its
    spend (as {"failed"}), so the case side books it before requeueing."""
    import run
    from budget import reconcile_reservations
    from worker_secrets import router_environment
    _prepare(job["workers"])
    for k, v in job.get("env", {}).items():   # this process serves one job: its env is the case worker's
        if v is None: os.environ.pop(k, None)
        else: os.environ[k] = v
    os.environ.update(router_environment()); os.environ["UNBUG_PROVIDER_WAIT"] = "1"   # as worker_step.supervise
    work = case.parent / f"{case.name}.work" / helpers.try_key(job)[:16]
    c = _try_context(job, case, work)
    try:
        run.make_pilots(c, [("pilot", 0)], False)
        c.pilot_user = "pilot"
        files = run.hosted_try(c, job)
    except helpers.HelperRefused:
        raise
    except Exception as error:
        files = {"result.json": json.dumps({"failed": type(error).__name__})}
    if c.ledger.exists(): reconcile_reservations(work, c.ledger)
    files["spend.json"] = json.dumps(helpers.spend_of(c.ledger, c.card))
    return files


def serve(frame, *, check=None, run=None, home=None):
    """One job frame {job, key, lease} to its sealed result. check/run are replaceable for tests."""
    case = Path(home or Path.home()) / CASE_DIR / frame["lease"]
    own = _run_try if frame["job"].get("kind") == "try" else _run
    return helpers.execute(frame["job"], bytes.fromhex(frame["key"]),
                           check=check or (lambda job: _check(job, case)), run=run or (lambda job: own(job, case)))


def main(argv=None, stdin=None, stdout=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["run"]: return 2
    try:
        out = serve(json.loads((stdin or sys.stdin).read()))
    except Exception as error:   # the control side only needs to know it failed; the text may hold paths
        print(type(error).__name__, file=sys.stderr)
        return 1
    print(json.dumps(out), file=stdout or sys.stdout)
    return 0


# ---- control VM ----------------------------------------------------------------------------------

class _Watch:
    def __init__(self, worker, si):
        self.worker, self.si, self.spool = worker, si, "~/" + spool_rel(si.idempotency_key)
        self.helpers, self.claimed, self.seen = {}, set(), time.monotonic()
        self.stop = threading.Event()


class Broker:
    """Control side. pool: BoatPool. boat: BoatCli. A helper is a BoatPool worker under case id <case>-h<k>."""

    def __init__(self, pool, boat, *, per_case=4, total=12, vm_type=None, min_per_copy=None, job_timeout_s=7200.0,
                 tick_s=2.0, idle_s=180.0, command=HELPER_COMMAND, ledger_dir=None, usd_per_hour=None, command_timeout=120.0, blob_timeout=900.0):
        self.pool, self.boat, self.per_case, self.total = pool, boat, per_case, total
        self.vm_type, self.min_per_copy, self.job_timeout_s = vm_type, min_per_copy, job_timeout_s
        self.tick_s, self.idle_s, self.command = tick_s, idle_s, tuple(command)
        self.ledger_dir, self.usd_per_hour = (Path(ledger_dir) if ledger_dir else None), usd_per_hour
        self.command_timeout, self.blob_timeout = command_timeout, blob_timeout
        self.instance, self._lock, self._watches, self._count = uuid.uuid4().hex, threading.Lock(), {}, 0

    # -- called by the channel

    def prepare(self, worker, si):
        """Before the attempt starts: the spool and its config. Failure leaves helpers off for this attempt."""
        w = _Watch(worker, si)
        config = json.dumps({"cap": self.per_case, "min_per_copy": self.min_per_copy, "job_timeout_s": self.job_timeout_s,
                             "usd_per_hour": self.usd_per_hour})
        code, _ = self.boat.ssh(worker, f"set -eu; umask 077; d={w.spool}; mkdir -p $d/req $d/res; cat > $d/config.json",
                                stdin=config.encode(), timeout=self.command_timeout)
        return code == 0

    def watch(self, worker, si):
        """Called on every poll of a running attempt: keeps its relay alive."""
        key = si.idempotency_key
        with self._lock:
            w = self._watches.get(key)
            if w is None:
                w = self._watches[key] = _Watch(worker, si)
                threading.Thread(target=self._loop, args=(w,), daemon=True).start()
            w.seen = time.monotonic()

    def finish(self, si):
        with self._lock:
            w = self._watches.pop(si.idempotency_key, None)
        if w is not None:
            w.stop.set()
            self._release_all(w)

    def release_orphans(self):
        """After a controller restart no helper has an owner: delete every helper record."""
        from durable.workers import lease_worker_id
        for case_id, record in self.pool._records().items():
            if HELPER_CASE.fullmatch(case_id) and record and record["worker"]:
                self.pool.release(WorkerLease(lease_worker_id(record["worker"]), case_id))

    # -- relay

    def _loop(self, w):
        while not w.stop.wait(self.tick_s):
            if time.monotonic() - w.seen > self.idle_s:   # nobody polls this attempt any more
                self.finish(w.si)
                return
            try: self._tick(w)
            except Exception:   # a transport failure is not an answer: the next tick retries
                pass

    def _tick(self, w):
        script = (f"python3 -c \"import json,os; d=os.path.expanduser('{w.spool}'); r={{}}; c={{}}\n"
                  "for n in sorted(os.listdir(d+'/req')):\n"
                  "  if n.endswith('.json') and not os.path.exists(d+'/res/'+n): r[n[:-5]]=json.load(open(d+'/req/'+n))\n"
                  "  elif n.endswith('.claim'): c[n[:-6]]=open(d+'/req/'+n).read()\n"
                  "print(json.dumps([r,c]))\"")
        code, out = self.boat.ssh(w.worker, script, timeout=self.command_timeout)
        if code != 0: return
        requests, claims = json.loads(out)
        for name, request in requests.items():
            if name in w.claimed or not NAME.fullmatch(name) or not isinstance(request, dict): continue
            if claims.get(name) == self.instance:   # already handled by this process (an earlier watch of the attempt)
                w.claimed.add(name)
                continue
            if claims.get(name) is not None:   # claimed by a controller that is gone
                self._answer(w, name, {"ok": False, "error": "relay_lost"})
                self._ssh_ok(w, f"printf %s {self.instance} > {w.spool}/req/{name}.claim")   # answered once, whatever the reader does
                w.claimed.add(name)
                continue
            self._ssh_ok(w, f"printf %s {self.instance} > {w.spool}/req/{name}.claim")
            w.claimed.add(name)
            target = {"lease": self._lease, "job": self._job, "release": self._release}.get(request.get("op"))
            if target is None: self._answer(w, name, {"ok": False, "error": "bad_request"}); continue
            threading.Thread(target=target, args=(w, name, request), daemon=True).start()

    def _ssh_ok(self, w, script, stdin=None, timeout=None):
        code, out = self.boat.ssh(w.worker, script, stdin=stdin, timeout=timeout or self.command_timeout)
        if code != 0: raise OSError("ssh")
        return out

    def _answer(self, w, name, value):
        script = (f"set -eu; umask 077; d={w.spool}/res; t=\"$d/.{name}.$$\"; cat > \"$t\"; mv \"$t\" \"$d/{name}.json\"")
        for _ in range(3):
            try: return self._ssh_ok(w, script, stdin=json.dumps(value).encode())
            except OSError: time.sleep(1)

    def _note(self, w, event):
        if self.ledger_dir is None: return
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        with (self.ledger_dir / f"{w.si.case_id}.jsonl").open("a") as f:
            f.write(json.dumps({**event, "attempt": attempt_id(w.si.idempotency_key)[:16], "at": round(time.time())}) + "\n")

    # -- operations

    def _lease(self, w, name, request):
        with self._lock:
            full = self._count >= self.total or len(w.helpers) >= self.per_case
            if not full: self._count += 1
        if full: return self._answer(w, name, {"ok": False, "error": "cap"})
        lease, began = None, time.monotonic()
        try:
            lease = self.pool.acquire(helper_case_id(w.si.case_id, name), w.si.plumbing_version, w.si.bench_version,
                                      vm_type=self.vm_type)
            from durable.workers import boat_id
            tar = self._ssh_ok(w, f"cat {w.spool}/req/{name}.case.tgz", timeout=self.blob_timeout)
            self.boat_ok(boat_id(lease.worker_id), f"set -eu; umask 077; d=~/{CASE_DIR}/{name}; rm -rf $d; mkdir -p $d; tar -xzf - -C $d",
                         tar, self.blob_timeout)
            if w.stop.is_set(): raise OSError("attempt ended")   # finish() already swept; do not leak this one
            w.helpers[name] = (lease, began)
            self._note(w, {"event": "lease", "helper": lease.worker_id, "ready_s": round(time.monotonic() - began, 1)})
            self._answer(w, name, {"ok": True})
        except Exception:
            if lease is not None: self._delete(lease)
            with self._lock: self._count -= 1
            self._answer(w, name, {"ok": False, "error": "lease_failed"})

    def boat_ok(self, boat_worker, script, stdin, timeout):
        code, _ = self.boat.ssh(boat_worker, script, stdin=stdin, timeout=timeout)
        if code != 0: raise OSError("ssh")

    def _job(self, w, name, request):
        held = w.helpers.get(request.get("lease"))
        if held is None: return self._answer(w, name, {"ok": False, "error": "no_lease"})
        from durable.workers import boat_id
        try:
            frame = json.dumps({"job": request["job"], "key": request["key"], "lease": request["lease"]}).encode()
            code, out = self.boat.ssh(boat_id(held[0].worker_id),
                                      f"cd ~/{RELEASE_ROOT} && exec {shlex.join(self.command)} run", stdin=frame,
                                      timeout=self.job_timeout_s)
            lines = out.decode("utf-8", "replace").split("\n")
            sealed = json.loads(lines[-2] if lines[-1] == "" else lines[-1]) if code == 0 else None
        except Exception:
            sealed = None
        self._answer(w, name, {"ok": True, "sealed": sealed} if sealed is not None else {"ok": False, "error": "job_failed"})

    def _release(self, w, name, request):
        held = w.helpers.pop(request.get("lease"), None)
        seconds = self._free(w, held, bool(request.get("dead")))
        self._answer(w, name, {"ok": True, "seconds": seconds})

    def _free(self, w, held, dead):
        if held is None: return 0
        lease, began = held
        self._delete(lease)
        with self._lock: self._count -= 1
        seconds = round(time.monotonic() - began, 1)
        self._note(w, {"event": "release", "helper": lease.worker_id, "dead": dead, "seconds": seconds})
        return seconds

    def _release_all(self, w):
        for name in list(w.helpers):
            self._free(w, w.helpers.pop(name, None), False)

    def _delete(self, lease):
        try: self.pool.release(lease)
        except Exception:   # the pool's own sweep deletes what a failed release left
            pass


if __name__ == "__main__":
    sys.exit(main())
