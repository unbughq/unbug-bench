"""Saved public contracts and pinned synthetic CLI traffic, never live inference."""
import copy
from dataclasses import replace
from decimal import Decimal
import gzip
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'factory'))
import budget
import model_call_gate as gate
import model_router as router
import token_prices as prices
import test_model_call_maxima as core
from router_test_support import historical_minimax_profile

FIXTURES = Path(__file__).with_name('fixtures')
CLAUDE = 'claude/claude-opus-4-5-20251101'
MINIMAX = 'openrouter/minimax/minimax-m3.1-flash'


def fixture(name):
    return json.loads(gzip.decompress((FIXTURES / name).read_bytes()))


class ProfileTests(unittest.TestCase):
    @historical_minimax_profile()
    def test_minimax_endpoint_contract(self):
        records = fixture('router-item8-minimax-availability.json.gz')
        paid, free = (r['response']['data'] for r in records)
        self.assertEqual([r['status'] for r in records], [200, 200])
        self.assertEqual(paid['id'], 'minimax/minimax-m3.1-flash')
        self.assertEqual(free['id'], 'minimax/minimax-m3.1-flash:free')
        self.assertEqual(free['endpoints'], [])
        entry, = [e for e in paid['endpoints'] if e['tag'].startswith('tenstorrent')]
        self.assertEqual(entry['tag'], 'tenstorrent/fp8')
        self.assertEqual((entry['context_length'], entry['max_completion_tokens']), (1000000, 900000))
        self.assertEqual({k:entry['pricing'][k] for k in ('prompt','completion','input_cache_read','discount')},
                         dict(prompt='0.00000005', completion='0.0000002', input_cache_read='0.000000005', discount=0))
        self.assertTrue({'max_tokens','tools','tool_choice','reasoning'} <= set(entry['supported_parameters']))
        maximum = router.route_maximum(MINIMAX)
        self.assertEqual(maximum, dict(max_usd=.690001, max_input_tokens=13800020, max_output_tokens=3450005,
            price_source='token_prices:2026-10-31:openrouter:minimax/minimax-m3.1-flash:tenstorrent/fp8:0.05,0.005,0.2:joint-gate-v1'))
        normalized = gate.openrouter_body(json.dumps(dict(model=paid['id'], messages=[dict(role='user',content='synthetic')])).encode(), MINIMAX)
        self.assertEqual(normalized['provider'], dict(only=['tenstorrent/fp8'], allow_fallbacks=False,
            require_parameters=True, max_price=dict(prompt=.05, completion=.2, request=0, image=0)))
        self.assertEqual(normalized['max_tokens'], 32768)
        self.assertEqual(router.route_maximum('opencode/minimax-m3.1-flash-free')['max_usd'], 0)
        self.assertIsNone(router.route_maximum('openrouter/minimax/minimax-m3.1-flash:free'))
        # Founder 2026-11-08: MiniMax free falls back to this gated paid route.
        self.assertEqual([r['route'] for r in router.routes('opencode/minimax-m3.1-flash-free')][-1], MINIMAX)

    def test_current_minimax_official_endpoint_contract(self):
        import hashlib
        record=fixture('router-minimax-price-record.json.gz')
        self.assertEqual(hashlib.sha256(record['raw_text'].encode()).hexdigest(),record['sha256'])
        endpoint=next(e for e in json.loads(record['raw_text'])['data']['endpoints'] if e['tag']==record['endpoint'])
        profile=prices.GATED_OPENROUTER[MINIMAX]
        self.assertEqual(endpoint['tag'],profile['endpoint'])
        self.assertEqual(endpoint['model_id'],'minimax/minimax-m3.1-flash')
        self.assertEqual(tuple(Decimal(endpoint['pricing'][k])*1000000 for k in ('prompt','input_cache_read','completion')),
                         tuple(map(Decimal,profile['prices'])))
        self.assertEqual((endpoint['context_length'],endpoint['max_completion_tokens']),(profile['context'],profile['output']))
        # Scheduled discounts never raise the pinned standard tariff.
        for override in endpoint['pricing'].get('overrides',[]):
            for field,ceiling in zip(('prompt','input_cache_read','completion'),profile['prices']):
                self.assertLessEqual(Decimal(override[field])*1000000,Decimal(ceiling))
        self.assertEqual(Decimal(endpoint['pricing'].get('input_cache_write','0')),0)
        self.assertTrue({'max_tokens','tools','tool_choice'}<=set(endpoint['supported_parameters']))
        maximum=router.route_maximum(MINIMAX)
        self.assertEqual(maximum['max_usd'],1.4155786)
        wire=gate.openrouter_body(json.dumps({'model':endpoint['model_id'],'messages':[{'role':'user','content':'synthetic'}]}),MINIMAX)
        self.assertEqual(wire['provider']['only'],['minimax'])
        self.assertEqual(wire['provider']['max_price'],dict(prompt=.15,completion=.6,request=0,image=0))

    def test_claude_public_contract_and_exact_aliases(self):
        sources = fixture('router-item8-source-evidence.json.gz')
        self.assertEqual(sources[0]['facts']['context'], 200000)
        self.assertEqual(sources[1]['facts']['rates'], [5,25,6.25,10,.5])
        lifecycle = next(r['facts'] for r in sources if 'model-deprecations' in r['url'])
        self.assertEqual((lifecycle['state'],lifecycle['retirement_not_before']), ('Active','2026-11-24'))
        for name, dollars, incoming, outgoing in [('compact',3,6000000,120000),('small',5,10000000,200000)]:
            route = CLAUDE + ':' + name
            self.assertEqual(router.route_maximum(route), dict(max_usd=float(dollars), max_input_tokens=incoming,
                max_output_tokens=outgoing, price_source='token_prices:2026-10-31:claude-opus-4-5-20251101:5.0,0.5,10.0,25.0:context=200000:output=16384:standard-global:joint-gate-v1:profile='+name+':usd='+str(dollars)))
            actual = core.lease(route)
            self.assertFalse(router.valid_maximum(replace(actual, **router.route_maximum(prices.GATED_CLAUDE))))
            env = {'CLAUDE_CODE_OAUTH_TOKEN':'synthetic', 'MAX_THINKING_TOKENS':'999999',
                   'CLAUDE_CODE_MAX_OUTPUT_TOKENS':'999999','ANTHROPIC_SMALL_FAST_MODEL':'wrong', 'HTTPS_PROXY':'wrong'}
            with gate.enforce(actual, env, {}, 2):
                self.assertEqual(env['MAX_THINKING_TOKENS'], '8192')
                self.assertEqual(env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'], '16384')
                self.assertEqual(env['ANTHROPIC_SMALL_FAST_MODEL'], CLAUDE.partition('/')[2])
                self.assertNotIn('HTTPS_PROXY', env)
        for route in (CLAUDE, CLAUDE+':medium', CLAUDE+':unknown'):
            self.assertIsNone(router.route_maximum(route))
            with self.assertRaises(ValueError): gate.request_body(b'{}', route)
        env = {'CLAUDE_CODE_OAUTH_TOKEN':'synthetic','MAX_THINKING_TOKENS':'999999'}
        with gate.enforce(core.lease(), env, {}, 2): self.assertNotIn('MAX_THINKING_TOKENS', env)

    def test_captured_two_request_cli_wire_and_refusals(self):
        captured = fixture('router-item8-claude45-cli.json.gz')
        self.assertEqual(captured['exit'], 0)
        self.assertEqual(len(captured['wire']), 2)
        self.assertIn('(deny network*)', captured['sandbox_policy'])
        old = fixture('router-maxima-cli-audit.json.gz')
        self.assertEqual(captured['binary_sha256'], old['pinned_offline_request_probe']['binary_sha256'])
        self.assertTrue(all(shape['beta'] == gate.BETAS for shape in captured['shapes']))
        second = json.loads(captured['wire'][1]['request_utf8'])
        kinds = [b.get('type') for m in second['messages'] for b in m['content'] if isinstance(b,dict)]
        self.assertTrue({'thinking','tool_use','tool_result'} <= set(kinds))
        for suffix in (':compact', ':small'):
            route = CLAUDE+suffix
            for wire in captured['wire']:
                body = gate.request_body(wire['request_utf8'].encode(), route)
                self.assertEqual(body['max_tokens'], 16384)
                self.assertEqual(body['thinking'], dict(type='enabled', budget_tokens=8192))
                self.assertNotIn('inference_geo', body)
                self.assertEqual(body['service_tier'], 'standard_only')
                parser = gate.Usage(16384, True, route)
                parser.feed(wire['response_utf8'].encode())
                self.assertEqual(parser.final(), dict(input_tokens=1, cache_creation_input_tokens=0,
                    cache_read_input_tokens=0, output_tokens=1))
            base = json.loads(captured['wire'][0]['request_utf8'])
            for change in [dict(model='claude-opus-5-5'), dict(inference_geo='us'),
                    dict(service_tier='priority'), dict(thinking=dict(type='adaptive')),
                    dict(thinking=dict(type='enabled',budget_tokens=True)),
                    dict(thinking=dict(type='enabled',budget_tokens=99999)),
                    dict(max_tokens=8192), dict(output_config=dict(effort='max')),
                    dict(tools=[dict(type='web_search_20250305',name='web_search')])]:
                with self.subTest(change=change), self.assertRaises(ValueError):
                    gate.request_body(json.dumps(base|change), route)
            formatted = base|dict(output_config=dict(effort='high',format={'type':'json_schema','schema':{'type':'object'}}))
            self.assertIn('format', gate.request_body(json.dumps(formatted),route)['output_config'])

    def test_unknown_usage_concurrency_and_headroom(self):
        for suffix, parallel in [(':compact',1),(':small',2)]:
            route = CLAUDE+suffix
            state = gate.Allowance(core.lease(route), deadline=time.monotonic()+5)
            ids = [state.reserve(16384) for _ in range(parallel)]
            self.assertTrue(all(ids))
            waiting = threading.Event(); original = state.condition.wait
            def wait(timeout): waiting.set(); return original(timeout)
            with patch.object(state.condition,'wait',side_effect=wait), ThreadPoolExecutor() as pool:
                next_request = pool.submit(state.reserve,16384)
                try:
                    self.assertTrue(waiting.wait(2)); self.assertFalse(next_request.done())
                    state.finish(ids.pop(),dict.fromkeys(prices.CLAUDE_GATE_FIELDS,0))
                    ids.append(next_request.result(timeout=2))
                finally: state.close()
            self.assertEqual(Decimal(state.snapshot()['held_usd']), Decimal('2.4096')*parallel)
            for identity in ids: state.finish(identity,dict.fromkeys(prices.CLAUDE_GATE_FIELDS,0))
            self.assertEqual(Decimal(state.snapshot()['held_usd']), Decimal('2.4096')*parallel)
            for invalid in ({'inference_geo':''}, {'speed':'fast'}, {'input_tokens':200001}):
                usage = dict.fromkeys(prices.CLAUDE_GATE_FIELDS,0)|invalid
                parser=gate.Usage(16384,True,route);parser.feed(core.sse(usage,model=CLAUDE.partition('/')[2]))
                self.assertIsNone(parser.final())
            state = gate.Allowance(core.lease(route))
            state.settled[0] = Decimal('0.5904' if parallel==1 else '2.5904')
            self.assertIsNone(state.reserve(16384)); self.assertTrue(state.exhaustion.is_set())
        state = gate.Allowance(core.lease(MINIMAX))
        for _ in range(3):
            identity=state.reserve(32768); self.assertIsNotNone(identity); state.finish(identity,None)
        self.assertIsNone(state.reserve(32768)); state.close()
        self.assertEqual(Decimal(state.snapshot()['held_usd']),Decimal('1.4155776'))

    def test_saved_writer_counters_are_priced_under_new_alias_not_old_tariff(self):
        # Counter envelope only: these are Opus5.5 records, NOT Opus4.5 role evidence.
        writer = next(e for c in core.PAID for e in c['continuation_budget']['events']
                      if e['id']=='252e6df1-f899-427e-aa07-7b98ba7eb156:result')
        usage = writer['tokens']
        expected = sum(Decimal(str(usage[k]))*rate for k,rate in zip(prices.CLAUDE_GATE_FIELDS,
                       map(Decimal,['5','.5','10','25'])))/1000000
        for suffix in (':compact',':small'):
            self.assertEqual(prices.claude_gate_cost(usage,CLAUDE+suffix),expected)
            self.assertEqual(prices.claude_cost(CLAUDE+suffix,usage),float(expected))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);ledger=path/'ledger.json'
            event=dict(type='assistant',message=dict(id='synthetic-envelope',usage=usage,content=[]))
            command=[sys.executable,'-c','import sys;print(sys.argv[1])',json.dumps(event)]
            with self.assertRaises(budget.BudgetError):
                budget.run_budgeted(command,path,dict(os.environ),path/'transcript',ledger,5,
                    containment=False, driver='claude',configured_model=CLAUDE+':small',role='writer',invocation_name='builder-partial',
                    max_cost=100,max_calls=1000,max_total_calls=1000,case_budget=1000)
            saved=json.loads(ledger.read_text())
            self.assertEqual(saved['estimated_subscription_cost_usd'],float(expected))
            self.assertFalse(saved.get('unpriced_invocations'))


class WireTests(unittest.TestCase):
    setUp = core.ProtocolTests.setUp

    def post_wire(self, base_url, path, raw, token, **headers):
        if isinstance(raw,str): raw=raw.encode()
        url=urlsplit(base_url);connection=http.client.HTTPConnection(url.hostname,url.port,timeout=3)
        try:
            connection.request('POST',path,raw,{'Authorization':'Bearer '+token,
                'Content-Type':'application/json',**headers})
            response=connection.getresponse()
            return response.status,response.read()
        finally:connection.close()

    def test_claude_capture_through_real_http_gate(self):
        captured=fixture('router-item8-claude45-cli.json.gz')
        for suffix in (':compact',':small'):
            route=CLAUDE+suffix;env={'CLAUDE_CODE_OAUTH_TOKEN':'synthetic'};cap={}
            self.responses=[w['response_utf8'].encode() for w in captured['wire']]
            before=len(self.seen)
            with self.assertRaisesRegex(budget.BudgetError,'^model_call_cap$'):
                with gate.enforce(core.lease(route),env,cap,5) as active:
                    for wire in captured['wire']:
                        status,data=self.post_wire(env['ANTHROPIC_BASE_URL'],'/v1/messages?beta=true',
                            wire['request_utf8'].encode(),'synthetic',**{'anthropic-beta':'context-1m-2025-08-07'})
                        self.assertEqual(status,200);self.assertEqual(data,wire['response_utf8'].encode())
                    self.assertEqual(active.state.snapshot()['validated_requests'],2)
                    self.assertEqual(Decimal(active.state.snapshot()['settled_usd']),Decimal('.000060'))
                    self.assertEqual(len(self.seen),before+2)
                    for _,body,headers in self.seen[before:]:
                        self.assertEqual({k.lower():v for k,v in headers.items()}['anthropic-beta'],gate.BETAS)
                        self.assertEqual(body['model'],'claude-opus-4-5-20251101')
                        self.assertEqual(body['max_tokens'],16384)
                        self.assertNotIn('inference_geo',body)
                    wrong=json.loads(captured['wire'][0]['request_utf8']);wrong['model']='claude-opus-5-5'
                    self.assertEqual(self.post_wire(env['ANTHROPIC_BASE_URL'],'/v1/messages',json.dumps(wrong),'synthetic')[0],400)
                    self.assertEqual(len(self.seen),before+2)
                    active.state.settled[0]=Decimal('0.5904' if suffix==':compact' else '2.5904')
                    status,_=self.post_wire(env['ANTHROPIC_BASE_URL'],'/v1/messages',captured['wire'][0]['request_utf8'],'synthetic')
                    self.assertEqual(status,400);self.assertEqual(len(self.seen),before+2)
            self.assertTrue(cap['closed']);self.assertTrue(cap['exhausted'])

    @historical_minimax_profile()
    def test_minimax_synthetic_wire_keeps_pin_and_unknowns(self):
        event=dict(id='synthetic-minimax',model='minimax/minimax-m3.1-flash',
            choices=[dict(index=0,finish_reason='stop')],
            usage=dict(prompt_tokens=1,completion_tokens=1,total_tokens=2))
        good=b'data: '+json.dumps(event).encode()+b'\n\ndata: [DONE]\n\n'
        # Unknown model ID is not accepted merely because the provider used a date suffix.
        wrong=b'data: '+json.dumps(event|{'model':'minimax/minimax-m3.1-flash-20261019'}).encode()+b'\n\ndata: [DONE]\n\n'
        self.responses=[good,wrong]
        env=dict(OPENROUTER_API_KEY='synthetic',XDG_CONFIG_HOME='/synthetic/config',
            XDG_DATA_HOME='/synthetic/data',XDG_CACHE_HOME='/synthetic/cache',
            OPENCODE_CONFIG_CONTENT='untrusted',HTTPS_PROXY='untrusted')
        cap={}
        from test_router_paid_spend import authority
        actual = core.lease(MINIMAX)
        with authority(actual), patch.object(gate.sys,'platform','linux'),gate.enforce(actual,env,cap,5) as active:
            options=json.loads(env['OPENCODE_CONFIG_CONTENT'])['provider']['openrouter']['options']
            self.assertNotIn('OPENROUTER_API_KEY',env);self.assertNotIn('HTTPS_PROXY',env)
            raw=json.dumps(dict(model='minimax/minimax-m3.1-flash',messages=[dict(role='user',content='synthetic')],stream=True))
            for data in (good,wrong):
                status,received=self.post_wire(options['baseURL'],'/api/v1/chat/completions',raw,options['apiKey'])
                self.assertEqual(status,200);self.assertEqual(received,data)
            self.assertEqual(active.state.snapshot()['validated_requests'],1)
            self.assertEqual(active.state.snapshot()['unknown_requests'],1)
            self.assertEqual(Decimal(active.state.snapshot()['held_usd']),Decimal('.23'))
            self.assertEqual(Decimal(active.state.snapshot()['settled_usd']),Decimal('.00000025'))
            for _,body,headers in self.seen:
                self.assertEqual(body['provider']['only'],['tenstorrent/fp8'])
                self.assertFalse(body['provider']['allow_fallbacks'])
                self.assertEqual(body['max_tokens'],32768)
        self.assertTrue(cap['closed'])


if __name__ == '__main__': unittest.main()
