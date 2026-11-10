"""Parallel gates for new cases: deferred engine snapshots, the G2/G8/G9 lane, admission defaults and
writer phase timing. Synthetic gates; no models, bench instances or providers."""
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin")]

import json
import pathlib
import tempfile
import threading
import time
import types
import unittest
from contextlib import ExitStack
from unittest import mock

import run
import public_progress
from durable import checkpoints as cp
from durable.steps import admit


def engine_context(work):
    c = types.SimpleNamespace(work=work, card={}, engine=types.SimpleNamespace(key="case-x/1/gates/1"))
    c.published = []
    c.engine_checkpoint = lambda: c.published.append(time.monotonic()) or True
    return c


class DeferredSnapshots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = engine_context(pathlib.Path(self.tmp.name))

    def test_outside_a_section_a_checkpoint_publishes(self):
        self.assertTrue(cp.checkpoint(self.c))
        self.assertEqual(len(self.c.published), 1)

    def test_inside_a_section_snapshots_wait_for_the_join_and_publish_once(self):
        with cp.concurrent_section(self.c):
            with cp.concurrent_section(self.c):
                self.assertFalse(cp.checkpoint(self.c))
                self.assertFalse(cp.checkpoint(self.c))
            self.assertEqual(self.c.published, [], "an inner join is not quiescent while the outer section runs")
        self.assertEqual(len(self.c.published), 1)
        self.assertFalse(self.c.engine.checkpoint_deferred)

    def test_a_section_without_requests_publishes_nothing(self):
        with cp.concurrent_section(self.c):
            pass
        self.assertEqual(self.c.published, [])

    def test_a_failing_section_still_publishes_its_deferred_snapshot(self):
        with self.assertRaises(RuntimeError):
            with cp.concurrent_section(self.c):
                cp.checkpoint(self.c)
                raise RuntimeError("role failed")
        self.assertEqual(len(self.c.published), 1)

    def test_a_deferred_checkpoint_never_waits_for_a_model_call_holding_the_lock(self):
        held, release = threading.Event(), threading.Event()
        def model_call():
            with cp._lock(self.c):
                held.set()
                release.wait(5)
        thread = threading.Thread(target=model_call)
        with cp.concurrent_section(self.c):
            thread.start()
            self.assertTrue(held.wait(5))
            started = time.monotonic()
            self.assertFalse(cp.checkpoint(self.c))
            self.assertLess(time.monotonic() - started, 1.0)
            release.set()
            thread.join(5)
        self.assertEqual(len(self.c.published), 1)

    def test_isolated_call_counts_survive_two_threads(self):
        (self.c.work / "inside").mkdir()
        outside = pathlib.Path(self.tmp.name).parent
        barrier = threading.Barrier(8)
        def isolated():
            barrier.wait(5)
            for _ in range(200):
                cp.model_call(self.c, ["m"], outside, "pilot", lambda: 0)
        threads = [threading.Thread(target=isolated) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join(10)
        self.assertEqual(self.c.engine.isolated_model_active, 0)
        self.assertTrue(cp.checkpoint(self.c))


class Calibrators(unittest.TestCase):
    def test_engine_cases_need_the_admission_flag(self):
        c = types.SimpleNamespace(engine=object(), args=types.SimpleNamespace(concurrent_roles=True), case=pathlib.Path("/nonexistent"))
        self.assertFalse(run.parallel_calibrators(c))
        self.assertFalse(run.parallel_gates(c))
        c.args.parallel_gates = True
        self.assertTrue(run.parallel_gates(c))
        import bench
        with mock.patch.object(bench, "load_scenario", return_value={}), \
             mock.patch.object(bench, "isolated_inventory_services", return_value=True), \
             mock.patch.object(bench, "factory_memory_fits", return_value=True):
            self.assertTrue(run.parallel_calibrators(c))
        with mock.patch.object(bench, "load_scenario", return_value={}), \
             mock.patch.object(bench, "isolated_inventory_services", return_value=True), \
             mock.patch.object(bench, "factory_memory_fits", return_value=False):
            self.assertFalse(run.parallel_calibrators(c), "memory still decides")

    def test_the_flag_is_a_kept_engine_setting(self):
        self.assertIn("parallel_gates", run.ENGINE_SETTINGS)
        self.assertFalse(run.argument_parser().parse_args([]).parallel_gates)
        self.assertEqual(run.argument_parser().parse_args([]).bench_workers, 1)

    def test_g10_defers_snapshots_until_both_calibrators_join(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        c = engine_context(pathlib.Path(tmp.name))
        c.args = types.SimpleNamespace(resume=None, bench_workers=2, concurrent_roles=True)
        c.calibrator_slot_offset, c.role_cancel = 2, threading.Event()
        both = threading.Barrier(2)
        def calibrate(child, role):
            both.wait(5)
            self.assertFalse(cp.checkpoint(child), "a calibrator snapshot while the other runs")
            both.wait(5)
            return {"solved": 1 if role == "strong_calibrator" else 0, "tries": 3}
        with mock.patch.object(run, "make_pilots"), mock.patch.object(run, "calibrate", calibrate), \
             mock.patch("exam_responder.contract", return_value={}), \
             mock.patch("calibration.require_summary_valid"):
            ok, _ = run.g10(c)
        self.assertTrue(ok)
        self.assertEqual(len(c.published), 1, "one snapshot once both workspaces joined")


class Admission(unittest.TestCase):
    def card(self, **inputs):
        value = {"seed": 7, "source": "port", **inputs}
        return admit._card(value, "case-new", value.get("dry_run", False))

    def test_new_cases_get_parallel_settings(self):
        self.assertEqual(self.card()["recovery_config"], {"bench_workers": 2, "parallel_gates": True,
                                                         "attack_open_findings": True, "seal_audit": True})

    def test_explicit_inputs_win(self):
        config = self.card(recovery_config={"bench_workers": 1, "rounds": 3})["recovery_config"]
        self.assertEqual(config, {"bench_workers": 1, "parallel_gates": True, "rounds": 3,
                                  "attack_open_findings": True, "seal_audit": True})

    def test_recertified_and_practice_cases_keep_theirs(self):
        self.assertEqual(self.card(recertify=True, recovery_config={"rounds": 8})["recovery_config"], {"rounds": 8})
        self.assertNotIn("recovery_config", self.card(dry_run=True))


GATES = ["G1", "G2", "G3", "G4", "G5", "G16", "G8", "G9", "G6", "G13", "G7", "G11"]


def exercise(test, gates, *, engine=False, change_case=False):
    """Run the pipeline with synthetic gates. gates: name -> callable(c) -> (ok, info)."""
    tmp = tempfile.TemporaryDirectory(); test.addCleanup(tmp.cleanup)
    work = pathlib.Path(tmp.name)
    c = types.SimpleNamespace(args=types.SimpleNamespace(dry_run=False, resume=None, bench_workers=2, no_early_probe=True),
                              card={"gates": {}, "failed_gate": None}, prepared_factory_slots=1, work=work, case=work / "case")
    c.case.mkdir()
    (c.case / "statement.md").write_text("one")
    if engine:
        c.engine = types.SimpleNamespace(key="case-x/1/gates/1")
        c.published = []
        c.engine_checkpoint = lambda: c.published.append(getattr(c.engine, "concurrent_sections", 0)) or True
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(run, "GATES", GATES))
        stack.enter_context(mock.patch.object(run, "log"))
        stack.enter_context(mock.patch.object(run, "public_progress"))
        stack.enter_context(mock.patch.object(run, "update_case_budget"))
        stack.enter_context(mock.patch.object(run, "case_budget_boundary"))
        stack.enter_context(mock.patch.object(run, "g10_overlap_reason", return_value="serial in this test"))
        stack.enter_context(mock.patch.object(run, "parallel_gates", return_value=True))
        if engine:
            stack.enter_context(mock.patch("gate_state.inputs", return_value={}))
            stack.enter_context(mock.patch.object(cp, "gate_call", lambda c, gate, invoke, binding: invoke()))
        for gate in GATES:
            fn = gates.get(gate, lambda c: (True, {}))
            stack.enter_context(mock.patch.object(run, gate.lower(), fn))
        if change_case:
            stack.enter_context(mock.patch.object(run, "g2", lambda c: ((c.case / "statement.md").write_text("two"), (True, {}))[1]))
        run.run_gates(c)
    return c


class SideLane(unittest.TestCase):
    def test_reviewers_and_freshness_run_beside_the_bench_gates(self):
        reviewing, benching = threading.Event(), threading.Event()
        seen = []
        def g4(c):
            benching.set()
            self.assertTrue(reviewing.wait(5), "G8 did not run beside G4")
            seen.append("G4"); return True, {}
        def g8(c):
            reviewing.set()
            self.assertTrue(benching.wait(5), "G4 did not run beside G8")
            seen.append("G8"); return True, {"approve": "2/2"}
        def g6(c):
            self.assertIn("G9", c.card["gates"], "the lane joins before G6")
            seen.append("G6"); return True, {}
        def g1(c):
            self.assertFalse(reviewing.is_set(), "the lane waits for G1")
            return True, {"problems": []}
        c = exercise(self, {"G1": g1, "G4": g4, "G8": g8, "G6": g6})
        self.assertIsNone(c.card["failed_gate"])
        self.assertEqual({g for g, v in c.card["gates"].items() if v == "pass"}, set(GATES))
        self.assertEqual(c.card["gate_results"]["G8"], {"approve": "2/2"})
        self.assertIn("G2", c.card["gate_minutes"])

    def test_a_lane_failure_stops_the_bench_gates_at_the_next_boundary(self):
        reached = []
        def g5(c):
            time.sleep(0.3)  # G2 has failed by now
            reached.append("G5"); return True, {}
        def g16(c):
            reached.append("G16"); return True, {}
        c = exercise(self, {"G2": lambda c: (False, {"outcome": "public_match"}), "G5": g5, "G16": g16})
        self.assertEqual(c.card["failed_gate"], "G2")
        self.assertNotIn("G16", reached)
        self.assertNotIn("G8", c.card["gates"])

    def test_the_earliest_failure_in_gate_order_is_reported(self):
        def g2(c):
            time.sleep(0.3)
            return False, {"outcome": "public_match"}
        c = exercise(self, {"G2": g2, "G3": lambda c: (False, {"problems": ["setup"]})})
        self.assertEqual(c.card["failed_gate"], "G2")
        c = exercise(self, {"G8": lambda c: (time.sleep(0.3), (False, {"approve": "1/2"}))[1],
                            "G4": lambda c: (False, {"problems": ["bug not real"]})})
        self.assertEqual(c.card["failed_gate"], "G4")
        self.assertEqual(c.card["failed_detail"], ["bug not real"])

    def test_a_case_edited_beside_the_bench_gates_is_an_infrastructure_retry(self):
        c = exercise(self, {}, change_case=True)
        self.assertEqual(c.card["failed_gate"], "G2")
        self.assertEqual(c.card["failed_detail"], {"error": "case_changed_during_parallel_gates"})
        self.assertNotIn("G6", c.card["gates"])

    def test_engine_snapshots_wait_for_the_lane(self):
        lane_running = threading.Event()
        def g8(c):
            lane_running.set(); time.sleep(0.3); return True, {"approve": "2/2"}
        def g4(c):
            self.assertTrue(lane_running.wait(5)); return True, {}
        c = exercise(self, {"G8": g8, "G4": g4}, engine=True)
        self.assertIsNone(c.card["failed_gate"])
        # Snapshots requested while the lane ran waited for it: each one published at a quiescent point.
        self.assertGreaterEqual(len(c.published), 1)
        self.assertEqual(set(c.published), {0})
        self.assertEqual(c.engine.concurrent_sections, 0)

    def test_a_lane_stop_is_raised_after_the_lane_joins(self):
        def g9(c): raise run.BudgetError("provider_limit")
        with self.assertRaises(run.BudgetError):
            exercise(self, {"G9": g9})

    def test_serial_without_the_flag(self):
        order = []
        gates = {g: (lambda g: lambda c: (order.append(g), (True, {}))[1])(g) for g in GATES}
        with mock.patch.object(run, "parallel_gates", return_value=False):
            tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
            work = pathlib.Path(tmp.name)
            c = types.SimpleNamespace(args=types.SimpleNamespace(dry_run=False, resume=None, bench_workers=1, no_early_probe=True),
                                      card={"gates": {}, "failed_gate": None}, work=work, case=work / "case")
            c.case.mkdir()
            with ExitStack() as stack:
                for name in ("log", "public_progress", "update_case_budget", "case_budget_boundary"):
                    stack.enter_context(mock.patch.object(run, name))
                stack.enter_context(mock.patch.object(run, "GATES", GATES))
                stack.enter_context(mock.patch.object(run, "g10_overlap_reason", return_value="serial"))
                for gate in GATES: stack.enter_context(mock.patch.object(run, gate.lower(), gates[gate]))
                run.run_gates(c)
        self.assertEqual(order, GATES)


class WriterPhases(unittest.TestCase):
    def test_phases_are_public_stages(self):
        for phase in public_progress.PHASES:
            self.assertTrue(public_progress._stage("phase:writer:" + phase))
        self.assertFalse(public_progress._stage("phase:writer:anything"))

    def test_a_phase_records_its_time_and_status(self):
        c = types.SimpleNamespace(card={})
        published = []
        with mock.patch.object(run, "public_progress", lambda c, stage, status, elapsed=None: published.append((stage, status))):
            with run.writer_phase(c, "writer_model", round=2, call=1):
                pass
            with self.assertRaises(run.BudgetError):
                with run.writer_phase(c, "early_checks", round=2, call=1):
                    raise run.BudgetError("provider_limit")
            with self.assertRaises(ValueError):
                with run.writer_phase(c, "g1", round=2, call=1):
                    raise ValueError("bad case")
        rows = c.card["phase_times"]
        self.assertEqual([(r["phase"], r["status"]) for r in rows],
                         [("writer_model", "completed"), ("early_checks", "interrupted"), ("g1", "failed")])
        self.assertEqual(rows[0]["round"], 2)
        self.assertTrue(rows[0]["started_at"].endswith("Z"))
        self.assertEqual(published[:2], [("phase:writer:writer_model", "running"), ("phase:writer:writer_model", "completed")])

    def test_the_public_file_accepts_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "case.progress.json"
            data = public_progress.publish(path, "phase:writer:g1", "completed", 12.5)
            self.assertEqual(data["completed"]["phase:writer:g1"]["elapsed_seconds"], 12.5)


if __name__ == "__main__":
    unittest.main()
