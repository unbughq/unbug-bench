"""Synthetic successor manifests, D1 caps and TTL retirement. No real bundles/workers."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'factory'))
import key_holder
import restore_bundle as b


def copy_host_sources(destination):
    # Staging now requires the declared host dependencies even for tiny releases.
    for name in (*b.HOST_FILES, *b.PUBLISHER.values()):
        target = destination/name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT/name).read_bytes())


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name);self.old=self.home/'old';self.old.mkdir()
        self.case=next(iter(b.CASES));self.worker='bx_synthetic'
        self.state=self.old/'control-home/launches/test';self.state.mkdir(parents=True)
        self.args=['1','--restore',self.case,'--qualified-release','old','--max-total-calls','2000',
            '--ttl-hours','8','--max-spend','0.5','--case-budget','70','--rounds','10',
            '--founder-ruling-sha256','a'*64]
        b.save(self.state/'launch.json',{'argv':self.args})
        (self.state/'ids').write_text(self.worker)
        (self.state/(self.worker+'.collected')).touch()
        # These handwritten markers must be ignored.
        (self.state/(self.worker+'.deleted')).touch()
        b.save(self.state/(self.worker+'.ttl-expired.json'),{'confirmed_absent':True})
        self.expiry='2026-10-26T17:29:28.066Z'
        (self.state/'new.1').write_text(json.dumps({'id':self.worker,'archiveAfter':self.expiry})+'\n')
        ready=self.old/'results/spend'/('launch-'+self.worker+'.readiness.json');ready.parent.mkdir(parents=True)
        b.save(ready,dict(outcome='ready',worker_id=self.worker,observed={'id':self.worker,'archiveAfter':self.expiry}))
        (self.old/'sealed').mkdir();self.archive=self.old/'sealed'/(self.case+'.checkpoint.tar.gz.age')
        self.archive.write_bytes(b'synthetic newest ciphertext')
        self.card=dict(case=self.case,status='stopped',sha256=b.sha(self.archive),
            r2_object='vm/'+self.worker+'/checkpoint.tar.gz.age',recovery_config=dict(rounds=10,case_budget=70),
            case_budget=dict(limit_usd=70),founder_ruling={'retained':'exact'},
            continuation_budget=dict(calls=1528,cost=1,list_cost_usd=51.28,events=[]))
        b.save(self.old/'sealed'/(self.case+'.scorecard.json'),self.card)
        b.save(self.old/'vm-current-sha256.json',{})
        b.save(self.old/'policy.restore.json',dict(root=str(self.old),jobs={'fixture':dict(case=self.case,args=self.args,max_calls=2000)}))
        for name in ('founder-run.py','start-in-terminal.sh','sync-to-vm.py','sync-to-vm.sh'):
            (self.old/name).write_text("# synthetic public helper\n")

    def query(self,args,**kw):
        value={'code':'not_found','status':404} if args[1]=='info' else {'pageInfo':{'hasMore':False},'sandboxes':[]}
        return subprocess.CompletedProcess(args,1 if args[1]=='info' else 0,json.dumps(value),'')

    def test_ttl_requires_provider_expiry_absence_and_exact_collected_generation(self):
        proof=b.retirement(self.old,self.case,self.card,self.archive,query=self.query,now=1793100000)
        self.assertEqual(proof['kind'],'ttl_expiry');self.assertIsNone(proof['deletion_receipt'])
        self.assertEqual(proof['generation'],b.sha(self.archive))
        with self.assertRaisesRegex(ValueError,'not elapsed'):
            b.retirement(self.old,self.case,self.card,self.archive,query=self.query,now=0)
        def live(args,**kw):return subprocess.CompletedProcess(args,0,'{"id":"bx_synthetic"}','')
        with self.assertRaisesRegex(ValueError,'absence'):
            b.retirement(self.old,self.case,self.card,self.archive,query=live,now=1793100000)
        self.archive.write_bytes(b'stale ciphertext')
        with self.assertRaisesRegex(ValueError,'generation'):
            b.retirement(self.old,self.case,self.card,self.archive,query=self.query,now=1793100000)

    def test_successor_pins_new_source_and_keeps_newest_ciphertext_ledger_ruling_counters(self):
        release=self.home/'release';(release/'source/factory').mkdir(parents=True)
        files={}
        for name in b.REQUIRED:
            p=release/'source'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('openrouter/deepseek/deepseek-v4.1-flash\n')
            files[name]=b.sha(p)
        copy_host_sources(release/'source')
        b.save(release/'source-manifest.json',{'files':files})
        adapter=self.home/'adapter.py';adapter.write_text('# qualified synthetic adapter')
        rehearsal=self.home/'rehearsal.json'
        proof=dict(status='PASS',source_manifest_sha256=b.sha(release/'source-manifest.json'),
            completed=['G2','G16','G10','G17','G11','G12','G10_interrupt_restore'],real_cases_used=False)
        b.save(rehearsal,proof)
        target=self.home/'successor'
        with patch.object(b,'SOURCE_ROOT',release/'source'), patch.object(b.runpy,'run_path',return_value={'load':lambda p:(None,None,files)}):
            b.stage(self.old,target,release,adapter,b.sha(adapter),rehearsal)
        job=b.read(target/'policy.restore.pending.json')['jobs']['fixture']
        self.assertEqual(job['max_calls'],5000)
        for flag,value in (('--max-total-calls','5000'),('--ttl-hours','16'),('--rounds','10'),('--case-budget','70')):
            self.assertEqual(job['args'][job['args'].index(flag)+1],value)
        self.assertNotIn('--founder-ruling-sha256',job['args'])
        self.assertEqual((target/'sync-to-vm.py').read_bytes(), (ROOT/'factory/restore_sync.py').read_bytes())
        self.assertFalse((target/'sealed').exists())
        b.verify_source(target)
        original=b.retirement
        with patch.object(b,'retirement',side_effect=lambda *args:original(*args,query=self.query,now=1793100000)), \
             patch.object(key_holder,'policy_load',return_value={'jobs':{'fixture':job}}), \
             patch.object(key_holder,'current_generation',return_value=self.card['sha256']):
            b.finalize(target)
        self.assertEqual(b.read(target/'input-scorecard.json'),self.card)
        self.assertEqual(b.read(target/'corrected-continuation-budget.json'),self.card['continuation_budget'])
        self.assertEqual(b.sha(target/'sealed'/self.archive.name),b.sha(self.archive))
        self.assertEqual(b.read(target/'retirement.json')['kind'],'ttl_expiry')
        self.assertFalse((target/'control-home').exists())
        (target/'factory/model_runtime.py').write_text('stale route')
        with self.assertRaisesRegex(ValueError,'changed'):b.verify_source(target)

    def test_staged_bundle_contains_every_restore_launcher_input(self):
        release=self.home/'release';source=release/'source';source.mkdir(parents=True)
        # Exercise the real launcher/collector/guard references, not a manually
        # maintained readiness-only list. Missing host files are staged by sweep.
        names=set(b.REQUIRED)|{'factory/launch.sh','factory/collect.sh','bin/boat-launch-guards.sh'}
        for name in names:
            p=source/name;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes((ROOT/name).read_bytes())
        for name in b.launcher_files(ROOT):
            p=source/name
            if not p.exists() and (ROOT/name).is_file():
                p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/name).read_bytes())
        files={name:b.sha(source/name) for name in names}
        copy_host_sources(release/'source')
        b.save(release/'source-manifest.json',{'files':files})
        adapter=self.home/'adapter.py';adapter.write_text('# synthetic pinned adapter')
        proof=self.home/'rehearsal.json'
        b.save(proof,dict(status='PASS',source_manifest_sha256=b.sha(release/'source-manifest.json'),
            completed=['G2','G16','G10','G17','G11','G12','G10_interrupt_restore'],real_cases_used=False))
        target=self.home/'successor'
        with patch.object(b,'SOURCE_ROOT',source), patch.object(b.runpy,'run_path',return_value={'load':lambda p:(None,None,files)}):
            b.stage(self.old,target,release,adapter,b.sha(adapter),proof)
        self.assertEqual(b.sha(target/'tools/boat_readiness.py'),b.sha(ROOT/'tools/boat_readiness.py'))
        b.verify_source(target)
        for name in sorted(b.launcher_files(target)):
            p=target/name;data=p.read_bytes();p.unlink()
            with self.subTest(missing=name), self.assertRaisesRegex(ValueError,'restore launcher input'):
                b.verify_source(target)
            p.write_bytes(data)

    def test_restaging_refuses_incomplete_or_different_release_rehearsal(self):
        # Rehearsal is mandatory before any real source/ciphertext can be staged.
        p=self.home/'adapter';p.write_text('public')
        release=self.home/'release';release.mkdir();b.save(release/'source-manifest.json',{})
        rehearsal=self.home/'rehearsal';b.save(rehearsal,dict(status='PASS',completed=['G16']))
        with patch.object(b,'REQUIRED',()), patch.object(b.runpy,'run_path',return_value={'load':lambda p:(None,None,{})}), \
             self.assertRaisesRegex(ValueError,'rehearsal'):
            b.stage(self.old,self.home/'new',release,p,b.sha(p),rehearsal)
        self.assertFalse((self.home/'new').exists())


if __name__=='__main__':unittest.main()
