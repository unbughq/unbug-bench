"""Offline transfer of saved cards/ledgers/ciphertext; lifecycle bindings authored.

No live diagnosis, deletion or publication is claimed, and no Murphy row closes.
"""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'tests/factory'), str(ROOT / 'bin')]
import batch
import batch_holder as holder
import batch_money as money
import batch_service as service
import batch_transfer as transfer
from carry_over import digest
from registry import atomic_json
from test_batch_holder import HolderTests


class TransferTests(unittest.TestCase):
    setUp = HolderTests.setUp
    setUpBase = HolderTests.setUpBase
    freeze = HolderTests.freeze
    input = HolderTests.input
    write_card = HolderTests.write_card
    answers = HolderTests.answers
    directory = HolderTests.directory
    ops = HolderTests.ops
    money = HolderTests.money
    reserve = HolderTests.reserve
    reconcile = HolderTests.reconcile
    publish = HolderTests.publish
    started = HolderTests.started
    output = HolderTests.output
    retirement = HolderTests.retirement

    def stopped(self, name='j'):
        op = self.started(self.reserve(name))
        card = self.output(op)
        self.publish(op); self.retirement(op); self.reconcile()
        return card

    def target(self, selections, *, name='fixed'):
        source_record, source_policy = deepcopy(self.record), deepcopy(self.policy)
        raw = (self.root / source_policy['batch']['manifest_path']).read_bytes()
        with tarfile.open(self.release / 'public-source.tar.gz', 'w:gz') as archive:
            member = tarfile.TarInfo('unbug-bench/' + source_policy['batch']['manifest_path'])
            member.size = len(raw); archive.addfile(member, io.BytesIO(raw))
        with money.locked(self.home, source_record['id']) as directory:
            snap = transfer.snapshot(directory, source_record, source_policy)
        record = deepcopy(source_record)
        record.update(id=name, jobs={key: deepcopy(value) for key, value in source_record['jobs'].items()
                                    if key in selections or any(k.startswith(key + '-r') for k in selections)})
        specs = {key: dict(generation=gen, case=snap['money']['jobs'][key]['authority']['case'],
                          committed_total_usd=snap['money']['jobs'][key]['held_usd']) for key, gen in selections.items()}
        # Root templates may remain solely to resolve an imported derived job.
        for key, value in record['jobs'].items():
            if key not in specs: value['case'] = 'case-' + name + '-' + key
        record['carry_from'] = dict(schema=1, manifest_json=raw.decode(), policy=source_policy,
                                   snapshot_sha256=digest(snap), jobs=specs)
        release = self.root / ('release-' + name); release.mkdir()
        path = self.root / ('factory/batches/' + name + '.json')
        path.write_text(json.dumps(record))
        pin = hashlib.sha256(path.read_bytes()).hexdigest()
        (release / 'source-manifest.json').write_text(json.dumps({'files': {'factory/batches/' + name + '.json': pin}}))
        policy = dict(jobs=record['jobs'], batch=dict(id=name, release=str(release), sha256='b'*64,
                      max_concurrency=record['max_concurrency'], manifest_path='factory/batches/' + name + '.json', manifest_sha256=pin))
        return record, policy

    def target_state(self, record, policy):
        return money.load_locked(self.home / 'batches' / record['id'], record, policy['batch']['manifest_sha256'])

    def test_saved_card_launch_keeps_spend_owner_lineage_and_freezes_source(self):
        card = self.stopped()
        old = self.money()['jobs']['j']
        record, policy = self.target({'j': card['sha256']})
        op = holder.reserve(policy, self.root, self.home, 'j', card['sha256'])
        self.assertEqual(op, holder.reserve(policy, self.root, self.home, 'j', card['sha256']))
        state = self.target_state(record, policy)
        self.assertEqual(state['jobs']['j']['previous'], old['previous'])
        self.assertEqual(state['jobs']['j']['known_floor_usd'], old['known_floor_usd'])
        self.assertEqual(op['case'], card['case'])
        self.assertNotEqual(op['authority']['reservation_id'], old['authority']['reservation_id'])
        self.assertEqual(money.aggregate(state), money.aggregate(self.money()))
        bound = batch.bind(policy, 'j', card['sha256'], self.root, home=self.home, operation=op['operation_id'])
        self.assertIn('--restore', bound['args'])
        source = holder.source_directory(policy, self.root, self.home, op['operation_id'])
        self.assertEqual(json.loads((source / (card['case'] + '.scorecard.json')).read_text()), card)
        with self.assertRaisesRegex(ValueError, 'batch_exported'): self.reserve(source=card['sha256'])
        with self.assertRaisesRegex(ValueError, 'batch_exported'): self.reconcile()
        with self.assertRaises(ValueError): holder.reserve(policy, self.root, self.home, 'j', None)

    def test_omitted_owner_stays_charged(self):
        card = self.stopped(); self.stopped('k')
        record, policy = self.target({'j': card['sha256']})
        transfer.prepare(policy, self.root, self.home)
        state = self.target_state(record, policy)
        self.assertEqual(state['carried_debit_usd'], '1000.000000000')
        self.assertEqual(money.aggregate(state), 2000 * 10**9)

    def test_export_crash_repair_does_not_regrant(self):
        card = self.stopped(); record, policy = self.target({'j': card['sha256']})
        real = transfer.atomic_json
        def fail(path, value):
            if path.name == 'import.json': raise OSError('authored crash')
            real(path, value)
        with patch.object(transfer, 'atomic_json', fail), self.assertRaises(OSError):
            transfer.prepare(policy, self.root, self.home)
        raw = (self.directory / 'export.json').read_bytes()
        transfer.prepare(policy, self.root, self.home)
        self.assertEqual(raw, (self.home / 'batches/fixed/import.json').read_bytes())
        transfer.prepare(policy, self.root, self.home)
        self.assertEqual(raw, (self.directory / 'export.json').read_bytes())

    def test_legacy_paths_refuse_without_minting_money(self):
        card = self.stopped(); record, policy = self.target({'j': card['sha256']})
        with patch.object(holder, 'HOLDER_ENABLED', False):
            for source in (None, card['sha256']):
                with self.assertRaises(ValueError): batch.bind(policy, 'j', source, self.root)
                with self.assertRaises(ValueError): money.authorize(policy, 'j', source, self.root, self.home)
            with self.assertRaises(ValueError): money.authorize(self.policy, 'j-r1', None, self.root, self.home)
        self.assertFalse((self.home / 'batches/fixed/money.json').exists())

    def test_changed_source_after_pinning_and_competing_target_refuse(self):
        card = self.stopped(); record, policy = self.target({'j': card['sha256']})
        other_record, other_policy = self.target({'j': card['sha256']}, name='other')
        transfer.prepare(policy, self.root, self.home)
        with self.assertRaises(ValueError): transfer.prepare(other_policy, self.root, self.home)
        path = self.directory / 'current' / (card['case'] + '.json')
        path.write_text('{}')
        with self.assertRaises(ValueError): holder.reserve(policy, self.root, self.home, 'j', card['sha256'])

    def derive(self, card):
        with money.locked(self.home, self.record['id']):
            journal = service._load(self.directory, self.record, self.policy['batch']['manifest_sha256'])
            entry = journal['entries'][card['case'] + '/' + card['sha256']]
            entry['facts'] = dict(exhaustion=True, actual_model_work=True, pending_projection=dict(
                schema_version=1, status='pending', replacement_eligible=True))
            service._enqueue(journal, self.record, entry, card)
            atomic_json(self.directory / 'journal.json', journal)
            state = self.money()
            money.authorize_locked(state, self.record, 'j-r1', None)
            atomic_json(self.directory / 'money.json', state)

    def test_queued_derived_authority_and_latch_survive_without_new_allocation(self):
        card = self.stopped(); self.derive(card)
        record, policy = self.target({'j': card['sha256'], 'j-r1': None})
        child = holder.reserve(policy, self.root, self.home, 'j-r1', None)
        self.assertEqual(child, holder.reserve(policy, self.root, self.home, 'j-r1', None))
        self.assertEqual(child['case'], 'case-practice-j-r1')
        journal = service._load(self.home / 'batches/fixed', record, policy['batch']['manifest_sha256'])
        self.assertEqual(len(journal['queue']), 1)
        self.assertEqual(journal['queue']['replacement/' + card['case']]['job'], 'j-r1')
        before = deepcopy(journal)
        entry = dict(job='j', case=card['case'], generation=card['sha256'], facts=dict(
            exhaustion=True, actual_model_work=True, pending_projection=dict(schema_version=1, status='pending', replacement_eligible=True)))
        service._enqueue(journal, record, entry, card)
        self.assertEqual(journal['imported_derivations'], before['imported_derivations'])
        self.assertEqual([r for r in journal['queue'].values() if r['kind'] == 'replacement'],
                         [r for r in before['queue'].values() if r['kind'] == 'replacement'])
        self.assertEqual(money.aggregate(self.target_state(record, policy)), 2000*10**9)

    def test_real_restore_ledger_and_worker_install_preserve_saved_accounting(self):
        from types import SimpleNamespace
        import job_config
        import restore_ledger
        card = self.stopped(); record, policy = self.target({'j': card['sha256']})
        worker = {'files': {policy['batch']['manifest_path']: policy['batch']['manifest_sha256']}}
        worker_path = self.root / 'worker-release-manifest.json'; worker_path.write_text(json.dumps(worker))
        release_path = self.root / 'batch-release.json'
        release_path.write_text(json.dumps({'files': {worker_path.name: hashlib.sha256(worker_path.read_bytes()).hexdigest()}}))
        policy['batch']['sha256'] = hashlib.sha256(release_path.read_bytes()).hexdigest()
        op = holder.reserve(policy, self.root, self.home, 'j', card['sha256'])
        config_path = self.home / 'batches/fixed/configs' / (op['config_sha256'] + '.json')
        work = self.root / 'work' / card['case']; work.mkdir(parents=True)
        sealed = self.root / 'worker-sealed'
        atomic_json(work / 'scorecard.json', card)
        atomic_json(work / 'continuation-budget.json', card['continuation_budget'])
        atomic_json(work / 'job-money.json', card['job_money'])
        before = (work / 'continuation-budget.json').read_bytes()
        with patch.object(job_config, 'FACTORY', self.root / 'factory'):
            receipt = restore_ledger.install(work, sealed, card['case'], card['sha256'], card,
                release_sha256=policy['batch']['sha256'], job_config_path=config_path, job_config_sha256=op['config_sha256'])
            self.assertTrue(receipt['accounting_authenticated'])
            args = SimpleNamespace(resume=card['case'], batch_release_sha256=policy['batch']['sha256'],
                                   factory_job_config=str(config_path), factory_job_config_sha256=op['config_sha256'])
            c = SimpleNamespace(case_id=card['case'], work=work, card={}, checkpoint_card=card,
                                ledger=sealed / (card['case'] + '.continuation-budget.json'))
            job_config.install(c, args)
            self.assertEqual(c.job_money, op['authority'])
            self.assertEqual((work / 'continuation-budget.json').read_bytes(), before)
            history = json.loads((work / 'job-money-history.json').read_text())
            self.assertEqual(next(iter(history.values()))['old'], card['job_money'])
            self.assertEqual(json.loads(c.ledger.read_text()), card['continuation_budget'])


    def test_child_only_import_cannot_launch_its_template_root(self):
        card = self.stopped(); self.derive(card)
        record, policy = self.target({'j-r1': None})
        child = holder.reserve(policy, self.root, self.home, 'j-r1', None)
        self.assertEqual(child['case'], 'case-practice-j-r1')
        with self.assertRaisesRegex(ValueError, 'template-only'):
            holder.reserve(policy, self.root, self.home, 'j', None)
        self.assertEqual(self.target_state(record, policy)['carried_debit_usd'], '1000.000000000')

    def test_queued_child_with_any_operation_refuses(self):
        card = self.stopped(); self.derive(card)
        child = self.reserve('j-r1')
        with money.locked(self.home, self.record['id']):
            ops = self.ops(); ops[child['operation_id']]['state'] = 'failed'
            holder._save(self.directory, self.record, self.policy, ops)
        record, policy = self.target({'j': card['sha256'], 'j-r1': None})
        with self.assertRaises(ValueError): transfer.prepare(policy, self.root, self.home)
        self.assertFalse((self.directory / 'export.json').exists())


del HolderTests  # Imported fixture methods are not another copy of its test suite.

if __name__ == '__main__': unittest.main()
