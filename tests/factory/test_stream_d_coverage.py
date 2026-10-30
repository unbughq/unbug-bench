"""Coverage/receipt replay on saved ledgers; authored transition evidence."""
import copy
from decimal import Decimal
import hashlib
import json
import sys
from pathlib import Path
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import test_stream_d as replay
from test_stream_d import cards


class CoverageTests(unittest.TestCase):
    setUp = replay.AccountingTests.setUp
    ledger = replay.AccountingTests.ledger
    reserve = replay.AccountingTests.reserve
    receipt = replay.AccountingTests.receipt
    wait = replay.AccountingTests.wait
    # Reuse the real-ledger harness without repeating its tests.
    def test_legacy_coverage_is_pure_and_uses_raw_total(self):
        for suffix in ('5813be', 'e15450'):
            ledger = copy.deepcopy(next(r['card']['continuation_budget'] for r in cards()
                                       if r['card']['case'].endswith(suffix)))
            before = copy.deepcopy(ledger)
            projection = budget.usage_coverage(ledger)
            self.assertIsNotNone(projection)
            self.assertGreaterEqual(Decimal(projection['covered_total_usd']),
                                    budget.usd(budget.case_spending(ledger)['total_spent_usd']))
            self.assertEqual(projection['invocations'], [])
            self.assertEqual(ledger, before)

    def test_streamed_partial_reduces_exactly_one_maximum_and_unknowns_fold(self):
        lease, row = self.reserve()
        with budget.ledger_transaction(self.path) as ledger:
            ledger['events'].append({'id': 'streamed', 'cost': 3, 'invocation_id': row['invocation_id'],
                                     'lease_id': lease.lease_id})
            ledger['cost'] += 3
            marker = {'invocation_id': row['invocation_id'], 'lease_id': lease.lease_id}
            ledger['unpriced_invocations'] = [marker, marker.copy()]
        ledger = self.ledger(); before = copy.deepcopy(ledger)
        coverage = budget.usage_coverage(ledger)
        self.assertEqual(coverage['invocations'][0]['booked_usd'], '3.000000000')
        self.assertEqual(coverage['invocations'][0]['remaining_usd'], '7.000000000')
        baseline = Decimal(budget.usage_coverage(self.original)['covered_total_usd'])
        self.assertEqual(Decimal(coverage['covered_total_usd']), baseline + 10)
        self.assertEqual(ledger, before)
        ledger['unpriced_invocations'][0]['lease_id'] = 'missing'
        self.assertIsNone(budget.usage_coverage(ledger))

    def test_estimate_to_final_receipt_retained_once_and_metadata_never_books(self):
        lease, row = self.reserve()
        call = self.receipt(lease, [('part', 3)])
        wait = self.wait(lease, call)
        budget.settle(wait, work=self.work, ledger_path=self.path)
        self.receipt(lease, [('part', 3), ('final', 5)], final=True)
        budget.settle(wait, work=self.work, ledger_path=self.path)
        ledger = self.ledger(); receipt = ledger['reconciled_decreases'][0]
        self.assertEqual(receipt['released_usd'], '2.000000000')
        self.assertEqual(receipt['wait_id'], wait['wait_id'])
        retained = self.work / 'usage-receipts/final' / (receipt['receipt_sha256'] + '.json')
        self.assertEqual(hashlib.sha256(retained.read_bytes()).hexdigest(), receipt['receipt_sha256'])
        self.assertEqual(json.loads(retained.read_text())['lease_id'], lease.lease_id)
        before = budget.case_spending(ledger)
        ledger['usage_coverage'] = {'ignored': True}
        ledger['reconciled_decreases'] *= 2
        self.assertEqual(budget.case_spending(ledger), before)
        self.receipt(lease, [('part', 3), ('final', 5), ('later', 1)], final=True)
        budget.settle(wait, work=self.work, ledger_path=self.path)
        budget.settle(wait, work=self.work, ledger_path=self.path)
        self.assertEqual(len(self.ledger()['reconciled_decreases']), 1)
        self.assertTrue(retained.is_file())

    def test_other_unknown_does_not_suppress_release_and_pending_settle_emits_none(self):
        l1, row1 = self.reserve(); l2, row2 = self.reserve()
        p1 = self.receipt(l1, [('known', 3)])
        budget.settle(self.wait(l1, p1), work=self.work, ledger_path=self.path)
        with budget.ledger_transaction(self.path) as ledger:
            ledger['unpriced_invocations'] = [{'invocation_id': row2['invocation_id'], 'lease_id': l2.lease_id}]
        self.receipt(l1, [('known', 3), ('final', 5)], final=True)
        budget.complete_invocation(self.work, self.path, l1.lease_id)
        self.assertIsNone(budget.case_spending(self.ledger())['total_spent_usd'])
        self.assertEqual(self.ledger()['reconciled_decreases'][0]['released_usd'], '2.000000000')
        self.receipt(l2, [('second', 1)], final=True)
        budget.complete_invocation(self.work, self.path, l2.lease_id)
        self.assertIsNotNone(budget.case_spending(self.ledger())['total_spent_usd'])
        self.assertEqual(len(self.ledger()['reconciled_decreases']), 1)

    def test_wait_replay_retains_new_lease_provenance(self):
        first, _ = self.reserve(); later, row = self.reserve(); partial, _ = self.reserve()
        budget.reconcile_reservations(self.work, self.path, exclude_leases=(first.lease_id,))
        wait = self.wait(first, self.receipt(first, [('first', 1)]))
        budget.settle(wait, work=self.work, ledger_path=self.path)
        self.receipt(later, [('late-final', 2)], final=True)
        self.receipt(partial, [('late-partial', 3)])
        budget.settle(wait, work=self.work, ledger_path=self.path)
        ledger = self.ledger()
        self.assertEqual(ledger['wait_settlements'][wait['wait_id']]['lease_ids'],
                         sorted([first.lease_id, later.lease_id, partial.lease_id]))
        decrease, = ledger['reconciled_decreases']
        self.assertEqual((decrease['invocation_id'], decrease['wait_id'], decrease['released_usd']),
                         (row['invocation_id'], wait['wait_id'], '8.000000000'))
        coverage = budget.usage_coverage(ledger)
        pending = next(r for r in coverage['invocations'] if r['lease_id'] == partial.lease_id)
        self.assertEqual(pending['wait_ids'], [wait['wait_id']])
        budget.settle(wait, work=self.work, ledger_path=self.path)
        self.assertEqual(self.ledger(), ledger)

    def test_unreserved_zero_usage_denial_keeps_coverage_available(self):
        from types import SimpleNamespace
        denied = SimpleNamespace(lease_id=str(uuid.uuid4()))
        relative = self.receipt(denied, [], final=True)
        path = self.work / relative
        receipt = json.loads(path.read_text()); receipt['outcome'] = 'denied'
        path.write_text(json.dumps(receipt))
        wait = self.wait(denied, relative)
        before = budget.usage_coverage(self.ledger())
        budget.settle(wait, work=self.work, ledger_path=self.path)
        self.assertEqual(self.ledger()['wait_settlements'][wait['wait_id']]['lease_ids'], [])
        self.assertEqual(budget.usage_coverage(self.ledger()), before)

    def test_malformed_or_ambiguous_coverage_fails_closed(self):
        lease, row = self.reserve(); l2, _ = self.reserve()
        original = self.ledger()
        for mutate in (
            lambda d: d['events'].append(copy.deepcopy(d['events'][0])),
            lambda d: d['events'][0].update(invocation_id=row['invocation_id'], lease_id='missing'),
            lambda d: d['invocation_reservations'][lease.lease_id].update(maximum_usd=None),
            lambda d: d.update(infrastructure_waste=[{'kind': 'infrastructure_kill', 'infrastructure_waste_usd': None}]),
            lambda d: d.update(cost=None),
        ):
            ledger = copy.deepcopy(original); mutate(ledger)
            self.assertIsNone(budget.usage_coverage(ledger))
        with budget.ledger_transaction(self.path) as ledger:
            event = ledger['events'][0]['id']
            ledger['invocation_reservations'][lease.lease_id]['event_ids'] = [event]
            ledger['invocation_reservations'][l2.lease_id]['event_ids'] = [event]
        self.assertIsNone(budget.usage_coverage(self.ledger()))
        path = self.receipt(lease, [], final=True)
        with self.assertRaisesRegex(budget.BudgetError, 'usage_event_shared'):
            budget.settle(self.wait(lease, path), work=self.work, ledger_path=self.path)

    def test_release_uninvoked_refuses_estimated_row_and_zero_release_rounding(self):
        lease, _ = self.reserve()
        budget.reconcile_reservations(self.work, self.path)
        with self.assertRaisesRegex(budget.BudgetError, 'reservation_already_invoked'):
            budget.release_uninvoked(self.path, lease.lease_id)
        # A final actual charge can round to the estimate: emit no fake receipt.
        self.receipt(lease, [('near-maximum', 9.9999999996)], final=True)
        budget.complete_invocation(self.work, self.path, lease.lease_id)
        self.assertEqual(self.ledger().get('reconciled_decreases', []), [])
        self.assertEqual(self.ledger()['invocation_reservations'][lease.lease_id]['state'], 'settled')

    def test_reestimate_preserves_one_reservation_on_sub_nanodollar_boundary(self):
        lease, row = self.reserve()
        call = self.receipt(lease, [('tiny', .0000000009)])
        wait = self.wait(lease, call)
        budget.settle(wait, work=self.work, ledger_path=self.path)
        before = budget.usage_coverage(self.ledger())
        self.receipt(lease, [('tiny', .0000000009), ('more', .0000000001)])
        budget.settle(wait, work=self.work, ledger_path=self.path)
        after = budget.usage_coverage(self.ledger())
        self.assertEqual(before['covered_total_usd'], after['covered_total_usd'])
        self.assertEqual(after['invocations'][0]['invocation_id'], row['invocation_id'])
        self.assertEqual(self.ledger().get('reconciled_decreases', []), [])

    def test_release_strings_and_rounding_boundary(self):
        lease, _ = self.reserve(9)
        call = self.receipt(lease, [('tiny', .0000000001)])
        budget.settle(self.wait(lease, call), work=self.work, ledger_path=self.path)
        self.receipt(lease, [('tiny', .0000000001), ('late', .0000000005)], final=True)
        budget.complete_invocation(self.work, self.path, lease.lease_id)
        record = self.ledger()['reconciled_decreases'][0]
        self.assertEqual(Decimal(record['released_usd']), Decimal(record['booked_before_usd']) +
                         Decimal(record['previous_estimate_usd']) - Decimal(record['actual_charge_usd']))


if __name__ == '__main__': unittest.main()
