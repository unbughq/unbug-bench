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
        restored = type(self.c)()
        vars(restored).update(card={}, args=self.c.args, job_money=self.c.job_money)
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




class ResumeTests(unittest.TestCase):
    """Saved practice/5813be bytes; batch/finding transitions explicitly authored."""
    patch = runtime.RuntimeTests.patch

    def setUp(self):
        import test_stream_d_inputs as inputs
        import job_config
        inputs.InputTests.setUp(self)
        old_work = self.work
        self.work = old_work.with_name('case-source-j'); old_work.rename(self.work)
        self.case = self.work / 'case'
        self.bench = self.work / 'authored-bench'
        self.parent = self.work / 'diagnosis' / self.c.card['diagnosis_state']['exhaustion_id']
        self.patch(job_config, 'FACTORY', self.work / 'authored-release/factory')
        self.c.work, self.c.case, self.c.case_id = self.work, self.case, self.work.name
        self.c.card['case'] = self.c.case_id
        self.c.job_money.update(batch='source', job='j', case=self.c.case_id)
        self.c.authenticated_job_config['job_money'] = copy.deepcopy(self.c.job_money)
        self.c.batch_id, self.c.job_id = 'source', 'j'
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        self.install_receipt()
        self.old_release = self.c.args.batch_release_sha256
        recipient = (ROOT / 'factory/control-recipient.txt').read_text().strip()
        self.record = dict(schema=1, id='source', money_limit_usd=self.c.job_money['committed_total_usd'],
            batch_deadline=self.c.batch_deadline, max_concurrency=1, target_slots=1, restore_recipient=recipient,
            jobs={'j': dict(mode='batch', case=self.c.case_id, args=['1'],
                            requested_total_usd=self.c.job_money['committed_total_usd'])})
        self.c.authenticated_batch_manifest = copy.deepcopy(self.record)
        self.manifest = self.freeze()
        inputs.InputTests.persist(self, self.manifest)
        self.held_card = copy.deepcopy(self.c.card)
        self.transition('fixed', 'b'*64)

    def install_receipt(self, *args, **kwargs):
        import test_stream_d_inputs as inputs
        return inputs.InputTests.install_receipt(self, *args, **kwargs)

    def freeze(self):
        return diagnosis.queued_inputs(self.c, self.bench, quiescent=True)

    def result(self, manifest):
        import test_stream_d_inputs as inputs
        return inputs.InputTests.result(self, manifest)

    def transition(self, name, release, *, same_batch=False):
        from registry import atomic_json
        import job_config
        if not same_batch:
            release_path = job_config.FACTORY.parent / 'batch-release.json'
            release_value = json.loads(release_path.read_text()); release_value['authored_revision'] = release
            release_path.write_text(json.dumps(release_value))
            release = hashlib.sha256(release_path.read_bytes()).hexdigest()
        else: release = self.c.authenticated_job_config['batch_release_sha256']
        old = copy.deepcopy(self.c.job_money)
        old_record = copy.deepcopy(self.c.authenticated_batch_manifest)
        prior_release = self.c.authenticated_job_config['batch_release_sha256']
        source = hashlib.sha256((name + release + str(old['revision'])).encode()).hexdigest()
        new = {**old, 'batch': name, 'source_generation': source,
               'reservation_id': old['reservation_id'] if same_batch else str(uuid.uuid4()),
               'revision': old['revision'] + 1 if same_batch else 1}
        if not same_batch:
            raw = json.dumps(old_record)
            policy = dict(jobs=old_record['jobs'], batch=dict(id=old_record['id'], release='/authored',
                sha256=prior_release, manifest_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                manifest_path='factory/batches/' + old_record['id'] + '.json', max_concurrency=1))
            self.record = {**old_record, 'id': name, 'carry_from': dict(schema=1, manifest_json=raw,
                policy=policy, snapshot_sha256='f'*64, jobs={'j': dict(generation=source,
                    case=self.c.case_id, committed_total_usd=old['committed_total_usd'])})}
            self.c.authenticated_batch_manifest = copy.deepcopy(self.record)
        path = self.work / 'job-money-history.json'
        history = json.loads(path.read_text()) if path.exists() else {}
        history[new['reservation_id'] + '/' + str(new['revision']) + '/' + source] = dict(
            old=old, new=new, config_sha256='c'*64, source_generation=source)
        atomic_json(path, history)
        self.c.job_money = copy.deepcopy(new)
        self.c.authenticated_job_config.update(job_money=copy.deepcopy(new), batch_release_sha256=release)
        self.c.batch_id, self.c.job_id, self.c.source_generation = name, 'j', source
        self.c.args.batch_release_sha256 = release
        self.c.checkpoint_card = copy.deepcopy(self.c.card)

    def test_admission_keeps_real_ledger_and_replay_debits_once(self):
        before = self.ledger.read_bytes()
        self.assertTrue(diagnosis.resume_factory_bug(self.c))
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.c.card['factory_bug_resume_count'], 1)
        self.assertNotIn('factory_bug', self.c.card)
        diagnosis.require_model_work(self.c.card)
        history = (self.work / 'factory-bug-resumes.json').read_bytes()
        # Simulate a process replay from the held card after the durable append.
        self.c.card = copy.deepcopy(self.held_card)
        self.assertTrue(diagnosis.resume_factory_bug(self.c))
        self.assertEqual((self.work / 'factory-bug-resumes.json').read_bytes(), history)

    def test_dispatch_admits_before_replaying_hold_or_acquiring_a_lease(self):
        import diagnosis_dispatch
        import model_runtime
        import run
        with patch.object(model_runtime, 'prepare_dispatch', side_effect=AssertionError('no diagnosis model')):
            self.assertFalse(diagnosis_dispatch.dispatch(self.c, run))
        self.assertEqual(self.c.card['factory_bug_resume_count'], 1)
        diagnosis.require_model_work(self.c.card)

    def test_append_ahead_collected_checkpoint_repairs_through_money_transition(self):
        import diagnosis_dispatch
        import run
        real = diagnosis.atomic_json
        def fail(path, value):
            if path.name == 'scorecard.json': raise OSError('authored death before cleared card')
            real(path, value)
        with patch.object(diagnosis, 'atomic_json', fail), self.assertRaisesRegex(
                budget.BudgetError, 'factory_bug_resume_io_wait'):
            diagnosis_dispatch.dispatch(self.c, run)
        self.assertEqual(self.c.card['diagnosis_state'], self.held_card['diagnosis_state'])
        self.assertNotEqual(self.c.card.get('terminal_stop'), 'diagnosis_input_invalid')
        self.c.card = copy.deepcopy(self.held_card)
        self.transition('fixed', 'b'*64, same_batch=True)
        self.assertTrue(diagnosis.resume_factory_bug(self.c))
        self.assertEqual(self.c.card['factory_bug_resume_count'], 1)

    def test_same_admission_crossing_another_release_keeps_uuid(self):
        diagnosis.resume_factory_bug(self.c)
        history = (self.work / 'factory-bug-resumes.json').read_bytes()
        self.c.card = copy.deepcopy(self.held_card)
        self.transition('fixed-again', 'd'*64)
        self.assertTrue(diagnosis.resume_factory_bug(self.c))
        self.assertEqual((self.work / 'factory-bug-resumes.json').read_bytes(), history)

    def test_missing_history_and_changed_release_chain_never_admit(self):
        path = self.work / 'factory-bug-resumes.json'
        path.unlink()
        with self.assertRaisesRegex(budget.BudgetError, 'factory_bug_history_invalid'):
            diagnosis.resume_factory_bug(self.c)
        self.assertFalse(path.exists())
        self.assertNotIn('factory_bug_resume_count', self.c.card)
        self.c.card = copy.deepcopy(self.held_card)
        path.write_text('[]')
        self.c.authenticated_batch_manifest['carry_from']['policy']['batch']['sha256'] = '0'*64
        with self.assertRaises(budget.BudgetError): diagnosis.resume_factory_bug(self.c)
        self.assertEqual(json.loads(path.read_text()), [])

    def test_three_distinct_resumes_then_fourth_retires_before_work(self):
        for ordinal in range(4):
            if ordinal == 3:
                with self.assertRaisesRegex(budget.BudgetError, 'retired_factory_bug_limit'):
                    diagnosis.resume_factory_bug(self.c)
                self.assertEqual(self.c.card['factory_bug_resume_count'], 3)
                break
            self.assertTrue(diagnosis.resume_factory_bug(self.c))
            self.assertEqual(self.c.card['factory_bug_resume_count'], ordinal + 1)
            self.c.card.update(status='stopped', terminal_stop='infrastructure_exhausted',
                               infrastructure_gate={'gate': 'G10', 'exhausted': True})
            diagnosis.record_exhaustion(self.c.card, new_exhaustion=True)
            self.c.checkpoint_card = copy.deepcopy(self.c.card)
            self.install_receipt()
            manifest = self.freeze()
            self.parent = self.work / 'diagnosis' / manifest['exhaustion_id']
            diagnosis.persist_factory_bug(self.c, self.result(manifest), generation=manifest['generation'],
                                         evidence_root=self.parent / 'inputs')
            # Keep the authored source pin consistent for frozen source capture.
            self.transition('fixed-' + str(ordinal), str(ordinal + 5)*64)


if __name__ == '__main__': unittest.main()
