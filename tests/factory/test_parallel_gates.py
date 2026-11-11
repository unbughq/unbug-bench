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
import gate_state
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


class RunningCases(unittest.TestCase):
    def case(self, config=None, receipt=None, dry_run=False):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name) / "attack-state.json"
        if receipt is not None: path.write_text(json.dumps(receipt))
        card = {} if config is None else {"recovery_config": config}
        c = types.SimpleNamespace(card=card, args=types.SimpleNamespace(dry_run=dry_run, bench_workers=1, parallel_gates=False))
        return c, path

    def test_an_older_case_adopts_the_settings_at_a_new_writer_round(self):
        c, path = self.case({"bench_workers": 1, "rounds": 8}, {"engine": True, "round": 2})
        self.assertTrue(run.adopt_parallel_checks(c, 3, path))
        self.assertEqual(c.card["recovery_config"], {"bench_workers": 2, "parallel_gates": True, "rounds": 8})
        self.assertEqual((c.args.bench_workers, c.args.parallel_gates), (2, True))

    def test_a_card_without_settings_adopts_them(self):
        c, path = self.case()
        self.assertTrue(run.adopt_parallel_checks(c, 1, path))
        self.assertEqual(c.card["recovery_config"], {"bench_workers": 2, "parallel_gates": True})

    def test_a_retry_of_a_round_that_began_keeps_its_settings(self):
        c, path = self.case({"bench_workers": 1}, {"engine": True, "round": 3, "repair_pending": True})
        self.assertFalse(run.adopt_parallel_checks(c, 3, path))
        self.assertEqual((c.card["recovery_config"], c.args.bench_workers), ({"bench_workers": 1}, 1))

    def test_an_explicit_flag_and_practice_cases_are_left_alone(self):
        for config, dry in (({"parallel_gates": False}, False), ({"bench_workers": 1}, True)):
            c, path = self.case(config, dry_run=dry)
            self.assertFalse(run.adopt_parallel_checks(c, 1, path))
            self.assertEqual((c.card["recovery_config"], c.args.bench_workers), (config, 1))

    def test_gates_entry_adopts_only_the_missing_flag(self):
        c, _ = self.case({"bench_workers": 1, "rounds": 8})
        c.engine, c.stopped = object(), False
        with mock.patch.object(run, "validate_and_repair", side_effect=lambda c: self.assertTrue(run.parallel_gates(c))):
            result = run.engine_gates(c)
        self.assertEqual(result["reason"], "engine:gates_passed")
        self.assertEqual(c.card["recovery_config"], {"bench_workers": 1, "rounds": 8, "parallel_gates": True})
        self.assertEqual(c.args.bench_workers, 1)

    def test_gates_entry_respects_explicit_flags_and_dry_runs(self):
        for config, dry in (({"parallel_gates": False, "bench_workers": 1}, False),
                            ({"parallel_gates": True, "bench_workers": 1}, False),
                            ({"bench_workers": 1}, True)):
            c, _ = self.case(config, dry_run=dry)
            self.assertFalse(run.adopt_parallel_gates_at_entry(c))
            self.assertEqual(c.card["recovery_config"], config)
            self.assertEqual(c.args.bench_workers, 1)

    def test_gates_entry_keeps_passed_gate_cache_identities(self):
        c, _ = self.case({"bench_workers": 1})
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        c.case = pathlib.Path(tmp.name) / "case"
        c.case.mkdir()
        c.seed, c.models = 7, {}
        bench = pathlib.Path(tmp.name) / "bench"
        bench.mkdir()
        before = {gate: gate_state.fingerprint(c, gate, bench) for gate in gate_state.REUSABLE}
        self.assertTrue(run.adopt_parallel_gates_at_entry(c))
        after = {gate: gate_state.fingerprint(c, gate, bench) for gate in gate_state.REUSABLE}
        self.assertEqual(before, after)
        for gate in gate_state.REUSABLE:
            sources = gate_state.runner_inputs(gate)
            self.assertNotIn("engine_gates", sources)
            self.assertNotIn("adopt_parallel_gates_at_entry", sources)


class Admission(unittest.TestCase):
    def card(self, **inputs):
        value = {"seed": 7, "source": "port", **inputs}
        return admit._card(value, "case-new", value.get("dry_run", False))

    def test_new_cases_get_parallel_settings(self):
        self.assertEqual(self.card()["recovery_config"], {"bench_workers": 2, "parallel_gates": True})

    def test_explicit_inputs_win(self):
        config = self.card(recovery_config={"bench_workers": 1, "rounds": 3})["recovery_config"]
        self.assertEqual(config, {"bench_workers": 1, "parallel_gates": True, "rounds": 3})

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


def early(test, gates, *, parallel=True, cheats=None, slots=4, engine=True, overlap=None, **args):
    """run.early_checks with synthetic G15/G3/G4/G5 and saved-cheat sample. gates: name -> fn(c) -> (ok, info).
    Returns (problems, c, calls) where calls lists (gate, factory_slot, bench_workers) per execution."""
    tmp = tempfile.TemporaryDirectory(); test.addCleanup(tmp.cleanup)
    work = pathlib.Path(tmp.name)
    c = types.SimpleNamespace(args=types.SimpleNamespace(**{"dry_run": False, "bench_workers": 2, **args}),
                              card={"gates": {}}, prepared_factory_slots=1, work=work, case=work / "case")
    c.case.mkdir(); (c.case / "answer-key.json").write_text("{}")
    test.c = c  # for tests whose early_checks raises
    if engine:
        c.engine = types.SimpleNamespace(key="case-x/1/writer/1")
        c.published = []
        c.engine_checkpoint = lambda: c.published.append(getattr(c.engine, "concurrent_sections", 0)) or True
    calls, lock = [], threading.Lock()
    def wrap(name, fn):
        def gate(ctx):
            with lock: calls.append((name, getattr(ctx, "factory_slot", 0), ctx.args.bench_workers))
            if name == "G3": ctx.prepared_factory_slots = slots
            return fn(ctx)
        return gate
    with ExitStack() as stack:
        for name in ("log", "public_progress"):
            stack.enter_context(mock.patch.object(run, name))
        stack.enter_context(mock.patch.object(run, "case_hash", return_value="h"))
        stack.enter_context(mock.patch.object(run, "parallel_gates", return_value=parallel))
        stack.enter_context(mock.patch.object(run, "g10_overlap_reason", return_value=overlap))
        for name in ("G15", "G3", "G4", "G5"):
            stack.enter_context(mock.patch.object(run, name.lower(), wrap(name, gates.get(name, lambda c: (True, {})))))
        stack.enter_context(mock.patch.object(run, "early_cheat_check", wrap("cheats", cheats or (lambda c: None))))
        problems = run.early_checks(c)
    return problems, c, calls


class EarlyLane(unittest.TestCase):
    """G15 beside G4, G5 and the saved-cheat sample during a writer step (early_checks)."""

    def test_g15_runs_beside_the_lane_on_separate_bench_instances(self):
        lane_running, g15_running = threading.Event(), threading.Event()
        def g15(c):
            g15_running.set()
            self.assertTrue(lane_running.wait(5), "G5 did not run beside G15")
            return True, {"honest_reference": {}}
        def g5(c):
            lane_running.set()
            self.assertTrue(g15_running.wait(5), "G15 did not run beside G5")
            return True, {"keys": "3/3"}
        problems, c, calls = early(self, {"G15": g15, "G5": g5})
        self.assertIsNone(problems)
        self.assertEqual(calls[0], ("G3", 0, 2), "G3 rebuilds every instance before the lanes start")
        self.assertIn(("G15", 0, 2), calls, "G15 keeps the foreground pool and its reuse identity")
        self.assertEqual([x for x in calls if x[0] != "G15"][1:],
                         [("G4", 2, 1), ("G5", 2, 1), ("cheats", 2, 1)], "the lane owns instance 2, in serial order")
        self.assertEqual(set(c.early), {"G15", "G3", "G4", "G5"})
        self.assertEqual(c.early_hash, "h")

    def test_verdicts_and_feedback_match_serial(self):
        fixtures = {
            "pass": ({}, None),
            "g4": ({"G4": lambda c: (False, {"broke": "0/10"})}, None),
            "g15": ({"G15": lambda c: (False, {"worse": {"ask-everything": False}})}, None),
            "cheat": ({}, lambda c: ["Retained cheat passed after repair: x"]),
        }
        for name, (gates, cheats) in fixtures.items():
            with self.subTest(fixture=name):
                serial = early(self, gates, cheats=cheats, parallel=False)
                parallel = early(self, gates, cheats=cheats)
                self.assertEqual(parallel[0], serial[0])
                self.assertEqual(parallel[1].early, serial[1].early)
                # Serial stops at the first failure; the lanes may also finish gates it never reached.
                verdicts = lambda c: {g: v["ok"] for g, v in c.card.get("early_gates", {}).items()}
                self.assertLessEqual(verdicts(serial[1]).items(), verdicts(parallel[1]).items())

    def test_each_lane_cites_only_its_own_evidence(self):
        scopes = {}
        def g15(c):
            scopes["G15"] = c.evidence_scope; return True, {}
        def g5(c):
            scopes["G5"] = c.evidence_scope; return True, {}
        _, c, _ = early(self, {"G15": g15, "G5": g5})
        mine, theirs = scopes["G15"], scopes["G5"]
        self.assertTrue(mine("bench", "runs/x/checkpoint.json")); self.assertTrue(mine("bench", "factory-slots/1/runs/x"))
        self.assertFalse(mine("bench", "factory-slots/2/runs/x")); self.assertFalse(mine("work", "gate-details/G5.json"))
        self.assertTrue(theirs("bench", "factory-slots/2/runs/x")); self.assertFalse(theirs("bench", "runs/x"))
        self.assertFalse(theirs("work", "gate-details/G15.json")); self.assertTrue(theirs("work", "gate-details/G5.json"))
        self.assertFalse(hasattr(c, "evidence_scope"), "the foreground scope ends with the lanes")

    def test_a_failing_g15_and_a_failing_g5_are_both_reported_in_serial_order(self):
        problems, c, _ = early(self, {"G15": lambda c: (time.sleep(0.2), (False, {"lazy": "keeps up"}))[1],
                                      "G5": lambda c: (False, {"keys": "1/3"})})
        self.assertEqual(len(problems), 2)
        self.assertIn("early check G15 failed", problems[0]); self.assertIn("keeps up", problems[0])
        self.assertIn("early check G5 failed", problems[1]); self.assertIn("1/3", problems[1])
        self.assertEqual(c.early, {})
        self.assertFalse(c.card["early_gates"]["G15"]["ok"]); self.assertFalse(c.card["early_gates"]["G5"]["ok"])

    def test_serial_when_parallel_work_is_not_permitted(self):
        for name, options, reason in (("flag", dict(parallel=False), None), ("one worker", dict(bench_workers=1), None),
                                      ("dry run", dict(dry_run=True), "dry run"), ("memory", {}, "memory allowance")):
            with self.subTest(name):
                problems, c, calls = early(self, {}, overlap=reason, **options)
            self.assertIsNone(problems)
            workers = 1 if name == "one worker" else 2
            self.assertEqual(calls, [(g, 0, workers) for g in ("G15", "G3", "G4", "G5", "cheats")])
        c = types.SimpleNamespace(args=types.SimpleNamespace(parallel_gates=True, bench_workers=2))
        self.assertIsNone(run.early_lane(c), "outside the engine the flag is off")
        c.args.parallel_gates = False; c.engine = object()
        self.assertIsNone(run.early_lane(c), "an explicit false pin")

    def test_instances_not_prepared_after_g3_run_the_rest_serially(self):
        problems, _, calls = early(self, {}, slots=2)
        self.assertIsNone(problems)
        self.assertEqual(calls, [(g, 0, 2) for g in ("G3", "G15", "G4", "G5", "cheats")])

    def test_a_g3_failure_stops_before_g15(self):
        problems, c, calls = early(self, {"G3": lambda c: (False, {"problems": ["setup"]})})
        self.assertEqual([x[0] for x in calls], ["G3"])
        self.assertIn("early check G3 failed", problems[0]); self.assertEqual(c.early, {})

    def test_engine_snapshots_wait_for_the_join_and_a_retry_resumes(self):
        problems, c, _ = early(self, {"G15": lambda c: (time.sleep(0.2), (True, {}))[1]})
        self.assertIsNone(problems)
        # G3's snapshot publishes at once; the four inside the section publish once, after the join.
        self.assertEqual(c.published, [0, 0])
        self.assertEqual(c.engine.concurrent_sections, 0)
        self.assertFalse(c.engine.checkpoint_deferred)
        again = early(self, {})
        self.assertEqual(again[1].early.keys(), c.early.keys())

    def test_a_g15_crash_cancels_the_lane_and_leaves_the_section(self):
        cancelled = threading.Event()
        def g4(c):
            self.assertTrue(c.role_cancel.wait(5), "the lane was not cancelled")
            cancelled.set()
            raise run.BudgetError("cancelled")
        def g15(c):
            time.sleep(0.1); raise RuntimeError("strategy crashed")
        with self.assertRaisesRegex(RuntimeError, "strategy crashed"):
            early(self, {"G15": g15, "G4": g4})
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.c.published, [0], "only G3's snapshot: neither crashed gate requested one")
        self.assertEqual(self.c.engine.concurrent_sections, 0)

    def test_a_lane_crash_is_raised_after_g15_finishes(self):
        finished = []
        def g15(c):
            time.sleep(0.2); finished.append("G15"); return True, {}
        with self.assertRaisesRegex(RuntimeError, "bench died"):
            early(self, {"G15": g15, "G5": lambda c: (_ for _ in ()).throw(RuntimeError("bench died"))})
        self.assertEqual(finished, ["G15"])


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
