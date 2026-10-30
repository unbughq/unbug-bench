"""Held-state control replays on saved 5813be and real practice bytes."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import diagnosis
import diagnosis as held
import test_stream_d_runtime as runtime


class HeldTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch

    def setUp(self):
        runtime.RuntimeTests.setUp(self)
        self.c.card = copy.deepcopy(self.source)
        self.c.card.update(status='stopped', terminal_stop='infrastructure_exhausted', gates={},
                           infrastructure_gate={'gate': 'G10', 'exhausted': True})
        diagnosis.record_exhaustion(self.c.card)
        self.c.authenticated_job_config['batch_release_sha256'] = self.c.args.batch_release_sha256
        # Authored queued-input layout; immutable bytes copied from the real
        # saved ledger. The dispatcher must verify this source binding.
        self.inputs = self.work / 'diagnosis' / self.c.card['diagnosis_state']['exhaustion_id'] / 'inputs'
        self.inputs.mkdir(parents=True)
        (self.inputs / self.ledger.name).write_bytes(self.ledger.read_bytes())
        self.result = dict(schema_version=1, case_id=self.c.case_id, checkpoint_sha256=self.source['sha256'],
            outcome='factory_bug', reason='authored finding control',
            evidence=[dict(path=self.ledger.name, sha256=hashlib.sha256(self.ledger.read_bytes()).hexdigest(),
                           finding='authored private evidence')],
            factory_bug=dict(component='private component', reproducer='private reproducer',
                             affected_operations=[str(uuid.uuid4())], fix_required='private fix'))

    def persist(self, result=None):
        held.persist_factory_bug(self.c, self.result if result is None else result,
                                 generation=self.source['sha256'], evidence_root=self.inputs)

    def restore(self):
        return held.restore_factory_bug(self.c, generation=self.source['sha256'], evidence_root=self.inputs)

    def test_pre_rollout_first_hold_normalizes_operations_and_keeps_spend(self):
        before = self.ledger.read_bytes()
        raw = copy.deepcopy(self.result)
        self.assertFalse(diagnosis.pending_projection(self.c.card)['replacement_eligible'])
        self.persist()
        self.assertEqual(self.result, raw)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.c.card['terminal_stop'], 'factory_bug_held')
        self.assertEqual(self.c.card['diagnosis_state']['status'], 'completed')
        self.assertEqual(self.c.card['factory_bug_resume_count'], 0)
        self.assertEqual(self.c.card['factory_bug']['gate_or_stage'], 'G10')
        self.assertEqual(set(self.c.card['factory_bug']), {'finding_id', 'gate_or_stage', 'summary_class'})
        self.assertIsNone(diagnosis.pending_projection(self.c.card))
        finding = next((self.work / 'diagnosis').glob('*/finding.json'))
        value = json.loads(finding.read_text())
        raw_path, = finding.parent.glob('raw-result-*.json')
        self.assertEqual(json.loads(raw_path.read_text()), raw)
        self.assertEqual(value['diagnosis']['factory_bug']['affected_operations'], [])
        self.assertEqual(value['eligible_operation_ids'], [])
        self.assertEqual(value['failure_receipts'], [])
        self.assertEqual(json.loads((self.work / 'factory-bug-resumes.json').read_text()), [])
        before = finding.read_bytes()
        self.assertTrue(self.restore())
        self.assertEqual(finding.read_bytes(), before)
        changed = copy.deepcopy(self.result); changed['reason'] = 'a different assertion'
        with self.assertRaisesRegex(budget.BudgetError, 'diagnosis_finding_invalid'): self.persist(changed)
        self.assertEqual(finding.read_bytes(), before)

    def test_crash_after_finding_replays_before_completing_public_state(self):
        atomic = held.atomic_json
        def fail_card(path, value):
            if Path(path).name == 'scorecard.json': raise OSError('authored checkpoint interruption')
            atomic(path, value)
        with patch.object(held, 'atomic_json', side_effect=fail_card):
            with self.assertRaises(OSError): self.persist()
        self.assertEqual(self.c.card['diagnosis_state']['status'], 'pending')
        self.assertNotIn('factory_bug', self.c.card)
        finding = next((self.work / 'diagnosis').glob('*/finding.json'))
        before = finding.read_bytes()
        ledger = json.loads(self.ledger.read_text())
        ledger['events'].append(dict(id='authored-later-receipt', role='reviewer', calls=1,
                                    cost=0, list_cost_usd=0, estimated_subscription_cost_usd=0))
        ledger['calls'] += 1
        self.ledger.write_text(json.dumps(ledger))
        live = self.ledger.read_bytes()
        self.assertTrue(self.restore())
        self.assertEqual(finding.read_bytes(), before)
        self.assertEqual(self.ledger.read_bytes(), live)
        self.assertEqual(self.c.card['terminal_stop'], 'factory_bug_held')

    def test_crash_after_history_replays_empty_history(self):
        atomic = held.atomic_json
        def fail_finding(path, value):
            if Path(path).name == 'finding.json': raise OSError('authored finding interruption')
            atomic(path, value)
        with patch.object(held, 'atomic_json', side_effect=fail_finding):
            with self.assertRaises(OSError): self.persist()
        self.assertEqual(self.c.card['diagnosis_state']['status'], 'pending')
        self.assertFalse(self.restore())
        self.persist()
        self.assertEqual(self.c.card['factory_bug_resume_count'], 0)

    def test_missing_history_after_finding_never_resets(self):
        self.persist()
        (self.work / 'factory-bug-resumes.json').unlink()
        with self.assertRaisesRegex(budget.BudgetError, 'factory_bug_history_invalid'): self.restore()
        self.assertNotIn('factory_bug_resume_count', self.c.card)
        self.assertEqual(self.c.card['terminal_stop'], 'factory_bug_history_invalid')
        self.assertFalse(diagnosis.exhaustion(self.c.card))
        self.assertIsNone(diagnosis.pending_projection(self.c.card))
        state = copy.deepcopy(self.c.card['diagnosis_state'])
        diagnosis.record_exhaustion(self.c.card, new_exhaustion=True)
        self.assertEqual(self.c.card['diagnosis_state'], state)

    def test_unreadable_history_and_prior_waste_refuse_initialization(self):
        history = self.work / 'factory-bug-resumes.json'
        history.write_text('{}')
        with self.assertRaisesRegex(budget.BudgetError, 'factory_bug_history_invalid'): self.persist()
        self.assertFalse(diagnosis.exhaustion(self.c.card))
        self.assertIsNone(diagnosis.pending_projection(self.c.card))
        history.unlink()
        ledger = json.loads(self.ledger.read_text())
        ledger['infrastructure_waste'] = [{'kind': 'factory_bug'}]
        self.ledger.write_text(json.dumps(ledger))
        with self.assertRaisesRegex(budget.BudgetError, 'factory_bug_history_invalid'): self.persist()
        self.assertFalse(history.exists())

    def test_stage_comes_only_from_code_and_hold_cannot_cross_batch(self):
        self.c.card['infrastructure_gate']['gate'] = 'private component'
        self.persist()
        self.assertEqual(self.c.card['factory_bug']['gate_or_stage'], 'unknown')
        self.c.batch_id = self.c.job_money['batch'] = 'different-batch'
        self.c.authenticated_job_config['job_money']['batch'] = 'different-batch'
        with self.assertRaisesRegex(budget.BudgetError, 'diagnosis_finding_invalid'): self.restore()

    def test_relaunch_uses_original_stage_and_cannot_recreate_missing_finding(self):
        # main creates a fresh card on relaunch; the authenticated source retains
        # the code-recorded stage for this same exhaustion ID.
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        self.c.card.pop('infrastructure_gate')
        self.persist()
        self.assertEqual(self.c.card['factory_bug']['gate_or_stage'], 'G10')
        finding = next((self.work / 'diagnosis').glob('*/finding.json'))
        finding.unlink()
        with self.assertRaisesRegex(budget.BudgetError, 'diagnosis_finding_invalid'): self.persist()
        self.assertFalse(finding.exists())

    def test_history_count_is_never_inferred_from_a_malformed_public_count(self):
        self.c.card['factory_bug_resume_count'] = 0
        with self.assertRaisesRegex(budget.BudgetError, 'factory_bug_history_invalid'): self.persist()
        self.assertNotIn('factory_bug_resume_count', self.c.card)
        (self.work / 'factory-bug-resumes.json').write_text('[]')
        self.c.card['factory_bug_resume_count'] = True
        with self.assertRaisesRegex(budget.BudgetError, 'factory_bug_history_invalid'): self.persist()
        self.assertNotIn('factory_bug_resume_count', self.c.card)

    def test_held_dispatch_refuses_before_lease_and_cannot_restart_diagnosis(self):
        import model_router
        import model_runtime
        import run
        self.persist()
        before = self.ledger.read_bytes()
        state = copy.deepcopy(self.c.card['diagnosis_state'])
        with patch.object(model_router, 'await_lease', side_effect=AssertionError('held case must not acquire')):
            with self.assertRaisesRegex(budget.BudgetError, '^factory_bug_held$'):
                run.model_call(self.c, self.c.models['builder'], 'no work', self.case, 'builder-held')
        diagnosis.record_exhaustion(self.c.card, new_exhaustion=True)
        self.assertEqual(self.c.card['diagnosis_state'], state)
        self.assertIsNone(diagnosis.pending_projection(self.c.card))
        self.assertEqual(self.ledger.read_bytes(), before)
        restored = type(self.c)(card={}, args=self.c.args, job_money=self.c.job_money)
        run.inherit_recovery_history(restored, self.c.card)
        self.assertEqual(restored.card['factory_bug'], self.c.card['factory_bug'])
        restored.card['factory_bug']['summary_class'] = 'changed copy'
        self.assertEqual(self.c.card['factory_bug']['summary_class'], 'factory_bug')
        with self.assertRaisesRegex(budget.BudgetError, '^factory_bug_held$'):
            with model_runtime.dispatch(restored, 'reviewer-held'): self.fail('held dispatch yielded')

    def test_result_requires_original_checkpoint_and_hash_bound_private_evidence(self):
        for change in (
            lambda value: value.update(checkpoint_sha256='f' * 64),
            lambda value: value.update(extra='authority'),
            lambda value: value['evidence'][0].update(path='../outside'),
            lambda value: value['evidence'][0].update(sha256='0' * 64),
            lambda value: value.update(outcome='close_to_passing'),
            lambda value: value.update(reason=''),
            lambda value: value['factory_bug'].update(affected_operations=['not-an-operation-id']),
        ):
            altered = copy.deepcopy(self.result); change(altered)
            with self.assertRaisesRegex(budget.BudgetError, 'diagnosis_result_invalid'): self.persist(altered)
        linked = self.inputs / 'linked'; linked.symlink_to(self.ledger)
        altered = copy.deepcopy(self.result); altered['evidence'][0]['path'] = 'linked'
        with self.assertRaisesRegex(budget.BudgetError, 'diagnosis_result_invalid'): self.persist(altered)
        with self.assertRaisesRegex(budget.BudgetError, 'diagnosis_result_invalid'):
            diagnosis.validate_result(self.result, case=self.c.case_id, generation=None, evidence_root=self.inputs)
        self.assertFalse((self.work / 'factory-bug-resumes.json').exists())

    def test_changed_immutable_evidence_refuses_finding_replay(self):
        self.persist()
        state = copy.deepcopy(self.c.card['diagnosis_state'])
        evidence = self.inputs / self.ledger.name
        evidence.write_bytes(evidence.read_bytes() + b'\n')
        with self.assertRaisesRegex(budget.BudgetError, 'diagnosis_result_invalid'): self.restore()
        self.assertEqual(self.c.card['diagnosis_state'], state)

    def test_persist_and_restore_apply_the_same_exact_finding_schema(self):
        self.persist()
        finding = next((self.work / 'diagnosis').glob('*/finding.json'))
        record = json.loads(finding.read_text()); record['schema_version'] = True
        finding.write_text(json.dumps(record))
        before = finding.read_bytes()
        for action in (self.persist, self.restore):
            with self.assertRaisesRegex(budget.BudgetError, 'diagnosis_finding_invalid'): action()
            self.assertEqual(finding.read_bytes(), before)

    def test_malformed_stage_metadata_is_content_free_unknown(self):
        self.c.checkpoint_card = {'diagnosis_state': None}
        self.c.card['infrastructure_gate'] = None
        self.persist()
        self.assertEqual(self.c.card['factory_bug']['gate_or_stage'], 'unknown')


if __name__ == '__main__': unittest.main()
