"""Actual public practice-5 refusal; temporary paths and mutations are authored."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'factory'),str(ROOT/'bin')]
import practice_cleanup as cleanup
from registry import atomic_json

class PredispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name);data=json.loads((ROOT/'tests/factory/fixtures/predispatch-refusal/public.json').read_text())
        self.op=data['operation'];self.directory=self.home/'batches'/self.op['authority']['batch'];self.directory.mkdir(parents=True)
        (self.home/'launches').mkdir();self.path=self.home/'launches'/self.op['launch_id']
        self.ledger=self.home/'boat-reservations.json';atomic_json(self.ledger,data['ledger']);(self.home/'boat-reservations.lock').touch()
        self.status=cleanup.location(self.home,self.op).with_suffix('.status.json');self.status.parent.mkdir();atomic_json(self.status,data['cleanup_status'])
        self.lock=self.directory/'operations'/(self.op['operation_id']+'.lock');self.lock.parent.mkdir();self.lock.touch()
        self.assertTrue(data['launch_absent']);self.assertTrue(all(v=='inactive' for v in data['services'].values()))

    def test_actual_refusal_certifies_without_changing_money_or_creating_launch(self):
        before=self.ledger.read_bytes(),self.status.read_bytes()
        proof=cleanup.preallocation_settlement(self.home,self.op)
        self.assertEqual(proof['operation_id'],self.op['operation_id'])
        self.assertEqual(set(proof['files']),{'cleanup'})
        self.assertFalse(self.path.exists())
        self.assertEqual(before,(self.ledger.read_bytes(),self.status.read_bytes()))
        self.assertEqual(proof,cleanup.preallocation_settlement(self.home,self.op))

    def test_any_launch_path_or_symlink_refuses(self):
        for kind in ('directory','file','dangling_symlink'):
            with self.subTest(kind=kind):
                if kind=='directory':self.path.mkdir()
                elif kind=='file':self.path.touch()
                else:self.path.symlink_to(self.home/'missing')
                try:
                    with self.assertRaises(ValueError):cleanup.preallocation_settlement(self.home,self.op)
                finally:
                    if kind=='directory':self.path.rmdir()
                    else:self.path.unlink()

    def test_wrong_terminal_or_operation_shape_refuses(self):
        for key,value in [('dispatch_started',0),('state','pending'),('incident',None),('launch',{}),('worker_id','bx-unexpected')]:
            with self.subTest(key=key):
                op=dict(self.op);op[key]=value
                with self.assertRaises(ValueError):cleanup.preallocation_settlement(self.home,op)
        original=self.status.read_bytes()
        for key,value in [('schema',True),('operation_id','foreign'),('state','waiting'),('settlement','settled'),('workers',['bx-unexpected']),('deadline',1),('settlement_attempted_at',1)]:
            with self.subTest(key=key):
                status=json.loads(original);status[key]=value;atomic_json(self.status,status)
                with self.assertRaises(ValueError):cleanup.preallocation_settlement(self.home,self.op)
                self.status.write_bytes(original)

    def test_missing_or_malformed_evidence_is_unknown(self):
        for p in (self.ledger,self.home/'boat-reservations.lock',self.status):
            with self.subTest(path=p.name):
                data=p.read_bytes();p.unlink()
                try:
                    with self.assertRaises((ValueError,OSError)):cleanup.preallocation_settlement(self.home,self.op)
                finally:p.write_bytes(data)
        self.ledger.write_text('{}')
        with self.assertRaises(ValueError):cleanup.preallocation_settlement(self.home,self.op)

    def test_even_settled_compute_reservation_for_this_path_refuses(self):
        data=json.loads(self.ledger.read_text())
        # Real settled no_creation row, relocated to the failed launch (AUTHORED mutation).
        row=next(deepcopy(r) for r in data['reservations'].values() if r.get('settlement',{}).get('basis')=='no_creation')
        row['state_path']=str(self.path.resolve());row['settlement']['state_path']=str(self.path.resolve())
        data['reservations'][str(self.home/'foreign-spend.json')]=row;atomic_json(self.ledger,data)
        with self.assertRaises(ValueError):cleanup.preallocation_settlement(self.home,self.op)

    def test_inactive_successor_preserves_exact_source_and_caps(self):
        import hashlib
        import practice
        from carry_over import digest
        previous=ROOT/'factory/batches/b-plumbing-practice-5.json'
        record=json.loads((ROOT/'factory/batches/b-plumbing-practice-6.json').read_text())
        prior=json.loads(previous.read_text())
        snapshot=json.loads((ROOT/'tests/factory/fixtures/predispatch-refusal/certified-snapshot.json').read_text())
        self.assertEqual(record,practice.EXPECTED)
        self.assertEqual(record['carry_from']['manifest_json'],previous.read_text())
        self.assertEqual(record['carry_from']['snapshot_sha256'],digest(snapshot))
        self.assertEqual(hashlib.sha256(previous.read_bytes()).hexdigest(),snapshot['manifest_sha256'])
        for key in ('money_limit_usd','batch_deadline','practice_admission','replacement_policy'):
            self.assertEqual(record[key],prior[key])
        self.assertEqual(record['jobs']['smoke'],prior['jobs']['smoke'])
        self.assertEqual(record['jobs']['practice']['args'],prior['jobs']['practice']['args'])
        self.assertEqual((ROOT/'factory/batches/b-plumbing-practice-6.decisions.json').read_bytes(),
                         (ROOT/'factory/batches/b-plumbing-practice-5.decisions.json').read_bytes())

    def test_other_process_lock_contention_refuses(self):
        for p in (self.lock,self.home/'boat-reservations.lock'):
            child=subprocess.Popen([sys.executable,'-c','import fcntl,sys;f=open(sys.argv[1],"r+");fcntl.flock(f,fcntl.LOCK_EX);print("ready",flush=True);sys.stdin.read()',str(p)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(),'ready')
                with self.assertRaises((ValueError,OSError)):cleanup.preallocation_settlement(self.home,self.op)
            finally:child.communicate(timeout=3)

if __name__=='__main__':unittest.main()
