"""Real public prices/receipts plus offline protocol faults; no model/provider call."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'factory'), str(ROOT/'bin')]
import argparse
import copy
from dataclasses import asdict, replace
from decimal import Decimal
import gzip
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import calibration
import budget
import model_call_gate as gate
import model_router as router
import model_runtime
import run
from token_prices import GATED_CLAUDE, CLAUDE_GATE_FIELDS, claude_gate_cost

FIXTURES = Path(__file__).with_name('fixtures')
PAID = json.loads(gzip.decompress((FIXTURES/'router-paid-deepseek.json.gz').read_bytes()))
LIMITS = json.loads(gzip.decompress((FIXTURES/'router-provider-limits.json.gz').read_bytes()))


def real_iterations():
    rows = {}
    cards = json.loads(gzip.decompress((FIXTURES/'20261029-real-public-cards.json.gz').read_bytes()))
    def walk(value):
        if isinstance(value, dict):
            if value.get('configured_model') == GATED_CLAUDE and value.get('id') and isinstance(value.get('tokens'), dict):
                rows[value['id']] = value
            for item in value.values(): walk(item)
        elif isinstance(value, list):
            for item in value: walk(item)
    walk(cards)
    return rows


def lease():
    return router.Lease(uuid.uuid4().hex, GATED_CLAUDE, 'claude-token', time.time()+180,
                        'subscription', 'anthropic', 'claude-token', **router.route_maximum(GATED_CLAUDE))


def body(**extra):
    return dict(model=GATED_CLAUDE.partition('/')[2], max_tokens=65536,
                messages=[{'role':'user', 'content':'synthetic protocol probe'}], **extra)


def sse(usage, *, stop=True, model='claude-opus-5-5'):
    start = dict(usage, output_tokens=0)
    events = [{'type':'message_start','message':{'model':model, 'usage':start}},
              {'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':usage['output_tokens']}}]
    if stop: events.append({'type':'message_stop'})
    return b''.join(b'data: '+json.dumps(e).encode()+b'\n\n' for e in events)


class MaximaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_real_routes_fail_closed_except_exact_bounded_subscription(self):
        store = router.Store(self.root/'router.sqlite')
        models = {r for c in router.CHAINS for r in c} | {'codex/gpt-6.1-sol', 'claude/unknown', 'unknown/model'}
        models |= {c['terminal_stop'].partition(':')[2] for c in LIMITS}
        for model in models:
            result = store.rpc('acquire', dict(id=uuid.uuid4().hex, model=model, accounts=list(router.ACCOUNTS),
                role='writer', deadline=time.time()+3600))
            if model != GATED_CLAUDE:
                self.assertEqual((result['kind'], result['reason']), ('wait','unbounded_route'))
                self.assertEqual(store.rpc('capacity', {'route':model})['slots'], 0)
            else:
                actual = router.Lease(**{k:v for k,v in result.items() if k != 'kind'})
                self.assertTrue(router.valid_lease(actual, model))
                self.assertEqual((actual.max_usd, actual.max_input_tokens, actual.max_output_tokens), (50.0,113636363,1136363))
                store.rpc('finish',dict(lease_id=actual.lease_id,outcome='denied',receipt=None))
        self.assertEqual(store.rpc('status', {})['leases'], [])
        for card in PAID:
            raw = json.dumps(card['continuation_budget'], sort_keys=True)
            events = [e for e in card['continuation_budget']['events'] if e.get('configured_model','').startswith('openrouter/deepseek/')]
            self.assertGreater(sum(e['cost'] for e in events), 0)
            self.assertIsNone(router.route_maximum(events[0]['configured_model']))
            self.assertEqual(json.dumps(card['continuation_budget'],sort_keys=True),raw)

    def test_real_aggregate_exam_and_more_than_eight_validated_requests(self):
        events = real_iterations(); self.assertEqual(len(events),153)
        costs = [claude_gate_cost(e['tokens']) for e in events.values()]
        worst = Decimal('19.041792')
        self.assertEqual((sum(c+worst < 50 for c in costs),sum(c>50 for c in costs),
                          sum(c<=50 and c+worst>=50 for c in costs)), (143,2,8))
        allowance = gate.Allowance(lease())
        samples = [i for e in events.values() for i in e['tokens'].get('iterations', [])][:20]
        for usage in samples:
            identity = allowance.reserve(32768); self.assertIsNotNone(identity)
            parser = gate.Usage(32768, True)
            for byte in sse(usage): parser.feed(bytes([byte]))
            self.assertIsNotNone(parser.final())
            allowance.finish(identity, parser.final())
        allowance.close(); result = allowance.snapshot()
        self.assertEqual(result['validated_requests'],20)
        self.assertEqual(result['forwarded_requests'],20)
        self.assertEqual(result['unknown_requests'],0)
        self.assertLess(Decimal(result['settled_usd']),50)

    def test_concurrent_reservations_and_close_never_refund_unknown(self):
        allowance = gate.Allowance(lease())
        ids = [allowance.reserve(32768), allowance.reserve(32768)]
        waited = threading.Event(); original = allowance.condition.wait
        def wait(timeout): waited.set(); return original(timeout)
        with patch.object(allowance.condition, 'wait', side_effect=wait), ThreadPoolExecutor() as pool:
            third = pool.submit(allowance.reserve,32768)
            self.assertTrue(waited.wait(2));self.assertFalse(third.done())
            self.assertFalse(allowance.is_set());self.assertEqual(allowance.forwarded,2)
            allowance.finish(ids[0],dict.fromkeys(CLAUDE_GATE_FIELDS,0))
            ids.append(third.result(timeout=2));self.assertIsNotNone(ids[-1])
        self.assertFalse(allowance.is_set())
        allowance.close(); before = allowance.snapshot()
        self.assertEqual((before['forwarded_requests'],before['unknown_requests'],before['in_flight_requests']), (3,2,0))
        self.assertEqual(Decimal(before['held_usd']),Decimal('38.083584'))
        for identity in ids:
            if identity: allowance.finish(identity,dict.fromkeys(CLAUDE_GATE_FIELDS,0))
        self.assertEqual(allowance.snapshot(),before)
        self.assertIsNone(allowance.reserve(1))  # Closed, and late handlers cannot refund.
        # Separate token admission, even when money is available.
        constrained = gate.Allowance(replace(lease(), max_output_tokens=32768))
        identity=constrained.reserve(32768)
        constrained.finish(identity,dict.fromkeys(CLAUDE_GATE_FIELDS,0)|{'output_tokens':32768})
        self.assertIsNone(constrained.reserve(1));self.assertTrue(constrained.is_set())
        sticky=gate.Allowance(lease());sticky.settled[0]=Decimal('32')
        self.assertIsNone(sticky.reserve(32768))  # W19.04 does not fit the remaining18.
        self.assertIsNone(sticky.reserve(1))  # W17.60 fits, but exhaustion is terminal.
        self.assertEqual(sticky.forwarded,0)
        cancel=threading.Event();cancel.set();cancelled=gate.Allowance(lease(),cancel)
        self.assertIsNone(cancelled.reserve(1));self.assertFalse(cancelled.exhaustion.is_set())

    def test_waiting_request_rechecks_unknowns_close_cancel_and_deadline(self):
        for stop in ('unknown','close','cancel','deadline'):
            cancel=threading.Event()
            allowance=gate.Allowance(lease(),cancel,time.monotonic()+(.2 if stop=='deadline' else 3))
            ids=[allowance.reserve(32768),allowance.reserve(32768)]
            waited=threading.Event();original=allowance.condition.wait
            def wait(timeout):waited.set();return original(timeout)
            with patch.object(allowance.condition,'wait',side_effect=wait),ThreadPoolExecutor() as pool:
                third=pool.submit(allowance.reserve,32768)
                self.assertTrue(waited.wait(1));self.assertFalse(allowance.is_set())
                if stop=='unknown':
                    for identity in ids:allowance.finish(identity,None)
                elif stop=='close':allowance.close()
                elif stop=='cancel':cancel.set()
                self.assertIsNone(third.result(timeout=2))
            self.assertEqual(allowance.exhaustion.is_set(),stop=='unknown')
            self.assertEqual(allowance.forwarded,2)
            if stop=='unknown':
                self.assertIsNone(allowance.reserve(1));self.assertEqual(allowance.unknown,2)
            allowance.close()

    def test_usage_only_refunds_complete_unambiguous_provider_controls(self):
        usage = dict(input_tokens=100,cache_read_input_tokens=50,cache_creation_input_tokens=25,output_tokens=10)
        good = sse(usage)
        bad = [sse(usage,stop=False),sse(usage,model='other'),good+good,
               good.replace(b'"output_tokens": 10',b'"output_tokens": -1'),
               good.replace(b'"input_tokens": 100',b'"input_tokens": true'),
               good.replace(b'"input_tokens": 100',b'"input_tokens": 1e999'),
               good.replace(b'"input_tokens": 100',b'"input_tokens": 1000001'),
               good.replace(b'"input_tokens": 100',b'"input_tokens": 100,"input_tokens":100'),
               good.replace(b'"output_tokens": 10',b'"output_tokens": 32769')]
        initial={'type':'message_start','message':{'model':'claude-opus-5-5','usage':dict(usage,output_tokens=0)}}
        missing_final=[initial,{'type':'content_block_delta','delta':{'type':'text_delta','text':'not final usage'}},
                       {'type':'message_stop'}]
        empty_final=[initial,{'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{}},{'type':'message_stop'}]
        errored=[initial,{'type':'error','error':{'type':'api_error'}},{'type':'message_stop'}]
        bad.extend(b''.join(b'data: '+json.dumps(e).encode()+b'\n\n' for e in events)
                   for events in (missing_final,empty_final,errored))
        for payload in bad:
            parser = gate.Usage(32768,True); parser.feed(payload)
            self.assertIsNone(parser.final(),payload[:100])
            allowance = gate.Allowance(lease()); identity = allowance.reserve(32768)
            allowance.finish(identity,parser.final()); allowance.close()
            self.assertEqual(allowance.snapshot()['unknown_requests'],1)
            self.assertEqual(allowance.snapshot()['held_usd'],'19.041792')
        parser = gate.Usage(32768,True);parser.feed(good)
        self.assertEqual(parser.final(),usage)
        for stop in (None, '', 'unknown'):
            parser=gate.Usage(32768,False)
            parser.feed(json.dumps({'type':'message','model':'claude-opus-5-5','usage':usage,'stop_reason':stop}).encode())
            self.assertIsNone(parser.final())
        parser=gate.Usage(32768,False)
        parser.feed(json.dumps({'type':'message','model':'claude-opus-5-5','usage':usage,'stop_reason':'end_turn'}).encode())
        self.assertEqual(parser.final(),usage)

    def test_client_and_supplied_tampering_denies_before_callbacks(self):
        original = lease()
        for fields in ({'max_usd':51.0},{'max_usd':True},{'max_usd':float('nan')},
                       {'max_input_tokens':True},{'max_output_tokens':9999999},{'price_source':'caller'}):
            changed = replace(original,**fields)
            self.assertFalse(router.valid_lease(changed,GATED_CLAUDE))
            c = SimpleNamespace(work=self.root, case_id='synthetic',card={'roles':{'writer':{'model':GATED_CLAUDE}}},
                batch_id='b',job_id='j',batch_deadline=time.time()+3600)
            runtime = model_runtime.ModelRuntime(self.root,Mock(),Mock(),Mock(),Mock())
            callback = Mock()
            with patch.dict(os.environ,{'UNBUG_PROVIDER_WAIT':'1'}), patch.object(router,'WAIT_SECONDS',0), \
                 patch.object(router,'finish'),patch.object(router,'_rpc',return_value={'cancelled':True}), \
                 patch.object(model_runtime.ModelRuntime,'_invoke') as invoke:
                with self.assertRaises(router.ProviderWait) as error:
                    runtime.call(c,[GATED_CLAUDE],'',self.root,'builder-1',lease=changed,before_attempt=callback)
            self.assertEqual(error.exception.wait.reason,'unbounded_route')
            callback.assert_not_called();invoke.assert_not_called()
        spoof = {'kind':'lease',**asdict(original)};spoof.pop('max_usd')
        c=SimpleNamespace(router_model=GATED_CLAUDE)
        with patch.object(router,'_rpc',return_value=spoof),patch.object(router,'finish'):
            result=router._admit('writer',c,time.time()+3600,original.lease_id,router.ACCOUNTS)
        self.assertEqual(result.reason,'unbounded_route')

    def test_execution_start_is_one_use_across_store_restart(self):
        path=self.root/'router.sqlite';store=router.Store(path)
        result=store.rpc('acquire',dict(id=uuid.uuid4().hex,model=GATED_CLAUDE,accounts=list(router.ACCOUNTS),role='writer',deadline=time.time()+3600))
        identity=result['lease_id'];store.rpc('start',{'lease_id':identity})
        store=router.Store(path)
        with self.assertRaisesRegex(ValueError,'already started'):store.rpc('start',{'lease_id':identity})
        with self.assertRaises(ValueError):store.rpc('observe',dict(observation_id='/execution/'+identity,healthy=True,pool='claude-token'))
        # A real old lease row lacks caps; neither renewal nor replay grants work.
        db=sqlite3.connect(path)
        with db:
            row=json.loads(db.execute('SELECT route FROM leases WHERE id=?',(identity,)).fetchone()[0])
            for key in router.MAXIMUM_FIELDS:row.pop(key)
            db.execute('UPDATE leases SET route=? WHERE id=?',(json.dumps(row),identity))
        db.close()
        with self.assertRaisesRegex(ValueError,'unbounded'):store.rpc('renew',{'lease_id':identity})
        store.rpc('finish',dict(lease_id=identity,outcome='denied',receipt=None))

    def test_cap_stop_is_not_preflight_failure_optional_skip_or_scientific_try(self):
        c=SimpleNamespace(case=self.root,card={},args=SimpleNamespace(bench_workers=1),
            models={'attacker':[GATED_CLAUDE],'reviewers':[[GATED_CLAUDE]],
                    'strong_calibrator':[GATED_CLAUDE],'easy_calibrator':[GATED_CLAUDE]})
        with patch.object(run,'opencode',side_effect=budget.BudgetError('model_call_cap')) as call:
            with self.assertRaisesRegex(budget.BudgetError,'^model_call_cap$'):run.provider_preflight(c)
            self.assertEqual(call.call_count,1)
        with patch.object(run,'g10_overlap_reason',return_value=None),patch.object(run,'make_pilots'), \
             patch.object(calibration,'isolated_attempt_context',return_value=nullcontext(c)), \
             patch.object(run,'calibrate',side_effect=budget.BudgetError('model_call_cap')), \
             patch.object(run,'pilot_home',return_value=self.root/'not-created'):
            with self.assertRaisesRegex(budget.BudgetError,'^model_call_cap$'):run.early_probe(c)
        self.assertEqual(calibration.interruption_label(budget.BudgetError('model_call_cap')),'model_call_cap')
        runtime=model_runtime.ModelRuntime(self.root,Mock(),Mock(),Mock(),Mock())
        with self.assertRaises(router.ProviderWait):
            runtime._invoke(SimpleNamespace(model_lease=lease()),[GATED_CLAUDE],'',self.root,'builder-1')

    def test_lost_cli_final_after_all_real_responses_complete_keeps_booked_estimate_within_cap(self):
        allowance=gate.Allowance(lease());emitted=[]
        for n,event in enumerate(real_iterations().values()):
            for usage in event['tokens'].get('iterations',[]):
                identity=allowance.reserve(32768)
                if identity is None:break
                allowance.finish(identity,{k:usage[k] for k in CLAUDE_GATE_FIELDS})
                emitted.append({'type':'assistant','message':{'id':'synthetic-wrap-'+str(n),
                    'model':'claude-opus-5-5','usage':usage,'content':[]}})
            if allowance.exhaustion.is_set():break
        allowance.close()
        self.assertGreater(len(emitted),8)
        self.assertEqual(allowance.snapshot()['unknown_requests'],0)
        ledger=self.root/'ledger.json'
        command=[sys.executable,'-c','import json,sys; [print(json.dumps(e),flush=True) for e in json.loads(sys.argv[1])]',json.dumps(emitted)]
        with self.assertRaises(budget.BudgetError):
            budget.run_budgeted(command,self.root,dict(os.environ),self.root/'transcript',ledger,5,
                driver='claude',configured_model=GATED_CLAUDE,role='writer',invocation_name='builder-partial',
                max_cost=100,max_calls=10000,max_total_calls=10000,case_budget=1000)
        saved=json.loads(ledger.read_text())
        self.assertGreater(saved['estimated_subscription_cost_usd'],0)
        self.assertLessEqual(saved['estimated_subscription_cost_usd'],50.0)  # exact, no epsilon.
        self.assertTrue(all(e.get('estimated_from_partial_usage') for e in saved['events']))

    def test_near_ceiling_float_booking_and_reserved_numerical_headroom(self):
        # Synthetic boundary arithmetic supplements, never replaces, the real-usage replay.
        usages=[dict(input_tokens=0,cache_read_input_tokens=0,cache_creation_input_tokens=1000000,output_tokens=32768),
                dict(input_tokens=0,cache_read_input_tokens=39,cache_creation_input_tokens=677068,output_tokens=0)]
        usages.append(usages[0])
        allowance=gate.Allowance(lease());events=[]
        for index,usage in enumerate(usages):
            identity=allowance.reserve(32768);self.assertIsNotNone(identity)
            allowance.finish(identity,usage)
            events.append({'type':'assistant','message':{'id':'boundary-'+str(index),'usage':usage,'content':[]}})
        self.assertGreater(allowance.settled[0],Decimal('49.99999'))
        self.assertIsNone(allowance.reserve(1));allowance.close()
        command=[sys.executable,'-c','import json,sys; [print(json.dumps(e),flush=True) for e in json.loads(sys.argv[1])]',json.dumps(events)]
        ledger=self.root/'near.json'
        with self.assertRaises(budget.BudgetError):
            budget.run_budgeted(command,self.root,dict(os.environ),self.root/'near-transcript',ledger,5,
                driver='claude',configured_model=GATED_CLAUDE,role='writer',invocation_name='builder-boundary',
                max_cost=100,max_calls=100,max_total_calls=100,case_budget=1000)
        self.assertLessEqual(json.loads(ledger.read_text())['estimated_subscription_cost_usd'],50.0)
        tight=gate.Allowance(lease())
        tight.settled[0]=Decimal('50')-Decimal('19.041792')-Decimal('0.0000005')
        self.assertIsNone(tight.reserve(32768));self.assertEqual(tight.forwarded,0)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.seen=[];self.failure=False;self.malformed=False
        owner=self
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                raw=self.rfile.read(int(self.headers['Content-Length']))
                owner.seen.append((self.path,json.loads(raw),dict(self.headers)))
                usage=dict(input_tokens=1,cache_read_input_tokens=0,cache_creation_input_tokens=0,output_tokens=1)
                data=b'not valid usage' if owner.malformed else sse(usage)
                self.send_response(503 if owner.failure else 200)
                self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(data)))
                self.send_header('anthropic-ratelimit-requests-reset','2030-01-01T00:00:00Z')
                self.send_header('Retry-After','17');self.end_headers();self.wfile.write(data)
        self.upstream=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        threading.Thread(target=self.upstream.serve_forever,daemon=True).start()
        self.addCleanup(self.upstream.server_close);self.addCleanup(self.upstream.shutdown)
        def connect(host,**kwargs):
            self.assertEqual(host,'api.anthropic.com')
            return http.client.HTTPConnection('127.0.0.1',self.upstream.server_port,**kwargs)
        mock=patch.object(gate.http.client,'HTTPSConnection',side_effect=connect);mock.start();self.addCleanup(mock.stop)

    def post(self, env, value, **headers):
        from urllib.parse import urlsplit
        url=urlsplit(env['ANTHROPIC_BASE_URL']);conn=http.client.HTTPConnection(url.hostname,url.port,timeout=3)
        conn.request('POST','/v1/messages?beta=true',json.dumps(value),
            {'Authorization':'Bearer synthetic','Content-Type':'application/json',**headers})
        response=conn.getresponse();result=(response.status,response.read(),dict(response.getheaders()));conn.close();return result

    def test_authenticated_normalisation_header_preservation_and_nonfatal_rejections(self):
        env={'PATH':os.environ['PATH'],'CLAUDE_CODE_OAUTH_TOKEN':'synthetic','ANTHROPIC_AUTH_TOKEN':'must-drop',
             'HTTPS_PROXY':'must-drop','CLAUDE_CODE_USE_BEDROCK':'1','FACTORY_STRATEGY_WORKERS':'2'}
        cap={}
        with gate.enforce(lease(),env,cap,3) as active:
            self.assertNotIn('ANTHROPIC_AUTH_TOKEN',env);self.assertNotIn('HTTPS_PROXY',env)
            self.assertNotIn('CLAUDE_CODE_USE_BEDROCK',env)
            self.assertEqual(self.post(env,body(),Authorization='Bearer stranger')[0],401)
            self.assertEqual(self.post(env,body(tools=[{'type':'web_search_20250305','name':'web_search'}]))[0],400)
            status,_,headers=self.post(env,body(context_management={},thinking={'type':'adaptive','display':'updates'}),
                **{'anthropic-beta':'fast-mode-bad','anthropic-workspace-id':'must-drop'})
            self.assertEqual(status,200);self.assertEqual(headers['Retry-After'],'17')
            self.assertFalse(active.is_set())
        self.assertEqual(len(self.seen),1)
        sent=self.seen[0][1];headers={k.lower():v for k,v in self.seen[0][2].items()}
        self.assertEqual(sent['max_tokens'],32768);self.assertNotIn('context_management',sent)
        self.assertEqual(sent['thinking'],{'type':'adaptive'});self.assertEqual(sent['service_tier'],'standard_only')
        self.assertEqual(headers['anthropic-beta'],gate.BETAS);self.assertNotIn('anthropic-workspace-id',headers)
        self.assertEqual(cap['validated_requests'],1);self.assertEqual(cap['unsupported_requests'],1)
        self.assertEqual(cap['forwarded_requests'],cap['validated_requests']+cap['unknown_requests']+cap['in_flight_requests'])

    def test_uncertain_requests_hold_full_w_and_exhaustion_stops_before_network(self):
        self.failure=True;env={'CLAUDE_CODE_OAUTH_TOKEN':'synthetic'};cap={}
        with self.assertRaisesRegex(budget.BudgetError,'^model_call_cap$'):
            with gate.enforce(lease(),env,cap,3) as active:
                self.assertEqual(self.post(env,body())[0],503)
                self.assertEqual(self.post(env,body())[0],503)
                self.assertEqual(self.post(env,body())[0],400)
                self.assertTrue(active.is_set())
        self.assertEqual(len(self.seen),2)
        self.assertEqual((cap['forwarded_requests'],cap['unknown_requests'],cap['in_flight_requests']),(2,2,0))
        self.assertEqual(Decimal(cap['held_usd']),Decimal('38.083584'))

    def test_parent_cancel_and_cleanup_failure_are_not_monetary_labels(self):
        cancel=threading.Event();cancel.set();cap={};env={'CLAUDE_CODE_OAUTH_TOKEN':'synthetic'}
        with gate.enforce(lease(),env,cap,3,cancel):
            status,data,_=self.post(env,body())
            self.assertEqual(status,400);self.assertIn(b'invocation_stopped',data)
        self.assertFalse(cap['exhausted']);self.assertEqual(self.seen,[])
        with self.assertRaisesRegex(budget.BudgetError,'^cancellation_failed$'):
            with gate.enforce(lease(),env,cap,3) as active:
                active.state.settled[0]=Decimal('32')
                self.assertIsNone(active.state.reserve(32768))
                raise budget.BudgetError('cancellation_failed')
        self.assertTrue(cap['exhausted']);self.assertTrue(cap['closed'])

    def test_close_between_connect_and_request_cannot_reconnect_or_forward(self):
        paused,release=threading.Event(),threading.Event()
        class Paused(http.client.HTTPConnection):
            def request(self,*args,**kwargs):
                paused.set()
                if not release.wait(3):raise AssertionError('test request was not released')
                return super().request(*args,**kwargs)
        def connect(host,**kwargs):
            self.assertEqual(host,'api.anthropic.com')
            return Paused('127.0.0.1',self.upstream.server_port,**kwargs)
        env={'CLAUDE_CODE_OAUTH_TOKEN':'synthetic'};cap={}
        with patch.object(gate.http.client,'HTTPSConnection',side_effect=connect):
            with gate.enforce(lease(),env,cap,3) as active,ThreadPoolExecutor() as pool:
                future=pool.submit(self.post,env,body())
                try:
                    self.assertTrue(paused.wait(2));active.close()
                    before=active.state.snapshot()
                finally:release.set()
                self.assertEqual(future.result(timeout=3)[0],502)
                self.assertEqual(active.state.snapshot(),before)
        self.assertEqual(self.seen,[])
        self.assertEqual((cap['unknown_requests'],cap['in_flight_requests']),(1,0))

    def test_successful_cli_cannot_hide_gate_unknown_usage_in_real_runtime_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'transcripts').mkdir();ram=root/'ram';ram.mkdir()
            (ram/'claude-token').write_text('synthetic-oauth-only')
            c=SimpleNamespace(work=root,case=root,case_id='synthetic',
                card={'roles':{'writer':{'model':GATED_CLAUDE}}},ledger=root/'ledger.json',
                batch_id='b',job_id='j',batch_deadline=time.time()+3600,
                args=argparse.Namespace(agent_timeout=5,max_cost=100,max_role_calls=1000,
                    max_total_calls=10000,no_progress_minutes=1,max_zero_tokens=3,case_budget=1000,resume=None))
            c.ledger.write_text(json.dumps({'cost':0,'calls':0,'events':[]}));before=c.ledger.read_bytes()
            store=router.Store(root/'router.sqlite');self.malformed=True
            def execute(cmd,cwd,env,*args,**kwargs):
                url=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(env['ANTHROPIC_BASE_URL'])
                connection=http.client.HTTPConnection(url.hostname,url.port,timeout=3)
                connection.request('POST','/v1/messages',json.dumps(body()),
                    {'Authorization':'Bearer synthetic-oauth-only','Content-Type':'application/json'})
                response=connection.getresponse();self.assertEqual(response.status,200);response.read();connection.close()
                return SimpleNamespace(returncode=0)
            runtime=model_runtime.ModelRuntime(root,Mock(),Mock(),lambda p,**kw:shutil.rmtree(p),Mock())
            with patch.dict(os.environ,{'UNBUG_PROVIDER_WAIT':'1'}),patch.object(router,'_rpc',store.rpc), \
                 patch.object(router,'SECRETS',ram),patch.object(model_runtime,'pinned_cli',return_value='synthetic'), \
                 patch.object(model_runtime,'run_budgeted',side_effect=execute):
                self.assertEqual(runtime.call(c,[GATED_CLAUDE],'',root,'builder-1'),0)
            receipt=json.loads((root/c.card['route_receipts'][0]['call_id']).read_text())
            self.assertFalse(receipt['final_usage_known'])
            self.assertEqual(receipt['cap_used']['unknown_requests'],1)
            self.assertTrue(receipt['cap_used']['closed'])
            self.assertEqual({k:receipt[k] for k in router.MAXIMUM_FIELDS},router.route_maximum(GATED_CLAUDE))
            self.assertNotIn('synthetic-oauth-only',json.dumps(receipt));self.assertEqual(c.ledger.read_bytes(),before)
            self.assertEqual(store.rpc('status',{})['leases'],[])


if __name__=='__main__':unittest.main()
