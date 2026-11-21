"""Synthetic fairness decisions: no providers, case secrets or cloud resources."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import fairness


class FairnessTests(unittest.TestCase):
    def context(self, root):
        return types.SimpleNamespace(
            work=root, args=types.SimpleNamespace(runs=10, pilot_runs=5),
            models={"builder": ["writer"], "strong_calibrator": ["solver"],
                    "reviewers": [["reviewer"]]},
            card={"calibrators": {"strong": {"tries": 2, "solved": 0}}})

    def test_breadth_acceptance_and_fail_closed_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = self.context(pathlib.Path(tmp))
            runner = types.SimpleNamespace(family=lambda x: x, make_pilots=Mock(),
                                           calibrate=Mock(return_value={"solved": 1}))
            self.assertTrue(fairness.breadth(c, runner)[0])
            call = runner.calibrate.call_args
            self.assertIs(call.args[0], c)
            self.assertEqual(c.args.pilot_runs, 5)
            self.assertEqual(call.kwargs["runs"], 10)
            self.assertFalse(call.kwargs["collect_passes"])
            self.assertEqual(call.kwargs["exposure"], "statement")
            runner.calibrate.return_value = {"solved": 0}
            for counts, passes in [(None, False), ({"wrong_fix": 1}, True),
                                   ({"wrong_fix": 0, "judge_too_narrow": 1}, False)]:
                with patch.object(fairness, "review_attempts", return_value=counts):
                    ok, info = fairness.breadth(c, runner)
                    self.assertEqual(ok, passes)
                    self.assertEqual(info["review_inconclusive"], counts is None)

    def test_a_capped_try_ends_the_review_before_replacements_are_bought(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp).resolve()
            c = self.context(root)
            c.card = {}
            rows = []
            for i, capped in ((1, False), (2, True)):
                workspace = root / f"try-{i}"; workspace.mkdir()
                if capped: (workspace / "guard").mkdir(); (workspace / "guard/db.sql").write_text("select 1")
                rows.append({"try": i, "workspace": str(workspace), "solved": False,
                             "stop_reason": "time_limit", "errors": 0, "checked_runs": 0, "solved_runs": 0})
            (root / "strong_calibrator").mkdir()
            (root / "strong_calibrator/results.json").write_text(json.dumps(rows))
            runner = types.SimpleNamespace(
                family=lambda x: x, jload=lambda path, default=None: json.loads(pathlib.Path(path).read_text())
                if pathlib.Path(path).is_file() else default, make_pilots=Mock(), calibrate=Mock())
            c.models["reviewers"] = [["reviewer"]]
            with patch("run_validity.require_valid"):
                self.assertIsNone(fairness.review_attempts(c, runner, "G17", "strong_calibrator"))
            runner.make_pilots.assert_not_called()
            runner.calibrate.assert_not_called()

    def test_diagnosis_requires_every_try_and_concrete_evidence(self):
        attempts = [{"try": i, "solved": False, "guard_submitted": True,
                     "stop_reason": "completed", "checked_runs": 1, "solved_runs": 0, "errors": 0}
                    for i in (1, 2)]
        rows = [{"try": i, "label": "wrong_fix", "finding": "incorrect update",
                 "evidence": "guard/db.sql"} for i in (1, 2)]
        counts = fairness.verdict({"tries": rows}, attempts)
        self.assertEqual(counts["wrong_fix"], 2)
        self.assertIsNone(fairness.verdict({"inconclusive": True, "reason": "uncertain", "tries": rows}, attempts))
        self.assertIsNone(fairness.verdict({"tries": rows[:1]}, attempts))
        self.assertIsNone(fairness.verdict({"tries": [rows[0], rows[0]]}, attempts))
        self.assertIsNone(fairness.verdict({"tries": [{**rows[0], "evidence": ""}, rows[1]]}, attempts))
        with tempfile.TemporaryDirectory() as tmp:
            c = self.context(pathlib.Path(tmp))
            with patch.object(fairness, "review_attempts", return_value=counts):
                self.assertTrue(fairness.diagnose(c, None)[0])
                self.assertEqual(c.card["difficulty"], "hard")
            for bad in (None, {"wrong_fix": 1, "missing_info": 1},
                        {"wrong_fix": 2, "missing_info": 1}):
                c.card.pop("difficulty", None)
                with patch.object(fairness, "review_attempts", return_value=bad):
                    self.assertFalse(fairness.diagnose(c, None)[0])
                    self.assertNotIn("difficulty", c.card)


class SubmittedAtTheBellTests(unittest.TestCase):
    """Founder 2026-11-14: a fix handed in at the time limit is graded, not capped."""
    # Shape of 2abb0a's judge_breadth/results.json row, stored before the rule changed.
    LEGACY = {"try": 1, "solved": False, "stop_reason": "time_limit", "guard_submitted": True,
              "checked_runs": 10, "solved_runs": 0, "errors": 0, "bench_crash": None,
              "scientific_outcome": "capped"}

    def test_time_limited_checked_fix_is_a_demonstrated_failure(self):
        from calibration import scientific_outcome
        row = {k: v for k, v in self.LEGACY.items() if k != "scientific_outcome"}
        self.assertEqual(scientific_outcome(row), "demonstrated_failure")
        self.assertEqual(scientific_outcome({**row, "solved_runs": 3}), "demonstrated_failure")
        self.assertEqual(scientific_outcome({**row, "stop_reason": "call_limit"}), "capped")
        self.assertEqual(scientific_outcome({**row, "guard_submitted": False}), "no_submission")
        self.assertEqual(scientific_outcome({**row, "checked_runs": 0}), "capped")
        self.assertEqual(scientific_outcome({**row, "errors": None}), "capped")
        from run_validity import InvalidInfra
        with self.assertRaises(InvalidInfra):
            scientific_outcome({**row, "errors": 1})

    def test_legacy_capped_row_goes_to_review_and_accepts_wrong_fix(self):
        from calibration import attempt_summary
        self.assertEqual(attempt_summary([dict(self.LEGACY)])["scientific"]["outcomes"]["demonstrated_failure"], 1)
        for other in ({**self.LEGACY, "stop_reason": "call_limit", "scientific_outcome": "demonstrated_failure"},
                      {**self.LEGACY, "scientific_outcome": "unknown"}):
            with self.assertRaises(ValueError):
                attempt_summary([other])
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp).resolve()
            c = FairnessTests.context(None, root)
            c.case = root / "case"
            workspace = root / "try-1"
            (workspace / "guard").mkdir(parents=True)
            (workspace / "guard/db.sql").write_text("select 1")
            (workspace / "execution.json").write_text("{}")
            (root / "judge_breadth").mkdir()
            (root / "judge_breadth/results.json").write_text(json.dumps([{**self.LEGACY, "workspace": str(workspace)}]))
            runner = types.SimpleNamespace(
                family=lambda x: x, jload=lambda path, default=None: json.loads(pathlib.Path(path).read_text())
                if pathlib.Path(path).is_file() else default, make_pilots=Mock(), calibrate=Mock(),
                seed_tampered=lambda records: False)
            seen = []
            def review(c, r, gate, inputs, text, validate):
                seen.append(json.loads((inputs["attempts"] / "attempts.json").read_text()))
                return validate({"tries": [{"try": 1, "label": "wrong_fix", "finding": "wrong rows",
                                            "evidence": "guard/db.sql"}]})
            with patch("run_validity.require_valid"), patch("independent_review.review", review):
                counts = fairness.review_attempts(c, runner, "G16", "judge_breadth")
            self.assertEqual(counts, {"wrong_fix": 1, "missing_info": 0, "judge_too_narrow": 0})
            self.assertEqual(seen[0][0]["scientific_outcome"], "demonstrated_failure")
            runner.calibrate.assert_not_called()

    def test_a_seed_tamper_try_is_reviewed_as_failed_and_not_rerun(self):
        """2a7b2a-h4 (11-21): run.calibrate scored the tamper try failed; G17 must not rerun it into InfrastructureExhausted."""
        import run
        tamper = {"errors": [{"stage": "reset", "message": "Baseline changed during application startup"},
                             {"stage": "installation", "message": "Frozen installation identity changed"}],
                  "checker": {"valid": False}, "judge": {"invalid": "reset failed", "paths": {}, "checks": {}, "pass": False}}
        row = {"try": 1, "solved": False, "stop_reason": "completed", "guard_submitted": True, "checked_runs": 1,
               "solved_runs": 0, "errors": 0, "seed_data_changed": True, "scientific_outcome": "demonstrated_failure"}
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp).resolve()
            c = FairnessTests.context(None, root)
            c.case = root / "case"
            workspace = root / "try-1"
            (workspace / "guard").mkdir(parents=True)
            (workspace / "guard/db.sql").write_text("UPDATE inventory_level SET reserved_quantity = 5;")
            (workspace / "execution.json").write_text(json.dumps({"summary": {"runs": 1, "error_runs": 1, "invalid_runs": 1},
                                                                  "records": [tamper]}))
            (root / "strong_calibrator").mkdir()
            (root / "strong_calibrator/results.json").write_text(json.dumps([{**row, "workspace": str(workspace)}]))
            runner = types.SimpleNamespace(
                family=lambda x: x, jload=lambda path, default=None: json.loads(pathlib.Path(path).read_text())
                if pathlib.Path(path).is_file() else default, make_pilots=Mock(), calibrate=Mock(),
                checkpoint=Mock(side_effect=AssertionError("rerun")), seed_tampered=run.seed_tampered)
            def review(c, r, gate, inputs, text, validate):
                return validate({"tries": [{"try": 1, "label": "wrong_fix", "finding": "rewrites seeded data",
                                            "evidence": "guard/db.sql"}]})
            with patch("independent_review.review", review):
                counts = fairness.review_attempts(c, runner, "G17", "strong_calibrator")
            self.assertEqual(counts, {"wrong_fix": 1, "missing_info": 0, "judge_too_narrow": 0})
            runner.checkpoint.assert_not_called()


if __name__ == "__main__":
    unittest.main()
