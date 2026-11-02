"""Restart the real monitor against the admission fixture's local Boat."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import io
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tarfile
import time
import unittest

import test_admission_handoff as fixture

HERE = (Path(__file__).resolve().parents[2] / "factory")


class ControlResumeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.AdmissionHandoffTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        for name in ('launch.sh', 'boat_lifecycle.py', 'control_resume.py', 'codex_login.py', 'model_router.py'):
            if (HERE / name).exists(): shutil.copyfile(HERE / name, f.root / 'factory' / name)
        for name in ('boat-launch-guards.sh', 'boat-spend', 'processes.py'):
            shutil.copyfile(HERE.parent / 'bin' / name, f.root / 'bin' / name)
            (f.root / 'bin' / name).chmod(0o755)
        shutil.copyfile(HERE / 'runner_supervisor.py', f.remote / 'factory/runner_supervisor.py')
        guards=f.root/'bin/boat-launch-guards.sh'
        guards.write_text(guards.read_text().replace('guard_delete_receipt() {',
            'guard_delete_receipt() {\n  "$root/bin/boat-call" test-gate before-delete',1).replace(
            'guard_delete_receipt || return 1', 'guard_delete_receipt || return 1\n    "$root/bin/boat-call" test-gate after-receipt',1))
        collector=f.root / 'factory/collect.sh'
        collector.write_text(collector.read_text().replace('set -eu', 'set -eu\necho collect >> "$TEST_BASE/effects"',1))
        collector.chmod(0o755)
        self.home = f.base / 'control'
        self.state = self.home / 'launches/abandoned'
        self.state.mkdir(parents=True, mode=0o700)
        self.spend = f.root / 'results/spend/test.json'
        self.spend.parent.mkdir(parents=True)
        self.spend.write_text(json.dumps(dict(provider='boat', balance_before_usd=10)))
        argv = ['1', '--admission-root', str(f.history), *f.argv]
        (self.state / 'launch.json').write_text(json.dumps(dict(argv=argv, environment={'UNBUG_CLOUD':'boat'})))
        values = dict(spend_file=str(self.spend), ttl_seconds='3600', retire_at='3500', margin='100',
                      poll='0.01', stall_minutes='45', stall_seconds='2700', unreachable='1')
        (self.state / 'monitor.sh').write_text(''.join(k+'='+shlex.quote(v)+'\n' for k,v in values.items()))
        (self.state / 'ids').write_text(f.worker+'\n')
        (self.state / (f.worker+'.started')).write_text(str(int(time.time())))
        (self.state / (f.worker+'.bench-sha')).write_text('a'*64)
        # Only synthetic credential bytes, emitted by a fake age executable.
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w') as tar:
            for name in ('claude-token','codex-auth.json','opencode-go-key','openrouter-key','statements-key'):
                value = b'synthetic credential'
                if name == 'codex-auth.json':
                    value = json.dumps({'tokens':{'access_token':'e30.eyJleHAiOjQxMDI0NDQ4MDB9.synthetic'},
                                        'last_refresh':'2026-10-28T00:00:00Z'}).encode()
                info = tarfile.TarInfo(name); info.size=len(value); tar.addfile(info, io.BytesIO(value))
        (f.base / 'bundle').write_bytes(output.getvalue())
        age = f.base / 'tools/age'
        age.write_text('#!/bin/sh\ncat '+shlex.quote(str(f.base/'bundle'))+'\n'); age.chmod(0o755)
        # Extend the existing local worker fake with provider receipts and crash gates.
        backend = f.root / 'bin/boat-call'
        original = f.root / 'bin/worker-call'
        backend.rename(original)
        code=original.read_text().replace('env={**os.environ,',
            'if a[0]=="exec": cmd=cmd[:cmd.index("unset ANTHROPIC")]+":"+cmd[cmd.index("\\nrm -f ~/sealed/DONE"):]\n' + 'env={**os.environ,')
        original.write_text(code)
        backend.write_text("#!/usr/bin/env python3\n" + r'''
import json, os, pathlib, subprocess, sys, time
base=pathlib.Path(os.environ['TEST_BASE']); a=sys.argv[1:]
phase=os.environ.get('TEST_CRASH','')
def gate(name):
    if phase==name:
        (base/'blocked').write_text(name)
        while not (base/'release').exists(): time.sleep(.01)
if a[0]=='billing':
    gate('before-spend-finish')
    with (base/'effects').open('a') as s: s.write('finish\n')
    print(json.dumps({'limits':{'creditBalanceSeconds':1000000}})); sys.exit()
if a[0]=='list':
    print(json.dumps({'sandboxes': [] if (base/'deleted').exists() else [{'id':'worker-owned','status':'running'}]})); sys.exit()
if a[0] in ('ssh','scp','exec') and (base/'deleted').exists(): sys.exit(1)
if a[0]=='test-gate': gate(a[1]); sys.exit()
if a[0]=='delete':
    with (base/'effects').open('a') as s: s.write('delete\n')
    (base/'deleted').touch()
    print(json.dumps({'operation':dict(id='op-owned',targetId='worker-owned',kind='sandbox',status='pending',stage='queued',completedAt=None)})); sys.exit()
if a[0]=='deletion':
    print(json.dumps({'operation':dict(id='op-owned',targetId='worker-owned',kind='sandbox',status='completed',stage='completed',completedAt='2026-10-23T19:30:00Z')})); sys.exit()
if a[0]=='ssh' and 'for directory, dirs, files in os.walk' in a[-1]:
    gate('before-admission')
    print('DONE'); sys.exit()
if a[0]=='ssh' and 'lock.mkdir()' in a[-1]: gate('after-handoff-reserved')
if a[0]=='exec':
    gate('before-restart')
result=subprocess.run([str(pathlib.Path(__file__).with_name('worker-call')),*a])
if a[0]=='ssh' and 's.rename(p)' in a[-1]: gate('after-admission-swap')
if a[0]=='exec' and not result.returncode:
    # The synthetic resumed runner completes with a non-retryable stop.
    card=base/'worker/sealed/case-selected.scorecard.json'
    c=json.loads(card.read_text()); c['terminal_stop']='call_limit'; card.write_text(json.dumps(c))
    (base/'worker/sealed/DONE').write_text('case-selected')
sys.exit(result.returncode)
''')
        backend.chmod(0o755)
        runner=f.remote/'factory/run.py'
        runner.write_text(runner.read_text().replace('(h/"sealed/.factory-restart.lock/owner").read_text()', '(h/"sealed/.factory-restart.lock/owner").read_text() if (h/"sealed/.factory-restart.lock/owner").exists() else "transient"'))
        self.env={**os.environ, 'UNBUG_CONTROL_HOME':str(self.home), 'UNBUG_CLOUD':'boat',
                  'BOAT_CMD':str(backend), 'TEST_BASE':str(f.base), 'BOAT_COLLECT_RETRY_SECONDS':'0',
                  'PATH':str(f.base/'tools')+os.pathsep+os.environ['PATH']}

    def start(self, crash=''):
        return subprocess.Popen(['sh', str(self.f.root/'factory/launch.sh'), '--resume-launch','abandoned'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env={**self.env,'TEST_CRASH':crash}, start_new_session=True)

    def run_resume(self):
        p=self.start()
        self.addCleanup(lambda: self.stop(p))
        try: out,err=p.communicate('synthetic identity\n',timeout=20)
        except subprocess.TimeoutExpired:
            self.stop(p)
            out,err=p.communicate(timeout=5)
            self.fail('resume timed out: '+err)
        self.assertEqual(p.returncode,0,err)

    def abandon(self, phase):
        p=self.start(phase)
        p.stdin.write('synthetic identity\n'); p.stdin.close(); p.stdin=None
        self.addCleanup(lambda: self.stop(p))
        deadline=time.monotonic()+10
        while not (self.f.base/'blocked').exists() and p.poll() is None and time.monotonic()<deadline:
            time.sleep(.01)
        if not (self.f.base/'blocked').exists():
            self.stop(p)
            self.fail('controller did not reach '+phase+': '+p.stderr.read())
        # A reboot loses the controller and every local in-flight child.
        os.killpg(p.pid,signal.SIGKILL); p.wait(timeout=5)
        p.communicate(timeout=10)
        (self.f.base/'blocked').unlink()

    @staticmethod
    def stop(p):
        if p.poll() is None:
            os.killpg(p.pid,signal.SIGKILL); p.wait(timeout=5)

    def assert_finished(self, handoffs=1, restarts=None, collections=None):
        f=self.f
        self.assertTrue((f.base/'deleted').exists())
        effects=(f.base/'effects').read_text().splitlines()
        self.assertEqual(effects.count('delete'),1)
        self.assertEqual(effects.count('finish'),1)
        if restarts is None: restarts=handoffs
        self.assertEqual(effects.count('collect'),1+restarts if collections is None else collections)
        receipt=self.spend.with_suffix('.deletions')/f.worker/'deletion-completion.json'
        self.assertEqual(json.loads(receipt.read_text())['targetId'],f.worker)
        calls=[json.loads(s) for s in (f.base/'calls').read_text().splitlines()]
        self.assertEqual(sum(c[0]=='exec' for c in calls),restarts)
        self.assertEqual(sum(c[0]=='ssh' and 's.rename(p)' in c[-1] for c in calls),handoffs)
        self.assertEqual(self.state.stat().st_mode & 0o777,0o700)
        data=b''.join(p.read_bytes() for p in self.state.rglob('*') if p.is_file())
        self.assertNotIn(b'synthetic identity',data)
        self.assertNotIn(b'synthetic credential',data)
        self.run_resume()  # Completed launches are harmless to resume again.
        self.assertEqual((f.base/'effects').read_text().splitlines(),effects)

    def test_batch_marker_survives_orphan_and_done_retires_without_restart(self):
        launch = json.loads((self.state / 'launch.json').read_text())
        launch['environment']['UNBUG_BATCH_OPERATION'] = 'e3d67c9e-5678-5abc-8123-123456789abc'
        (self.state / 'launch.json').write_text(json.dumps(launch))
        # Collector transport double: this test isolates orphan marker/guard flow.
        collector = self.f.root / 'factory/collect.sh'
        collector.write_text('#!/bin/sh\necho collect >> "$TEST_BASE/effects"\n')
        collector.chmod(0o755)
        (self.f.base / 'calls').touch()
        self.run_resume(); self.assert_finished(handoffs=0, restarts=0)

    def test_killed_before_admission_handoff(self):
        self.abandon('before-admission'); self.run_resume(); self.assert_finished()

    def test_abandoned_after_handoff_reserved(self):
        self.abandon('after-handoff-reserved')
        self.assertTrue((self.state/(self.f.worker+'.admission-'+self.f.card['sha256']+'.reserved')).exists())
        self.run_resume(); self.assert_finished()

    def test_killed_after_admission_snapshot_swap(self):
        self.abandon('after-admission-swap'); self.run_resume(); self.assert_finished()

    def test_abandoned_bare_admission_reservation(self):
        (self.state/(self.f.worker+'.admission-'+self.f.card['sha256']+'.reserved')).touch()
        self.run_resume(); self.assert_finished()

    def test_killed_after_collection_before_deletion(self):
        self.f.card['terminal_stop']='call_limit'; self.f.save_card()
        self.abandon('before-delete'); self.run_resume(); self.assert_finished(handoffs=0)

    def test_killed_after_deletion_before_spend_finish(self):
        self.f.card['terminal_stop']='call_limit'; self.f.save_card()
        self.abandon('before-spend-finish'); self.run_resume(); self.assert_finished(handoffs=0)

    def test_deletion_receipt_recovers_with_pending_restart(self):
        f=self.f
        f.card['terminal_stop']='call_limit'; f.save_card()
        (self.state/(f.worker+'.restart-attempted')).write_text('old generation')
        (self.state/(f.worker+'.restart-acknowledged')).touch()
        (self.state/(f.worker+'.started')).write_text('1')
        self.abandon('after-receipt')
        self.assertFalse((self.state/(f.worker+'.deleted')).exists())
        self.run_resume(); self.assert_finished(handoffs=0)

    def test_live_owner_excludes_second_controller(self):
        p=self.start('before-admission')
        p.stdin.write('synthetic identity\n'); p.stdin.close(); p.stdin=None
        self.addCleanup(lambda: self.stop(p))
        deadline=time.monotonic()+10
        while not (self.f.base/'blocked').exists() and p.poll() is None and time.monotonic()<deadline: time.sleep(.01)
        self.assertTrue((self.f.base/'blocked').exists())
        other=self.start(); _,err=other.communicate('synthetic identity\n',timeout=10)
        self.assertNotEqual(other.returncode,0)
        self.assertIn('owned',err)
        owner=json.loads((self.state/'controller.lock').read_text())
        self.assertEqual(owner['pid'],p.pid); self.assertTrue(owner['started'])
        os.kill(p.pid,signal.SIGKILL); p.wait(timeout=5)
        (self.f.base/'release').touch(); p.communicate(timeout=10)
        self.run_resume(); self.assert_finished()

    def test_recycled_pid_does_not_own_launch(self):
        (self.state/'controller.lock').write_text(json.dumps({'pid':os.getpid(),'started':'old process'}))
        self.run_resume(); self.assert_finished()

    def test_scan_resumes_abandoned_launch(self):
        result=subprocess.run(['sh',str(self.f.root/'factory/launch.sh'),'--resume-launches'],
            input='synthetic identity\n',text=True,capture_output=True,env=self.env,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assert_finished()

    def test_scan_starts_all_monitors_before_waiting(self):
        second=self.home/'launches/second'
        shutil.copytree(self.state,second)
        launcher=self.f.root/'factory/launch.sh'
        launcher.write_text('#!/bin/sh\nset -eu\ntouch "$TEST_BASE/started-$2"\nwhile [ ! -f "$TEST_BASE/started-abandoned" ] || [ ! -f "$TEST_BASE/started-second" ]; do sleep .01; done\n')
        p=subprocess.Popen(['python3',str(launcher.with_name('control_resume.py')),'--resume-launches'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=self.env,start_new_session=True)
        try: _,err=p.communicate('synthetic identity\n',timeout=5)
        except subprocess.TimeoutExpired:
            self.stop(p); _,err=p.communicate(timeout=5)
            self.fail('scan did not start both monitors: '+err)
        self.assertEqual(p.returncode,0,err)
        self.assertTrue((self.f.base/'started-abandoned').exists())
        self.assertTrue((self.f.base/'started-second').exists())

    def test_transient_retry_preserves_deadline_and_attempt_count(self):
        f=self.f
        f.card['terminal_stop']='stalled'; f.save_card()
        (self.state/(f.worker+'.retry-at')).write_text('1')
        (self.state/(f.worker+'.autoresumes')).write_text('1')
        started=(self.state/(f.worker+'.started')).read_text()
        self.abandon('before-admission'); self.run_resume()
        self.assert_finished(handoffs=0,restarts=1)
        self.assertEqual((self.state/(f.worker+'.autoresumes')).read_text().strip(),'2')
        self.assertEqual((self.state/(f.worker+'.started')).read_text(),started)
        self.assertFalse((self.state/(f.worker+'.retry-at')).exists())

    def test_acknowledged_restart_waits_for_a_new_checkpoint(self):
        f=self.f
        result=subprocess.run(['sh',str(f.root/'factory/collect.sh'),f.worker],env=self.env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        digest=hashlib.sha256((f.root/'sealed'/(f.case+'.scorecard.json')).read_bytes()).hexdigest()
        (self.state/(f.worker+'.collected')).touch()
        (self.state/(f.worker+'.restart-attempted')).write_text(digest)
        (self.state/(f.worker+'.restart-acknowledged')).touch()
        p=self.start()
        self.addCleanup(lambda: self.stop(p))
        p.stdin.write('synthetic identity\n'); p.stdin.close(); p.stdin=None
        deadline=time.monotonic()+5
        while not (f.base/'calls').exists() and p.poll() is None and time.monotonic()<deadline: time.sleep(.01)
        time.sleep(.5)
        self.assertIsNone(p.poll())
        calls=[json.loads(s) for s in (f.base/'calls').read_text().splitlines()]
        self.assertFalse(any(c[0]=='exec' or (c[0]=='ssh' and 's.rename(p)' in c[-1]) for c in calls))
        self.assertFalse((self.state/(f.worker+'.admission-handoffs')).exists())
        self.stop(p); p.communicate(timeout=5)
        prior=(f.base/'effects').read_text().splitlines().count('collect')
        # Reboot immediately after an early poll collected the old DONE. The worker
        # subsequently finishes a new checkpoint; retirement must not trust that marker.
        (self.state/(f.worker+'.collected')).touch()
        archive=f.remote/'sealed'/f.archive
        archive.write_bytes(archive.read_bytes()+b' later completed checkpoint')
        f.card['sha256']=f.sha(archive); f.card['terminal_stop']='call_limit'; f.save_card()
        (self.state/(f.worker+'.started')).write_text('1')  # retire at the original TTL
        self.run_resume()
        self.assertEqual(f.sha(f.root/'sealed'/f.archive),f.card['sha256'])
        self.assertEqual(json.loads((f.root/'sealed'/(f.case+'.scorecard.json')).read_text()),f.card)
        self.assert_finished(handoffs=0,collections=prior+1)

    def test_new_launch_records_persistent_job_and_spend_path(self):
        # Deliberately stop at the fake's unsupported create. No worker is made.
        f=self.f
        (f.root/'factory/worker_release.py').write_text('')
        result=subprocess.run(['sh',str(f.root/'factory/launch.sh'),'1','--source','hunt','--dry-run'],
            input='synthetic identity\n',text=True,capture_output=True,env=self.env,timeout=20)
        states=[p for p in (self.home/'launches').iterdir() if p != self.state]
        self.assertEqual(len(states),1,result.stderr)
        state=states[0]
        self.assertEqual(state.stat().st_mode & 0o777,0o700)
        job=json.loads((state/'launch.json').read_text())
        self.assertEqual(job['argv'],['1','--source','hunt','--dry-run'])
        monitor=(state/'monitor.sh').read_text()
        self.assertIn(str(f.root/'results/spend'),monitor)
        self.assertTrue((state/'ids').exists())
        self.assertFalse((f.base/'deleted').exists())

class CreationIntentTests(unittest.TestCase):
    """Real exec/lock/Boat wrappers; saved provider data with authored crash timing."""
    setUp = ControlResumeTests.setUp
    stop = staticmethod(ControlResumeTests.stop)

    def provider(self):
        root = HERE.parent
        fixtures = root / 'tests/factory/fixtures/isolation-timeouts'
        self.created = json.loads((fixtures / 'created.json').read_text())
        self.provider_path = self.f.base / 'creation-provider'
        self.provider_path.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, time
base=pathlib.Path(os.environ['TEST_BASE']); a=sys.argv[1:]
fixtures=pathlib.Path(os.environ['CREATION_FIXTURES'])
event=json.loads((fixtures/'created.json').read_text()); worker=event['id']
with (base/'creation-calls').open('a') as f: f.write(json.dumps(a)+'\\n')
if a[0]=='new':
 state=pathlib.Path(os.environ['UNBUG_LAUNCH_STATE'] if 'UNBUG_LAUNCH_STATE' in os.environ else os.environ['TEST_STATE'])
 assert (state/'new.1.pending').is_file()
 (base/'provider-pid').write_text(str(os.getpid()))
 (base/'create-entered').touch()
 if os.environ.get('CREATE_BLOCK')=='1':
  end=time.monotonic()+20
  while not (base/'release').exists():
   if time.monotonic()>end: sys.exit(90)
   time.sleep(.01)
 if os.environ.get('CREATE_UNKNOWN')!='1': print(json.dumps(event),flush=True)
 sys.exit(int(os.environ.get('CREATE_EXIT','0')))
elif a[0]=='billing': print((fixtures/'billing.json').read_text())
elif a[0]=='list':
 if os.environ.get('LIST_FAIL')=='1': sys.exit(9)
 print((fixtures/'list.json').read_text())
elif a[0]=='delete':
 print(json.dumps({'operation':dict(id='op-owned',targetId=worker,kind='sandbox',status='pending',stage='queued',completedAt=None)}))
elif a[0]=='deletion':
 print(json.dumps({'operation':dict(id='op-owned',targetId=worker,kind='sandbox',status='completed',stage='completed',completedAt='2026-10-23T19:30:00Z')}))
else: sys.exit(9)
''')
        self.provider_path.chmod(0o755)
        # The real wrapper owns the provider process session. No production transport.
        shutil.copyfile(root / 'bin/boat-call', self.f.root / 'bin/boat-call')
        self.env.update(BOAT_CMD=str(self.provider_path), CREATION_FIXTURES=str(fixtures),
                        BOAT_TYPE='default', TEST_STATE=str(self.state))
        # control_resume deliberately clears ambient transport overrides. Bind the
        # existing resume fixture to this fake just as fresh launch.json does.
        launch=json.loads((self.state/'launch.json').read_text())
        launch['environment']['BOAT_CMD']=str(self.provider_path)
        (self.state/'launch.json').write_text(json.dumps(launch))
        # Copy public release inputs missing from the older resume-only fixture.
        from launch_manifest import worker_files
        for name in worker_files(root):
            source=root/name; destination=self.f.root/name
            if source.is_file() and not destination.exists():
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,destination)
        shutil.copyfile(HERE/'worker_release.py',self.f.root/'factory/worker_release.py')
        # Collection is outside these crash exams; deletion still uses the real verifier.
        collector = self.f.root / 'factory/collect.sh'
        collector.write_text('#!/bin/sh\nexit 0\n'); collector.chmod(0o755)
        self.addCleanup(self.kill_provider)

    def kill_provider(self):
        path = self.f.base / 'provider-pid'
        if path.exists():
            try: os.killpg(int(path.read_text()), signal.SIGKILL)
            except ProcessLookupError: pass

    def wait_file(self, path, process):
        deadline=time.monotonic()+15
        while not path.exists() and process.poll() is None and time.monotonic()<deadline:
            time.sleep(.01)
        if not path.exists():
            self.stop(process); _,err=process.communicate(timeout=5)
            self.fail('creation did not reach the fault boundary: '+err)

    def fresh(self):
        self.provider()
        p=subprocess.Popen(['sh', str(self.f.root/'factory/launch.sh'), '1', '--source', 'hunt', '--dry-run'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**self.env,'CREATE_BLOCK':'1'}, start_new_session=True)
        self.addCleanup(lambda: self.stop(p))
        p.stdin.write('synthetic identity\n'); p.stdin.close(); p.stdin=None
        self.wait_file(self.f.base/'create-entered', p)
        self.state=next(path for path in (self.home/'launches').iterdir() if path.name!='abandoned')
        self.spend=next(path for path in (self.f.root/'results/spend').glob('*.json') if path.name!='test.json')
        return p

    def resume(self):
        return subprocess.run(['sh',str(self.f.root/'factory/launch.sh'),'--resume-launch',self.state.name],
            input='synthetic identity\n',text=True,capture_output=True,env=self.env,timeout=20)

    def ledger(self):
        return json.loads((self.home/'boat-reservations.json').read_text())

    def calls(self):
        return [json.loads(line) for line in (self.f.base/'creation-calls').read_text().splitlines()]

    def assert_unfinished(self, before):
        self.assertTrue((self.state/'new.1.pending').exists())
        self.assertFalse((self.state/'complete').exists())
        self.assertNotIn('finished_at',json.loads(self.spend.read_text()))
        self.assertEqual(self.ledger(),before)
        self.assertEqual(sum(a[0]=='new' for a in self.calls()),1)

    def test_killed_creator_retains_money_across_resume_and_holder(self):
        p=self.fresh(); before=self.ledger()
        os.killpg(p.pid,signal.SIGKILL); self.kill_provider()
        p.communicate(timeout=10)
        for _ in range(2):
            resumed=self.resume()
            self.assertEqual(resumed.returncode,0,resumed.stderr)
            self.assertEqual(json.loads((self.state/'cleanup-status.json').read_text()),
                             dict(primary_exit_code=0,cleanup_failed=False))
            self.assert_unfinished(before)
        # Same crash artifacts, bound to the existing holder fixture's operation.
        import test_batch_holder as hf
        h=hf.HolderTests(); h.setUp(); self.addCleanup(h.doCleanups)
        op=h.started(h.reserve(),created=False)
        destination=h.home/'launches'/op['launch_id']
        for name in ('ids','new.1','new.1.pending'):
            shutil.copyfile(self.state/name,destination/name)
        h.reconcile(); current=h.ops()[op['operation_id']]
        self.assertEqual((current['state'],current['incident']),('pending','creation_unknown'))
        self.assertEqual(hf.holder.record_child(h.policy,h.root,h.home,op['operation_id'],'resume',resumed.returncode),1)
        self.assertEqual(h.ops()[op['operation_id']]['failures'],1)

    def test_surviving_creator_holds_lock_then_resume_finishes(self):
        p=self.fresh()
        os.kill(p.pid,signal.SIGKILL); p.wait(timeout=5)
        early=self.resume()
        self.assertNotEqual(early.returncode,0)
        self.assertIn('owned',early.stderr)
        (self.f.base/'release').touch(); p.communicate(timeout=10)
        result=self.resume()
        # Existing monitor lacks started when creation outlives its controller;
        # the missing-start path aborts monitoring into the real exit cleanup.
        self.assertIn('.started',result.stderr)
        self.assertFalse((self.state/'new.1.pending').exists(),result.stderr)
        self.assertEqual((self.state/'ids').read_text().split(),[self.created['id']])
        self.assertTrue((self.state/'complete').exists(),result.stderr)
        self.assertIn('finished_at',json.loads(self.spend.read_text()))
        self.assertEqual(self.ledger()['reservations'][str(self.spend.resolve())]['status'],'finished')
        proof=self.spend.with_suffix('.deletions')/self.created['id']/'deletion-completion.json'
        self.assertEqual(json.loads(proof.read_text())['status'],'completed')
        calls=self.calls(); self.resume(); self.assertEqual(self.calls(),calls)

    def bare(self, body, **environment):
        script='''root=$1; state=$2; spend_file=$3; serial=0; bundle=''; label=factory
id=''; ttl_seconds=3600; purpose=case
. "$root/bin/boat-launch-guards.sh"
collect_vm() { return 0; }
''' + body
        return subprocess.Popen(['sh','-c',script,'sh',str(self.f.root),str(self.state),str(self.spend)],
            env={**self.env,**environment},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)

    def test_sigterm_live_exit_resolves_or_retains_without_saved_state(self):
        self.provider()
        (self.state/'ids').write_text('')
        p=self.bare("trap 'guard_exit $?' 0\ntrap 'exit 143' TERM\nguard_new\n", CREATE_BLOCK='1')
        self.addCleanup(lambda:self.stop(p))
        self.wait_file(self.f.base/'create-entered',p)
        os.kill(p.pid,signal.SIGTERM); (self.f.base/'release').touch()
        _,err=p.communicate(timeout=15)
        self.assertEqual(p.returncode,143,err)
        self.assertFalse(self.state.exists(),err)
        data=json.loads(self.spend.read_text())
        self.assertEqual(data['ids'],[self.created['id']]); self.assertIn('finished_at',data)
        proof=self.spend.with_suffix('.deletions')/self.created['id']/'deletion-completion.json'
        self.assertEqual(json.loads(proof.read_text())['status'],'completed')
        # Unknown create, same live SIGTERM path, must retain evidence and not finish.
        self.state.mkdir(); (self.state/'ids').touch()
        self.spend.write_text(json.dumps(dict(provider='boat',balance_before_usd=10)))
        for name in ('release','create-entered'): (self.f.base/name).unlink()
        p=self.bare("trap 'guard_exit $?' 0\ntrap 'exit 143' TERM\nguard_new\n", CREATE_BLOCK='1',CREATE_UNKNOWN='1')
        self.addCleanup(lambda:self.stop(p))
        self.wait_file(self.f.base/'create-entered',p)
        os.kill(p.pid,signal.SIGTERM); (self.f.base/'release').touch()
        _,err=p.communicate(timeout=15)
        self.assertEqual(p.returncode,143,err)
        self.assertTrue((self.state/'new.1.pending').exists())
        self.assertNotIn('finished_at',json.loads(self.spend.read_text()))

    def test_success_nonzero_and_early_failure_preserve_identity(self):
        self.provider(); (self.state/'ids').write_text('')
        # Nonzero provider status still has a known identity and durable ownership.
        p=self.bare('guard_new; result=$?; printf "%s %s" "$result" "$id"',CREATE_EXIT='9')
        out,err=p.communicate(timeout=10)
        self.assertEqual(out,'1 '+self.created['id'],err)
        self.assertFalse((self.state/'new.1.pending').exists())
        self.assertEqual((self.state/'ids').read_text().split(),[self.created['id']])
        old=(self.state/'new.1').read_bytes()
        p=self.bare('id=stale; guard_new; result=$?; printf "%s:%s" "$result" "$id"')
        out,err=p.communicate(timeout=10)
        self.assertEqual(out,'1:',err); self.assertEqual((self.state/'new.1').read_bytes(),old)
        (self.state/'new.2.pending').mkdir()
        p=self.bare('serial=1; id=stale; guard_new; result=$?; printf "%s:%s\\n" "$result" "$id"; guard_exit 1',
                    UNBUG_LAUNCH_STATE=str(self.state))
        out,err=p.communicate(timeout=10)
        self.assertEqual(out,'1:\n',err)
        self.assertEqual((self.state/'ids').read_text().split(),[self.created['id']])
        self.assertFalse((self.state/'complete').exists())
        self.assertNotIn('finished_at',json.loads(self.spend.read_text()))
        self.assertEqual(sum(a[0]=='new' for a in self.calls()),1)

    def test_merge_failure_keeps_prior_ids_and_reported_id(self):
        self.provider(); (self.state/'ids').write_text('existing-reuse-worker\n')
        (self.state/'new.9').mkdir()  # Read failure after valid serial 1 event.
        p=self.bare('guard_new; result=$?; printf "%s:%s" "$result" "$id"')
        out,err=p.communicate(timeout=10)
        self.assertEqual(out,'1:'+self.created['id'],err)
        self.assertTrue((self.state/'new.1.pending').exists())
        self.assertEqual((self.state/'ids').read_text(),'existing-reuse-worker\n')
        # Real receipt verifier refuses the reported ID missing from durable ids.
        p=self.bare('guard_retire '+shlex.quote(self.created['id'])+'; printf "%s" "$?"')
        out,err=p.communicate(timeout=10)
        self.assertEqual(out,'1',err)
        self.assertIn('deletion receipt verification FAILED',err)
        self.assertFalse(any(a[0]=='delete' for a in self.calls()))
        self.assertEqual((self.state/'ids').read_text(),'existing-reuse-worker\n')
        self.assertNotIn('finished_at',json.loads(self.spend.read_text()))
        self.assertFalse((self.state/'complete').exists())

    def test_merge_failure_alone_blocks_finish_after_verified_retirement(self):
        self.provider(); (self.state/'ids').write_text('')
        p=self.bare('guard_new || exit 91; guard_retire "$id" || exit 92; mkdir "$state/new.9"; guard_exit 0',
                    UNBUG_LAUNCH_STATE=str(self.state))
        _,err=p.communicate(timeout=10)
        self.assertEqual(p.returncode,1,err)
        self.assertEqual((self.state/'ids').read_text().split(),[self.created['id']])
        self.assertTrue((self.state/(self.created['id']+'.deleted')).exists())
        self.assertEqual(list(self.state.glob('new.*.pending')),[])
        self.assertNotIn('finished_at',json.loads(self.spend.read_text()))
        self.assertFalse((self.state/'complete').exists())
        self.assertTrue(json.loads((self.state/'cleanup-status.json').read_text())['cleanup_failed'])
        # Non-object JSON is also an evidence error, even with no uncertainty marker.
        (self.state/'new.9').rmdir(); (self.state/'new.9').write_text('42\n')
        p=self.bare('guard_exit 0',UNBUG_LAUNCH_STATE=str(self.state))
        _,err=p.communicate(timeout=10)
        self.assertEqual(p.returncode,1,err)
        self.assertNotIn('finished_at',json.loads(self.spend.read_text()))
        self.assertFalse((self.state/'complete').exists())

    def test_unrelated_inventory_error_keeps_prior_finish_semantics(self):
        self.provider(); (self.state/'ids').write_text('')
        p=self.bare('guard_new || exit 91; guard_retire "$id" || exit 92; guard_exit 0',
                    UNBUG_LAUNCH_STATE=str(self.state),LIST_FAIL='1')
        _,err=p.communicate(timeout=10)
        self.assertEqual(p.returncode,1,err)
        self.assertTrue(json.loads((self.state/'cleanup-status.json').read_text())['cleanup_failed'])
        self.assertIn('finished_at',json.loads(self.spend.read_text()))
        self.assertTrue((self.state/'complete').exists())

    def test_dangling_marker_refuses_submission_and_finish(self):
        self.provider(); (self.state/'ids').write_text('')
        (self.state/'new.1.pending').symlink_to(self.state/'absent')
        p=self.bare('id=stale; guard_new; printf "%s:%s" "$?" "$id"; guard_exit 1',
                    UNBUG_LAUNCH_STATE=str(self.state))
        out,err=p.communicate(timeout=10)
        self.assertEqual(out,'1:',err)
        self.assertTrue((self.state/'new.1.pending').is_symlink())
        self.assertNotIn('finished_at',json.loads(self.spend.read_text()))
        self.assertFalse((self.state/'complete').exists())
        self.assertFalse((self.f.base/'creation-calls').exists())

    def test_resume_propagates_evidence_merge_failure_before_monitor(self):
        self.provider()
        (self.state/'new.9').mkdir()
        result=self.resume()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('creation evidence could not be persisted',result.stderr)
        self.assertEqual(json.loads((self.state/'cleanup-status.json').read_text())['primary_exit_code'],1)
        self.assertFalse(any(a[0]=='ssh' for a in self.calls()))
        self.assertNotIn('finished_at',json.loads(self.spend.read_text()))
        self.assertFalse((self.state/'complete').exists())


if __name__=='__main__': unittest.main()
