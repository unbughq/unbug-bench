"""Gathering bench evidence leaves a live factory slot's seed IDs in place (case f46dac).

  uv run -q --with numpy --with scipy --with dbos==3.4.0 python -B tests/factory/test_live_slot_fixture.py"""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json, os, re, shutil, subprocess, tempfile, time, types, unittest
from pathlib import Path
from unittest import mock
import run
import gate_state

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

    def test_gather_leaves_every_live_slot_state_file(self):
        """Gather moved .prepared.json, .inventory-services.json and the compose/port overrides too:
        the slot then looked unprepared and the next stop_inventory_services lost its compose files.
        Everything else in results, including factory_pool's leftover .factory-runs-* records, is
        evidence and is gathered (a checkpoint timeout leaves that folder behind)."""
        with tempfile.TemporaryDirectory() as tmp:
            bench = Path(tmp) / "bench"
            for name in ("bin/bench.py", "bin/bench_judging.py", "bin/processes.py", "bin/refusal.py",
                         "factory/case_permissions.py"):
                (bench / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, bench / name)
            (bench / "projects/medusa").mkdir(parents=True)
            env = {**os.environ, "UNBUG_FACTORY_SLOT": "1"}
            def probe(code):
                p = subprocess.run([sys.executable, "-B", "-c", "import bench, hashlib, json, pathlib\n" + code],
                                   cwd=bench / "bin", env=env, capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stderr)
                return p.stdout.strip()
            c = types.SimpleNamespace(t0=time.time() - 1, work=Path(tmp) / "work")
            # Slot 1's state at the names bench itself uses (importing it writes the slot compose override).
            state = probe("""
r = bench.RESULTS
bench.IDS.write_text('{}')
(r / bench.PREPARED).write_text(json.dumps({'version': 1, 'slot': 1,
    'seed_ids_sha256': hashlib.sha256(bench.IDS.read_bytes()).hexdigest()}))
bench.INVENTORY_STATE.write_text(json.dumps({'compose': ['true'], 'names': []}))
for name in (bench.INVENTORY_COMPOSE, bench.INVENTORY_PORTS, bench.GUARD_COMPOSE, bench.PENDING_STATE, bench.LOCK,
             pathlib.Path(bench.PREPARED).with_suffix('.tmp').name, bench.PROGRESS_PREFIX + '7.json'):
    (r / name).write_text('x')
(r / bench.NO_CHANGES).mkdir(); (r / bench.NO_CHANGES / 'scenario.json').write_text('{}')
print(json.dumps(sorted(str(p.relative_to(bench.ROOT / 'results')) for p in r.rglob('*') if p.is_file())))""")
            state = set(json.loads(state))
            self.assertEqual(len(state), 12)
            evidence = {"factory-slots/1/runs/20261113T000000Z-g5/01.json", ".factory-runs-x/records.json",
                        ".factory-runs-x/job.json"}
            for rel in evidence:
                (bench / "results" / rel).parent.mkdir(parents=True, exist_ok=True)
                (bench / "results" / rel).write_text("{}\n")
            # The gate inventory and the gather agree on what is evidence.
            inventory = {rel for kind, rel in gate_state.inventory(c, bench) if kind == "bench"}
            self.assertEqual(inventory, evidence)
            with mock.patch.object(run, "BENCH", bench), mock.patch.object(run, "HOME", Path(tmp)):
                run.gather_bench_results(c)
            for rel in state:
                self.assertTrue((bench / "results" / rel).is_file(), f"gather moved live slot state {rel}")
            self.assertEqual({p.relative_to(c.work / "bench-results").as_posix()
                              for p in (c.work / "bench-results").rglob("*") if p.is_file()}, evidence)
            self.assertEqual(probe("print(bench.factory_slot_ready(bench.ROOT / 'results', 1), bench.INVENTORY_STATE.exists())"),
                             "True True")
            # The wipe still shreds that state (it can hold case paths), but never the lock or the seed IDs.
            artifacts = run._run_artifacts()
            artifacts.bench = bench
            wiped = {p.relative_to(bench / "results").as_posix() for p in artifacts.results_since(c, include_state=True)}
            self.assertEqual(wiped, state - {"factory-slots/1/seed-ids.json", "factory-slots/1/.bench.lock"})

    def test_bench_writes_its_state_only_under_registered_names(self):
        """A state file bench (or the CLIs beside it) writes into RESULTS under a bare literal would
        bypass bench.is_state and be gathered as evidence again; renaming a constant must reach both."""
        import bench
        for name in ("bin/bench.py", "bin/checkpoint", "bin/factory_pool.py"):
            text = (ROOT / name).read_text()
            self.assertEqual(re.findall(r"RESULTS\s*/\s*f?[\"']\.[^\"']*[\"']", text), [], name)
        self.assertTrue(all(bench.is_state(n) for n in bench.STATE_FILES))
        self.assertTrue(bench.is_state(f"factory-slots/2/{bench.NO_CHANGES}/scenario.json"))
        self.assertFalse(bench.is_state(".factory-runs-x/records.json"))
        self.assertFalse(bench.is_state("factory-slots/2/runs/x/01.json"))

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
                # Slot 0 is the main shop, whose IDs prepare_factory_main rewrites in projects/medusa.
                main = bench / "projects/medusa/seed-ids.json"
                main.parent.mkdir(parents=True)
                main.write_text('{"region_id": "reg_M1"}\n')
                crash[0] = True
                with self.assertRaises(InfrastructureExhausted): checkpoint(0)
                main.write_text('{"region_id": "reg_M2"}\n')
                crash[0] = False
                self.assertEqual(checkpoint(0), ({}, []))
                # A slot-less checkpoint keeps the row helpers charge (durable/helpers.py), whatever the IDs.
                crash[0] = True
                with self.assertRaises(InfrastructureExhausted): checkpoint(None)
                ids.write_text('{"region_id": "reg_C"}\n')
                crash[0] = False
                with self.assertRaises(InfrastructureExhausted): checkpoint(None)


if __name__ == "__main__":
    unittest.main()
