"""Real public -4 failure/release; temp path relocation and target host binding are AUTHORED."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import batch
import batch_holder as holder
import batch_money as money
import batch_transfer as transfer
import practice_cleanup as cleanup
import practice
from carry_over import digest
from registry import atomic_json

FIXTURE = ROOT / 'tests/factory/fixtures/preallocation-recovery'
OLD = ROOT / 'tests/factory/fixtures/practice3-transfer'


class PreallocationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve(); self.home = self.root / 'home'; self.home.mkdir()
        data = json.loads((FIXTURE / 'public.json').read_text())
        supplement = json.loads((FIXTURE / 'supplement.json').read_text())
        self.record = json.loads(data['files']['manifest.json'])
        self.policy = json.loads(data['files']['policy.json'])
        batch.verify(FIXTURE / 'release', self.policy['batch']['sha256'])
        self.policy['batch']['release'] = str(FIXTURE / 'release')  # AUTHORED location only.
        self.directory = self.home / 'batches' / self.record['id']; self.directory.mkdir(parents=True)
        for name, raw in data['files'].items():
            if name.startswith('batch/'): (self.directory / name.removeprefix('batch/')).write_text(raw)
        self.ops = json.loads(data['files']['batch/reservations.json'])['operations']
        self.identity, self.op = next(iter(self.ops.items()))
        self.launch = self.home / 'launches' / self.op['launch_id']; self.launch.mkdir(parents=True)
        self.spend = self.root / 'spend.json'
        for name, raw in {**data['files'], **supplement['files']}.items():
            if name.startswith('launch/'):
                if name == 'launch/monitor.sh':
                    raw = '\n'.join('spend_file='+str(self.spend) if l.startswith('spend_file=') else l for l in raw.splitlines())+'\n'
                (self.launch / name.removeprefix('launch/')).write_text(raw)
        spend = json.loads(data['files']['spend.json']); spend['settlement']['state_path'] = str(self.launch)
        atomic_json(self.spend, spend)
        ledger = json.loads(supplement['files']['ledger.json'])
        old_spend, row = next(iter(data['compute_reservations'].items())); row = deepcopy(row)
        row['state_path'] = row['settlement']['state_path'] = str(self.launch)
        ledger['reservations'].pop(old_spend); ledger['reservations'][str(self.spend)] = row
        self.ledger = self.home / 'boat-reservations.json'; atomic_json(self.ledger, ledger)
        (self.home / 'boat-reservations.lock').touch()
        operation_dir = self.directory / 'operations'; operation_dir.mkdir()
        (operation_dir / (self.identity+'.lock')).touch()  # AUTHORED unlocked copy of the operation lock.
        target = cleanup.location(self.home,self.op).with_suffix('.status.json');target.parent.mkdir()
        target.write_text(data['files']['cleanup/status.json'])
        # Exact predecessor journals/generation; only their physical paths are relocated.
        retained = json.loads((OLD / 'source-public.json').read_text()); self.parent_record = json.loads(retained['manifest_json'])
        self.parent = self.home / 'batches' / self.parent_record['id']; self.parent.mkdir()
        snap = retained['snapshot']
        atomic_json(self.parent/'money.json',snap['money'])
        atomic_json(self.parent/'reservations.json',dict(schema=1,batch=snap['batch'],manifest_sha256=snap['manifest_sha256'],operations=snap['operations']))
        collected=json.loads((OLD/'collection-public.json').read_text());atomic_json(self.parent/'journal.json',collected['journal'])
        (self.parent/'export.json').write_text(data['files']['batch/import.json'])
        self.generation=self.record['carry_from']['jobs']['smoke']['generation'];self.case=self.op['case']
        gen=self.parent/'generations'/self.case/self.generation;gen.mkdir(parents=True)
        for name in collected['generation_manifest']['files']:shutil.copy2(OLD/name,gen/name)
        atomic_json(gen/'manifest.json',collected['generation_manifest'])
        publication=json.loads((OLD/'publication-public.json').read_text())
        for folder,name,value in [('current',self.case,publication['current']),('outbox',publication['outbox']['operation_id'],publication['outbox'])]:
            (self.parent/folder).mkdir();atomic_json(self.parent/folder/(name+'.json'),value)

    def test_actual_preallocation_failure_is_certified_without_changing_records(self):
        before=self.ledger.read_bytes(),(self.directory/'reservations.json').read_bytes()
        snap=transfer.snapshot(self.directory,self.record,self.policy)
        proof=snap['preallocation_settlements'][self.identity]
        self.assertEqual(proof['operation_id'],self.identity)
        self.assertEqual(snap['operations'][self.identity]['incident'],'preflight_refused')
        self.assertEqual(snap['money']['jobs']['smoke']['held_usd'],'0.010000000')
        self.assertEqual(before,(self.ledger.read_bytes(),(self.directory/'reservations.json').read_bytes()))

    def test_mutated_creation_or_settlement_refuses_certificate(self):
        original=self.ledger.read_bytes()
        for change in ['created','pending','ids','missing_complete','nonzero','unknown','missing_ledger','foreign_envelope']:
            with self.subTest(change=change):
                if change in ('created','pending'):(self.launch/('new.1'+('.pending' if change=='pending' else ''))).write_text('{}')
                elif change=='ids':(self.launch/'ids').write_text('bx-not-empty')
                elif change=='missing_complete':(self.launch/'complete').unlink()
                elif change=='missing_ledger':self.ledger.unlink()
                else:
                    d=json.loads(original);row=d['reservations'][str(self.spend)]
                    if change=='nonzero':row['actual_spend_usd']='0.01'
                    elif change=='unknown':row['status']='reserved'
                    elif change=='foreign_envelope':row['ttl_seconds']=7200
                    atomic_json(self.ledger,d)
                with self.assertRaises((ValueError,OSError)):
                    transfer.snapshot(self.directory,self.record,self.policy)
                for p in self.launch.glob('new.*'):p.unlink()
                (self.launch/'ids').write_text('');(self.launch/'complete').touch();self.ledger.write_bytes(original)


    def test_foreign_launch_cleanup_and_incomplete_proofs_refuse(self):
        status_path=cleanup.location(self.home,self.op).with_suffix('.status.json')
        cases=[(self.launch/'launch.json',lambda d:d['argv'].append('--foreign')),
               (status_path,lambda d:d.update(operation_id='foreign')),
               (status_path,lambda d:d.update(state='waiting')),
               (status_path,lambda d:d.update(schema=True)),
               (self.spend,lambda d:d.update(ids=['bx-unexpected'])),
               (self.spend,lambda d:d.update(vms=True)),
               (self.spend,lambda d:d.update(actual_spend_usd=1))]
        for path,mutate in cases:
            with self.subTest(path=path.name,mutation=cases.index((path,mutate))):
                original=path.read_bytes();data=json.loads(original);mutate(data);atomic_json(path,data)
                try:
                    with self.assertRaises((ValueError,OSError)):transfer.snapshot(self.directory,self.record,self.policy)
                finally:path.write_bytes(original)
        for path in [self.launch/'spend-finished',self.launch/'ids',status_path]:
            with self.subTest(missing=path.name):
                original=path.read_bytes();path.unlink()
                try:
                    with self.assertRaises((ValueError,OSError)):transfer.snapshot(self.directory,self.record,self.policy)
                finally:path.write_bytes(original)

    def test_inactive_successor_pins_observed_failure_and_preserves_limits(self):
        record=json.loads((ROOT/'factory/batches/b-plumbing-practice-5.json').read_text())
        observed=json.loads((FIXTURE/'certified-snapshot.json').read_text())
        # The retained -5 profile remains authenticated by the actual -5 snapshot.
        snap5=json.loads((ROOT/'tests/factory/fixtures/predispatch-refusal/certified-snapshot.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT/'factory/batches/b-plumbing-practice-5.json').read_bytes()).hexdigest(),snap5['manifest_sha256'])
        self.assertEqual(record['carry_from']['manifest_json'],json.loads((FIXTURE/'public.json').read_text())['files']['manifest.json'])
        self.assertEqual(record['carry_from']['snapshot_sha256'],digest(observed))
        self.assertEqual(record['money_limit_usd'],self.record['money_limit_usd'])
        self.assertEqual(record['batch_deadline'],self.record['batch_deadline'])
        self.assertEqual(record['practice_admission'],self.record['practice_admission'])
        self.assertEqual(record['jobs']['smoke'],self.record['jobs']['smoke'])
        self.assertEqual(record['jobs']['practice']['args'],self.record['jobs']['practice']['args'])
        self.assertEqual((ROOT/'factory/batches/b-plumbing-practice-5.decisions.json').read_bytes(),
                         (ROOT/'factory/batches/b-plumbing-practice-4.decisions.json').read_bytes())
        for value in ('b-plumbing-practice-4','b-plumbing-practice-3'):
            with patch.dict(os.environ,UNBUG_PRACTICE_BATCH=value):
                self.assertFalse(practice.active({'batch':{'id':'b-plumbing-practice-5'}},ROOT))

    def successor(self):
        self.target_root=self.root/'target-root';(self.target_root/'factory/batches').mkdir(parents=True)
        shutil.copy2(ROOT/'factory/control-recipient.txt',self.target_root/'factory/control-recipient.txt')
        self.next_record=deepcopy(self.record);self.next_record['id']='b-plumbing-practice-5'
        self.next_record['jobs']['practice']['case']='case-b-plumbing-practice-5-practice'
        self.next_record['carry_from']={'schema':1,'manifest_json':json.loads((FIXTURE/'public.json').read_text())['files']['manifest.json'],
            'policy':{'batch':deepcopy(self.policy['batch']),'jobs':deepcopy(self.policy['jobs'])},
            'snapshot_sha256':digest(transfer.snapshot(self.directory,self.record,self.policy)),
            'jobs':{'smoke':{'generation':self.generation,'case':self.case,'committed_total_usd':'0.010000000'}}}
        path=self.target_root/'factory/batches/b-plumbing-practice-5.json';path.write_text(json.dumps(self.next_record))
        self.target_release=self.root/'authored-target-release';self.target_release.mkdir()
        self.next_policy={'jobs':self.next_record['jobs'],'batch':{'id':self.next_record['id'],'release':str(self.target_release),
            'sha256':hashlib.sha256(b'AUTHORED target release binding').hexdigest(),'max_concurrency':1,
            'manifest_path':'factory/batches/b-plumbing-practice-5.json','manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}
        atomic_json(self.target_release/'source-manifest.json',{'files':{self.next_policy['batch']['manifest_path']:self.next_policy['batch']['manifest_sha256']}})
        real_verify=batch.verify;real_frozen=transfer.frozen_manifest
        def verify(directory,sha,root=None):
            if Path(directory)==self.target_release:
                self.assertEqual(sha,self.next_policy['batch']['sha256']);self.assertEqual(root,self.target_root)
            else:return real_verify(directory,sha,root)
        def frozen(record):
            # AUTHORED release-path relocation only; both retained source releases are verified by real code.
            relocated=deepcopy(record);old_policy=relocated['carry_from']['policy']
            old_policy['batch']['release']=str(FIXTURE/'release' if old_policy['batch']['id']==self.record['id'] else OLD/'release')
            return real_frozen(relocated)
        for obj,key,value in [(batch,'verify',verify),(transfer,'frozen_manifest',frozen)]:
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)
        p=patch('time.time',return_value=1793815000);p.start();self.addCleanup(p.stop)

    def test_carry_replay_returns_original_ancestor_and_keeps_all_debits(self):
        self.successor();before=self.ledger.read_bytes(),(self.directory/'reservations.json').read_bytes(),(self.parent/'export.json').read_bytes()
        transfer.prepare(self.next_policy,self.target_root,self.home)
        ack,entry,card,path=transfer.source(self.home,self.next_record,'smoke',self.generation)
        self.assertEqual(path,self.parent/'generations'/self.case/self.generation)
        self.assertEqual(hashlib.sha256((path/(self.case+'.checkpoint.tar.gz.age')).read_bytes()).hexdigest(),self.generation)
        target=self.home/'batches'/self.next_record['id'];receipt=(target/'import.json').read_bytes()
        row=money.load_locked(target,self.next_record,self.next_policy['batch']['manifest_sha256'])['jobs']['smoke']
        self.assertEqual((row['held_usd'],row['previous']['total_usd']),('0.010000000','0.000000000'))
        transfer.prepare(self.next_policy,self.target_root,self.home)
        self.assertEqual((target/'import.json').read_bytes(),receipt)
        self.assertEqual(before,(self.ledger.read_bytes(),(self.directory/'reservations.json').read_bytes(),(self.parent/'export.json').read_bytes()))

    def test_nested_import_binds_the_original_producer_release(self):
        self.successor()
        # AUTHORED activation only; transfer, reservation, source and bind are real.
        with patch.object(holder, 'HOLDER_ENABLED', True), patch.object(practice, 'EXPECTED', self.next_record):
            op = holder.reserve(self.next_policy, self.target_root, self.home, 'smoke', self.generation)
            job = batch.bind(self.next_policy, 'smoke', self.generation, self.target_root,
                             home=self.home, operation=op['operation_id'])
        self.assertIn('--restore', job['args'])
        self.assertEqual(job['args'][job['args'].index('--checkpoint-sha256') + 1], self.generation)
        self.assertEqual(job['args'][job['args'].index('--batch-sha256') + 1],
                         self.next_policy['batch']['sha256'])
        # A different producing release cannot be asserted by editing the public card.
        path = self.parent / 'generations' / self.case / self.generation / (self.case + '.scorecard.json')
        card = json.loads(path.read_text()); card['batch_release_sha256'] = self.policy['batch']['sha256']
        atomic_json(path, card)
        with patch.object(holder, 'HOLDER_ENABLED', True), self.assertRaises(ValueError):
            batch.bind(self.next_policy, 'smoke', self.generation, self.target_root,
                       home=self.home, operation=op['operation_id'])

    def test_never_dispatched_import_carries_again_then_reserves_and_binds(self):
        self.successor()
        with patch.object(holder, 'HOLDER_ENABLED', True), patch.object(practice, 'EXPECTED', self.next_record):
            op=holder.reserve(self.next_policy,self.target_root,self.home,'smoke',self.generation)
        target=self.home/'batches'/self.next_record['id']
        with money.locked(self.home,self.next_record['id']):
            ops=holder._operations(target,self.next_record,self.next_policy)
            # AUTHORED replay of retained -5's exact never-dispatched failure mode.
            ops[op['operation_id']].update(state='failed',incident='preflight_refused',dispatch_exit=1)
            holder._save(target,self.next_record,self.next_policy,ops)
        status=json.loads((ROOT/'tests/factory/fixtures/predispatch-refusal/public.json').read_text())['cleanup_status']
        status['operation_id']=op['operation_id'];path=cleanup.location(self.home,op).with_suffix('.status.json');path.parent.mkdir();atomic_json(path,status)
        source_snapshot=transfer.snapshot(target,self.next_record,self.next_policy)
        root6=self.root/'target6';(root6/'factory/batches').mkdir(parents=True)
        shutil.copy2(ROOT/'factory/control-recipient.txt',root6/'factory/control-recipient.txt')
        record6=deepcopy(self.next_record);record6['id']='b-plumbing-practice-6'
        record6['jobs']['practice']['case']='case-b-plumbing-practice-6-practice'
        record6['carry_from']={'schema':1,'manifest_json':(self.target_root/self.next_policy['batch']['manifest_path']).read_text(),
            'policy':{'batch':deepcopy(self.next_policy['batch']),'jobs':deepcopy(self.next_policy['jobs'])},
            'snapshot_sha256':digest(source_snapshot),'jobs':deepcopy(self.next_record['carry_from']['jobs'])}
        relative='factory/batches/b-plumbing-practice-6.json';atomic_json(root6/relative,record6)
        release6=self.root/'authored-release6';release6.mkdir()
        policy6={'jobs':record6['jobs'],'batch':dict(self.next_policy['batch'],id=record6['id'],release=str(release6),
            sha256=hashlib.sha256(b'AUTHORED target6 release').hexdigest(),manifest_path=relative,
            manifest_sha256=hashlib.sha256((root6/relative).read_bytes()).hexdigest())}
        atomic_json(release6/'source-manifest.json',{'files':{relative:policy6['batch']['manifest_sha256']}})
        prior_verify=batch.verify;prior_frozen=transfer.frozen_manifest
        def verify(directory,sha,root=None):
            if Path(directory)==release6:
                self.assertEqual((sha,root),(policy6['batch']['sha256'],root6))
            else:return prior_verify(directory,sha,root)
        def frozen(record):
            if record['id']==record6['id']:
                # AUTHORED target5 host/release binding; original -3/-4 remain real verified artifacts.
                self.assertEqual(record['carry_from']['manifest_json'],(self.target_root/self.next_policy['batch']['manifest_path']).read_text())
                self.assertEqual(record['carry_from']['policy'],record6['carry_from']['policy'])
                return self.next_policy,self.next_record
            return prior_frozen(record)
        before=self.ledger.read_bytes(),(target/'reservations.json').read_bytes()
        with patch.object(batch,'verify',verify),patch.object(transfer,'frozen_manifest',frozen),patch.object(holder,'HOLDER_ENABLED',True),patch.object(practice,'EXPECTED',record6):
            transfer.prepare(policy6,root6,self.home);transfer.prepare(policy6,root6,self.home)
            next_op=holder.reserve(policy6,root6,self.home,'smoke',self.generation)
            job=batch.bind(policy6,'smoke',self.generation,root6,home=self.home,operation=next_op['operation_id'])
            _,_,_,source=transfer.source(self.home,record6,'smoke',self.generation)
        self.assertEqual(source,self.parent/'generations'/self.case/self.generation)
        self.assertEqual(hashlib.sha256((source/(self.case+'.checkpoint.tar.gz.age')).read_bytes()).hexdigest(),self.generation)
        self.assertEqual(job['args'][job['args'].index('--batch-sha256')+1],policy6['batch']['sha256'])
        self.assertEqual(before,(self.ledger.read_bytes(),(target/'reservations.json').read_bytes()))

    def test_existing_snapshot_without_certificates_keeps_its_original_digest(self):
        record=self.parent_record;policy=self.record['carry_from']['policy']
        snap=transfer.snapshot(self.parent,record,policy)
        self.assertNotIn('preallocation_settlements',snap)
        self.assertEqual(digest(snap),self.record['carry_from']['snapshot_sha256'])

    def test_advanced_imported_money_is_not_exported_as_unchanged(self):
        self.successor();path=self.directory/'money.json';state=json.loads(path.read_text())
        state['jobs']['smoke']['previous']['total_usd']='0.000000001';atomic_json(path,state)
        # The pinned source snapshot and unchanged imported-base predicates both fail closed.
        with self.assertRaises(ValueError):transfer.prepare(self.next_policy,self.target_root,self.home)
        self.assertFalse((self.directory/'export.json').exists())

    def test_source_rejects_ancestor_drift_and_cyclic_manifest_before_resolution(self):
        self.successor();transfer.prepare(self.next_policy,self.target_root,self.home)
        invalid=deepcopy(self.next_record);old=json.loads(invalid['carry_from']['manifest_json']);old['id']=invalid['id']
        invalid['carry_from']['manifest_json']=json.dumps(old)
        invalid['carry_from']['policy']['batch']['manifest_sha256']=hashlib.sha256(invalid['carry_from']['manifest_json'].encode()).hexdigest()
        with self.assertRaises(ValueError):transfer.source(self.home,invalid,'smoke',self.generation)
        path=self.parent/'money.json';data=json.loads(path.read_text());data['jobs']['smoke']['known_floor_usd']='0.000000001';atomic_json(path,data)
        with self.assertRaises(ValueError):transfer.source(self.home,self.next_record,'smoke',self.generation)

    def test_other_process_lock_contention_refuses_without_wait(self):
        import subprocess,time
        paths=[self.launch/'controller.lock',self.directory/'operations'/(self.identity+'.lock'),self.home/'boat-reservations.lock']
        for path in paths:
            with self.subTest(lock=path.name):
                child=subprocess.Popen([sys.executable,'-c',
                    'import fcntl,sys;f=open(sys.argv[1],"r+");fcntl.flock(f,fcntl.LOCK_EX);print("ready",flush=True);sys.stdin.read()',str(path)],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
                try:
                    self.assertEqual(child.stdout.readline().strip(),'ready');start=time.monotonic()
                    with self.assertRaises((ValueError,OSError)):transfer.snapshot(self.directory,self.record,self.policy)
                    self.assertLess(time.monotonic()-start,2)
                finally:
                    child.communicate(timeout=3)


if __name__=='__main__':unittest.main()
