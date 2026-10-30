"""Real endpoint quotes and saved sessions; synthetic protocol controls, no providers."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'factory'),str(ROOT/'bin')]
from collections import OrderedDict
from dataclasses import replace
from decimal import Decimal
import copy
import gzip
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import budget
import job_authority
import model_call_gate as gate
import model_router as router
from token_prices import GATED_OPENROUTER,openrouter_gate_cost,openrouter_gate_maximum,runtime_prices

FIXTURES=Path(__file__).with_name('fixtures')
PRICES=json.loads(gzip.decompress((FIXTURES/'router-cheap-price-records.json.gz').read_bytes()))
CARDS=json.loads(gzip.decompress((FIXTURES/'router-paid-deepseek.json.gz').read_bytes()))


def lease(route):
    return router.Lease(uuid.uuid4().hex,route,'openrouter-key',time.time()+180,'paid',router.family(route),
                        'openrouter-key',**router.route_maximum(route))


def request(route,**extra):
    return dict(model=route.partition('/')[2],max_tokens=65536,messages=[dict(role='user',content='synthetic')],**extra)


def response(route,usage=None):
    return dict(id='chatcmpl-synthetic',model=route.partition('/')[2],
        choices=[dict(index=0,delta={'content':'synthetic'},finish_reason='stop')],
        usage=usage or dict(prompt_tokens=100,completion_tokens=10,total_tokens=110))


def encoded(event,streaming):
    return (('data: '+json.dumps(event)+'\n\ndata: [DONE]\n\n').encode() if streaming else json.dumps(event).encode())


class CheapTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def test_exact_profiles_match_raw_prices_and_reject_cache_write_and_free(self):
        expected=[('1.710490600',3932162,1966081),('1.174406120',8388615,2796205)]
        for (route,profile),record,values in zip(GATED_OPENROUTER.items(),PRICES,expected):
            self.assertEqual(hashlib.sha256(record['raw_text'].encode()).hexdigest(),record['sha256'])
            self.assertEqual(json.loads(record['raw_text']),record['response'])
            self.assertEqual(record['checked_on'],'2026-10-30')
            endpoint=next(e for e in record['response']['data']['endpoints'] if e['tag']==profile['endpoint'])
            actual=tuple(Decimal(endpoint['pricing'][k])*1000000 for k in ('prompt','input_cache_read','completion'))
            self.assertEqual(actual,tuple(map(Decimal,profile['prices'])))
            self.assertEqual(Decimal(endpoint['pricing'].get('input_cache_write','0')),0)
            self.assertEqual(endpoint['context_length'],profile['context'])
            maximum=router.route_maximum(route)
            self.assertEqual((format(Decimal(str(maximum['max_usd'])),'.9f'),maximum['max_input_tokens'],maximum['max_output_tokens']),values)
            self.assertEqual(maximum['price_source'],'token_prices:2026-10-30:'+route.replace('/',':',1)+':'+profile['endpoint']+':'+','.join(profile['prices'])+':joint-gate-v1')
            self.assertTrue(router.valid_lease(lease(route),route))
            with patch.dict(profile,cache_write='0.000001'):self.assertIsNone(router.route_maximum(route))
            for fields in ({'max_usd':5.0},{'max_input_tokens':True},{'max_output_tokens':9},{'price_source':'old'}, {'expires_at':1}):
                self.assertFalse(router.valid_lease(replace(lease(route),**fields),route))
        free='opencode/deepseek-v4.1-flash-free';self.assertIsNone(router.route_maximum(free))
        store=router.Store(self.root/'router.sqlite')
        # Existing same-family paid fallback is allowed only with its account.
        for accounts in ([],['claude-token']):
            result=store.rpc('acquire',dict(id=uuid.uuid4().hex,model=free,accounts=accounts,role='writer',deadline=time.time()+3600))
            # A qualified family fallback exists but its account is unavailable:
            # preserve the router's existing outage classification and no lease.
            self.assertEqual((result['kind'],result['reason']),('wait','outage'))
        self.assertEqual(store.rpc('status',{})['leases'],[])
        result=store.rpc('acquire',dict(id=uuid.uuid4().hex,model=free,accounts=['openrouter-key'],role='writer',deadline=time.time()+3600))
        self.assertEqual(result['route'],'openrouter/deepseek/deepseek-v4.1-flash')
        store.rpc('finish',dict(lease_id=result['lease_id'],outcome='denied',receipt=None))

    def test_real_session_replay_and_three_dollar_job_fit(self):
        expected={'e15450':(17,Decimal('0.8515172860'),Decimal('2.4924907220')),
                  '873d7f':(14,Decimal('0.6516037902'),Decimal('2.2841285566'))}
        longest={route:(0,0) for route in GATED_OPENROUTER}
        for card in CARDS:
            sessions=OrderedDict()
            for event in card['continuation_budget']['events']:
                if event.get('configured_model') in GATED_OPENROUTER:sessions.setdefault(event['id'].split(':')[0],[]).append(event)
            work=self.root/card['case'];work.mkdir();(work/'usage-receipts').mkdir();path=work/'ledger.json'
            path.write_text(json.dumps(dict(cost=0,calls=0,events=[])))
            channel=json.loads((ROOT/'tests/fixtures/factory/stream-d/job-money.json').read_text())
            channel['committed_total_usd']='3.000000000';authority=job_authority.read(channel,copy.deepcopy(channel))
            total=peak=Decimal(0)
            for index,(session,events) in enumerate(sessions.items()):
                route=events[0]['configured_model'];self.assertTrue(all(e['configured_model']==route for e in events))
                actual=lease(route);allowance=gate.Allowance(actual)
                peak=max(peak,total+Decimal(str(actual.max_usd)))
                row=budget.reserve_invocation(path,actual,actual.max_usd,authority,operation_id=str(uuid.uuid4()),call_name='builder-'+str(index))
                priced=[];inputs=0
                for event in events:
                    tokens=event['tokens'];incoming=tokens['input']+tokens['cache']['read']+tokens['cache']['write']
                    outgoing=tokens['output']+tokens['reasoning'];inputs+=incoming
                    identity=allowance.reserve(32768);self.assertIsNotNone(identity)
                    allowance.finish(identity,dict(prompt_tokens=incoming,completion_tokens=outgoing))
                    rates=list(map(Decimal,GATED_OPENROUTER[route]['prices']))
                    cost=(Decimal(tokens['input'])*rates[0]+Decimal(tokens['cache']['read'])*rates[1]
                          +Decimal(outgoing)*rates[2])/1000000
                    self.assertEqual(tokens['cache']['write'],0)
                    total+=cost
                    # Explicit repricing example on a separate ledger; never mutate source receipts.
                    priced.append(dict(event,cost=float(cost),invocation_id=row['invocation_id'],lease_id=actual.lease_id))
                self.assertIsNotNone(allowance.reserve(32768));allowance.close()
                longest[route]=max(longest[route],(len(events),inputs))
                receipt=dict(lease_id=actual.lease_id,final_usage_known=True,events=priced,booked_event_ids=[])
                (work/'usage-receipts'/(actual.lease_id+'.json')).write_text(json.dumps(receipt))
                budget.complete_invocation(work,path,actual.lease_id)
                ledger=json.loads(path.read_text());self.assertEqual(budget.outstanding_reservations(ledger),0)
                self.assertLessEqual(budget.case_spending(ledger)['total_spent_usd'],3)
                before=path.read_bytes();budget.complete_invocation(work,path,actual.lease_id);self.assertEqual(path.read_bytes(),before)
            self.assertEqual((len(sessions),total,peak),expected[card['case'].rsplit('-',1)[1]])
        self.assertEqual(list(longest.values()),[(29,1611966),(34,2568428)])

    def test_request_schema_and_exact_provider_ceiling(self):
        for route,profile in GATED_OPENROUTER.items():
            original=request(route,stream=True,reasoning={'enabled':True,'max_tokens':90000})
            body=gate.openrouter_body(json.dumps(original),route)
            self.assertEqual(body['max_tokens'],32768);self.assertEqual(body['reasoning']['max_tokens'],32768)
            self.assertEqual(body['usage'],{'include':True});self.assertEqual(body['stream_options'],{'include_usage':True})
            incoming,_,outgoing=map(float,profile['prices'])
            self.assertEqual(body['provider'],dict(only=[profile['endpoint']],allow_fallbacks=False,require_parameters=True,
                             max_price=dict(prompt=incoming,completion=outgoing,request=0,image=0)))
            if profile['endpoint']=='deepinfra/fp8':
                tags={e['tag'] for e in PRICES[1]['response']['data']['endpoints']}
                self.assertTrue({'deepinfra/fp8/flex','deepinfra/fp8/priority'}<=tags)
                self.assertFalse(set(body['provider']['only']) & {'deepinfra/fp8/flex','deepinfra/fp8/priority'})
            bad=[{'provider':{}},{'plugins':[]},{'models':['other']},{'model':'other'},{'n':2},
                 {'web_search_options':{}},{'max_tokens':True},{'stream':'yes'},
                 {'messages':[dict(role='user',content=[dict(type='image_url',image_url={'url':'https://invalid'})])]},
                 {'tools':[dict(type='web_search')]},{'reasoning':{'unknown':True}},
                 {'usage':{'unknown':True}},{'response_format':{'type':'unknown'}}]
            for change in bad:
                with self.subTest(route=route,change=change),self.assertRaises((ValueError,TypeError)):
                    gate.openrouter_body(json.dumps(request(route)|change),route)
            for raw in (json.dumps(request(route)).replace('65536','NaN'),json.dumps(request(route)).replace('65536','65536,"max_tokens":1')):
                with self.assertRaises(ValueError):gate.openrouter_body(raw,route)

    def test_only_complete_unambiguous_usage_refunds(self):
        for route,profile in GATED_OPENROUTER.items():
            for streaming in (False,True):
                good=response(route)
                parser=gate.OpenRouterUsage(route,streaming)
                for byte in encoded(good,streaming):parser.feed(bytes([byte]))
                self.assertEqual(parser.final(),good['usage'])
                variants=[dict(good,model='other'),dict(good,error={}),dict(good,choices=[]),
                    dict(good,choices=good['choices']*2),dict(good,usage={}),
                    dict(good,usage=good['usage']|{'prompt_tokens':True}),
                    dict(good,usage=good['usage']|{'total_tokens':111}),
                    dict(good,usage=good['usage']|{'cost':100}),
                    dict(good,usage=good['usage']|{'completion_tokens_details':{'reasoning_tokens':11}}),
                    dict(good,usage={'prompt_tokens':profile['context']+1,'completion_tokens':0,'total_tokens':profile['context']+1}),
                    dict(good,usage={'prompt_tokens':0,'completion_tokens':profile['output']+1,'total_tokens':profile['output']+1})]
                for event in variants:
                    parser=gate.OpenRouterUsage(route,streaming);parser.feed(encoded(event,streaming));self.assertIsNone(parser.final())
                if streaming:
                    for data in (encoded(good,True).replace(b'data: [DONE]\n\n',b''),encoded(good,True)*2,
                                 encoded(good,True).replace(b'"prompt_tokens": 100',b'"prompt_tokens":100,"prompt_tokens":1')):
                        parser=gate.OpenRouterUsage(route,True);parser.feed(data);self.assertIsNone(parser.final())
            state=gate.Allowance(lease(route));holds=[state.reserve(1) for _ in range(profile['windows'])]
            self.assertTrue(all(holds))
            for identity in holds:state.finish(identity,None)
            self.assertIsNone(state.reserve(1));self.assertTrue(state.exhaustion.is_set());state.close()
            before=state.snapshot()
            for identity in holds:state.finish(identity,{'prompt_tokens':0,'completion_tokens':0})
            self.assertEqual(state.snapshot(),before)
            self.assertEqual(before['unknown_requests'],profile['windows'])
            self.assertEqual(before['max_request_output_tokens'],profile['output'])

    def test_overlapping_requests_wait_for_refund_and_platform_guards_deny_launch(self):
        for route,profile in GATED_OPENROUTER.items():
            state=gate.Allowance(lease(route),deadline=time.monotonic()+3)
            holds=[state.reserve(32768) for _ in range(profile['windows'])]
            entered=threading.Event();finished=threading.Event();result=[]
            def reserve():
                entered.set();result.append(state.reserve(32768));finished.set()
            thread=threading.Thread(target=reserve);thread.start()
            self.assertTrue(entered.wait(1));self.assertFalse(finished.wait(.1))
            self.assertFalse(state.exhaustion.is_set())
            state.finish(holds[0],dict(prompt_tokens=0,completion_tokens=0))
            self.assertTrue(finished.wait(1));thread.join(1)
            self.assertIsNotNone(result[0]);state.close()
            self.assertEqual(state.snapshot()['unknown_requests'],profile['windows'])
            for platform,managed in [('darwin',False),('linux',True)]:
                with self.subTest(platform=platform,managed=managed),patch.object(gate.sys,'platform',platform), \
                     patch.object(gate.Path,'exists',return_value=managed),patch.object(gate,'Gate') as create:
                    with self.assertRaisesRegex(budget.BudgetError,'^route_feature_unsupported$'):
                        with gate.enforce(lease(route),dict(OPENROUTER_API_KEY='synthetic',
                            XDG_CONFIG_HOME='config',XDG_DATA_HOME='data',XDG_CACHE_HOME='cache'),{},1):
                            self.fail('unsupported setup launched')
                    create.assert_not_called()

    def test_saved_pinned_cli_runtime_proof_and_unknown_reconciliation(self):
        record=json.loads(gzip.decompress((FIXTURES/'router-cheap-native.json.gz').read_bytes()))
        self.assertEqual(record['status'],'passed')
        self.assertEqual(hashlib.sha256(record['probe_source'].encode()).hexdigest(),record['probe_source_sha256'])
        self.assertEqual(len(record['probes']),12)
        for proof in record['probes']:
            route=proof['route'];profile=GATED_OPENROUTER[route];mode=proof['mode']
            self.assertEqual((proof['status'],proof['exit_code'],proof['version']),('passed',0,'1.19.0'))
            self.assertIn('--network=none',proof['command']);self.assertTrue(proof['router_empty'])
            self.assertEqual(proof['source_sha256']['tests/factory/router_cheap_pin_probe.py'],record['probe_source_sha256'])
            for command in proof['commands']:
                self.assertIn('pilot',command['argv']);self.assertNotIn('OPENROUTER_API_KEY',command['env_keys'])
                self.assertEqual((command['model'],command['small_model']),(route,route))
            for request_ in proof['requests']:
                self.assertEqual(request_['model'],route.partition('/')[2]);self.assertLessEqual(request_['max_tokens'],32768)
                self.assertEqual(request_['provider']['only'],[profile['endpoint']])
                self.assertFalse(request_['provider']['allow_fallbacks']);self.assertTrue(request_['upstream_key_matches'])
                self.assertNotIn('task',request_['tools'])
                if not request_['compaction']:self.assertIn('websearch',request_['tools'])
            receipt,=proof['receipts'];row=proof['ledger']['invocation_reservations'][receipt['lease_id']]
            self.assertEqual(Decimal(row['maximum_usd']),Decimal(str(router.route_maximum(route)['max_usd'])))
            self.assertEqual(receipt['cap_used']['forwarded_requests'],len(proof['requests']))
            unknown=mode=='retry';self.assertEqual(receipt['final_usage_known'],not unknown)
            self.assertEqual(row['state'],'pending' if unknown else 'settled')
            self.assertEqual(proof['outcome'],'model_call_cap' if unknown else 'done')
            gap=proof['reconciled_ledger']['invocation_reservations'][row['lease_id']]['estimated_gap_usd']
            self.assertEqual(Decimal(gap),Decimal(row['maximum_usd']) if unknown else 0)
            self.assertTrue(proof['reconcile_replay_identical'])
            if unknown:self.assertEqual(receipt['cap_used']['unknown_requests'],profile['windows'])
            else:self.assertEqual(receipt['cap_used']['validated_requests'],len(proof['requests']))
            if mode=='compaction':self.assertGreaterEqual(proof['controls']['compaction'],1)
            if mode=='exa':
                search,=proof['search_requests'];self.assertEqual(search['url'],'https://mcp.exa.ai/mcp')
                self.assertFalse(search['authorization_present']);self.assertEqual(search['payload']['params']['name'],'web_search_exa')
        self.assertEqual({(p['route'],p['role']) for p in record['probes'] if p['mode']=='exa'},
                         {(r,s) for r in GATED_OPENROUTER for s in ('writer','stress_tester')})

    def test_gateway_only_key_custody_environment_and_real_http(self):
        seen=[]
        class Stub(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append((self.path,body,self.headers['Authorization']))
                data=encoded(response('openrouter/'+body['model']),False)
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Stub);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def connect(host,**kw):
            self.assertEqual(host,'openrouter.ai');return http.client.HTTPConnection('127.0.0.1',server.server_port,**kw)
        for route in GATED_OPENROUTER:
            env=dict(PATH=os.environ['PATH'],HOME=str(self.root),OPENROUTER_API_KEY='synthetic-upstream-only',
                CLAUDE_CODE_OAUTH_TOKEN='synthetic-other',HTTPS_PROXY='http://invalid',OPENCODE_TEST_MANAGED_CONFIG_DIR='/invalid',
                PARALLEL_API_KEY='synthetic-other',OPENCODE_WEBSEARCH_PROVIDER='parallel',OPENCODE_CONFIG='/invalid',
                XDG_CONFIG_HOME=str(self.root/'config'),XDG_DATA_HOME=str(self.root/'data'),XDG_CACHE_HOME=str(self.root/'cache'))
            used={}
            with patch.object(gate.sys,'platform','linux'),patch.object(gate.http.client,'HTTPSConnection',side_effect=connect):
                with gate.enforce(lease(route),env,used,3) as active:
                    self.assertFalse(set(env)&{'OPENROUTER_API_KEY','CLAUDE_CODE_OAUTH_TOKEN','HTTPS_PROXY','OPENCODE_TEST_MANAGED_CONFIG_DIR','PARALLEL_API_KEY','OPENCODE_WEBSEARCH_PROVIDER','OPENCODE_CONFIG'})
                    self.assertEqual(env['OPENCODE_ENABLE_EXA'],'1')
                    config=json.loads(env['OPENCODE_CONFIG_CONTENT']);provider=config['provider']['openrouter']
                    self.assertEqual(config['model'],route);self.assertEqual(config['small_model'],route)
                    self.assertEqual(provider['models'][route.partition('/')[2]]['cost'],runtime_prices(route))
                    self.assertNotEqual(provider['options']['apiKey'],'synthetic-upstream-only')
                    for token,status in [('synthetic-upstream-only',401),(provider['options']['apiKey'],200)]:
                        c=http.client.HTTPConnection('127.0.0.1',active.server.server_port,timeout=2)
                        c.request('POST','/api/v1/chat/completions',json.dumps(request(route)),{'Authorization':'Bearer '+token})
                        r=c.getresponse();r.read();self.assertEqual(r.status,status);c.close()
                    with active.state.condition:self.assertTrue(active.state.condition.wait_for(lambda:not active.state.active,timeout=1))
                self.assertEqual(used['validated_requests'],1);self.assertEqual(used['unknown_requests'],0)
            path,body,auth=seen[-1];self.assertEqual(path,'/api/v1/chat/completions')
            self.assertEqual(body['provider']['only'],[GATED_OPENROUTER[route]['endpoint']])
            self.assertEqual(auth,'Bearer synthetic-upstream-only')
        self.assertEqual(len(seen),2)


if __name__=='__main__':unittest.main()
