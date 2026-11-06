"""Attempt ownership regressions; only local temporary files, no runtime workloads."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import contextlib
import json
import os
import shutil
import sys
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "bin"))
import calibration
import bench
import exam_responder
import run


class AttemptSeriesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = pathlib.Path(temporary.name)
        self.path = self.work / "strong_calibrator/results.json"
        self.identity = {"version": 1, "model": "synthetic"}

    def series(self, tries=2, probe=None):
        return calibration.AttemptSeries(self.path, self.identity, self.work, tries, "synthetic", probe=probe)

    def complete(self, series, number=1):
        ws = series.workspace(number)
        (ws / "guard").mkdir(parents=True)
        (ws / "guard/db.sql").write_text("-- synthetic guard")
        series.commit({"try": number, "solved": True, "guard_submitted": True,
                       "guard": str(ws / "guard"), "stop_reason": "completed"}, ws)
        return ws

    def test_interrupted_workspace_is_quarantined_and_not_counted(self):
        series = self.series()
        ws = series.workspace(1)
        (ws / "guard").mkdir(parents=True)
        (ws / "guard/db.sql").write_text("-- unfinished")
        resumed = self.series()
        fresh = resumed.workspace(1)
        self.assertEqual(fresh, ws)
        self.assertFalse(fresh.exists())
        self.assertEqual(len(list(ws.parent.glob("try-1-interrupted-*"))), 1)
        self.assertEqual(list(resumed.remaining()), [1, 2])
        self.assertFalse(self.path.exists())

    def test_failed_commit_cannot_advance_in_memory_or_durable_series(self):
        series = self.series()
        ws = series.workspace(1); ws.mkdir(parents=True)
        with patch.object(calibration, "atomic_results", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                series.commit({"try": 1, "solved": False, "guard_submitted": False}, ws)
        self.assertEqual(list(series.remaining()), [1, 2])
        self.assertFalse(self.path.exists())

    def test_resume_keeps_only_verified_attempts_and_collects_passes(self):
        original = self.series()
        ws = self.complete(original)
        resumed = self.series()
        self.assertEqual(list(resumed.remaining()), [2])
        self.complete(resumed, 2)
        summary, passes = resumed.finish()
        self.assertEqual((summary["tries"], summary["solved"]), (2, 2))
        self.assertEqual(passes[0], ws / "guard")
        self.assertTrue(self.series().finish()[0]["kept"])
        (ws / "guard/db.sql").write_text("-- changed")
        self.assertEqual(list(self.series().remaining()), [1, 2])
        self.assertTrue(list(self.path.parent.glob("results-unverified-*")))

    def test_identical_probe_is_adopted_once_without_copying_workspace(self):
        probe_path = self.work / "early_probe/results.json"
        probe = calibration.AttemptSeries(probe_path, self.identity, self.work, 1, "synthetic")
        ws = self.complete(probe)
        series = self.series(probe=probe_path)
        self.assertEqual(list(series.remaining()), [2])
        self.assertEqual(series.rows[0]["workspace"], str(ws))
        self.assertEqual(series.rows[0]["source"], "early_probe")
        self.assertEqual(len(json.loads(self.path.read_text())), 1)

    def test_incomplete_or_out_of_order_series_never_finishes(self):
        series = self.series()
        with self.assertRaises(ValueError): series.finish()
        with self.assertRaises(ValueError): series.workspace(2)

    def test_probe_scope_retains_budget_state_even_on_interruption(self):
        parent = types.SimpleNamespace(args=types.SimpleNamespace(bench_workers=2),
                                       pilot_passes=["retained"], budget_resumed=False)
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            with calibration.isolated_attempt_context(parent, slot=2, user="pilot") as child:
                self.assertEqual(child.args.bench_workers, 1)
                child.pilot_passes.append("probe pass")
                child.budget_resumed = True
                child.force_budget_resume = True
                raise RuntimeError("interrupted")
        self.assertTrue(parent.budget_resumed)
        self.assertTrue(parent.force_budget_resume)
        self.assertEqual(parent.args.bench_workers, 2)
        self.assertEqual(parent.pilot_passes, ["retained"])
        self.assertFalse(hasattr(parent, "factory_slot"))


class ModelInterruptionTests(unittest.TestCase):
    def exercise(self, reason, *, probe=False, real_budget=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            c = types.SimpleNamespace(
                work=root / "work", case=root / "case", seed=1, card={}, pilot_passes=[],
                args=types.SimpleNamespace(pilot_tries=2 if real_budget else 1, pilot_runs=1, calibrator_minutes=1,
                                          resume=None, bench_workers=2),
                models={"strong_calibrator": ["synthetic"], "reviewers": [["synthetic-reviewer"]]},
                budget_resumed=False, force_budget_resume=False)
            c.work.mkdir(); (c.case / "base").mkdir(parents=True)
            c.ledger = c.work / "budget.json"
            home = root / "pilot"; home.mkdir()
            calls = []
            def model(call_context, *args, **kwargs):
                calls.append(call_context)
                self.assertIsNot(call_context, c)
                self.assertEqual(call_context.exam_owner_models, c.models["reviewers"][0])
                if real_budget:
                    import budget
                    events = [{'type': 'thread.started', 'thread_id': str(len(calls))},
                              {'type': 'turn.started'},
                              {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'done'}},
                              {'type': 'turn.completed', 'usage': {'input_tokens': 10,
                                   'cached_input_tokens': 0, 'output_tokens': 1}}]
                    payload = ''.join(json.dumps(e) + '\n' for e in events).encode()
                    budget.run_budgeted([sys.executable, '-c', f'import os; os.write(1, {payload!r})'],
                        root, os.environ.copy(), c.work / ('transcript-' + str(len(calls))), c.ledger, 3,
                        containment=False, driver='codex', configured_model='codex/gpt-6.1-sol',
                        max_calls=1 if len(calls) == 1 else 10,
                        resume=call_context.force_budget_resume, concurrent=True)
                    call_context.budget_resumed = True
                    call_context.force_budget_resume = False
                    return 0
                call_context.budget_resumed = True
                # Capped attempts must override this False after propagation.
                call_context.force_budget_resume = reason == "provider_limit"
                raise run.BudgetError(reason)
            def shell(context, argv, **kwargs):
                if argv[:3] == ["sudo", "cp", "-a"] and pathlib.Path(argv[3]).exists():
                    shutil.copytree(argv[3], argv[4])
                return 0
            def shred(path, **kwargs):
                if path.exists(): shutil.rmtree(path)
            def delivery(case, bench_root, workspace, **kwargs):
                workspace.mkdir(parents=True)
                (workspace / "promise.md").write_text("synthetic")
            with contextlib.ExitStack() as stack:
                replacements = [
                    (run, "calibration_identity", lambda *a, **k: {"synthetic": True}),
                    (run, "prepare_delivery", delivery), (run, "sh", shell),
                    (run, "shred_tree", shred), (run, "model_call", model),
                    (run, "pilot_home", lambda user: home), (run, "prompt", lambda *a: "synthetic"),
                    (bench, "reset", lambda *a, **k: None), (bench, "load_scenario", lambda *a: {}),
                    (bench, "inventory_services", lambda *a: []),
                    (exam_responder, "owner_channel", lambda *a: contextlib.nullcontext("")),
                    (run, "make_pilots", lambda *a: None), (run, "pilot_wall", lambda *a, **k: None),
                    (run, "g10_overlap_reason", lambda *a: "serial"), (run, "log", lambda *a: None),
                    # budget shares subprocess: Darwin cancellation may inspect returncode.
                    (run.subprocess, "run", lambda argv, **k: run.subprocess.CompletedProcess(argv, 0)),
                ]
                for owner, name, value in replacements:
                    stack.enter_context(patch.object(owner, name, value))
                if probe:
                    run.early_probe(c)
                elif reason == "provider_limit":
                    with self.assertRaisesRegex(run.BudgetError, reason):
                        run.calibrate(c, "strong_calibrator")
                else:
                    result = run.calibrate(c, "strong_calibrator")
                    self.assertEqual((result["tries"], result["solved"]), (2 if real_budget else 1, 0))
            self.assertEqual(len(calls), 2 if real_budget else 1)
            self.assertTrue(c.budget_resumed)
            self.assertEqual(c.force_budget_resume, not real_budget)
            folder = "early_probe" if probe else "strong_calibrator"
            receipt = c.work / folder / "results.json"
            if reason == "provider_limit":
                self.assertFalse(receipt.exists(), "interruption is not a completed failed attempt")
                if probe: self.assertEqual("BudgetError", c.card["early_probe"]["skipped"])
            else:
                rows = json.loads(receipt.read_text())
                self.assertEqual(len(rows), 2 if real_budget else 1)
                if real_budget:
                    self.assertEqual(rows[1]["stop_reason"], "completed")
                    self.assertEqual(json.loads(c.ledger.read_text())["terminal_stop"], "complete")
                self.assertEqual(rows[0]["stop_reason"], "time_limit" if reason == "timeout" else "call_limit")
            self.assertEqual(c.args.bench_workers, 2)

    def test_calibrate_continues_after_priced_subscription_cap(self):
        self.exercise('call_limit', real_budget=True)

    def test_calibrate_propagates_budget_flags_before_handling_model_stop(self):
        for reason in ("provider_limit", "timeout", "call_limit"):
            with self.subTest(reason=reason): self.exercise(reason)

    def test_early_probe_propagates_nested_model_budget_flags(self):
        for reason in ("provider_limit", "timeout", "call_limit"):
            with self.subTest(reason=reason): self.exercise(reason, probe=True)


if __name__ == "__main__": unittest.main()
