"""Fakes of every seam WP1 composes, written from the contract protocols, and the engine driver
the WP1 engine tests run in a child process.

docs/designs/durable-execution-wp1.md, "Tests". The fakes keep all their state in files under
one directory, so they outlive a SIGKILL of the engine process the way real workers, R2 and
the ledger table do:

- FakeWorker: the worker side of the wire protocol (contract RELEASE_MANIFEST notes): an
  O_EXCL attempt marker, a per-case busy check, a tombstoning cancel, first-wins results, a
  deadline, detached completion (an attempt finishes at its own time whether or not the
  engine is alive), and injectable transport failures and worker death. It also opens every
  input blob with the keys it was given, as a worker must.
- FakeLedger: the Ledger docstring (labels, waste, settle_lost, idempotent replay).
- FakeStore, FakeSealer, FakeKeys: a directory store, a keyed-stream sealer built on
  derive_keys/artifact_digest, and fixed scope keys.

Run directly, this file checks the fakes against the contract docstrings. With
`engine <workdir>` it is the engine program: it reads <workdir>/scenario.json, runs the
batch on real DBOS (SQLite), and writes <workdir>/result.json.
"""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory")]
os.environ.setdefault("BENCH", str(ROOT))

from durable.artifacts import ArtifactError
from durable.contract import (BATCH_SCOPED, ArtifactKind, BatchSpec, Grant, LimitedBy, Outcome, Poll, PollState,
                              Ref, StepKind, StepResult, Usage, Verdict, WorkerLease, artifact_digest, derive_keys,
                              poll_from_record, start_frame, step_input_from_record, step_result_from_record,
                              to_record)

A64 = "a" * 64
ALL_GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "G13", "G14", "G15", "G16", "G17")


# ---- shared file state ---------------------------------------------------------------------------

class _Files:
    """JSON documents under one directory, updated under one fcntl lock (threads and processes)."""
    _tlock = threading.RLock()

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @contextlib.contextmanager
    def locked(self):
        with self._tlock, open(self.root / ".lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def read(self, name, default):
        p = self.root / name
        return json.loads(p.read_text()) if p.exists() else default

    def write(self, name, value):
        p = self.root / name
        tmp = p.with_name(p.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(value, sort_keys=True))
        os.replace(tmp, p)

    def append(self, name, record):
        record = {"t": time.time(), **record}
        with open(self.root / name, "a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def lines(self, name):
        p = self.root / name
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


# ---- keys, sealer, store -------------------------------------------------------------------------

class FakeKeys:
    def scope_key(self, scope):
        return hashlib.sha256(b"fake-scope-key:" + scope.encode()).digest()


def _stream(secret, n):
    out, i = b"", 0
    while len(out) < n:
        out += hashlib.sha256(secret + i.to_bytes(8, "big")).digest()
        i += 1
    return out[:n]


class FakeSealer:
    """seal/open with the age secret and HMAC key from derive_keys; opens only with its scope key."""

    def seal(self, scope_key, kind, plaintext):
        age, mac = derive_keys(scope_key)
        ref = Ref(artifact_digest(mac, plaintext), ArtifactKind(kind))
        tag = hashlib.sha256(b"tag" + age).digest()[:8]
        return ref, b"FAKEAGE1" + tag + bytes(a ^ b for a, b in zip(plaintext, _stream(age, len(plaintext))))

    def open(self, scope_key, ref, ciphertext):
        age, mac = derive_keys(scope_key)
        if ciphertext[:8] != b"FAKEAGE1" or ciphertext[8:16] != hashlib.sha256(b"tag" + age).digest()[:8]:
            raise ArtifactError("digest_mismatch")
        body = ciphertext[16:]
        plaintext = bytes(a ^ b for a, b in zip(body, _stream(age, len(body))))
        if artifact_digest(mac, plaintext) != ref.digest:
            raise ArtifactError("digest_mismatch")
        return plaintext


class FakeStore:
    def __init__(self, root):
        self.root = Path(root)

    def _path(self, scope, ref):
        return self.root / scope / f"{ref.digest}.{ref.kind.value}"

    def put_sealed(self, scope, ref, ciphertext):
        p = self._path(scope, ref)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_bytes(ciphertext)
        os.replace(tmp, p)

    def get_sealed(self, scope, ref):
        return self._path(scope, ref).read_bytes()

    def exists(self, scope, ref):
        return self._path(scope, ref).exists()


# ---- ledger --------------------------------------------------------------------------------------

class FakeLedger:
    """The Ledger docstring, in one JSON file. Every call is idempotent on its key."""

    def __init__(self, root):
        self.f = _Files(root)

    def _state(self):
        return self.f.read("ledger.json", {"batches": {}, "cases": {}, "res": {}})

    def open(self, batch_id, bound_usd_micros):
        with self.f.locked():
            s = self._state()
            s["batches"].setdefault(batch_id, {"bound": bound_usd_micros, "spent": 0, "held": 0, "waste": 0})
            self.f.write("ledger.json", s)

    def raise_bound(self, batch_id, bound_usd_micros):
        with self.f.locked():
            s = self._state()
            b = s["batches"][batch_id]
            b["bound"] = max(b["bound"], bound_usd_micros)
            self.f.write("ledger.json", s)
            self.f.append("ledger.log", {"op": "raise_bound", "bound": bound_usd_micros})

    def reserve(self, batch_id, case_id, idempotency_key, requested_usd_micros, case_limit_usd_micros, *,
                draws_case_money=True):
        with self.f.locked():
            s = self._state()
            if idempotency_key in s["res"]:
                r = s["res"][idempotency_key]
                return Grant(r["amount"], LimitedBy(r["label"]))
            b = s["batches"][batch_id]
            c = s["cases"].setdefault(case_id, {"spent": 0, "held": 0})
            batch_left = max(0, b["bound"] - b["spent"] - b["held"])
            case_left = max(0, case_limit_usd_micros - c["spent"] - c["held"])
            amount = min(requested_usd_micros, batch_left, case_left if draws_case_money else requested_usd_micros)
            amount = max(0, amount)
            if batch_left <= amount:
                label = LimitedBy.BATCH
            elif draws_case_money and case_left < requested_usd_micros:
                label = LimitedBy.CASE
            else:
                label = LimitedBy.NOTHING
            b["held"] += amount
            if draws_case_money:
                c["held"] += amount
            s["res"][idempotency_key] = {"batch": batch_id, "case": case_id, "amount": amount, "label": label.value,
                                         "draws": draws_case_money, "settled": None}
            self.f.write("ledger.json", s)
            self.f.append("ledger.log", {"op": "reserve", "key": idempotency_key, "amount": amount,
                                         "label": label.value, "draws": draws_case_money})
            return Grant(amount, label)

    def _close(self, key, paid, waste, how):
        with self.f.locked():
            s = self._state()
            r = s["res"][key]
            if r["settled"] is not None:
                return
            b, c = s["batches"][r["batch"]], s["cases"][r["case"]]
            b["held"] -= r["amount"]
            if r["draws"]:
                c["held"] -= r["amount"]
            b["spent"] += paid
            if waste:
                b["waste"] += paid
            elif r["draws"]:
                c["spent"] += paid
            r["settled"] = {"how": how, "paid": paid, "waste": waste}
            self.f.write("ledger.json", s)
            self.f.append("ledger.log", {"op": how, "key": key, "paid": paid, "waste": waste})

    def settle(self, idempotency_key, usage, *, waste=False):
        self._close(idempotency_key, usage.paid_usd_micros, waste, "settle")

    def settle_lost(self, idempotency_key):
        with self.f.locked():
            amount = self._state()["res"][idempotency_key]["amount"]
        self._close(idempotency_key, amount, True, "settle_lost")

    def book_waste(self, idempotency_key, reason):
        """SqlLedger.book_waste: a settled attempt's case spend becomes batch waste, once."""
        with self.f.locked():
            s = self._state()
            r = s["res"].get(idempotency_key)
            if r is None or r["settled"] is None or r["settled"]["waste"] or not r["draws"] or r.get("rebooked"):
                return False
            r["rebooked"] = reason
            s["cases"][r["case"]]["spent"] -= r["settled"]["paid"]
            s["batches"][r["batch"]]["waste"] += r["settled"]["paid"]
            self.f.write("ledger.json", s)
            self.f.append("ledger.log", {"op": "book_waste", "key": idempotency_key, "reason": reason})
            return True

    def balance(self, batch_id):
        """SqlLedger.balance: the batch's remaining bound."""
        b = self.snapshot()["batches"][batch_id]
        return {"remaining": max(0, b["bound"] - b["spent"] - b["held"])}

    def case_balance(self, batch_id, case_id, case_limit_usd_micros):
        """SqlLedger.case_balance: the case's own money left under its limit."""
        c = self.snapshot()["cases"].get(case_id, {"spent": 0, "held": 0})
        return {"remaining": max(0, case_limit_usd_micros - c["spent"] - c["held"])}

    def snapshot(self):
        with self.f.locked():
            return self._state()


# ---- pool and worker -----------------------------------------------------------------------------

def case_number(case_id):
    return int(case_id.rsplit("-", 1)[1])


class FakePool:
    def __init__(self, root, fail_acquires=0, reason=None):
        self.f = _Files(root)
        self.fail_acquires, self.reason = fail_acquires, reason

    def acquire(self, case_id, plumbing_version, bench_version):
        with self.f.locked():
            failures = self.f.read("acquire-failures.json", 0)
            if failures < self.fail_acquires:
                self.f.write("acquire-failures.json", failures + 1)
                if self.reason:
                    from durable.workers import PoolError
                    raise PoolError(self.reason)
                raise RuntimeError("provider error containing a private path")
            s = self.f.read("pool.json", {})
            w = s.get(case_id)
            if w is None or w["dead"]:
                gen = 1 if w is None else w["gen"] + 1
                w = {"gen": gen, "dead": False}
                s[case_id] = w
                self.f.write("pool.json", s)
                self.f.append("pool.log", {"op": "provision", "case": case_id, "gen": gen})
            return WorkerLease(f"w-{case_number(case_id)}-{w['gen']}", case_id)

    def release(self, lease):
        with self.f.locked():
            s = self.f.read("pool.json", {})
            w = s.get(lease.case_id)
            if w is not None and f"w-{case_number(lease.case_id)}-{w['gen']}" == lease.worker_id:
                w["dead"] = True
                self.f.write("pool.json", s)
            self.f.append("pool.log", {"op": "release", "case": lease.case_id, "worker": lease.worker_id})

    def kill(self, lease_or_case):
        with self.f.locked():
            s = self.f.read("pool.json", {})
            s[lease_or_case]["dead"] = True
            self.f.write("pool.json", s)

    def alive(self, lease):
        s = self.f.read("pool.json", {})
        w = s.get(lease.case_id)
        return w is not None and not w["dead"] and f"w-{case_number(lease.case_id)}-{w['gen']}" == lease.worker_id


def _stage_of(kind):
    return {"admit": "admit", "writer": "writer", "stress": "stress", "gates": "g11", "seal": "seal",
            "diagnosis": "diagnosis"}[kind]


class FakeWorker:
    """Worker side and control side of the channel in one, on files. `script` maps
    "<case n>/<seq>/<step name>/<attempt>", "<case n>/<step name>/<attempt>" or
    "<case n>/<step name>/*" to a result spec; the default is OK."""

    def __init__(self, root, pool, store, sealer, keys, scenario):
        self.f = _Files(root)
        self.pool, self.store, self.sealer, self.keys = pool, store, sealer, keys
        self.script = scenario.get("script", {})
        self.dur = scenario.get("default_dur", 0.05)
        self.flaky = scenario.get("flaky", {})
        self.dead_on_start = scenario.get("dead_on_start", [])

    # -- worker side --

    def _spec_for(self, si):
        n = case_number(si.case_id)
        for k in (f"{n}/{si.seq}/{si.step.name}/{si.attempt}", f"{n}/{si.step.name}/{si.attempt}",
                  f"{n}/{si.step.name}/*"):
            if k in self.script:
                return self.script[k]
        return {}

    def _seal(self, scope, kind, text):
        ref, ct = self.sealer.seal(self.keys.scope_key(scope), kind, text.encode())
        self.store.put_sealed(scope, ref, ct)   # the channel fetches outputs into the store before DONE
        return ref

    def _result(self, si, spec, now):
        key, case, batch = si.idempotency_key, si.case_id, si.batch_id
        outcome = Outcome(spec.get("outcome", "ok"))
        stage = _stage_of(si.step.kind.value)
        reason = spec.get("reason", f"{stage}:pass" if outcome is Outcome.OK else f"{stage}:failed")
        paid = spec.get("paid", 1000)
        if outcome is not Outcome.PROVIDER_LIMIT and paid > si.money_ceiling_usd_micros:
            outcome, reason, paid = Outcome.EXHAUSTED, f"{stage}:money", si.money_ceiling_usd_micros
        kw = {}
        k = si.step.kind
        snap = lambda: self._seal(case, ArtifactKind.CASE_SNAPSHOT, f"snapshot {key}")
        if outcome is Outcome.OK:
            kw["snapshot"] = snap()
            if k is StepKind.ADMIT:
                prev = si.registry.digest
                kw["registry"] = self._seal(batch, ArtifactKind.STATEMENT_REGISTRY, f"registry {prev} {case}")
            if k is StepKind.STRESS and spec.get("feedback"):
                kw["feedback"] = self._seal(case, ArtifactKind.WRITER_FEEDBACK, f"findings {key}")
            if k is StepKind.GATES:
                kw["passed"] = tuple(spec.get("passed", ALL_GATES))
                kw["receipt"] = self._seal(case, ArtifactKind.GATE_RECEIPT, f"receipt {key}")
            if k is StepKind.SEAL:
                kw["archive"] = self._seal(case, ArtifactKind.SEALED_ARCHIVE, f"archive {key}")
                kw["hard"] = bool(spec.get("hard", False))
            if k is StepKind.DIAGNOSIS:
                kw["verdict"] = Verdict(spec.get("verdict", "not_converging"))
                kw["report"] = self._seal(case, ArtifactKind.DIAGNOSIS_REPORT, f"report {key}")
                if kw["verdict"] is Verdict.CLOSE_TO_PASSING:
                    kw["feedback"] = self._seal(case, ArtifactKind.WRITER_FEEDBACK, f"guidance {key}")
        elif outcome is Outcome.GATE_FAILED:
            kw.update(gate=spec.get("gate", "G5"), passed=tuple(spec.get("passed", ())),
                      repairable=bool(spec.get("repairable", False)), snapshot=snap(),
                      receipt=self._seal(case, ArtifactKind.GATE_RECEIPT, f"receipt {key}"))
            if kw["repairable"]:
                kw["feedback"] = self._seal(case, ArtifactKind.WRITER_FEEDBACK, f"repair {key}")
        elif outcome is Outcome.NEEDS_FOUNDER:
            if k is StepKind.GATES:
                kw.update(gate=spec.get("gate"), passed=tuple(spec.get("passed", ())))
        elif outcome is Outcome.PROVIDER_LIMIT:
            kw["retry_at"] = now + spec.get("retry_in", 0.3)
        elif outcome is Outcome.INFRA_ERROR and spec.get("diagnostic"):
            kw["diagnostic"] = self._seal(case, ArtifactKind.DIAGNOSTIC, f"diagnostic {key}")
        if spec.get('checkpoint'): kw['snapshot'] = snap()
        return StepResult(outcome, reason, Usage(calls=1, paid_usd_micros=paid), **kw)

    def _open_inputs(self, frame, si):
        keys = {s: base64.b64decode(k) for s, k in frame["keys"].items()}
        refs = {"inputs": si.inputs, "snapshot": si.snapshot, "feedback": si.feedback, "registry": si.registry,
                "ruling": si.ruling}
        opened = {}
        for name, ref in list(refs.items()) + [(f"evidence{i}", r) for i, r in enumerate(si.evidence)]:
            if ref is None:
                continue
            blob = frame["blobs"].get(f"{ref.digest}.{ref.kind.value}.age")
            if name == "inputs" and si.step.kind is not StepKind.ADMIT:
                # WP5a restores the runner settings from the case snapshot. The batch
                # inputs ref is present, but later workers never receive the batch key.
                if blob is None or si.batch_id in keys:
                    return None
                continue
            if ref.kind in BATCH_SCOPED and (si.step.kind is StepKind.ADMIT or ref.kind is ArtifactKind.STATEMENT_REGISTRY):
                scope = si.batch_id
            else:
                scope = si.case_id
            if blob is None or scope not in keys:
                return None
            try:
                opened[name] = self.sealer.open(keys[scope], ref, blob).decode()
            except ValueError:
                return None
        return opened

    def _materialize(self, case_id, now):
        """Finish every due attempt of a case: the detached unit writes its result first-wins."""
        attempts = self.f.read(f"attempts-{case_id}.json", {})
        for key, a in sorted(attempts.items()):
            if a["done"] or a["dead"]:
                continue
            if now < a["done_at"]:
                continue
            si = step_input_from_record(a["input"])
            if a["mode"] == "busy":
                result = StepResult(Outcome.INFRA_ERROR, "infra:attempt_busy")
            elif a["mode"] == "bad_input":
                result = StepResult(Outcome.INFRA_ERROR, "infra:bad_input")
            elif a["deadline_hit"]:
                result = StepResult(Outcome.INFRA_ERROR, "infra:deadline", Usage(paid_usd_micros=a["spec"].get("paid", 1000)))
            else:
                result = self._result(si, a["spec"], now)
            self._write_result(key, result, ran=a["mode"] == "run", done_at=a["done_at"])
            a["done"] = True
        self.f.write(f"attempts-{case_id}.json", attempts)

    def _write_result(self, key, result, ran, done_at=None):
        p = self.f.root / "results" / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        p.parent.mkdir(exist_ok=True)
        try:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL)   # first wins
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as fh:
            fh.write(json.dumps(to_record(result)))
            fh.flush()
            os.fsync(fh.fileno())
        if ran:
            self.f.append("worker.log", {"op": "ran", "key": key, "outcome": result.outcome.value,
                                         "reason": result.reason, "done_at": done_at})
        return True

    def _read_result(self, key):
        p = self.f.root / "results" / (hashlib.sha256(key.encode()).hexdigest() + ".json")
        return step_result_from_record(json.loads(p.read_text())) if p.exists() else None

    # -- control side (WorkerChannel) --

    def start(self, lease, step_input, keys, blobs):
        frame = start_frame(step_input, keys)
        frame["blobs"] = blobs
        si = step_input_from_record(json.loads(json.dumps(frame["input"])))
        key, now = si.idempotency_key, time.time()
        with self.f.locked():
            if not self.pool.alive(lease):
                return   # a dead worker never answers
            self._materialize(si.case_id, now)
            attempts = self.f.read(f"attempts-{si.case_id}.json", {})
            if key in attempts:
                self.f.append("worker.log", {"op": "start_again", "key": key, "t": now})
                return   # the marker exists (O_EXCL): a second start does nothing
            live = [k for k, a in attempts.items() if not a["done"] and not a["dead"]]
            spec = self._spec_for(si)
            opened = self._open_inputs(frame, si)
            mode = "busy" if live else ("run" if opened is not None else "bad_input")
            dur = spec.get("dur", self.dur)
            deadline_hit = dur > si.deadline_s
            attempts[key] = {"input": to_record(si), "spec": spec, "mode": mode, "done": False, "dead": False,
                             "worker": lease.worker_id, "deadline_hit": deadline_hit,
                             "done_at": now + (0 if mode != "run" else min(dur, si.deadline_s))}
            if key in self.dead_on_start and mode == "run":
                attempts[key]["dead"] = True
                self.pool.kill(si.case_id)
            self.f.write(f"attempts-{si.case_id}.json", attempts)
            self.f.append("worker.log", {"op": "start", "key": key, "mode": mode, "worker": lease.worker_id,
                                         "pv": si.plumbing_version[:4], "bv": si.bench_version[:4],
                                         "ceiling": si.money_ceiling_usd_micros, "deadline_s": si.deadline_s,
                                         "opened": opened, "evidence": [r.kind.value for r in si.evidence],
                                         "t": now, **({} if si.roles is None else {"roles": si.roles})})

    def _drop(self, what, key):
        n = self.flaky.get(what, {}).get(key, 0)
        if n <= 0:
            return False
        with self.f.locked():
            used = self.f.read("flaky.json", {})
            k = f"{what}/{key}"
            if used.get(k, 0) >= n:
                return False
            used[k] = used.get(k, 0) + 1
            self.f.write("flaky.json", used)
            self.f.append("worker.log", {"op": f"drop_{what}", "key": key})
        return True

    def poll(self, lease, step_input):
        key = step_input.idempotency_key
        if not self.pool.alive(lease) or self._drop("poll", key):
            return Poll(PollState.RUNNING)   # transport failure
        with self.f.locked():
            self._materialize(step_input.case_id, time.time())
            result = self._read_result(key)
            if result is not None:
                return poll_from_record(json.loads(json.dumps(to_record(Poll(PollState.DONE, result)))))
            attempts = self.f.read(f"attempts-{step_input.case_id}.json", {})
            if key not in attempts:
                return Poll(PollState.ABSENT)
            return Poll(PollState.RUNNING)

    def cancel(self, lease, step_input):
        key = step_input.idempotency_key
        if not self.pool.alive(lease) or self._drop("cancel", key):
            return
        with self.f.locked():
            self._materialize(step_input.case_id, time.time())
            attempts = self.f.read(f"attempts-{step_input.case_id}.json", {})
            if key not in attempts:   # tombstone: a late start does nothing
                attempts[key] = {"input": to_record(step_input), "spec": {}, "mode": "tombstone", "done": True,
                                 "dead": False, "worker": lease.worker_id, "deadline_hit": False, "done_at": 0}
            elif not attempts[key]["done"]:
                attempts[key]["done"] = True   # stop the unit
            self.f.write(f"attempts-{step_input.case_id}.json", attempts)
            if self._write_result(key, StepResult(Outcome.INFRA_ERROR, "infra:cancelled"), ran=False):
                self.f.append("worker.log", {"op": "cancelled", "key": key})


def build_fakes(state_dir, scenario):
    state = Path(state_dir)
    keys, sealer, store = FakeKeys(), FakeSealer(), FakeStore(state / "store")
    pool, ledger = FakePool(state / "pool", scenario.get("pool_failures", 0), scenario.get("pool_reason")), FakeLedger(state / "ledger")
    worker = FakeWorker(state / "worker", pool, store, sealer, keys, scenario)
    return dict(keys=keys, sealer=sealer, store=store, pool=pool, ledger=ledger, worker=worker)


def make_spec(**kw):
    base = dict(batch_id="b-t", plumbing_version="1" * 64, bench_version="2" * 64, app_repo="medusajs/medusa",
                app_commit="c" * 40, inputs=Ref(A64, ArtifactKind.INPUTS), target_sealed=1,
                money_bound_usd_micros=10_000_000_000, deadline_epoch=4e9, max_concurrency=2)
    return BatchSpec(**{**base, **kw})


def seed_batch(fakes, spec_kw, inputs=b"inputs: app pin and promise"):
    """Seal the batch INPUTS and initial registry with the batch key, as WP8's launch would."""
    keys, sealer, store = fakes["keys"], fakes["sealer"], fakes["store"]
    batch_id = spec_kw.get("batch_id", "b-t")
    bk = keys.scope_key(batch_id)
    inputs, ct = sealer.seal(bk, ArtifactKind.INPUTS, inputs)
    store.put_sealed(batch_id, inputs, ct)
    registry, ct = sealer.seal(bk, ArtifactKind.STATEMENT_REGISTRY, b"registry: empty")
    store.put_sealed(batch_id, registry, ct)
    return make_spec(**{**spec_kw, "inputs": inputs}), registry


# ---- the engine program --------------------------------------------------------------------------

def engine_main(workdir):
    work = Path(workdir)
    scenario = json.loads((work / "scenario.json").read_text())
    from durable.engine import Engine, Timing, draining_sleep, hold_if_draining
    from durable import engine as engine_module
    from durable.cli import stop_on_signal
    from durable.guard import degraded
    from durable.executor import Executor
    from durable import report
    from durable.contract import BenchRelease, BoundRaised, FounderReply, PlumbingRelease, Topic
    engine_module.OVERRIDE_EXTRA.update(scenario.get('override_extra', {}))
    disabled_patches = set(scenario.get('disabled_patches', []))
    if scenario.get('legacy_admit_snapshot'):
        disabled_patches.add('admit_checkpoint_input')
    if disabled_patches:
        from dbos import DBOS
        original_patch = DBOS.patch
        DBOS.patch = classmethod(lambda cls, name: False if name in disabled_patches else original_patch(name))
    if scenario.get("release_step_failure"):
        from dbos import DBOS

        @DBOS.step()
        def fail_release(_case_id, _worker_id):
            raise RuntimeError("simulated cleanup failure")

        engine_module.release_step = fail_release
    if scenario.get("post_release_failure"):
        original_card = engine_module._Case.card

        def fail_sealed_card(case):
            if case.status == "sealed":
                raise RuntimeError("simulated post-cleanup reporting failure")
            return original_card(case)

        engine_module._Case.card = fail_sealed_card
    fakes = build_fakes(work / "state", scenario)
    if scenario.get('pool_acquire_delay_s'):
        acquire = fakes['pool'].acquire
        def slow_acquire(*args):
            time.sleep(scenario['pool_acquire_delay_s'])
            return acquire(*args)
        fakes['pool'].acquire = slow_acquire
    if scenario.get('reserve_delay_s') or scenario.get('case_reserve_delay_s'):
        # {"<seq>/<step>/<attempt>": seconds}, any case, and {"<case>/<seq>/<step>/<attempt>": seconds}: orders reservations
        reserve = fakes['ledger'].reserve
        def delayed_reserve(batch_id, case_id, key, *args, **kw):
            rest = key.split('/', 1)[1]
            time.sleep(scenario.get('reserve_delay_s', {}).get(rest, 0)
                       + scenario.get('case_reserve_delay_s', {}).get(f"{case_number(case_id)}/{rest}", 0))
            return reserve(batch_id, case_id, key, *args, **kw)
        fakes['ledger'].reserve = delayed_reserve
    if scenario.get('later_case_lease_fails'):   # [delay_s, reason]: every case but the first to lease fails
        acquire_ok = fakes['pool'].acquire
        first = work / 'first-leased-case'
        def failing_acquire(case_id, *args):
            if not first.exists():
                first.write_text(case_id)
            if first.read_text() == case_id:
                return acquire_ok(case_id, *args)
            time.sleep(scenario['later_case_lease_fails'][0])
            from durable.workers import PoolError
            raise PoolError(scenario['later_case_lease_fails'][1])
        fakes['pool'].acquire = failing_acquire
    if scenario.get("verification_failures"):
        original_exists = fakes["store"].exists
        remaining = [scenario["verification_failures"]]
        def flaky_exists(scope, ref):
            if remaining[0]:
                remaining[0] -= 1
                raise OSError("temporary store failure")
            return original_exists(scope, ref)
        fakes["store"].exists = flaky_exists
    spec_kw = dict(scenario.get("spec", {}))
    if "deadline_in" in scenario:   # a batch deadline that passes mid-run, fixed at the first launch
        fixed = work / "deadline.txt"
        if not fixed.exists():
            fixed.write_text(repr(time.time() + scenario["deadline_in"]))
        spec_kw["deadline_epoch"] = float(fixed.read_text())
    # "inputs": a real INPUTS document (e.g. a live, non-dry-run batch, whose model calls hold money).
    spec, registry = seed_batch(fakes, spec_kw, *([json.dumps(scenario["inputs"]).encode()] if "inputs" in scenario else []))
    class FaultInjectingExecutor(Executor):
        def call_hold(self, si):
            # {"<case>/<seq>/<step>/<attempt>": seconds}: a slow read of a step's call hold, to order reservations
            time.sleep(scenario.get("call_hold_delay_s", {}).get(f"{case_number(si.case_id)}/{si.idempotency_key.split('/', 1)[1]}", 0))
            return super().call_hold(si)

        def _poll(self, lease, step_input):
            fault = work / "executor-fault-fired"
            if scenario.get("raise_after_start") == step_input.idempotency_key and not fault.exists():
                fault.touch()
                raise RuntimeError("simulated failure after dispatch")
            return super()._poll(lease, step_input)

    if scenario.get("trace_credential_sleep"):
        from dbos import DBOS
        original_sleep = DBOS.sleep
        def trace_sleep(seconds):
            if seconds == scenario["timing"]["credential_retry_s"]:
                fakes["worker"].f.append("credential-sleep.log", {"seconds": seconds})
            return original_sleep(seconds)
        DBOS.sleep = staticmethod(trace_sleep)
    ex = FaultInjectingExecutor(fakes["pool"], fakes["worker"], fakes["ledger"], fakes["store"], fakes["sealer"],
                                fakes["keys"], poll_interval_s=scenario.get("poll_s", 0.02),
                                grace_s=scenario.get("grace_s", 0.3), sleep=draining_sleep, pause=hold_if_draining)
    timing = Timing(**{"batch_poll_s": 0.5, "wake_poll_s": 5.0, "founder_poll_s": 2.0, "queue_poll_s": 0.05,
                       "listener_poll_s": 0.05, **scenario.get("timing", {})})
    engine = Engine(system_database_url=scenario.get("database_url", f"sqlite:///{work}/sys.sqlite"), executor=ex,
                    timing=timing, admission_paused=lambda: degraded(work / "state"),
                    router_clear=lambda: (work / "router-clear").exists())
    engine.launch()
    if "drain_s" in scenario:
        stop_on_signal(lambda: engine.drain(scenario["drain_s"]))
    def report_in_flight():
        while True:
            fakes["worker"].f.write("in-flight.json", engine.in_flight())
            time.sleep(0.05)
    threading.Thread(target=report_in_flight, daemon=True).start()
    imported = None
    if scenario.get("import_snapshot"):
        # A rewrapped legacy checkpoint, prepared under the first case's scope like `prepare <case> case`.
        from durable.engine import case_id_for
        case = case_id_for(spec.batch_id, 1)
        imported, ct = fakes["sealer"].seal(fakes["keys"].scope_key(case), ArtifactKind.CASE_SNAPSHOT, b"legacy import")
        fakes["store"].put_sealed(case, imported, ct)
    if scenario.get("bad_restore"):   # a resume point that restores attempts never recorded: it diverges
        import durable.engine as engine_module
        made = engine_module.resume_point
        engine_module.resume_point = lambda *a, **k: (lambda p: {**p, "restore": p["restore"] + scenario["bad_restore"]})(made(*a, **k))
    if scenario.get("resume_of"):
        from durable.contract import ContractError
        try:   # what runtime.start books as waste before its resume_money check
            waste_keys = engine.factory_bug_waste_keys(scenario["resume_of"], scenario.get("override"))
        except ContractError as error:
            waste_keys = {"refused": str(error)}
        (work / "waste-keys.json").write_text(json.dumps(waste_keys))
        try:
            handle = engine.start_batch(spec, registry, None, scenario["resume_of"], scenario.get("override"),
                                        roles=scenario.get("roles"),
                                        **({"case_money_extra": scenario["case_money_extra"]}
                                           if "case_money_extra" in scenario else {}))
        except ContractError as error:
            (work / "result.json").write_text(json.dumps({"refused": str(error)}))
            print("ENGINE-DONE", flush=True)
            os._exit(0)
    else:
        handle = engine.start_batch(spec, registry, imported)
    from dbos import DBOS

    stop = threading.Event()

    def actions():
        done = set()
        while not stop.is_set():
            for i, act in enumerate(scenario.get("actions", [])):
                if i in done:
                    continue
                when = act["when"]
                if "ran" in when or "started" in when:
                    op, key = ("ran", when["ran"]) if "ran" in when else ("start", when["started"])
                    if not [x for x in fakes["worker"].f.lines("worker.log") if x["op"] == op and x["key"] == key]:
                        continue
                if "case" in when:
                    case_id = f"case-{spec.batch_id[2:]}-{when['case']}"
                    try:
                        card = DBOS.get_event(case_id, "card", timeout_seconds=0.01)
                    except Exception:
                        card = None
                    if not card or card.get("status") != when["status"]:
                        continue
                done.add(i)
                if act.get('delay_s'):
                    stop.wait(act['delay_s'])
                held = fakes['ledger'].snapshot()['batches'].get(spec.batch_id, {}).get('held')
                if "reply" in act:
                    rep = act["reply"]
                    ruling = None
                    if rep["action"] == "continue":
                        cid = f"case-{spec.batch_id[2:]}-{when['case']}"
                        ruling, ct = fakes["sealer"].seal(fakes["keys"].scope_key(cid), ArtifactKind.FOUNDER_RULING,
                                                          b"ruling: the reviewers' split is settled")
                        fakes["store"].put_sealed(cid, ruling, ct)
                    engine.reply(f"case-{spec.batch_id[2:]}-{when['case']}", FounderReply(rep["action"], ruling))
                if "bound" in act:
                    engine.send(spec.batch_id, Topic.BOUND_RAISED, BoundRaised(act["bound"]))
                if "plumbing" in act:
                    engine.send(spec.batch_id, Topic.PLUMBING_RELEASE, PlumbingRelease(act["plumbing"]))
                if "bench" in act:
                    engine.send(spec.batch_id, Topic.BENCH_RELEASE, BenchRelease(act["bench"]))
                observed = {"i": i, "held": held}
                if act.get("router_clear"):
                    (work / "router-clear").touch()   # the router reports its pools healthy
                if "resume_held" in act:
                    observed["resume_sent"] = engine.resume_held(f"case-{spec.batch_id[2:]}-{act['resume_held']}")
                if "case" in when:
                    observed.update(status=card.get("status"), reason=card.get("reason"))
                fakes["worker"].f.append("actions.log", observed)
            stop.wait(0.05)

    t = threading.Thread(target=actions, daemon=True)
    t.start()
    result = handle.get_result()
    stop.set()
    cards = report.load_cards(spec.batch_id)
    out = {"result": result, "cards": cards,
           "scorecard": report.scorecard(spec.batch_id, cards, allowlist=scenario.get("allowlist", ()),
                                         target_sealed=spec.target_sealed),
           "ledger": fakes["ledger"].snapshot()}
    (work / "result.json").write_text(json.dumps(out, sort_keys=True, indent=1))
    print("ENGINE-DONE", flush=True)
    os._exit(0)   # the fakes' state is on disk; skip DBOS's thread teardown


# ---- harness helpers for the engine tests --------------------------------------------------------

def uv_python():
    """The interpreter that has dbos; the suite runs under `uv run --with dbos==3.4.0`."""
    return sys.executable


class EngineRun:
    def __init__(self, scenario, workdir=None):
        self._tmp = None
        if workdir is None:
            self._tmp = tempfile.TemporaryDirectory()
            workdir = self._tmp.name
        self.work = Path(workdir)
        (self.work / "scenario.json").write_text(json.dumps(scenario))

    def spawn(self, **popen):
        import subprocess
        with open(self.work / "engine.out", "ab") as out:
            return subprocess.Popen([uv_python(), "-B", str(Path(__file__).resolve()), "engine", str(self.work)],
                                    stdout=out, stderr=subprocess.STDOUT, **popen)

    def run(self, timeout=120):
        p = self.spawn()
        try:
            p.wait(timeout=timeout)
        except Exception:
            p.kill()
            raise AssertionError("engine timed out:\n" + self.tail())
        if p.returncode != 0 or not (self.work / "result.json").exists():
            raise AssertionError(f"engine exit {p.returncode}:\n" + self.tail())
        return self.result()

    def result(self):
        return json.loads((self.work / "result.json").read_text())

    def tail(self, n=4000):
        p = self.work / "engine.out"
        return p.read_text(errors="replace")[-n:] if p.exists() else ""

    def worker_log(self):
        return _Files(self.work / "state" / "worker").lines("worker.log")

    def ledger_log(self):
        return _Files(self.work / "state" / "ledger").lines("ledger.log")

    def actions(self):
        """The scenario actions taken, in order, with the card status each found."""
        return _Files(self.work / "state" / "worker").lines("actions.log")

    def pool_log(self):
        return _Files(self.work / "state" / "pool").lines("pool.log")

    def starts(self, case=None):
        out = [x for x in self.worker_log() if x["op"] == "start"]
        return [x for x in out if case is None or x["key"].split("/")[0].endswith(f"-{case}")]

    def keys(self, case):
        """The (seq, step, attempt) of every started attempt of one case, in order."""
        return [tuple(x["key"].split("/")[1:]) for x in self.starts(case)]

    def close(self):
        if self._tmp is not None:
            self._tmp.cleanup()


# ---- self-checks of the fakes against the contract docstrings ------------------------------------

class FakesFollowTheContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ledger_labels_waste_and_replay(self):
        led = FakeLedger(self.root)
        led.open("b-x", 100)
        self.assertEqual(led.reserve("b-x", "case-x-1", "k1", 30, 50), Grant(30, LimitedBy.NOTHING))
        self.assertEqual(led.reserve("b-x", "case-x-1", "k1", 30, 50), Grant(30, LimitedBy.NOTHING))   # replay
        self.assertEqual(led.reserve("b-x", "case-x-1", "k2", 30, 50), Grant(20, LimitedBy.CASE))
        self.assertEqual(led.reserve("b-x", "case-x-2", "k3", 60, 60), Grant(50, LimitedBy.BATCH))
        led.settle("k1", Usage(paid_usd_micros=30), waste=True)   # waste never touches case money
        s = led.snapshot()
        self.assertEqual(s["cases"]["case-x-1"]["spent"], 0)
        self.assertEqual(s["batches"]["b-x"]["spent"], 30)
        led.settle_lost("k2")
        led.settle_lost("k2")
        s = led.snapshot()
        self.assertEqual((s["batches"]["b-x"]["waste"], s["cases"]["case-x-1"]["spent"]), (50, 0))
        led.raise_bound("b-x", 1000)
        self.assertEqual(led.reserve("b-x", "case-x-2", "k3", 60, 60), Grant(50, LimitedBy.BATCH))  # original

    def test_sealer_opens_only_with_its_scope_key(self):
        keys, sealer = FakeKeys(), FakeSealer()
        ref, ct = sealer.seal(keys.scope_key("case-x-1"), ArtifactKind.CASE_SNAPSHOT, b"plain")
        self.assertEqual(sealer.open(keys.scope_key("case-x-1"), ref, ct), b"plain")
        with self.assertRaises(ValueError):
            sealer.open(keys.scope_key("case-x-2"), ref, ct)
        ref2, _ = sealer.seal(keys.scope_key("case-x-2"), ArtifactKind.CASE_SNAPSHOT, b"plain")
        self.assertNotEqual(ref.digest, ref2.digest)

    def test_worker_protocol(self):
        from durable.contract import Step, StepInput
        fakes = build_fakes(self.root, {"default_dur": 0.05})
        spec, registry = seed_batch(fakes, {"batch_id": "b-x"})
        w, pool = fakes["worker"], fakes["pool"]
        lease = pool.acquire("case-x-1", spec.plumbing_version, spec.bench_version)
        si = StepInput("b-x", "case-x-1", 1, Step(StepKind.ADMIT), 1, spec.plumbing_version, spec.bench_version,
                       spec.inputs, None, 60.0, 5000, registry=registry)
        keys = {"case-x-1": fakes["keys"].scope_key("case-x-1"), "b-x": fakes["keys"].scope_key("b-x")}
        blobs = {f"{r.digest}.{r.kind.value}.age": fakes["store"].get_sealed("b-x", r) for r in (spec.inputs, registry)}
        self.assertIs(w.poll(lease, si).state, PollState.ABSENT)
        w.start(lease, si, keys, blobs)
        si2 = StepInput("b-x", "case-x-1", 1, Step(StepKind.ADMIT), 2, spec.plumbing_version, spec.bench_version,
                        spec.inputs, None, 60.0, 5000, registry=registry)
        w.start(lease, si2, keys, blobs)                                       # busy while attempt 1 is live
        self.assertIs(w.poll(lease, si).state, PollState.RUNNING)
        time.sleep(0.1)
        self.assertIs(w.poll(lease, si).result.outcome, Outcome.OK)
        self.assertEqual(w.poll(lease, si2).result.reason, "infra:attempt_busy")
        w.cancel(lease, si)                                                    # first wins: the OK stays
        self.assertIs(w.poll(lease, si).result.outcome, Outcome.OK)
        si3 = StepInput("b-x", "case-x-1", 1, Step(StepKind.ADMIT), 3, spec.plumbing_version, spec.bench_version,
                        spec.inputs, None, 60.0, 5000, registry=registry)
        w.cancel(lease, si3)                                                   # tombstone
        w.start(lease, si3, keys, blobs)
        self.assertEqual(w.poll(lease, si3).result.reason, "infra:cancelled")
        self.assertEqual([x["op"] for x in w.f.lines("worker.log")].count("ran"), 1)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "engine":
        engine_main(sys.argv[2])
    else:
        unittest.main()
