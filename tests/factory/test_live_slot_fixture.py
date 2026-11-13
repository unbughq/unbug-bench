"""Gathering bench evidence leaves a live factory slot's seed IDs in place (case f46dac).

  uv run -q --with numpy --with scipy --with dbos==3.4.0 python -B tests/factory/test_live_slot_fixture.py"""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import os, shutil, subprocess, tempfile, time, types, unittest
from pathlib import Path
from unittest import mock
import run

ROOT = _TEST_ROOT
FINGERPRINT = "import bench; bench.bench_fingerprint(); print(bench.IDS.relative_to(bench.ROOT))"


class LiveSlotFixtureTests(unittest.TestCase):
    def test_gather_keeps_slot_seed_ids_for_later_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench = Path(tmp) / "bench"
            # The real bench code, so the slot's seed-ID path is the one bench.py derives.
            for name in ("bin/bench.py", "bin/bench_judging.py", "bin/processes.py", "bin/refusal.py",
                         "factory/case_permissions.py", "cases/medusa-oversell/checker/check.sql",
                         "cases/medusa-oversell/traffic/run.mjs"):
                (bench / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, bench / name)
            (bench / "projects/medusa").mkdir(parents=True)
            env = {**os.environ, "UNBUG_FACTORY_SLOT": "1"}
            def fingerprint():
                return subprocess.run([sys.executable, "-B", "-c", FINGERPRINT], cwd=bench / "bin",
                                      env=env, capture_output=True, text=True)
            c = types.SimpleNamespace(t0=time.time() - 1, work=Path(tmp) / "work")
            # prepare_factory_slot ran during this step: the fixture is newer than t0.
            ids = bench / "results/factory-slots/1/seed-ids.json"
            ids.parent.mkdir(parents=True)
            ids.write_text('{"admin": {"email": "a@example.test", "password": "x"}}\n')
            evidence = bench / "results/factory-slots/1/runs/20261113T000000Z-g5/01.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("{}\n")
            first = fingerprint()
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout.strip(), "results/factory-slots/1/seed-ids.json")
            with mock.patch.object(run, "BENCH", bench), mock.patch.object(run, "HOME", Path(tmp)):
                run.gather_bench_results(c)
            self.assertTrue((c.work / "bench-results/factory-slots/1/runs/20261113T000000Z-g5/01.json").is_file())
            self.assertFalse(evidence.exists())
            self.assertTrue(ids.is_file(), "the live slot fixture was moved into the evidence")
            self.assertFalse((c.work / "bench-results/factory-slots/1/seed-ids.json").exists())
            again = fingerprint()  # the next bin/checkpoint on slot 1
            self.assertEqual(again.returncode, 0, again.stderr)

    def test_rebuilt_slot_gets_a_fresh_infra_allowance(self):
        from run_validity import InfrastructureExhausted
        with tempfile.TemporaryDirectory() as tmp:
            bench, work = Path(tmp) / "bench", Path(tmp) / "work"
            work.mkdir()
            ids = bench / "results/factory-slots/1/seed-ids.json"
            ids.parent.mkdir(parents=True)
            c = types.SimpleNamespace(work=work)
            calls, crash = [], [True]
            def sh(c, command, **kwargs):
                calls.append(command)
                if crash[0]: raise FileNotFoundError(str(ids))  # bench_fingerprint on a broken slot
                return types.SimpleNamespace(returncode=0)
            def checkpoint(slot):
                identity = {"operation": "checkpoint", "case": "f46dac", "guard": {}, "scenarios": [], "runs": 3,
                            "seed": 1, "slot": slot, "label": "g5", "bench": None, "workers": 1}
                return run._checkpoint_call(c, identity, ["bin/checkpoint"], None, None, lambda p: ({}, [], None))
            with mock.patch.object(run, "BENCH", bench), mock.patch.object(run, "sh", sh), \
                 mock.patch.object(run, "case_budget_boundary", lambda c: None):
                ids.write_text('{"region_id": "reg_A"}\n')  # prepare_factory_slot's IDs before the crash
                with self.assertRaises(InfrastructureExhausted): checkpoint(1)
                self.assertEqual(len(calls), 2)
                crash[0] = False
                with self.assertRaises(InfrastructureExhausted): checkpoint(1)  # same shop: still refused
                self.assertEqual(len(calls), 2)
                ids.write_text('{"region_id": "reg_B"}\n')  # engine restart re-prepared the slot
                self.assertEqual(checkpoint(1), ({}, []))
                self.assertEqual(len(calls), 3)
                # A slot-less checkpoint keeps the row helpers charge (durable/helpers.py), whatever the IDs.
                crash[0] = True
                with self.assertRaises(InfrastructureExhausted): checkpoint(None)
                ids.write_text('{"region_id": "reg_C"}\n')
                crash[0] = False
                with self.assertRaises(InfrastructureExhausted): checkpoint(None)


if __name__ == "__main__":
    unittest.main()
