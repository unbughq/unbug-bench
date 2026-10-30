"""Real saved ledgers + D public settlement; prior ACK/holds are authored.

No real receipt transition is claimed: test_stream_d.AccountingTests helpers
supply authored receipts on saved ledgers. B asserts maps/inequalities only.
"""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import batch_accounting as accounting
import budget
import test_stream_d as d


class AccountingTests(unittest.TestCase):
    setUp = d.AccountingTests.setUp
    ledger = d.AccountingTests.ledger
    reserve = d.AccountingTests.reserve
    receipt = d.AccountingTests.receipt
    wait = d.AccountingTests.wait

    def snapshot_card(self, ledger=None):
        ledger = self.ledger() if ledger is None else ledger
        return dict(continuation_budget=ledger, case_budget=budget.case_spending(ledger))

    def facts(self, card=None, previous=None, held='1000.000000000', api=budget):
        card = self.snapshot_card() if card is None else card
        previous = dict(total_usd='0.000000000', estimated={}) if previous is None else previous
        before = deepcopy((card, previous))
        result = accounting.collection_facts(card, previous, held, api)
        self.assertEqual((card, previous), before)
        return result

    def previous(self, facts): return {k: facts[k] for k in ('total_usd', 'estimated')}

    def estimate(self):
        lease, row = self.reserve()
        wait = self.wait(lease, self.receipt(lease, [('part', 3)]))
        budget.settle(wait, work=self.work, ledger_path=self.path)
        return lease, row, wait, self.facts()

    def final(self, lease, wait):
        self.receipt(lease, [('part', 3), ('final', 5)], final=True)
        budget.settle(wait, work=self.work, ledger_path=self.path)

    def test_saved_cards_exact_outcomes_and_authored_known_variant(self):
        for suffix in ('e15450', '5813be'):
            card = deepcopy(next(r['card'] for r in d.cards() if r['card']['case'].endswith(suffix)))
            if suffix == '5813be':
                with self.assertRaisesRegex(ValueError, '^invalid_accounting_input$'): self.facts(card)
                card['case_budget'] = budget.case_spending(card['continuation_budget'])  # Authored total.
            result = self.facts(card)
            self.assertEqual(result['total_usd'], accounting.card_total(card))
            self.assertEqual(result['estimated'], {})
            with patch.object(budget, 'usage_coverage', side_effect=AssertionError('known total must not call')):
                self.assertEqual(self.facts(card), result)

    def test_estimate_release_replay_then_growing_receipt(self):
        lease, row, wait, old = self.estimate()
        self.assertEqual(old['estimated'], {row['invocation_id']: '7.000000000'})
        self.final(lease, wait)
        result = self.facts(previous=self.previous(old))
        self.assertEqual(Decimal(old['total_usd']) - Decimal(result['total_usd']), 2)
        self.assertEqual(result['estimated'], {})
        self.assertEqual([r['invocation_id'] for r in result['reconciled_decreases']], [row['invocation_id']])
        ledger = self.ledger(); ledger['reconciled_decreases'] *= 2
        self.assertEqual(self.facts(self.snapshot_card(ledger), self.previous(old)), result)
        # Host generation replay must return saved ACK; next checkpoint sees the replaced map.
        next_result = self.facts(previous=self.previous(result))
        self.assertEqual(next_result['reconciled_decreases'], [])
        before = budget.case_spending(ledger)
        ledger['reconciled_decreases'] *= 2; ledger['usage_coverage'] = {'ignored': True}
        self.assertEqual(budget.case_spending(ledger), before)
        self.receipt(lease, [('part', 3), ('final', 5), ('later', 1)], final=True)
        budget.complete_invocation(self.work, self.path, lease.lease_id)
        later = self.facts(previous=self.previous(result))
        self.assertEqual(Decimal(later['total_usd']) - Decimal(result['total_usd']), 1)
        self.assertEqual(later['reconciled_decreases'], [])

    def test_in_run_estimate_has_no_previous_release_authority(self):
        lease, row, wait, old = self.estimate(); self.final(lease, wait)
        result = self.facts()  # Prior map empty; valid current-run record contributes nothing.
        self.assertEqual(result['reconciled_decreases'], [])
        card = self.snapshot_card(); card['continuation_budget'].pop('reconciled_decreases')
        with self.assertRaisesRegex(ValueError, '^unsupported_decrease$'):
            self.facts(card, self.previous(old))

    def unknown(self):
        lease, row = self.reserve()
        with budget.ledger_transaction(self.path) as ledger:
            ledger['events'].append(dict(id='streamed', cost=3, invocation_id=row['invocation_id'], lease_id=lease.lease_id))
            ledger['cost'] += 3
            marker = dict(invocation_id=row['invocation_id'], lease_id=lease.lease_id)
            ledger['unpriced_invocations'] = [marker, marker.copy()]
        return lease, row

    def test_null_coverage_booked_three_maximum_ten_and_hold_boundary(self):
        lease, row = self.unknown()
        card = self.snapshot_card(); coverage = budget.usage_coverage(card['continuation_budget'])
        self.assertIsNone(accounting.card_total(card))
        self.assertEqual(Decimal(coverage['covered_total_usd']),
                         Decimal(budget.usage_coverage(self.original)['covered_total_usd']) + 10)
        self.facts(card, held=coverage['covered_total_usd'])
        with self.assertRaisesRegex(ValueError, '^uncovered_total$'):
            self.facts(card, held=format(Decimal(coverage['covered_total_usd']) - Decimal('.000000001'), '.9f'))
        # Stored public coverage is ignored; only D's recomputed answer is consumed.
        card['continuation_budget']['usage_coverage'] = {'covered_total_usd': '0.000000000'}
        self.assertIsNone(self.facts(card)['total_usd'])
        for change in ('maximum', 'waste'):
            bad = deepcopy(card)
            if change == 'maximum': bad['continuation_budget']['invocation_reservations'][lease.lease_id]['maximum_usd'] = None
            else: bad['continuation_budget']['infrastructure_waste'] = [{'kind': 'infrastructure_kill', 'infrastructure_waste_usd': None}]
            with self.assertRaisesRegex(ValueError, '^accounting_api_refused$'): self.facts(bad)

    def test_null_ack_replaces_estimates_then_known_receipt_qualifies_once(self):
        first, _ = self.reserve(); second, second_row = self.reserve()
        wait = self.wait(first, self.receipt(first, [('part', 3)]))
        budget.settle(wait, work=self.work, ledger_path=self.path)
        budget.reconcile_reservations(self.work, self.path)
        # Introduce an admitted unknown on a new row after the two estimates.
        third, third_row = self.reserve()
        with budget.ledger_transaction(self.path) as ledger:
            ledger['unpriced_invocations'] = [dict(invocation_id=third_row['invocation_id'], lease_id=third.lease_id)]
        unknown = self.facts()
        self.assertIsNone(unknown['total_usd'])
        self.assertTrue(unknown['estimated'])
        self.receipt(first, [('part', 3), ('final', 5)], final=True)
        budget.complete_invocation(self.work, self.path, first.lease_id)
        still_unknown = self.facts(previous=self.previous(unknown))
        self.assertIsNone(still_unknown['total_usd'])
        self.assertEqual(len(still_unknown['reconciled_decreases']), 1)
        self.assertLess(len(still_unknown['estimated']), len(unknown['estimated']))
        self.receipt(third, [('third', 1)], final=True)
        budget.complete_invocation(self.work, self.path, third.lease_id)
        known = self.facts(previous=self.previous(still_unknown))
        self.assertIsNotNone(known['total_usd'])
        self.assertEqual(known['reconciled_decreases'], [])
        self.assertEqual(set(known['estimated']), {second_row['invocation_id']})

    def test_rounding_bound_with_release_empty_map_and_no_qualifying_record(self):
        lease, row, wait, old = self.estimate(); self.final(lease, wait)
        card = self.snapshot_card(); total = Decimal(accounting.card_total(card))
        for estimates, release in ((old['estimated'], Decimal(2)), ({}, Decimal(0)),
                                  ({str(uuid.uuid4()): '0.000000000'}, Decimal(0))):
            epsilon = Decimal(2 * len(estimates) + 1) / Decimal(10**9)
            prior = dict(total_usd=format(total + release + epsilon, '.9f'), estimated=estimates)
            self.facts(card, prior)
            prior['total_usd'] = format(total + release + epsilon + Decimal('.000000001'), '.9f')
            with self.assertRaisesRegex(ValueError, '^unsupported_decrease$'): self.facts(card, prior)

    def test_sub_nanodollar_reestimate_and_zero_rounded_release(self):
        lease, row = self.reserve()
        wait = self.wait(lease, self.receipt(lease, [('tiny', .0000000009)]))
        budget.settle(wait, work=self.work, ledger_path=self.path)
        old = self.facts()
        self.receipt(lease, [('tiny', .0000000009), ('more', .0000000001)])
        budget.settle(wait, work=self.work, ledger_path=self.path)
        reestimated = self.facts(previous=self.previous(old))
        self.assertEqual(set(reestimated['estimated']), {row['invocation_id']})
        self.assertEqual(reestimated['reconciled_decreases'], [])
        self.receipt(lease, [('near-maximum', 9.9999999996)], final=True)
        budget.complete_invocation(self.work, self.path, lease.lease_id)
        final = self.facts(previous=self.previous(reestimated))
        self.assertEqual(final['estimated'], {})
        self.assertEqual(final['reconciled_decreases'], [])

    def test_zero_gap_estimate_is_retained_in_next_map(self):
        lease, row, wait, old = self.estimate()
        ledger = self.ledger()
        # Authored public-record boundary; not claimed to be a producer transition.
        ledger['invocation_reservations'][lease.lease_id]['estimated_gap_usd'] = '0.000000000'
        result = self.facts(self.snapshot_card(ledger))
        self.assertEqual(result['estimated'], {row['invocation_id']: '0.000000000'})

    def test_overrun_keeps_full_total_but_unknown_previous_refuses(self):
        card = self.snapshot_card(); total = accounting.card_total(card)
        self.assertEqual(self.facts(card, held='0.000000000')['total_usd'], total)
        with self.assertRaisesRegex(ValueError, '^uncovered_total$'):
            self.facts(card, dict(total_usd=None, estimated={}), held='0.000000000')

    def test_public_record_mutations_refuse_without_producer_claim(self):
        lease, row, wait, old = self.estimate(); self.final(lease, wait)
        original = self.snapshot_card()
        for mutate in (
            lambda l: l['reconciled_decreases'][0].update(extra=True),
            lambda l: l['reconciled_decreases'][0].update(released_usd='3.000000000'),
            lambda l: l['reconciled_decreases'][0].update(wait_id='bad'),
            lambda l: l['reconciled_decreases'].append({**l['reconciled_decreases'][0], 'receipt_sha256': 'a' * 64}),
            lambda l: l['invocation_reservations'].clear(),
            lambda l: l['invocation_reservations'][lease.lease_id].update(state='pending'),
            lambda l: l['invocation_reservations'][lease.lease_id].update(state='estimated'),
            lambda l: l.update(reconciled_decreases=None),
        ):
            card = deepcopy(original); mutate(card['continuation_budget'])
            with self.assertRaisesRegex(ValueError, '^malformed_reconciliation$'):
                self.facts(card, self.previous(old))
        card = deepcopy(original)
        card['continuation_budget']['invocation_reservations']['duplicate'] = {
            **card['continuation_budget']['invocation_reservations'][lease.lease_id], 'lease_id': 'duplicate'}
        with self.assertRaisesRegex(ValueError, '^invalid_accounting_input$'): self.facts(card)

    def test_api_failures_mutation_and_coverage_schema_are_refused(self):
        card = self.snapshot_card()
        for call in (lambda l: None, lambda l: {}, lambda l: l.clear() or {'total_spent_usd': 0}):
            with self.assertRaisesRegex(ValueError, '^accounting_api_refused$'):
                self.facts(card, api=SimpleNamespace(case_spending=call))
        self.unknown(); card = self.snapshot_card(); coverage = budget.usage_coverage(card['continuation_budget'])
        for change in ({'schema_version': True}, {'extra': True}, {'booked_total_usd': '0'},
                       {'invocations': coverage['invocations'] * 2}):
            api = SimpleNamespace(case_spending=budget.case_spending, usage_coverage=lambda l: {**coverage, **change})
            with self.assertRaisesRegex(ValueError, '^accounting_api_refused$'): self.facts(card, api=api)
        def mutate(ledger): ledger.clear(); return coverage
        with self.assertRaisesRegex(ValueError, '^accounting_api_refused$'):
            self.facts(card, api=SimpleNamespace(case_spending=budget.case_spending, usage_coverage=mutate))

    def test_input_shapes_precision_and_fixed_refusals(self):
        for value in (True, -1, 'NaN', float('inf'), [], {}):
            with self.assertRaisesRegex(ValueError, '^invalid_accounting_input$'):
                accounting.card_total({'case_budget': {'total_spent_usd': value}})
        for card in ({}, {'case_budget': None}, {'case_budget': {}}, {'case_budget': {'total_spent_usd': None}}):
            self.assertIsNone(accounting.card_total(card))
        self.assertEqual(accounting.card_total({'case_budget': {'total_spent_usd': '1.0000000001'}}), '1.000000001')
        with self.assertRaisesRegex(ValueError, '^invalid_accounting_input$'):
            self.facts({'case_budget': {'total_spent_usd': '1.0000000001'}, 'continuation_budget': {'cost': 1.0000000001}})
        for prior in ({}, {'total_usd': '0', 'estimated': {}}, {'total_usd': None, 'estimated': {'bad': '0.000000000'}}):
            with self.assertRaisesRegex(ValueError, '^invalid_accounting_input$'): self.facts(previous=prior)


if __name__ == '__main__': unittest.main()
