"""Helper machines over the control VM (durable/helper_link.py): a GATES step's G6/G7 cheat checkpoints
run on real helpers leased through BoatPool on the stand-in Boat of test_durable_workers.py, results
sealed and verified, helpers released on success, failure and case stop, lease time accounted, flag off
changes nothing. The helper's `bin/checkpoint` is a stand-in; its input checks are the real ones."""
import sys
from pathlib import Path as _P
_ROOT = _P(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "tests/factory"), str(_ROOT / "factory"), str(_ROOT / "bin"), str(_ROOT / "tests/bench")]
import json, os, subprocess, tempfile, threading, time, types, unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault("BENCH", str(_ROOT))
import checkpoint_evidence
import run
import test_durable_workers as support
from test_helper_machines import write_checkpoint
from durable import helper_link, helpers, workers as W
from durable.channel import BoatChannel, blob_name
from durable.contract import ArtifactKind as K, PollState, Ref, Step, StepInput, StepKind

STANDIN = f'''
import os, sys, json
os.environ["BENCH"] = {str(_ROOT)!r}
sys.path[:0] = [{str(_ROOT / "factory")!r}, {str(_ROOT / "bin")!r}]
from pathlib import Path
from durable import helper_link
sys.path.insert(0, {str(_ROOT / "tests/factory")!r})
sys.path.insert(0, {str(_ROOT / "tests/bench")!r})
from test_helper_machines import write_checkpoint
frame = json.loads(sys.stdin.read())
if frame["job"].get("kind") == "try":
    sys.path.insert(0, {{TRYDIR!r}})
    import standin_try
    print(json.dumps(standin_try.serve(frame))); sys.exit(0)
def fake(job):
    name = Path(job["guard_at"][1]).name
    case = Path.home() / helper_link.CASE_DIR / frame["lease"]
    with open({{SEEN!r}}, "a") as f:
        f.write(json.dumps([job["label"], [p.name for p in helper_link._scenarios(job, case)]]) + "\\n")
    die = Path({{DIE!r}})
    if name == "b" and die.exists():
        die.unlink(); os._exit(9)   # the helper is lost mid-job, once
    out = write_checkpoint(Path.home() / "ckpt" / name, job["runs"], name == "b")
    if name == "a" and Path({{INVALID!r}}).exists():   # a batch that ran but is not a valid measurement
        r = json.loads((out / "01.json").read_text()); r["checker"] = {{"valid": False}}
        (out / "01.json").write_text(json.dumps(r))
    return out
print(json.dumps(helper_link.serve(frame, run=fake)))
'''


TRY_STANDIN = '''
"""Helper side of a G10 try on the stand-in Boat: the real helper_link check, context rebuild, run.hosted_try,
spend reconciliation and seal. The model call, pilot wall, bench and scorer are stand-ins. The model books
its spend into the context's ledger the way model_call does (a settled reservation and its event)."""
import json, os, sys, uuid
from pathlib import Path
from unittest.mock import patch
import run, budget, checkpoint_evidence
from durable import helper_link, helpers
sys.path.insert(0, {TESTS!r})
from test_helper_machines import write_checkpoint
TMP = Path({TMP!r})

def author(c, role, name, exposure, i, make_ws):
    if i == 3 and (TMP / "die-try").exists():
        (TMP / "die-try").unlink(); os._exit(9)   # the helper is lost mid-try, once, before any model call
    lease, event, invocation = f"lease-{uuid.uuid4().hex}", str(uuid.uuid4()), str(uuid.uuid4())
    funding = budget.available_invocation_funding(c.ledger, c.engine)   # bounded by the try's authority
    with budget.ledger_transaction(c.ledger) as ledger:
        ledger.setdefault("invocation_reservations", {})[lease] = {
            "schema_version": 1, "invocation_id": invocation, "operation_id": str(uuid.uuid4()), "lease_id": lease,
            "route": "r", "account": None, "billing": "paid", "pool": "p", "family": "f",
            "call_name": f"easy-calibrator-{name}-{i}", "parent_call_name": None, "maximum_usd": "1.000000000",
            "state": "settled", "event_ids": [event], "launched": True}
        ledger["events"].append({"id": event, "cost": 0.25, "lease_id": lease, "invocation_id": invocation,
                                 "configured_model": c.models[role][0], "role": "easy_calibrator", "funding": funding})
        ledger["cost"] += 0.25; ledger["calls"] += 1
    c.card.setdefault("models_used", {})[f"easy-calibrator-{name}-{i}"] = c.models[role][0]
    if i == 2 and (TMP / "stop").exists(): raise run.BudgetError("quota:x")   # a provider stop after spending
    ws = make_ws(); (ws / "guard").mkdir(parents=True); (ws / "guard/db.sql").write_text(f"-- try {i}")
    return ws, None

def checkpoint(c, scenarios, guard, runs, seed, label, **kw):
    out = write_checkpoint(Path(c.work) / f"ck-{seed}", runs, seed % 2 == 0)
    p = type("P", (), {"returncode": 0, "stderr": "", "stdout": checkpoint_evidence.RECEIPT_PREFIX + json.dumps(
        {"version": 1, "path": str(out / "checkpoint.json"), "requested_runs": runs})})
    return checkpoint_evidence.read_completed(p, runs, label)[:2]

def delivery(case, bench, ws, **kw): ws.mkdir(parents=True, exist_ok=True); (ws / "DELIVERY.md").write_text("d")

def identity(c, role, exposure, *, runs=None, bench=None):
    a = c.args
    return {"case": run.case_hash(c), "model": c.models[role], "seed": c.seed, "runs": runs, "minutes": a.calibrator_minutes,
            "role_calls": a.max_role_calls, "limits": [a.max_cost, a.max_total_calls], "exposure": exposure, "slot": 0}

def serve(frame):
    with patch.object(run, "BENCH", TMP / "bench"), patch.object(run, "prompt", lambda *a: "p"), \
         patch.object(run, "prepare_delivery", delivery), patch.object(run, "bench_manifest", lambda: "m"), \
         patch.object(run, "make_pilots", lambda c, ids, concurrent: open(TMP / "pilots", "a").write(json.dumps(ids) + "\\n")), \
         patch.object(run, "_author_try", author), patch.object(run, "try_checkpoint", checkpoint), \
         patch.object(run, "calibration_identity", identity), patch.object(helper_link, "_prepare", lambda w: None), \
         patch.object(run, "verdicts", lambda c, recs: [{"clean": True, "solved": True}] * len(recs)):
        return helper_link.serve(frame)
'''


def try_standin(tmp):
    return TRY_STANDIN.replace("{TESTS!r}", repr(str(_ROOT / "tests/factory"))).replace("{TMP!r}", repr(str(tmp)))


class LockedPool(W.BoatPool):
    """The stand-in Boat's inventory file is not safe for two creates at once; the real one is."""
    lock = threading.Lock()

    def acquire(self, *a, **k):
        with self.lock: return super().acquire(*a, **k)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.h = support.Harness(self)
        self.bench = self.h.benches["bench-env"]
        self.pool = LockedPool(self.h.tmp / "state-t", self.h.store, "wp2-test", boat=self.h.boat, steps=support.TEST_STEPS,
                               ready_timeout=5, poll_interval=0.05, delete_timeout=5)
        self.case_id = support.CASE
        self.lease = self.pool.acquire(self.case_id, self.h.plumbing, self.bench)
        self.worker = W.boat_id(self.lease.worker_id)
        self.home = self.h.home(self.worker)
        self.die = self.h.tmp / "die"
        self.script = self.h.tmp / "standin_helper.py"
        self.invalid = self.h.tmp / "invalid"
        self.seen = self.h.tmp / "seen.jsonl"
        self.trydir = self.h.tmp / "trydir"; self.trydir.mkdir()
        (self.trydir / "standin_try.py").write_text(try_standin(self.trydir))
        self.script.write_text(STANDIN.replace("{DIE!r}", repr(str(self.die))).replace("{INVALID!r}", repr(str(self.invalid)))
                               .replace("{SEEN!r}", repr(str(self.seen))).replace("{TRYDIR!r}", repr(str(self.trydir))))
        self.si = StepInput(batch_id="b-wp2-test", case_id=self.case_id, seq=1, step=Step(StepKind.GATES, 1), attempt=1,
                            plumbing_version=self.h.plumbing, bench_version=self.bench, inputs=Ref(format(1, "064x"), K.INPUTS),
                            snapshot=Ref(format(2, "064x"), K.CASE_SNAPSHOT), deadline_s=60.0, money_ceiling_usd_micros=1)
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.case = self.tmp / "case"
        for name in ("a", "b", "c"):
            (self.case / "guards/cheats" / name).mkdir(parents=True)
            (self.case / "guards/cheats" / name / "g.js").write_text(name)
        (self.case / "base").mkdir(); (self.case / "base/x").write_text("x"); (self.case / "case.json").write_text("{}")
        self.work = self.tmp / "work"; self.work.mkdir()
        self.guards = sorted((self.case / "guards/cheats").iterdir())
        self.c = types.SimpleNamespace(case=self.case, work=self.work, seed=5, card={}, manifest0=None,
                                       args=types.SimpleNamespace(runs=3, helper_workers=2, bench_workers=1))
        self.root = self.home / helper_link.spool_rel(self.si.idempotency_key)

    def broker(self, **kw):
        kw = {"per_case": 2, "total": 2, "tick_s": 0.1, "job_timeout_s": 120, "ledger_dir": self.h.tmp / "ledger",
              "command": (sys.executable, "-B", str(self.script)), **kw}
        b = helper_link.Broker(self.pool, self.h.boat, **kw)
        self.addCleanup(b.finish, self.si)
        self.assertTrue(b.prepare(self.worker, self.si))
        b.watch(self.worker, self.si)
        return b

    def attach(self, b):
        config = helper_link.read_config(self.root)
        self.c.args.helper_workers, self.c.args.helper_min_per_copy = config["cap"], config["min_per_copy"]
        self.c.helper_pool = helper_link.SpoolPool(self.root, self.case, job_timeout_s=config["job_timeout_s"], poll_s=0.1)

    def serial(self):
        def checkpoint(c, scenarios, guard, runs, seed, label, **kw):
            out = write_checkpoint(self.tmp / f"s-{guard.name}", runs, guard.name == "b")
            p = types.SimpleNamespace(returncode=0, stderr="", stdout=checkpoint_evidence.RECEIPT_PREFIX + json.dumps(
                {"version": 1, "path": str(out / "checkpoint.json"), "requested_runs": runs}))
            s, r, _ = checkpoint_evidence.read_completed(p, runs, label)
            return s, r
        return checkpoint

    def cheats(self):
        with patch.object(run, "checkpoint", side_effect=self.serial()) as cp, patch.object(run, "case_budget_boundary"), \
             patch.object(run, "verdicts", wraps=run.verdicts) as v:
            out = run.cheat_runs(self.c, 5, "g6", guards=self.guards)
        return out, cp.call_count, [x.args[1] for x in v.call_args_list]

    def helper_boats(self):
        return [r["id"] for r in self.h.inventory() if r["id"] != self.worker]

    def ledger(self):
        path = self.h.tmp / "ledger" / f"{self.case_id}.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def test_g6_cheats_run_on_leased_helpers_with_serial_verdicts(self):
        self.c.args.helper_workers = 0
        (serial, total), _, serial_inputs = self.cheats()
        b = self.broker(); self.attach(b)
        (got, total2), local, inputs = self.cheats()
        self.assertEqual((got, total2, local), (serial, total, 0))   # nothing ran on the case worker
        self.assertEqual(inputs, serial_inputs)                      # same records into verdicts()
        events = [e["event"] for e in self.ledger()]
        self.assertGreaterEqual(events.count("lease"), 1)
        self.assertEqual(events.count("lease"), events.count("release"))
        self.assertTrue(all(e["seconds"] >= 0 for e in self.ledger() if e["event"] == "release"))
        self.assertEqual(self.helper_boats(), [])                    # every helper deleted
        cases = [r["name"] for r in self.h.inventory()]
        self.assertEqual(len(cases), 1)
        mine = [json.loads(l) for l in (self.work / "helper-ledger.jsonl").read_text().splitlines()]
        self.assertEqual(sum(e["event"] == "job" and e["ok"] for e in mine), 3)

    def test_dead_helper_requeues_only_its_job_and_is_released(self):
        self.die.write_text("")
        b = self.broker(); self.attach(b)
        (got, total), local, _ = self.cheats()
        self.assertEqual((got, total, local), (1, 3, 0))
        mine = [json.loads(l) for l in (self.work / "helper-ledger.jsonl").read_text().splitlines()]
        self.assertEqual(sum(e["event"] == "job" and not e["ok"] for e in mine), 1)
        self.assertTrue(any(e["event"] == "release" and e["dead"] for e in mine))
        self.assertEqual(self.helper_boats(), [])

    def test_global_cap_bounds_helpers_and_the_rest_still_runs(self):
        b = self.broker(per_case=3, total=1); self.attach(b)
        self.c.args.helper_workers = 3
        (got, total), local, _ = self.cheats()
        self.assertEqual((got, total, local), (1, 3, 0))
        self.assertEqual(sum(e["event"] == "lease" for e in self.ledger()), 1)   # never two helpers at once
        self.assertEqual(self.helper_boats(), [])

    def test_case_stop_releases_a_helper_the_case_worker_still_holds(self):
        b = self.broker(); self.attach(b)
        handle = self.c.helper_pool.lease()
        self.assertEqual(len(self.helper_boats()), 1)
        b.finish(self.si)                       # the attempt ended or was cancelled
        self.assertEqual(self.helper_boats(), [])
        self.assertEqual([e["event"] for e in self.ledger()], ["lease", "release"])

    def test_quiet_attempt_is_released_after_the_idle_time(self):
        b = self.broker(idle_s=3); self.attach(b)
        polling = threading.Event()
        def poll():   # the channel's polls, while the lease is being provisioned
            while not polling.wait(0.5): b.watch(self.worker, self.si)
        threading.Thread(target=poll, daemon=True).start()
        self.c.helper_pool.lease()
        polling.set()
        self.assertEqual(len(self.helper_boats()), 1)
        end = time.monotonic() + 20
        while self.helper_boats() and time.monotonic() < end: time.sleep(0.2)
        self.assertEqual(self.helper_boats(), [])

    def test_orphan_helpers_are_deleted_after_a_controller_restart(self):
        b = self.broker(); self.attach(b)
        self.c.helper_pool.lease()
        self.assertEqual(len(self.helper_boats()), 1)
        fresh = helper_link.Broker(self.pool, self.h.boat)
        fresh.release_orphans()
        self.assertEqual(self.helper_boats(), [])
        self.assertEqual(len(self.h.inventory()), 1)    # the case worker is not a helper

    def test_claim_of_a_gone_controller_is_answered_as_lost(self):
        b = self.broker()
        (self.root / "req").mkdir(parents=True, exist_ok=True)
        (self.root / "req/L9.json").write_text(json.dumps({"op": "lease"}))
        (self.root / "req/L9.claim").write_text("an-older-controller")
        end = time.monotonic() + 10
        while not (self.root / "res/L9.json").exists() and time.monotonic() < end: time.sleep(0.1)
        self.assertEqual(json.loads((self.root / "res/L9.json").read_text()), {"ok": False, "error": "relay_lost"})
        self.assertEqual(self.helper_boats(), [])

    def test_helper_with_other_inputs_refuses(self):
        b = self.broker(); self.attach(b)
        (self.case / "guards/cheats/a/g.js").write_text("changed after the case worker built its jobs")
        handle = self.c.helper_pool.lease()
        job = helpers.make_job(case=run.case_hash(self.c), guard=helpers._tree(self.guards[0]),
                               scenarios=[helpers._tree(self.case / "base")], bench=None, release="stale", runs=3, seed=5,
                               label="l", guard_at=["case", "guards/cheats/a"])
        with self.assertRaises(helpers.HelperDied):
            self.c.helper_pool.run(handle, job, b"k" * 32)
        self.c.helper_pool.release(handle, True)

    def test_machine_minimum_per_copy(self):
        mine = {"cpus": 4, "mem_gib": 8}
        self.assertTrue(helpers.fits(mine, helpers.need_for({"cpus": 2, "mem_gib": 4}, 2)))
        self.assertFalse(helpers.fits(mine, helpers.need_for({"cpus": 2, "mem_gib": 4}, 3)))
        self.assertFalse(helpers.fits({"cpus": 4, "mem_gib": None}, helpers.need_for({"cpus": 1, "mem_gib": 1}, 1)))
        self.assertFalse(helpers.fits({"cpus": 8, "mem_gib": 8}, mine))      # exact stays exact without a minimum
        self.assertEqual(helpers.need_for(None, 2, own=mine), mine)
        job = helpers.make_job(case="c", guard={}, scenarios=[], bench=None, release="r", runs=1, seed=1, label="l",
                               machine=helpers.need_for({"cpus": 1, "mem_gib": 1}, 1))
        sealed = helpers.execute(job, b"k" * 32, check=lambda j: None, machine=lambda: {"cpus": 3, "mem_gib": 2},
                                 run=lambda j: write_checkpoint(self.tmp / "m", 1, True))
        helpers.open_sealed(b"k" * 32, job, sealed)
        with self.assertRaises(helpers.HelperRefused):
            helpers.execute(job, b"k" * 32, check=lambda j: None, machine=lambda: {"cpus": 1, "mem_gib": 0},
                            run=lambda j: write_checkpoint(self.tmp / "m2", 1, True))

    def test_flag_off_changes_nothing(self):
        from durable.worker_step import Worker
        c = types.SimpleNamespace(args=types.SimpleNamespace(helper_workers=0), case=self.case)
        Worker(self.home).bind_helpers(self.si, c)
        self.assertFalse(hasattr(c, "helper_pool"))
        self.assertEqual(c.args.helper_workers, 0)
        channel = BoatChannel(types.SimpleNamespace(), keys=None, sealer=None, boat=self.h.boat)
        self.assertIsNone(channel.helpers)
        self.assertFalse((self.root / "config.json").exists())

    def test_worker_binds_helpers_only_when_the_control_side_set_up_a_spool(self):
        from durable.worker_step import Worker
        b = self.broker()
        c = types.SimpleNamespace(args=types.SimpleNamespace(helper_workers=0), case=self.case)
        Worker(self.home).bind_helpers(self.si, c)
        self.assertEqual((c.args.helper_workers, type(c.helper_pool).__name__), (2, "SpoolPool"))
        other = types.SimpleNamespace(args=types.SimpleNamespace(helper_workers=0), case=self.case)
        Worker(self.home).bind_helpers(StepInput(**{**self.si.__dict__, "step": Step(StepKind.WRITER, 1)}), other)
        self.assertFalse(hasattr(other, "helper_pool"))   # only GATES

    def test_channel_prepares_on_gates_start_and_finishes_on_done(self):
        calls = []
        class Spy:
            def prepare(s, worker, si): calls.append(("prepare", worker))
            def watch(s, worker, si): calls.append(("watch", worker))
            def finish(s, si): calls.append(("finish",))
        channel = BoatChannel(types.SimpleNamespace(), keys=None, sealer=None, boat=self.h.boat, helpers=Spy())
        channel.start(self.lease, self.si, {self.case_id: b"k" * 32}, {})
        self.assertEqual(calls, [("prepare", self.worker)])
        writer = StepInput(**{**self.si.__dict__, "step": Step(StepKind.WRITER, 1)})
        channel.start(self.lease, writer, {self.case_id: b"k" * 32}, {})
        self.assertEqual(len(calls), 1)

    # ---- review findings

    def test_lease_seconds_are_booked_on_the_case_card_and_stop_at_the_budget(self):
        b = self.broker(); self.attach(b)
        self.c.args.helper_usd_per_hour = 10.0
        self.cheats()
        card = self.c.card["helper_lease"]
        self.assertGreaterEqual(card["leases"], 1)
        self.assertEqual(card["usd"], round(card["seconds"] / 3600 * 10, 6))
        self.assertEqual(self.c.card["case_budget"]["helper_lease_usd"], card["usd"])
        for e in self.ledger():
            if e["event"] == "release": self.assertEqual(e["seconds"] >= 0, True)
        mine = [json.loads(l) for l in (self.work / "helper-ledger.jsonl").read_text().splitlines()]
        self.assertTrue(all(e["machine"]["cpus"] for e in mine if e["event"] == "job" and e["ok"]))   # class beside each result
        (self.work / "helper-ledger.jsonl").write_text(json.dumps({"event": "release", "seconds": 3600 * 6}) + "\n")   # $60 > $50
        from budget import BudgetError
        with self.assertRaises(BudgetError): helpers.book_lease(self.c)
        self.c.args.helper_usd_per_hour = None   # unpriced: seconds only, never a stop
        helpers.book_lease(self.c)
        self.assertEqual(self.c.card["helper_lease"], {"leases": 1, "seconds": 21600.0})

    def test_helper_code_is_part_of_the_verdict_identity(self):
        from durable.checkpoints import VERDICT_CODE
        import gate_state
        self.assertIn("durable/helper_link.py", VERDICT_CODE)
        for gate in ("G5", "G6", "G7", "G10"): self.assertIn("factory/durable/helper_link.py", gate_state.STAGE_DEPENDENCIES[gate])

    def test_invalid_helper_batch_is_charged_to_the_serial_retry_budget_not_retried_on_helpers(self):
        self.invalid.write_text("")
        b = self.broker(); self.attach(b)
        (got, total), local, _ = self.cheats()
        self.assertEqual((got, total, local), (1, 3, 1))   # only the invalid guard ran locally
        mine = [json.loads(l) for l in (self.work / "helper-ledger.jsonl").read_text().splitlines()]
        self.assertEqual(sum(e["event"] == "job" and not e["ok"] for e in mine), 1)   # no second helper attempt
        rows = json.loads((self.work / "infra-attempts.json").read_text()).values()
        self.assertEqual([r["invalid_attempts"] for r in rows], [1])
        self.assertEqual(self.helper_boats(), [])

    def test_a_recreated_watch_does_not_rerun_a_request_this_controller_already_handled(self):
        b = self.broker(); self.attach(b)
        self.c.helper_pool.lease()
        b.finish(self.si)
        (self.root / "req/L1.json").write_text(json.dumps({"op": "lease"}))   # consumed by the case worker; files left behind
        (self.root / "req/L1.claim").write_text(b.instance)
        (self.root / "res/L1.json").unlink(missing_ok=True)
        b.watch(self.worker, self.si)
        time.sleep(1.5)
        self.assertFalse((self.root / "res/L1.json").exists())
        self.assertEqual(sum(e["event"] == "lease" for e in self.ledger()), 1)
        self.assertEqual(self.helper_boats(), [])

    def test_the_real_helper_command_runs_checkpoint_with_the_job_env_and_prepares_once(self):
        bench = self.tmp / "bench"; (bench / "bin").mkdir(parents=True)
        seen = self.tmp / "seen.json"
        script = bench / "bin/checkpoint"
        script.write_text(f"#!{sys.executable}\n" + """
import json, os, sys, time
from pathlib import Path
if os.environ.get("SLOW"): time.sleep(5)
a = sys.argv[1:]
out = Path.home() / "ck"; out.mkdir(exist_ok=True)
for i in range(1, int(a[a.index("--runs") + 1]) + 1): (out / f"{i:02}.json").write_text("{}")
(out / "checkpoint.json").write_text("{}")
Path(%r).write_text(json.dumps({"argv": a, "judge": os.environ.get("UNBUG_JUDGE"), "slot": os.environ.get("UNBUG_FACTORY_SLOT")}))
print("UNBUG_CHECKPOINT=" + json.dumps({"version": 1, "path": str(out / "checkpoint.json")}))
""" % str(seen))
        script.chmod(0o755)
        home = self.tmp / "home"; home.mkdir()
        (self.case / "scenarios/s1").mkdir(parents=True); (self.case / "scenarios/s1/key.json").write_text("{}")
        base, s1 = helpers._tree(self.case / "base"), helpers._tree(self.case / "scenarios/s1")
        job = helpers.make_job(case="c", guard={}, scenarios=[base], bench=None, release="r", runs=3, seed=7, label="lbl",
                               guard_at=["case", "guards/cheats/a"], env={"UNBUG_JUDGE": None, "UNBUG_FACTORY_SLOT": "3"}, timeout_s=60)
        import factory_pool
        with patch.object(run, "BENCH", bench), patch.object(factory_pool, "prepare", return_value=True) as prep, \
                patch.dict(os.environ, {"HOME": str(home), "UNBUG_JUDGE": "leaked"}):
            out = helper_link._run(job, self.case)
            helper_link._run(job, self.case)
            self.assertEqual(sorted(p.name for p in out.glob("*.json")), ["01.json", "02.json", "03.json", "checkpoint.json"])
            got = json.loads(seen.read_text())
            self.assertEqual((got["judge"], got["slot"]), (None, "3"))   # exactly the case worker's, no default
            self.assertEqual(got["argv"][got["argv"].index("--seed") + 1], "7")
            self.assertIn("--stress", got["argv"])
            self.assertEqual(prep.call_count, 1)
            self.assertEqual([got["argv"][i + 1] for i, x in enumerate(got["argv"]) if x == "--scenario"], [str(self.case / "base")])
            helper_link._run({**job, "scenarios": [helpers.digest_of(base), helpers.digest_of(s1)]}, self.case)   # a G5 key job
            got = json.loads(seen.read_text())
            self.assertEqual([got["argv"][i + 1] for i, x in enumerate(got["argv"]) if x == "--scenario"],
                             [str(self.case / "base"), str(self.case / "scenarios/s1")])
            for bad in ([helpers.digest_of(s1)], [helpers.digest_of(base), "0" * 64], []):   # base first, every one known
                with self.assertRaises(helpers.HelperRefused): helper_link._run({**job, "scenarios": bad}, self.case)
            with patch.dict(os.environ, {"SLOW": "1"}), self.assertRaises(subprocess.TimeoutExpired):
                helper_link._run({**job, "timeout_s": 0.5}, self.case)

    def test_the_real_helper_command_starts_and_refuses_stale_inputs(self):
        job = helpers.make_job(case="c", guard={}, scenarios=[], bench=None, release="stale", runs=1, seed=1, label="l",
                               guard_at=["case", "guards/cheats/a"])
        frame = json.dumps({"job": job, "key": "00" * 32, "lease": "L1"})
        p = subprocess.run([sys.executable, "-B", "factory/durable/helper_link.py", "run"], input=frame, text=True, cwd=_ROOT,
                           capture_output=True, env={**os.environ, "BENCH": str(_ROOT), "HOME": str(self.tmp)})
        self.assertEqual((p.returncode, p.stderr.strip()), (1, "HelperRefused"))   # imports and sys.path resolve; the check ran

    # --- G5 checkpoints and G10 tries over the transport ---------------------------------------------

    def test_g5_reference_and_key_checkpoints_run_on_helpers_and_a_dead_helper_requeues_one(self):
        (self.case / "guards/reference").mkdir(parents=True); (self.case / "guards/reference/g.js").write_text("ref")
        (self.case / "scenarios/s1/examples/b").mkdir(parents=True); (self.case / "scenarios/s1/examples/b/g.js").write_text("key")
        (self.case / "scenarios/s1/key.json").write_text(json.dumps({"expected_judge": {"b": {}}}))
        self.c.args.scenario_runs = 2
        self.die.write_text("")   # the helper running the key check ("b") dies once
        b = self.broker(); self.attach(b)
        with patch.object(run, "case_budget_boundary"):
            shards = run.g5_shards(self.c)
        self.assertEqual(sorted(shards), ["reference", "s1/b"])
        self.assertEqual((len(shards["reference"][1]), len(shards["s1/b"][1])), (3, 2))
        mine = [json.loads(l) for l in (self.work / "helper-ledger.jsonl").read_text().splitlines()]
        self.assertEqual([e["ok"] for e in mine if e["event"] == "job"].count(False), 1)   # only the key job went round again
        self.assertEqual([e["ok"] for e in mine if e["event"] == "job"].count(True), 2)
        seen = {tuple(x) for x in (json.loads(l) for l in self.seen.read_text().splitlines()) for x in [(x[0], tuple(x[1]))]}
        self.assertEqual(seen, {("g5-reference", ("base",)), ("g5-key", ("base", "s1"))})   # the helper's own case tree
        self.assertEqual(self.helper_boats(), [])

    def try_context(self):
        c = run.Ctx()
        c.work, c.case, c.case_id = self.work, self.case, self.case_id
        for n in ("promise.md", "contestant.md"): (self.case / n).write_text("synthetic contract")
        a = run.argument_parser().parse_args(["--source", "port"])
        a.pilot_tries, a.pilot_runs, a.calibrator_minutes, a.helper_workers, a.bench_workers = 3, 2, 30, 0, 1
        c.args, c.seed, c.card, c.pilot_passes, c.manifest0 = a, 7, {}, [], "m"
        c.models = {"easy_calibrator": ["synthetic/easy"], "reviewers": [["synthetic/reviewer"]]}
        c.ledger = self.work / "continuation-budget.json"
        (self.trydir / "bench").mkdir(exist_ok=True)
        c.local = []
        def author(c_, role, name, exposure, i, make_ws):
            c.local.append(i); raise AssertionError("authored on the case worker")
        def delivery(case, bench, ws, **kw): ws.mkdir(parents=True, exist_ok=True); (ws / "DELIVERY.md").write_text("d")
        standin = {}
        exec(compile(try_standin(self.trydir), "standin", "exec"), standin)
        stack = __import__("contextlib").ExitStack(); self.addCleanup(stack.close)
        for n, v in [("BENCH", self.trydir / "bench"), ("_author_try", author), ("prompt", lambda *a: "p"),
                     ("prepare_delivery", delivery), ("case_budget_boundary", lambda c_: None),
                     ("calibration_identity", standin["identity"]),
                     ("helper_try_authority", lambda c_, role, exposure, n: (__import__("decimal").Decimal("1"), n)),
                     ("verdicts", lambda c_, recs: [{"clean": True, "solved": True}] * len(recs))]:
            stack.enter_context(patch.object(run, n, v))
        return c

    def test_g10_tries_run_on_helpers_spend_is_booked_once_and_a_stop_propagates(self):
        from budget import case_spending
        (self.trydir / "die-try").write_text(""); (self.trydir / "stop").write_text("")
        c = self.try_context()
        ids = json.loads((self.h.boat_dir / "ids.json").read_text())
        self.h.ids(ids + [f"bx_extra{n:03}" for n in range(4)])   # two dispatches need more machines than the stand-in's four
        b = self.broker(); self.attach(b); c.helper_pool = self.c.helper_pool
        c.args.helper_workers = 2
        with self.assertRaises(run.BudgetError) as raised: run.calibrate(c, "easy_calibrator")
        self.assertEqual(str(raised.exception), "quota:x")                       # the helper's stop, at try 2's turn
        label = __import__("calibration").interruption_label(run.BudgetError("quota:x"))   # labelled on the helper, as serial
        self.assertEqual(c.card["calibration_interruptions"], {"easy_calibrator": {label: 1}})
        mine = [json.loads(l) for l in (self.work / "helper-ledger.jsonl").read_text().splitlines()]
        self.assertEqual([e["ok"] for e in mine if e["event"] == "job"].count(False), 1)   # the dead helper's try 3, once
        ledger = json.loads(c.ledger.read_text())
        self.assertEqual(len(ledger["events"]), 3)                                # tries 1, 2 (stopped) and 3: each once
        self.assertEqual(case_spending(ledger)["total_spent_usd"], 0.75)
        self.assertEqual({e["funding"] for e in ledger["events"]}, {"1.000000000"})   # each helper held to its authority
        self.assertEqual(len(c.card["models_used"]), 3)
        self.assertEqual(json.loads((self.trydir / "pilots").read_text().splitlines()[0]), [["pilot", 0]])
        self.assertEqual(c.local, [])
        self.assertEqual(self.helper_boats(), [])
        # resume after the stop: try 3 comes from its saved result and is not booked again; try 2 runs anew
        (self.trydir / "stop").unlink()
        run.calibrate(c, "easy_calibrator")
        ledger = json.loads(c.ledger.read_text())
        self.assertEqual((len(ledger["events"]), case_spending(ledger)["total_spent_usd"]), (4, 1.0))
        self.assertEqual([r["try"] for r in json.loads((self.work / "easy_calibrator/results.json").read_text())], [1, 2, 3])
        self.assertEqual(c.local, [])
        self.assertEqual(self.helper_boats(), [])

    def test_spend_import_is_idempotent_and_keeps_unsettled_calls_held(self):
        from budget import case_spending
        c = types.SimpleNamespace(ledger=self.work / "l.json", card={})
        spend = {"ledger": {"events": [{"id": "e1", "cost": 0.5}], "cost": 0.5, "calls": 1,
                            "invocation_reservations": {"L": {"lease_id": "L", "state": "pending", "launched": True,
                                                              "maximum_usd": "2.000000000", "event_ids": [], "invocation_id": "i",
                                                              "call_name": "easy-calibrator-x-1"}}},
                 "card": {"models_used": {"easy-calibrator-x-1": "m"}}}
        helpers.book_spend(c, spend); helpers.book_spend(c, spend)
        ledger = json.loads(c.ledger.read_text())
        self.assertEqual((len(ledger["events"]), ledger["cost"], ledger["calls"]), (1, 0.5, 1))
        self.assertEqual(case_spending(ledger)["total_spent_usd"], 0.5)
        from durable.worker_step import ledger_totals
        self.assertEqual(ledger_totals(c.ledger)["total"], __import__("decimal").Decimal("2.5"))   # the open call holds its maximum
        self.assertEqual(c.card["models_used"], {"easy-calibrator-x-1": "m"})

    def test_try_jobs_carry_no_credentials(self):
        c = self.try_context()
        context = helpers.try_context(c)
        self.assertLessEqual(set(context["args"]), set(vars(run.argument_parser().parse_args(["--source", "port"]))))   # CLI args only
        self.assertEqual(set(context), {"case_id", "seed", "args", "models", "card", "router_accounts", "batch", "attempt", "deadline_epoch"})


if __name__ == "__main__":
    unittest.main()
