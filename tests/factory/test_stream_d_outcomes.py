"""Diagnosis admission consumer over saved practice bytes and 5813be usage.

Entry snapshots and CLI output are authored controls. Real money/history/intent
and continuation run; this does not qualify lane 2's scientific entry producer.
"""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import diagnosis_dispatch as dispatch
import extension_package
import extensions
import model_router
import model_runtime
import registry
import run
import test_stream_d_runtime as runtime
import test_stream_d_extensions as states


class OutcomeTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    snapshot = states.ExtensionTests.snapshot
    diagnosis = states.ExtensionTests.diagnosis
    begin = states.ExtensionTests.begin
    reserve = states.ExtensionTests.reserve

    def setUp(self):
        runtime.RuntimeTests.setUp(self)
        self.diagnosis()
        self.c.args.case_budget = self.c.args.ordinary_case_budget = .01
        self.c.args.resume = self.c.case_id
        self.c.card['builder_rounds'] = 8
        self.c.card['gate_continuation'] = {'old': True}
        (self.work / 'gate-continuation.json').write_text('{"old":true}')
        self.prev = {'failed_gate': 'G8', 'failed_detail': ['authored code finding']}
        self.entry = self.snapshot(1)
        self.entry_mock = self.patch(extension_package, 'entry', return_value=self.entry, create=True)
        self.patch(run, 'prompt', lambda role, text: text)
        self.patch(run, 'run_context', lambda c, **kw: json.dumps(kw))
        self.calls = []
        def invoke(rt, c, models, text, cwd, name, **kwargs):
            self.assertNotIn('gate_continuation', c.card)
            self.assertFalse((self.work / 'gate-continuation.json').exists())
            row = extensions.active(c)
            self.assertEqual(row['round'], 9)
            self.calls.append((name, json.loads(text), row['writer_operation_id']))
            c.model_process_state['started'] = True
            (self.case / 'draft.txt').write_text('authored repaired case')
            return 0
        self.invoke = self.patch(model_runtime.ModelRuntime, '_invoke', invoke)

    def admit(self):
        return dispatch.admit_extension(self.c, run, self.prev)

    def test_first_writer_is_reserved_completed_and_not_repeated_on_resume(self):
        self.assertEqual(self.admit(), 1)
        row = extensions.active(self.c)
        receipt = extensions.writer_receipt(self.c)
        self.assertEqual(receipt['phase'], 'completed')
        self.assertEqual(receipt['round_limit'], 9)
        self.assertEqual(receipt['operation_id'], row['writer_operation_id'])
        self.assertIsNone(receipt['findings_report'])
        self.assertEqual(receipt['input_problems'], run.writer_feedback(self.c, self.prev))
        self.assertEqual(self.calls[0][1]['precheck_problems'], receipt['input_problems'])
        self.assertIsNone(self.calls[0][1]['attack_report'])
        for _ in range(2):
            self.assertEqual(extensions.writer_receipt(self.c)['phase'], 'completed')
            with self.assertRaisesRegex(budget.BudgetError, '^extension_already_active$'): self.admit()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(extensions.read(self.c)), 1)
        self.assertEqual(self.c.args.rounds, 8)

    def test_missing_entry_and_stale_authority_admit_nothing(self):
        with patch.object(extension_package, 'entry', None):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_comparison_pending$'): self.admit()
        self.c.authenticated_job_config['job_money']['source_generation'] = 'f' * 64
        with self.assertRaisesRegex(budget.BudgetError, '^money_wait$'): self.admit()
        self.entry_mock.assert_not_called()
        self.assertEqual(extensions.read(self.c), [])
        self.assertEqual(self.calls, [])

    def test_no_progress_stress_failure_and_pending_do_not_reserve(self):
        for snapshot, label in ((self.snapshot(0), 'retired_no_progress'),
                                (self.snapshot(1), 'extension_execution_pending')):
            if label == 'extension_execution_pending': snapshot['stages'][1]['status'] = 'pending'
            self.entry_mock.return_value = snapshot
            with self.assertRaisesRegex(budget.BudgetError, '^' + label + '$'): self.admit()
        self.assertEqual(extensions.read(self.c), [])
        self.assertFalse(json.loads(self.ledger.read_text()).get('invocation_reservations'))

    def test_five_entries_refuse_before_scientific_entry_or_writer(self):
        for n in range(1, 6):
            self.begin(self.snapshot(n))
            extensions.complete(self.c, self.snapshot(n + 1))
        self.diagnosis()
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(budget.BudgetError, '^retired_extension_limit$'): self.admit()
        self.entry_mock.assert_not_called()
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(len(extensions.read(self.c)), 5)
        self.assertEqual(self.calls, [])

    def test_regression_no_progress_and_version_drift_cannot_buy_extension(self):
        self.begin(self.snapshot(2))
        extensions.complete(self.c, self.snapshot(2))
        self.diagnosis()
        for snapshot, label in ((self.snapshot(2), 'retired_no_progress'),
                                (self.snapshot(2, 'c'), 'extension_comparison_pending')):
            self.entry_mock.return_value = snapshot
            with self.assertRaisesRegex(budget.BudgetError, '^' + label + '$'): self.admit()
        regression = self.snapshot(1, 'c')
        regression['stages'][1].update(status='fail', binding_sha256='b' * 64,
            evidence_sha256=next(iter(regression['evidence'].values())))
        extensions.retain_comparison(self.c, 1, self.snapshot(2, 'c'), regression)
        self.entry_mock.return_value = regression
        with self.assertRaisesRegex(budget.BudgetError, '^retired_no_progress$'): self.admit()
        self.assertEqual(len(extensions.read(self.c)), 1)
        self.assertEqual(self.calls, [])

    def test_money_and_provider_wait_before_reservation_consume_no_id(self):
        before = self.ledger.read_bytes()
        with patch.object(model_router, 'await_lease', side_effect=budget.BudgetError('provider_wait')):
            with self.assertRaisesRegex(budget.BudgetError, '^provider_wait$'): self.admit()
        self.assertEqual(self.ledger.read_bytes(), before)
        self.c.job_money['committed_total_usd'] = str(self.baseline)
        self.c.authenticated_job_config['job_money'] = copy.deepcopy(self.c.job_money)
        with self.assertRaisesRegex(budget.BudgetError, '^money_wait$'): self.admit()
        self.assertFalse((self.work / 'extension-history.json').exists())
        self.assertFalse((self.work / 'attack-state.json').exists())
        self.assertTrue((self.work / 'gate-continuation.json').exists())
        self.assertEqual(self.calls, [])

    def test_orphaned_intent_books_once_and_cannot_grant_or_reuse_operation(self):
        captured = []
        def killed(*args):
            captured.append(self.ledger.read_bytes())
            raise runtime.Killed()
        with patch.object(extensions, 'admit', side_effect=killed):
            with self.assertRaises(runtime.Killed): self.admit()
        # Restore the image before Python unwind, as a process kill would leave it.
        self.ledger.write_bytes(captured[0])
        orphan, = json.loads(self.ledger.read_text())['invocation_reservations'].values()
        self.assertTrue((self.work / 'extension-writers' / (orphan['operation_id'] + '.json')).is_file())
        for _ in range(2): budget.reconcile_reservations(self.work, self.ledger)
        total = budget.case_spending(json.loads(self.ledger.read_text()))['total_spent_usd']
        self.assertAlmostEqual(total, self.baseline + float(orphan['maximum_usd']), places=8)
        self.assertEqual(extensions.read(self.c), [])
        self.assertEqual(self.admit(), 1)
        self.assertNotEqual(extensions.active(self.c)['writer_operation_id'], orphan['operation_id'])
        self.assertEqual(len(self.calls), 1)

    def test_history_before_callback_recovers_intent_and_invalidates_before_writer(self):
        atomic = extensions.atomic_json
        def killed(path, value):
            atomic(path, value)
            if Path(path).name == 'extension-history.json': raise runtime.Killed()
        with patch.object(extensions, 'atomic_json', killed):
            with self.assertRaises(runtime.Killed): self.admit()
        row = extensions.active(self.c)
        self.assertTrue((self.work / 'gate-continuation.json').exists())
        self.assertFalse((self.work / 'attack-state.json').exists())
        receipt = extensions.writer_receipt(self.c)
        self.assertEqual(receipt['phase'], 'pending')
        self.assertEqual(receipt['operation_id'], row['writer_operation_id'])
        with patch.object(run, 'g1', return_value=(False, {'problems': ['authored invalid output']})), \
                patch.object(run, 'early_checks', side_effect=AssertionError('no early work')):
            with self.assertRaisesRegex(budget.BudgetError, 'rounds_exhausted'):
                run.write_and_attack(self.c, self.prev, extension_id=1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][2], row['writer_operation_id'])
        self.assertEqual(len(extensions.read(self.c)), 1)

    def test_mid_writer_continues_same_operation_and_completed_writer_never_repeats(self):
        with patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=runtime.Killed):
            with self.assertRaises(runtime.Killed): self.admit()
        row = extensions.active(self.c)
        self.assertEqual(extensions.writer_receipt(self.c)['phase'], 'pending')
        with patch.object(run, 'g1', return_value=(False, {'problems': ['authored invalid output']})):
            with self.assertRaisesRegex(budget.BudgetError, 'rounds_exhausted'):
                run.write_and_attack(self.c, self.prev, extension_id=1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][2], row['writer_operation_id'])
        self.assertEqual(len(extensions.read(self.c)), 1)

    def test_kill_after_writer_completion_validates_without_second_writer(self):
        self.admit()
        with patch.object(run, 'g1', return_value=(False, {'problems': ['authored invalid output']})):
            with self.assertRaisesRegex(budget.BudgetError, 'rounds_exhausted'):
                run.write_and_attack(self.c, self.prev, extension_id=1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(extensions.read(self.c)), 1)


if __name__ == '__main__': unittest.main()
