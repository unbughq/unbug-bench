"""NVIDIA's hosted inference as a $0 backup route for DeepSeek, MiniMax and GLM (2026-11-08).

Synthetic only: no key, no network, no case material.
"""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import free_models
import free_route_smoke
import model_call_gate
import model_router
import model_runtime
from budget import BudgetError
from token_prices import FREE_ROUTES, NVIDIA_FIRST, NVIDIA_FIRST_EVENT_SECONDS, NVIDIA_ROUTES, NVIDIA_URL

DEEPSEEK, NV_DEEPSEEK = 'opencode/deepseek-v4.1-flash-free', 'nvidia/deepseek-ai/deepseek-v4.1-flash'
MINIMAX, NV_MINIMAX = 'opencode/minimax-m3.1-flash-free', 'nvidia/minimaxai/minimax-m3.1-flash'
GLM, NV_GLM = 'opencode/glm-5.3-flash-free', 'nvidia/z-ai/glm-5.3-flash'
PAID_DEEPSEEK = 'openrouter/deepseek/deepseek-v4.1-flash'
KEY = 'nvapi-synthetic-never-printed'


def lease(route=NV_DEEPSEEK, account='nvidia-key'):
    return SimpleNamespace(lease_id=uuid.uuid4().hex, route=route, account=account, pool=model_router.free_pool(account),
                           family=model_router.family(route), billing='free', **model_router.route_maximum(route))


def step(model_id='deepseek-ai/deepseek-v4.1-flash', provider='nvidia', cost=0, tokens_in=12):
    part = {'messageID': 'm', 'id': 'p', 'cost': cost, 'modelID': model_id, 'providerID': provider,
            'tokens': {'input': tokens_in, 'output': 3, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}}
    return [{'type': 'step_start', 'part': {'messageID': 'm'}}, {'type': 'step_finish', 'part': part}]


def cli(tmp, lines, record=None):
    script = Path(tmp) / 'opencode'
    head = '#!/bin/sh\n' + ('echo "$NVIDIA_API_KEY|$OPENCODE_API_KEY" > %s\n' % record if record else '')
    script.write_text(head + ''.join("echo '%s'\n" % json.dumps(l) for l in lines))
    script.chmod(0o755)
    return str(script)


class Routes(unittest.TestCase):
    def test_nvidia_is_a_backup_after_the_account_lanes_at_zero(self):
        self.assertEqual(NVIDIA_FIRST, {DEEPSEEK: NV_DEEPSEEK, MINIMAX: NV_MINIMAX, GLM: NV_GLM})
        self.assertTrue(NVIDIA_ROUTES <= FREE_ROUTES)
        for requested, nvidia in NVIDIA_FIRST.items():
            rows = model_router.routes(requested)
            # Both OpenCode account lanes first, then NVIDIA, then the paid or subscription fallback.
            self.assertEqual([(r['route'], r['account']) for r in rows[:2]],
                             [(requested, 'opencode-go-key'), (requested, 'opencode-go-key-2')])
            self.assertEqual((rows[2]['route'], rows[2]['account'], rows[2]['billing'], rows[2]['pool']),
                             (nvidia, 'nvidia-key', 'free', 'nvidia-free:nvidia-key'))
            self.assertNotIn(nvidia, [r['route'] for r in rows[3:]])
            # Same family: no new model and no family change (routes() refuses one anyway).
            self.assertEqual({r['family'] for r in rows}, {model_router.family(requested)})
            self.assertEqual(model_router.route_maximum(nvidia),
                             dict(max_usd=0.0, max_input_tokens=0, max_output_tokens=0, price_source='free:' + nvidia))
            self.assertEqual(model_router.funded_maximum(nvidia, '5'), model_router.route_maximum(nvidia))
        # DeepSeek and MiniMax still end on their paid gated OpenRouter route.
        self.assertEqual(model_router.routes(DEEPSEEK)[-1]['route'], PAID_DEEPSEEK)
        self.assertEqual(model_router.routes(MINIMAX)[-1]['route'], 'openrouter/minimax/minimax-m3.1-flash')
        # A batch that pins the paid route, MiMo (not in NVIDIA's catalogue) and the Claude/Codex roles get no NVIDIA route.
        for model in (PAID_DEEPSEEK, 'openrouter/z-ai/glm-5.3-flash', 'opencode-go/mimo-v2.6-pro',
                      'openrouter/xiaomi/mimo-v2.6-pro', 'claude/claude-opus-5-5', 'codex/gpt-6.1-sol'):
            self.assertFalse(any(r['route'] in NVIDIA_ROUTES for r in model_router.routes(model)), model)
        # A worker without the account has no NVIDIA lane.
        accounts = [a for a in model_router.ACCOUNTS if a != 'nvidia-key']
        self.assertFalse(any(r['route'] in NVIDIA_ROUTES for r in model_router.routes(DEEPSEEK, accounts)))

    def test_walled_roles_never_get_nvidia(self):
        # Calibrators (and the easy calibrator's dedup, same role) reach only a gate's port: NVIDIA has no gate.
        self.assertIn('nvidia-free:nvidia-key/' + NV_GLM, model_router.free_lanes(GLM, model_router.ACCOUNTS))
        c = SimpleNamespace(models={'builder': [MINIMAX], 'attacker': [DEEPSEEK], 'strong_calibrator': ['claude/claude-opus-5-5'],
                                    'easy_calibrator': [GLM], 'reviewers': [['openrouter/xiaomi/mimo-v2.6-pro']]})
        with self.assertRaises(model_router.ProviderWait) as stop:
            model_runtime.require_bounded_models(c)
        self.assertEqual((stop.exception.role, stop.exception.wait.reason), ('easy_calibrator', 'unbounded_route'))
        with self.assertRaisesRegex(BudgetError, 'route_feature_unsupported'):
            with model_call_gate.enforce(lease(NV_GLM), {}, model_call_gate.empty_usage(NV_GLM), 5, None, user='pilot'): pass

    def test_a_worker_without_the_key_skips_nvidia_instead_of_waiting(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = SimpleNamespace(card={})
            with mock.patch.object(model_router, 'SECRETS', Path(tmp)):
                self.assertNotIn('nvidia-key', model_router._account_order(case))
                (Path(tmp) / 'nvidia-key').write_text('x')
                self.assertIn('nvidia-key', model_router._account_order(case))


class Router(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    ACCOUNT_LANES = ['opencode-free:opencode-go-key/' + DEEPSEEK, 'opencode-free:opencode-go-key-2/' + DEEPSEEK]

    def acquire(self, store, model=DEEPSEEK, excluded=()):
        return store.rpc('acquire', dict(paid_protocol=1, id=uuid.uuid4().hex, model=model, accounts=list(model_router.ACCOUNTS),
                                         role='writer', deadline=4e9, excluded_lanes=list(excluded)))

    def test_closed_until_the_router_opens_it(self):
        # No case material goes to NVIDIA until the founder has checked its terms: 0 seats by default.
        store = model_router.Store(Path(self.tmp.name) / 'closed.sqlite')
        self.assertEqual(model_router.lane_capacity({}, 'nvidia-free:nvidia-key'), 0)
        first = self.acquire(store)
        self.assertEqual((first['route'], first['account']), (DEEPSEEK, 'opencode-go-key'))
        self.assertEqual(store.rpc('capacity', {'route': NV_DEEPSEEK})['slots'], 0)
        # The account lanes failed for this call: it skips the closed NVIDIA lane for paid OpenRouter.
        self.assertEqual(self.acquire(store, excluded=self.ACCOUNT_LANES)['route'], PAID_DEEPSEEK)
        # Every other lane busy: the wait never names the closed NVIDIA lane.
        self.acquire(store)
        wait = self.acquire(store, excluded=self.ACCOUNT_LANES)
        self.assertEqual(wait['kind'], 'wait')
        self.assertNotIn(wait['route'], NVIDIA_ROUTES)

    def test_open_lane_follows_the_account_lanes_and_a_429_falls_back_with_a_record(self):
        store = model_router.Store(Path(self.tmp.name) / 'open.sqlite', capacities={'nvidia-free': 1})
        # The account lanes are asked first even with NVIDIA open.
        self.assertEqual(self.acquire(store)['route'], DEEPSEEK)
        first = self.acquire(store, excluded=self.ACCOUNT_LANES)
        self.assertEqual((first['route'], first['account'], first['max_usd']), (NV_DEEPSEEK, 'nvidia-key', 0.0))
        # Its one seat is taken: the next caller goes to paid OpenRouter rather than queueing.
        self.assertEqual(self.acquire(store, excluded=self.ACCOUNT_LANES)['route'], PAID_DEEPSEEK)
        error = {'error_class': 'opencode_error', 'http_status': 429, 'error_name': 'APIError', 'events_seen': 1}
        store.rpc('finish', dict(lease_id=first['lease_id'], outcome='interrupted', receipt=None, error=error))
        rows = store.rpc('status', {})['free_errors']
        self.assertEqual([(r['route'], r['account'], r['pool'], r['error_class'], r['http_status']) for r in rows],
                         [(NV_DEEPSEEK, 'nvidia-key', 'nvidia-free:nvidia-key', 'opencode_error', 429)])
        # The failed lane is excluded for that call, which moves on.
        retry = self.acquire(store, excluded=[*self.ACCOUNT_LANES, 'nvidia-free:nvidia-key/' + NV_DEEPSEEK])
        self.assertEqual(retry['route'], PAID_DEEPSEEK)
        # A 429 (rate) observation blocks only NVIDIA's lane: later calls skip it for paid.
        lane = self.acquire(store, excluded=self.ACCOUNT_LANES)
        self.assertEqual(lane['route'], NV_DEEPSEEK)
        store.rpc('observe', dict(lease_id=lane['lease_id'], reason='rate', observation_id=lane['lease_id'] + ':f'))
        store.rpc('finish', dict(lease_id=lane['lease_id'], outcome='interrupted', receipt=None))
        self.assertEqual(self.acquire(store, excluded=self.ACCOUNT_LANES)['route'], PAID_DEEPSEEK)
        # The operator can clear the lane by name.
        store.rpc('observe', dict(pool='nvidia-free:nvidia-key', healthy=True, observation_id='nvidia-ok'))

    def test_a_failed_nvidia_call_moves_on_through_the_runtime(self):
        from router_test_support import offline_router
        stack, store = offline_router()
        self.addCleanup(stack.close)
        store.capacities = {'nvidia-free': 1}
        tried = []
        def invoke(runtime, context, models, *args, **kwargs):
            tried.append((models[0], context.model_env.get('NVIDIA_API_KEY')))
            if models[0] == DEEPSEEK:   # both OpenCode account lanes hang without a word
                raise BudgetError('opencode_error', provider_error={'events_seen': 0})
            if models[0] in NVIDIA_ROUTES:
                raise BudgetError('opencode_error', provider_error={'http_status': 429, 'error_name': 'APIError', 'events_seen': 1})
            return 0
        runtime = model_runtime.ModelRuntime(None, None, None, None, None)
        c = SimpleNamespace(work=Path(self.tmp.name), card={})
        with mock.patch.object(model_runtime.ModelRuntime, '_invoke', invoke):
            self.assertEqual(runtime.call(c, [DEEPSEEK], 't', '.', 'attacker-1'), 0)
        # Both account lanes, then NVIDIA with its own key, then paid OpenRouter. (A key left over from an
        # earlier attempt never reaches the CLI: enforce keeps only the leased provider's key.)
        self.assertEqual([r for r, _ in tried], [DEEPSEEK, DEEPSEEK, NV_DEEPSEEK, PAID_DEEPSEEK])
        self.assertEqual(tried[2][1], 'synthetic-only')
        self.assertIsNone(tried[0][1])
        rows = store.rpc('status', {})['free_errors']
        self.assertEqual([(r['route'], r['error_class'], r['http_status'], r['error_name']) for r in rows
                          if r['route'] in NVIDIA_ROUTES], [(NV_DEEPSEEK, 'opencode_error', 429, 'APIError')])
        self.assertEqual(model_runtime.call_failure_reason('opencode_error', NV_DEEPSEEK), 'outage')


class Execution(unittest.TestCase):
    def test_config_points_at_nvidia_with_a_key_reference_only(self):
        cfg = free_models.provider_config('synthetic-case', NV_MINIMAX)
        self.assertEqual(cfg['options'], {'baseURL': NVIDIA_URL, 'apiKey': '{env:NVIDIA_API_KEY}', 'includeUsage': True})
        self.assertEqual(cfg['npm'], '@ai-sdk/openai-compatible')
        self.assertEqual(cfg['whitelist'], ['minimaxai/minimax-m3.1-flash'])
        self.assertEqual(set(cfg['models']['minimaxai/minimax-m3.1-flash']['cost'].values()), {0})
        path = model_runtime.opencode_config(NV_MINIMAX, 'synthetic-case')
        whole = json.loads(Path(path).read_text())
        self.assertEqual(whole['provider']['nvidia'], cfg)
        self.assertEqual(whole['small_model'], NV_MINIMAX)
        self.assertNotIn('nvapi-', Path(path).read_text())

    def test_enforce_passes_only_the_nvidia_provider_and_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = model_runtime.opencode_config(NV_GLM, 'synthetic-case')
            xdg = {k: tmp for k in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME')}
            env = {'PATH': '/bin', 'OPENCODE_CONFIG': str(config), 'NVIDIA_API_KEY': KEY, 'OPENCODE_API_KEY': 'other',
                   'OPENROUTER_API_KEY': 'paid', **xdg}
            with model_call_gate.enforce(lease(NV_GLM), env, model_call_gate.empty_usage(NV_GLM), 5, threading.Event()): pass
            cfg = json.loads(env.pop('OPENCODE_CONFIG_CONTENT'))
            self.assertEqual(env['NVIDIA_API_KEY'], KEY)
            self.assertNotIn('OPENCODE_API_KEY', env); self.assertNotIn('OPENROUTER_API_KEY', env)
            self.assertEqual(cfg['enabled_providers'], ['nvidia'])
            self.assertEqual(list(cfg['provider']), ['nvidia'])
            self.assertEqual(cfg['provider']['nvidia']['whitelist'], ['z-ai/glm-5.3-flash'])
            self.assertEqual((cfg['model'], cfg['small_model']), (NV_GLM, NV_GLM))

    def run_cli(self, lines, max_cost=None):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / 'ledger.json'
            try:
                return budget.run_budgeted([cli(tmp, lines), '-m', NV_DEEPSEEK], tmp, {'PATH': '/bin:/usr/bin'},
                                           Path(tmp) / 'out.jsonl', ledger, 30, driver='opencode', configured_model=NV_DEEPSEEK,
                                           containment=False, **({'max_cost': max_cost} if max_cost is not None else {}))
            finally:
                self.ledger = json.loads(ledger.read_text()) if ledger.exists() else None

    def test_usage_is_booked_from_reported_tokens_at_zero(self):
        self.assertEqual(self.run_cli(step()).returncode, 0)
        event = self.ledger['events'][0]
        self.assertEqual((event['cost'], event['tokens']['input'], event['providerID']), (0, 12, 'nvidia'))
        # No usage back (zero input tokens) is not trusted: the call moves to the next route.
        with self.assertRaisesRegex(BudgetError, 'missing_usage'):
            self.run_cli(step(tokens_in=0))
        self.assertEqual(model_runtime.call_failure_reason('missing_usage', NV_DEEPSEEK), 'outage')
        # A step from another provider or model stops it.
        for model_id, provider in (('deepseek-v4.1-flash', 'nvidia'), ('deepseek-ai/deepseek-v4.1-flash', 'openrouter')):
            with self.assertRaisesRegex(BudgetError, 'free_route_mismatch'):
                self.run_cli(step(model_id, provider))
        # Slow to answer: no output event within the limit skips it to the next route.
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'slow'; script.write_text('#!/bin/sh\nsleep 30\n'); script.chmod(0o755)
            started = time.monotonic()
            with self.assertRaisesRegex(BudgetError, 'first_token_timeout') as caught:
                budget.run_budgeted([str(script)], tmp, {'PATH': '/bin:/usr/bin'}, Path(tmp) / 'o.jsonl', Path(tmp) / 'l.json',
                                    30, driver='opencode', configured_model=NV_DEEPSEEK, containment=False, first_event_timeout=1)
            self.assertLess(time.monotonic() - started, 10)
            self.assertEqual(caught.exception.provider_error['events_seen'], 0)
        self.assertEqual(model_runtime.call_failure_reason('first_token_timeout', NV_DEEPSEEK), 'outage')
        self.assertEqual(NVIDIA_FIRST_EVENT_SECONDS, 20)
        # Any booked cost stops it (the smoke's own limit; a factory call is stopped by its $0 reservation).
        with self.assertRaisesRegex(BudgetError, 'cost_limit'):
            self.run_cli(step(cost=0.01), max_cost=free_route_smoke.STOP_AT_ANY_COST)


class Smoke(unittest.TestCase):
    def test_toy_prompt_on_the_nvidia_key_only(self):
        self.assertEqual(free_route_smoke.PROMPT, 'Reply with the single word OK.')
        with self.assertRaisesRegex(ValueError, 'unapproved'):
            free_route_smoke.smoke('opencode-go-key', NV_DEEPSEEK, '/nonexistent')
        with self.assertRaisesRegex(ValueError, 'unapproved'):
            free_route_smoke.smoke('nvidia-key', DEEPSEEK, '/nonexistent')
        with self.assertRaisesRegex(ValueError, 'unapproved'):
            free_route_smoke.smoke('nvidia-key', NV_DEEPSEEK, '/nonexistent', variant='zen')
        with tempfile.TemporaryDirectory() as tmp:
            secrets = Path(tmp) / 'secrets'; secrets.mkdir()
            (secrets / 'nvidia-key').write_text(KEY + '\n')
            (secrets / 'opencode-go-key').write_text('opencode-key\n')
            record = Path(tmp) / 'seen'
            with mock.patch.object(model_runtime, 'OPENCODE_BIN', cli(tmp, step(), record)), \
                 mock.patch.object(model_runtime, '_opencode_flags', lambda binary: ()):
                row = free_route_smoke.smoke('nvidia-key', NV_DEEPSEEK, secrets, timeout=30)
            self.assertEqual((row['ok'], row['route'], row['error_class']), (True, NV_DEEPSEEK, None))
            self.assertEqual(record.read_text().strip(), KEY + '|')        # its key, and no OpenCode key
            self.assertNotIn(KEY, json.dumps(row))
            # Run with no arguments, nvidia-key gets exactly NVIDIA's three routes.
            seen = []
            with mock.patch.object(free_route_smoke, 'smoke', lambda a, m, *x, **k: seen.append((a, m)) or {'ok': True}):
                free_route_smoke.main(['--account', 'nvidia-key'])
            self.assertEqual(sorted(seen), sorted(('nvidia-key', r) for r in NVIDIA_ROUTES))


if __name__ == '__main__':
    unittest.main()
