"""Contract-only collection/queue exams, no model/cloud/decryption or row closure.

Saved public card + opaque saved ciphertext; case/release/archive bindings and
D answers are explicitly authored. The ciphertext is repurposed as an archive
transport envelope, not claimed to be a new case or D eligibility evidence.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
import batch
import batch_money as money
import batch_service as service

CARD = json.loads((ROOT / 'tests/factory/fixtures/isolation-timeouts/scorecard.json').read_text())
CIPHER = (ROOT / 'sealed/case-20261017T212118Z-1ad7fa.statement.age').read_bytes()
KEY = (ROOT / 'sealed/case-20261017T212118Z-1ad7fa.casekey.age').read_bytes()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home, self.source = self.root / 'control', self.root / 'incoming'
        self.source.mkdir()
        (self.root / 'factory/batches').mkdir(parents=True)
        recipient = (ROOT / 'factory/control-recipient.txt').read_text()
        (self.root / 'factory/control-recipient.txt').write_text(recipient)
        jobs = {name: dict(mode='batch', case='case-practice-' + name, max_calls=10,
                          requested_total_usd='1.000000000', args=['1', '--source', 'port'])
                for name in ('j', 'k')}
        self.record = dict(schema=1, id='practice', jobs=jobs, money_limit_usd='3.000000000',
                           batch_deadline='2099-01-01T00:00:00Z', max_concurrency=1,
                           target_slots=1, restore_recipient=recipient.strip(),
                           replacement_policy=dict(schema=1, enabled=True), diagnosis_policy=dict(schema=1, enabled=True))
        self.release = self.root / 'release'; self.release.mkdir()
        self.policy = dict(jobs=jobs, batch=dict(id='practice', release=str(self.release),
                           sha256='a' * 64, max_concurrency=1, manifest_path='factory/batches/practice.json'))
        self.freeze()
        # Only release verification is mocked; actual manifest digest/root binding,
        # collection.verify, files, lock, journal and queue paths are exercised.
        verify = patch.object(batch, 'verify'); verify.start(); self.addCleanup(verify.stop)
        self.api_calls = []
        self.api = self.answers()

    def freeze(self):
        path = self.root / 'factory/batches/practice.json'
        path.write_text(json.dumps(self.record))
        pin = hashlib.sha256(path.read_bytes()).hexdigest()
        self.policy['batch']['manifest_sha256'] = pin
        (self.release / 'source-manifest.json').write_text(json.dumps({'files': {
            'factory/batches/practice.json': pin}}))

    def answers(self, exhausted=True, work=True, pending=None):
        def call(name, value):
            def result(card):
                self.api_calls.append((name, deepcopy(card)))
                return deepcopy(value)
            return result
        return SimpleNamespace(exhaustion=call('exhaustion', exhausted),
                               actual_model_work=call('actual_model_work', work),
                               pending_projection=call('pending_projection', pending))

    def input(self, job='j', *, payload=CIPHER, total=None, **changes):
        case = 'case-practice-' + job
        card = deepcopy(CARD)
        card.update(case=case, batch_release_sha256='a' * 64,
                    archive=case + '.checkpoint.tar.gz.age', sha256=hashlib.sha256(payload).hexdigest(),
                    case_budget={'total_spent_usd': total},
                    diagnosis_state={})  # Authored provenance for contract-only API doubles.
        card.update(changes)
        (self.source / card['archive']).write_bytes(payload)
        (self.source / (case + '.casekey.age')).write_bytes(KEY)
        (self.source / (case + '.statement.age')).write_bytes(CIPHER)
        self.write_card(card)
        return card

    def write_card(self, card, case=None):
        (self.source / ((case or card['case']) + '.scorecard.json')).write_text(json.dumps(card))

    @property
    def journal(self): return self.home / 'batches/practice/journal.json'

    def state(self): return json.loads(self.journal.read_text())

    def collect(self, job='j'):
        return service.collect(self.policy, self.root, self.home, job, self.source)

    def plan(self, card, api=None, **kwargs):
        with patch.dict(sys.modules, diagnosis=api or self.api):
            return service.plan(self.policy, self.root, self.home, card['case'], card['sha256'], **kwargs)

    def generation(self, card):
        return self.home / 'batches/practice/generations' / card['case'] / card['sha256']

    def test_explicit_false_policy_never_projects_or_enqueues(self):
        self.record['diagnosis_policy']['enabled'] = False; self.freeze()
        card = self.input(); self.collect()
        with patch.dict(sys.modules, diagnosis=self.api):
            result = service.plan(self.policy, self.root, self.home, card['case'], card['sha256'])
        self.assertEqual(result['status'], 'diagnosis_unavailable')
        self.assertEqual(self.api_calls, [])
        self.assertEqual(self.state()['queue'], {})

    def test_verified_immutable_copy_and_gate_off_never_imports_d(self):
        self.record.pop('diagnosis_policy'); self.freeze()
        card = self.input()
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        self.collect()
        result = service.plan(self.policy, self.root, self.home, card['case'], card['sha256'])
        self.assertEqual(result['status'], 'diagnosis_unavailable')
        self.assertNotIn('diagnosis', sys.modules)
        self.assertEqual(self.state()['queue'], {})
        self.assertEqual({p.name: p.read_bytes() for p in self.source.iterdir()}, before)
        generation = self.generation(card)
        self.assertEqual((generation / (card['case'] + '.statement.age')).read_bytes(), CIPHER)
        self.assertEqual(self.collect(), self.collect())
        self.assertFalse((self.home / 'batch-money').exists())
        self.assertFalse((self.home / 'batches/practice/current').exists())
        # A different key/card/companion at the SAME archive hash refuses.
        for suffix in ('casekey.age', 'scorecard.json', 'statement.age'):
            path = self.source / (card['case'] + '.' + suffix); original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.assertRaises(ValueError): self.collect()
            path.write_bytes(original)

    def test_missing_corrupt_foreign_linked_members_refuse(self):
        card = self.input()
        for suffix in ('casekey.age', 'checkpoint.tar.gz.age', 'scorecard.json'):
            path = self.source / (card['case'] + '.' + suffix); raw = path.read_bytes()
            path.unlink()
            with self.assertRaises((OSError, ValueError)): self.collect()
            path.symlink_to(self.source / (card['case'] + '.statement.age'))
            with self.assertRaises((OSError, ValueError)): self.collect()
            path.unlink(); path.write_bytes(raw)
        for changes in ({'case': 'case-foreign'}, {'batch_release_sha256': 'b' * 64},
                        {'checkpoint_error': 'authored failure'}, {'sha256': '0' * 64},
                        {'archive': 'foreign.tar.gz.age'}):
            self.write_card({**card, **changes}, card['case'])
            with self.assertRaises(ValueError): self.collect()
        self.write_card(card)
        self.assertFalse(self.journal.exists())

    def test_referenced_ciphertexts_and_unbound_archive(self):
        card = self.input(statement_cipher_sha256=hashlib.sha256(CIPHER).hexdigest(),
                          public_search={'cipher_sha256': hashlib.sha256(CIPHER).hexdigest()})
        with self.assertRaises(ValueError): self.collect()  # referenced search is missing
        path = self.source / (card['case'] + '.search.age'); path.write_bytes(b'bad')
        with self.assertRaises(ValueError): self.collect()
        path.write_bytes(CIPHER)
        alternate = self.source / (card['case'] + '.tar.gz.age'); alternate.write_bytes(b'other')
        (self.source / 'case-foreign.scorecard.json').write_text('{}')
        card.pop('archive'); self.write_card(card)
        self.collect()
        self.assertFalse((self.generation(card) / alternate.name).exists())
        self.assertFalse((self.generation(card) / 'case-foreign.scorecard.json').exists())

    def test_publish_before_journal_crash_repairs_then_corruption_refuses(self):
        card = self.input()
        atomic = service.atomic_json
        def interrupt(path, value):
            if path.name == 'journal.json': raise OSError('authored crash')
            return atomic(path, value)
        with patch.object(service, 'atomic_json', interrupt), self.assertRaises(OSError): self.collect()
        self.assertTrue(self.generation(card).is_dir())
        self.assertFalse(self.journal.exists())
        self.collect()
        self.plan(card)
        (self.generation(card) / (card['case'] + '.casekey.age')).write_bytes(b'changed')
        with self.assertRaises(ValueError): self.plan(card)
        with self.assertRaises(ValueError): self.collect()

    def test_unknown_absent_projection_settlement_and_immutable_replay(self):
        card = self.input(); card.pop('case_budget'); self.write_card(card)
        self.collect()
        result = self.plan(card)
        self.assertEqual([name for name, _ in self.api_calls],
                         ['exhaustion', 'actual_model_work', 'pending_projection'])
        self.assertTrue(all(c == card for _, c in self.api_calls))
        self.assertIsNone(result['facts']['pending_projection'])
        self.assertEqual([r['reason'] for r in result['queue']], ['settlement'])
        self.assertEqual(self.state()['derivations'], {})
        before = self.journal.read_bytes()
        changed = SimpleNamespace()  # would fail any call; stored facts must win
        self.assertEqual(self.plan(card, changed), result)
        self.assertEqual(self.journal.read_bytes(), before)

    def test_unknown_eligible_projection_settlement_precedes_replacement(self):
        card = self.input(); self.collect()
        eligible = self.answers(pending=dict(schema_version=1, status='pending', replacement_eligible=True))
        result = self.plan(card, eligible)
        self.assertEqual([r['reason'] for r in result['queue']], ['settlement', 'unknown_total'])
        self.assertGreater(result['queue'][0]['sequence'], result['queue'][1]['sequence'])
        self.assertEqual(len(self.state()['derivations']), 1)

    def test_two_child_chain_dedup_across_generations_and_restart(self):
        self.api = self.answers(pending=dict(schema_version=1, status='pending', replacement_eligible=True))
        card = self.input(total=0); self.collect(); self.plan(card)
        child = self.input('j-r1', total=0); self.collect('j-r1'); self.plan(child)
        later = self.input(payload=KEY, total=0); self.collect(); self.plan(later, self.answers())
        state = self.state()
        self.assertEqual([r['job'] for r in service.ordered_queue(state) if r['kind'] == 'replacement'],
                         ['j-r1', 'j-r2'])
        self.assertEqual(len(state['derivations']), 2)
        self.assertEqual(state['derivations'][card['case']]['eligible_generation'], card['sha256'])
        self.assertEqual(self.collect('j-r1')['facts'], self.plan(child)['facts'])
        state['derivations'][card['case']]['child_job'] = 'j-r2'
        self.journal.write_text(json.dumps(state))
        with self.assertRaises(ValueError): self.plan(later)

    def test_none_projection_never_derives_even_with_both_predicates_true(self):
        card = self.input(total=0); self.collect()
        result = self.plan(card)
        self.assertTrue(result['facts']['exhaustion'])
        self.assertTrue(result['facts']['actual_model_work'])
        self.assertEqual(result['queue'], [])
        self.assertEqual(self.state()['derivations'], {})
        before = self.journal.read_bytes()
        eligible = self.answers(pending=dict(schema_version=1, status='pending', replacement_eligible=True))
        self.assertEqual(self.plan(card, eligible), result)
        self.assertEqual(self.journal.read_bytes(), before)

    def test_predicate_no_work_false_projection_and_disabled_replacements(self):
        for index, (work, pending, count) in enumerate((
                (False, None, 0),
                (True, dict(schema_version=1, status='pending', replacement_eligible=False), 1))):
            job = ('j', 'k')[index]
            card = self.input(job, total=0); self.collect(job)
            self.plan(card, self.answers(work=work, pending=pending))
            own = [r for r in self.state()['queue'].values() if r['job'] == job]
            self.assertEqual(len(own), count)
        self.assertEqual(self.state()['derivations'], {})

    def test_schema_mutation_exception_and_deadline_cannot_persist_requests(self):
        card = self.input(); self.collect(); before = self.journal.read_bytes()
        invalid = [self.answers(exhausted=1), self.answers(pending={}),
                   self.answers(work=False, pending=dict(schema_version=1, status='pending', replacement_eligible=True)),
                   self.answers(pending=dict(schema_version=True, status='pending', replacement_eligible=True)),
                   self.answers(pending=dict(schema_version=1, status='pending', replacement_eligible=True, extra=0)),
                   SimpleNamespace()]
        mutating = self.answers()
        mutating.exhaustion = lambda c: c.update(case='case-foreign') or True
        invalid.append(mutating)
        for api in invalid:
            with self.assertRaises(ValueError): self.plan(card, api)
            self.assertEqual(self.journal.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'retired_batch_bound'):
            self.plan(card, now=money.deadline(self.record['batch_deadline']))
        self.assertEqual(self.journal.read_bytes(), before)
        with self.assertRaises(ValueError):
            service.plan(self.policy, self.root, self.home, card['case'], 'f' * 64)

    def test_manifest_grammar_and_derived_collection_require_recorded_parent(self):
        self.input('j-r1')
        with self.assertRaises(ValueError): self.collect('j-r1')
        for name in ('j-r0', 'j-r01', 'j-r-1', '../j'):
            with self.assertRaises(ValueError): service.resolve_job(self.record, name)
        for bad in ({'schema': 1, 'enabled': 1}, {'schema': True, 'enabled': True},
                    {'schema': 1, 'enabled': True, 'extra': 0}):
            record = {**self.record, 'replacement_policy': bad}
            with self.assertRaises(ValueError): service.resolve_job(record, 'j')
        for name in ('j-r1', 'j-r01'):
            record = deepcopy(self.record)
            record['jobs'][name] = {**record['jobs']['j'], 'case': 'case-practice-' + name}
            with self.assertRaises(ValueError): service.resolve_job(record, name)
        record = {**self.record, 'replacement_policy': dict(schema=1, enabled=False)}
        with self.assertRaises(ValueError): service.resolve_job(record, 'j-r1')
        self.assertEqual(service.resolve_job(self.record, 'j-r200')['ordinal'], 200)

    def test_failed_plan_write_is_atomic_and_replay_rebuilds_once(self):
        self.api = self.answers(pending=dict(schema_version=1, status='pending', replacement_eligible=True))
        card = self.input(); self.collect()
        before = self.journal.read_bytes()
        with patch.object(service, 'atomic_json', side_effect=OSError('authored crash')):
            with self.assertRaises(OSError): self.plan(card)
        self.assertEqual(self.journal.read_bytes(), before)
        self.plan(card)
        self.assertEqual(len(self.state()['queue']), 2)
        self.journal.write_text('{}')
        with self.assertRaises(ValueError): self.collect()


if __name__ == '__main__': unittest.main()
