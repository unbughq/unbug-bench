"""Real saved-practice G1 rejection through admitted writer completion.

The writer output/usage acknowledgement are authored external controls. No
stress/model/Docker worker runs. Terminal outcomes retain those same observations.
"""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import extension_package as package
import extensions
import gate_state
import registry
import run
from run_validity import InvalidInfra
import test_stream_d_execution as execution
import test_stream_d_runtime as runtime
import test_stream_d_extensions as states
from test_extension_compare import cached_source_inputs


class WriterG1Tests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    snapshot = states.ExtensionTests.snapshot
    diagnosis = states.ExtensionTests.diagnosis
    saved = execution.ExecutionTests.saved

    def setUp(self):
        self.patch(gate_state, 'source_inputs', cached_source_inputs)
        execution.ExecutionTests.setUp(self)
        (self.work / 'logs').mkdir(exist_ok=True)
        self.c.manifest0 = run.bench_manifest()
        self.g1.side_effect = execution.REAL_G1
        self.records = package.Records(self.c, run, self.row)
        self.path = self.records.root / 'G1/record.json'

    def package(self):
        return package.run(self.c, run, self.prev, 1)

    def held(self):
        with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'):
            self.package()

    def rejected(self):
        data = self.records.load('G1')
        self.assertIs(data['ok'], False)
        self.assertEqual(data['info']['problems'], ['case.json source differs from the run argument'])
        self.assertEqual(data['writer_operation_id'], self.row['writer_operation_id'])
        self.assertEqual(data['round'], 9)
        self.assertEqual(data['case_sha256'], run.case_hash(self.c))
        for name in ('case.json', 'base/app.patch', 'promise.md'):
            saved = next(self.work / p for p in data['support'] if p.endswith('/case/' + name))
            self.assertEqual(saved.read_bytes(), (self.case / name).read_bytes())
        self.assertFalse((self.records.root / 'stress/record.json').exists())
        self.assertIsNotNone(extensions.read(self.c)[-1]['outcome'])
        if self.saved()['phase'] == 'validated':
            self.assertEqual(self.saved()['stop_reason'], 'rounds_exhausted')
            self.assertIs(self.saved()['exhausted'], True)
        else: self.assertEqual(self.saved()['phase'], 'completed')
        self.early.assert_not_called()
        return data

    def test_fresh_writer_retains_actual_rejection(self):
        self.held(); self.rejected()
        self.assertEqual(self.calls, ['builder-9'])
        self.g1.assert_called_once()

    def test_completed_writer_retains_rejection_without_writer_call(self):
        (self.case / 'draft.txt').write_text('authored changed draft')
        run.complete_writer(self.c, self.saved(), self.work / 'attack-state.json')
        self.held(); self.rejected()
        self.assertEqual(self.calls, [])
        self.g1.assert_called_once()

    def test_done_writer_retains_rejection_without_writer_call(self):
        (self.case / 'draft.txt').write_text('authored changed draft')
        with patch.object(run, 'writer_call_done', return_value=True): self.held()
        self.rejected(); self.assertEqual(self.calls, [])
        self.g1.assert_called_once()

    def test_kill_after_record_before_receipt_replays_without_g1(self):
        original = package.Records.save
        def killed(records, *args):
            original(records, *args)
            raise runtime.Killed()
        with patch.object(package.Records, 'save', killed):
            with self.assertRaises(runtime.Killed): self.package()
        self.assertEqual(self.saved()['phase'], 'completed')
        before = self.path.read_bytes()
        self.g1.side_effect = AssertionError('G1 rerolled')
        self.held(); self.rejected()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.calls, ['builder-9'])
        self.g1.assert_called_once()

    def test_kill_before_publication_can_repeat_local_contract_only(self):
        with patch.object(package.Records, 'save', side_effect=runtime.Killed):
            with self.assertRaises(runtime.Killed): self.package()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.saved()['phase'], 'completed')
        self.held(); self.rejected()
        self.assertEqual(self.calls, ['builder-9'])
        self.assertEqual(self.g1.call_count, 2)

    def test_legacy_validated_receipt_is_not_reconstructed(self):
        # Use the existing default writer loop to produce the legacy gap.
        with self.assertRaisesRegex(budget.BudgetError, '^stress_review_unresolved:rounds_exhausted$'):
            run.write_and_attack(self.c, self.prev, extension_id=1)
        self.assertFalse(self.path.exists())
        self.g1.side_effect = AssertionError('legacy G1 inferred')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_execution_pending$'): self.package()
        self.assertFalse(self.path.exists())
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        self.assertEqual(self.calls, ['builder-9'])

    def test_pass_does_not_publish_pre_stress_record(self):
        self.g1.side_effect = None
        self.g1.return_value = True, {'problems': []}  # Authored routing control.
        with patch.object(package, 'stress', side_effect=budget.BudgetError('test_stress_handoff')):
            with self.assertRaisesRegex(budget.BudgetError, '^test_stress_handoff$'): self.package()
        self.assertEqual(self.calls, ['builder-9', 'attacker-9'])
        self.early.assert_called_once()
        self.assertFalse(self.path.exists())

    def test_false_without_problems_continues_without_rejection_record(self):
        self.g1.side_effect = None
        self.g1.return_value = False, {'problems': []}  # Authored non-rejection control.
        with patch.object(package, 'stress', side_effect=budget.BudgetError('test_stress_handoff')):
            with self.assertRaisesRegex(budget.BudgetError, '^test_stress_handoff$'): self.package()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.calls, ['builder-9', 'attacker-9'])

    def test_pending_and_exception_controls_keep_original_result(self):
        for result in ((False, {'error': 'authored pending'}),
                       (False, {'classification': 'invalid-infra'}),
                       (True, {'verdict_valid': False})):
            invoke = Mock(return_value=result)
            self.assertEqual(self.records.writer_g1(self.c, invoke), result)
            invoke.assert_called_once(); self.assertFalse(self.path.exists())
        for error in (InvalidInfra('authored infrastructure'), budget.BudgetError('money_wait')):
            invoke = Mock(side_effect=error)
            with self.assertRaises(type(error)) as caught: self.records.writer_g1(self.c, invoke)
            self.assertIs(caught.exception, error)
            invoke.assert_called_once(); self.assertFalse(self.path.exists())

    def test_record_and_support_refusals_never_invoke(self):
        self.held(); data = self.rejected()
        invoke = Mock(side_effect=AssertionError('unverified G1'))
        support = self.work / next(iter(data['support']))
        original = support.read_bytes()
        for mode in ('tamper', 'missing', 'symlink'):
            with self.subTest(mode=mode):
                support.unlink()
                if mode == 'tamper': support.write_bytes(b'changed')
                if mode == 'symlink': support.symlink_to(self.case / 'case.json')
                with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
                    self.records.writer_g1(self.c, invoke)
                if support.exists() or support.is_symlink(): support.unlink()
                support.write_bytes(original)
        (self.case / 'draft.txt').write_text('tampered case')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
            self.records.writer_g1(self.c, invoke)
        (self.case / 'draft.txt').write_text('authored changed draft')
        with patch.object(gate_state, 'scientific_version', return_value='d' * 64):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_comparison_pending$'):
                self.records.writer_g1(self.c, invoke)
        envelope = json.loads(self.path.read_text())
        envelope['record']['ok'] = True
        envelope['sha256'] = extensions.digest(envelope['record'])
        registry.atomic_json(self.path, envelope)
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
            self.records.writer_g1(self.c, invoke)
        invoke.assert_not_called()

    def test_package_version_drift_completes_historical_rejection(self):
        original = package.Records.save
        def killed(records, *args):
            original(records, *args)
            raise runtime.Killed()
        with patch.object(package.Records, 'save', killed):
            with self.assertRaises(runtime.Killed): self.package()
        self.g1.side_effect = AssertionError('drift reroll')
        with patch.object(package.Records, 'version', return_value='d' * 64): self.held()
        self.assertEqual(self.saved()['phase'], 'completed')
        self.assertEqual(self.calls, ['builder-9'])


if __name__ == '__main__': unittest.main()
