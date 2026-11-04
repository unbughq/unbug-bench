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
        decision=life.legacy_decision(); original_regular=life.regular; original_sha=life.sha256
        resolve=Path.resolve; is_dir=Path.is_dir; iterdir=Path.iterdir
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve()
            def mapped(path):
                path=Path(path)
                return base/path.relative_to('/home/user') if path.is_relative_to('/home/user') else path
            spend=Path(decision['spend_path']); state=Path(decision['state_path'])
            mapped(state).mkdir(parents=True); mapped(spend).parent.mkdir(parents=True)
            mapped(spend).write_text(json.dumps(SAVED['spend_metadata']))
            (mapped(state)/'ids').write_text(decision['worker_id'])
            (mapped(state)/'new.1').write_text(json.dumps(dict(event='created',id=decision['worker_id'])))
            (mapped(state)/'monitor.sh').write_text('spend_file='+str(spend)+'\n')
            evidence=mapped(spend.with_suffix('.deletions')/decision['worker_id']); evidence.mkdir(parents=True)
            done=json.loads((ROOT/'tests/factory/fixtures/boat-retirement/legacy-budget-proposal.json').read_text())['retirement']
            request=dict(done,status='pending',stage='pending',completedAt=None)
            (evidence/'deletion-request.json').write_text(json.dumps(request))
            (evidence/'deletion-completion.json').write_text(json.dumps(done))
            ledger=dict(version=1,reservations={str(spend):deepcopy(SAVED['ledger_row'])})
            # AUTHORED filesystem transport uses the real observed SHA at the digest
            # boundary; it is not a fabricated raw spend file claimed to hash to it.
            def digest(path): return decision['spend_sha256'] if Path(path)==spend else original_sha(path)
            with patch.object(life,'regular',side_effect=lambda path:original_regular(mapped(path))), patch.object(life,'sha256',side_effect=digest), patch.object(Path,'resolve',lambda path,*a,**k:path if path.is_relative_to('/home/user') else resolve(path,*a,**k)), patch.object(Path,'is_dir',lambda path:is_dir(mapped(path))), patch.object(Path,'iterdir',lambda path:iterdir(mapped(path))):
                before={p:p.read_bytes() for p in base.rglob('*') if p.is_file()}
                bad=dict(done,id='wrong'); (evidence/'deletion-completion.json').write_text(json.dumps(bad))
                with self.assertRaises(ValueError): life.record_approved_debit(ledger)
                self.assertEqual(ledger['reservations'][str(spend)],SAVED['ledger_row'])
                (evidence/'deletion-completion.json').write_text(json.dumps(done))
                self.assertTrue(life.record_approved_debit(ledger))
                self.assertFalse(life.record_approved_debit(ledger))
                self.assertEqual(ledger['reservations'][str(spend)]['budget_debit']['original_row'],SAVED['ledger_row'])
                self.assertIsNone(ledger['reservations'][str(spend)]['actual_spend_usd'])
                self.assertEqual({p:p.read_bytes() for p in base.rglob('*') if p.is_file()},before)

    def test_accepted_debit_finish_settle_and_record_replays_write_nothing(self):
        decision=life.legacy_decision(); key=decision['spend_path']
        row=life.approved_budget_row(deepcopy(SAVED['ledger_row']))
        ledger=dict(version=1,reservations={key:row})
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp).resolve(); target=home/'boat-reservations.json'
            target.write_text(json.dumps(ledger)); before=target.read_bytes()
            env={**os.environ,'UNBUG_CONTROL_HOME':tmp,'UNBUG_CLOUD':'boat','BOAT_CMD':'/does/not/exist'}
            for args in (['--finish',key,'0',decision['state_path']+'/ids'],
                         ['--settle',key,decision['state_path']],['--record-approved-legacy-debit']):
                result=subprocess.run([str(ROOT/'bin/boat-spend'),*args],env=env,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(target.read_bytes(),before)
            observed=inventory.scan_ledger(target,time.time())
            self.assertEqual(observed['state'],'ok')
            self.assertEqual(observed['settled_usd'],'0')
            self.assertEqual(observed['conservative_budget_debit_usd'],'0.036')
            # A raised caller cap cannot reset the decision's original $5 ceiling.
            edge=home/'edge'; edge.write_text('#!/bin/sh\necho \'{"limits":{"creditBalanceSeconds":100000000}}\'\n'); edge.chmod(0o755)
            env['BOAT_CMD']=str(edge)
            next_record=home/'new.json'
            for count,allowed in ((137,True),(138,False)):
                result=subprocess.run([str(ROOT/'bin/boat-spend'),'--check',str(count),'1','100',str(next_record)],env=env,capture_output=True,timeout=10)
                self.assertEqual(result.returncode==0,allowed,result.stderr)
                if allowed:
                    current=json.loads(target.read_text()); del current['reservations'][str(next_record)]
                    target.write_text(json.dumps(current)); next_record.unlink()
            self.assertIsNone(json.loads(target.read_text())['reservations'][key]['actual_spend_usd'])


if __name__=='__main__': unittest.main()
