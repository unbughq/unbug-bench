"""Public saved-card replays with authored lifecycle markers; no row closure."""
import copy
import json
import sys
from pathlib import Path
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import diagnosis
from test_stream_d import cards


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.card = copy.deepcopy(next(r['card'] for r in cards() if r['card']['case'].endswith('5813be')))
        self.card.update(terminal_stop='budget_exhausted', status='stopped', gates={})

    def state(self, stop='budget_exhausted', status='pending', outcome=None):
        self.card['diagnosis_state'] = dict(schema_version=1, exhaustion_id=str(uuid.uuid4()),
                                          stop=stop, status=status, outcome=outcome)

    def test_first_collection_is_eligible_before_diagnosis_and_completed_clears(self):
        self.assertTrue(diagnosis.exhaustion(self.card))
        expected = dict(schema_version=1, status='pending', replacement_eligible=True)
        self.assertEqual(diagnosis.pending_projection(self.card), expected)
        self.state()
        before = json.dumps(self.card, sort_keys=True)
        for _ in range(2):
            self.assertEqual(diagnosis.pending_projection(self.card), expected)
            self.assertTrue(diagnosis.actual_model_work(self.card))
        self.assertEqual(json.dumps(self.card, sort_keys=True), before)
        self.card['sha256'] = 'f' * 64
        self.assertEqual(diagnosis.pending_projection(self.card), expected)
        for outcome in ('factory_bug', 'close_to_passing', 'not_converging'):
            self.state(status='completed', outcome=outcome)
            self.assertIsNone(diagnosis.pending_projection(self.card))

    def test_completed_infrastructure_none_is_never_replacement_authority(self):
        self.card['terminal_stop'] = 'infrastructure_exhausted'
        self.state(stop='infrastructure_exhausted')
        self.assertEqual(diagnosis.pending_projection(self.card),
                         dict(schema_version=1, status='pending', replacement_eligible=False))
        self.state(stop='infrastructure_exhausted', status='completed', outcome='factory_bug')
        self.assertTrue(diagnosis.exhaustion(self.card))
        self.assertTrue(diagnosis.actual_model_work(self.card))
        self.assertIsNone(diagnosis.pending_projection(self.card))

    def test_later_budget_exhaustion_uses_its_current_diagnosis(self):
        self.card['infrastructure_gate'] = {'exhausted': True}
        self.state(stop='infrastructure_exhausted', status='completed', outcome='factory_bug')
        self.assertIsNone(diagnosis.pending_projection(self.card))
        # The authenticated runner archives the old marker before the fix resume;
        # even a retained historical marker cannot override a fresh exhaustion ID.
        self.state(stop='budget_exhausted')
        self.assertTrue(diagnosis.pending_projection(self.card)['replacement_eligible'])
        self.card.pop('infrastructure_gate')
        self.assertTrue(diagnosis.pending_projection(self.card)['replacement_eligible'])

    def test_b_core_queues_pending_infrastructure_but_never_derives_a_child(self):
        # B's saved-ciphertext transport harness uses authored envelope bindings.
        # Use D's real predicates, not the harness's authored answers.
        import test_batch_service as batch_test
        import budget
        harness = batch_test.ServiceTests(); harness.setUp(); self.addCleanup(harness.doCleanups)
        total = budget.case_spending(self.card['continuation_budget'])['total_spent_usd']
        self.state(stop='infrastructure_exhausted')
        pending = harness.input(total=total, terminal_stop='infrastructure_exhausted', gates={},
            diagnosis_state=copy.deepcopy(self.card['diagnosis_state']),
            continuation_budget=copy.deepcopy(self.card['continuation_budget']))
        harness.collect()
        planned = harness.plan(pending, diagnosis)
        self.assertEqual(planned['facts']['pending_projection'],
                         dict(schema_version=1, status='pending', replacement_eligible=False))
        self.assertEqual([(q['kind'], q['job']) for q in planned['queue']], [('resume', 'j')])
        self.assertEqual(harness.state()['derivations'], {})
        completed_state = {**pending['diagnosis_state'], 'status': 'completed', 'outcome': 'factory_bug'}
        completed = harness.input(payload=batch_test.KEY, total=total, terminal_stop='factory_bug_held', gates={},
            diagnosis_state=completed_state, continuation_budget=copy.deepcopy(self.card['continuation_budget']),
            factory_bug=dict(finding_id=completed_state['exhaustion_id'], gate_or_stage='unknown', summary_class='factory_bug'))
        harness.collect()
        after = harness.plan(completed, diagnosis)
        self.assertEqual(completed['terminal_stop'], 'factory_bug_held')
        self.assertIsNone(after['facts']['pending_projection'])
        self.assertFalse(any(q['source_generation'] == completed['sha256'] for q in after['queue']))
        self.assertEqual(harness.state()['derivations'], {})

    def test_bare_denied_or_estimated_reservation_is_zero_work(self):
        self.card['continuation_budget'] = {'events': [], 'invocation_reservations':
            {'denied': {'state': 'settled'}, 'crash': {'state': 'estimated', 'estimated_gap_usd': '10.000000000'}}}
        self.assertFalse(diagnosis.actual_model_work(self.card))
        self.assertFalse(diagnosis.pending_projection(self.card)['replacement_eligible'])
        for event in ({'cost': 0}, {'priced': 'subscription'}, {'cost': None}):
            self.card['continuation_budget']['events'] = [event]
            self.assertTrue(diagnosis.actual_model_work(self.card))
        self.card['continuation_budget']['events'] = []
        self.card['continuation_budget']['unpriced_invocations'] = [{'invocation_id': str(uuid.uuid4())}]
        self.assertTrue(diagnosis.actual_model_work(self.card))
        # A started call whose unknown usage settled to an estimate is still work.
        self.card['continuation_budget']['unpriced_invocations'] = []
        self.card['route_receipts'] = [{'outcome': 'denied'}, {'outcome': 'admitted'}]
        self.assertFalse(diagnosis.actual_model_work(self.card))
        self.card['route_receipts'].append({'outcome': 'interrupted'})
        self.assertTrue(diagnosis.actual_model_work(self.card))

    def test_projection_refuses_malformed_pause_seal_retirement_and_unproven_stops(self):
        for stop in ('provider_wait', 'paused', 'ttl_retired', 'retired_batch_bound', 'diagnosis_pending', 'extension_incomplete'):
            with self.subTest(stop=stop):
                self.card['terminal_stop'] = stop
                self.assertIsNone(diagnosis.pending_projection(self.card))
        self.card['terminal_stop'] = 'budget_exhausted'
        for state in (None, {}, {'status': 'pending'}):
            self.card['diagnosis_state'] = state
            self.assertIsNone(diagnosis.pending_projection(self.card))
        self.state()
        self.card['gates'] = {'G12': 'pass'}
        self.assertIsNone(diagnosis.pending_projection(self.card))

    def test_late_stop_and_extension_completion_need_exact_evidence(self):
        self.card.update(terminal_stop='late_defect_needs_ruling:G10', builder_rounds=8, recovery_config={'rounds': 8})
        self.assertTrue(diagnosis.exhaustion(self.card))
        history = [{'schema_version': 1, 'extension_id': 1, 'writer_operation_id': str(uuid.uuid4()),
                    'entry_sha256': 'a' * 64, 'outcome_sha256': None}]
        self.card['extension_history'] = history
        self.assertFalse(diagnosis.exhaustion(self.card))
        self.card['terminal_stop'] = 'extension_incomplete'
        self.assertFalse(diagnosis.exhaustion(self.card))
        history[-1]['outcome_sha256'] = 'b' * 64
        self.assertTrue(diagnosis.exhaustion(self.card))
        self.state(stop='extension_incomplete')
        self.card['terminal_stop'] = 'diagnosis_pending'
        self.assertTrue(diagnosis.exhaustion(self.card))
        history[-1]['extra'] = 'refuse'
        self.assertFalse(diagnosis.exhaustion(self.card))


if __name__ == '__main__': unittest.main()
