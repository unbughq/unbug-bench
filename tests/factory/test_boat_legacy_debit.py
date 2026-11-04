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
