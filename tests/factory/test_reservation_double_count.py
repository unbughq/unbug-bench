"""A running call's spend must not count twice against its own reservation (7 November)."""
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'factory'), str(Path(__file__).resolve().parents[2] / 'bin')]
import budget


class RunningReservation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'continuation-budget.json'
        self.path.write_text(json.dumps({'calls': 0, 'events': [], 'cost': 0}))
        self.attempt = SimpleNamespace(key='case/1/admit/2', baseline_spent_usd=0, ceiling_usd=10)

    def lease(self, n):
        return SimpleNamespace(lease_id=f'{n:032x}', route='openrouter/minimax/minimax-m3.1-flash',
                               account='openrouter-key', billing='paid', pool='openrouter-key', family='minimax')

    def reserve(self, lease, maximum):
        return budget.reserve_invocation(self.path, lease, maximum, attempt=self.attempt,
                                         operation_id=str(uuid.uuid4()), call_name='builder-selection-1')

    def stream(self, row, cost):
        """What run_budgeted writes while the call is running: bound by lease and invocation, not yet listed."""
        ledger = json.loads(self.path.read_text())
        ledger['events'].append({'id': uuid.uuid4().hex, 'cost': cost, 'lease_id': row['lease_id'],
                                 'invocation_id': row['invocation_id']})
        ledger['cost'] += cost
        self.path.write_text(json.dumps(ledger))
        return ledger

    def check(self, ledger):
        """run_budgeted's check_limits condition for a reserved call."""
        total = budget.case_spending(ledger)['total_spent_usd']
        return budget.usd(total) + budget.outstanding_reservations(ledger) > budget.attempt_limit(ledger, self.attempt)

    def test_a_call_holding_the_whole_grant_survives_its_first_priced_event(self):
        funding = budget.available_invocation_funding(self.path, self.attempt)
        row = self.reserve(self.lease(1), funding)
        ledger = self.stream(row, 2.0)
        self.assertEqual(budget.outstanding_reservations(ledger), Decimal('8.000000000'))
        self.assertFalse(self.check(ledger), 'usage_reservation_exceeded on ordinary spend')

    def test_two_concurrent_calls_share_the_grant_without_tripping(self):
        first = self.reserve(self.lease(1), Decimal(6))
        second = self.reserve(self.lease(2), budget.available_invocation_funding(self.path, self.attempt))
        self.stream(first, 1.5)
        ledger = self.stream(second, 0.5)
        self.assertEqual(budget.outstanding_reservations(ledger), Decimal('8.000000000'))
        self.assertFalse(self.check(ledger))

    def test_spend_past_its_own_maximum_still_trips(self):
        row = self.reserve(self.lease(1), Decimal(4))
        self.reserve(self.lease(2), Decimal(6))
        ledger = self.stream(row, 5.0)   # one dollar past its reservation, with no slack left
        self.assertTrue(self.check(ledger))


if __name__ == '__main__':
    unittest.main()
