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

    def check(self, ledger, row=None):
        """run_budgeted's check_limits condition for the running reserved call `row` (each listed call)."""
        rows = [row] if row else [r for r in ledger['invocation_reservations'].values() if r['state'] == 'pending']
        return any(budget.reservation_exceeded(ledger, r['lease_id']) for r in rows)

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
        other = self.reserve(self.lease(2), Decimal(6))
        ledger = self.stream(row, 5.0)   # one dollar past its reservation, with no slack left
        self.assertTrue(self.check(ledger, row))
        self.assertFalse(self.check(ledger, other))

    def test_a_late_booking_elsewhere_does_not_stop_a_call_within_its_own_reservation(self):
        # b5521c, 7 November: calls holding the attempt's remaining funding were stopped
        # mid-admission when spend landed outside them after they were admitted.
        row = self.reserve(self.lease(1), budget.available_invocation_funding(self.path, self.attempt))
        ledger = json.loads(self.path.read_text())
        ledger['events'].append({'id': uuid.uuid4().hex, 'cost': 0.25})   # settled elsewhere, after admission
        ledger['cost'] += 0.25
        self.path.write_text(json.dumps(ledger))
        ledger = self.stream(row, 0.5)
        self.assertFalse(self.check(ledger, row))
        # The next call still cannot reserve past the attempt: admission keeps the whole-attempt bound.
        with self.assertRaises(budget.BudgetError):
            self.reserve(self.lease(2), Decimal('0.01'))

    def test_a_listed_event_missing_from_the_ledger_stops_the_call(self):
        row = self.reserve(self.lease(1), Decimal(4))
        ledger = json.loads(self.path.read_text())
        ledger['invocation_reservations'][row['lease_id']]['event_ids'].append('gone')
        self.assertTrue(self.check(ledger, row))

    def test_unknown_spend_still_stops_the_call(self):
        row = self.reserve(self.lease(1), Decimal(4))
        ledger = json.loads(self.path.read_text())
        ledger['events'].append({'id': uuid.uuid4().hex, 'cost': None})
        self.path.write_text(json.dumps(ledger))
        self.assertTrue(self.check(ledger, row))


if __name__ == '__main__':
    unittest.main()
