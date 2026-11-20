"""Neuralwatt through the wall's gate (docs/designs/neuralwatt-walled-gate.md; founder 2026-11-20), on real bytes.

neuralwatt-gate-streams-20261120.json holds seven real answers of api.neuralwatt.com (GLM text, tool and
non-streaming; MiMo and DeepSeek text and tool), byte for byte as http.client read1() returned them, which is
what the gate's parser is fed. The upstream here is a loopback stub that replays those bytes; the gate, its
body filter, its holds, its parser, the wall's OpenCode environment and the runtime's budget are the real code.
"""
import base64
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import model_call_gate as gate
import model_router as router
from budget import BudgetError
from token_prices import NW_CONTEXT, OPENROUTER_OUTPUT, gate_profile, openrouter_gate_cost, runtime_prices

FIXTURES = Path(__file__).with_name('fixtures')
CALLS = json.loads((FIXTURES / 'neuralwatt-gate-streams-20261120.json').read_text())['calls']
SMOKE = json.loads((FIXTURES / 'neuralwatt-smoke-20261119.json').read_text())
# neuralwatt-gate-opencode-requests-20261120.json: what OpenCode 1.19 really sends through this gate's walled config.
OPENCODE = json.loads((FIXTURES / 'neuralwatt-gate-opencode-requests-20261120.json').read_text())
RAW = {name: base64.b64decode(call['raw_b64']) for name, call in CALLS.items()}
GLM = 'neuralwatt/glm-5.3-flash'
KEY = 'synthetic-neuralwatt-key'


def route(name):
    return 'neuralwatt/' + name.partition(':')[0]


def real_usage(raw):
    """The usage the real answer reports, read independently of the gate's parser."""
    if not raw.startswith(b'data:'): return json.loads(raw)['usage']
    frames = [json.loads(line[5:]) for line in raw.split(b'\n') if line.startswith(b'data:') and line[5:].strip() != b'[DONE]']
    return next(f['usage'] for f in frames if f.get('usage'))


def parse(name, raw, chunk=None):
    parser = gate.OpenRouterUsage(route(name), raw.startswith(b'data:'))
    for i in range(0, len(raw), chunk or len(raw)): parser.feed(raw[i:i + (chunk or len(raw))])
    return parser.final()


def lease(route=GLM, account='neuralwatt-key', **maximum):
    return router.Lease(uuid.uuid4().hex, route, account, time.time() + 180, 'paid', router.family(route), account,
                        **{**router.route_maximum(route), **maximum})


class RealStreams(unittest.TestCase):
    def test_the_parser_returns_each_real_answers_usage_however_it_is_chunked(self):
        self.assertEqual(len(RAW), 7)
        for name, raw in RAW.items():
            for chunk in (None, 1, 7):
                with self.subTest(name=name, chunk=chunk):
                    self.assertEqual(CALLS[name]['status'], 200)
                    usage = parse(name, raw, chunk)
                    self.assertEqual(usage, real_usage(raw))
                    # Priced at the route's gate profile (Neuralwatt's list), never above one request's hold.
                    self.assertIsNotNone(openrouter_gate_cost(route(name), usage))
                    self.assertLess(openrouter_gate_cost(route(name), usage), gate.request_hold(route(name)))
        # The real shape the parser relies on: comments after the usage frame, no repeated terminal choice.
        text = RAW['glm-5.3-flash:text']
        self.assertIn(b'\n\n: energy {', text); self.assertIn(b'\n\n: cost {', text)
        self.assertTrue(text.endswith(b'data: [DONE]\n\n'))

    def test_altered_real_streams_are_refused(self):
        raw = RAW['glm-5.3-flash:tool']
        lines = raw.split(b'\n\n')
        usage_frame = next(l for l in lines if b'"usage"' in l)
        terminal = next(l for l in lines if b'"finish_reason": "tool_calls"' in l)
        altered = {
            'no [DONE]': raw.replace(b'data: [DONE]\n\n', b''),
            'no usage frame': raw.replace(usage_frame + b'\n\n', b''),
            'two usage frames': raw.replace(usage_frame, usage_frame + b'\n\n' + usage_frame),
            'two terminal choices': raw.replace(terminal, terminal + b'\n\n' + terminal),
            'another model': raw.replace(b'"model": "glm-5.3-flash"', b'"model": "glm-5.4"'),
            'an error frame': raw.replace(terminal, b'data: {"error": {"message": "x"}}'),
            'prompt above the context': raw.replace(b'"prompt_tokens": 162', b'"prompt_tokens": 9999999'),
            'total not the sum': raw.replace(b'"total_tokens": 175', b'"total_tokens": 176'),
            'cut mid-frame': raw[:-40],
            'another generation id': raw.replace(usage_frame, usage_frame.replace(b'chatcmpl-8e0d', b'chatcmpl-ffff')),
        }
        for label, bad in altered.items():
            with self.subTest(label):
                self.assertNotEqual(bad, raw)
                self.assertIsNone(parse('glm-5.3-flash:tool', bad))
        self.assertIsNone(parse('mimo-v2.6-pro:tool', RAW['glm-5.3-flash:tool']))   # a GLM answer on a MiMo lease

    def test_holds_use_neuralwatt_prices_and_clamped_output(self):
        # GLM: the twin's 1048576 context at 0.15 plus OPENROUTER_OUTPUT at 0.5. DeepSeek: Neuralwatt's own list.
        self.assertEqual(gate.request_hold(GLM), Decimal('0.1736704'))
        self.assertEqual(gate.request_hold('neuralwatt/deepseek-v4.1-flash'),
                         (1048576 * Decimal('0.15') + OPENROUTER_OUTPUT * Decimal('0.6')) / 1_000_000)
        self.assertEqual(gate.empty_usage(GLM)['max_request_output_tokens'], gate_profile(GLM)['output'])
        # No provider charge in Neuralwatt's usage: a cached token is held at the full input price.
        usage = dict(real_usage(RAW['glm-5.3-flash:text']), prompt_tokens_details={'cached_tokens': 19})
        self.assertEqual(openrouter_gate_cost(GLM, usage), (19 * Decimal('0.15') + 77 * Decimal('0.5')) / 1_000_000)


class Upstream(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args): pass
    def do_POST(self):
        owner = self.server.owner
        body = self.rfile.read(int(self.headers['Content-Length']))
        owner.seen.append((self.path, json.loads(body), dict(self.headers)))
        status, content_type, data = owner.answers.pop(0)
        self.send_response(status); self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)


class WalledGate(unittest.TestCase):
    def setUp(self):
        self.seen, self.answers, self.hosts = [], [], []
        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream); self.upstream.owner = self
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.addCleanup(self.upstream.server_close); self.addCleanup(self.upstream.shutdown)
        def connect(host, **kwargs):
            self.hosts.append(host)
            return http.client.HTTPConnection('127.0.0.1', self.upstream.server_port, **kwargs)
        def no_router(*args, **kwargs): raise AssertionError('a Neuralwatt gate never asks the router')
        self.firewall = []
        def iptables(argv, **kwargs):
            self.firewall.append(argv); return subprocess.CompletedProcess(argv, 0)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.xdg = {k: tmp.name for k in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME')}
        for patcher in (patch.object(gate.http.client, 'HTTPSConnection', side_effect=connect),
                        patch.object(router, '_rpc', no_router), patch.object(gate.sys, 'platform', 'linux'),
                        patch.object(gate.subprocess, 'run', iptables),
                        patch.object(gate.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=24001))):
            patcher.start(); self.addCleanup(patcher.stop)

    def env(self, **extra):
        return {'PATH': '/bin', 'HOME': '/home/pilot', 'NEURALWATT_API_KEY': KEY, 'OPENROUTER_API_KEY': 'r',
                'OPENCODE_API_KEY': 'o', 'CLAUDE_CODE_OAUTH_TOKEN': 'c', 'OPENCODE_CONFIG': '/tmp/x.json', **self.xdg, **extra}

    def post(self, env, body, path='/v1/chat/completions', token=None):
        """What the walled OpenCode does: its only provider is the gate, with the gate's token."""
        provider = json.loads(env['OPENCODE_CONFIG_CONTENT'])['provider']['neuralwatt']['options']
        url = provider['baseURL']
        self.assertTrue(url.startswith('http://127.0.0.1:') and url.endswith('/v1'))
        port = int(url.split(':')[2].split('/')[0])
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        connection.request('POST', path, json.dumps(body), {'Authorization': 'Bearer ' + (token or provider['apiKey']),
                                                           'Content-Type': 'application/json'})
        response = connection.getresponse(); data = response.read(); connection.close()
        return response.status, data

    def test_a_walled_call_reaches_only_neuralwatt_through_the_gate_and_settles_its_real_usage(self):
        for name in ('glm-5.3-flash:tool', 'glm-5.3-flash:text', 'deepseek-v4.1-flash:tool', 'mimo-v2.6-pro:text'):
            with self.subTest(name=name):
                self.seen.clear(); self.hosts.clear(); self.firewall.clear()
                self.answers = [(200, 'text/event-stream; charset=utf-8', RAW[name])]
                env, cap, current = self.env(), {}, lease(route(name))
                request = dict(CALLS[name]['request'], max_tokens=100000)
                request.pop('stream_options')
                with gate.enforce(current, env, cap, 5, None, user='pilot') as active:
                    # The key never crosses the wall: not in the walled env, not as the gate's token.
                    self.assertNotIn(KEY, json.dumps(env))
                    self.assertEqual({k for k in env if k.endswith(('_KEY', '_TOKEN'))}, set())
                    self.assertNotEqual(active.token, KEY)
                    cfg = json.loads(env['OPENCODE_CONFIG_CONTENT'])
                    model = name.partition(':')[0]
                    self.assertEqual(cfg['enabled_providers'], ['neuralwatt'])
                    self.assertEqual(cfg['provider']['neuralwatt']['npm'], '@ai-sdk/openai-compatible')
                    self.assertTrue(cfg['provider']['neuralwatt']['options']['includeUsage'])
                    self.assertEqual(cfg['provider']['neuralwatt']['models'][model]['limit'],
                                     {'context': NW_CONTEXT, 'output': OPENROUTER_OUTPUT})
                    self.assertEqual(cfg['provider']['neuralwatt']['models'][model]['cost'], runtime_prices(route(name)))
                    status, data = self.post(env, request)
                    self.assertEqual((status, data), (200, RAW[name]))   # passed through unchanged
                    self.assertFalse(active.is_set())
                # One iptables rule for the gate's port, inserted and deleted.
                self.assertEqual([a[4] for a in self.firewall], ['-I', '-D'])
                self.assertEqual(self.hosts, ['api.neuralwatt.com'])
                path, sent, headers = self.seen[0]
                self.assertEqual(path, '/v1/chat/completions')
                self.assertEqual(headers['Authorization'], 'Bearer ' + KEY)
                self.assertNotIn('anthropic-version', {k.lower() for k in headers})
                self.assertEqual(sent['max_tokens'], OPENROUTER_OUTPUT)
                self.assertEqual(sent['stream_options'], {'include_usage': True})
                self.assertFalse({'provider', 'usage', 'reasoning'} & set(sent))
                usage = real_usage(RAW[name])
                self.assertEqual((cap['forwarded_requests'], cap['validated_requests'], cap['unknown_requests']), (1, 1, 0))
                self.assertEqual(Decimal(cap['settled_usd']), openrouter_gate_cost(route(name), usage))
                self.assertEqual((Decimal(cap['held_usd']), cap['settled_output_tokens']), (0, usage['completion_tokens']))

    def test_real_opencode_turns_pass_the_gate_and_openrouter_or_unsafe_fields_are_refused(self):
        tool = CALLS['glm-5.3-flash:tool']['request']
        # OpenCode 1.19 itself, run with this gate's walled config: its second turn sends the assistant's reasoning
        # back as reasoning_content, content "" beside tool_calls, then the tool's answer.
        bodies = [b['body'] for b in OPENCODE['bodies']]
        self.assertTrue(all(b['path'] == '/v1/chat/completions' and b['auth_is_gate_token'] for b in OPENCODE['bodies']))
        turns = bodies[1]
        self.assertEqual([sorted(m) for m in turns['messages'][2:]],
                         [['content', 'reasoning_content', 'role', 'tool_calls'], ['content', 'role', 'tool_call_id']])
        self.assertEqual([e['type'] for e in OPENCODE['events']].count('step_finish'), 2)   # OpenCode took both answers
        # The 11-19 smoke's real top-level keys (OpenCode's title call adds temperature and reasoning_effort) pass too.
        smoke_keys = {k for r in SMOKE['requests'] for k in r} - {'n_messages'} | {'messages'}
        self.assertEqual(smoke_keys, {'model', 'max_tokens', 'temperature', 'reasoning_effort', 'stream', 'stream_options',
                                      'messages', 'tools', 'tool_choice'})
        bodies.append(dict(turns, temperature=0.5, reasoning_effort='low'))
        env, cap = self.env(), {}
        self.answers = [(200, 'text/event-stream; charset=utf-8', RAW['glm-5.3-flash:text']) for _ in bodies]
        with gate.enforce(lease(), env, cap, 5, None, user='pilot'):
            for body in bodies:
                self.assertEqual(set(body) - smoke_keys, set())
                self.assertEqual(self.post(env, body)[0], 200)
        self.assertEqual((len(self.seen), cap['validated_requests'], cap['unsupported_requests']), (3, 3, 0))
        self.assertEqual(self.seen[1][1]['messages'], turns['messages'])   # forwarded as sent
        image = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}
        bad = {
            'OpenRouter usage': dict(tool, usage={'include': True}),
            'OpenRouter provider': dict(tool, provider={'order': ['x']}),
            'OpenRouter reasoning': dict(tool, reasoning={'max_tokens': 10}),
            'include_reasoning': dict(tool, include_reasoning=True),
            'reasoning_details': dict(turns, messages=[dict(turns['messages'][2], reasoning_details=[])]),
            'non-text reasoning': dict(turns, messages=[dict(turns['messages'][2], reasoning_content=['x'])]),
            'an image': dict(tool, messages=[{'role': 'user', 'content': [image]}]),
            'a server tool': dict(tool, tools=[{'type': 'web_search'}]),
            'another model': dict(tool, model='glm-5.4'),
            'an unknown field': dict(tool, web_search_options={}),
        }
        for label, body in bad.items():
            with self.subTest(label):
                with self.assertRaises(ValueError): gate.openrouter_body(json.dumps(body), GLM)
        # OpenRouter's own filter is unchanged: it still refuses reasoning_content.
        with self.assertRaises(ValueError):
            gate.openrouter_body(json.dumps(dict(turns, model='z-ai/glm-5.3-flash')), 'openrouter/z-ai/glm-5.3-flash')

    def test_refused_requests_and_refusing_answers_never_settle_free(self):
        env, cap = self.env(), {}
        error = SMOKE['errors']['concurrent']
        self.answers = [(error['status'], 'application/json', json.dumps(error['body']).encode())]
        request = CALLS['glm-5.3-flash:text']['request']
        with gate.enforce(lease(), env, cap, 5, None, user='pilot'):
            self.assertEqual(self.post(env, request, path='/api/v1/chat/completions')[0], 400)   # OpenRouter's path
            self.assertEqual(self.post(env, request, token=KEY)[0], 401)                         # the real key is not the gate's
            self.assertEqual(self.post(env, dict(request, usage={'include': True}))[0], 400)
            status, data = self.post(env, request)
            self.assertEqual(status, 429)   # Neuralwatt's own refusal, passed through for OpenCode to classify
        self.assertEqual(len(self.seen), 1)
        self.assertEqual((cap['unsupported_requests'], cap['forwarded_requests'], cap['unknown_requests']), (2, 1, 1))
        # Not a validated usage: the request's whole hold stays (its own max_tokens bound, 200, and the full context).
        self.assertEqual(Decimal(cap['held_usd']), gate.Allowance(lease()).amount(gate.worst_request(GLM, 200))[0])
        self.assertEqual(Decimal(cap['held_usd']), (1048576 * Decimal('0.15') + 200 * Decimal('0.5')) / 1_000_000)

    def test_the_gate_is_only_for_neuralwatts_own_account_and_key_and_its_stop_is_the_calls_cap(self):
        for bad_lease, env in ((lease(account='openrouter-key'), self.env()), (lease(), self.env(NEURALWATT_API_KEY=''))):
            with self.assertRaisesRegex(BudgetError, '^credential_expiring$'):
                with gate.enforce(bad_lease, env, {}, 5, None, user='pilot'): pass
        with self.assertRaisesRegex(BudgetError, '^unbounded_route$'):
            with gate.enforce(lease(max_usd=0.0), self.env(), {}, 5, None, user='pilot'): pass
        # budget.py's Neuralwatt stop (one more whole request no longer fits) ends the call as its cap, not infra.
        cap = {}
        with self.assertRaisesRegex(BudgetError, '^model_call_cap$'):
            with gate.enforce(lease(), self.env(), cap, 5, None, user='pilot'):
                raise BudgetError('usage_reservation_exceeded')
        self.assertTrue(cap['closed'])
        # Unwalled, Neuralwatt still runs without a gate on its key, as before; Go and free never pass the wall.
        import model_runtime
        env = self.env(OPENCODE_CONFIG=str(model_runtime.opencode_config(GLM)))
        with gate.enforce(lease(), env, {}, 5, None) as call:
            self.assertIsInstance(call, gate.FreeCall)
        self.assertEqual(env['NEURALWATT_API_KEY'], KEY)
        go = 'opencode-go/glm-5.3-flash'
        with self.assertRaisesRegex(BudgetError, '^route_feature_unsupported$'):
            with gate.enforce(lease(go, account='opencode-go-key'), self.env(), {}, 5, None, user='pilot'): pass


if __name__ == '__main__':
    unittest.main()
