"""bin/case_copies.py catches a copy that drifted from its source, on the public phase-2 fixture."""
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
from case_copies import problems  # noqa: E402

FIXTURE = ROOT / "cases/medusa-oversell-v2"
TASK = "harbor/medusa-oversell-v2"


class CaseCopiesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.case = pathlib.Path(temp.name) / "case"
        shutil.copytree(FIXTURE, self.case)

    def edit_json(self, rel, change):
        path = self.case / rel; data = json.loads(path.read_text()); change(data)
        path.write_text(json.dumps(data, indent=2))

    def fails(self): return problems(self.case)[0]

    def test_fixture_copies_agree(self):
        self.assertEqual(self.fails(), [])

    def test_workdir_change_payload_must_match_scenario(self):
        path = self.case / TASK / "steps/p2-request-timeout/workdir/changes/p2-request-timeout/admin.sql"
        path.write_text(path.read_text() + "-- edited only here\n")
        self.assertEqual(self.fails(), [f"{TASK}/steps/p2-request-timeout/workdir/changes/p2-request-timeout/admin.sql: "
                                        "differs from scenarios/P2/admin.sql"])
        self.edit_json(f"{TASK}/steps/s11-privacy-tuning/workdir/changes/s11-privacy-tuning/scenario.json",
                       lambda d: d.update(blind_monitors=[]))
        self.assertIn("blind_monitors differs from the scenario", self.fails()[-1])

    def test_workdir_contestant_copy_must_match_case(self):
        copy = self.case / TASK / "steps/establish/workdir/contestant.md"
        shutil.copy(self.case / "contestant.md", copy)
        self.assertEqual(self.fails(), [])
        copy.write_text(copy.read_text() + "\nA stale line.\n")
        self.assertEqual(self.fails(), [f"{TASK}/steps/establish/workdir/contestant.md: differs from case contestant.md"])

    def test_answer_key_mirrors_scenario_key(self):
        self.edit_json("answer-key.json", lambda d: d["P1"].update(correct_responses=["keep"]))
        self.assertEqual(self.fails(), ["answer-key.json P1: correct_responses differs from the scenario key"])

    def test_answer_key_prose_drift_only_warns(self):
        self.edit_json("answer-key.json", lambda d: d["P1"].update(judge_checks=["reworded"]))
        fails, warns = problems(self.case)
        self.assertEqual(fails, [])
        self.assertIn("answer-key.json P1: judge_checks differs from the scenario key", warns)

    def test_window_key_keeps_earlier_intent_checks(self):
        self.edit_json(f"{TASK}/steps/quiet/window.json", lambda d: d["key"].update(intent_checks=[]))
        self.assertEqual(self.fails(), [f"{TASK}/steps/quiet/window.json key: intent_checks are not the step's cumulative set"])

    def test_window_hook_drift_warns(self):
        self.edit_json(f"{TASK}/steps/quiet/window.json", lambda d: d["traffic_hooks"].update(BASE="// own recipe\n"))
        fails, warns = problems(self.case)
        self.assertEqual(fails, [])
        self.assertIn(f"{TASK}/steps/quiet/window.json: traffic_hooks.BASE is not its scenario's hooks.mjs", warns)


if __name__ == "__main__":
    unittest.main()
