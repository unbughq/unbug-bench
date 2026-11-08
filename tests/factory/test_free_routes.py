"""OpenCode free routes (founder 2026-11-08): $0 maximum, no gate, a clean pinned environment, never behind the wall."""
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


def lease(route=FREE, account=None, **maximum):
    m = {**model_router.route_maximum(route), **maximum}
    return SimpleNamespace(lease_id=uuid.uuid4().hex, route=route, account=account, pool=route, family='deepseek',
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
        # So does MiniMax free (on either OpenCode account), past the unbounded OpenRouter :free variant.
        self.assertEqual([(r['route'], r['account']) for r in model_router._bounded_routes(
                              'opencode/minimax-m3.1-flash-free', model_router.ACCOUNTS)],
                         [('opencode/minimax-m3.1-flash-free', 'opencode-go-key'),
                          ('opencode/minimax-m3.1-flash-free', 'opencode-go-key-2'),
                          ('openrouter/minimax/minimax-m3.1-flash', 'openrouter-key')])
        # A batch that pins the paid route still asks it first: free routes run only where a batch pins them.
        self.assertEqual(model_router.routes('openrouter/minimax/minimax-m3.1-flash', model_router.ACCOUNTS)[0]['route'],
                         'openrouter/minimax/minimax-m3.1-flash')

    def test_enforce_runs_a_free_call_without_a_gate_and_refuses_the_wall(self):
        cancel, cap = threading.Event(), model_call_gate.empty_usage(FREE)
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'opencode.json'
            config.write_text(json.dumps({'provider': {'opencode': {'options': {'baseURL': 'https://free.example/v1'}},
                                                       'openrouter': {}, 'opencode-go': {}}, 'mcp': {'computer': {}}}))
            xdg = {k: tmp for k in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME')}
            env = {'PATH': '/bin', 'OPENCODE_CONFIG': str(config), 'OPENCODE_API_KEY': 'k', 'OPENROUTER_API_KEY': 'r',
                   'OPENCODE_CONFIG_DIR': '/home/x/.opencode', **xdg}
            with model_call_gate.enforce(lease(), env, cap, 5, cancel) as call:
                self.assertFalse(call.is_set())
                cancel.set()
                self.assertTrue(call.is_set())
            # Clean environment: no keys (DeepSeek free runs on no account), no outside config, no self-update.
            cfg = json.loads(env.pop('OPENCODE_CONFIG_CONTENT'))
            self.assertEqual(env, {'PATH': '/bin', **xdg, 'OPENCODE_ENABLE_EXA': '1', 'OPENCODE_PURE': '1',
                                   'OPENCODE_DISABLE_PROJECT_CONFIG': '1', 'OPENCODE_DISABLE_AUTOUPDATE': '1'})
            # Only OpenCode's provider, only this model, for the call and its compaction.
            self.assertEqual(cfg['enabled_providers'], ['opencode'])
            self.assertEqual(cfg['provider'], {'opencode': {'options': {'baseURL': 'https://free.example/v1'},
                                                            'whitelist': ['deepseek-v4.1-flash-free']}})
            self.assertEqual((cfg['model'], cfg['small_model'], cfg['mcp']), (FREE, FREE, {}))
            self.assertEqual(cap, model_call_gate.empty_usage(FREE))                 # nothing held, nothing forwarded
            # A route on an OpenCode account keeps only that account's key.
            minimax = 'opencode/minimax-m3.1-flash-free'
            env = {'PATH': '/bin', 'OPENCODE_CONFIG': str(config), 'OPENCODE_API_KEY': 'k', **xdg}
            with model_call_gate.enforce(lease(minimax, account='opencode-go-key'), env, cap, 5, None): pass
            self.assertEqual(env['OPENCODE_API_KEY'], 'k')
            # Without scratch XDG dirs the user's own OpenCode config would load.
            with self.assertRaisesRegex(BudgetError, 'route_feature_unsupported'):
                with model_call_gate.enforce(lease(), {'OPENCODE_CONFIG': str(config)}, cap, 5, None): pass
        with self.assertRaisesRegex(BudgetError, 'route_feature_unsupported'):
            with model_call_gate.enforce(lease(), {}, cap, 5, None, user='pilot'): pass
        with self.assertRaisesRegex(BudgetError, 'unbounded_route'):
            with model_call_gate.enforce(lease(max_usd=1.0), {}, cap, 5, None): pass

    def test_a_walled_role_is_never_leased_a_free_route(self):
        import model_runtime
        runtime = model_runtime.ModelRuntime(Path('/nonexistent'), None, None, None, None)
        seen = []
        def await_lease(role, context, deadline=None):
            seen.append((role, getattr(context, 'router_excluded', ())))
            raise RuntimeError('stop before dispatch')
        original = model_router.await_lease
        model_router.await_lease = await_lease
        try:
            for user, name in (('pilot', 'easy-calibrator-1'), (None, 'easy-calibrator-provider-preflight'),
                               ('pilot', 'diagnosis-1')):
                # DeepSeek free keeps its gated OpenRouter route.
                with self.assertRaisesRegex(RuntimeError, 'stop before dispatch'):
                    runtime._call(SimpleNamespace(card={}), [FREE], 'x', '/', name, user=user)
                self.assertEqual(seen.pop(), (model_runtime.invocation_role(name),
                                              ('opencode-free/' + FREE,)))
                # GLM free has no bounded route behind the wall: refused as a configuration, not slept on.
                with self.assertRaises(model_router.ProviderWait) as stop:
                    runtime._call(SimpleNamespace(card={}), ['opencode/glm-5.3-flash-free'], 'x', '/', name, user=user)
                self.assertEqual(stop.exception.wait.reason, 'unbounded_route')
            # An unwalled role still gets the free lane.
            with self.assertRaisesRegex(RuntimeError, 'stop before dispatch'):
                runtime._call(SimpleNamespace(card={}), [FREE], 'x', '/', 'attacker-1')
            self.assertEqual(seen.pop(), ('stress_tester', ()))
        finally:
            model_router.await_lease = original
        # Before construction: a calibrator chain whose only bounded route is free is refused.
        c = SimpleNamespace(models={'builder': [FREE], 'attacker': [FREE],
                                    'strong_calibrator': ['claude/claude-opus-5-5'], 'easy_calibrator': ['opencode/glm-5.3-flash-free'],
                                    'reviewers': [['openrouter/xiaomi/mimo-v2.6-pro']]})
        with self.assertRaises(model_router.ProviderWait) as stop:
            model_runtime.require_bounded_models(c)
        self.assertEqual(stop.exception.role, 'easy_calibrator')
        c.models['easy_calibrator'] = ['openrouter/z-ai/glm-5.3-flash']   # what the batches pin today
        model_runtime.require_bounded_models(c)

    def test_a_failing_free_call_moves_to_the_next_route(self):
        from model_runtime import call_failure_reason
        paid = 'openrouter/deepseek/deepseek-v4.1-flash'
        for label in ('provider_limit:x', 'opencode_error', 'process_error'):   # limits, 5xx, a crashed CLI
            self.assertIsNotNone(call_failure_reason(label, FREE))
        for label in ('missing_usage', 'invalid_usage', 'free_route_mismatch'):  # a usage report we cannot trust
            self.assertEqual(call_failure_reason(label, FREE), 'outage')
            self.assertIsNone(call_failure_reason(label, paid))                 # a paid route's stays a stop
        self.assertIsNone(call_failure_reason('timeout', FREE))                 # its window is spent: durable retry

    def test_a_step_from_another_provider_or_model_stops_a_free_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out.jsonl'
            def run(model_id, provider, cost=0):
                part = {'messageID': 'm', 'id': 'p', 'cost': cost, 'modelID': model_id, 'providerID': provider,
                        'tokens': {'input': 1, 'output': 1, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}}
                lines = [{'type': 'step_start', 'part': {'messageID': 'm'}}, {'type': 'step_finish', 'part': part}]
                script = Path(tmp) / 'cli.sh'
                script.write_text('#!/bin/sh\n' + ''.join("echo '%s'\n" % json.dumps(l) for l in lines))
                script.chmod(0o755)
                ledger = Path(tmp) / f'ledger-{uuid.uuid4().hex}.json'
                return budget.run_budgeted([str(script), '-m', FREE], tmp, {'PATH': '/bin:/usr/bin'}, out, ledger, 30,
                                           driver='opencode', configured_model=FREE, containment=False)
            self.assertEqual(run('deepseek-v4.1-flash-free', 'opencode').returncode, 0)
            self.assertEqual(run(None, None).returncode, 0)                    # OpenCode 2.x reports neither
            for model_id, provider in (('deepseek-v4.1-flash', 'opencode'), ('deepseek-v4.1-flash-free', 'openrouter')):
                with self.assertRaisesRegex(BudgetError, 'free_route_mismatch'):
                    run(model_id, provider, cost=0.25)
                ledger = json.loads(max(Path(tmp).glob('ledger-*.json'), key=lambda p: p.stat().st_mtime_ns).read_text())
                self.assertEqual(ledger['cost'], 0.25)   # the mismatched step's cost is booked before the stop

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
