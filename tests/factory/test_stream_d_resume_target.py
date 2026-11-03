"""Focused return-target controls on saved practice/5813be bytes.

Real diagnosis journal, reservation, freeze, finding and admission functions.
Owner transitions are authored IN PLACE, not checkpoint archive/restore.
Snapshot controls below do not qualify subsequent_entry/pair-attempts or close
new-stream-d-current-comparison-1. That integrated chain stays on item 8.
"""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import batch_service
import budget
import diagnosis
import diagnosis_dispatch as dispatch
import extension_package
import extensions
import job_config
import run
import test_stream_d_dispatch as dispatch_tests
import test_stream_d_held as held_tests
import test_stream_d_inputs as input_tests
import test_stream_d_extensions as extension_tests
from registry import atomic_json


class Crash(BaseException): pass


class ReturnTargetTests(unittest.TestCase):
    patch = dispatch_tests.DispatchTests.patch
    install_receipt = input_tests.InputTests.install_receipt
    freeze = input_tests.InputTests.freeze
    result = input_tests.InputTests.result
    helper = dispatch_tests.DispatchTests.helper
    call = dispatch_tests.DispatchTests.call
    writable_tasks = dispatch_tests.DispatchTests.writable_tasks
    resume = dispatch_tests.DispatchTests.resume
    transition = held_tests.ResumeTests.transition
    admit_active_control = dispatch_tests.DispatchTests.admit_active_control

    def setUp(self):
        dispatch_tests.DispatchTests.setUp(self)
        # Same authored owner-chain envelope as ResumeTests, in this existing
        # DispatchTests tree. No fixture claims an extension comparison here.
        old_work = self.work
        self.work = old_work.with_name('case-source-j'); old_work.rename(self.work)
        self.case = self.work / 'case'
        self.bench = self.work / 'authored-bench'
        c = self.c
        c.work, c.case, c.case_id = self.work, self.case, self.work.name
        c.card['case'] = c.case_id
        self.ledger = self.ledger.rename(self.ledger.with_name(c.case_id + '.continuation-budget.json'))
        c.ledger = self.ledger
        self.parent = self.work / 'diagnosis' / c.card['diagnosis_state']['exhaustion_id']
        self.patch(job_config, 'FACTORY', self.work / 'authored-release/factory')
        self.patch(run, 'BENCH', self.bench)
        c.job_money.update(batch='source', job='j', case=c.case_id)
        c.authenticated_job_config['job_money'] = copy.deepcopy(c.job_money)
        c.batch_id, c.job_id = 'source', 'j'
        self.record = dict(schema=1, id='source', money_limit_usd=c.job_money['committed_total_usd'],
            batch_deadline=c.batch_deadline, max_concurrency=1, target_slots=1,
            restore_recipient=(ROOT / 'factory/control-recipient.txt').read_text().strip(),
            jobs={'j': dict(mode='batch', case=c.case_id, args=['1'],
                           requested_total_usd=c.job_money['committed_total_usd'])})
        c.authenticated_batch_manifest = copy.deepcopy(self.record)
        c.checkpoint_card = copy.deepcopy(c.card)
        self.install_receipt()
        self.target = self.work / 'extension-resume.json'
        self.patch(run, 'build', side_effect=AssertionError('ordinary construction'))
        self.patch(run, 'validate_and_repair', side_effect=AssertionError('ordinary validation'))
        self.answer = 'close_to_passing'

    def choose(self):
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True):
            self.assertEqual(dispatch.dispatch(self.c, run, comparison_route=True), 0)
        self.original_state = copy.deepcopy(self.c.card['diagnosis_state'])
        self.original_parent = self.parent
        return self.original_state

    def hold(self):
        self.choose()
        # Authored infrastructure stop, not a subsequent_entry exhaustion claim.
        self.c.card.update(status='stopped', terminal_stop='infrastructure_exhausted',
                           infrastructure_gate={'gate': 'G10', 'exhausted': True})
        self.c.card.pop('failed_gate', None)
        self.c.card.pop('failed_detail', None)
        self.c.stopped = self.c.exhaustion_occurred = True
        run.finalize_accounting(self.c)
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        self.install_receipt()
        self.parent = self.work / 'diagnosis' / self.c.card['diagnosis_state']['exhaustion_id']
        self.answer = 'factory_bug'
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), self.assertRaisesRegex(
                budget.BudgetError, '^factory_bug_held$'):
            dispatch.dispatch(self.c, run, comparison_route=True)
        self.held = copy.deepcopy(self.c.card)
        self.transition('fixed', 'b' * 64)
        self.assertEqual((self.parent / 'inputs/work/extension-resume.json').read_bytes(),
                         self.target.read_bytes())

    def replay(self):
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), patch.object(
                run, 'opencode', side_effect=AssertionError('extra diagnosis')):
            return dispatch.dispatch(self.c, run, comparison_route=True)

    def test_enabled_selection_retains_before_card_and_replay_preserves_bytes(self):
        writes = []
        real = dispatch.atomic_json
        def publish(path, value):
            if path.name == 'scorecard.json':
                self.assertTrue(self.target.is_file())
                writes.append(path)
            return real(path, value)
        with patch.object(dispatch, 'atomic_json', side_effect=publish): self.choose()
        self.assertTrue(writes)
        saved = self.target.read_bytes()
        record = json.loads(saved)['record']
        self.assertEqual(record['diagnosis_state'], self.original_state)
        calls = list(self.calls)
        self.resume()
        self.assertEqual(self.replay(), 0)
        self.assertEqual(self.target.read_bytes(), saved)
        self.assertEqual(self.calls, calls)

    def test_disabled_selection_does_not_publish_a_route(self):
        manifest = self.freeze()
        result = self.result(manifest)
        result.update(outcome='close_to_passing', factory_bug=None)
        with self.assertRaisesRegex(budget.BudgetError, '^extension_comparison_pending$'):
            dispatch.apply(self.c, self.parent, manifest, result)
        self.assertFalse(self.target.exists())

    def test_in_place_resume_replays_original_journal_and_restores_atomically(self):
        self.hold()
        original = extensions.tree(self.original_parent)
        before = self.ledger.read_bytes()
        checkpoint = copy.deepcopy(self.c.checkpoint_card)
        writes = []
        real = diagnosis.atomic_json
        def publish(path, value):
            if path.name == 'scorecard.json':
                writes.append(copy.deepcopy(value))
                self.assertEqual(value['diagnosis_state'], self.original_state)
                self.assertNotIn('factory_bug', value)
            return real(path, value)
        with patch.object(diagnosis, 'atomic_json', side_effect=publish):
            self.assertEqual(self.replay(), 0)
        self.assertTrue(writes)
        self.assertEqual(self.c.checkpoint_card, checkpoint)
        self.assertEqual(self.c.card['diagnosis_state'], self.original_state)
        self.assertEqual(self.c.card['factory_bug_resume_count'], 1)
        self.assertEqual(extensions.tree(self.original_parent), original)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(len(self.calls), 2)

    def test_kill_after_admission_before_card_clear_reuses_admission(self):
        self.hold()
        real = diagnosis.atomic_json
        def publish(path, value):
            if path.name == 'scorecard.json': raise Crash()
            return real(path, value)
        with patch.object(diagnosis, 'atomic_json', side_effect=publish), self.assertRaises(Crash):
            self.replay()
        self.assertEqual(self.c.card['diagnosis_state'], self.held['diagnosis_state'])
        admission = (self.work / 'factory-bug-resumes.json').read_bytes()
        self.resume()
        self.assertEqual(self.replay(), 0)
        self.assertEqual((self.work / 'factory-bug-resumes.json').read_bytes(), admission)
        self.assertEqual(self.c.card['factory_bug_resume_count'], 1)

    def test_kill_after_cleared_card_replays_without_another_debit(self):
        self.hold()
        real = diagnosis.atomic_json
        def publish(path, value):
            real(path, value)
            if path.name == 'scorecard.json': raise Crash()
        with patch.object(diagnosis, 'atomic_json', side_effect=publish), self.assertRaises(Crash):
            self.replay()
        self.c.card = json.loads((self.work / 'scorecard.json').read_text())
        self.resume()
        admission = (self.work / 'factory-bug-resumes.json').read_bytes()
        self.assertEqual(self.replay(), 0)
        self.assertEqual((self.work / 'factory-bug-resumes.json').read_bytes(), admission)

    def test_restored_decision_recovers_admitted_writer_without_second_admission(self):
        self.hold()
        self.assertEqual(self.replay(), 0)
        # Authored snapshot/CLI controls from DispatchTests; real pending_call
        # commits the writer then dies before attack-state publication.
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True):
            row = self.admit_active_control(1)
        history = (self.work / 'extension-history.json').read_bytes()
        ledger = self.ledger.read_bytes()
        self.resume()
        self.assertEqual(self.replay(), row['extension_id'])
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), history)
        self.assertEqual(self.ledger.read_bytes(), ledger)
        self.assertEqual(json.loads((self.work / 'attack-state.json').read_text()), self.admitted_receipt)

    def test_completed_successor_uses_existing_completed_route(self):
        self.hold()
        self.assertEqual(self.replay(), 0)
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True):
            row = self.admit_active_control(1)
        # Authored snapshot, not scientific package proof. Control only the
        # completed_route seam to isolate the dispatch identity contract.
        extensions.complete(self.c, extension_tests.ExtensionTests.snapshot(self, 2))
        # Real extension history/ledger/snapshot validation with authored
        # scientific snapshots. This does not prove subsequent_entry execution.
        root = self.parent / 'inputs'
        before = copy.deepcopy(self.c.card)
        self.assertEqual(diagnosis._extension_resume_state(self.c, root), self.original_state)
        self.assertEqual(self.c.card, before)
        record = self.target.read_bytes()
        self.target.unlink()
        with self.assertRaisesRegex(diagnosis.FactoryBugHeldWait, '^extension_resume_target_invalid$'):
            diagnosis._extension_resume_state(self.c, root)
        self.target.write_bytes(record)
        self.resume()
        with patch.object(extension_package, 'completed_route') as completed:
            self.assertEqual(self.replay(), row['extension_id'])
        completed.assert_called_once()
        self.assertEqual(completed.call_args.args[1]['extension_id'], row['extension_id'])

    def test_disabled_after_admission_keeps_replay_state_and_one_debit(self):
        self.hold()
        with patch.object(run, 'opencode', side_effect=AssertionError('extra diagnosis')), self.assertRaisesRegex(
                budget.BudgetError, '^extension_comparison_pending$'):
            dispatch.dispatch(self.c, run, comparison_route=True)
        self.assertEqual(self.c.card['diagnosis_state'], self.original_state)
        admission = (self.work / 'factory-bug-resumes.json').read_bytes()
        self.resume()
        self.assertEqual(self.replay(), 0)
        self.assertEqual((self.work / 'factory-bug-resumes.json').read_bytes(), admission)

    def test_record_corruption_refuses_before_new_debit_and_never_guesses(self):
        self.hold()
        saved = self.target.read_bytes()
        history = (self.work / 'factory-bug-resumes.json').read_bytes()
        for fault in ('missing', 'json', 'shape', 'digest', 'state', 'link'):
            with self.subTest(fault=fault):
                self.target.unlink(missing_ok=True)
                if fault == 'json': self.target.write_text('{')
                if fault == 'shape': atomic_json(self.target, [])
                if fault in ('digest', 'state'):
                    value = json.loads(saved)
                    if fault == 'digest': value['sha256'] = '0' * 64
                    else: value['record']['diagnosis_state']['outcome'] = 'not_converging'
                    atomic_json(self.target, value)
                if fault == 'link':
                    backing = self.work / 'authored-target'; backing.write_bytes(saved)
                    self.target.symlink_to(backing)
                with self.assertRaisesRegex(diagnosis.FactoryBugHeldWait, '^extension_resume_target_invalid$'):
                    diagnosis.resume_factory_bug(self.c, run)
                self.assertEqual((self.work / 'factory-bug-resumes.json').read_bytes(), history)
                self.assertEqual(self.c.card['diagnosis_state'], self.held['diagnosis_state'])
        self.target.unlink()
        self.target.write_bytes(saved)
        original = diagnosis._input_bytes
        with patch.object(diagnosis, '_input_bytes', wraps=original) as read:
            def denied(path, base):
                if path == self.target: raise PermissionError('authored record read denial')
                return original(path, base)
            read.side_effect = denied
            with self.assertRaisesRegex(diagnosis.FactoryBugHeldWait, '^extension_resume_target_invalid$'):
                diagnosis.resume_factory_bug(self.c, run)

    def test_frozen_record_mismatch_and_missing_post_extension_target_refuse(self):
        self.hold()
        root = self.parent / 'inputs'
        frozen = root / 'work/extension-resume.json'
        original = frozen.read_bytes()
        for payload in (b'{}', b'[]'):
            frozen.write_bytes(payload)
            with self.assertRaisesRegex(diagnosis.FactoryBugHeldWait, '^extension_resume_target_invalid$'):
                diagnosis._extension_resume_state(self.c, root)
        frozen.unlink()
        with self.assertRaisesRegex(diagnosis.FactoryBugHeldWait, '^extension_resume_target_invalid$'):
            diagnosis._extension_resume_state(self.c, root)
        self.target.unlink()
        # No post-extension history is the ordinary pre-extension case.
        self.assertIsNone(diagnosis._extension_resume_state(self.c, root))
        # Authored history-presence control tests legacy refusal only, not
        # scientific snapshot verification or an active-extension factory hold.
        with patch.object(extensions, 'read', return_value=[{'authored_presence': True}]):
            with self.assertRaisesRegex(diagnosis.FactoryBugHeldWait, '^extension_resume_target_invalid$'):
                diagnosis._extension_resume_state(self.c, root)
        frozen.write_bytes(original)
        self.target.write_bytes(original)

    def test_reused_admission_checks_live_record_again(self):
        self.hold()
        real = diagnosis.atomic_json
        def publish(path, value):
            if path.name == 'scorecard.json': raise OSError('authored publication loss')
            return real(path, value)
        with patch.object(diagnosis, 'atomic_json', side_effect=publish), self.assertRaisesRegex(
                diagnosis.FactoryBugHeldWait, '^factory_bug_resume_io_wait$'):
            self.replay()
        history = (self.work / 'factory-bug-resumes.json').read_bytes()
        self.target.unlink()
        with self.assertRaisesRegex(diagnosis.FactoryBugHeldWait, '^extension_resume_target_invalid$'):
            diagnosis.resume_factory_bug(self.c, run)
        self.assertEqual((self.work / 'factory-bug-resumes.json').read_bytes(), history)

    def test_missing_original_decision_artifacts_never_buys_diagnosis(self):
        self.hold()
        (self.original_parent / 'input.json').unlink()
        with self.assertRaisesRegex(budget.BudgetError, '^diagnosis_input_invalid$'):
            self.replay()
        self.assertEqual(self.c.card['factory_bug_resume_count'], 1)
        self.assertEqual(len(self.calls), 2)

    def test_same_state_is_idempotent_new_state_replaces_corrupt_state_refuses(self):
        self.choose()
        before = self.target.read_bytes()
        diagnosis.retain_extension_resume(self.c, self.original_state)
        self.assertEqual(self.target.read_bytes(), before)
        changed = {**self.original_state, 'exhaustion_id': str(uuid.uuid4())}
        # Authored new validated-state unit input, not a new model decision.
        diagnosis.retain_extension_resume(self.c, changed)
        self.assertEqual(json.loads(self.target.read_text())['record']['diagnosis_state'], changed)
        self.target.write_text('{}')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_resume_target_invalid$'):
            diagnosis.retain_extension_resume(self.c, self.original_state)


if __name__ == '__main__': unittest.main()
