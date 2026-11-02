"""Early rejection on saved checkpoint bytes and admitted writer receipts.

G1/G15/G3 passes and writer completion are labelled controls. Real G4/G5 and
saved-cheat judging consume saved executions; no live worker/model is used.
"""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
from case_contract import CaseProblem
import extension_package as package
import extensions
import gate_state
import registry
import run
from run_validity import InvalidInfra, require_valid
import test_stream_d_execution as execution_tests
import test_stream_d_runtime as runtime
import test_stream_d_extensions as states
from test_extension_compare import REAL, execution, cached_source_inputs

REAL_EARLY = run.early_checks


class EarlyWriterTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    snapshot = states.ExtensionTests.snapshot
    diagnosis = states.ExtensionTests.diagnosis
    saved = execution_tests.ExecutionTests.saved

    def setUp(self):
        self.patch(gate_state, 'source_inputs', cached_source_inputs)
        execution_tests.ExecutionTests.setUp(self)
        (self.work / 'logs').mkdir(exist_ok=True)
        (self.case / 'case.json').write_text(json.dumps(REAL['suffix-case']['files']['case.json']))
        self.c.args.rehearse_only = True  # Real G5 reference test, no scenario workers.
        self.c.args.runs = 1
        self.c.args.bench_workers = 2
        self.c.manifest0 = run.bench_manifest()
        self.early.side_effect = REAL_EARLY
        self.pipeline = run._gate_pipeline()
        self.pipeline.publish = self.pipeline.log = lambda *a: None
        self.patch(run, '_gate_pipeline', return_value=self.pipeline)
        self.executed = []
        self.failure = 'G5'
        def check(c, stage):
            self.executed.append(stage)
            if stage == 'G3':
                c.args.bench_workers = 1
                c.card['bench_workers_effective'] = 1
            if stage == 'G15':
                return self.failure != 'G15', {'authored_stage_control': stage}
            if stage == 'G3': return True, {'authored_stage_control': stage}
            return getattr(run, stage.lower())(c)
        self.pipeline.check = check
        self.transports = []
        def checkpoint(c, overlays, guard, runs, seed, tag, **kwargs):
            label = 'plain' if tag == 'g4-none' or self.failure == 'G5' else 'reference'
            saved = execution(label)
            require_valid(saved['summary'], saved['records'])
            self.transports.append((tag, saved))
            # Saved execution transport is retained in the ordinary inventory.
            path = self.work / 'gate-details' / (tag + '.execution.json')
            path.parent.mkdir(exist_ok=True)
            registry.atomic_json(path, saved)
            return saved['summary'], saved['records']
        self.checkpoint = self.patch(run, 'checkpoint', side_effect=checkpoint)
        self.records = package.Records(self.c, run, self.row)

    def package(self):
        return package.run(self.c, run, self.prev, 1)

    def held(self):
        with self.assertRaisesRegex(budget.BudgetError, '^extension_execution_pending$'): self.package()

    def observation(self, stage):
        data = self.records.load(stage)
        self.assertIs(data['ok'], False)
        self.assertEqual(data['info']['writer_observation']['feedback'], self.saved()['validation_problems'])
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        self.assertFalse((self.records.root / 'stress').exists())
        return data

    def cheats(self):
        self.failure = 'saved-cheats'
        (self.case / 'guards/cheats/saved-reference-control').mkdir(parents=True, exist_ok=True)

    def test_real_g5_rejection_retains_checkpoint_bytes(self):
        self.held(); data = self.observation('G5')
        self.assertEqual(self.calls, ['builder-9'])
        self.assertEqual(self.executed, ['G15', 'G3', 'G4', 'G5'])
        self.assertEqual(data['info']['reference'], '0/' + str(len(execution('plain')['records'])))
        self.assertEqual(data['info']['writer_observation']['bench_workers'], 1)
        retained = [self.work / name for name in data['support'] if name.endswith('g5-reference.execution.json')]
        self.assertEqual(len(retained), 1)
        self.assertEqual(json.loads(retained[0].read_text()), execution('plain'))

    def test_completed_and_done_writer_windows(self):
        # Each window gets an independent admitted writer and ledger.
        for done in (False, True):
            with self.subTest(done=done):
                if done: self.setUp()
                (self.case / 'draft.txt').write_text('authored changed draft')
                if not done: run.complete_writer(self.c, self.saved(), self.work / 'attack-state.json')
                with patch.object(run, 'writer_call_done', return_value=done): self.held()
                self.observation('G5')
                self.assertEqual(self.calls, [])

    def test_authored_g15_rejection_precedes_setup(self):
        self.failure = 'G15'
        self.held(); self.observation('G15')
        self.assertEqual(self.executed, ['G15'])
        self.checkpoint.assert_not_called()

    def test_real_saved_cheat_failure_is_not_full_g6(self):
        self.cheats(); self.held(); data = self.observation('saved-cheats')
        self.assertEqual(data['info']['sample'], 'retained_case_cheats')
        self.assertFalse(data['info']['summary']['ok'])
        self.assertEqual(data['info']['summary']['runs_each'], 1)
        self.assertTrue(any(tag == 'early-g6-cheat' for tag, _ in self.transports))
        for path in (self.records.root / 'G6', self.work / 'gate-cache/G6.json'):
            self.assertFalse(path.exists())
        self.assertNotIn('G6', self.c.early)
        proof = [self.work / name for name in data['support'] if name.endswith('early-g6-cheat.execution.json')]
        self.assertEqual(json.loads(proof[0].read_text()), execution('reference'))
        before = (self.records.root / 'saved-cheats/record.json').read_bytes()
        self.g1.side_effect = self.early.side_effect = AssertionError('sample replay work')
        self.checkpoint.side_effect = AssertionError('sample checkpoint reroll')
        self.held()
        self.assertEqual((self.records.root / 'saved-cheats/record.json').read_bytes(), before)
        self.assertEqual(self.calls, ['builder-9'])

    def test_stale_sample_summary_is_cleared_for_case_problem(self):
        self.cheats()
        self.c.card['early_gates'] = {'saved_cheats': {'ok': True, 'checked': 99}}
        original = self.checkpoint.side_effect
        def fail_sample(c, overlays, guard, runs, seed, tag, **kwargs):
            if tag == 'early-g6-cheat': raise CaseProblem('authored missing guard contract')
            return original(c, overlays, guard, runs, seed, tag, **kwargs)
        self.checkpoint.side_effect = fail_sample
        self.held(); data = self.observation('saved-cheats')
        self.assertIsNone(data['info']['summary'])
        self.c.card['early_gates']['saved_cheats'] = {'ok': True}
        self.held()
        self.assertNotIn('saved_cheats', self.c.card['early_gates'])

    def test_after_publication_skips_g1_and_every_early_call_with_requested_two_workers(self):
        original = package.Records.save
        def killed(records, *args):
            original(records, *args)
            raise runtime.Killed()
        with patch.object(package.Records, 'save', killed):
            with self.assertRaises(runtime.Killed): self.package()
        self.assertEqual(self.saved()['phase'], 'completed')
        path = self.records.root / 'G5/record.json'
        before = path.read_bytes()
        receipt = (self.work / 'attack-state.json').read_bytes()
        expected = json.loads(before)['record']['info']['writer_observation']['feedback']
        self.c.args.bench_workers = 2
        self.g1.side_effect = self.early.side_effect = AssertionError('replayed check')
        self.checkpoint.side_effect = AssertionError('replayed checkpoint')
        self.pipeline.check = Mock(side_effect=AssertionError('replayed setup'))
        for _ in range(2):
            self.held()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual((self.work / 'attack-state.json').read_bytes(), receipt)
            self.assertEqual(self.records.replay_writer_early(), expected)
            self.assertEqual(self.c.args.bench_workers, 2)
        self.assertEqual(self.calls, ['builder-9'])
        self.assertEqual(self.c.early, {})
        self.assertEqual(self.c.card['early_gates']['G5'], {'ok': False, 'minutes': 0})

    def test_before_publication_keeps_ordinary_path(self):
        with patch.object(package.Records, 'save', side_effect=runtime.Killed):
            with self.assertRaises(runtime.Killed): self.package()
        self.assertFalse((self.records.root / 'G5/record.json').exists())
        self.held(); self.observation('G5')
        self.assertEqual(self.executed, ['G15', 'G3', 'G4', 'G5'] * 2)
        self.assertEqual(self.calls, ['builder-9'])

    def test_save_failure_does_not_retry_rejecting_paid_gate(self):
        self.failure = 'G15'
        with patch.object(package.Records, 'save', side_effect=OSError('authored disk fault')):
            with self.assertRaisesRegex(OSError, 'authored disk fault'): self.package()
        self.assertEqual(self.executed, ['G15'])
        self.assertFalse((self.records.root / 'G15/record.json').exists())

    def test_all_pass_early_path_records_nothing(self):
        self.failure = None
        self.pipeline.saved_cheat_check = Mock(return_value=None)  # no-cheat control
        with patch.object(package, 'stress', side_effect=budget.BudgetError('test_handoff')):
            with self.assertRaisesRegex(budget.BudgetError, '^test_handoff$'): self.package()
        self.assertEqual(self.calls, ['builder-9', 'attacker-9'])
        self.assertFalse(self.records.root.exists())

    def test_pending_and_sample_exceptions_publish_nothing(self):
        self.pipeline.check = Mock(return_value=(False, {'classification': 'invalid-infra'}))
        self.held()
        self.assertFalse(self.records.root.exists())
        # Fresh real sample invocation; failure propagates without callback.
        self.cheats()
        for error in (InvalidInfra('authored invalid'), TimeoutError('authored timeout'), budget.BudgetError('money_wait')):
            callback = Mock()
            with patch.object(run, 'cheat_runs', side_effect=error), \
                    patch.object(self.pipeline, 'check', return_value=(True, {})):
                with self.assertRaises(type(error)) as caught:
                    REAL_EARLY(self.c, on_rejection=callback)
            self.assertIs(caught.exception, error)
            callback.assert_not_called()
        self.assertFalse(self.records.root.exists())

    def test_support_case_version_and_metadata_refusals_precede_work(self):
        self.held(); data = self.observation('G5')
        self.g1.side_effect = self.early.side_effect = AssertionError('refusal executed')
        support = self.work / next(iter(data['support']))
        original = support.read_bytes()
        for mode in ('missing', 'tamper', 'symlink'):
            support.unlink()
            if mode == 'tamper': support.write_bytes(b'bad')
            if mode == 'symlink': support.symlink_to(self.case / 'case.json')
            with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'): self.package()
            if support.exists() or support.is_symlink(): support.unlink()
            support.write_bytes(original)
        draft = self.case / 'draft.txt'; original_draft = draft.read_bytes()
        draft.write_bytes(b'changed')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'): self.package()
        draft.write_bytes(original_draft)
        with patch.object(gate_state, 'scientific_version', return_value='d' * 64): self.held()
        path = self.records.root / 'G5/record.json'; envelope = json.loads(path.read_text())
        for change in ('pass', 'metadata', 'workers'):
            modified = copy.deepcopy(envelope)
            if change == 'pass': modified['record']['ok'] = True
            if change == 'metadata': modified['record']['info']['writer_observation']['feedback'] = []
            if change == 'workers': modified['record']['info']['writer_observation']['bench_workers'] = True
            modified['sha256'] = extensions.digest(modified['record'])
            registry.atomic_json(path, modified)
            with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'): self.package()
        registry.atomic_json(path, envelope)
        for extra in ('G1', 'G15'):
            target = self.records.root / extra / 'record.json'; target.parent.mkdir()
            target.write_text('{}')
            with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'): self.package()
            target.unlink(); target.parent.rmdir()


if __name__ == '__main__': unittest.main()
