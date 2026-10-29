"""Synthetic fairness decisions: no providers, case secrets or cloud resources."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
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

    def test_diagnosis_requires_every_try_and_concrete_evidence(self):
        attempts = [{"try": 1}, {"try": 2}]
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


if __name__ == "__main__":
    unittest.main()
