"""Real retained failure, real runner handler, and isolated offline Docker ownership."""
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'factory'), str(ROOT/'bin')]
import run
import bench
import factory_pool

FIXTURE = ROOT/'tests/factory/fixtures/practice-startup-conflict-20261103.json'
CONFLICT = next(r['message'] for r in json.loads(FIXTURE.read_text()) if r['location'].endswith('commands.log:4'))


class Diagnostics(unittest.TestCase):
    def test_real_command_tail_capture_bounds_and_redaction(self):
        with tempfile.TemporaryDirectory() as d:
            c=SimpleNamespace(work=Path(d),args=SimpleNamespace(agent_timeout=10))
            (c.work/'logs').mkdir()
            script=c.work/'fail.py'
            script.write_text('import sys,os\nprint('+repr(CONFLICT)+',file=sys.stderr)\nprint(os.environ["TEST_TOKEN"],file=sys.stderr)\nprint("sk-public-sentinel Bearer public-bearer https://user:pass@example.invalid/?token=value",file=sys.stderr)\nsys.exit(1)\n')
            for capture in (False,True):
                (c.work/'logs/commands.log').write_text('OLD DIAGNOSTIC MUST NOT REAPPEAR\n')
                with self.subTest(capture=capture), self.assertRaises(RuntimeError) as caught:
                    run.sh(c,[sys.executable,script],capture=capture,check=True,
                           env={**os.environ,'TEST_TOKEN':'public-offline-secret','TEST_AUTH_ENABLED':'1'})
                message=str(caught.exception)
                self.assertIn(CONFLICT,message); self.assertIn('exit 1',message)
                for value in ('OLD DIAGNOSTIC','public-offline-secret','sk-public-sentinel','public-bearer','user:pass'):
                    self.assertNotIn(value,message)
            script.write_text('import os,sys\nos.write(2,b"x"*10000+b"\\nlast error\\xff\\n");sys.exit(2)\n')
            with self.assertRaises(RuntimeError) as caught: run.sh(c,[sys.executable,script],check=True)
            self.assertIn('last error',str(caught.exception)); self.assertLess(len(str(caught.exception)),4200)

    def test_every_startup_mode_uses_checked_owner_and_retains_real_error(self):
        if not shutil.which('age'): self.skipTest('real age absent: encrypted runner evidence exam unavailable')
        bootstrap=r'''
import pathlib,sys,json,hashlib,os,subprocess
import run, factory_pool, founder_decisions, founder_ruling, late_recovery, sealed_audit, late_rehearsal, job_config, diagnosis_dispatch, r2_upload
root=pathlib.Path(sys.argv[1]); mode=sys.argv[2]; run.HOME=root;run.SEALED=root/'sealed';run.BENCH=root/'bench'
run.BENCH.mkdir(); (run.BENCH/'results').mkdir();run.FOUNDER_RECIPIENT=sys.argv[3]
run.pilot_homes=lambda:[]; r2_upload.upload=lambda *a,**kw:None
run.bench_manifest=lambda:'trusted'; run.inherit_recovery_history=lambda *a:None
run.archive_pilot_state=lambda *a:None; founder_decisions.record=lambda *a:None
founder_ruling.context=lambda *a:None; late_recovery.authenticate_gates=lambda *a:None
sealed_audit.prepare=lambda *a:None; late_rehearsal.recipient=lambda *a:None
job_config.install=lambda c,a:setattr(c,'job_money',{})
diagnosis_dispatch.carry_context=lambda *a:None; diagnosis_dispatch.dispatch=lambda *a,**kw:1
run.pick_models=lambda *a:(_ for _ in ()).throw(AssertionError('model selection after startup failure'))
run.finalize_accounting=lambda *a:None  # Accounting is independently tested, not inferred as zero.
conflict=json.loads(pathlib.Path(sys.argv[4]).read_text())
message=next(r['message'] for r in conflict if r['location'].endswith('commands.log:4'))
script=root/'fail.py';script.write_text('import sys,os\nprint('+repr(message)+',file=sys.stderr)\nprint(os.environ["TEST_TOKEN"],file=sys.stderr)\nsys.exit(1)\n')
def prepare(slots,*,previous_slots=1,fresh=False,execute=None):
 assert slots==1 and previous_slots==1 and fresh is True
 (root/'startup-called').write_text(mode)
 # Explicit check reproduces the duplicate-key hazard in the required adapter.
 execute([sys.executable,str(script)],check=True)
 raise AssertionError('failed startup did not raise')
factory_pool.prepare=prepare
args=['run.py','--source','port']
if mode=='dry-run':args+=['--dry-run']
if mode=='statement-only':args+=['--statement-only']
if mode in ('resume','rehearse-only','audit-fairness','late-gate-rehearsal','extension'):
 case='case-late-rehearsal-test' if mode=='late-gate-rehearsal' else 'case-test'
 work=root/'work'/case; (work/'case').mkdir(parents=True);(work/'logs').mkdir()
 (work/'scorecard.json').write_text('{}');args+=['--resume',case,'--resume-bench-sha','trusted']
 if mode in ('rehearse-only','audit-fairness'):args+=['--'+mode]
 if mode=='late-gate-rehearsal':args+=['--late-gate-rehearsal','--rehearsal-recipient',sys.argv[3]]
 if mode=='extension':
  (root/'batch-release.json').write_text('{}');args+=['--batch-release-sha256',hashlib.sha256(b'{}').hexdigest()]
os.environ['TEST_TOKEN']='public-runner-error-sentinel';sys.argv=args;run.main()
'''
        for mode in ('ordinary','dry-run','resume','rehearse-only','audit-fairness','late-gate-rehearsal','statement-only','extension'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as d:
                root=Path(d); key=root/'test.identity'
                subprocess.run(['age-keygen','-o',str(key)],capture_output=True,check=True)
                recipient=subprocess.check_output(['age-keygen','-y',str(key)],text=True).strip()
                result=subprocess.run([sys.executable,'-c',bootstrap,str(root),mode,recipient,str(FIXTURE)],
                    env={**os.environ,'PYTHONPATH':str(ROOT/'factory')+os.pathsep+str(ROOT/'bin')},capture_output=True,text=True,timeout=35)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual((root/'startup-called').read_text(),mode)
                card=json.loads(next((root/'sealed').glob('*.scorecard.json')).read_text())
                self.assertEqual(card['terminal_stop'],'runner_error:RuntimeError')
                self.assertEqual(card['error_evidence'],'logs/runner.log')
                self.assertNotIn('public-runner-error-sentinel',json.dumps(card)); self.assertNotIn(CONFLICT,json.dumps(card))
                archive=next((root/'sealed').glob('*.checkpoint.tar.gz.age'))
                decrypt_key=next((root/'sealed').glob('*.throwaway-key.txt')) if mode=='dry-run' else key
                data=subprocess.check_output(['age','-d','-i',str(decrypt_key),str(archive)])
                with tarfile.open(fileobj=io.BytesIO(data)) as t:
                    log=t.extractfile(next(m for m in t if m.name.endswith('/logs/runner.log'))).read().decode()
                self.assertIn(CONFLICT,log);self.assertIn('RuntimeError:',log)
                self.assertNotIn('public-runner-error-sentinel',log)


class RealDocker(unittest.TestCase):
    def test_unadopted_container_volume_is_fresh_at_startup_and_g3(self):
        if not shutil.which('docker'): self.skipTest('Docker absent: real volume/seed exam must run on the handback Mac')
        def docker(*args,check=True,**kw):
            p=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=60,**kw)
            if check:self.assertEqual(p.returncode,0,p.stderr)
            return p
        docker('info','--format','{{.ServerVersion}}')
        image='postgres:17.11-bookworm';docker('image','inspect',image) # No pulls.
        project='unbug-startup-test-'+uuid.uuid4().hex[:8]
        name=project+'-postgres-1';volume=project+'_postgres-data';sentinel=project+'-unrelated'
        compose=['docker','compose','-p',project,'-f',str(ROOT/'projects/medusa/compose.yaml')]
        def dc(*args):
            p=subprocess.run([*compose,*args],capture_output=True,text=True,timeout=60)
            self.assertEqual(p.returncode,0,p.stderr);return p.stdout
        def sql(query):return docker('exec',name,'psql','-Xq','-v','ON_ERROR_STOP=1','-U','medusa','-d','postgres','-c',query)
        def ready():
            until=time.monotonic()+30
            while docker('exec',name,'pg_isready','-h','127.0.0.1','-U','medusa',check=False).returncode:
                if time.monotonic()>until:self.fail('isolated Postgres did not become ready')
                time.sleep(.2)
        try:
            docker('volume','create','--label','com.docker.compose.project='+project,'--label','com.docker.compose.volume=postgres-data',volume)
            docker('run','--pull','never','-d','--name',name,'-e','POSTGRES_USER=medusa','-e','POSTGRES_PASSWORD=public-offline',
                   '-v',volume+':/var/lib/postgresql/data',image)
            docker('create','--name',sentinel,image)
            ready();sql('CREATE ROLE bench_checker;');sql('CREATE DATABASE medusa_seed;')
            docker('exec',name,'touch','/var/lib/postgresql/data/old-pilot-marker');docker('stop',name)
            bad=subprocess.run([*compose,'up','--pull','never','--no-build','-d','--wait','postgres'],capture_output=True,text=True,timeout=60)
            self.assertNotEqual(bad.returncode,0);self.assertIn('already in use',bad.stderr)
            dc('down','-v');docker('volume','inspect',volume) # Prove old ordering retains it.
            with tempfile.TemporaryDirectory() as d:
                results=Path(d)
                def setup():
                    with (results/'.bench.lock').open('r') as f:
                        with self.assertRaises(BlockingIOError):fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    dc('up','--pull','never','--no-build','-d','--wait','postgres')
                    self.assertNotEqual(docker('exec',name,'test','-e','/var/lib/postgresql/data/old-pilot-marker',check=False).returncode,0)
                    sql('CREATE ROLE bench_checker;');sql('CREATE DATABASE medusa_seed;')
                    docker('inspect',sentinel)
                def execute(cmd,**kw):
                    self.assertEqual(cmd[2],'import bench; bench.prepare_factory_main()')
                    bench.prepare_factory_main();return 0
                with patch.multiple(bench,RESULTS=results,COMPOSE=compose,COMPOSE_PROJECT=project,FACTORY_SLOT=0), \
                     patch.object(bench,'stop_inventory_services'), patch.object(bench,'setup',side_effect=setup):
                    for phase in ('startup','G3'):
                        with self.subTest(phase=phase):self.assertTrue(factory_pool.prepare(1,fresh=True,execute=execute))
            print('REAL DOCKER: conflict, mounted-volume freshness and repeated seed SQL passed',flush=True)
        finally:
            docker('rm','-f',name,sentinel,check=False)
            subprocess.run([*compose,'down','-v','--remove-orphans'],capture_output=True,timeout=60)
            docker('volume','rm',volume,check=False)


if __name__=='__main__':unittest.main()
