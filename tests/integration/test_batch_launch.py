"""Real commit/source/launcher/archive/ledger paths, public practice only.

Cloud, model calls and holder socket I/O are offline doubles. No holder daemon,
provider, Docker workload, private archive or production identity is used.
Inputs are tracked public practice files and an independently saved public card.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CONSUMER_ROOT = Path(os.environ.get('UNBUG_TEST_D_CONSUMER_ROOT', str(ROOT / 'factory')))
if '--consumer-root' in sys.argv:
    index = sys.argv.index('--consumer-root'); CONSUMER_ROOT = Path(sys.argv[index + 1])
    del sys.argv[index:index + 2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import batch
import key_holder as holder
import restore_ledger
sys.path.insert(0,str(ROOT/'tests/factory'))
from router_delivery_support import router, TOKEN
from registry import Registry

RUNNER = r'''
import json, os, pathlib, shutil, sys
home = pathlib.Path(sys.argv[1]); sys.path[:0] = [str(home/'factory'), str(home/'unbug-bench/bin')]
import run, worker_release
run.HOME, run.BENCH, run.SEALED = home, home/'unbug-bench', home/'sealed'
(run.BENCH/'results').mkdir(exist_ok=True)
run.sh = lambda *a, **k: 0
run.bench_manifest = lambda: 'a'*64
run.pilot_homes = lambda: []
run.provider_preflight = lambda c: None
worker_release.verify_selected_drivers = lambda *a, **k: {'public_offline': True}
def build(c):
    if not c.args.resume:
        shutil.copytree(run.BENCH/'cases/medusa-oversell-v2', c.case, dirs_exist_ok=True)
run.build = build
def interrupt(c):
    saved = json.loads((run.BENCH/'tests/factory/fixtures/c7d405-confirm-timeout-card.json').read_text())['continuation_budget']
    if c.args.resume:
        ledger = json.loads(c.ledger.read_text())
        assert ledger['events'][:len(saved['events'])] == saved['events'], 'cumulative usage reset'
        assert ledger['calls'] >= saved['calls'] and ledger['cost'] >= saved['cost']
        recorded = json.loads((run.BENCH/'tests/factory/fixtures/e15450-collected-card.json').read_text())['continuation_budget']['events']
        ids = {e.get('id') for e in ledger['events']}
        event = next(e for e in recorded if e.get('id') not in ids and isinstance(e.get('cost'), (int, float)) and e['cost'] > 0)
        ledger['events'].append(event)
        ledger['calls'] += 1; ledger['cost'] += event['cost']
        ledger['list_cost_usd'] += event['cost']
        c.ledger.write_text(json.dumps(ledger))
    else:
        c.ledger.parent.mkdir(exist_ok=True)
        c.ledger.write_text(json.dumps(saved))
    assert (c.case/'promise.md').read_bytes() == (run.BENCH/'cases/medusa-oversell-v2/promise.md').read_bytes()
    raise run.BudgetError('timeout')
run.validate_and_repair = interrupt
sys.argv = ['run.py', *sys.argv[2:]]
run.main()
'''

CLOUD = r'''
import datetime, json, os, pathlib, shlex, shutil, subprocess, sys
cloud = pathlib.Path(CLOUD_ROOT)
args = sys.argv[1:]
if args[:1] == ['--stdin']: args.pop(0)
with (cloud/'calls.jsonl').open('a') as f: f.write(json.dumps(args)+'\n')
cmd = args[0]
if cmd == 'billing': print(json.dumps({'limits':{'creditBalanceSeconds':1000000}}))
elif cmd == 'new':
    vm = cloud/('vm-'+str(len(list(cloud.glob('vm-*')))+1)); vm.mkdir()
    print(json.dumps({'event':'created','id':vm.name}))
elif cmd == 'list': print(json.dumps({'sandboxes':[], 'pageInfo':{'hasMore':False}}))
elif cmd == 'info':
    print(json.dumps({'sandbox':dict(id=args[1],type='default',ttlSeconds=28800,
        archiveAfter=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=8)).isoformat(),
        holdsCreatorLogins=False,monitoring=False,snapshots=False,state='ready',health='ok',
        error=None,setupError=None,setupStatus=None,degradedSince=None,hydrated=True,hydration=None)}))
elif cmd == 'exec':
    vm = cloud/args[1]
    assert 'runner_supervisor.py -- python3 ~/factory/run.py' in args[-1]
    assert 'FACTORY_RUNNER_SECONDS=' in args[-1] and 'FACTORY_RUNNER_GRACE_SECONDS=' in args[-1]
    command = args[-1].split('python3 ~/factory/run.py ',1)[1].split('> ~/sealed/',1)[0]
    argv = shlex.split(command.split(' --bench-workers ',1)[0]) + ['--bench-workers','1']
    argv = [v.replace('/dev/shm/secrets/',str(vm/'shm-secrets')+'/') for v in argv]
    result = subprocess.run([sys.executable,RUNNER,str(vm),*argv], env={**os.environ,'HOME':str(vm)},
                            capture_output=True)
    if result.returncode: sys.stderr.buffer.write(result.stderr); sys.stderr.buffer.write(result.stdout)
    sys.exit(result.returncode)
elif cmd == 'ssh':
    vm = cloud/args[1]; command = args[2]
    if 'print(run.bench_manifest())' in command: print('a'*64); sys.exit()
    if 'opencode' in command and '--version' in command: sys.exit()  # offline driver boundary
    if 'docker image inspect unbug-bench-medusa:latest' in command: sys.exit()
    if 'factory/worker_release.py' in command: print('{"public_offline":true}'); sys.exit()
    if command.startswith('sudo loginctl '): sys.exit()  # worker-only administration
    if 'base64 -d | tar' in command: sys.stdin.buffer.read(); sys.exit()  # fake credentials
    if 'job_config.py deliver' in command:
        # Real atomic installer, with the offline cloud's private RAM directory.
        pin = shlex.split(command)[-1]
        code = ('import sys,pathlib; sys.path.insert(0,'+repr(str(vm/'factory'))+'); '
                'import job_config; job_config.deliver(sys.stdin.buffer.read(65537),'+repr(pin)+','+
                'pathlib.Path('+repr(str(vm/'shm-secrets/factory-job.json'))+'))')
        sys.exit(subprocess.run([sys.executable,'-B','-c',code],stdin=sys.stdin.buffer).returncode)
    if 'if [ ! -f ~/sealed/DONE ]' in command: sys.exit()
    if 'ls *.' in command:
        if not (vm/'sealed').is_dir(): sys.exit()
        print('\n'.join(p.name for p in (vm/'sealed').iterdir() if p.is_file() and
            p.name.endswith(('.age','.scorecard.json','.scorecard.txt','.progress.json')))); sys.exit()
    command = command.replace('/home/user',str(vm)).replace('/dev/shm/casekey',str(vm/'casekey'))
    command = command.replace('/dev/shm/secrets/',str(vm/'shm-secrets')+'/')
    if 'cat > '+str(vm/'casekey') in command:
        data = sys.stdin.buffer.read()
        assert data != pathlib.Path(IDENTITY).read_bytes(), 'founder identity sent to worker'
        result = subprocess.run(['/bin/sh','-c',command], input=data, env={**os.environ,'HOME':str(vm)})
    else:
        result = subprocess.run(['/bin/sh','-c',command], stdin=sys.stdin.buffer, env={**os.environ,'HOME':str(vm)})
    sys.exit(result.returncode)
elif cmd == 'scp':
    if ':' in args[1]:
        worker, name = args[1].split(':',1); shutil.copyfile(cloud/worker/name.removeprefix('/home/user/'),args[2])
    else:
        worker, name = args[2].split(':',1); target=cloud/worker/name.removeprefix('/home/user/')
        target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(args[1],target)
elif cmd == 'delete':
    (cloud/args[1]/'deleted').touch()
    print(json.dumps({'operation':dict(id='op-'+args[1],targetId=args[1],kind='sandbox',status='pending')}))
elif cmd == 'deletion':
    print(json.dumps({'operation':dict(id=args[2],targetId=args[2].removeprefix('op-'),kind='sandbox',
        status='completed',stage='completed',completedAt='2026-10-29T19:00:00Z')}))
else: raise AssertionError('unexpected offline cloud operation: '+cmd)
'''


class BatchLaunchTests(unittest.TestCase):
    def test_no_inventory_skips_suite_but_blocks_batch_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('factory/batch.py', 'factory/launch_manifest.py', 'factory/launch.sh',
                         'tests/factory/test_restore_inventory.py'):
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            # Source archives have no .git: ordinary qualification must still skip loudly.
            ordinary = subprocess.run([sys.executable, '-B', str(root / 'tests/factory/test_restore_inventory.py')],
                                      capture_output=True, text=True)
            self.assertEqual(ordinary.returncode, 0, ordinary.stderr)
            self.assertIn('SKIPPING: REAL RESTORE INVENTORY ABSENT', ordinary.stderr)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            subprocess.run(['git', '-c', 'user.name=Public test', '-c', 'user.email=public@example.invalid',
                            'commit', '-qm', 'Public source archive'], cwd=root, check=True)
            release = root / 'must-not-build'
            required = subprocess.run([sys.executable, '-B', str(root / 'factory/batch.py'), 'build',
                                       '--root', str(root), '--release', str(release)], capture_output=True, text=True)
            self.assertNotEqual(required.returncode, 0)
            self.assertIn('REQUIRED REAL RESTORE INVENTORY ABSENT', required.stderr)
            self.assertFalse(release.exists())

    def test_inventory_falls_back_to_real_local_store_on_git_errors(self):
        archives = batch.restore_inventory(ROOT)
        if not archives: self.skipTest('REAL RESTORE INVENTORY ABSENT')
        local_root = archives[0].parent.parent
        for error in (subprocess.CalledProcessError(128, ['git']), OSError('git unavailable')):
            with self.subTest(error=type(error).__name__), patch.object(batch.subprocess, 'check_output', side_effect=error):
                self.assertEqual(batch.restore_inventory(local_root), archives)

    def test_build_rejects_non_head_and_dirty_trees_before_qualification(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            public = root / 'CONTESTANT.md'; shutil.copy2(ROOT / 'CONTESTANT.md', public)
            subprocess.run(['git', 'add', '.'], cwd=root, check=True)
            commit = ['git', '-c', 'user.name=Public test', '-c', 'user.email=public@example.invalid', 'commit', '-qm']
            subprocess.run([*commit, 'Public source'], cwd=root, check=True)
            old = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
            subprocess.run([*commit, 'Advance HEAD', '--allow-empty'], cwd=root, check=True)
            release = root / 'must-not-build'
            with self.assertRaisesRegex(ValueError, 'commit must equal HEAD'):
                batch.build(root, old, release)
            public.write_bytes(public.read_bytes() + b'\nPublic dirty input\n')
            for staged in (False, True):
                if staged: subprocess.run(['git', 'add', '.'], cwd=root, check=True)
                with self.assertRaisesRegex(ValueError, 'clean working tree'):
                    batch.build(root, 'HEAD', release)
            subprocess.run(['git', 'restore', '--staged', '--worktree', '.'], cwd=root, check=True)
            (root / 'untracked-public-input').write_text('Untracked source\n')
            with self.assertRaisesRegex(ValueError, 'clean working tree'):
                batch.build(root, 'HEAD', release)
            self.assertFalse(release.exists())

    def test_call_caps_preserved_and_historical_money_caps_removed(self):
        for arguments, calls in ((['--max-total-calls', '750', '--max-cost=0.5'], 750),
                                        (['--max-total-calls=9000', '--max-cost', '10'], 5000),
                                        (['--max-total-calls=750', '--max-total-calls', '9000',
                                          '--max-cost', '.5', '--max-cost=10'], 750)):
            with self.subTest(arguments=arguments), patch('batch_money.manifest') as manifest:
                policy = {'batch': {'id': 'public', 'release': 'unused', 'sha256': 'a' * 64},
                          'jobs': {'a': {'mode': 'batch', 'case': 'case-public-a', 'max_calls': 5000,
                                         'requested_total_usd': '50.000000000', 'args': ['1', '--source', 'port', '--rotation-slot', '1',
                                                               *arguments]}}}
                manifest.return_value = dict(schema=1, id='public', jobs=policy['jobs'],
                    money_limit_usd='50.000000000', batch_deadline='2099-01-01T00:00:00Z',
                    max_concurrency=1, target_slots=1,
                    restore_recipient='age1' + 'a' * 58)
                job = batch.bind(policy, 'a', None, ROOT)
                self.assertEqual(job['max_calls'], 5000)  # Historical metadata only.
                self.assertNotIn('max_cost',job)
                self.assertFalse(any(a.startswith('--max-cost') for a in job['args']))
                self.assertFalse(any(a == '--max-total-calls' or a.startswith('--max-total-calls=') for a in job['args']))

    def test_capacity_counts_durable_unknown_outcomes_without_in_memory_jobs(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(holder,'CONTROL_HOME',Path(temp)):
            policy={'batch':{'id':'public','sha256':'a'*64}}
            row={'batch_id':'public','batch_release_sha256':'a'*64,'launch_id':'1'*32,'completed_ok':False}
            self.assertEqual(holder.batch_live_reservations(policy,[row]),1)
            self.assertEqual(holder.batch_live_reservations(policy,[{**row,'exit':1}]),1)
            self.assertEqual(holder.batch_live_reservations(policy,[{**row,'launch_id':None}]),1)
            complete=Path(temp)/'launches'/row['launch_id']/'complete'
            complete.parent.mkdir(parents=True); complete.touch()
            self.assertTrue(holder.reconcile_batch_receipts(policy,[row]))
            self.assertTrue(row['completed_ok'])
            self.assertEqual(holder.batch_live_reservations(policy,[row]),0)
            self.assertNotIn('exit',row)  # Lifecycle completion does not invent a process exit code.
            self.assertEqual(row['launch_id'],'1'*32)  # Reservation/replay history survives.
            self.assertFalse(holder.reconcile_batch_receipts(policy,[row]))

    def test_public_fresh_interruption_and_liability_refuses_successors_on_one_unlock(self):
        self.run_public_launch()

    def test_complete_worker_command_router_delivery(self):
        if not shutil.which('age'): self.skipTest('real age required for offline worker exam')
        if any(Path('/home',n).exists() for n in ('pilot','pilot-strong','pilot-easy')):
            self.skipTest('offline exam requires no real pilot homes on host')
        self.run_public_launch(full_worker=True)

    def run_public_launch(self, full_worker=False):
        if not (CONSUMER_ROOT/'job_authority.py').is_file():
            self.skipTest('D consumer not merged; explicit --consumer-root integration run required; no enablement')
        if not batch.restore_inventory(ROOT):
            self.skipTest('REAL RESTORE INVENTORY ABSENT: public release build qualification is unavailable; builds stay blocked')
        with tempfile.TemporaryDirectory() as temp, router(Path(temp)/'tls') as (router_config, router_store, router_server):
            base = Path(temp).resolve(); root = base/'source'; root.mkdir()
            cloud = base/'cloud'; cloud.mkdir()
            runner = base/'public-runner.py'; runner.write_text(RUNNER)
            if full_worker:
                from worker_delivery_edge import CLOUD as full_cloud, install_edges
                install_edges(base)
            identity = base/'throwaway-identity'
            subprocess.run(['age-keygen','-o',str(identity)], check=True, capture_output=True)
            recipient = subprocess.check_output(['age-keygen','-y',str(identity)], text=True).strip()
            fake = base/'offline-cloud.py'
            fake.write_text('CLOUD_ROOT='+repr(str(cloud))+'\nRUNNER='+repr(str(runner))+
                            '\nIDENTITY='+repr(str(identity))+'\n'+(full_cloud if full_worker else CLOUD))
            # Snapshot real maintained public sources independently of the release builder.
            names = subprocess.check_output(['git','ls-files','-z','--',*batch.BATCH_SOURCE,
                                             *batch.HOST_FILES,'tools/install_source.py'],cwd=ROOT).decode().split('\0')
            for name in {*filter(None,names),*batch.HOST_FILES}:
                target=root/name; target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT/name,target)
            if CONSUMER_ROOT != ROOT/'factory':
                # Actual reviewed D accounting code, not a stub. Only this explicit
                # cross-branch qualification uses it before the parent merges D.
                for name in ('job_authority.py','budget.py'):
                    shutil.copy2(CONSUMER_ROOT/name,root/'factory'/name)
            source = root/'factory/run.py'
            source.write_text(re.sub(r'^FOUNDER_RECIPIENT = "age1[a-z0-9]+"',
                'FOUNDER_RECIPIENT = "'+recipient+'"',source.read_text(),flags=re.M))
            # Only the external cloud boundary is replaced, before committing the source.
            (root/'bin/boat-call').write_text('#!/bin/sh\nexec '+shutil.which('python3')+' '+str(fake)+' "$@"\n')
            (root/'bin/boat-call').chmod(0o755)
            (root/'bin/boat-name').write_text('#!/bin/sh\nexit 0\n')
            rotation=json.loads((ROOT/'factory/rotation-3writers.json').read_text())
            roles={r:{**rotation['families'][f],'family':f} for r,f in rotation['slots'][0].items()}
            roles['easy_calibrator']={'model':'opencode/glm-5.3-flash-free','effort':'default','family':'z-ai'}
            jobs={n:dict(mode='batch',case='case-public-'+n,roles=roles,max_calls=5000,
                         requested_total_usd='100.000000000',
                         args=['1','--source','port','--rotation-slot','1', '--bench-workers','1']) for n in ('a','b')}
            if full_worker:
                import practice
                for job in jobs.values():
                    job['args']=practice.EXPECTED['jobs']['practice']['args']+['--bench-workers','1']
                    job.update(claude_accounts=[2,1],initial_accounts={'claude':2})
            batch_manifest=dict(schema=1,id='public',jobs=jobs,max_concurrency=2,target_slots=2,
                                money_limit_usd='400.000000000',batch_deadline='2099-01-01T00:00:00Z',
                                restore_recipient=(root/'factory/control-recipient.txt').read_text().strip())
            manifest_path=root/'factory/batches/public.json'; manifest_path.parent.mkdir(exist_ok=True)
            manifest_path.write_text(json.dumps(batch_manifest))
            manifest_sha=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','add','.'],cwd=root,check=True)
            subprocess.run(['git','-c','user.name=Public test','-c','user.email=public@example.invalid',
                            'commit','-qm','Public source test snapshot'],cwd=root,check=True)
            commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
            release=base/'release'; digest=batch.build(root,commit,release)
            record=batch.verify(release,digest,root)
            self.assertEqual(record['commit'],commit)
            manifest=json.loads((release/'source-manifest.json').read_text())['files']
            self.assertEqual(manifest['cases/medusa-oversell-v2/promise.md'],hashlib.sha256(
                (ROOT/'cases/medusa-oversell-v2/promise.md').read_bytes()).hexdigest())
            self.assertFalse(any(n.startswith(('sealed/','results/')) for n in manifest))
            # Qualification and the release must use exactly the clean HEAD source.
            source.write_text(source.read_text()+'\n# dirty host\n')
            with self.assertRaisesRegex(ValueError, 'clean working tree'):
                batch.build(root,commit,base/'second-release')
            self.assertFalse((base/'second-release').exists())
            with self.assertRaisesRegex(ValueError,'host differs'): batch.verify(release,digest,root)
            subprocess.run(['git','restore','factory/run.py'],cwd=root,check=True)
            self.assertEqual(batch.build(root,commit,base/'second-release'),digest)
            (root/'sealed').mkdir()
            statement=root/'sealed/case-old.statement.age'
            subprocess.run(['age','-r',recipient,'-o',str(statement)],
                           input=b'public historical practice statement',check=True)
            Registry(root/'sealed/statement-registry').import_historical('case-old',statement)
            plain=base/'credentials'; plain.mkdir()
            for name in ('claude-token','claude-factory-token-2','claude-token-2','opencode-go-key','openrouter-key','statements-key'):
                (plain/name).write_text('offline-public-placeholder\n')
            if full_worker:
                (plain/'r2-env').write_text('R2_ACCOUNT_ID=public\nR2_ACCESS_KEY_ID=public\nR2_SECRET_ACCESS_KEY=public\nR2_BUCKET=public\n')
            (plain/'codex-auth.json').write_text(json.dumps({'tokens':{'access_token':
                'e30.eyJleHAiOjQxMDI0NDQ4MDB9.synthetic'},'last_refresh':'2026-10-28T00:00:00Z'}))
            data=subprocess.check_output(['tar','-C',str(plain),'-cf','-',*sorted(p.name for p in plain.iterdir())])
            credentials=base/'credentials.age'
            subprocess.run(['age','-r',recipient,'-o',str(credentials)],input=data,check=True)
            if full_worker:
                import batch_holder
                r2=batch_holder._r2_env(identity.read_bytes(),credentials)
                self.assertEqual(set(r2),{'R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET'})
            policy=dict(root=str(root),code_sha256=holder.fingerprint(root),recipient=recipient,
                        path=os.environ['PATH'],batch=dict(id='public',release=str(release),sha256=digest,
                        max_concurrency=2,manifest_path='factory/batches/public.json',
                        manifest_sha256=manifest_sha),jobs=jobs)
            policy_path=base/'policy.json'; batch.save(policy_path,policy)
            results=[]; processes=[]; verifications=[]
            popen=subprocess.Popen
            def spawn(argv,*args,**kwargs):
                if argv[0]=='/usr/bin/caffeinate': return SimpleNamespace(terminate=lambda:None)
                p=popen(argv,*args,**kwargs)
                if argv[:2]==['age-keygen','-y']: verifications.append(p)
                elif argv[:2]==['/bin/sh',str(root/'factory/launch.sh')]: processes.append(p)
                return p
            def payload(name,checkpoint=None):
                with patch.object(holder,'request',side_effect=lambda value:value):
                    return batch.launch('public',name,checkpoint)
            generations=[]
            def issue_collected_fixture(generation):
                # Authored authority input from the reviewed contract; 2b will
                # produce this only after verified collection/retirement.
                money_path=base/'control/batches/public/money.json'
                state=json.loads(money_path.read_text())
                authority=state['jobs']['a']['authority']
                authority.update(source_generation=generation,revision=authority['revision']+1)
                money_path.write_text(json.dumps(state))
            def checkpoint():
                if not generations:
                    generations.append(json.loads((root/'sealed/case-public-a.scorecard.json').read_text())['sha256'])
                    with patch.object(holder,'ROOT',root):
                        self.assertEqual(holder.current_generation(batch.bind(policy,'a',generations[0],root)),generations[0])
                    # Authored current authority input, standing in for the future
                    # 2b collection verifier. authorize itself cannot advance it.
                    issue_collected_fixture(generations[0])
                return generations[0]
            requests=iter([lambda:payload('a'),lambda:payload('b'),lambda:payload('a'),
                           lambda:payload('a',checkpoint()),lambda:payload('a',checkpoint()),lambda:{'op':'stop'}])
            if full_worker: requests=iter([lambda:payload('a'),lambda:{'op':'stop'}])
            class Connection:
                def __init__(self,value): self.value=json.dumps(value).encode()+b'\n'
                def __enter__(self): return self
                def __exit__(self,*a): pass
                def settimeout(self,*a): pass
                def recv(self,*a): value,self.value=self.value,b''; return value
                def sendall(self,value): results.append(json.loads(value))
            class Server:
                def __enter__(self): return self
                def __exit__(self,*a): pass
                def bind(self,*a): pass
                def listen(self,*a): pass
                def settimeout(self,*a): pass
                def accept(self):
                    for p in processes:
                        try: p.wait(timeout=90)
                        except subprocess.TimeoutExpired:
                            os.killpg(p.pid,signal.SIGKILL); p.wait()
                            calls=(cloud/'calls.jsonl').read_text().splitlines()[-4:]
                            raise AssertionError('\n'.join(f.read_text() for f in (runtime/'jobs').glob('*.log'))+
                                                 '\nLast offline operations: '+'\n'.join(calls)) from None
                        if p.returncode:
                            logs='\n'.join(f.read_text() for f in (runtime/'jobs').glob('*.log'))
                            if not full_worker and 'infrastructure liability unsettled' not in logs:
                                raise AssertionError(logs)
                    return Connection(next(requests)()),None
            runtime=base/'runtime'; runtime.mkdir(mode=0o700)
            # Exercise the real serialized holder loop without a socket or holder process.
            key=next(v for v in identity.read_bytes().splitlines() if v.startswith(b'AGE-SECRET-KEY-'))+b'\n'
            with patch.multiple(holder,ROOT=root,RUNTIME=runtime,SOCKET=runtime/'control.sock',CONTROL_HOME=base/'control'), \
                 patch.object(holder,'socket',SimpleNamespace(**{**vars(holder.socket),'socket':lambda *a,**k:Server()})), \
                 patch.object(holder.os,'chmod',side_effect=lambda *a:None), \
                 patch.object(holder,'peer_is_owner',return_value=True), \
                 patch.object(holder.resource,'setrlimit'), patch.object(holder.signal,'signal'), \
                 patch.object(holder.subprocess,'Popen',side_effect=spawn), \
                 patch.object(holder.sys,'stdin',SimpleNamespace(buffer=io.BytesIO(key))), \
                 patch.dict(os.environ,{'UNBUG_SECRETS_FILE':str(credentials), 'UNBUG_ROUTER_CLIENT_FILE':str(router_config)}):
                holder.serve(policy_path,.1)
                self.assertEqual(len(verifications),1,'all requests must share one identity verification')
                if full_worker:
                    from worker_delivery_edge import verify_exam
                    verify_exam(self,base,root,cloud,router_config,router_store,digest,results,runtime)
                    return
                # Recreate the lost-reap window from durable, actually completed
                # public launches. The second service has no old child handles.
                rows=json.loads((runtime/'reservations.json').read_text())
                rows[0]['completed_ok']=False
                prior_generation=rows[0]['generation']
                batch.save(runtime/'reservations.json',rows)
                latest=json.loads((root/'sealed/case-public-a.scorecard.json').read_text())['sha256']
                issue_collected_fixture(latest)
                requests=iter([lambda:payload('a',latest),lambda:{'op':'stop'}])
                holder.sys.stdin.buffer=io.BytesIO(key)
                holder.serve(policy_path,.1)
            errors=[(i,r) for i,r in enumerate(results) if 'error' in r]
            if errors != [(2,results[2]),(4,results[4]),(6,results[6])]:
                logs='\n'.join(p.read_text() for p in (runtime/'jobs').glob('*.log'))
                self.fail('unexpected offline results: '+repr(results)+'\n'+logs)
            for index in (2,4,6):
                self.assertIn('checkpoint already used',results[index]['error'])
            self.assertTrue(all(results[i].get('started') for i in (0,1,3)))
            self.assertEqual(len(processes),3)
            self.assertEqual(processes[0].returncode,0)
            self.assertTrue(all(p.returncode!=0 for p in processes[1:]))
            receipts=json.loads((runtime/'reservations.json').read_text())
            self.assertEqual(len(receipts),3)
            self.assertTrue(receipts[0]['completed_ok'])
            self.assertEqual(receipts[0]['generation'],prior_generation)
            self.assertEqual({r['case'] for r in receipts},{'case-public-a','case-public-b'})
            self.assertTrue(all('--batch-release' in r['launch']['argv'] for r in receipts))
            self.assertEqual({r['launch']['argv'][r['launch']['argv'].index('--batch-sha256')+1]
                              for r in receipts},{digest})
            saved=json.loads((ROOT/'tests/factory/fixtures/c7d405-confirm-timeout-card.json').read_text())['continuation_budget']
            # The first public worker still exercises the real release/collection
            # lifecycle. No second worker can exist until attributed settlement.
            self.assertEqual([p.name for p in cloud.glob('vm-*')], ['vm-1'])
            calls=[json.loads(line) for line in (cloud/'calls.jsonl').read_text().splitlines()]
            self.assertEqual(sum(c[0]=='new' for c in calls),1)
            public=json.loads(next((cloud/'vm-1/sealed').glob('*.scorecard.json')).read_text())
            self.assertEqual(public['batch_release_sha256'],digest)
            ledger=public['continuation_budget']
            self.assertEqual(ledger['calls'],saved['calls'])
            self.assertEqual(ledger['cost'],saved['cost'])
            self.assertEqual(ledger['events'],saved['events'])
            self.assertEqual(ledger['infrastructure_waste'],saved['infrastructure_waste'])
            self.assertTrue((cloud/'vm-1/deleted').exists())
            self.assertEqual(receipts[2]['budget_calls'],saved['calls'])
            self.assertEqual(receipts[2]['budget_cost'],saved['cost'])
            infra=json.loads((base/'control/boat-reservations.json').read_text())
            self.assertEqual(len(infra['reservations']),1)
            held=next(iter(infra['reservations'].values()))
            self.assertEqual(held['status'],'finished')
            self.assertIsNone(held['actual_spend_usd'])
            # Public-card edits cannot assign batch provenance to an old embedded checkpoint.
            work=cloud/'vm-1/work/case-public-a'
            public=json.loads((root/'sealed/case-public-a.scorecard.json').read_text())
            archived=json.loads((work/'scorecard.json').read_text()); archived.pop('batch_release_sha256')
            batch.save(work/'scorecard.json',archived)
            with self.assertRaisesRegex(restore_ledger.Refused,'explicit migration'):
                restore_ledger.install(work,base/'rejected-import','case-public-a',public['sha256'],public,
                                       release_sha256=digest)


if __name__=='__main__': unittest.main()
