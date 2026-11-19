"""Neuralwatt lane money (docs/designs/neuralwatt-routes.md items 6 and 7) through the real monitor and settler.

Stand-in: the OpenCode step parts below are the Go step shape the existing Go budget tests use
(test_durable_call_budget.run_go). No real Neuralwatt step part or 402 body exists until rollout
step 5 captures them on the trial; replace these with those fixtures then.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
from decimal import Decimal, ROUND_CEILING
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
import uuid

os.environ.setdefault('BENCH', str(ROOT))
import budget
from token_prices import nw_request_worst
from durable import stop_registry
from durable.classify import PUBLISHED_REASONS, classify
from durable.contract import Outcome, StepKind

NW, GO = 'neuralwatt/mimo-v2.6-pro', 'opencode-go/mimo-v2.6-pro'
TOKENS = dict(input=1000, output=2000, reasoning=500, cache=dict(read=4000, write=0))
# MiMo's OpenRouter twin pins $0.435/M input, $0.87/M output and reasoning, $0.0036/M cache read.
STEP = (1000 * .435 + 2500 * .87 + 4000 * .0036) / 1_000_000
# OpenCode's error event for a provider 402 (shape of test_budget's OpenRouter 402 case).
CREDIT_402 = dict(type='error', error=dict(name='APIError', data=dict(statusCode=402, message='Insufficient credits')))


def finish(i, cost=0):
    return dict(type='step_finish', sessionID='s', part=dict(id=f'p{i}', messageID=f'm{i}', cost=cost, tokens=TOKENS))


def start(i):
    return dict(type='step_start', sessionID='s', part=dict(id=f's{i}', messageID=f'm{i}'))


class NeuralwattBudget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / 'ledger.json'
        self.attempt = SimpleNamespace(key='attempt-1', baseline_spent_usd=0, ceiling_usd=50)

    def reserve(self, route, maximum='5'):
        lease = SimpleNamespace(lease_id=uuid.uuid4().hex, route=route, billing='paid', pool='neuralwatt-key',
                                account='neuralwatt-key', family='xiaomi')
        row = budget.reserve_invocation(self.ledger, lease, maximum, attempt=self.attempt,
                                        operation_id=str(uuid.uuid4()), call_name='builder-1')
        return lease, row

    def call(self, lease, row, events):
        command = [sys.executable, '-c', ''.join('print(' + repr(json.dumps(e)) + ', flush=True);' for e in events)]
        budget.run_budgeted(command, self.root, {}, self.root / 'transcript', self.ledger, 3,
            max_cost=None, case_budget=50, configured_model=lease.route, concurrent=True, attempt=self.attempt,
            invocation_id=row['invocation_id'], lease_id=lease.lease_id, containment=False)

    def settle_unknown(self, lease):
        """The receipt model_runtime writes for a call that did not finish: final usage unknown."""
        data = json.loads(self.ledger.read_text())
        receipt = dict(lease_id=lease.lease_id, final_usage_known=False, events=[], outcome='provider_wait',
                       booked_event_ids=data['invocation_reservations'][lease.lease_id]['event_ids'])
        (self.root / 'usage-receipts').mkdir(exist_ok=True)
        (self.root / 'usage-receipts' / (lease.lease_id + '.json')).write_text(json.dumps(receipt))
        budget.complete_invocation(self.root, self.ledger, lease.lease_id)
        data = json.loads(self.ledger.read_text())
        return data, Decimal(data['invocation_reservations'][lease.lease_id]['estimated_gap_usd'])

    def test_an_nw_step_books_its_twin_list_price_as_case_money(self):
        lease, row = self.reserve(NW)
        self.call(lease, row, [start(0), finish(0), start(1), finish(1, 1e-9)])
        data = json.loads(self.ledger.read_text())
        self.assertEqual(data['terminal_stop'], 'complete')
        self.assertEqual([e['cost'] for e in data['events']], [STEP, STEP])
        self.assertNotIn('plan_list_cost_usd', data)   # real money, not a plan's list value: never counted twice
        self.assertAlmostEqual(budget.case_spending(data)['total_spent_usd'], 2 * STEP)
        self.assertEqual(data['invocation_reservations'][lease.lease_id]['open_steps'], 0)
        self.assertIsNotNone(budget.usage_coverage(data))

    def test_the_same_step_on_go_still_books_no_money(self):
        lease, row = self.reserve(GO)
        self.call(lease, row, [start(0), finish(0)])
        data = json.loads(self.ledger.read_text())
        self.assertEqual(([e['cost'] for e in data['events']], data['plan_list_cost_usd']), ([0], STEP))
        self.assertEqual(budget.case_spending(data)['total_spent_usd'], 0)
        self.assertNotIn('open_steps', data['invocation_reservations'][lease.lease_id])

    def test_a_402_before_any_step_books_no_tail(self):
        lease, row = self.reserve(NW)
        with self.assertRaises(budget.BudgetError) as stop:
            self.call(lease, row, [CREDIT_402])
        self.assertEqual(str(stop.exception), 'provider_limit:' + NW)
        self.assertEqual(stop.exception.provider_failure['reason'], 'credit')
        data, gap = self.settle_unknown(lease)
        self.assertEqual(gap, 0)
        self.assertEqual(budget.case_spending(data)['total_spent_usd'], 0)
        self.assertIsNotNone(budget.usage_coverage(data))

    def test_one_open_step_books_at_most_one_whole_request(self):
        worst = nw_request_worst(NW).quantize(Decimal('.000000001'), rounding=ROUND_CEILING)
        self.assertEqual(round(worst, 3), Decimal('0.570'))
        for maximum in ('5', '0.3'):
            with self.subTest(maximum=maximum):
                self.ledger.unlink(missing_ok=True)
                lease, row = self.reserve(NW, maximum)
                with self.assertRaises(budget.BudgetError):
                    self.call(lease, row, [start(0), finish(0), start(1), CREDIT_402])
                data, gap = self.settle_unknown(lease)
                self.assertEqual(data['invocation_reservations'][lease.lease_id]['open_steps'], 1)
                booked = Decimal(str(STEP))
                self.assertEqual(gap, min(Decimal(maximum) - booked, worst).quantize(
                    Decimal('.000000001'), rounding=ROUND_CEILING))

    def test_a_stop_with_no_step_start_still_books_one_whole_request(self):
        # Not a classified refusal: a request may be in flight before its step-start part appears.
        lease, row = self.reserve(NW)
        with self.assertRaises(budget.BudgetError) as stop:
            self.call(lease, row, [])
        self.assertEqual(str(stop.exception), 'missing_usage')
        data, gap = self.settle_unknown(lease)
        self.assertEqual(data['invocation_reservations'][lease.lease_id]['open_steps'], 1)
        self.assertEqual(gap, nw_request_worst(NW).quantize(Decimal('.000000001'), rounding=ROUND_CEILING))

    def test_without_the_stops_count_the_whole_bound_stays_booked(self):
        # A killed worker never records open_steps: its reservation's remainder is booked, as before.
        lease, _ = self.reserve(NW)
        _, gap = self.settle_unknown(lease)
        self.assertEqual(gap, 5)


class NeuralwattClassify(unittest.TestCase):
    def test_an_nw_402_wait_is_neuralwatts_limit_not_openrouter_credit(self):
        from durable import classify as wp4
        from model_router import ProviderWait, Wait
        now = 1_792_400_000.0
        for account, route, want in (('neuralwatt-key', NW, 'router:neuralwatt_limit'),
                                     ('openrouter-key', 'openrouter/xiaomi/mimo-v2.6-pro', 'router:credit')):
            with self.subTest(route=route):
                error = ProviderWait('writer', Wait('credit', now + 120, route=route, account=account))
                result, _ = wp4.classify_wait(error, step=StepKind.GATES, now=now)
                self.assertEqual((result.outcome, result.reason), (Outcome.PROVIDER_LIMIT, want))
        self.assertEqual(classify('provider_limit:' + NW, step=StepKind.GATES, now=now).reason, 'router:neuralwatt_limit')
        self.assertIn('router:neuralwatt_limit', PUBLISHED_REASONS)
        self.assertIs(stop_registry.REGISTRY['router:neuralwatt_limit'], stop_registry.WAIT)


if __name__ == '__main__':
    unittest.main()
