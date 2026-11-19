"""Neuralwatt lane money (docs/designs/neuralwatt-routes.md items 6-8) through the real monitor and settler.

neuralwatt-smoke-20261119.json holds rollout step 1's capture on the trial key: OpenCode 1.19.0's own event
streams for both models under the factory's opencode_config, the request bodies OpenCode sent, and the error
bodies (401/404 real; 402/429/503 from Neuralwatt's docs, marked source=docs: not provokable without spending
the trial), wrapped in OpenCode's real APIError event (captured with a bad key). The control-flow tests keep the Go step shape for exact arithmetic; the last three run the real
streams and bodies.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
from decimal import Decimal, ROUND_CEILING
import copy
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault('BENCH', str(ROOT))
import budget
from token_prices import OPENROUTER_OUTPUT, go_step_cost, nw_request_worst
from durable import stop_registry
from durable.classify import PUBLISHED_REASONS, classify
from durable.contract import Outcome, StepKind

NW, GO = 'neuralwatt/mimo-v2.6-pro', 'opencode-go/mimo-v2.6-pro'
TOKENS = dict(input=1000, output=2000, reasoning=500, cache=dict(read=4000, write=0))
# MiMo's OpenRouter twin pins $0.435/M input, $0.87/M output and reasoning, $0.0036/M cache read.
STEP = (1000 * .435 + 2500 * .87 + 4000 * .0036) / 1_000_000
SMOKE = json.loads((Path(__file__).with_name('fixtures') / 'neuralwatt-smoke-20261119.json').read_text())


def opencode_error(name):
    """OpenCode's real APIError event (captured with a bad key) carrying another Neuralwatt error body."""
    error, event = SMOKE['errors'][name], copy.deepcopy(SMOKE['opencode_error_event']['event'])
    body = error['body']['error']
    event['error']['data'].update(statusCode=error['status'], message=body.get('message', body['code']),
                                  isRetryable=body.get('retryable', False), responseBody=json.dumps(error['body']))
    return event


# Neuralwatt's 402 never says "insufficient credits": the status code alone must make it credit.
CREDIT_402 = opencode_error('key_allowance')


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
        self.call(lease, row, [start(0), finish(0), start(1), finish(1, 1e-9), start(2), finish(2, 2 * STEP)])
        data = json.loads(self.ledger.read_text())
        self.assertEqual(data['terminal_stop'], 'complete')
        # The larger of OpenCode's cost and the twin's list: below list books list, above list books OpenCode's.
        self.assertEqual([e['cost'] for e in data['events']], [STEP, STEP, 2 * STEP])
        self.assertEqual([budget.event_bound_charge(e) for e in data['events']], [Decimal(str(e['cost'])) for e in data['events']])
        self.assertNotIn('plan_list_cost_usd', data)   # real money, not a plan's list value: never counted twice
        self.assertAlmostEqual(budget.case_spending(data)['total_spent_usd'], 4 * STEP)
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
        # A reservation below one whole request stops before its first step books (check_limits): its tail
        # is then that whole small bound.
        for maximum, booked in (('5', Decimal(str(STEP))), ('0.3', 0)):
            with self.subTest(maximum=maximum):
                self.ledger.unlink(missing_ok=True)
                lease, row = self.reserve(NW, maximum)
                with self.assertRaises(budget.BudgetError):
                    self.call(lease, row, [start(0), finish(0), start(1), CREDIT_402])
                data, gap = self.settle_unknown(lease)
                self.assertEqual(data['invocation_reservations'][lease.lease_id]['open_steps'], 1)
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

    def test_an_nw_call_stops_while_one_more_request_still_fits_its_reservation(self):
        # Steps book when they finish, so without this stop the step after the last one that fits could book
        # (and Neuralwatt bill) past the maximum by up to one whole request.
        worst = nw_request_worst(NW)
        maximum = str(worst + Decimal('0.001'))
        lease, row = self.reserve(NW, maximum)
        with self.assertRaises(budget.BudgetError) as stop:
            self.call(lease, row, [start(0), finish(0), start(1), finish(1)])
        self.assertEqual(str(stop.exception), 'usage_reservation_exceeded')
        data, gap = self.settle_unknown(lease)
        self.assertEqual([e['cost'] for e in data['events']], [STEP])   # the second step never booked
        self.assertLessEqual(Decimal(str(STEP)) + gap, Decimal(maximum) + Decimal('.000000001'))   # the tail's own rounding

    def test_an_opencode_error_event_books_no_phantom_tail(self):
        # OpenCode's error event ends the request: no request is left open, unlike a stall.
        lease, row = self.reserve(NW)
        with self.assertRaises(budget.BudgetError) as stop:
            self.call(lease, row, [start(0), finish(0), dict(type='error', error=dict(name='UnknownError'))])
        self.assertEqual(str(stop.exception), 'opencode_error')
        data, gap = self.settle_unknown(lease)
        self.assertEqual((data['invocation_reservations'][lease.lease_id]['open_steps'], gap), (0, 0))

    def test_a_failed_kill_keeps_the_whole_remaining_bound_booked(self):
        # The process may outlive its stop and keep sending paid requests: no per-step bound holds.
        lease, row = self.reserve(NW)
        with patch.object(budget.os, 'killpg', side_effect=OSError('kill failed')):
            with self.assertRaises(budget.BudgetError):
                self.call(lease, row, [start(0), finish(0), start(1)])
        data, gap = self.settle_unknown(lease)
        self.assertEqual(data['terminal_stop'], 'cancellation_failed')
        self.assertNotIn('open_steps', data['invocation_reservations'][lease.lease_id])
        self.assertEqual(gap, (5 - Decimal(str(STEP))).quantize(Decimal('.000000001'), rounding=ROUND_CEILING))

    def test_without_the_stops_count_the_whole_bound_stays_booked(self):
        # A killed worker never records open_steps: its reservation's remainder is booked, as before.
        lease, _ = self.reserve(NW)
        _, gap = self.settle_unknown(lease)
        self.assertEqual(gap, 5)

    # Rollout step 1's real capture (SMOKE).
    def test_real_opencode_streams_book_the_twin_list_price(self):
        for model, events in SMOKE['events'].items():
            with self.subTest(model=model):
                self.ledger.unlink(missing_ok=True)
                route = 'neuralwatt/' + model
                lease, row = self.reserve(route)
                self.call(lease, row, events)
                data = json.loads(self.ledger.read_text())
                parts = [e['part'] for e in events if e['type'] == 'step_finish']
                self.assertTrue(parts and all(p['tokens']['input'] + p['tokens']['cache']['read'] > 0 for p in parts))
                # OpenCode prices the step at the twin (opencode_config's cost); the booking is never below it.
                self.assertEqual(len(data['events']), len(parts))
                for event, part in zip(data['events'], parts):
                    self.assertAlmostEqual(part['cost'], go_step_cost(route, part['tokens']), places=12)
                    self.assertEqual(event['cost'], max(part['cost'], go_step_cost(route, part['tokens'])))
                self.assertEqual((data['terminal_stop'], data['invocation_reservations'][lease.lease_id]['open_steps']), ('complete', 0))
                self.assertNotIn('plan_list_cost_usd', data)

    def test_opencode_asks_for_usage_and_stays_under_the_output_cap(self):
        # nw_request_worst holds only while OpenCode caps max_tokens at limit.output: Neuralwatt itself
        # accepted max_tokens 5,000,000 on the trial.
        self.assertEqual(SMOKE['huge_max_tokens_accepted']['status'], 200)
        self.assertEqual(len(SMOKE['requests']), 6)
        for request in SMOKE['requests']:
            self.assertEqual(request['stream_options'], {'include_usage': True})
            self.assertLessEqual(request['max_tokens'], OPENROUTER_OUTPUT)

    def test_a_neuralwatt_429_ends_the_call_as_rate_with_no_phantom_tail(self):
        # OpenCode's error event is terminal. The one-notice allowance for CLIs once skipped it, so the call
        # ended as missing_usage, never told the router, and booked a whole request it never sent.
        for name in ('concurrent', 'uncached_window', 'uncached_too_large'):
            event = opencode_error(name)
            for before in ([], [start(0), finish(0), start(1)]):
                with self.subTest(error=name, steps=len(before)):
                    self.ledger.unlink(missing_ok=True)
                    lease, row = self.reserve(NW)
                    with self.assertRaises(budget.BudgetError) as stop:
                        self.call(lease, row, before + [event])
                    self.assertEqual((str(stop.exception), stop.exception.provider_failure['reason']), ('provider_limit:' + NW, 'rate'))
                    data, gap = self.settle_unknown(lease)
                    self.assertEqual(gap, (nw_request_worst(NW).quantize(Decimal('.000000001'), rounding=ROUND_CEILING)
                                           if before else 0))   # one open step: its request may have been sent

    def test_a_go_429_keeps_its_one_lane_exclusion(self):
        # Only NW lanes treat the event as terminal: on Go, rate would block the whole Go account.
        lease, row = self.reserve(GO)
        with self.assertRaises(budget.BudgetError) as stop:
            self.call(lease, row, [opencode_error('concurrent')])
        self.assertEqual((str(stop.exception), stop.exception.provider_failure), ('missing_usage', None))

    def test_every_neuralwatt_error_body_classifies(self):
        want = {402: 'credit', 429: 'rate', 503: 'outage', 404: 'outage', 401: None}
        for name, error in SMOKE['errors'].items():
            with self.subTest(error=name):
                found = budget.classify_provider_failure(json.dumps(error['body']), NW, status_code=error['status'])
                self.assertEqual(found and found['reason'], want[error['status']])
                if error['status'] == 402: self.assertEqual(found['scope'], 'wallet')


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
