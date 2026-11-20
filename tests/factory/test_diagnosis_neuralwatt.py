"""A walled diagnosis takes the Neuralwatt lane through the wall's gate (docs/designs/diagnosis-neuralwatt-gate.md;
founder 2026-11-20 ~10:40), with its reasoning bounded in Neuralwatt's own form.

neuralwatt-thinking-budget-20261120.json holds six real answers of api.neuralwatt.com (GLM, MiMo, DeepSeek; each
without and with vLLM's thinking_token_budget=64) as http.client read1() returned them. The gate, its body filter,
its parser, the runtime's diagnosis path and its environment are the real code; the upstream is a loopback stub
replaying those bytes (test_neuralwatt_walled_gate.WalledGate).
"""
import argparse
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(Path(__file__).resolve().parent)]
import diagnosis_task
import model_call_gate as gate
import model_router as router
import model_runtime
from token_prices import OPENROUTER_OUTPUT
import test_neuralwatt_walled_gate as walled
from test_neuralwatt_walled_gate import KEY, lease, real_usage

BUDGET = json.loads((Path(__file__).with_name('fixtures') / 'neuralwatt-thinking-budget-20261120.json').read_text())['calls']
RAW = {name: base64.b64decode(call['raw_b64']) for name, call in BUDGET.items()}
MIMO = 'neuralwatt/mimo-v2.6-pro'


def content(raw):
    frames = [json.loads(line[5:]) for line in raw.split(b'\n') if line.startswith(b'data: {')]
    return ''.join((c.get('delta') or {}).get('content') or '' for f in frames for c in f.get('choices') or [])


class RealBudget(unittest.TestCase):
    def test_neuralwatt_stops_reasoning_at_thinking_token_budget_and_still_answers(self):
        for model in ('glm-5.3-flash', 'mimo-v2.6-pro', 'deepseek-v4.1-flash'):
            with self.subTest(model=model):
                free, bound = RAW[model + ':budget=None'], RAW[model + ':budget=64']
                self.assertEqual(BUDGET[model + ':budget=64']['request']['thinking_token_budget'], 64)
                self.assertEqual(real_usage(bound)['completion_tokens_details']['reasoning_tokens'], 64)
                self.assertTrue(content(bound).strip())   # the answer still comes after the bound
                for raw in (free, bound):   # the gate's parser takes the real bytes
                    parser = gate.OpenRouterUsage('neuralwatt/' + model, True); parser.feed(raw)
                    self.assertEqual(parser.final(), real_usage(raw))
        # Without the bound GLM and MiMo reason past 64 on the same prompt: the field, not the prompt, cut it.
        for model in ('glm-5.3-flash', 'mimo-v2.6-pro'):
            self.assertGreater(real_usage(RAW[model + ':budget=None'])['completion_tokens_details']['reasoning_tokens'], 64)

    def test_the_gate_adds_the_bound_only_for_a_diagnosis_and_never_takes_one_from_the_caller(self):
        request = dict(BUDGET['mimo-v2.6-pro:budget=None']['request'], max_tokens=200_000, reasoning_effort='high')
        bound = gate.openrouter_body(json.dumps(request), MIMO, True)
        self.assertEqual(bound['thinking_token_budget'], OPENROUTER_OUTPUT * 3 // 4)
        self.assertEqual(bound['reasoning_effort'], 'high')   # effort is no token bound on vLLM: both are sent
        self.assertEqual(gate.openrouter_body(json.dumps(dict(request, max_tokens=400)), MIMO, True)['thinking_token_budget'], 300)
        self.assertNotIn('thinking_token_budget', gate.openrouter_body(json.dumps(request), MIMO))
        with self.assertRaises(ValueError):
            gate.openrouter_body(json.dumps(BUDGET['mimo-v2.6-pro:budget=64']['request']), MIMO, True)
        # OpenRouter's form is unchanged.
        twin = dict(request, model='xiaomi/mimo-v2.6-pro'); twin.pop('reasoning_effort')
        body = gate.openrouter_body(json.dumps(twin), 'openrouter/xiaomi/mimo-v2.6-pro', True)
        self.assertNotIn('thinking_token_budget', body)
        self.assertEqual(body['reasoning']['max_tokens'], body['max_tokens'] * 3 // 4)


class WalledDiagnosis(unittest.TestCase):
    setUp, post = walled.WalledGate.setUp, walled.WalledGate.post   # its loopback upstream, not its tests

    def test_a_walled_diagnosis_runs_on_neuralwatt_through_the_gate_with_the_bound_and_no_key(self):
        current = router.Lease(**{**vars(lease(MIMO)), 'expires_at': 4_000_000_000})
        self.assertTrue(router.valid_lease(current, MIMO))
        self.answers = [(200, 'text/event-stream; charset=utf-8', RAW['mimo-v2.6-pro:budget=64'])]
        posted = []
        def budgeted(cmd, cwd, env, *args, **kwargs):
            # What the walled OpenCode sees: no key of any kind, webfetch denied, only the gate as provider.
            self.assertNotIn(KEY, json.dumps(env))
            self.assertEqual({k for k in env if k.endswith(('_KEY', '_TOKEN'))}, set())
            cfg = json.loads(env['OPENCODE_CONFIG_CONTENT'])
            self.assertEqual((cfg['permission']['webfetch'], cfg['permission']['websearch']), ('deny', 'deny'))
            self.assertNotIn('OPENCODE_ENABLE_EXA', env)
            posted.append(self.post(env, dict(BUDGET['mimo-v2.6-pro:budget=None']['request'], max_tokens=32000)))
            return subprocess.CompletedProcess(cmd, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'transcripts').mkdir()
            c = SimpleNamespace(work=root, case=root / 'case', case_id='case-x', card={}, ledger=root / 'ledger.json',
                model_env={'NEURALWATT_API_KEY': KEY, 'OPENROUTER_API_KEY': 'r', 'OPENCODE_API_KEY': 'o'},
                model_lease=current, model_cap_used={}, _model_launch_permit=current.lease_id,
                args=argparse.Namespace(agent_timeout=30, max_cost=5, max_role_calls=10, max_total_calls=20,
                                        no_progress_minutes=1, max_zero_tokens=3))
            runtime = model_runtime.ModelRuntime(root, lambda *a, **k: 0, lambda *a, **k: None,
                lambda path, sudo=False: shutil.rmtree(path), lambda user: root / 'home' / user)
            with patch.object(model_runtime, 'run_budgeted', budgeted), \
                 patch.object(model_runtime, '_opencode_flags', return_value=()), \
                 patch.object(model_runtime.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=24001)), \
                 patch.object(diagnosis_task, '_quiet'):
                self.assertEqual(runtime._invoke(c, [MIMO], 'diagnose', root, 'diagnosis-' + current.lease_id, user='pilot'), 0)
        self.assertEqual(posted, [(200, RAW['mimo-v2.6-pro:budget=64'])])
        self.assertEqual(self.hosts, ['api.neuralwatt.com'])
        path, sent, headers = self.seen[0]
        self.assertEqual((path, headers['Authorization']), ('/v1/chat/completions', 'Bearer ' + KEY))
        self.assertEqual(sent['thinking_token_budget'], 32000 * 3 // 4)
        self.assertEqual((c.model_cap_used['validated_requests'], c.model_cap_used['unknown_requests']), (1, 0))

    def test_a_walled_diagnosis_is_offered_the_neuralwatt_lane(self):
        seen = []
        def await_lease(role, context, deadline=None):
            seen.append(context.router_excluded); raise RuntimeError('stop before dispatch')
        runtime = model_runtime.ModelRuntime(Path('/nonexistent'), None, None, None, None)
        with patch.object(router, 'await_lease', await_lease):
            for model in ('openrouter/xiaomi/mimo-v2.6-pro', 'openrouter/deepseek/deepseek-v4.1-flash'):
                with self.assertRaisesRegex(RuntimeError, 'stop before dispatch'):
                    runtime._call(SimpleNamespace(card={}), [model], 'x', '/', 'diagnosis-1', user='pilot')
                excluded = seen.pop()
                self.assertFalse([lane for lane in excluded if lane.startswith('neuralwatt-key/')])
                self.assertTrue(excluded)   # Go and free stay excluded: they have no gate
                self.assertTrue(all(lane.partition('/')[2] in router.GO_ROUTES | router.FREE_ROUTES for lane in excluded))


if __name__ == '__main__':
    unittest.main()
