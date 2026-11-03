"""Terminal writer outcomes from saved real rejection evidence; no live workers."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import batch_service
import budget
import diagnosis
import diagnosis_dispatch
import extension_compare as comparison
import extension_evaluator
import extension_package as package
import extension_writer_rejection as rejection
import extensions
import gate_state
import job_authority
import registry
import run
import test_stream_d_writer_early as early
import test_stream_d_runtime as runtime
import test_stream_d_inputs as inputs
import test_stream_d_extensions as states
from test_extension_compare import REAL, execution, cached_source_inputs


class TerminalTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    snapshot = early.EarlyWriterTests.snapshot
    diagnosis = early.EarlyWriterTests.diagnosis
    saved = early.EarlyWriterTests.saved
    setUp = early.EarlyWriterTests.setUp
    package = early.EarlyWriterTests.package
    cheats = early.EarlyWriterTests.cheats

    def capture(self):
        original = package.Records.save
        def killed(records, *args):
            original(records, *args)
            raise runtime.Killed()
        with patch.object(package.Records, 'save', killed):
            with self.assertRaises(runtime.Killed): self.package()
        self.g1.side_effect = self.early.side_effect = AssertionError('rejection reroll')
        self.checkpoint.side_effect = AssertionError('checkpoint reroll')
        return self.saved()

    def finish(self):
        self.c.card.update(early_gates={'G1': {'ok': True}}, failed_gate='G17',
            failed_detail={'stale': True}, infrastructure_gate={'gate': 'G10'}, gates={'G6': 'pass'})
        self.c.early, self.c.early_hash = {'G6': (True, {})}, 'stale'
        with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): self.package()
        row = extensions.read(self.c)[-1]
        self.assertTrue(rejection.verified(self.c, run, row))
        self.assertEqual(row['outcome']['frontier'], 0)
        self.assertTrue(all(s['status'] == 'unreached' for s in row['outcome']['stages']))
        self.assertEqual(self.c.card['gates'], {})
        self.assertEqual(self.c.card['gate_results'], {})
        for key in ('early_gates', 'infrastructure_gate'): self.assertNotIn(key, self.c.card)
        for key in ('early', 'early_hash'): self.assertFalse(hasattr(self.c, key))
        stage, info = rejection.retained(self.c, run, row)
        self.assertEqual(self.c.card['failed_detail'], info)
        self.assertEqual(self.c.card.get('failed_gate'), None if stage == 'saved-cheats' else stage)
        self.assertEqual(self.c.card['stress_review'], {'status': 'not_run', 'reason': 'writer_rejection'})
        return row

    def test_completed_window_leftover_staging_and_replay(self):
        self.capture()
        leftover = self.records.root / '.stage-x/record.json'
        leftover.parent.mkdir(); leftover.write_text('{}')
        receipt = (self.work / 'attack-state.json').read_bytes()
        row = self.finish()
        before = extensions.tree(self.work / 'extension-snapshots/1/outcome')
        with patch.object(extensions, 'writer_receipt', side_effect=AssertionError('receipt replay')), \
                patch.object(run, 'case_budget_boundary', side_effect=AssertionError('money')):
            self.finish()
        self.assertEqual((self.work / 'attack-state.json').read_bytes(), receipt)
        self.assertEqual(extensions.tree(self.work / 'extension-snapshots/1/outcome'), before)
        self.assertEqual(row['outcome'], extensions.read(self.c)[-1]['outcome'])
        self.assertEqual(self.calls, ['builder-9'])

    def test_validated_before_exhaustion_and_saved_cheat_unknown(self):
        self.cheats(); receipt = self.capture()
        data = self.records.load('saved-cheats')
        receipt.update(phase='validated', next_phase='writer', awaiting_stress=False,
                       validation_problems=data['info']['writer_observation']['feedback'])
        registry.atomic_json(self.work / 'attack-state.json', receipt)
        self.finish(); self.finish()
        self.assertEqual(diagnosis._held_stage(self.c.card, 'extension_incomplete'), 'unknown')

    def test_receipt_refusals_preserve_bytes_and_open_history(self):
        receipt = self.capture()
        feedback = self.records.load('G5')['info']['writer_observation']['feedback']
        for change in ({'repair_pending': True}, {'phase': 'pending'}, {'next_phase': 'stress'},
                       {'awaiting_stress': True}, {'round': 8}, {'operation_id': 'bad'},
                       {'phase': 'validated', 'next_phase': 'writer', 'validation_problems': ['wrong']},
                       {'exhausted': True}, {'stop_reason': 'rounds_exhausted'},
                       {'phase': 'validated', 'next_phase': 'writer', 'validation_problems': feedback,
                        'exhausted': True},
                       {'phase': 'validated', 'next_phase': 'writer', 'validation_problems': feedback,
                        'stop_reason': 'rounds_exhausted'}):
            with self.subTest(change=change):
                registry.atomic_json(self.work / 'attack-state.json', {**receipt, **change})
                before = (self.work / 'attack-state.json').read_bytes()
                with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
                    rejection.complete(self.c, run, self.row)
                self.assertEqual((self.work / 'attack-state.json').read_bytes(), before)
                self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        registry.atomic_json(self.work / 'attack-state.json', receipt)

    def test_full_tree_and_published_directory_refusals(self):
        self.capture()
        path = self.case / 'freshness.jsonl'; before = path.read_bytes()
        path.write_bytes(before + b'\n')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
            rejection.complete(self.c, run, self.row)
        path.write_bytes(before)
        other = self.records.root / 'G8'; other.mkdir()
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
            rejection.complete(self.c, run, self.row)
        other.rmdir(); self.finish()

    def test_invalid_observations_and_all_pass_entry_refuse(self):
        self.capture()
        path = self.records.root / 'G5/record.json'
        original = json.loads(path.read_text())
        for mode in ('pass', 'pending', 'metadata', 'unbound_case'):
            value = copy.deepcopy(original)
            if mode == 'pass': value['record']['ok'] = True
            if mode == 'pending': value['record']['info']['error'] = 'authored pending'
            if mode == 'metadata': value['record']['info']['writer_observation']['feedback'] = []
            if mode == 'unbound_case':
                name = next(n for n in value['record']['support'] if '/support/case/' in n)
                del value['record']['support'][name]
            value['sha256'] = extensions.digest(value['record']); registry.atomic_json(path, value)
            with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
                rejection.complete(self.c, run, self.row)
        registry.atomic_json(path, original)
        row = copy.deepcopy(self.row)
        row['entry']['frontier'] = len(row['entry']['stages'])
        for stage in row['entry']['stages']:
            stage.update(status='pass', binding_sha256='a' * 64,
                         evidence_sha256=next(iter(row['entry']['evidence'].values())))
        extensions.validate_snapshot(row['entry'])
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
            rejection.complete(self.c, run, row)
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_rename_before_history_reuses_bytes_across_generation(self):
        self.capture()
        original = extensions._write
        def killed(c, history):
            if history[-1]['outcome'] is not None: raise runtime.Killed()
            return original(c, history)
        with patch.object(extensions, '_write', side_effect=killed):
            with self.assertRaises(runtime.Killed): self.package()
        root = self.work / 'extension-snapshots/1/outcome'
        before = extensions.tree(root)
        authority = job_authority.for_case(self.c)
        from dataclasses import replace
        with patch.object(job_authority, 'for_case', return_value=replace(authority, source_generation='f' * 64)):
            row = self.finish()
        self.assertEqual(row['outcome']['source_generation'], 'f' * 64)
        self.assertEqual(extensions.tree(root), before)

    def test_history_before_card_and_new_diagnosis_route_never_evaluate(self):
        self.capture(); lagging = copy.deepcopy(self.c.card['extension_history'])
        row = self.finish(); self.c.card['extension_history'] = lagging
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), \
                patch.object(extensions, 'writer_receipt', side_effect=AssertionError('receipt')):
            self.assertEqual(diagnosis_dispatch.apply(self.c, self.work,
                {'exhaustion_id': row['exhaustion_id']}, {'outcome': 'close_to_passing'}, resume=True), 1)
        self.c.stopped = self.c.exhaustion_occurred = True
        self.c.card['terminal_stop'] = 'extension_incomplete'
        run.finalize_accounting(self.c)
        pending = copy.deepcopy(self.c.card['diagnosis_state'])
        self.c.exhaustion_occurred = False
        self.finish(); run.finalize_accounting(self.c)
        self.assertEqual(self.c.card['diagnosis_state'], pending)
        self.c.factory_slot = 9
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), \
                patch.object(gate_state, 'scientific_version', side_effect=AssertionError('version evaluation')), \
                patch.object(comparison, 'current_pair', side_effect=AssertionError('comparison')), \
                patch.object(extension_evaluator, 'Evaluator', side_effect=AssertionError('evaluator')), \
                patch.object(run, 'writer_request', side_effect=AssertionError('writer request')), \
                patch.object(run, 'pending_call', side_effect=AssertionError('admission')):
            self.assertEqual(diagnosis_dispatch.apply(self.c, self.work,
                {'exhaustion_id': pending['exhaustion_id']}, {'outcome': 'close_to_passing'}, comparison_route=True), 0)
            with self.assertRaisesRegex(budget.BudgetError, '^retired_no_progress$'):
                diagnosis_dispatch.admit_extension(self.c, run, self.prev)

    def test_retained_proof_tamper_missing_and_symlink_refuse(self):
        self.capture(); row = self.finish()
        root = self.work / 'extension-snapshots/1/outcome/evidence'
        names = list(row['outcome']['evidence'])
        for name in (rejection.marker(row), next(n for n in names if n.endswith('/record.json')),
                     next(n for n in names if '/support/' in n)):
            path = root / name; original = path.read_bytes()
            for mode in ('tamper', 'missing', 'symlink'):
                path.unlink()
                if mode == 'tamper': path.write_text('{}')
                if mode == 'symlink': path.symlink_to(self.case / 'case.json')
                with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
                    rejection.verified(self.c, run, row)
                label = 'extension_snapshot_invalid' if mode == 'symlink' else 'extension_snapshot_changed'
                with self.assertRaisesRegex(budget.BudgetError, '^' + label + '$'): self.package()
                if path.exists() or path.is_symlink(): path.unlink()
                path.write_bytes(original)


class DiagnosisTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    install_receipt = inputs.InputTests.install_receipt
    snapshot = states.ExtensionTests.snapshot
    diagnosis = states.ExtensionTests.diagnosis

    def exercise(self, sample):
        inputs.InputTests.setUp(self)
        self.patch(gate_state, 'source_inputs', cached_source_inputs)
        self.c.card['builder_rounds'] = self.c.args.rounds = 8
        self.diagnosis()
        proposal = extensions.propose(self.c, self.snapshot(1))
        intent = runtime.RuntimeTests.receipt(self)
        intent.update(round=9, round_limit=9, report='round-9.json', binding=run.attack_binding(self.c))
        with patch.object(run, 'opencode', side_effect=runtime.Killed):
            with self.assertRaises(runtime.Killed):
                run.pending_call(self.c, self.c.models['builder'], 'authored writer', self.case,
                    'builder-9', intent, role='writer', on_complete=lambda: None, extension_proposal=proposal)
        (self.case / 'case.json').write_text(json.dumps(REAL['suffix-case']['files']['case.json']))
        (self.case / 'draft.txt').write_text('authored changed draft')
        if sample: (self.case / 'guards/cheats/saved-reference-control').mkdir(parents=True)
        self.c.args.rehearse_only = True; self.c.args.runs = 1; self.c.args.bench_workers = 1
        receipt = extensions.writer_receipt(self.c)
        run.complete_writer(self.c, receipt, self.work / 'attack-state.json')
        records = package.Records(self.c, run, extensions.read(self.c)[-1])
        pipeline = run._gate_pipeline()
        pipeline.publish = pipeline.log = lambda *a: None
        # Authored earlier-pass controls; the rejecting verdict uses real saved runs.
        pipeline.check = lambda c, gate: run.g5(c) if gate == 'G5' and not sample else (True, {})
        saved = execution('reference' if sample else 'plain')
        def checkpoint(*a, **kw):
            path = self.work / 'gate-details/saved-execution.json'; path.parent.mkdir(exist_ok=True)
            registry.atomic_json(path, saved)
            return saved['summary'], saved['records']
        with patch.object(run, '_gate_pipeline', return_value=pipeline), patch.object(run, 'checkpoint', side_effect=checkpoint):
            self.assertTrue(records.writer_early(self.c))
        with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'):
            package.run(self.c, run, {}, 1)
        self.c.card.update(status='stopped', terminal_stop='extension_incomplete')
        self.c.stopped = self.c.exhaustion_occurred = True
        run.finalize_accounting(self.c)
        self.assertEqual(self.c.card['diagnosis_state']['status'], 'pending')
        self.c.checkpoint_card = copy.deepcopy(self.c.card); self.install_receipt()
        manifest = diagnosis.queued_inputs(self.c, self.bench, quiescent=True)
        root = self.work / 'diagnosis' / self.c.card['diagnosis_state']['exhaustion_id'] / 'inputs'
        card = json.loads((root / 'card.json').read_text())
        self.assertEqual(diagnosis._held_stage(card, 'extension_incomplete'), 'unknown' if sample else 'G5')
        self.assertEqual(card['failed_detail'], self.c.card['failed_detail'])
        answer = dict(schema_version=1, case_id=self.c.case_id, checkpoint_sha256=self.c.source_generation,
            outcome='close_to_passing', reason='Authored diagnosis on saved writer rejection',
            evidence=[dict(path='card.json', sha256=manifest['files']['card.json'], finding='Retained rejection')], factory_bug=None)
        self.assertEqual(diagnosis.validate_result(answer, case=self.c.case_id,
            generation=self.c.source_generation, evidence_root=root), answer)

    def test_g5_diagnosis_inputs(self): self.exercise(False)
    def test_sample_unknown_diagnosis_inputs(self): self.exercise(True)


if __name__ == '__main__': unittest.main()
