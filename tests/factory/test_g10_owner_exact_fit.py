"""A funding quote must never exceed what reserve_invocation admits (case-import-2a7b2a-h5-1, 21 November).

A hosted G10 strong try is funded with exactly one tester window plus one owner window
(helper_try_authority: 12.5 + 1.7104906). The Codex tester books live events whose float values
(0.013604799999999998, ...) leave the exact booked sum below its nine-place total, so the owner's
headroom was 1.7104906 less a sub-nanodollar residue. available_invocation_funding rounded that up to
1.710490600, the router funded the owner's lease at it, and reserve_invocation refused the lease
(budget_exhausted:grant_insufficient). The owner channel then cancelled the tester, the helper returned
the try as a 'cancelled' stop, and gates:1 attempts 4 and 5 ended ENGINE STOPPED cancelled at try 3.
Replays the real tester events, leases and authority from that run (fixture)."""
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import budget
import model_router
from model_runtime import call_window

FIXTURE = json.loads((Path(__file__).resolve().parent / 'fixtures' / 'g10-owner-exact-fit-20261121.json').read_text())
TESTER, OWNER = 'strong-calibrator-strong_calibrator-3', 'reviewer-owner-strong_calibrator-try-3-1'


def lease(row):
    l = row['lease']
    return SimpleNamespace(lease_id=row['lease_id'], route=l['route'], account=l['account'], billing=l['billing'],
                           pool=l['pool'], family=l['family'], max_usd=l['max_usd'])


class OwnerExactFit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        authority = FIXTURE['helper_try_authority']['per_try_usd']
        # As helper_link._try_context builds a hosted try's attempt.
        self.attempt = SimpleNamespace(key='case/2/gates:1/4/helper/x', baseline_spent_usd=0.0, ceiling_usd=float(authority))

    def ledger(self, name):
        path = Path(self.tmp.name) / name
        path.write_text(json.dumps({'cost': 0, 'calls': 0, 'events': []}))
        return path

    def reserve(self, path, row, maximum, name, parent=None):
        return budget.reserve_invocation(path, lease(row), maximum, attempt=self.attempt, operation_id=str(uuid.uuid4()),
                                         call_name=name, parent_call_name=parent)

    def admit_tester(self, path, attempt):
        """model_runtime's calibrator admission: the funding less one owner window, capped at the call window."""
        owner_route = attempt['owner']['lease']['route']
        owner_max = Decimal(str(model_router.route_maximum(owner_route)['max_usd']))
        funding = Decimal(budget.available_invocation_funding(path, self.attempt, TESTER)) - owner_max
        funding = min(funding, call_window('strong_calibrator', attempt['tester']['lease']['route']))
        self.assertEqual(funding, Decimal(str(attempt['tester']['lease']['max_usd'])))   # the run's real window
        return self.reserve(path, attempt['tester'], funding, TESTER)

    def stream(self, path, row, events):
        """What run_budgeted books while the tester runs: each real event, bound to its reservation."""
        with budget.ledger_transaction(path) as ledger:
            for event in events:
                ledger['events'].append(dict(event, lease_id=row['lease_id'], invocation_id=row['invocation_id']))
                for key in ('cost', 'list_cost_usd', 'estimated_subscription_cost_usd'):
                    ledger[key] = ledger.get(key, 0) + (event.get(key) or 0)
                ledger['calls'] += event.get('calls', 1)

    def admit_owner(self, path, attempt):
        """model_runtime's owner admission: quote, the router's funded lease, then the reservation."""
        route = attempt['owner']['lease']['route']
        funding = Decimal(budget.available_invocation_funding(path, self.attempt, OWNER))
        funding = min(funding, call_window('reviewer', route))
        quoted = model_router.funded_maximum(route, format(funding, '.9f'))
        held = SimpleNamespace(**{**vars(lease(attempt['owner'])), 'max_usd': quoted['max_usd']})
        return funding, budget.reserve_invocation(
            path, held, Decimal(str(held.max_usd)), attempt=self.attempt, operation_id=str(uuid.uuid4()),
            call_name=OWNER, parent_call_name=TESTER)

    def test_the_run_quoted_what_its_reservation_then_refused(self):
        # The evidence itself: both owner leases were funded at the whole owner window and denied.
        for attempt in FIXTURE['tries']:
            self.assertEqual(attempt['owner']['request']['funding_usd'], '1.710490600')
            self.assertEqual(attempt['owner']['outcome'], 'denied')
            self.assertEqual(attempt['tester']['outcome'], 'interrupted')

    def test_owner_is_admitted_beside_the_tester_after_every_real_event(self):
        for n, attempt in enumerate(FIXTURE['tries']):
            for k in range(len(attempt['tester_events']) + 1):
                with self.subTest(attempt=n, events=k):
                    path = self.ledger(f'{n}-{k}.json')
                    tester = self.admit_tester(path, attempt)
                    self.stream(path, tester, attempt['tester_events'][:k])
                    funding, row = self.admit_owner(path, attempt)
                    # Money safety: the two holds never exceed the try's authority ...
                    ledger = json.loads(path.read_text())
                    spent = Decimal(str(budget.case_spending(ledger)['total_spent_usd']))
                    self.assertLessEqual(spent + budget.outstanding_reservations(ledger),
                                         Decimal(str(self.attempt.ceiling_usd)))
                    # ... the quote stays within a nanodollar of the window, and nothing more fits.
                    self.assertGreaterEqual(funding, Decimal('1.710490599'))
                    with self.assertRaises(budget.BudgetError):
                        self.reserve(path, {**attempt['owner'], 'lease_id': uuid.uuid4().hex}, Decimal('0.000000001'), OWNER)

    def test_a_try_without_an_owner_window_still_stops(self):
        attempt = FIXTURE['tries'][0]
        self.attempt.ceiling_usd = 12.5   # authority for the tester alone
        path = self.ledger('unfunded.json')
        self.reserve(path, attempt['tester'], Decimal('12.5'), TESTER)
        self.stream(path, json.loads(path.read_text())['invocation_reservations'][attempt['tester']['lease_id']],
                    attempt['tester_events'])
        with self.assertRaises(budget.BudgetError) as stop:
            budget.available_invocation_funding(path, self.attempt, OWNER)
        self.assertEqual(str(stop.exception), 'budget_exhausted:grant_insufficient')


if __name__ == '__main__':
    unittest.main()
