"""A failed workflow cannot leave its last public card looking active."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "factory"))
os.environ.setdefault("BENCH", str(ROOT))

from durable import report


class FailedWorkflow(unittest.TestCase):
    def test_failure_overlays_a_stale_card_and_handles_a_missing_card(self):
        stale = {"case_id": "case-t-1", "status": "running", "stage": "writer:1", "passed": ["G1"],
                 "failed_gate": None, "writer_rounds": 1, "extensions": 0, "replacement_of": None}

        def event(workflow_id, name, **_):
            return ["case-t-1", "case-t-2"] if workflow_id == "b-t" else stale if workflow_id == "case-t-1" else None

        with patch("dbos.DBOS.get_event", side_effect=event), \
             patch("dbos.DBOS.get_workflow_status", return_value=SimpleNamespace(status="ERROR")):
            cards = report.load_cards("b-t")
        public = report.scorecard("b-t", cards)
        self.assertEqual([row["status"] for row in public["cases"]], ["engine_error", "engine_error"])
        self.assertEqual(public["cases"][0]["gates"], {"G1": "pass"})
        self.assertEqual(public["cases"][1]["stage"], "admit")


if __name__ == "__main__":
    unittest.main()
