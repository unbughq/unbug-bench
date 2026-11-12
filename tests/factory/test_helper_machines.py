"""G6/G7 cheat checkpoints sharded over helper machines: same verdict inputs as the serial path,
a dead helper requeues only its job, flag off changes nothing."""
import sys
from pathlib import Path as _P
_ROOT = _P(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_ROOT / "bin"), str(_ROOT / "tests/bench")]
import json, tempfile, threading, time, types, unittest
from pathlib import Path
from unittest.mock import patch
import checkpoint_evidence
import run
from durable import helpers


def write_checkpoint(directory, runs, solved):
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(1, runs + 1):
        r = {"run": i, "errors": [], "checker": {"valid": True},
             "judge": {"pass": solved, "paths": {"p": False}, "checks": {"k": solved}, "legit": {"attempted": 1, "placed": 1}}}
        (directory / f"{i:02}.json").write_text(json.dumps(r))
    summary = {"runs": runs, "pass_runs": runs if solved else 0, "error_runs": 0, "invalid_runs": 0,
               "paths": {"p": {"violated_runs": 0, "runs": runs}},
               "checks": {"k": {"ok_runs": runs if solved else 0, "runs": runs}}}
    (directory / "checkpoint.json").write_text(json.dumps(summary))
    return directory


class FakePool:
    """Helpers that run a fake bin/checkpoint; `die_on` kills the helper running that guard once."""
    def __init__(self, tmp, solves, die_on=()):
        self.tmp, self.solves, self.die_on, self.lock = tmp, solves, set(die_on), threading.Lock()
        self.leased, self.dead, self.ran, self.jobs = 0, [], [], []

    def lease(self):
        with self.lock:
            self.leased += 1
            return self.leased

    def run(self, handle, job, key):
        with self.lock:
            self.ran.append((handle, job["guard"]))
            self.jobs.append(job)
            if job["guard"] in self.die_on:
                self.die_on.discard(job["guard"])
                raise helpers.HelperDied()
        return helpers.execute(job, key, check=lambda j: None, run=lambda j: write_checkpoint(
            self.tmp / f"h{handle}-{j['guard'][:8]}", j["runs"], job["guard"] in self.solves))

    def release(self, handle, dead):
        if dead: self.dead.append(handle)


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.case = self.tmp / "case"
        for name in ("a", "b", "c"):
            (self.case / "guards/cheats" / name).mkdir(parents=True)
            (self.case / "guards/cheats" / name / "g.js").write_text(name)
        (self.case / "base").mkdir()
        (self.case / "base/x").write_text("x")
        (self.case / "case.json").write_text("{}")
        self.work = self.tmp / "work"
        self.work.mkdir()
        self.guards = sorted((self.case / "guards/cheats").iterdir())
        self.by_name = {g.name: helpers.digest_of(helpers._tree(g)) for g in self.guards}
        self.c = types.SimpleNamespace(case=self.case, work=self.work, seed=5, card={}, manifest0="m",
                                       args=types.SimpleNamespace(runs=3, helper_workers=0, bench_workers=1))

    def pool(self, **kw):
        return FakePool(self.tmp, {self.by_name["b"]}, **kw)   # only cheat "b" solves the case

    def serial_checkpoint(self, c, scenarios, guard, runs, seed, label, **kw):
        out = write_checkpoint(self.tmp / f"serial-{guard.name}", runs, guard.name == "b")
        p = types.SimpleNamespace(returncode=0, stderr="", stdout=checkpoint_evidence.RECEIPT_PREFIX + json.dumps(
            {"version": 1, "path": str(out / "checkpoint.json"), "requested_runs": runs}))
        summary, records, _ = checkpoint_evidence.read_completed(p, runs, label)
        return summary, records

    def cheat_runs(self, **kw):
        with patch.object(run, "checkpoint", side_effect=self.serial_checkpoint) as cp, \
             patch.object(run, "case_budget_boundary"), patch.object(run, "verdicts", wraps=run.verdicts) as v:
            out = run.cheat_runs(self.c, 5, "g6", guards=self.guards, **kw)
        return out, cp, v

    def test_flag_off_runs_serially_and_never_touches_pool(self):
        self.c.helper_pool = types.SimpleNamespace(lease=lambda: 1 / 0)
        (passed, total), cp, _ = self.cheat_runs()
        self.assertEqual((passed, total, cp.call_count), (1, 3, 3))

    def test_sharded_gives_same_verdict_inputs_as_serial(self):
        (serial, _), _, sv = self.cheat_runs()
        pool = self.pool()
        self.c.args.helper_workers, self.c.helper_pool = 3, pool
        (sharded, total), cp, hv = self.cheat_runs()
        self.assertEqual((sharded, total), (serial, 3))
        self.assertEqual(cp.call_count, 0)   # nothing ran locally
        self.assertEqual([c.args[1] for c in hv.call_args_list], [c.args[1] for c in sv.call_args_list])
        self.assertEqual(len(pool.ran), 3)
        events = [json.loads(l)["event"] for l in (self.work / "helper-ledger.jsonl").read_text().splitlines()]
        self.assertEqual(events.count("job"), 3)
        self.assertEqual(events.count("lease"), events.count("release"))

    def test_dead_helper_requeues_only_its_job(self):
        pool = self.pool(die_on=[self.by_name["b"]])
        self.c.args.helper_workers, self.c.helper_pool = 1, pool
        (passed, total), cp, _ = self.cheat_runs()
        self.assertEqual((passed, total, cp.call_count), (1, 3, 0))
        self.assertEqual(len(pool.dead), 1)
        self.assertEqual(sum(g == self.by_name["b"] for _, g in pool.ran), 2)   # b twice, a and c once
        self.assertEqual(len(pool.ran), 4)

    def test_job_no_helper_completes_runs_locally(self):
        class Broken(FakePool):
            def run(self, handle, job, key): raise helpers.HelperDied()
        self.c.args.helper_workers, self.c.helper_pool = 2, Broken(self.tmp, set())
        (passed, total), cp, _ = self.cheat_runs()
        self.assertEqual((passed, total, cp.call_count), (1, 3, 3))

    def test_tampered_result_is_not_accepted(self):
        class Forger(FakePool):
            def run(self, handle, job, key):
                sealed = super().run(handle, job, key)
                sealed["body"]["files"]["01.json"] = sealed["body"]["files"]["01.json"].replace("true", "false")
                return sealed
        self.c.args.helper_workers, self.c.helper_pool = 1, Forger(self.tmp, set(self.by_name.values()))
        (_, _), cp, _ = self.cheat_runs()
        self.assertEqual(cp.call_count, 3)   # every result rejected, all run locally
        sealed = helpers.seal(b"k" * 32, {"a": 1}, {"checkpoint.json": "{}"})
        with self.assertRaises(ValueError): helpers.open_sealed(b"k" * 32, {"a": 2}, sealed)
        with self.assertRaises(ValueError): helpers.open_sealed(b"z" * 32, {"a": 1}, sealed)

    def test_advisory_early_check_never_uses_helpers(self):
        self.c.args.helper_workers, self.c.helper_pool = 2, types.SimpleNamespace(lease=lambda: 1 / 0)
        (_, _), cp, _ = self.cheat_runs(runs=1, deadline=time.monotonic() + 999, unchecked=[])
        self.assertEqual(cp.call_count, 3)

    def test_cap_bounds_concurrent_helpers_and_boundary_stops_dispatch(self):
        live, peak, lock = [0], [0], threading.Lock()
        class Counting:
            def lease(s):
                with lock:
                    live[0] += 1
                    peak[0] = max(peak[0], live[0])
                time.sleep(0.01)
                return object()
            def run(s, handle, job, key): return helpers.seal(key, job, {"checkpoint.json": "{}"})
            def release(s, handle, dead):
                with lock: live[0] -= 1
        jobs = {str(i): {"i": i} for i in range(6)}
        out = helpers.run_jobs(Counting(), jobs, cap=2, key=b"k" * 32, accept=lambda j, f: f)
        self.assertEqual(len(out), 6)
        self.assertLessEqual(peak[0], 2)
        class Stop(Exception): pass
        def boundary(): raise Stop()
        with self.assertRaises(Stop):
            helpers.run_jobs(Counting(), jobs, cap=2, key=b"k" * 32, accept=lambda j, f: f, boundary=boundary)

    def test_job_identity_equals_serial_checkpoint_identity(self):
        def go():
            with patch.object(run, "checkpoint", side_effect=self.serial_checkpoint) as cp, \
                 patch.object(run, "case_budget_boundary"):
                run.cheat_runs(self.c, 9, "g7", guards=self.guards)
            return cp
        serial = {str(c.args[2]): (c.args[3], c.args[4], c.args[5]) for c in go().call_args_list}
        pool = self.pool()
        self.c.args.helper_workers, self.c.helper_pool = 3, pool
        go()
        self.assertEqual(len(pool.jobs), 3)
        for job in pool.jobs:
            g = next(g for g in self.guards if helpers.digest_of(helpers._tree(g)) == job["guard"])
            self.assertEqual((job["runs"], job["seed"], job["label"]), serial[str(g)])
            self.assertEqual(job["scenarios"], [helpers.digest_of(helpers._tree(self.case / "base"))])
            self.assertEqual(job["case"], run.case_hash(self.c))
            self.assertEqual(job["bench"], "m")
            self.assertEqual((job["seed"], job["label"], job["workers"]), (9, "g7-cheat", 1))

    def test_helper_of_another_machine_class_is_refused_and_seal_records_class(self):
        job = helpers.make_job(case="c", guard={}, scenarios=[], bench="m", release="r", runs=1, seed=1, label="l")
        other = lambda: {"cpus": job["machine"]["cpus"] + 1, "mem_gib": 1}
        with self.assertRaises(helpers.HelperRefused):
            helpers.execute(job, b"k" * 32, check=lambda j: None, run=lambda j: write_checkpoint(self.tmp / "x", 1, True), machine=other)
        forged = helpers.seal(b"k" * 32, job, {"checkpoint.json": "{}", "01.json": "{}"}, other())
        with self.assertRaises(ValueError): helpers.open_sealed(b"k" * 32, job, forged)
        ok = helpers.execute(job, b"k" * 32, check=lambda j: None, run=lambda j: write_checkpoint(self.tmp / "y", 1, True))
        helpers.open_sealed(b"k" * 32, job, ok)

    def test_result_must_be_exactly_one_checkpoint_batch(self):
        job = helpers.make_job(case="c", guard={}, scenarios=[], bench="m", release="r", runs=2, seed=1, label="l")
        full = helpers.collect(write_checkpoint(self.tmp / "z", 2, True))
        helpers.open_sealed(b"k" * 32, job, helpers.seal(b"k" * 32, job, full))
        for bad in ({k: v for k, v in full.items() if k != "checkpoint.json"}, {k: v for k, v in full.items() if k != "02.json"},
                    {**full, "03.json": "{}"}, {}):
            with self.assertRaises(ValueError): helpers.open_sealed(b"k" * 32, job, helpers.seal(b"k" * 32, job, bad))

    def test_helper_code_is_part_of_the_verdict_binding(self):
        from durable.checkpoints import VERDICT_CODE
        import gate_state
        self.assertIn("durable/helpers.py", VERDICT_CODE)
        self.assertIn("factory/durable/helpers.py", gate_state.DEPENDENCIES["G6"])
        self.assertIn("factory/durable/helpers.py", gate_state.STAGE_DEPENDENCIES["G7"])


if __name__ == "__main__":
    unittest.main()
