"""Provider/VM edges for the real worker command; no runtime monkeypatches."""
import json
from pathlib import Path
import os
import sqlite3
import sys

EDGE = r'''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name; args=sys.argv[1:]
if name in ('npm','apt-get','curl'): raise SystemExit(97)
if name=='sudo': raise SystemExit(0 if args[:1]==['loginctl'] else 97)
if name=='node':
 if args==['--version']: print('v22.14.0')
 raise SystemExit(0)
if name=='harbor': print('harbor 0.24.0');raise SystemExit(0)
if name=='docker':
 home=pathlib.Path(os.environ['HOME']); ready=home/'bench-cleaned.json'
 if args[:3]==['rm','-f','unbug-bench-postgres-1']:
  assert args[2:]==['unbug-bench-'+n+'-1' for n in ('postgres','redis','medusa','medusa-b')]
  ready.write_text('{"fixed_names_removed":true}')
 elif args[:1]==['cp'] and args[-1].endswith('seed-ids.json'):
  pathlib.Path(args[-1]).write_text(json.dumps({**{k:'offline-'+k for k in ('inventory_x','product_x','variant_single','variant_pack')},'admin':{'email':'offline@example.invalid','password':'offline-public'}}))
 elif 'up' in args and 'postgres' in args and not ready.exists():
  print('Error response from daemon: Conflict. The container name "/unbug-bench-postgres-1" is already in use.',file=sys.stderr); raise SystemExit(1)
 elif 'psql' in args:
  import bench
  print(json.dumps(bench.EXPECTED_BASELINE))
 elif 'inspect' in args and '--format' in args: print('sha256:'+'a'*64)
 elif args[:2]==['compose','version']: print('2.35.1')
 elif args[:1]==['info']: print('28.0.0')
 raise SystemExit(0)
versions={'opencode':'1.19.0','codex':'codex-cli 0.162.1','claude':'2.1.299'}
if args==['--version']: print(versions[name]);raise SystemExit(0)
if '--help' in args: print('--auto --title --format --variant');raise SystemExit(0)
# Provider generation edge: refuse, without any request or real model.
assert not any(k.startswith('FACTORY_ROUTER_') for k in os.environ)
assert 'public-offline-router-sentinel' not in json.dumps(dict(os.environ))
audit=pathlib.Path(os.environ['HOME'])/'model-edge.json'
audit.write_text(json.dumps({'driver':name,'router_authority_absent':True}))
raise SystemExit(42)
'''


def install_edges(base):
    path=base/'edges';path.mkdir()
    for name in ('opencode','codex','claude','node','harbor','docker','npm','sudo','apt-get','curl'):
        p=path/name;p.write_text(EDGE.replace('#!/usr/bin/env python3','#!'+sys.executable));p.chmod(0o755)
    (path/'sitecustomize.py').write_text("""import os,sys,subprocess
from pathlib import Path
edges=Path(__file__).parent
_original=subprocess.Popen
class EdgeProcess(_original):
 def __init__(self,args,*a,**kw):
  if isinstance(args,(list,tuple)) and str(args[0]) in ('/usr/local/bin/opencode','/usr/local/bin/codex','/tmp/factory-claude-cli/bin/claude'):
   args=[str(edges/Path(args[0]).name),*args[1:]]
  super().__init__(args,*a,**kw)
subprocess.Popen=EdgeProcess
# Docker app health is an offline network edge; router TLS remains real.
import urllib.request,io
_urlopen=urllib.request.urlopen
def urlopen(url,*a,**kw):
 if isinstance(url,str) and url in ('http://127.0.0.1:9000/health','http://127.0.0.1:9001/health'):
  response=io.BytesIO(b'OK'); response.status=200; return response
 return _urlopen(url,*a,**kw)
urllib.request.urlopen=urlopen
def guard(event,args):
 if event in ('open','os.remove','os.mkdir','os.rmdir','os.listdir','os.scandir') and args and isinstance(args[0],(str,bytes)):
  value=os.fsdecode(args[0])
  if value.startswith('/dev/shm') or value.startswith('/tmp/factory'):
   raise RuntimeError('real worker RAM/shared temporary path accessed')
sys.addaudithook(guard)
if sys.argv[0].endswith('/runner_supervisor.py'):
 try:
  import json
  assert os.environ.get('FACTORY_ROUTER_TOKEN')=='public-offline-router-sentinel'
  assert os.environ['FACTORY_ROUTER_URL'].startswith('https://localhost:')
  assert Path(os.environ['FACTORY_ROUTER_CA_FILE']).is_file()
  ram=Path(os.environ['UNBUG_TEST_WORKER_SECRETS'])
  assert ram.is_relative_to(Path(os.environ['HOME']))
  assert not (ram/'r2-env').exists() and not (ram/'claude-token-2').exists()
  assert not (ram/'claude-token').exists()
  assert os.environ['CLAUDE_SECRET_NAME']=='claude-factory-token-2'
  assert os.environ['CLAUDE_CODE_OAUTH_TOKEN']==(ram/'claude-factory-token-2').read_text().strip()
  assert os.environ['OPENCODE_API_KEY']==(ram/'opencode-go-key').read_text().strip()
  assert os.environ['OPENROUTER_API_KEY']==(ram/'openrouter-key').read_text().strip()
  assert all((ram/name).is_file() for name in ('factory-job.json','codex-auth.json','statements-key'))
  Path(os.environ['HOME'],'worker-inputs.json').write_text(json.dumps({'router':True,'tls':True,'selected_secrets':True,'r2_excluded':True,'ram_isolated':True}))
 except Exception: os._exit(95)
""")



CLOUD = r'''
import datetime,json,os,pathlib,shlex,shutil,subprocess,sys
cloud=pathlib.Path(CLOUD_ROOT); base=cloud.parent; args=sys.argv[1:]
if args[:1]==['--stdin']:args.pop(0)
assert 'public-offline-router-sentinel' not in json.dumps(args)
with (cloud/'calls.jsonl').open('a') as f:f.write(json.dumps(args)+'\n')
cmd=args[0]
if cmd=='billing':print(json.dumps({'limits':{'creditBalanceSeconds':1000000}}))
elif cmd=='new':
 vm=cloud/'vm-1';vm.mkdir();(vm/'tmp').mkdir();(vm/'ram').mkdir();print(json.dumps({'event':'created','id':vm.name}))
elif cmd=='list':print(json.dumps({'sandboxes':[],'pageInfo':{'hasMore':False}}))
elif cmd=='info':print(json.dumps({'sandbox':dict(id=args[1],type='default',ttlSeconds=3600,archiveAfter=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)).isoformat(),holdsCreatorLogins=False,monitoring=False,snapshots=False,state='ready',health='ok',error=None,setupError=None,setupStatus=None,degradedSince=None,hydrated=True,hydration=None)}))
elif cmd in ('ssh','exec'):
 vm=cloud/args[1];command=args[-1]
 # Map entire namespace, including bare RAM directory, before shell execution.
 command=command.replace('/dev/shm',str(vm/'ram')).replace('/home/user',str(vm))
 for name in ('opencode','codex'):command=command.replace('/usr/local/bin/'+name,str(base/'edges'/name))
 env={**os.environ,'HOME':str(vm),'TMPDIR':str(vm/'tmp'),'PATH':str(base/'edges')+os.pathsep+os.environ['PATH'],
      'PYTHONPATH':str(base/'edges')+os.pathsep+str(vm/'factory')+os.pathsep+str(vm/'unbug-bench/bin'),
      'FACTORY_CLAUDE_BIN':str(base/'edges/claude'),'FACTORY_CODEX_BIN':str(base/'edges/codex'),
      'UNBUG_TEST_WORKER_SECRETS':str(vm/'ram/secrets'),'BENCH':str(vm/'unbug-bench')}
 assert '/dev/shm' not in command
 sys.exit(subprocess.run(['/bin/sh','-c',command],stdin=sys.stdin.buffer,env=env,cwd=vm).returncode)
elif cmd=='scp':
 if ':' in args[1]:
  worker,name=args[1].split(':',1);shutil.copyfile(cloud/worker/name.removeprefix('/home/user/'),args[2])
 else:
  worker,name=args[2].split(':',1);dest=cloud/worker/name.removeprefix('/home/user/');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(args[1],dest)
elif cmd=='delete':
 (cloud/args[1]/'deleted').touch();print(json.dumps({'operation':dict(id='op-'+args[1],targetId=args[1],kind='sandbox',status='pending')}))
elif cmd=='deletion':print(json.dumps({'operation':dict(id=args[2],targetId=args[2].removeprefix('op-'),kind='sandbox',status='completed',stage='completed',completedAt='2026-10-29T19:00:00Z')}))
else:raise AssertionError('unsupported provider edge')
'''


def verify_exam(test,base,root,cloud,config,store,digest,results,runtime):
    logs='\n'.join(p.read_text() for p in (runtime/'jobs').glob('*.log'))
    cards=list((root/'sealed').glob('case-public-a.scorecard.json'))
    test.assertTrue(cards,logs)
    card=json.loads(cards[0].read_text())
    if card.get('terminal_stop') != 'provider_preflight_failed':
        import io,tarfile,subprocess
        wrapped=next((root/'sealed').glob('*.casekey.age'))
        key=subprocess.check_output(['age','-d','-i',str(base/'throwaway-identity'),str(wrapped)])
        archive=next((root/'sealed').glob('*.checkpoint.tar.gz.age'))
        data=subprocess.check_output(['age','-d','-i','/dev/stdin',str(archive)],input=key)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            logs+='\n'+tar.extractfile(next(m for m in tar if m.name.endswith('/logs/runner.log'))).read().decode()
    test.assertEqual(card.get('terminal_stop'),'provider_preflight_failed',logs+'\n'+json.dumps(card))
    test.assertEqual(card['job_money']['batch'],'public')
    test.assertEqual(card['job_money']['job'],'a')
    test.assertEqual(card['batch_release_sha256'],digest)
    from contextlib import closing
    with closing(sqlite3.connect(store.path)) as db:
        requests=[json.loads(row[0]) for row in db.execute('SELECT payload FROM requests')]
        test.assertTrue(requests)
        test.assertTrue(all(r['deadline']==4070908800 for r in requests))
    vm=cloud/'vm-1'
    test.assertEqual(json.loads((vm/'bench-cleaned.json').read_text()), {'fixed_names_removed':True})
    test.assertTrue((vm/'deleted').exists())
    test.assertTrue(all(json.loads((vm/'worker-inputs.json').read_text()).values()))
    if sys.platform == 'linux': test.assertTrue(list(vm.rglob('model-edge.json')),logs)
    else: test.assertEqual(card['provider_preflight'][0]['reason'],'route_feature_unsupported')
    test.assertFalse((vm/'ram/secrets/r2-env').exists())
    test.assertFalse((vm/'ram/secrets/claude-token-2').exists())
    token='public-offline-router-sentinel'
    test.assertNotIn(token,logs)
    test.assertNotIn(token,(cloud/'calls.jsonl').read_text())
    for f in (root/'sealed').iterdir():
        if f.suffix in ('.json','.txt'): test.assertNotIn(token.encode(),f.read_bytes(),str(f))
    for f in (base/'control').rglob('*'):
        if f.is_file():test.assertNotIn(token.encode(),f.read_bytes(),str(f))
