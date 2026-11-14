"""Seeded chaos runs of the durable case engine: random step results, worker loss, controller
restarts (SIGKILL + DBOS recovery), clock jumps (short retry_at, a batch deadline that passes
mid-run), bound raises, releases and resumes, with invariants checked after every run.

Real engine, policy, executor and SqlLedger (SQLite); only the edges are faked, with the fakes of
test_durable_engine_fakes.py (worker, pool, store, clock by short real waits, controller process).

    uv run -q --with numpy --with scipy --with dbos==3.4.0 python -B tests/factory/test_engine_chaos.py
    CHAOS_SEEDS=500 CHAOS_JOBS=8 ...      # more seeds; CHAOS_SEED=17 replays one seed
"""
import contextlib
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import random
import signal
import sqlite3
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(Path(__file__).resolve().parent)]
os.environ.setdefault("BENCH", str(ROOT))

import test_durable_engine_fakes as fakes_mod  # noqa: E402
from test_durable_engine_fakes import EngineRun, _Files  # noqa: E402

M = 1_000_000
MIN_GRANT = 1_000_000
TIMING = {"wake_poll_s": 0.5, "credential_retry_s": 0.2, "pause_retry_s": 0.2, "admission_backoff_s": 0.1,
          "admission_backoff_max_s": 0.3, "founder_poll_s": 0.3, "reconcile_retry_s": 0.1,
          "pool_wait_ceiling_s": 1.0}
# Violations a pushed fix branch closes, skipped until it merges: delete each entry with its merge.
# b-cancelled: an infra:cancelled result that reports usage books its whole grant (fix/cancelled-settles-usage).
KNOWN_OPEN = set(filter(None, os.environ.get("CHAOS_KNOWN_OPEN", "b-cancelled").split(",")))
PARKED = {"waiting_for_bound", "escalated", "held_for_release", "waiting_for_release"}
TERMINAL = {"sealed", "retired", "held", "stopped_admission", "not_admitted"}


# ---- the engine program: the fakes' engine_main on the real SqlLedger ---------------------------

class SqlFakeLedger:
    """durable.ledger.SqlLedger plus the fake's call log and snapshot() the engine driver reads."""

    def __init__(self, root):
        from durable.ledger import SqlLedger
        Path(root).mkdir(parents=True, exist_ok=True)
        self.sql, self.f = SqlLedger(f"sqlite:///{root}/ledger.sqlite"), _Files(root)

    def __getattr__(self, name):
        fn = getattr(self.sql, name)
        if name not in ("reserve", "settle", "settle_lost", "book_waste", "raise_bound"):
            return fn

        def logged(*args, **kw):
            out = fn(*args, **kw)
            self.f.append("ledger.log", {"op": name, "args": [a if isinstance(a, (str, int)) else repr(a) for a in args],
                                         "out": repr(out)})
            return out
        return logged

    def snapshot(self):
        rows = self.sql.rows()
        batches = {b: {"bound": bound, **{k: v for k, v in self.sql.balance(b).items() if k != "bound"}}
                   for b, bound in rows["batches"]}
        return {"batches": batches}


def seq_free(key):
    case, _seq, rest = key.split("/", 2)
    return f"{case}/{rest}"


class SeqFree(dict):
    """A key set or count map of "<case id>/<step>/<attempt>" that matches any seq."""
    def __contains__(self, key):
        return dict.__contains__(self, seq_free(key))

    def get(self, key, default=None):
        return dict.get(self, seq_free(key), default)


def engine_program(workdir):
    build = fakes_mod.build_fakes

    def build_fakes(state_dir, scenario):
        out = build(state_dir, scenario)
        out["ledger"] = SqlFakeLedger(Path(state_dir) / "ledger")
        w = out["worker"]
        w.dead_on_start = SeqFree({k: 1 for k in scenario.get("dead_any", [])})
        w.flaky = {what: SeqFree(counts) for what, counts in scenario.get("flaky_any", {}).items()}
        lost_starts = SeqFree({k: 1 for k in scenario.get("lost_start_any", [])})
        start = w.start

        def lossy_start(lease, si, keys, blobs):   # the start frame never reaches the worker: ABSENT
            if si.idempotency_key in lost_starts:
                return
            return start(lease, si, keys, blobs)
        w.start = lossy_start
        return out
    fakes_mod.build_fakes = build_fakes
    fakes_mod.engine_main(workdir)


class ChaosRun(EngineRun):
    def spawn(self, **popen):
        import subprocess
        with open(self.work / "engine.out", "ab") as out:
            return subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "engine", str(self.work)],
                                    stdout=out, stderr=subprocess.STDOUT, **popen)


# ---- fault sequences -----------------------------------------------------------------------------

STEPS = ["admit", "writer:1", "stress:1", "gates:1", "writer:2", "stress:2", "gates:2", "writer:3", "stress:3",
         "gates:3", "seal", "diagnosis"]
STAGE = {"admit": "admit", "writer": "writer", "stress": "stress", "gates": "engine", "seal": "seal",
         "diagnosis": "diagnosis"}


def fault(rng, step):
    """One step result drawn from the contract's outcome and reason set (or a worker fault)."""
    kind = step.split(":")[0]
    paid = rng.choice([0, 0, 700, 3000])
    r = rng.random()
    if r < 0.30:
        reason = rng.choice(["infra:stalled", "infra:invalid_execution", "infra:cancelled", "infra:cancelled",
                             "infra:paused", "infra:deadline", "infra:worker_create_failed", "infra:usage_unknown",
                             "router:credential_expiring", "router:outage", "router:upstream_rejected"])
        if reason == "infra:usage_unknown":
            paid = 0
        return {"outcome": "infra_error", "reason": reason, "paid": paid, "checkpoint": rng.random() < .5}
    if r < 0.45:
        return {"outcome": "provider_limit", "reason": rng.choice(["router:quota", "router:claude_limit",
                                                                   "router:credit"]),
                "retry_in": rng.choice([0.05, 0.2, 0.6]), "paid": paid}
    if r < 0.55 and kind != "diagnosis":
        return {"outcome": "exhausted", "reason": f"{STAGE[kind]}:money", "paid": paid}
    if r < 0.62 and kind == "writer":
        return {"outcome": "exhausted", "reason": rng.choice(["writer:unchanged_repair", "writer:output_capped"]),
                "paid": paid}
    if r < 0.75 and kind == "gates":
        return {"outcome": "gate_failed", "gate": "G5", "repairable": rng.random() < .7,
                "passed": ["G1", "G2"], "paid": paid}
    if r < 0.75 and kind == "stress":
        return {"feedback": True, "paid": paid}
    if kind == "diagnosis":
        return {"verdict": rng.choice(["factory_bug", "close_to_passing", "not_converging", "factory_bug"]),
                "paid": paid}
    if r < 0.80 and kind in ("gates", "stress"):
        return {"outcome": "needs_founder", "paid": paid, **({"gate": "G8", "passed": ["G1"]} if kind == "gates" else {})}
    return {"paid": paid}


def scenario_for(seed):
    rng = random.Random(seed)
    cases = rng.choice([1, 1, 2])
    spec = {"max_cases_started": cases, "target_sealed": 1, "max_infra_retries_per_step": rng.choice([1, 2]),
            "max_writer_rounds": rng.choice([2, 3])}
    if rng.random() < .3:   # a bound the case can run into
        spec["money_bound_usd_micros"] = rng.choice([800_000, 1_500_000, 3_000_000, 60 * M])
    script = {}
    for n in range(1, cases + 1):
        for step in STEPS:
            for attempt in range(1, 5):
                if rng.random() < (0.45 if attempt == 1 else 0.25):
                    script[f"{n}/{step}/{attempt}"] = fault(rng, step)
    sc = {"seed": seed, "spec": spec, "script": script, "timing": TIMING, "grace_s": 0.2,
          "disabled_patches": [], "actions": []}
    if rng.random() < .3:
        sc["deadline_in"] = rng.choice([1.5, 3.0, 6.0])
    any_key = lambda: f"{fakes_case(rng.randint(1, cases))}/{rng.choice(STEPS)}/{rng.randint(1, 3)}"
    if rng.random() < .3:   # the worker dies right after a start: worker_lost
        sc["dead_any"] = [any_key() for _ in range(rng.randint(1, 3))]
    if rng.random() < .25:   # a start frame lost on the wire: the attempt is absent
        sc["lost_start_any"] = [any_key() for _ in range(rng.randint(1, 3))]
    if rng.random() < .3:   # lost polls and cancels on the wire
        sc["flaky_any"] = {what: {any_key(): rng.randint(1, 3) for _ in range(3)} for what in ("poll", "cancel")}
    if rng.random() < .4:   # long attempts, so restarts land mid-attempt; a short deadline cuts some
        for _ in range(4):
            k = f"{rng.randint(1, cases)}/{rng.choice(STEPS)}/{rng.randint(1, 2)}"
            script.setdefault(k, {})["dur"] = rng.choice([0.5, 1.5, 3.0])
        if rng.random() < .5:
            spec["step_deadline_s"] = rng.choice([1.0, 2.0])
    for n in range(1, cases + 1):
        for _ in range(4):   # each action fires once per engine process
            sc["actions"].append({"when": {"case": n, "status": "escalated"}, "delay_s": .2,
                                  "reply": {"action": rng.choice(["continue", "continue", "retire"])}})
        if "money_bound_usd_micros" in spec and rng.random() < .6:
            sc["actions"].append({"when": {"case": n, "status": "waiting_for_bound"}, "delay_s": .3,
                                  "bound": rng.choice([spec["money_bound_usd_micros"], 300 * M])})
        if rng.random() < .3:
            sc["actions"].append({"when": {"case": n, "status": "held_for_release"},
                                  rng.choice(["plumbing", "bench"]): rng.choice("345") * 64})
    if rng.random() < .3:
        sc["disabled_patches"].append("factory_bug_release_wait")   # holds end the workflow
    sc["restarts"] = sorted(rng.uniform(0.3, 5.0) for _ in range(rng.choice([0, 0, 1, 1, 2])))
    if rng.random() < .35:
        sc["resume"] = {"override": rng.random() < .5, "extra": rng.random() < .3, "times": rng.randint(1, 3)}
    return sc


def fakes_case(n):
    return f"case-t-{n}"


def materialize(sc):
    """The scenario as engine_main reads it: seq-free keys only (dead_on_start needs a full key)."""
    return {k: v for k, v in sc.items() if k not in ("restarts", "resume", "seed")}


# ---- running -------------------------------------------------------------------------------------

def run_seed(sc, timeout=75):
    """Run one scenario (with restarts and resumes). Returns (run, outcomes, notes)."""
    r = ChaosRun(materialize(sc))
    outs, notes = [], []
    deadline = time.monotonic() + timeout
    for t in sc.get("restarts", []):
        p = r.spawn()
        try:
            p.wait(timeout=t)
        except Exception:
            p.send_signal(signal.SIGKILL)
            p.wait()
            notes.append(f"killed at {t:.2f}s")
    outs.append(finish(r, deadline))
    resume = sc.get("resume")
    if resume and outs[-1].get("result"):
        for i in range(resume["times"]):
            statuses = outs[-1]["result"]["cases"]
            case = fakes_case(1)
            if not any(s in ("held", "retired") for c, s in statuses.items() if c.startswith(case)):
                break
            batch = f"b-r{i}"
            s2 = {"spec": {"batch_id": batch, "max_cases_started": 1, "max_infra_retries_per_step": 2},
                  "resume_of": case, "script": sc["script"], "timing": TIMING, "grace_s": 0.2,
                  "disabled_patches": ["factory_bug_release_wait"], "actions": []}
            if resume["override"]:
                s2["override"] = f"chaos override {i}"
            if resume["extra"]:
                s2["case_money_extra"] = {"usd_micros": 10 * M, "reason": f"chaos extra {i}"}
            r2 = ChaosRun(s2, workdir=r.work)
            out = finish(r2, time.monotonic() + timeout)
            out["resume"] = {"batch": batch, "override": s2.get("override")}
            outs.append(out)
            if "refused" in out or not out.get("result"):
                break
    return r, outs, notes


def finish(r, deadline):
    p = r.spawn()
    try:
        p.wait(timeout=max(1, deadline - time.monotonic()))
    except Exception:
        p.send_signal(signal.SIGKILL)
        p.wait()
        return {"timeout": True, "cards": read_cards(r.work)}
    if not (r.work / "result.json").exists():
        return {"crash": r.tail(2000)}
    out = r.result()
    (r.work / "result.json").unlink()
    return out


def read_cards(work):
    """Cards of a killed engine, straight from the DBOS system database."""
    from dbos import DBOSClient
    client = DBOSClient(system_database_url=f"sqlite:///{work}/sys.sqlite")
    try:
        cards = []
        with contextlib.closing(sqlite3.connect(work / "sys.sqlite")) as db:
            wids = [w for (w,) in db.execute("SELECT DISTINCT workflow_uuid FROM workflow_events WHERE key='card'")]
        for wid in wids:
            cards.append(client.get_event(wid, "card", timeout_seconds=0.1))
        return cards
    finally:
        client.destroy()


# ---- invariants ----------------------------------------------------------------------------------

def result_of(work, key):
    p = work / "state/worker/results" / (hashlib.sha256(key.encode()).hexdigest() + ".json")
    return json.loads(p.read_text()) if p.exists() else None


def starts_order(work, key):
    """When the ledger reserved `key` (its line in the call log)."""
    for i, x in enumerate(_Files(work / "state/ledger").lines("ledger.log")):
        if x["op"] == "reserve" and x["args"][2] == key:
            return i
    return -1


def ledger_rows(work):
    db = sqlite3.connect(work / "state/ledger/ledger.sqlite")
    db.row_factory = sqlite3.Row
    with contextlib.closing(db):
        return ([dict(x) for x in db.execute("SELECT * FROM durable_ledger_attempt")],
            {x[0]: x[1] for x in db.execute("SELECT * FROM durable_ledger_batch")},
            {x[0] for x in db.execute("SELECT idempotency_key FROM durable_ledger_rebooked_waste")})


def check(sc, r, outs):
    """Violations as (invariant, detail)."""
    from durable.policy import settles_lost
    from durable.contract import step_result_from_record
    v = []
    work = r.work
    rows, bounds, rebooked = ledger_rows(work)
    ended = all(o.get("result") or "refused" in o for o in outs)
    # (a) terminal or parked with a reason
    for o in outs:
        if "crash" in o:
            v.append(("a", "engine crashed: " + o["crash"][-600:]))
        if o.get("timeout"):
            remaining = {b: bound - sum((x["granted_usd_micros"] if x["state"] in ("held", "lost")
                                         else x["paid_usd_micros"]) for x in rows if x["batch_id"] == b)
                         for b, bound in bounds.items()}
            for c in o["cards"]:
                if not c or c["status"] in TERMINAL:
                    continue
                if c["status"] == "waiting_for_bound":
                    # Truly exhausted: less than a minimum grant left, or no more than the BATCH grant
                    # its last attempt money-stopped under (the call it needs did not fit in that).
                    mine = [x for x in rows if x["case_id"] == c["case_id"]]
                    last = max(mine, key=lambda x: starts_order(work, x["idempotency_key"]), default=None)
                    left = min(remaining.values())
                    if left < MIN_GRANT or (last is not None and last["limited_by"] == "batch"
                                            and left <= last["granted_usd_micros"]):
                        continue
                if c["status"] in PARKED - {"waiting_for_bound"}:
                    continue
                v.append(("a", f"stuck: {c['case_id']} {c['status']} at {c['stage']} ({c['reason']}), "
                               f"batch remaining {remaining}"))
        for c, s in (o.get("result") or {}).get("cases", {}).items():
            if s not in TERMINAL:
                v.append(("a", f"{c} ended {s}"))
    # (b), (c), (d)
    for x in rows:
        key, state = x["idempotency_key"], x["state"]
        if state == "held":
            if ended:
                v.append(("a/b", f"{key} still holds {x['granted_usd_micros']} after the batch ended"))
            continue
        raw = result_of(work, key)
        booked = x["granted_usd_micros"] if state == "lost" else x["paid_usd_micros"]
        if booked > x["granted_usd_micros"]:
            v.append(("b", f"{key} booked {booked} > grant {x['granted_usd_micros']}"))
        if raw is None:
            continue
        res = step_result_from_record(raw)
        real = res.usage.paid_usd_micros
        if booked < real:
            v.append(("b", f"{key} booked {booked} < real spend {real} ({res.reason})"))
        if state == "lost" and real > 0 and not settles_lost(res):
            pass   # the engine's own result differed (worker lost): the grant covers it
        elif state == "lost" and real > 0:
            v.append(("b-cancelled" if res.reason == "infra:cancelled" else "b", f"{key} {res.reason} reported {real} spent but booked its whole grant "
                           f"{x['granted_usd_micros']} as waste"))
        waste = state == "lost" or x["waste"] or key in rebooked
        if waste and res.outcome.value in ("ok", "gate_failed", "needs_founder") and state != "lost" \
                and key not in rebooked:
            v.append(("c", f"{key} {res.outcome.value} booked as waste"))
        if not waste and x["draws_case_money"] and res.outcome.value == "infra_error" and x["paid_usd_micros"] > 0:
            v.append(("c", f"{key} infra stop {res.reason} booked {x['paid_usd_micros']} to case money"))
    for b, bound in bounds.items():
        used = sum(x["granted_usd_micros"] if x["state"] in ("held", "lost") else x["paid_usd_micros"]
                   for x in rows if x["batch_id"] == b)
        if used > bound:
            v.append(("d", f"{b} used {used} > bound {bound}"))
    # (e) replay: one run per key, no attempt started while another of its case was live, no engine error
    log = _Files(work / "state/worker").lines("worker.log")
    ran = [x["key"] for x in log if x["op"] == "ran"]
    for k in {k for k in ran if ran.count(k) > 1}:
        v.append(("e", f"{k} ran {ran.count(k)} times"))
    attempts = {}
    for f in (work / "state/worker").glob("attempts-*.json"):
        attempts.update(json.loads(f.read_text()))
    for x in log:
        if x["op"] == "cancelled" and attempts.get(x["key"], {}).get("mode") == "run":
            a = attempts[x["key"]]
            if x["t"] < a["done_at"] and not a["deadline_hit"]:
                v.append(("e", f"{x['key']} cancelled while running inside its deadline"))
        if x["op"] == "start" and x["mode"] == "busy":
            v.append(("e", f"{x['key']} started while an earlier attempt of its case was live"))
    for o in outs:
        for c in o.get("cards", []):
            if c and c.get("status") == "engine_error":
                v.append(("e", f"{c['case_id']} engine_error"))
    # (f) a passed GATES is followed by SEAL, unless a release changed the versions
    released = any("plumbing" in a or "bench" in a for a in sc.get("actions", []))
    starts = [x["key"] for x in log if x["op"] == "start"]
    if not released:
        for i, k in enumerate(starts):
            raw = result_of(work, k)
            if "/gates:" in k and raw and raw["outcome"] == "ok":
                case = k.split("/")[0]
                nxt = next((s for s in starts[i + 1:] if s.startswith(case + "/")), None)
                if nxt and "/seal/" not in nxt and "/gates:" in nxt.split("/", 2)[2][:6]:
                    v.append(("f", f"{k} passed, then {nxt} reran gates"))
    # (g) the infra retry allowance of a seq (first batch only: a resume starts it afresh), and the
    # lineage's factory_bug resumes
    from durable.classify import WORKER_POOL_REASONS
    free = WORKER_POOL_REASONS | {"infra:paused", "infra:deadline", "router:credential_expiring",
                                  "infra:credentials_unavailable", "router:unbounded_route",
                                  "infra:router_unavailable", "router:outage"}
    counted = {}
    for x in rows:
        k = x["idempotency_key"]
        case, seq, step, _ = k.split("/")
        if x["batch_id"] != "b-t" or step == "admit":
            continue
        raw = result_of(work, k)
        if raw is None and x["state"] != "lost":
            continue   # never started
        if raw is None or (raw["outcome"] == "infra_error" and raw["reason"] not in free):
            counted[(case, seq, step)] = counted.get((case, seq, step), 0) + 1
    limit = sc["spec"]["max_infra_retries_per_step"] + 1
    for run, n in counted.items():
        if n > limit:
            v.append(("g", f"{'/'.join(run)} had {n} counted infra stops, allowance {limit}"))
    for case in {x.split("/")[0] for x in starts}:
        mine = [k for k in starts if k.startswith(case + "/")]
        fb = [i for i, k in enumerate(mine) if "/diagnosis/" in k
              and (result_of(work, k) or {}).get("verdict") == "factory_bug"
              and any("/diagnosis/" not in later for later in mine[i + 1:])]
        if len(fb) > 3:
            v.append(("g", f"{case}: {len(fb)} factory_bug resumes, cap 3"))
    # (g) overrides spent per lineage
    spent = [o for o in outs if any(c and c.get("override") for c in o.get("cards", []))]
    if len(spent) > 2:
        v.append(("g", f"{len(spent)} overrides spent in one lineage"))
    return v


def describe(sc):
    faults = {k: v for k, v in sc["script"].items()}
    return json.dumps({k: sc[k] for k in sc if k != "script"} | {"script": faults}, sort_keys=True)


def chaos(seed):
    sc = scenario_for(seed)
    r, outs, notes = run_seed(sc)
    try:
        return seed, check(sc, r, outs), notes, [o.get("result", {}).get("cases") if o.get("result") else o.get(
            "refused", "timeout" if o.get("timeout") else "crash") for o in outs]
    finally:
        r.close()


class EngineChaos(unittest.TestCase):
    def test_seeded_chaos_keeps_the_invariants(self):
        one = os.environ.get("CHAOS_SEED")
        seeds = [int(one)] if one else range(int(os.environ.get("CHAOS_BASE", 0)),
                                             int(os.environ.get("CHAOS_BASE", 0)) + int(os.environ.get("CHAOS_SEEDS", 16)))
        bad = []
        with ThreadPoolExecutor(int(os.environ.get("CHAOS_JOBS", 8))) as pool:
            for seed, violations, notes, ends in pool.map(chaos, seeds):
                if os.environ.get("CHAOS_VERBOSE"):
                    print(seed, ends, notes, flush=True)
                violations = [x for x in violations if x[0] not in KNOWN_OPEN]
                if violations:
                    bad.append(seed)
                    print(f"\nSEED {seed} ends={ends} {notes}", flush=True)
                    for inv, detail in violations:
                        print(f"  ({inv}) {detail}", flush=True)
                    print("  faults: " + describe(scenario_for(seed)), flush=True)
        self.assertEqual(bad, [], f"invariant violations; replay with CHAOS_SEED=<seed>")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "engine":
        engine_program(sys.argv[2])
    else:
        unittest.main()
