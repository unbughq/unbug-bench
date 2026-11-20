"""new-cached-window-1: the gate prices cached prompt tokens at the pinned cache-read rate, never below the
provider's charge. Replays the router's real recorded OpenRouter usage of the last week's cut leases."""
import gzip
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import model_call_gate as gate
from token_prices import GATED_OPENROUTER, openrouter_gate_cost

LEASES = json.loads(gzip.decompress((Path(__file__).with_name('fixtures') / 'cached-window-leases-20261119.json.gz')
                                    .read_bytes()))['leases']


def replay(record):
    """The gate's allowance after the lease's requests, in order; None when it refused one."""
    lease = SimpleNamespace(**{k: record['lease'][k] for k in ('route', 'max_usd', 'max_input_tokens', 'max_output_tokens')})
    state = gate.Allowance(lease)
    for request in record['requests']:
        identity = state.reserve(gate.OPENROUTER_OUTPUT)
        if identity is None: return None
        state.finish(identity, request['usage'])
    return state


def full_rate(route, usage):
    incoming, _, outgoing = map(Decimal, GATED_OPENROUTER[route]['prices'])
    return (usage['prompt_tokens'] * incoming + usage['completion_tokens'] * outgoing) / 1_000_000


class CachedWindowTests(unittest.TestCase):
    def test_every_recorded_request_is_priced_between_its_bill_and_the_full_rate(self):
        for record in LEASES.values():
            route = record['lease']['route']
            for request in record['requests']:
                usage = request['usage']
                if usage is None: continue
                price = openrouter_gate_cost(route, usage)
                self.assertGreaterEqual(price, Decimal(str(usage['cost'])))   # never below the provider's bill
                self.assertLessEqual(price, full_rate(route, usage))
                cached = usage['prompt_tokens_details']['cached_tokens']
                # Without the provider's charge the pin is all there is: no cache discount.
                bare = {k: v for k, v in usage.items() if k != 'cost'}
                self.assertEqual(openrouter_gate_cost(route, bare), full_rate(route, usage))
                if cached and usage['cost'] < float(full_rate(route, usage)):
                    self.assertLess(price, full_rate(route, usage))

    def test_a_bill_above_the_pinned_cache_rate_is_the_price(self):
        # A serving endpoint whose cache read costs more than the pin: its charge, not the pin, is booked.
        record = next(r for r in LEASES.values() if r['lease']['route'] == 'openrouter/xiaomi/mimo-v2.6-pro')
        route = record['lease']['route']
        usage = max((r['usage'] for r in record['requests']), key=lambda u: u['prompt_tokens_details']['cached_tokens'])
        full = full_rate(route, usage)
        for cost, booked in ((float(full) * 0.99, Decimal(str(float(full) * 0.99))), (float(full) * 1.01, None)):
            charged = dict(usage, cost=cost)
            self.assertEqual(openrouter_gate_cost(route, charged), booked)
            lease = SimpleNamespace(**{k: record['lease'][k] for k in ('route', 'max_usd', 'max_input_tokens', 'max_output_tokens')})
            state = gate.Allowance(lease)
            self.assertEqual(state.finish(state.reserve(gate.OPENROUTER_OUTPUT), charged), booked is not None)
            snapshot = state.snapshot()
            # Above the full rate the usage is not trusted: the request keeps its whole hold.
            self.assertEqual(Decimal(snapshot['settled_usd'] if booked else snapshot['held_usd']),
                             booked or gate.request_hold(route))

    def test_cb5e26_diagnosis_fits_its_window_at_its_real_cost(self):
        record = next(r for r in LEASES.values() if r['lease']['route'] == 'openrouter/xiaomi/mimo-v2.6-pro')
        self.assertEqual((record['lease']['max_usd'], record['lease']['max_input_tokens']), (12.5, 28735629))
        usages = [r['usage'] for r in record['requests']]
        self.assertTrue(all(usages))
        route = record['lease']['route']
        # The row as seen: $12.05 at the full rate, 27.6M prompt tokens, 74% cached, $2.40 billed.
        self.assertEqual(round(sum(full_rate(route, u) for u in usages), 2), Decimal('12.05'))
        prompt = sum(u['prompt_tokens'] for u in usages)
        self.assertEqual(round(prompt / 1e6, 1), 27.6)
        self.assertEqual(round(100 * sum(u['prompt_tokens_details']['cached_tokens'] for u in usages) / prompt), 74)
        billed = sum(Decimal(str(u['cost'])) for u in usages)
        self.assertEqual(round(billed, 2), Decimal('2.40'))
        state = replay(record)
        self.assertIsNotNone(state)
        usage = state.snapshot()
        self.assertEqual((usage['validated_requests'], usage['unknown_requests']), (111, 0))
        settled = Decimal(usage['settled_usd'])
        self.assertGreaterEqual(settled, billed)
        self.assertLess(settled, Decimal('3.2'))
        self.assertLess(usage['settled_input_tokens'], prompt // 3)
        # Room for several more whole requests, where the full-rate count had none.
        self.assertIsNotNone(state.reserve(gate.OPENROUTER_OUTPUT))
        hold = gate.request_hold(route)
        self.assertGreater(sum(full_rate(route, u) for u in usages) + hold, Decimal('12.5'))

    def test_glm_windows_no_longer_cut(self):
        # a14a21d1, reviewer2, 98% cached: $2.06 of a $2.09 window at the full rate for $0.99 billed (15 November).
        # 1d921598, cb5e26's first G10 easy calibrator: $1.09 of $1.26 for $0.05 billed (19 November).
        for prefix in ('a14a21d1', '1d921598'):
            record = next(r for k, r in LEASES.items() if k.startswith(prefix))
            self.assertIsNotNone(replay(record).reserve(gate.OPENROUTER_OUTPUT))

    def test_unknown_request_holds_still_bound_the_easy_calibrator(self):
        # Not this row: cb5e26's G10 easy calibrator (e11c7bb2) left 6 requests without usage, each holding
        # its whole worst case ($0.17 of a $1.26 window). Cache pricing does not fit those, and must not.
        record = next(r for k, r in LEASES.items() if k.startswith('e11c7bb2'))
        self.assertEqual(sum(r['usage'] is None for r in record['requests']), 6)
        state = replay(record)
        self.assertIsNone(state.reserve(gate.OPENROUTER_OUTPUT))
        self.assertTrue(state.exhaustion.is_set())


if __name__ == '__main__':
    unittest.main()
