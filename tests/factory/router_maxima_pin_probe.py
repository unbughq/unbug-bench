"""Manual native-CLI exam. Run ONLY in an isolated Linux Docker --network=none.

Arguments: public pinned Claude executable, scenario (tools/retry/compaction/output/concurrency).
The only credential is synthetic. HTTPSConnection is patched in this TEST process
to a fake loopback upstream; there is no product upstream override.
"""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'factory'),str(ROOT/'bin')]
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
import pwd
import shutil
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import budget
import model_call_gate as gate
import model_router as router
import model_runtime


def main():
    binary,mode=sys.argv[1:3]
    if mode not in ('tools','retry','compaction','output','concurrency'):raise SystemExit('unknown synthetic scenario')
    if not Path('/proc/net/route').is_file() or len(Path('/proc/net/route').read_text().splitlines())>1:
        raise SystemExit('requires isolated Linux --network=none; refusing networked host')
    version=subprocess.run([binary,'--version'],capture_output=True,text=True,check=True).stdout.strip()
    if not version.startswith('2.1.299 '):raise SystemExit('wrong public pin')
    pilot=pwd.getpwnam('pilot')
    seen=[];controls={'main':0,'compaction':0};commands=[]
    queued=threading.Event();release=threading.Event();helper_codes=[]
    original_init=gate.Allowance.__init__
    def observed_init(self,*args,**kwargs):
        original_init(self,*args,**kwargs)
        original_wait=self.condition.wait
        def wait(timeout):queued.set();return original_wait(timeout)
        self.condition.wait=wait
    class Fake(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            hosted=any(t.get('type') not in (None,'custom') for t in body.get('tools',[]))
            last=str(body.get('messages',[])[-1].get('content','')).lower() if body.get('messages') else ''
            compact=('tasked with summarizing' in str(body.get('system','')).lower()
                     or ('summar' in last and ('conversation' in last or 'context' in last)))
            seen.append({'path':self.path,'model':body.get('model'),'max_tokens':body.get('max_tokens'),
                'fields':sorted(body),'hosted':hosted,'compaction':compact,
                'beta':self.headers.get('anthropic-beta'),'tier':body.get('service_tier'),
                'auth_matches_synthetic':self.headers.get('Authorization')=='Bearer synthetic-native-gate'})
            assert not hosted and body['max_tokens']<=32768 and body['service_tier']=='standard_only'
            if mode=='concurrency' and len(seen)<=2:
                assert release.wait(30),'third native CLI request never queued'
            if mode=='compaction' and len(seen)==2 and not compact:
                data=json.dumps({'type':'error','error':{'type':'invalid_request_error',
                    'message':'prompt is too long: 1100000 tokens > 1000000 maximum'}}).encode()
                self.send_response(400);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            if mode=='retry':
                data=json.dumps({'type':'error','error':{'type':'overloaded_error','message':'synthetic retry failure'}}).encode()
                self.send_response(503);self.send_header('Retry-After','0');self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            if compact:
                controls['compaction']+=1;content={'type':'text','text':'COMPACTED_SYNTHETIC_HANDOFF'};stop='end_turn'
            else:
                controls['main']+=1;n=controls['main']
                if n==1 and mode in ('tools','compaction'):
                    content={'type':'tool_use','id':'tool_synthetic_bash','name':'Bash',
                        'input':{'command':'printf offline-ok','description':'synthetic local probe'}};stop='tool_use'
                elif n==2 and mode=='tools':
                    content={'type':'tool_use','id':'tool_synthetic_search','name':'WebSearch',
                        'input':{'query':'synthetic offline request cap probe'}};stop='tool_use'
                else:content={'type':'text','text':'OK'};stop='max_tokens' if mode=='output' and n==1 else 'end_turn'
            incoming=950000 if mode=='compaction' and controls['main']==1 and not compact else 1
            outgoing=32768 if stop=='max_tokens' else 1
            usage={'input_tokens':incoming,'cache_read_input_tokens':0,'cache_creation_input_tokens':0,'output_tokens':0}
            start=dict(content);start['input' if content['type']=='tool_use' else 'text']={} if content['type']=='tool_use' else ''
            delta=({'type':'input_json_delta','partial_json':json.dumps(content['input'])} if content['type']=='tool_use'
                   else {'type':'text_delta','text':content['text']})
            events=[{'type':'message_start','message':{'id':'msg_synthetic_'+str(len(seen)), 'type':'message',
                'role':'assistant','model':'claude-opus-5-5','content':[],'stop_reason':None,'stop_sequence':None,'usage':usage}},
                {'type':'content_block_start','index':0,'content_block':start},
                {'type':'content_block_delta','index':0,'delta':delta},{'type':'content_block_stop','index':0},
                {'type':'message_delta','delta':{'stop_reason':stop,'stop_sequence':None},'usage':{'output_tokens':outgoing}},
                {'type':'message_stop'}]
            data=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Fake)
    threading.Thread(target=upstream.serve_forever,daemon=True).start()
    def connect(host,**kwargs):
        assert host=='api.anthropic.com'
        return http.client.HTTPConnection('127.0.0.1',upstream.server_port,**kwargs)
    with tempfile.TemporaryDirectory(prefix='router-public-probe-') as temporary:
        root=Path(temporary);root.chmod(0o755)
        case=root/'synthetic';case.mkdir();os.chown(case,pilot.pw_uid,pilot.pw_gid)
        ram=root/'synthetic-ram';ram.mkdir()
        for label in router.ACCOUNTS[:2]:(ram/label).write_text('synthetic-native-gate')
        (root/'transcripts').mkdir()
        c=SimpleNamespace(work=root,case=case,case_id='synthetic-protocol-only',
            card={'roles':{'writer':{'model':'claude/claude-opus-5-5','effort':'high'}}},
            ledger=root/'ledger.json',batch_id='synthetic-b',job_id='synthetic-j',batch_deadline=time.time()+600,
            args=argparse.Namespace(agent_timeout=45,max_cost=100,max_role_calls=1000,max_total_calls=10000,
                no_progress_minutes=1,max_zero_tokens=3,case_budget=1000,resume=None))
        store=router.Store(root/'router.sqlite');rpc_ops=[]
        def rpc(operation,data):rpc_ops.append(operation);return store.rpc(operation,data)
        def command(c,argv,**kwargs):return subprocess.run(list(map(str,argv)),capture_output=True,text=True,**kwargs)
        original=model_runtime.run_budgeted
        def budgeted(argv,cwd,env,*args,**kwargs):
            # Test-only adversarial CLI settings AFTER the product allowlist:
            # make native SDK retries/compaction happen, never weaken gate limits.
            extra=({'CLAUDE_CODE_MAX_RETRIES':'3'} if mode=='retry' else
                   {'CLAUDE_AUTOCOMPACT_PCT_OVERRIDE':'1','CLAUDE_CODE_AUTO_COMPACT_WINDOW':'100000'} if mode=='compaction' else {})
            env.update(extra)
            if extra and argv[0]=='sudo':
                argv=list(argv);argv[1]+=','+','.join(k for k in extra if k not in gate.ENV_KEYS)
                argv[1]=argv[1].rstrip(',')
            recorded=[str(a) if len(str(a))<1024 else '<synthetic-text:'+str(len(str(a)))+':'+hashlib.sha256(str(a).encode()).hexdigest()+'>' for a in argv]
            commands.append({'argv':recorded,'env_keys':sorted(env),'test_env_overrides':extra})
            if mode!='concurrency':return original(argv,cwd,env,*args,**kwargs)
            # Three actual pinned SDK clients share ONE test gate/Lease. These
            # two extra CLIs are test-only parallel clients, not a claim that
            # one live WebFetch workflow has completed under network denial.
            with ThreadPoolExecutor(max_workers=3) as pool:
                helpers=[pool.submit(subprocess.run,argv,cwd=cwd,env=env,capture_output=True,text=True,timeout=40)
                         for _ in range(2)]
                main=pool.submit(original,argv,cwd,env,*args,**kwargs)
                try:
                    assert queued.wait(30),'no native request waited for active allowances'
                finally:release.set()
                result=main.result(timeout=40)
                helper_codes.extend(f.result(timeout=40).returncode for f in helpers)
                return result
        runtime=model_runtime.ModelRuntime(root,command,lambda *a:None,
            lambda path,**kw:shutil.rmtree(path),lambda user:Path('/home')/user)
        outcome='done'
        with patch.dict(os.environ,{'UNBUG_PROVIDER_WAIT':'1','FACTORY_CLAUDE_BIN':binary}), \
             patch.object(router,'_rpc',side_effect=rpc),patch.object(router,'SECRETS',ram), \
             patch.object(gate.http.client,'HTTPSConnection',side_effect=connect), \
             patch.object(gate.Allowance,'__init__',observed_init), \
             patch.object(model_runtime,'run_budgeted',side_effect=budgeted):
            text='Use only the synthetic local replies.' + (' offline'*10000 if mode=='compaction' else '')
            try:runtime.call(c,['claude/claude-opus-5-5'],text,case,'builder-1',user='pilot')
            except budget.BudgetError as error:outcome=str(error)
        receipts=[json.loads(p.read_text()) for p in (root/'usage-receipts').glob('*.json')]
        transcripts=[json.loads(line) for p in (root/'transcripts').glob('*') for line in p.read_text().splitlines() if line.startswith('{')]
        summary=next((e for e in reversed(transcripts) if e.get('type')=='result'),{})
        result={'scope':'SYNTHETIC native CLI + real wrapper/gate; Docker network none; no provider/model/case',
            'mode':mode,'platform':os.uname().machine,'version':version,'binary_sha256':hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
            'commands':commands,'outcome':outcome,'requests':seen,'controls':controls,
            'concurrency':{'queued':queued.is_set(),'extra_native_cli_returncodes':helper_codes},
            'rpc_counts':{op:rpc_ops.count(op) for op in set(rpc_ops)},'route_receipts':c.card.get('route_receipts'),
            'usage_receipts':receipts,'final':{k:summary.get(k) for k in ('is_error','num_turns','stop_reason','result')},
            'compact_boundaries':sum(e.get('subtype')=='compact_boundary' for e in transcripts)}
        assert len(receipts)==1 and len(c.card['route_receipts'])==1
        cap=receipts[0]['cap_used'];assert cap['closed'] and cap['in_flight_requests']==0
        print(json.dumps(result,sort_keys=True),flush=True)
        assert cap['forwarded_requests']==len(seen)
        if mode=='retry':
            assert outcome=='model_call_cap' and len(seen)==2 and cap['unknown_requests']==2 and cap['exhausted']
            assert rpc_ops.count('acquire')==1 and not receipts[0]['final_usage_known']
        else:
            assert outcome=='done'
            if mode!='compaction':assert receipts[0]['final_usage_known']
            if mode=='tools':assert cap['unsupported_requests']>=1 and summary.get('result')=='OK'
            if mode=='compaction':assert controls['compaction']>0 or result['compact_boundaries']>0
            if mode=='concurrency':
                assert queued.is_set() and helper_codes==[0,0] and len(seen)==3
                assert cap['validated_requests']==3 and cap['unknown_requests']==0 and not cap['exhausted']
                assert rpc_ops.count('acquire')==1
    upstream.shutdown();upstream.server_close()


if __name__=='__main__':main()
