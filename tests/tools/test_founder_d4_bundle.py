"""D4 is a narrow host staging waiver; qualified worker bytes stay unchanged."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_late_restore_bundle as fixtures
import founder_decisions as decisions
import restore_bundle as b


class D4Tests(unittest.TestCase):
    setUp=fixtures.BundleTests.setUp

    def prepare(self):
        release=self.home/'release';current=self.home/'current';files={}
        for name in b.REQUIRED:
            for root in (release/'source',current):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_text('# qualified original\n')
            files[name]=b.sha(release/'source'/name)
        for name in ('restore_bundle.py','founder_decisions.py'):
            (current/'factory'/name).write_bytes((fixtures.ROOT/'factory'/name).read_bytes())
        fixtures.copy_host_sources(current)
        b.save(release/'source-manifest.json',{'files':files})
        self.pin=b.sha(release/'source-manifest.json')
        adapter=self.home/'adapter.py';adapter.write_text('# pinned adapter')
        proof=self.home/'partial.json'
        b.save(proof,dict(status='PARTIAL',source_manifest_sha256=self.pin,real_cases_used=False,
            completed=['G2','G3','G4','G5','G15'],not_reached=['G10','G16','G17','G11','G12']))
        self.record=dict(decision='D4',authority='founder-2026-10-29',scope='restage_real_cases',
            waive_rehearsal_pass=True,source_manifest_sha256=self.pin,rehearsal_sha256=b.sha(proof),
            cases=decisions.CASES,reason='Founder stops rehearsal after eleven attempts; launch real cases now')
        self.waiver=self.home/'founder-decisions.json';self.write_waiver()
        self.enterContext(patch.object(decisions,'D4_RELEASE_PIN',self.pin))
        self.enterContext(patch.object(b,'SOURCE_ROOT',current))
        self.enterContext(patch.object(b.runpy,'run_path',return_value={'load':lambda p:(None,None,files)}))
        return (self.old,self.home/'successor',release,adapter,b.sha(adapter),proof)

    def write_waiver(self):
        digest=hashlib.sha256(json.dumps(self.record,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        b.save(self.waiver,{'D4':{'record':self.record,'record_sha256':digest}})

    def test_waiver_exact_pin_stages_original_worker_and_frozen_host_decision(self):
        args=self.prepare();b.stage(*args,founder_decisions=self.waiver)
        target=args[1];b.verify_source(target)
        self.assertEqual(b.read(target/'source-binding.json')['rehearsal_authorization'],'D4')
        self.assertEqual(b.read(target/'rehearsal.json')['status'],'PARTIAL')
        self.assertEqual((target/'factory/restore_bundle.py').read_text(),'# qualified original\n')
        self.assertEqual(b.sha(target/'host-tools/restore_bundle.py'),b.sha(b.SOURCE_ROOT/'factory/restore_bundle.py'))
        self.assertIn('host-tools',(target/'validate-offline.py').read_text())
        (target/'founder-decisions.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):b.verify_source(target)

    def test_waiver_wrong_pin_refuses_even_with_valid_record_digest(self):
        args=self.prepare();self.record['source_manifest_sha256']='0'*64;self.write_waiver()
        with self.assertRaisesRegex(ValueError,'exact.*PIN'):b.stage(*args,founder_decisions=self.waiver)
        self.assertFalse(args[1].exists())

    def test_different_release_cannot_rebind_waiver(self):
        args=self.prepare()
        with patch.object(decisions,'D4_RELEASE_PIN','f'*64), self.assertRaisesRegex(ValueError,'exact.*PIN'):
            b.stage(*args,founder_decisions=self.waiver)
        self.assertFalse(args[1].exists())

    def test_no_waiver_no_pass_refuses(self):
        args=self.prepare()
        # Restore host files too, so this tests the original rehearsal gate itself.
        for name in ('restore_bundle.py','founder_decisions.py'):
            (b.SOURCE_ROOT/'factory'/name).write_text('# qualified original\n')
        with self.assertRaisesRegex(ValueError,'rehearsal'):b.stage(*args)
        self.assertFalse(args[1].exists())

    def test_other_source_drift_still_refuses_under_d4(self):
        args=self.prepare();(b.SOURCE_ROOT/'factory/model_runtime.py').write_text('unqualified change')
        with self.assertRaisesRegex(ValueError,'exact current'):b.stage(*args,founder_decisions=self.waiver)
        self.assertFalse(args[1].exists())

    def test_wrong_evidence_digest_refuses(self):
        args=self.prepare();self.record['rehearsal_sha256']='0'*64;self.write_waiver()
        with self.assertRaisesRegex(ValueError,'evidence'):b.stage(*args,founder_decisions=self.waiver)
        self.assertFalse(args[1].exists())


if __name__=='__main__':unittest.main()
