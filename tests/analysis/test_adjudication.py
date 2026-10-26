"""Validity survives scoring, exam export and both report input formats.

Run with the analysis dependencies: python3 tests/analysis/test_adjudication.py
"""

# Keep direct execution independent of the working directory.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'analysis'))

import copy
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
import claims
import report_round

loader = importlib.machinery.SourceFileLoader("validity_exam", str(ROOT / "bin/run-exam"))
exam = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(exam)

KEY = {"correct_responses": ["keep"]}
CLAIM = {"response": "keep", "claims": [{"path": "store-checkout", "status": "protected"}]}


def checkpoint():
    return {"runs": 3, "error_runs": 0, "invalid_runs": 0, "errors": [], "key": KEY,
            "paths": {"store-checkout": {"runs": 3, "violated_runs": 0}}, "checks": {},
            "legit": {"attempted": 10, "placed": 10}, "legit_completion": 1.0}


class AdjudicationTests(unittest.TestCase):
    def test_invalid_and_legacy_checkpoints_cannot_receive_correct_response(self):
        good = checkpoint()
        self.assertTrue(claims.score(CLAIM, good, KEY)["response_correct"])
        bad_batches = [dict(good, **changes) for changes in (
            {"error_runs": 3, "invalid_runs": 3, "paths": {}, "checks": {},
             "legit": {"attempted": 0, "placed": 0}},
            {"invalid_runs": 1}, {"error_runs": 1}, {"runs": 0},
            {"runs": True}, {"invalid_runs": False}, {"errors": ["reset failed"]},
            {"error": "JudgeFailed"}, {"judge_error": 1})]
        for missing in ("runs", "error_runs", "invalid_runs"):
            legacy = dict(good); legacy.pop(missing); bad_batches.append(legacy)
        for cp in bad_batches:
            with self.subTest(cp=cp):
                scored = claims.score(CLAIM, cp, KEY)
                self.assertFalse(scored["adjudicated"])
                self.assertFalse(scored["response_correct"])
                self.assertIn("human_minutes", scored)  # retained diagnostic, not a verdict

    def test_exam_preserves_invalidity_even_when_reward_has_no_judge_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            trial = Path(tmp); step = trial / "steps/s2"
            (step / "verifier").mkdir(parents=True); (step / "artifacts").mkdir()
            cp = dict(checkpoint(), invalid_runs=3)
            (step / "verifier/checkpoint.json").write_text(json.dumps(cp))
            (step / "artifacts/claims.json").write_text(json.dumps(CLAIM))
            (step / "artifacts/manifest.json").write_text(json.dumps([
                {"source": "/app/claims.json", "destination": "artifacts/claims.json", "status": "ok"}]))
            row, _ = exam.step_card(2, {"step_name": "s2", "verifier_result": {
                "rewards": {"reward": 0, "judge_error": 0, "invalid_runs": 3}}}, trial, 0)
            self.assertEqual(row["invalid_runs"], 3)
            self.assertFalse(row["adjudicated"])
            self.assertFalse(row["response_correct"])

    def test_report_rejects_invalid_exam_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); design = report_round.read_json(report_round.make_fixture(root))
            path = next(root.glob("*.scorecard.json")); good = report_round.read_json(path)
            for changes in ({"invalid_runs": 1}, {"adjudicated": False}, {"runs": 0}):
                bad = copy.deepcopy(good); bad["trials"][0]["steps"][1].update(changes)
                path.write_text(json.dumps(bad))
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    report_round.load_results(root, design)

    def test_report_preserves_wrapper_validity_and_rejects_historical_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); design = report_round.read_json(report_round.make_fixture(root))
            score = claims.score(CLAIM, checkpoint(), KEY)
            wrapped = dict(checkpoint(), claims_score=score)
            (root / "score.json").write_text(json.dumps(wrapped))
            design["score_files"] = [dict(case=c["case"], **{"try": t}, arm=a, step=s, path="score.json")
                                    for c in design["cases"] for t in c["tries"]
                                    for a in ("B", "C") for s in c["maintenance_steps"]]
            _, audit = report_round.load_results(root, design)
            self.assertEqual(audit["included_checkpoints"], 448)
            for bad in (dict(wrapped, error_runs=1), dict(wrapped, invalid_runs=1),
                        dict(wrapped, runs=0), dict(wrapped, errors=["failed"]),
                        {k: v for k, v in score.items() if k != "adjudicated"},
                        dict(score, adjudicated=False), dict(score, invalid_runs=1)):
                (root / "score.json").write_text(json.dumps(bad))
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    report_round.load_results(root, design)
            # Standalone scoring must not erase an explicit checkpoint error.
            for error in ({"error": "JudgeFailed"}, {"judge_error": 1}):
                rescored = claims.score(CLAIM, dict(checkpoint(), **error), KEY)
                self.assertFalse(rescored["adjudicated"])
                self.assertFalse(rescored["response_correct"])
                (root / "score.json").write_text(json.dumps(rescored))
                with self.subTest(error=error), self.assertRaises(ValueError):
                    report_round.load_results(root, design)
            (root / "score.json").write_text(json.dumps(score))
            _, audit = report_round.load_results(root, design)
            self.assertEqual(audit["included_checkpoints"], 448)


if __name__ == "__main__":
    unittest.main()
