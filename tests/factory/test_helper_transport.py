"""Helper machines over the control VM (durable/helper_link.py): a GATES step's G6/G7 cheat checkpoints
run on real helpers leased through BoatPool on the stand-in Boat of test_durable_workers.py, results
sealed and verified, helpers released on success, failure and case stop, lease time accounted, flag off
changes nothing. The helper's `bin/checkpoint` is a stand-in; its input checks are the real ones."""
import sys
from pathlib import Path as _P
_ROOT = _P(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "tests/factory"), str(_ROOT / "factory"), str(_ROOT / "bin"), str(_ROOT / "tests/bench")]
import json, os, tempfile, threading, time, types, unittest
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
def fake(job):
    name = Path(job["guard_at"][1]).name
    die = Path({{DIE!r}})
    if name == "b" and die.exists():
        die.unlink(); os._exit(9)   # the helper is lost mid-job, once
    return write_checkpoint(Path.home() / "ckpt" / name, job["runs"], name == "b")
print(json.dumps(helper_link.serve(frame, run=fake)))
'''


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
        self.script.write_text(STANDIN.replace("{DIE!r}", repr(str(self.die))))
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


if __name__ == "__main__":
    unittest.main()
