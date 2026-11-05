"""Exact founder budget decision; real saved historical public metadata.
Initial mutation I/O is AUTHORED here: raw exact historical spend bytes live only
on root's control VM, never reconstructed or accessed by this offline test.
"""
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'factory'),str(ROOT/'bin')]
import boat_lifecycle as life
import deployment_inventory as inventory

SAVED=json.loads((ROOT/'tests/factory/fixtures/boat-retirement/legacy-spend-metadata.json').read_text())['legacy_spend_metadata'][0]


class BudgetDebitTests(unittest.TestCase):
    def test_runtime_decision_copy_is_verbatim_original_founder_record(self):
        self.assertEqual((ROOT/life.SMOKE_DECISION_FILE).read_bytes(),(ROOT/'tests/factory/fixtures/retained-evidence/smoke-bx-bykfqbyn-budget-decision-20261104.json').read_bytes())
        with patch.object(life,'sha256',return_value='wrong'), self.assertRaises(ValueError):life.legacy_decision('smoke')
        self.assertEqual((ROOT/life.LEGACY_DECISION_FILE).read_bytes(),
                         (ROOT/'tests/factory/fixtures/retained-evidence/legacy-bx-z4wktrbn-budget-decision-20261104.json').read_bytes())
        self.assertEqual(life.sha256(ROOT/life.LEGACY_DECISION_FILE),life.LEGACY_DECISION_SHA)

    def test_smoke_scope_preserves_legacy_and_mixed_budget(self):
        decision=life.legacy_decision('smoke')
        original=dict(usd='0.036',expires_at=1793790083.3712797,status='reserved',
            state_path=decision['state_path'],vms=1,ttl_seconds=3600,max_spend_usd='5')
        old=life.approved_budget_row(deepcopy(SAVED['ledger_row']))
        new=life.approved_budget_row(original,'smoke')
        self.assertEqual(new['budget_debit']['original_row'],original)
        self.assertNotIn('finished_at',new); self.assertIsNone(new['actual_spend_usd'])
        self.assertEqual(life.budget_amount(old,SAVED['ledger_key'])+life.budget_amount(new,decision['spend_path']),Decimal('.072'))
        self.assertEqual(Decimal(5)-Decimal('.072'),Decimal('4.928'))
        for field,value in [('status','finished'),('vms',True),('ttl_seconds',7200),('max_spend_usd','6'),('expires_at',0),('state_path','foreign')]:
            bad=deepcopy(original);bad[field]=value
            with self.assertRaises(ValueError): life.approved_budget_row(bad,'smoke')
        with self.assertRaises(ValueError): life.legacy_decision('arbitrary')

    def test_saved_metadata_permanent_debit_actual_stays_unknown_and_strict_scope(self):
        row=life.approved_budget_row(deepcopy(SAVED['ledger_row'])); key=SAVED['ledger_key']
        self.assertEqual(row['budget_debit']['original_row'],SAVED['ledger_row'])
        self.assertIsNone(row['actual_spend_usd'])
        self.assertEqual(life.budget_amount(row,key),Decimal('.036'))
        self.assertEqual(Decimal('5')-life.budget_amount(row,key),Decimal('4.964'))
        with self.assertRaises(ValueError): life.budget_amount(row,key+'.other')
        for mutate in (lambda r:r.update(actual_spend_usd='.036'),
                       lambda r:r['budget_debit'].update(budget_debit_usd='0'),
                       lambda r:r['budget_debit'].update(worker_id='other'),
                       lambda r:r['budget_debit'].update(spend_sha256='a'*64),
                       lambda r:r['budget_debit'].update(budget_cap_usd='100'),
                       lambda r:r['budget_debit'].update(extra=True),
                       lambda r:r['budget_debit']['original_row'].update(usd='.035')):
            bad=deepcopy(row); mutate(bad)
            with self.assertRaises(ValueError): life.budget_amount(bad,key)
        with self.assertRaises(ValueError): life.approved_budget_row(dict(SAVED['ledger_row'],state_path='foreign'))

    def test_initial_application_requires_exact_raw_hash_and_retained_deletion(self):
        decision=life.legacy_decision(); row=deepcopy(SAVED['ledger_row'])
        ledger=dict(version=1,reservations={decision['spend_path']:row})
        # The absent canonical file is a refusal, never inferred from metadata SHA.
        with patch.object(life,'sha256',return_value='wrong'), self.assertRaises(ValueError): life.record_approved_debit(ledger)
        self.assertEqual(ledger['reservations'][decision['spend_path']],row)

    def test_successful_initial_debit_and_wrong_retained_deletion_authored_io(self):
        selector=getattr(self,'selector','legacy')
        decision=life.legacy_decision(selector); original_regular=life.regular; original_sha=life.sha256
        original_row=deepcopy(SAVED['ledger_row']) if selector=='legacy' else dict(usd='0.036',expires_at=1793790083.3712797,status='reserved',state_path=decision['state_path'],vms=1,ttl_seconds=3600,max_spend_usd='5')
        resolve=Path.resolve; is_dir=Path.is_dir; iterdir=Path.iterdir
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve()
            spend=Path(decision['spend_path']); state=Path(decision['state_path'])
            # Map only the synthetic VM paths this test builds. The spend path shares
            # the /home/user/unbug-bench prefix with a checkout there, so a blanket
            # /home/user mapping would also capture the repository's own files.
            vm_roots=(spend,spend.with_suffix('.deletions'),state)
            def vm(path): return any(Path(path).is_relative_to(root) for root in vm_roots)
            def mapped(path):
                path=Path(path)
                return base/path.relative_to('/home/user') if vm(path) else path
            mapped(state).mkdir(parents=True); mapped(spend).parent.mkdir(parents=True)
            data=deepcopy(SAVED['spend_metadata'])
            if selector=='smoke': data.pop('finished_at',None)
            mapped(spend).write_text(json.dumps(data))
            (mapped(state)/'ids').write_text(decision['worker_id'])
            (mapped(state)/'new.1').write_text(json.dumps(dict(event='created',id=decision['worker_id'])))
            (mapped(state)/'monitor.sh').write_text('spend_file='+str(spend)+'\n')
            evidence=mapped(spend.with_suffix('.deletions')/decision['worker_id']); evidence.mkdir(parents=True)
            done=json.loads((ROOT/'tests/factory/fixtures/boat-retirement/legacy-budget-proposal.json').read_text())['retirement']
            if selector=='smoke': done.update(id=decision['deletion_operation_id'],targetId=decision['worker_id'],completedAt='2026-11-04T10:05:28.458Z')
            request=dict(done,status='pending',stage='pending',completedAt=None)
            (evidence/'deletion-request.json').write_text(json.dumps(request))
            (evidence/'deletion-completion.json').write_text(json.dumps(done))
            ledger=dict(version=1,reservations={str(spend):deepcopy(original_row)})
            # AUTHORED filesystem transport uses the real observed SHA at the digest
            # boundary; it is not a fabricated raw spend file claimed to hash to it.
            def digest(path):
                path=Path(path)
                if path==spend:return decision['spend_sha256']
                if selector=='smoke' and path.name in ('deletion-request.json','deletion-completion.json'):
                    return decision['deletion_request_sha256' if path.name=='deletion-request.json' else 'deletion_completion_sha256']
                return original_sha(path)
            with patch.object(life,'regular',side_effect=lambda path:original_regular(mapped(path))), patch.object(life,'sha256',side_effect=digest), patch.object(Path,'resolve',lambda path,*a,**k:path if vm(path) else resolve(path,*a,**k)), patch.object(Path,'is_dir',lambda path:is_dir(mapped(path))), patch.object(Path,'iterdir',lambda path:iterdir(mapped(path))):
                before={p:p.read_bytes() for p in base.rglob('*') if p.is_file()}
                bad=dict(done,id='wrong'); (evidence/'deletion-completion.json').write_text(json.dumps(bad))
                with self.assertRaises(ValueError): life.record_approved_debit(ledger,selector)
                self.assertEqual(ledger['reservations'][str(spend)],original_row)
                (evidence/'deletion-completion.json').write_text(json.dumps(done))
                if selector=='smoke':
                    with patch.object(life,'sha256',side_effect=lambda path:'0'*64 if Path(path).name=='deletion-completion.json' else digest(path)):
                        with self.assertRaises(ValueError): life.record_approved_debit(ledger,selector)
                    ids=mapped(state)/'ids'; ids.write_text('foreign')
                    with self.assertRaises(ValueError): life.record_approved_debit(ledger,selector)
                    ids.write_text(decision['worker_id'])
                    saved=mapped(spend).read_bytes(); bad=json.loads(saved);bad['ttl_seconds']=7200
                    mapped(spend).write_text(json.dumps(bad))
                    with self.assertRaises(ValueError): life.record_approved_debit(ledger,selector)
                    mapped(spend).write_bytes(saved)
                self.assertTrue(life.record_approved_debit(ledger,selector))
                self.assertFalse(life.record_approved_debit(ledger,selector))
                self.assertEqual(ledger['reservations'][str(spend)]['budget_debit']['original_row'],original_row)
                self.assertIsNone(ledger['reservations'][str(spend)]['actual_spend_usd'])
                self.assertEqual({p:p.read_bytes() for p in base.rglob('*') if p.is_file()},before)

    def test_smoke_initial_application_authored_transport(self):
        self.selector='smoke'
        self.test_successful_initial_debit_and_wrong_retained_deletion_authored_io()

    def test_accepted_debit_finish_settle_and_record_replays_write_nothing(self):
        decision=life.legacy_decision(); key=decision['spend_path']
        row=life.approved_budget_row(deepcopy(SAVED['ledger_row']))
        smoke=life.legacy_decision('smoke')
        bound=dict(usd='0.036',expires_at=1793790083.3712797,status='reserved',state_path=smoke['state_path'],vms=1,ttl_seconds=3600,max_spend_usd='5')
        ledger=dict(version=1,reservations={key:row,smoke['spend_path']:life.approved_budget_row(bound,'smoke')})
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp).resolve(); target=home/'boat-reservations.json'
            target.write_text(json.dumps(ledger)); before=target.read_bytes()
            env={**os.environ,'UNBUG_CONTROL_HOME':tmp,'UNBUG_CLOUD':'boat','BOAT_CMD':'/does/not/exist'}
            for args in (['--finish',key,'0',decision['state_path']+'/ids'],
                         ['--settle',key,decision['state_path']],['--record-approved-legacy-debit'],['--record-approved-smoke-debit'],['--finish',smoke['spend_path'],'0',smoke['state_path']+'/ids'],['--settle',smoke['spend_path'],smoke['state_path']]):
                result=subprocess.run([str(ROOT/'bin/boat-spend'),*args],env=env,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(target.read_bytes(),before)
            observed=inventory.scan_ledger(target,time.time())
            self.assertEqual(observed['state'],'ok')
            self.assertEqual(observed['settled_usd'],'0')
            self.assertEqual(observed['conservative_budget_debit_usd'],'0.072')
            # A raised caller cap cannot reset the decision's original $5 ceiling.
            edge=home/'edge'; edge.write_text('#!/bin/sh\necho \'{"limits":{"creditBalanceSeconds":100000000}}\'\n'); edge.chmod(0o755)
            env['BOAT_CMD']=str(edge)
            next_record=home/'new.json'
            for count,allowed in ((136,True),(137,False)):
                result=subprocess.run([str(ROOT/'bin/boat-spend'),'--check',str(count),'1','100',str(next_record)],env=env,capture_output=True,timeout=10)
                self.assertEqual(result.returncode==0,allowed,result.stderr)
                if allowed:
                    current=json.loads(target.read_text()); del current['reservations'][str(next_record)]
                    target.write_text(json.dumps(current)); next_record.unlink()
            self.assertIsNone(json.loads(target.read_text())['reservations'][key]['actual_spend_usd'])


if __name__=='__main__': unittest.main()
