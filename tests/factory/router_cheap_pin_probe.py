"""Manual pinned OpenCode qualification, ONLY Linux Docker --network=none.

Synthetic upstream/credentials. Real runtime, router, accountant, CLI and gate.
Firewall subprocesses alone are faked: real-wall isolation is separately proven
by router-gate-wall-linux.json.gz. Never point this probe at a provider.
"""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'factory'),str(ROOT/'bin')]
import argparse
import copy
from decimal import Decimal
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
import pwd
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch
from types import SimpleNamespace
import uuid
import budget
import model_call_gate as gate
import model_router as router
import model_runtime
import run
from token_prices import GATED_OPENROUTER,openrouter_gate_cost


def main():
    binary,route,mode,role=sys.argv[1:5]
    assert route in GATED_OPENROUTER and mode in ('basic','tools','retry','compaction','exa')
    assert role in ('writer','stress_tester')
    assert sys.platform=='linux' and len(Path('/proc/net/route').read_text().splitlines())==1,'requires network none'
    version=subprocess.run([binary,'--version'],check=True,capture_output=True,text=True).stdout.strip()
    assert version=='1.19.0'
    pilot=pwd.getpwnam('pilot');seen=[];searches=[];commands=[];wall=[];exa_server=None;controls={'main':0,'compaction':0}
    result={'scope':'SYNTHETIC upstream; actual pinned CLI/runtime/gate/D; network none; firewall faked separately proven',
        'route':route,'mode':mode,'role':role,'version':version,'binary_sha256':hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT/'factory/model_call_gate.py',ROOT/'factory/model_runtime.py',ROOT/'factory/token_prices.py',Path(__file__).resolve())}}
    class Stub(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            text=json.dumps(body.get('messages',[])).lower()
            compact=('summar' in text and ('conversation' in text or 'compaction' in text) and not body.get('tools'))
            names=[v['function']['name'] for v in body.get('tools',[])]
            seen.append(dict(path=self.path,model=body.get('model'),max_tokens=body.get('max_tokens'),fields=sorted(body),
                provider=body.get('provider'),tools=names,compaction=compact,
                upstream_key_matches=self.headers.get('Authorization')=='Bearer synthetic-upstream-only',
                message_roles=[v.get('role') for v in body.get('messages',[])]))
            assert body['model']==route.partition('/')[2] and body['max_tokens']<=32768
            assert body['provider']['only']==[GATED_OPENROUTER[route]['endpoint']] and body['provider']['allow_fallbacks'] is False
            assert seen[-1]['upstream_key_matches']
            if mode=='retry':
                data=json.dumps({'error':{'message':'synthetic overloaded','code':503}}).encode()
                self.send_response(503);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data);return
            controls['compaction' if compact else 'main']+=1
            tool=(not compact and controls['main']==1 and mode in ('tools','compaction','exa'))
            delta={'role':'assistant','content':'COMPACTED_SYNTHETIC_HANDOFF' if compact else 'OK'}
            if tool:
                name='websearch' if mode=='exa' else 'bash'
                arguments={'query':'synthetic offline gate probe'} if mode=='exa' else {'command':'printf cheap-probe'}
                assert name in names and 'task' not in names
                delta={'role':'assistant','tool_calls':[{'index':0,'id':'call_synthetic','type':'function',
                    'function':{'name':name,'arguments':json.dumps(arguments)}}]}
            incoming=1040000 if mode=='compaction' and tool else 20
            usage={'prompt_tokens':incoming,'completion_tokens':2,'total_tokens':incoming+2}
            usage['cost']=float(openrouter_gate_cost(route,usage))
            event={'id':'chatcmpl-'+str(len(seen)),'object':'chat.completion.chunk','created':1,'model':body['model'],
                'choices':[{'index':0,'delta':delta,'finish_reason':'tool_calls' if tool else 'stop'}],'usage':usage}
            data=('data: '+json.dumps(event)+'\n\ndata: [DONE]\n\n').encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Stub);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def connect(host,**kwargs):
        assert host=='openrouter.ai';return http.client.HTTPConnection('127.0.0.1',server.server_port,**kwargs)
    original_run=subprocess.run
    def command(argv,*args,**kwargs):
        if list(argv[:2])==['sudo','iptables']:
            wall.append(argv);return subprocess.CompletedProcess(argv,0)
        return original_run(argv,*args,**kwargs)
    try:
        with tempfile.TemporaryDirectory(prefix='cheap-native-') as temporary:
            root=Path(temporary);root.chmod(0o755)
            if mode=='exa':
                # Test-only DNS and trust: actual CLI HTTPS request, no internet/proxy.
                # The production environment still drops EXA/PARALLEL credentials.
                cert=root/'exa.crt';key=root/'exa.key'
                subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                    '-subj','/CN=mcp.exa.ai','-addext','subjectAltName=DNS:mcp.exa.ai',
                    '-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
                with Path('/etc/hosts').open('a') as hosts:hosts.write('\n127.0.0.1 mcp.exa.ai\n')
                class Search(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                        url='https://'+self.headers['Host']+self.path
                        searches.append(dict(url=url,payload=payload,authorization_present='Authorization' in self.headers))
                        assert url=='https://mcp.exa.ai/mcp' and 'Authorization' not in self.headers
                        assert payload['method']=='tools/call' and payload['params']['name']=='web_search_exa'
                        data=json.dumps({'jsonrpc':'2.0','id':1,'result':{'content':[{'type':'text','text':'SYNTHETIC_OFFLINE_EXA'}]}}).encode()
                        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
                        self.end_headers();self.wfile.write(data)
                exa_server=ThreadingHTTPServer(('127.0.0.1',443),Search)
                context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
                exa_server.socket=context.wrap_socket(exa_server.socket,server_side=True)
                threading.Thread(target=exa_server.serve_forever,daemon=True).start()
            case=root/'case';case.mkdir();os.chown(case,pilot.pw_uid,pilot.pw_gid)
            work=root/'work';work.mkdir();(work/'transcripts').mkdir();ram=root/'ram';ram.mkdir()
            (ram/'openrouter-key').write_text('synthetic-upstream-only')
            ledger=work/'ledger.json';ledger.write_text(json.dumps(dict(cost=0,calls=0,events=[])))
            channel=dict(schema=1,batch='synthetic',job='synthetic',case='case-synthetic',reservation_id=str(uuid.uuid4()),
                revision=1,source_generation=None,committed_total_usd='3.000000000',batch_deadline=router.utc(time.time()+600))
            c=SimpleNamespace(work=work,case=case,case_id='case-synthetic',ledger=ledger,
                card={'roles':{role:{'model':route,'effort':'default'}}},args=run.argument_parser().parse_args(['--source','hunt']),
                batch_id='synthetic',job_id='synthetic',batch_deadline=channel['batch_deadline'],source_generation=None,
                job_money=copy.deepcopy(channel),authenticated_job_config={'job_money':copy.deepcopy(channel)},router_accounts=('openrouter-key',))
            c.args.agent_timeout=50;c.args.no_progress_minutes=1
            store=router.Store(root/'router.sqlite')
            runtime=model_runtime.ModelRuntime(root,lambda c,argv,**kw:command(list(map(str,argv)),capture_output=True,text=True,**kw),
                lambda *a:None,lambda p,**kw:shutil.rmtree(p),lambda user:Path('/home')/user)
            original_budget=model_runtime.run_budgeted
            def budgeted(argv,cwd,env,*args,**kwargs):
                cfg=json.loads(env['OPENCODE_CONFIG_CONTENT']);provider=cfg['provider']['openrouter']
                assert provider['options']['apiKey']!='synthetic-upstream-only'
                assert 'OPENROUTER_API_KEY' not in env and 'OPENCODE_TEST_MANAGED_CONFIG_DIR' not in env
                assert env['OPENCODE_ENABLE_EXA']=='1'
                commands.append({'argv':list(map(str,argv)),'env_keys':sorted(env),
                    'model':cfg['model'],'small_model':cfg['small_model'],'provider':{k:v for k,v in provider.items() if k!='options'},
                    'baseURL':provider['options']['baseURL'],'synthetic_client_key':True})
                if mode=='exa':env['NODE_EXTRA_CA_CERTS']=str(cert)
                return original_budget(argv,cwd,env,*args,**kwargs)
            outcome='done'
            with patch.object(router,'_rpc',store.rpc),patch.object(router,'SECRETS',ram), \
                 patch.object(model_runtime,'OPENCODE_BIN',binary),patch.object(model_runtime,'run_budgeted',side_effect=budgeted), \
                 patch.object(gate.http.client,'HTTPSConnection',side_effect=connect),patch.object(subprocess,'run',side_effect=command):
                try:runtime.call(c,[route],'Use only the synthetic local replies.',case,'builder-native' if role=='writer' else 'attacker-native',user='pilot')
                except budget.BudgetError as error:outcome=str(error)
            receipts=[json.loads(p.read_text()) for p in (work/'usage-receipts').glob('*.json')]
            transcripts='\n'.join(p.read_text() for p in (work/'transcripts').glob('*'))
            result.update(outcome=outcome,requests=seen,controls=controls,commands=commands,wall_commands=wall,
                search_requests=searches,test_overrides=['container hosts mcp.exa.ai to loopback','NODE_EXTRA_CA_CERTS synthetic certificate'] if mode=='exa' else [],receipts=receipts,ledger=json.loads(ledger.read_text()),transcript=transcripts)
            result['router_empty']=store.rpc('status',{})['leases']==[]
            expected='model_call_cap' if mode=='retry' else 'done'
            assert outcome==expected,(outcome,transcripts[-3000:])
            assert seen and result['router_empty']
            assert all('task' not in v['tools'] for v in seen)
            assert any('websearch' in v['tools'] for v in seen)
            if mode=='tools':assert len(seen)>=2 and 'tool' in seen[-1]['message_roles']
            if mode=='compaction':assert controls['compaction']>=1
            if mode=='exa':assert len(searches)==1 and len(seen)==2 and 'SYNTHETIC_OFFLINE_EXA' in transcripts
            if mode=='retry':assert len(seen)<=GATED_OPENROUTER[route]['windows']
            assert len(receipts)==1
            receipt=receipts[0];rows=result['ledger']['invocation_reservations'];row=rows[receipt['lease_id']]
            assert row['maximum_usd']==format(Decimal(str(router.route_maximum(route)['max_usd'])),'.9f')
            assert receipt['cap_used']['forwarded_requests']==len(seen)
            assert receipt['cap_used']['closed'] and receipt['cap_used']['in_flight_requests']==0
            assert row['state']==('pending' if mode=='retry' else 'settled')
            assert receipt['final_usage_known']==(mode!='retry')
            assert all(e['invocation_id']==row['invocation_id'] and e['lease_id']==row['lease_id'] for e in result['ledger']['events'])
            if mode=='retry':
                assert receipt['cap_used']['unknown_requests']==len(seen)
                assert budget.outstanding_reservations(result['ledger'])==Decimal(row['maximum_usd'])
            else:
                assert receipt['cap_used']['validated_requests']==len(seen) and receipt['cap_used']['unknown_requests']==0
                assert budget.outstanding_reservations(result['ledger'])==0
            budget.reconcile_reservations(work,ledger)
            result['reconciled_ledger']=json.loads(ledger.read_text())
            settled=result['reconciled_ledger']['invocation_reservations'][row['lease_id']]
            assert Decimal(settled['estimated_gap_usd'])==(Decimal(row['maximum_usd']) if mode=='retry' else 0)
            before=ledger.read_bytes();budget.reconcile_reservations(work,ledger)
            result['reconcile_replay_identical']=ledger.read_bytes()==before
            assert result['reconcile_replay_identical']
            result['status']='passed'
    except BaseException as error:
        result.update(status='failed',failure_type=type(error).__name__,failure=str(error),requests=seen,commands=commands)
        raise
    finally:
        if exa_server:exa_server.shutdown();exa_server.server_close()
        server.shutdown();server.server_close();thread.join(timeout=1)
        print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
