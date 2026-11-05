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
from durable.classify import PUBLISHED_REASONS
from durable.contract import ContractError


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

    def test_only_recorded_verified_seal_survives_a_failed_workflow(self):
        stale = {"status": "sealed", "stage": "sealed", "passed": ["G1"], "failed_gate": None,
                 "writer_rounds": 1, "extensions": 0, "replacement_of": None,
                 "hard": True, "cleanup_error": True}
        seal = {"archive": {"digest": "a" * 64, "kind": "sealed"}, "hard": True}

        def event(workflow_id, name, **_):
            if workflow_id == "b-t":
                return ["case-t-1", "case-t-2", "case-t-3"]
            if name == "card":
                return dict(stale, case_id=workflow_id)
            if name == "verified_seal" and workflow_id == "case-t-1":
                return seal
            if name == "verified_seal" and workflow_id == "case-t-2":
                return {"archive": {"digest": "a" * 64, "kind": "case"}, "hard": True}
            return None

        with patch("dbos.DBOS.get_event", side_effect=event), \
             patch("dbos.DBOS.get_workflow_status", return_value=SimpleNamespace(status="ERROR")):
            cards = report.load_cards("b-t")
        public = report.scorecard("b-t", cards)
        self.assertEqual([row["status"] for row in public["cases"]], ["sealed", "engine_error", "engine_error"])
        self.assertEqual(public["sealed"], 1)
        self.assertIs(public["cases"][0]["cleanup_error"], True)
        self.assertNotIn("cleanup_error", public["cases"][1])
        self.assertNotIn("cleanup_error", public["cases"][2])

    def test_admission_waits_and_cleanup_error_are_public_without_scoring_a_wait(self):
        base = {"case_id": "case-t-1", "stage": "admit", "passed": [], "failed_gate": None,
                "writer_rounds": 0, "extensions": 0, "replacement_of": None}
        cards = [dict(base, case_id=f"case-t-{i}", status=status) for i, status in enumerate(
            ("pending_admission", "waiting_for_worker", "not_admitted"), 1)]
        cards.append(dict(base, case_id="case-t-4", status="sealed", stage="sealed", hard=True,
                          cleanup_error=True))
        public = report.scorecard("b-t", cards)
        self.assertEqual(public["sealed"], 1)
        self.assertEqual([row["status"] for row in public["cases"]],
                         ["pending_admission", "waiting_for_worker", "not_admitted", "sealed"])
        self.assertIs(public["cases"][-1]["cleanup_error"], True)
        self.assertIn("cleanup unconfirmed", report.render_text(public))

    def test_cleanup_error_must_be_a_boolean_on_a_sealed_card(self):
        base = {"case_id": "case-t-1", "status": "sealed", "stage": "sealed", "passed": [],
                "failed_gate": None, "writer_rounds": 0, "extensions": 0, "replacement_of": None,
                "hard": False}
        for value in (1, "yes", None):
            with self.subTest(value=value), self.assertRaises(ContractError):
                report.case_entry(dict(base, cleanup_error=value))
        with self.assertRaises(ContractError):
            report.case_entry(dict(base, status="running", cleanup_error=True))

    def test_worker_creation_wait_shows_only_fixed_public_reasons(self):
        base = {"case_id": "case-t-1", "status": "waiting_for_worker", "stage": "admit", "passed": [],
                "failed_gate": None, "writer_rounds": 0, "extensions": 0, "replacement_of": None}
        for reason in ("infra:worker_create_failed", "infra:worker_create_unknown"):
            with self.subTest(reason=reason):
                self.assertEqual(report.case_entry(dict(base, reason=reason), PUBLISHED_REASONS)["reason"], reason)
        self.assertIsNone(report.case_entry(dict(base, reason="infra:private_provider_text"), PUBLISHED_REASONS)["reason"])

    def test_credential_wait_is_public_with_a_fixed_reason(self):
        card = {"case_id": "case-t-1", "status": "waiting_for_credentials", "stage": "writer:1", "passed": [],
                "failed_gate": None, "writer_rounds": 0, "extensions": 0, "replacement_of": None,
                "reason": "router:credential_expiring"}
        row = report.case_entry(card, PUBLISHED_REASONS)
        self.assertEqual((row["status"], row["reason"]), ("waiting_for_credentials", "router:credential_expiring"))


if __name__ == "__main__":
    unittest.main()
