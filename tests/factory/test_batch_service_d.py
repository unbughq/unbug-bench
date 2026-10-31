"""Merged D on saved 5813be; authored lifecycle, totals and collection bindings.

The archive envelope is the saved opaque ciphertext used by test_batch_service,
not a newly generated case. Each phase uses a fresh journal. No launch or ACK.
"""
from copy import deepcopy
import hashlib
import json
from unittest.mock import patch
import unittest
import uuid

import test_batch_service as fixtures
import test_stream_d as d
import batch_service as service
import budget
import diagnosis


class RealDTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ServiceTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.saved = deepcopy(next(r['card'] for r in d.cards() if r['card']['case'].endswith('5813be')))

    def card(self, *, known=True, state='pending', stop='infrastructure_exhausted', provenance=True):
        card = self.saved.copy()
        card.update(status='stopped', gates={}, terminal_stop=stop,
                    infrastructure_gate={'exhausted': True},
                    case_budget=budget.case_spending(card['continuation_budget']) if known else None)
        if provenance:
            card['diagnosis_state'] = dict(schema_version=1, exhaustion_id=str(uuid.uuid4()),
                stop='infrastructure_exhausted', status=state, outcome='factory_bug' if state == 'completed' else None)
        if state == 'completed':
            card['factory_bug'] = dict(finding_id='finding-infra-1', gate_or_stage='G10', summary_class='infrastructure')
        bound = self.fixture.input(**{k: v for k, v in card.items() if k not in (
            'case', 'batch_release_sha256', 'archive', 'sha256', 'statement_cipher_sha256', 'public_search')})
        if not provenance:
            bound.pop('diagnosis_state', None); self.fixture.write_card(bound)
        self.fixture.collect()
        self.assertIsNone(next(iter(self.fixture.state()['entries'].values()))['facts'])
        return bound

    def plan(self, card): return self.fixture.plan(card, api=diagnosis)

    def test_known_pending_infrastructure_queues_diagnosis_without_child(self):
        card = self.card()
        result = self.plan(card)
        self.assertTrue(self.fixture.record['replacement_policy']['enabled'])
        self.assertEqual(result['facts']['pending_projection'],
                         dict(schema_version=1, status='pending', replacement_eligible=False))
        self.assertEqual([(r['kind'], r['job'], r['reason']) for r in result['queue']],
                         [('resume', 'j', 'exhaustion')])
        self.assertEqual(self.fixture.state()['derivations'], {})
        self.assertEqual(self.plan(card), result)

    def test_known_completed_infrastructure_is_held_without_child_or_new_queue(self):
        card = self.card(state='completed', stop='factory_bug_held')
        result = self.plan(card)
        self.assertTrue(result['facts']['exhaustion'])
        self.assertTrue(result['facts']['actual_model_work'])
        self.assertIsNone(result['facts']['pending_projection'])
        self.assertEqual(result['queue'], [])
        self.assertEqual(self.fixture.state()['derivations'], {})
        self.assertEqual(card['terminal_stop'], 'factory_bug_held')

    def test_null_pending_infrastructure_only_settles(self):
        self.check_null('pending', 'infrastructure_exhausted')

    def test_null_completed_infrastructure_only_settles(self):
        self.check_null('completed', 'factory_bug_held')

    def check_null(self, state, stop):
        result = self.plan(self.card(known=False, state=state, stop=stop))
        self.assertEqual([(r['kind'], r['reason']) for r in result['queue']], [('resume', 'settlement')])
        self.assertEqual(self.fixture.state()['derivations'], {})

    def test_unbound_legacy_known_precollected_retires_without_journal_changes(self):
        self.check_unbound(True)

    def test_unbound_legacy_null_precollected_retires_without_journal_changes(self):
        self.check_unbound(False)

    def check_unbound(self, known):
        card = self.fixture.input(terminal_stop='budget_exhausted', status='stopped', gates={},
            continuation_budget=self.saved['continuation_budget'],
            case_budget=budget.case_spending(self.saved['continuation_budget']) if known else None)
        card.pop('diagnosis_state'); self.fixture.write_card(card); self.fixture.collect()
        self.assertTrue(diagnosis.pending_projection(card)['replacement_eligible'])
        before = self.fixture.journal.read_bytes()
        expected = dict(status='retired', reason='legacy_retire', facts=None, queue=[])
        self.assertEqual(service.plan(self.fixture.policy, self.fixture.root, self.fixture.home,
            card['case'], card['sha256']), expected)
        entry = next(iter(self.fixture.state()['entries'].values()))
        path = self.fixture.journal.parent / 'retirements' / card['case'] / (card['sha256'] + '.json')
        record = path.read_bytes()
        self.assertEqual(json.loads(record), dict(schema=1, status='retired', reason='legacy_retire',
            decision_date='2026-10-30', case=card['case'], generation=card['sha256'],
            manifest_sha256=entry['manifest_sha256']))
        with patch.object(service, '_project', side_effect=AssertionError('must not invoke D')):
            self.assertEqual(self.plan(card), expected)
        self.assertEqual(path.read_bytes(), record)
        self.assertEqual(self.fixture.journal.read_bytes(), before)
        self.assertEqual(self.fixture.state()['queue'], {})

    def test_legacy_retirement_precedes_stored_facts(self):
        card = self.card(provenance=False)
        state = self.fixture.state()
        entry = next(iter(state['entries'].values()))
        entry['facts'] = dict(exhaustion=True, actual_model_work=True, pending_projection=None)
        service.atomic_json(self.fixture.journal, state)
        before = self.fixture.journal.read_bytes()
        self.assertEqual(self.plan(card)['status'], 'retired')
        self.assertEqual(self.fixture.journal.read_bytes(), before)

    def test_retirement_conflict_link_and_nonregular_are_unchanged(self):
        card = self.card(provenance=False)
        self.plan(card)
        path = self.fixture.journal.parent / 'retirements' / card['case'] / (card['sha256'] + '.json')
        good = path.read_bytes()
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'retirement conflict'): self.plan(card)
        self.assertEqual(path.read_text(), '{}')
        path.unlink()
        target = path.with_name('target.json'); target.write_bytes(good)
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'retirement conflict'): self.plan(card)
        self.assertTrue(path.is_symlink()); self.assertEqual(target.read_bytes(), good)
        path.unlink(); path.mkdir()
        with self.assertRaisesRegex(ValueError, 'retirement conflict'): self.plan(card)
        self.assertTrue(path.is_dir())

    def test_retired_inventory_preserves_every_saved_case_and_digest(self):
        root = fixtures.ROOT
        path = root / 'docs/reports/batch-service-inventory-20261030.json'
        source = json.loads(path.read_text())
        retired = json.loads((root / 'docs/reports/stream-b-legacy-retirements-20261031.json').read_text())
        expected = dict(schema=1, decision_date='2026-10-30', disposition='retired',
            reason='pre-new-schema', inventory_path=str(path.relative_to(root)),
            inventory_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), inventories={})
        for side in ('mac', 'vm'):
            expected['inventories'][side] = [{k: row[k] for k in (
                'case', 'card_sha256', 'card_archive_sha256', 'casekey', 'casekey_metadata', 'files')
                if k in row} for row in source[side]['checkpoints']]
        self.assertEqual(retired, expected)
        self.assertEqual(len(retired['inventories']['mac']), 43)
        self.assertEqual(len(retired['inventories']['vm']), 46)

    def test_malformed_object_real_d_creates_no_requests_known_total(self):
        self.check_malformed(True)

    def test_malformed_object_real_d_creates_no_requests_null_total(self):
        self.check_malformed(False)

    def check_malformed(self, known):
        card = self.fixture.input(terminal_stop='budget_exhausted', status='stopped', gates={},
            continuation_budget=self.saved['continuation_budget'], diagnosis_state={},
            case_budget=budget.case_spending(self.saved['continuation_budget']) if known else None)
        self.fixture.collect(); result = self.plan(card)
        self.assertFalse(result['facts']['exhaustion'])
        self.assertIsNone(result['facts']['pending_projection'])
        self.assertEqual(result['queue'], [])

    def test_disabled_adapter_blocks_stored_facts_replay(self):
        card = self.card(); self.plan(card)
        before = self.fixture.journal.read_bytes()
        result = service.plan(self.fixture.policy, self.fixture.root, self.fixture.home, card['case'], card['sha256'])
        self.assertEqual(result, dict(status='diagnosis_unavailable', facts=None, queue=[]))
        self.assertEqual(before, self.fixture.journal.read_bytes())


if __name__ == '__main__': unittest.main()
