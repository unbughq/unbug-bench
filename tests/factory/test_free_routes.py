"""OpenCode free routes (founder 2026-11-08): $0 maximum, no gate, refused behind the isolation wall."""
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import budget
import model_call_gate
import model_router
from budget import BudgetError

FREE = 'opencode/deepseek-v4.1-flash-free'


def lease(route=FREE, **maximum):
    m = {**model_router.route_maximum(route), **maximum}
    return SimpleNamespace(lease_id=uuid.uuid4().hex, route=route, account=None, pool=route, family='deepseek',
                           billing='free', **m)


class FreeRoutes(unittest.TestCase):
    def test_free_routes_are_bounded_at_zero_and_ignore_funding(self):
        for route in ('opencode/deepseek-v4.1-flash-free', 'opencode/minimax-m3.1-flash-free', 'opencode/glm-5.3-flash-free'):
            self.assertEqual(model_router.route_maximum(route)['max_usd'], 0.0, route)
            self.assertEqual(model_router.funded_maximum(route, '5'), model_router.route_maximum(route))
        self.assertTrue(model_router.valid_maximum(vars(lease())))
        self.assertFalse(model_router.valid_maximum(vars(lease(max_usd=1.0))))   # a free lease holds nothing
        # Paid routes are unchanged.
        self.assertGreater(model_router.route_maximum('openrouter/deepseek/deepseek-v4.1-flash')['max_usd'], 0)
        # DeepSeek free falls back to the paid gated route of the same family.
        self.assertEqual([r['route'] for r in model_router.routes(FREE, model_router.ACCOUNTS)],
                         [FREE, 'openrouter/deepseek/deepseek-v4.1-flash'])

    def test_enforce_runs_a_free_call_without_a_gate_and_refuses_the_wall(self):
        cancel, cap = threading.Event(), model_call_gate.empty_usage(FREE)
        env = {'PATH': '/bin', 'OPENCODE_CONFIG_CONTENT': '{}'}
        with model_call_gate.enforce(lease(), env, cap, 5, cancel) as call:
            self.assertFalse(call.is_set())
            cancel.set()
            self.assertTrue(call.is_set())
        self.assertEqual(env, {'PATH': '/bin', 'OPENCODE_CONFIG_CONTENT': '{}'})   # env is the runtime's own
        self.assertEqual(cap, model_call_gate.empty_usage(FREE))                 # nothing held, nothing forwarded
        with self.assertRaisesRegex(BudgetError, 'route_feature_unsupported'):
            with model_call_gate.enforce(lease(), {}, cap, 5, None, user='pilot'): pass
        with self.assertRaisesRegex(BudgetError, 'unbounded_route'):
            with model_call_gate.enforce(lease(max_usd=1.0), {}, cap, 5, None): pass

    def test_a_free_call_that_books_any_cost_is_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'continuation-budget.json'
            path.write_text(json.dumps({'calls': 0, 'events': [], 'cost': 0}))
            attempt = SimpleNamespace(key='case/1/stress/1', baseline_spent_usd=0, ceiling_usd=10)
            row = budget.reserve_invocation(path, lease(), Decimal(0), attempt=attempt,
                                            operation_id=str(uuid.uuid4()), call_name='attacker-1')
            ledger = json.loads(path.read_text())
            event = {'id': 'e1', 'cost': 0, 'lease_id': row['lease_id'], 'invocation_id': row['invocation_id']}
            ledger['events'].append(event)
            budget.check_reservation(ledger, row['lease_id'])               # free, as promised: runs on
            ledger['events'].append({**event, 'id': 'e2', 'cost': 0.000001})
            with self.assertRaisesRegex(BudgetError, 'usage_reservation_exceeded'):
                budget.check_reservation(ledger, row['lease_id'])           # one micro-dollar stops it


if __name__ == '__main__':
    unittest.main()
