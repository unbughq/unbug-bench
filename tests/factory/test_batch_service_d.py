"""Merged D on saved 5813be; authored lifecycle, totals and collection bindings.

The archive envelope is the saved opaque ciphertext used by test_batch_service,
not a newly generated case. Each phase uses a fresh journal. No launch or ACK.
"""
from copy import deepcopy
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

    def test_unbound_legacy_known_precollected_refuses_without_changes(self):
        self.check_unbound(True)

    def test_unbound_legacy_null_precollected_refuses_without_changes(self):
        self.check_unbound(False)

    def check_unbound(self, known):
        card = self.fixture.input(terminal_stop='budget_exhausted', status='stopped', gates={},
            continuation_budget=self.saved['continuation_budget'],
            case_budget=budget.case_spending(self.saved['continuation_budget']) if known else None)
        card.pop('diagnosis_state'); self.fixture.write_card(card); self.fixture.collect()
        self.assertTrue(diagnosis.pending_projection(card)['replacement_eligible'])
        before = self.fixture.journal.read_bytes()
        self.assertEqual(service.plan(self.fixture.policy, self.fixture.root, self.fixture.home,
            card['case'], card['sha256'])['status'], 'diagnosis_unavailable')
        with self.assertRaisesRegex(ValueError, 'legacy_projection_unbound'): self.plan(card)
        self.assertEqual(self.fixture.journal.read_bytes(), before)
        self.assertEqual(self.fixture.state()['queue'], {})

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
