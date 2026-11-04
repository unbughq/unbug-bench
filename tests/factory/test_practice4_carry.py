"""Retained -3 smoke transfer. Only the target host/release binding and paths are authored.

The original source release, snapshot, journal, ACK, card and ciphertext are real.
Target release verification is a named double; no live qualification or Murphy closure.
AUTHORED: fixed clock; source money/reservations files re-serialised from the pinned snapshot.
"""
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
from carry_over import digest
import practice
import practice_preflight as preflight
from registry import atomic_json

FIXTURE = ROOT / 'tests/factory/fixtures/practice3-transfer'


class PracticeCarryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.home = self.root / 'home'
        retained = json.loads((FIXTURE / 'source-public.json').read_text())
        self.snapshot = retained['snapshot']; self.old = json.loads(retained['manifest_json'])
        self.case = self.old['jobs']['smoke']['case']
        self.generation = next(iter(self.snapshot['money']['jobs']['smoke']['acks']))
        self.record = json.loads((ROOT / 'factory/batches/b-plumbing-practice-4.json').read_text())  # Retained -3 to -4 contract.
        self.source = self.home / 'batches' / self.old['id']; self.source.mkdir(parents=True)
        source_release = self.root / 'retained-release'
        shutil.copytree(FIXTURE / 'release', source_release)
        real_verify = batch.verify
        real_verify(source_release, retained['public_policy']['batch']['sha256'])
        # Authored location only; original retained release/policy bytes stay untouched.
        self.record['carry_from']['policy']['batch']['release'] = str(source_release)
        self.target = self.home / 'batches' / self.record['id']
        for name, value in [('money.json', self.snapshot['money']),
                            ('reservations.json', dict(schema=1, batch=self.old['id'],
                             manifest_sha256=self.snapshot['manifest_sha256'], operations=self.snapshot['operations']))]:
            atomic_json(self.source / name, value)
        collected = json.loads((FIXTURE / 'collection-public.json').read_text())
        atomic_json(self.source / 'journal.json', collected['journal'])
        generation = self.source / 'generations' / self.case / self.generation
        generation.mkdir(parents=True)
        for name in collected['generation_manifest']['files']:
            shutil.copy2(FIXTURE / name, generation / name)
        atomic_json(generation / 'manifest.json', collected['generation_manifest'])
        publication = json.loads((FIXTURE / 'publication-public.json').read_text())
        for folder, name, value in [('current', self.case, publication['current']),
                                    ('outbox', publication['outbox']['operation_id'], publication['outbox'])]:
            (self.source / folder).mkdir()
            atomic_json(self.source / folder / (name + '.json'), value)
        self.release = self.root / 'authored-target-release'; self.release.mkdir()
        self.policy = dict(jobs=self.record['jobs'], batch=dict(id=self.record['id'],
            release=str(self.release), sha256=hashlib.sha256(b'authored target binding').hexdigest(),
            max_concurrency=1, manifest_path='factory/batches/' + self.record['id'] + '.json'))
        (self.root / 'factory/batches').mkdir(parents=True)
        shutil.copy2(ROOT / 'factory/control-recipient.txt', self.root / 'factory/control-recipient.txt')
        self.pin()
        def verify(directory, sha, root=None):
            if Path(directory) == self.release:
                self.assertEqual(sha, self.policy['batch']['sha256'])
                self.assertEqual(root, self.root)
            else:
                return real_verify(directory, sha, root)
        p = patch.object(batch, 'verify', verify); p.start(); self.addCleanup(p.stop)
        p = patch('time.time', return_value=1793790000); p.start(); self.addCleanup(p.stop)

    def pin(self):
        path = self.root / self.policy['batch']['manifest_path']
        path.write_text(json.dumps(self.record))
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        self.policy['batch']['manifest_sha256'] = sha
        atomic_json(self.release / 'source-manifest.json', dict(files={self.policy['batch']['manifest_path']: sha}))

    def test_actual_collected_smoke_keeps_identity_money_and_restore_bytes(self):
        self.assertEqual(digest(self.snapshot), self.record['carry_from']['snapshot_sha256'])
        transfer.prepare(self.policy, self.root, self.home)
        ack, entry, card, path = transfer.source(self.home, self.record, 'smoke', self.generation)
        row = money.load_locked(self.target, self.record, self.policy['batch']['manifest_sha256'])['jobs']['smoke']
        self.assertEqual(card['case'], self.case)
        self.assertEqual(card['sha256'], self.generation)
        self.assertEqual(row['authority']['case'], self.case)
        self.assertEqual(row['authority']['source_generation'], self.generation)
        self.assertEqual(row['held_usd'], '0.010000000')
        self.assertEqual(row['previous']['total_usd'], '0.000000000')
        self.assertEqual(ack, self.snapshot['money']['jobs']['smoke']['acks'][self.generation])
        payload = path / (self.case + '.checkpoint.tar.gz.age')
        self.assertEqual(hashlib.sha256(payload.read_bytes()).hexdigest(), self.generation)
        files = json.loads((FIXTURE / 'collection-public.json').read_text())['generation_manifest']['files']
        for name, meta in files.items():  # exact restore archive: checkpoint, wrapped key, card
            self.assertEqual(hashlib.sha256((path / name).read_bytes()).hexdigest(), meta['sha256'])
        transfer.prepare(self.policy, self.root, self.home)  # exact replay, no new authority

    def test_changed_snapshot_release_or_generation_refuses_before_export(self):
        original = deepcopy(self.record)
        for field in ('snapshot', 'release', 'generation'):
            with self.subTest(field=field):
                self.record = deepcopy(original)
                if field == 'snapshot': self.record['carry_from']['snapshot_sha256'] = '0' * 64
                if field == 'release': self.record['carry_from']['policy']['batch']['sha256'] = '0' * 64
                if field == 'generation': self.record['carry_from']['jobs']['smoke']['generation'] = '0' * 64
                self.pin()
                with self.assertRaises(ValueError): transfer.prepare(self.policy, self.root, self.home)
                self.assertFalse((self.source / 'export.json').exists())
                self.assertFalse((self.target / 'import.json').exists())

    def test_current_fixed_contract_preserves_caps_and_refuses_old_opt_in(self):
        current = json.loads((ROOT / preflight.MANIFEST).read_text())
        self.assertTrue(practice.matches(current))
        self.assertEqual(current['money_limit_usd'], self.old['money_limit_usd'])
        self.assertEqual(current['practice_admission'], self.old['practice_admission'])
        self.assertEqual(current['jobs']['smoke'], self.old['jobs']['smoke'])
        self.assertEqual(current['jobs']['practice']['args'], self.old['jobs']['practice']['args'])
        with patch.dict(os.environ, UNBUG_PRACTICE_BATCH=practice.BATCH):
            self.assertFalse(practice.active({'batch': {'id': self.old['id']}}, ROOT))
        with patch.dict(os.environ, UNBUG_PRACTICE_BATCH=self.old['id']):  # stale -3 unit/drop-in
            self.assertFalse(practice.active({'batch': {'id': self.old['id']}}, ROOT))
        changed = deepcopy(current); changed['money_limit_usd'] = '20.000000000'
        self.assertFalse(practice.matches(changed))

    def test_whole_batch_refuses_without_current_opt_in(self):
        # The opt-in gate is batch-wide. Once -4 is opted in for the smoke continuation,
        # practice dormancy and smoke-before-practice are procedural only (runbook + go-ahead).
        for value in (None, self.old['id']):
            with self.subTest(opt_in=value):
                env = {k: v for k, v in os.environ.items() if k != 'UNBUG_PRACTICE_BATCH'}
                if value: env['UNBUG_PRACTICE_BATCH'] = value
                with patch.dict(os.environ, env, clear=True):
                    self.assertFalse(practice.active(self.policy, self.root))
                    with self.assertRaisesRegex(ValueError, 'request_refused'):
                        holder.reserve(self.policy, self.root, self.home, 'practice', None)
                self.assertFalse(self.target.exists())
                self.assertFalse((self.source / 'export.json').exists())


if __name__ == '__main__': unittest.main()
