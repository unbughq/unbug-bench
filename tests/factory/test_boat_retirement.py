"""Saved public Boat DTOs; AUTHORED transport, policy, clocks and lifecycle layout.
Real wrapper/process locks exercised locally; Linux WRITE-FD positive skips on Mac.
No provider/network/worker credentials, no historical ledger edits or row closure.
"""
from copy import deepcopy
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'factory'), str(ROOT/'bin')]
import boat_lifecycle as life
import batch
import batch_holder as holder
import batch_money as money
import key_holder
import launch_manifest
import practice
from registry import atomic_json

CONTRACT = json.loads((ROOT/'docs/reports/boat-stopped-contract-20261104.json').read_text())
WORKER = CONTRACT['worker_never_mutated']


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve(); self.root = self.base/'source'; self.root.mkdir()
        # Public source only. This is an AUTHORED local release, not a saved production pin.
        paths = set(launch_manifest.HOST_FILES)
        paths.update(str(p.relative_to(ROOT)) for pattern in ('factory/*.py', 'bin/*.py') for p in ROOT.glob(pattern))
        for name in paths:
            target = self.root/name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/name, target)
        self.home = self.base/'control'; self.home.mkdir()
        self.state = self.home/'launches'/('a'*32); self.state.mkdir(parents=True)
        self.spend = self.root/'results/spend/authored.json'; self.spend.parent.mkdir(parents=True)
        self.record = deepcopy(practice.EXPECTED)
        self.policy = dict(root=str(self.root), code_sha256=key_holder.fingerprint(self.root),
            jobs=self.record['jobs'], batch=dict(id=practice.BATCH, release=str(self.base/'release'),
                max_concurrency=1, manifest_path='factory/batches/'+practice.BATCH+'.json'))
        recipient = self.root/'factory/control-recipient.txt'; recipient.write_text(self.record['restore_recipient']+'\n')
        manifest = self.root/self.policy['batch']['manifest_path']; manifest.parent.mkdir(exist_ok=True)
        atomic_json(manifest,self.record)
        release = self.base/'release'; release.mkdir()
        for name in (*batch.INPUTS,'deploy.py'): (release/name).write_text('{}')
        self.policy['batch']['manifest_sha256'] = life.sha256(manifest) if hasattr(life,'sha256') else hashlib.sha256(manifest.read_bytes()).hexdigest()
        atomic_json(release/'source-manifest.json', dict(files={self.policy['batch']['manifest_path']:self.policy['batch']['manifest_sha256']}))
        atomic_json(release/'batch-release.json', dict(schema=1, files={n:hashlib.sha256((release/n).read_bytes()).hexdigest() for n in (*batch.INPUTS,'deploy.py')},
            host_files={n:hashlib.sha256((self.root/n).read_bytes()).hexdigest() for n in launch_manifest.HOST_FILES}))
        self.policy['batch']['sha256'] = hashlib.sha256((release/'batch-release.json').read_bytes()).hexdigest()
        self.env = {**os.environ, 'UNBUG_CONTROL_HOME':str(self.home), 'UNBUG_LAUNCH_STATE':str(self.state),
                    'UNBUG_PRACTICE_BATCH':practice.BATCH, 'UNBUG_CLOUD':'boat', 'BOAT_COMMAND_TIMEOUT_SECONDS':'2'}
        with patch.dict(os.environ,self.env):
            op = holder.reserve(self.policy,self.root,self.home,'smoke',None)
        # Use the existing API/journal; bind a saved public worker identity to this authored launch.
        directory = self.home/'batches'/practice.BATCH
        with money.locked(self.home,practice.BATCH):
            ops = holder._operations(directory,self.record,self.policy)
            self.state.rmdir(); self.state = self.home/'launches'/op['launch_id']
            self.state.mkdir(); self.env['UNBUG_LAUNCH_STATE']=str(self.state)
            config = holder._config(self.policy,self.home,op)
            launch = dict(argv=['1','--factory-job-config',str(config),'--factory-job-config-sha256',op['config_sha256']],
                environment={'UNBUG_BATCH_OPERATION':op['operation_id'],'UNBUG_PRACTICE_BATCH':practice.BATCH})
            ops[op['operation_id']].update(dispatch_started=True,launch=launch)
            holder._save(directory,self.record,self.policy,ops)
        atomic_json(self.state/'launch.json',launch)
        (self.state/'ids').write_text(WORKER+'\n')
        # Real saved identity, AUTHORED creation transport response for this layout.
        atomic_json(self.state/'new.1',dict(event='created',id=WORKER))
        self.started = int(time.time())-2701
        (self.state/(WORKER+'.started')).write_text(str(self.started))
        self.row = dict(status='finished', usd='0.036', expires_at=time.time()+3600,
            state_path=str(self.state),vms=1,ttl_seconds=3600,max_spend_usd='5')
        atomic_json(self.spend,dict(provider='boat',allowed=True,vms=1,ttl_seconds=3600,max_spend_usd=5))
        atomic_json(self.home/'boat-reservations.json',dict(version=1,reservations={str(self.spend):self.row}))
        atomic_json(self.home/'policy.json',self.policy)
        self.edge = self.base/'boat'  # Exact pinned-version check is exercised.
        self.edge.write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys
base=pathlib.Path(os.environ['RETIREMENT_EDGE']); args=sys.argv[1:]
if args==['--version']: print('boat 1.0.85'); sys.exit(0)
with (base/'calls').open('a') as out: out.write(json.dumps(args)+'\\n')
if args[0]=='delete': print(json.dumps({'operation':{'id':'authored-delete','targetId':args[1],'kind':'sandbox','status':'pending','stage':'pending','completedAt':None}}))
else: sys.exit(99)
'''); self.edge.chmod(0o755)
        self.env.update(BOAT_CMD=str(self.edge), RETIREMENT_EDGE=str(self.base))

    def wrapper(self,args,**kwargs):
        return subprocess.run([str(self.root/'bin/boat-call'),*args],env=self.env,capture_output=True,timeout=8,**kwargs)

    def calls(self):
        path=self.base/'calls'
        return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []

    def fence(self):
        with patch.dict(os.environ,self.env), patch.object(key_holder,'ROOT',self.root):
            return life.retirement_marker(self.root,self.spend,WORKER,self.state,self.started+2700)

    def test_real_wrapper_busy_ex_deadline_unique_provider_call_and_no_id_replay(self):
        self.fence()
        with (self.state/(WORKER+'.deletion.lock')).open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            start=time.monotonic()
            children=[subprocess.Popen([str(self.root/'bin/boat-call'),'delete',WORKER,'--yes','--json'],
                env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(2)]
            for child in children: child.communicate(timeout=8)
            self.assertEqual(sorted(c.returncode for c in children),[0,1])
            self.assertLess(time.monotonic()-start,6)
        self.assertEqual(self.calls(),[['delete',WORKER,'--yes','--json']])
        self.assertTrue((self.state/(WORKER+'.deletion-attempted')).is_file())
        self.assertTrue((self.state/(WORKER+'.metering-bypassed')).is_file())
        self.assertNotEqual(self.wrapper(['delete',WORKER,'--yes','--json']).returncode,0)
        self.assertEqual(len(self.calls()),1)

    def test_deadline_wrapper_negative_authority_and_mutation_controls(self):
        self.fence()
        for args in (['delete',WORKER,'--yes','--json','--force'],['delete','foreign','--yes','--json'],
                     ['resume',WORKER],['ssh',WORKER,'true'],['scp','file',WORKER+':/tmp/file']):
            self.assertNotEqual(self.wrapper(args).returncode,0,args)
        self.assertEqual(self.calls(),[])
        row=deepcopy(self.row); row['ttl_seconds']=7200
        atomic_json(self.home/'boat-reservations.json',dict(version=1,reservations={str(self.spend):row}))
        self.assertNotEqual(self.wrapper(['delete',WORKER,'--yes','--json']).returncode,0)
        self.assertEqual(self.calls(),[])

    def test_real_public_stop_and_meter_contract_negative_controls(self):
        info=CONTRACT['info_projection']; status=CONTRACT['stop_status_response']
        usage=life.loads(CONTRACT['usage_raw_public_json'])
        stop=life.stopped(info,status,WORKER)
        self.assertEqual(stop['id'],'stop_cf0b665fb2ed2957')
        self.assertEqual(life.stopped_usage(usage,WORKER,stop['endedAt']),Decimal('0.00672'))
        for change in ('failing','superseded'):
            bad=deepcopy(status); bad['stop']['status']=change
            with self.assertRaises(ValueError): life.stopped(info,bad,WORKER)
        forced=deepcopy(status); forced['stop']['forced']=True
        self.assertTrue(life.stopped(info,forced,WORKER)['forced'])
        for key,value in [('sandboxId','wrong'),('running',True),('seconds',True),('dollars',Decimal('NaN')),('until','2026-10-13T00:00:00Z')]:
            bad=deepcopy(usage); bad[key]=value
            with self.assertRaises(ValueError): life.stopped_usage(bad,WORKER,stop['endedAt'])

    def test_future_deadline_bad_fd_wrong_creation_and_version_do_not_claim(self):
        self.started=int(time.time())-100
        (self.state/(WORKER+'.started')).write_text(str(self.started))
        self.fence()
        self.env['UNBUG_BOAT_RETIREMENT_FD']='999999'
        self.assertNotEqual(self.wrapper(['delete',WORKER,'--yes','--json']).returncode,0)
        self.assertEqual(self.calls(),[])
        self.assertFalse((self.state/(WORKER+'.deletion-attempted')).exists())
        self.assertNotEqual(self.wrapper(['exec',WORKER,'true']).returncode,0)
        self.assertEqual(self.calls(),[])

    def test_shared_mutation_holds_fence_then_new_mutation_refuses(self):
        self.env['BOAT_COMMAND_TIMEOUT_SECONDS']='10'
        self.edge.write_text(self.edge.read_text().replace("else: sys.exit(99)",
            "elif args[0]=='exec':\n (base/'entered').touch(); import time;\n while not (base/'allow-exit').exists(): time.sleep(.01)\nelse: sys.exit(99)"))
        child=subprocess.Popen([str(self.root/'bin/boat-call'),'exec',WORKER,'true'],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        end=time.monotonic()+5
        while not (self.base/'entered').exists() and time.monotonic()<end: time.sleep(.01)
        self.assertTrue((self.base/'entered').exists())
        self.fence()
        with (self.state/(WORKER+'.deletion.lock')).open('a+') as lock:
            with self.assertRaises(BlockingIOError): fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.assertNotEqual(self.wrapper(['exec',WORKER,'new']).returncode,0)
        (self.base/'allow-exit').touch(); child.communicate(timeout=8)
        self.assertEqual(self.calls(),[['exec',WORKER,'true']])

    def test_version_failure_does_not_consume_intent_and_deadline_loser_does_not_bypass(self):
        self.fence()
        original=self.edge.read_text(); self.edge.write_text(original.replace('boat 1.0.85','boat wrong'))
        self.assertNotEqual(self.wrapper(['delete',WORKER,'--yes','--json']).returncode,0)
        self.assertFalse((self.state/(WORKER+'.deletion-attempted')).exists())
        self.assertEqual(self.calls(),[])
        self.edge.write_text(original)
        # An already claimed ordinary attempt is not invalidated by an emergency loser.
        (self.state/(WORKER+'.deletion-attempted')).touch()
        self.assertNotEqual(self.wrapper(['delete',WORKER,'--yes','--json']).returncode,0)
        self.assertFalse((self.state/(WORKER+'.metering-bypassed')).exists())
        self.assertEqual(self.calls(),[])

    def test_lifecycle_does_not_preclaim_fenced_delete_and_uses_due_even_without_ex(self):
        self.fence()
        def response(argv,**kwargs):
            self.assertFalse((self.state/(WORKER+'.deletion-attempted')).exists())
            self.assertLessEqual(float(kwargs['env']['BOAT_COMMAND_TIMEOUT_SECONDS']),5)
            self.assertEqual(argv[-4:],['delete',WORKER,'--yes','--json'])
            raise OSError('AUTHORED wrapper acceptance interruption')
        with (self.state/(WORKER+'.deletion.lock')).open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            with patch.dict(os.environ,self.env), patch.object(key_holder,'ROOT',self.root), patch.object(life.subprocess,'run',side_effect=response):
                with self.assertRaises(OSError): life.delete_receipt(self.root,self.spend,WORKER,self.state/'ids')
        self.assertFalse((self.state/(WORKER+'.deletion-attempted')).exists())

    def test_uncollected_worker_is_not_stopped_before_due(self):
        self.started=int(time.time())-100
        (self.state/(WORKER+'.started')).write_text(str(self.started))
        with patch.dict(os.environ,self.env), patch.object(key_holder,'ROOT',self.root):
            with self.assertRaises(FileNotFoundError): life.delete_receipt(self.root,self.spend,WORKER,self.state/'ids')
        self.assertFalse((self.state/(WORKER+'.retiring.json')).exists())
        self.assertEqual(self.calls(),[])

    def test_guard_reports_uncollected_deadline_retirement_failure_on_replay(self):
        (self.state/(WORKER+'.retiring.json')).write_text('{}')  # AUTHORED fence transport.
        script='''root=$1; state=$2; label=factory
. "$root/bin/boat-launch-guards.sh"
guard_delete_receipt() { touch "$state/delete-checked"; }
collect_vm() { touch "$state/forbidden-collection"; }
guard_retire "$3"
first=$?
guard_retire "$3"
second=$?
[ "$first" -ne 0 ] && [ "$second" -ne 0 ]
'''
        result=subprocess.run(['sh','-c',script,'sh',str(self.root),str(self.state),WORKER],
            env=self.env,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((self.state/'delete-checked').exists())
        self.assertFalse((self.state/'forbidden-collection').exists())
        self.assertFalse((self.state/(WORKER+'.collected')).exists())

    def test_saved_proof_recheck_failure_never_reaches_ordinary_delete(self):
        self.started=int(time.time())-100
        (self.state/(WORKER+'.started')).write_text(str(self.started))
        (self.state/(WORKER+'.collected')).touch()
        evidence=self.spend.with_suffix('.deletions')/WORKER; evidence.mkdir(parents=True)
        (evidence/'retirement-proof.json').write_text('{}')  # AUTHORED retained/corrupt proof seam.
        with patch.dict(os.environ,self.env), patch.object(key_holder,'ROOT',self.root), patch.object(life,'capture_meter',side_effect=ValueError('AUTHORED failed fresh stop recheck')), patch.object(life,'_delete') as delete:
            with self.assertRaises(ValueError): life.delete_receipt(self.root,self.spend,WORKER,self.state/'ids')
            delete.assert_not_called()
        self.assertEqual((evidence/'retirement-proof.json').read_text(),'{}')
        self.assertFalse((self.state/(WORKER+'.metering-bypassed')).exists())

    def test_public_capture_failure_receipt_is_fixed_and_preserved(self):
        self.started=int(time.time())-100
        (self.state/(WORKER+'.started')).write_text(str(self.started))
        import subprocess
        errors=[(TimeoutError('PRIVATE_SENTINEL'),'timeout'),
                (subprocess.CalledProcessError(1,['PRIVATE_SENTINEL']),'rpc'),
                (OSError('PRIVATE_SENTINEL'),'io'),(TypeError('PRIVATE_SENTINEL'),'invalid_response')]
        with patch.dict(os.environ,self.env),patch.object(key_holder,'ROOT',self.root):
            marker=life.retirement_marker(self.root,self.spend,WORKER,self.state,self.started+2700)
        target=self.spend.with_suffix('.deletions')/WORKER/'capture-stage.json'
        for error,kind in errors:
            target.unlink(missing_ok=True)
            with patch.object(life,'_capture_meter',side_effect=error):
                with self.assertRaises(type(error)): life.capture_meter(self.root,self.spend,WORKER,self.state,marker,0)
                raw=target.read_bytes(); receipt=json.loads(raw)
                self.assertEqual(set(receipt),{'schema','retirement_id','worker_id','stage','outcome','error_class','observed_at'})
                self.assertEqual(receipt['error_class'],kind)
                self.assertNotIn(b'PRIVATE_SENTINEL',raw)
                with self.assertRaises(type(error)): life.capture_meter(self.root,self.spend,WORKER,self.state,marker,0)
                self.assertEqual(target.read_bytes(),raw)
            self.assertFalse((target.parent/'retirement-proof.json').exists())

    def test_null_status_has_public_failure_without_proof(self):
        self.null_status=True
        with self.assertRaises(ValueError): self.test_fresh_stop_delayed_identity_and_stopped_info()
        receipt=json.loads((self.spend.with_suffix('.deletions')/WORKER/'capture-stage.json').read_text())
        self.assertEqual((receipt['stage'],receipt['error_class']),('stop_status','invalid_response'))
        self.assertFalse((self.spend.with_suffix('.deletions')/WORKER/'retirement-proof.json').exists())

    def test_transitional_supersession_refuses(self):
        self.supersede_transition=True
        with self.assertRaises(ValueError): self.test_fresh_stop_delayed_identity_and_stopped_info()
        self.assertFalse((self.spend.with_suffix('.deletions')/WORKER/'retirement-proof.json').exists())

    def test_saved_request_continues_identity_poll_without_second_stop(self):
        self.prior_request=True
        target=self.spend.with_suffix('.deletions')/WORKER/'stop-request.json'
        target.parent.mkdir(parents=True); target.write_text(json.dumps({'id':WORKER}))
        self.test_fresh_stop_delayed_identity_and_stopped_info()

    def test_fresh_stop_delayed_identity_and_stopped_info(self):
        from types import SimpleNamespace
        self.started=int(time.time())-100
        (self.state/(WORKER+'.started')).write_text(str(self.started))
        current=deepcopy(CONTRACT['info_projection']); current['sandbox'].update(state='running',stop=None)
        waiting=deepcopy(current); waiting['sandbox']['state']='stopping'
        identified=deepcopy(CONTRACT['info_projection']); identified['sandbox']['state']='stopping'
        infos=iter([current,waiting,identified,identified,CONTRACT['info_projection'],CONTRACT['info_projection']])
        calls=[]
        pending=deepcopy(CONTRACT['stop_status_response']); pending['stop'].update(status='pending',endedAt=None)
        statuses=iter([pending,CONTRACT['stop_status_response']])
        def run(argv,**kwargs):
            args=argv[1:];calls.append(args)
            if args[0]=='info':
                data=deepcopy(next(infos))
                if getattr(self,'supersede_transition',False) and not getattr(self,'supersession_emitted',False) and data['sandbox']['stop'] is not None:
                    self.supersession_emitted=True
                    data['sandbox']['stop']['status']='superseded'
            elif args==['stop',WORKER,'--json']: data={'id':WORKER}
            elif args[0]=='stop': data={'id':WORKER,'stop':None} if getattr(self,'null_status',False) else next(statuses)
            else: return SimpleNamespace(stdout=CONTRACT['usage_raw_public_json'].encode())
            return SimpleNamespace(stdout=json.dumps(data).encode())
        with patch.dict(os.environ,self.env),patch.object(key_holder,'ROOT',self.root),patch.object(life,'boot_id',return_value='AUTHORED boot'),patch.object(life.time,'sleep'),patch.object(life.subprocess,'run',side_effect=run):
            marker=life.retirement_marker(self.root,self.spend,WORKER,self.state,self.started+2700)
            with (self.state/(WORKER+'.deletion.lock')).open('a+') as fd:
                proof,_,_=life.capture_meter(self.root,self.spend,WORKER,self.state,marker,fd.fileno())
        self.assertEqual(proof['stop_id'],CONTRACT['stop_status_response']['stop']['id'])
        self.assertEqual(calls.count(['stop',WORKER,'--json']),0 if getattr(self,'prior_request',False) else 1)

    def test_delete_queries_cannot_use_unspent_meter_allowance(self):
        from types import SimpleNamespace
        budgets=[]
        def run(argv,**kwargs):
            budgets.append(float(kwargs['env']['BOAT_COMMAND_TIMEOUT_SECONDS']))
            request=argv[1]=='delete'
            return SimpleNamespace(returncode=0,stdout=json.dumps({'operation':dict(id='authored-delete',targetId=WORKER,kind='sandbox',
                status='pending' if request else 'completed',stage='pending' if request else 'completed',
                completedAt=None if request else '2026-11-04T00:00:00Z')}))
        with patch.object(life.subprocess,'run',side_effect=run):
            life._delete(self.root,self.spend,WORKER,self.state/'ids',60,deadline=time.monotonic()+180)
        self.assertTrue(all(0<b<=60 for b in budgets),budgets)

    def test_controlled_late_stop_reply_abandons_meter_without_renewing_delete_budget(self):
        from types import SimpleNamespace
        self.started=int(time.time())-100
        (self.state/(WORKER+'.started')).write_text(str(self.started))
        (self.state/(WORKER+'.collected')).touch()
        tick=[time.monotonic()]; calls=[]; budgets=[]
        def run(argv,**kwargs):
            command=argv[1:]; calls.append(command); budgets.append(float(kwargs['env']['BOAT_COMMAND_TIMEOUT_SECONDS']))
            if command[0]=='info': data=CONTRACT['info_projection']
            elif command[0]=='stop':
                tick[0]+=121  # AUTHORED late return includes 70s cancellation allowance.
                data=CONTRACT['stop_status_response']
            else:
                data={'operation':dict(id='authored-delete',targetId=WORKER,kind='sandbox',
                    status='pending' if command[0]=='delete' else 'completed',
                    stage='pending' if command[0]=='delete' else 'completed',
                    completedAt=None if command[0]=='delete' else '2026-11-04T00:00:00Z')}
            return SimpleNamespace(returncode=0,stdout=json.dumps(data).encode())
        with patch.dict(os.environ,self.env), patch.object(key_holder,'ROOT',self.root), patch.object(life,'boot_id',return_value='AUTHORED boot'), patch.object(life.time,'monotonic',side_effect=lambda:tick[0]), patch.object(life.subprocess,'run',side_effect=run):
            life.delete_receipt(self.root,self.spend,WORKER,self.state/'ids')
        self.assertEqual([c[0] for c in calls],['info','stop','delete','deletion'])
        self.assertLessEqual(budgets[0],20); self.assertLess(budgets[2],60)
        self.assertFalse((self.spend.with_suffix('.deletions')/WORKER/'retirement-proof.json').exists())
        self.assertFalse(any('--force' in c for c in calls))

    def test_wrong_creation_generation_and_corrupt_marker_never_reach_provider(self):
        self.fence(); creation=self.state/'new.1'; original=creation.read_bytes()
        creation.write_text('{"event":"created","id":"foreign"}')
        self.assertNotEqual(self.wrapper(['delete',WORKER,'--yes','--json']).returncode,0)
        creation.write_bytes(original)
        marker=self.state/(WORKER+'.retiring.json'); original=marker.read_bytes()
        for key,value in [('source_generation','b'*64),('job_config_sha256','b'*64),('schema',True),('worker_id','foreign')]:
            data=json.loads(original); data[key]=value; atomic_json(marker,data)
            self.assertNotEqual(self.wrapper(['delete',WORKER,'--yes','--json']).returncode,0)
        marker.write_bytes(original)
        self.assertEqual(self.calls(),[])
        self.assertFalse((self.state/(WORKER+'.deletion-attempted')).exists())

    @unittest.skipUnless(sys.platform=='linux','normal inherited WRITE-FD wrapper path requires Linux')
    def test_saved_meter_stop_delete_settle_and_immutable_replay_without_deleted_usage(self):
        self.started=int(time.time())-100
        (self.state/(WORKER+'.started')).write_text(str(self.started))
        (self.state/(WORKER+'.collected')).touch()
        atomic_json(self.base/'info',CONTRACT['info_projection'])
        atomic_json(self.base/'status',CONTRACT['stop_status_response'])
        (self.base/'usage').write_text(CONTRACT['usage_raw_public_json'])
        self.edge.write_text(self.edge.read_text().replace("else: sys.exit(99)",'''elif args[0]=='info':
 data=json.loads((base/'info').read_text())
 if os.environ.get('FRESH_STOP_EDGE')=='1' and not (base/'identity-visible').exists():
  data['sandbox'].update(state='stopping',stop=None)
  if (base/'stop-issued').exists(): (base/'identity-visible').touch()
 print(json.dumps(data))
elif args[0]=='stop' and '--status' not in args:
 (base/'stop-issued').touch(); print(json.dumps({'id':args[1]}))
elif args[0]=='stop' and '--status' in args: print((base/'status').read_text())
elif args[0]=='usage':
 if (base/'deleted').exists(): sys.exit(44)
 print((base/'usage').read_text(),end='')
elif args[0]=='deletion':
 (base/'deleted').touch()
 print(json.dumps({'operation':{'id':'authored-delete','targetId':os.environ['RETIREMENT_WORKER'],'kind':'sandbox','status':'completed','stage':'completed','completedAt':'2026-11-04T00:00:00Z'}}))
elif args[0]=='list': print('{"sandboxes":[],"pageInfo":{"hasMore":false}}')
else: sys.exit(99)'''))
        self.env['RETIREMENT_WORKER']=WORKER
        # Real wrapper/kernel seam: crash after meter commit but before DELETE.
        with patch.dict(os.environ,self.env), patch.object(key_holder,'ROOT',self.root):
            marker=life.retirement_marker(self.root,self.spend,WORKER,self.state,self.started+2700)
            with (self.state/(WORKER+'.deletion.lock')).open('a+') as owner:
                fcntl.flock(owner,fcntl.LOCK_EX)
                life.capture_meter(self.root,self.spend,WORKER,self.state,marker,owner.fileno())
            evidence=self.spend.with_suffix('.deletions')/WORKER
            retained=(evidence/'retirement-proof.json').read_bytes()
            resumed=deepcopy(CONTRACT['info_projection']); resumed['sandbox']['state']='running'
            atomic_json(self.base/'info',resumed)
            with self.assertRaises(ValueError): life.delete_receipt(self.root,self.spend,WORKER,self.state/'ids')
            self.assertFalse((self.state/(WORKER+'.deletion-attempted')).exists())
            self.assertFalse(any(c[0]=='delete' for c in self.calls()))
            self.assertEqual((evidence/'retirement-proof.json').read_bytes(),retained)
            atomic_json(self.base/'info',CONTRACT['info_projection'])
            life.delete_receipt(self.root,self.spend,WORKER,self.state/'ids',delete_due=self.started+2700)
        evidence=self.spend.with_suffix('.deletions')/WORKER
        proof=life.loads((evidence/'retirement-proof.json').read_bytes())
        self.assertEqual((evidence/'final-usage.json').read_text(),CONTRACT['usage_raw_public_json'])
        before={p.name:p.read_bytes() for p in evidence.iterdir()}
        for name in ('final-usage.json','stopped-info.json','retirement-proof.json'):
            file=evidence/name; original=file.read_bytes(); file.write_bytes(b'{}' if name=='retirement-proof.json' else original+b' ')
            rejected=subprocess.run([str(self.root/'bin/boat-spend'),'--settle',str(self.spend),str(self.state)],env=self.env,capture_output=True,timeout=10)
            # proof's own JSON whitespace does not invalidate its covered bytes; use malformed content there.
            if name=='retirement-proof.json':
                file.write_text('{}')
                rejected=subprocess.run([str(self.root/'bin/boat-spend'),'--settle',str(self.spend),str(self.state)],env=self.env,capture_output=True,timeout=10)
            self.assertNotEqual(rejected.returncode,0,rejected.stderr)
            file.write_bytes(original)
        bypass=self.state/(WORKER+'.metering-bypassed'); bypass.touch()
        rejected=subprocess.run([str(self.root/'bin/boat-spend'),'--settle',str(self.spend),str(self.state)],env=self.env,capture_output=True,timeout=10)
        self.assertNotEqual(rejected.returncode,0); bypass.unlink()
        settle=subprocess.run([str(self.root/'bin/boat-spend'),'--settle',str(self.spend),str(self.state)],env=self.env,capture_output=True,timeout=10)
        self.assertEqual(settle.returncode,0,settle.stderr)
        ledger=life.loads((self.home/'boat-reservations.json').read_bytes())
        row=ledger['reservations'][str(self.spend)]
        self.assertEqual(row['actual_spend_usd'],'0.00672')
        self.assertEqual(row['settlement']['schema'],2)
        self.assertEqual(row['settlement']['basis'],'stopped_usage_then_deleted')
        calls=self.calls(); self.assertEqual(sum(c[0]=='usage' for c in calls),1)
        repeat=subprocess.run([str(self.root/'bin/boat-spend'),'--settle',str(self.spend),str(self.state)],env=self.env,capture_output=True,timeout=10)
        self.assertEqual(repeat.returncode,0,repeat.stderr)
        self.assertEqual(self.calls(),calls)
        self.assertEqual({p.name:p.read_bytes() for p in evidence.iterdir()},before)
        self.assertEqual(proof['stop_id'],CONTRACT['stop_status_response']['stop']['id'])

    @unittest.skipUnless(sys.platform=='linux','fresh stop real-wrapper FD positive requires Linux')
    def test_fresh_stop_real_wrapper_and_write_fd(self):
        self.env['FRESH_STOP_EDGE']='1'
        self.test_saved_meter_stop_delete_settle_and_immutable_replay_without_deleted_usage()
        self.assertEqual(self.calls().count(['stop',WORKER,'--json']),1)

    @unittest.skipUnless(sys.platform=='linux','actual /proc/self/fdinfo WRITE proof requires Linux')
    def test_kernel_owner_fd_accepts_only_existing_write_flock(self):
        self.fence()
        path=self.state/(WORKER+'.deletion.lock')
        with path.open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_SH)
            self.assertFalse(life.owner_fd(self.state,WORKER,lock.fileno()))
            # Rejected SH was not upgraded: a second independent SH remains possible.
            with path.open('rb') as second: fcntl.flock(second,fcntl.LOCK_SH|fcntl.LOCK_NB)
            fcntl.flock(lock,fcntl.LOCK_EX)
            self.assertTrue(life.owner_fd(self.state,WORKER,lock.fileno()))
        with path.open('rb') as readonly:
            fcntl.flock(readonly,fcntl.LOCK_EX)
            self.assertFalse(life.owner_fd(self.state,WORKER,readonly.fileno()))


if __name__=='__main__': unittest.main()
