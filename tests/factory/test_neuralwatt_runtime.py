"""Neuralwatt lanes on the worker side: offered accounts, OpenCode config, the gate, the wall and move-on
(docs/designs/neuralwatt-routes.md items 3-5)."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import model_call_gate
import model_router
import model_runtime
from budget import BudgetError
from token_prices import NW_TWINS, OPENROUTER_OUTPUT, runtime_prices

MIMO, GLM = 'neuralwatt/mimo-v2.6-pro', 'neuralwatt/glm-5.3-flash'


def lease(route=MIMO, account='neuralwatt-key', **maximum):
    m = {**model_router.route_maximum(route), **maximum}
    return SimpleNamespace(lease_id=uuid.uuid4().hex, route=route, account=account, pool=account, family='xiaomi',
                           billing='paid', **m)


class NeuralwattRuntime(unittest.TestCase):
    def test_only_neuralwatt_is_dropped_when_its_key_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(model_router, 'SECRETS', Path(tmp)):
            # No key files at all: every other account stays offered (its call fails credential_expiring).
            self.assertEqual(model_runtime.offered_accounts(), model_router.ACCOUNTS[:-1])
            (Path(tmp) / 'neuralwatt-key').write_text('k')
            self.assertEqual(model_runtime.offered_accounts(), model_router.ACCOUNTS)

    def test_config_carries_the_exact_neuralwatt_provider_only_for_a_neuralwatt_call(self):
        for route in (MIMO, GLM):
            cfg = json.loads(model_runtime.opencode_config(route).read_text())
            self.assertEqual(cfg['small_model'], route)
            self.assertEqual(cfg['provider']['neuralwatt'], {
                'npm': '@ai-sdk/openai-compatible',
                'options': {'baseURL': 'https://api.neuralwatt.com/v1', 'apiKey': '{env:NEURALWATT_API_KEY}', 'includeUsage': True},
                'models': {'mimo-v2.6-pro': {'cost': runtime_prices(NW_TWINS[MIMO]), 'limit': {'context': 1048560, 'output': 32768}},
                           'glm-5.3-flash': {'cost': runtime_prices(NW_TWINS[GLM]), 'limit': {'context': 1048560, 'output': 32768}}}})
        self.assertEqual(OPENROUTER_OUTPUT, 32768)
        # Every other call's config is as it was: no Neuralwatt provider.
        for model in ('opencode-go/mimo-v2.6-pro', 'opencode/glm-5.3-flash-free', None):
            self.assertNotIn('neuralwatt', json.loads(model_runtime.opencode_config(model).read_text())['provider'])

    def test_gate_runs_neuralwatt_on_its_own_key_and_nothing_else(self):
        cap = model_call_gate.empty_usage(MIMO)
        with tempfile.TemporaryDirectory() as tmp:
            config = model_runtime.opencode_config(MIMO)
            xdg = {k: tmp for k in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME')}
            env = {'PATH': '/bin', 'OPENCODE_CONFIG': str(config), 'NEURALWATT_API_KEY': 'n',
                   'OPENCODE_API_KEY': 'k', 'OPENROUTER_API_KEY': 'r', 'CLAUDE_CODE_OAUTH_TOKEN': 'c', **xdg}
            with model_call_gate.enforce(lease(), env, cap, 5, None) as call:
                self.assertFalse(call.is_set())
            cfg = json.loads(env.pop('OPENCODE_CONFIG_CONTENT'))
            self.assertEqual({k for k in env if k.endswith(('_KEY', '_TOKEN'))}, {'NEURALWATT_API_KEY'})
            self.assertEqual(env['NEURALWATT_API_KEY'], 'n')
            self.assertEqual(cfg['enabled_providers'], ['neuralwatt'])
            self.assertEqual(cfg['provider']['neuralwatt']['whitelist'], ['mimo-v2.6-pro'])
            full = dict(env, OPENCODE_CONFIG=str(config), NEURALWATT_API_KEY='n')
            with self.assertRaisesRegex(BudgetError, '^model_call_cap$'):
                with model_call_gate.enforce(lease(), dict(full), cap, 5, None):
                    raise BudgetError('usage_reservation_exceeded')
            # No key, or a lease on another account: credential_expiring. Behind the wall: refused.
            for bad_env, bad_lease in ((dict(full, NEURALWATT_API_KEY=''), lease()),
                                       (dict(full, OPENCODE_API_KEY='k'), lease(account='opencode-go-key'))):
                with self.assertRaisesRegex(BudgetError, '^credential_expiring$'):
                    with model_call_gate.enforce(bad_lease, dict(bad_env), cap, 5, None): pass
            with self.assertRaisesRegex(BudgetError, '^route_feature_unsupported$'):
                with model_call_gate.enforce(lease(), dict(full), cap, 5, None, user='pilot'): pass
        with self.assertRaisesRegex(BudgetError, '^unbounded_route$'):
            with model_call_gate.enforce(lease(max_usd=0.0), {}, cap, 5, None): pass

    def test_go_keeps_only_its_opencode_key(self):
        go = 'opencode-go/mimo-v2.6-pro'
        env = {'OPENCODE_CONFIG': str(model_runtime.opencode_config(go)), 'OPENCODE_API_KEY': 'k', 'NEURALWATT_API_KEY': 'n'}
        clean = model_call_gate.free_environment(SimpleNamespace(route=go, account='opencode-go-key'), env)
        self.assertEqual((clean.get('OPENCODE_API_KEY'), clean.get('NEURALWATT_API_KEY')), ('k', None))

    def test_a_walled_role_is_never_bounded_on_a_neuralwatt_lane(self):
        nw_only = ('neuralwatt-key',)
        for route in (MIMO, GLM):
            self.assertTrue(model_runtime.bounded_route('writer', route, nw_only))
            self.assertFalse(model_runtime.bounded_route('strong_calibrator', route, nw_only))
            self.assertFalse(model_runtime.bounded_route('easy_calibrator', route, nw_only))
            # Its gated OpenRouter twin still bounds the walled role.
            self.assertTrue(model_runtime.bounded_route('easy_calibrator', route, ('neuralwatt-key', 'openrouter-key')))

    def test_diagnosis_never_carries_a_key_for_a_neuralwatt_lease(self):
        # Walled diagnosis never leases an NW lane (bounded_route); if that regressed, no key crosses the wall.
        env = {'PATH': '/bin', 'NEURALWATT_API_KEY': 'n', 'OPENCODE_API_KEY': 'k', 'OPENROUTER_API_KEY': 'r'}
        clean = model_runtime.diagnosis_environment(env, 'opencode', lease(), Path('/h'))
        self.assertEqual({k for k in clean if k.endswith('_KEY')}, set())

    def test_a_case_context_offers_accounts_as_a_list_without_a_missing_neuralwatt_key(self):
        import run
        with tempfile.TemporaryDirectory() as tmp, patch.object(model_router, 'SECRETS', Path(tmp)):
            accounts = run.Ctx().router_accounts
        self.assertIs(type(accounts), list)   # a helper's sealed job comes back from JSON as a list
        self.assertEqual(accounts, list(model_router.ACCOUNTS[:-1]))

    def test_neuralwatt_quota_or_credit_moves_on_and_other_faults_do_not(self):
        moves = model_runtime.go_quota_moves_on
        for reason in ('quota', 'credit'):
            self.assertTrue(moves(SimpleNamespace(route=MIMO), reason))
            self.assertTrue(moves(SimpleNamespace(route=GLM), reason))
        for reason in ('rate', 'refusal', 'process_error'):
            self.assertFalse(moves(SimpleNamespace(route=MIMO), reason))
        # Go is unchanged: quota only. OpenRouter never.
        self.assertTrue(moves(SimpleNamespace(route='opencode-go/mimo-v2.6-pro'), 'quota'))
        self.assertFalse(moves(SimpleNamespace(route='opencode-go/mimo-v2.6-pro'), 'credit'))
        self.assertFalse(moves(SimpleNamespace(route='openrouter/xiaomi/mimo-v2.6-pro'), 'credit'))


if __name__ == '__main__':
    unittest.main()
