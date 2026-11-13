"""The GATES grant's G10 authority (founder 2026-11-12) funds G10's strong tries only.

Every other GATES spender (second reviewer, G16, G17, G11, the freshness top-up) keeps the old
cap: the grant less the authority, plus what of the authority the strong tries already used.
"""
from decimal import Decimal
import pathlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin")]
import budget  # noqa: E402
from budget import BudgetError  # noqa: E402


def lease():
    return SimpleNamespace(lease_id=uuid.uuid4().hex, route="claude/claude-opus-5-5", account="claude-factory-token-2",
                           billing="subscription", pool="claude-token", family="anthropic")


class G10Authority(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger = pathlib.Path(tmp.name) / "ledger.json"
        # A GATES grant of $50 case money plus the $150 authority.
        self.attempt = SimpleNamespace(key="b/c/4/gates:1/1", baseline_spent_usd=0, ceiling_usd=200.0, g10_reserve_usd=150.0)

    def reserve(self, name, usd):
        return budget.reserve_invocation(self.ledger, lease(), Decimal(usd), attempt=self.attempt,
                                         operation_id=str(uuid.uuid4()), call_name=name)

    def headroom(self, name):
        return budget.invocation_headroom(self.ledger, self.attempt, name)

    def test_other_gates_keep_the_old_cap(self):
        for name in ("reviewer-2-g8", "builder-g16-1", "attacker-freshness-1", "easy-calibrator-dedup"):
            self.assertEqual(self.headroom(name), 50)
        self.assertEqual(self.headroom("strong-calibrator-strong_calibrator-1"), 200)
        self.assertEqual(self.headroom(None), 200)   # the G10 headroom check and helper tries see it all
        with self.assertRaisesRegex(BudgetError, "grant_insufficient"):
            self.reserve("reviewer-2-g8", 51)
        self.reserve("reviewer-2-g8", 50)
        with self.assertRaisesRegex(BudgetError, "grant_insufficient"):
            self.reserve("reviewer-g17", 1)
        for i in (1, 2, 3):   # the strong tries still have their whole authority
            self.reserve(f"strong-calibrator-strong_calibrator-{i}", 50)
        with self.assertRaisesRegex(BudgetError, "grant_insufficient"):
            self.reserve("strong-calibrator-strong_calibrator-4", 1)

    def test_strong_tries_spend_the_authority_first(self):
        for i in (1, 2, 3):
            self.reserve(f"strong-calibrator-strong_calibrator-{i}", 50)
            self.assertEqual(self.headroom("reviewer-g11"), 50)   # G10's holds never shrink the old cap
        self.reserve("reviewer-owner-strong_calibrator-try-1-1", 10)                  # the exam owner a try asks is G10's too
        self.assertEqual(self.headroom("reviewer-g11"), 40)       # past its authority G10 uses the case's money

    def test_g16_and_g17_keep_the_old_cap_though_they_use_the_strong_role(self):
        for name in ("strong-calibrator-fairness-replacement-x-1", "strong-calibrator-judge_breadth-1",
                     "reviewer-owner-fairness-replacement-x-try-1-1"):
            self.assertEqual(self.headroom(name), 50)
        with self.assertRaisesRegex(BudgetError, "grant_insufficient"):
            self.reserve("strong-calibrator-judge_breadth-1", 75)
        self.reserve("strong-calibrator-judge_breadth-1", 50)
        self.assertEqual(self.headroom("strong-calibrator-early_probe-1"), 150)   # G10 keeps its $150

    def test_g10_use_is_valued_as_case_spending_values_it(self):
        # A settled Go-plan strong try costs the case $0 (its $10 list value only bounds its own call);
        # an estimated one adds its $5 gap to case spending. G10's use counts both the same way.
        go = {"id": "e1", "cost": 0, "plan_list_cost_usd": 10, "priced": "plan", "lease_id": "l1", "invocation_id": "i1"}
        rows = {lease: {"lease_id": lease, "invocation_id": inv, "call_name": f"strong-calibrator-strong_calibrator-{n}",
                        "maximum_usd": "50.000000000", "state": state, "event_ids": ids, "estimated_gap_usd": gap}
                for n, (lease, inv, state, ids, gap) in enumerate((("l1", "i1", "settled", ["e1"], "0.000000000"),
                                                                   ("l2", "i2", "estimated", [], "5.000000000")), 1)}
        ledger = {"cost": 0, "plan_list_cost_usd": 10, "events": [go], "invocation_reservations": rows}
        self.assertEqual(budget._g10_used(ledger), Decimal(budget.case_spending(ledger)["total_spent_usd"]))
        self.assertEqual(budget._g10_used(ledger), 5)

    def test_other_steps_are_unchanged(self):
        self.attempt = SimpleNamespace(key="b/c/2/writer:1/1", baseline_spent_usd=0, ceiling_usd=50.0)
        self.assertEqual(self.headroom("builder-1"), 50)
        self.reserve("builder-1", 50)


if __name__ == "__main__":
    unittest.main()
