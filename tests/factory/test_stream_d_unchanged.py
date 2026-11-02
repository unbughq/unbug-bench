"""Unchanged writer completion on saved practice bytes and the 5813be ledger.

Real G1 diagnostics and comparison receipts; stress pass and no-op writer are
labelled external-output controls. No live worker, model or network calls.
"""
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
import batch_service
import budget
import diagnosis
import diagnosis_dispatch
import extension_compare as comparison
import extension_evaluator
import extension_package as package
import extensions
import gate_state
import model_runtime
import registry
import run
import test_stream_d_runtime as runtime
import test_stream_d_execution as execution
import test_stream_d_extensions as states
from test_extension_compare import cached_source_inputs


class UnchangedTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    diagnosis = states.ExtensionTests.diagnosis
    saved = execution.ExecutionTests.saved

    def snapshot(self, ignored):
        # The ordinary entry retains real practice-contract diagnostics, with an
        # authored clean stress answer preceding it, never invented gate passes.
        (self.work / 'logs').mkdir(exist_ok=True)
        self.c.manifest0 = run.bench_manifest()
        records = package.Records(self.c, run, observation_id=str(uuid.uuid4()), round_number=8)
        records.capture(self.c, 'stress', lambda: (True, {'authored_external_stress': 'clean'}))
        records.capture(self.c, 'G1', lambda: execution.REAL_G1(self.c))
        self.assertFalse(records.load('G1')['ok'])
        value = comparison.snapshot(package.workspace(self.c, run), self.c.source_generation, records.evidence)
        if self.unreached:
            # Explicit boundary control: an admitted legacy entry stopped before
            # G1. Retained practice evidence is unchanged, no failure is inferred.
            value['stages'][1].update(status='unreached', binding_sha256=None, evidence_sha256=None)
        return value

    def prepare(self, *, repair=True, unreached=False):
        self.unreached = unreached
        self.patch(gate_state, 'source_inputs', cached_source_inputs)
        original_receipt = runtime.RuntimeTests.receipt
        def receipt(test, role='writer'):
            value = original_receipt(test, role)
            if role == 'writer': value['repair_requested'] = repair
            return value
        with patch.object(runtime.RuntimeTests, 'receipt', receipt):
            execution.ExecutionTests.setUp(self)
        if not repair: self.prev = {}; self.c.card.pop('failed_gate', None)
        def noop(rt, c, models, text, cwd, name, **kwargs):
            c.model_process_state['started'] = True
            self.calls.append(name)
            if name == 'builder-9':
                if self.search:
                    with (c.case / 'freshness.jsonl').open('a') as f:
                        f.write('\n' + json.dumps({'authored_search_control': True}) + '\n')
            elif name == 'attacker-9':
                registry.atomic_json(self.work / 'attacks/round-9.json', {'complete': True, 'blocking': []})
            else: self.fail('unexpected model call: ' + name)
            return 0
        self.search = False
        self.patch(model_runtime.ModelRuntime, '_invoke', noop)
        self.package = lambda: package.run(self.c, run, self.prev, 1)

    def complete(self):
        with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): self.package()
        row = extensions.read(self.c)[-1]
        self.assertTrue(package.unchanged_outcome(self.c, run, row))
        self.assertEqual(row['outcome']['stages'], row['entry']['stages'])
        self.assertEqual(row['outcome']['frontier'], row['entry']['frontier'])
        root = self.work / 'extension-snapshots/1'
        for name in row['entry']['evidence']:
            self.assertEqual((root / 'entry/evidence' / name).read_bytes(),
                             (root / 'outcome/evidence' / name).read_bytes())
        return row

    def test_pending_writer_completion_and_two_accounting_free_replays(self):
        self.prepare(); row = self.complete()
        self.assertEqual(self.calls, ['builder-9'])
        self.g1.assert_not_called(); self.early.assert_not_called(); self.fresh.assert_not_called()
        projection = {key: copy.deepcopy(self.c.card.get(key)) for key in
                      ('gates', 'gate_results', 'failed_gate', 'failed_detail', 'stress_review')}
        self.assertEqual(projection['failed_gate'], 'G1')
        with patch.object(run, 'write_and_attack', side_effect=AssertionError('writer replay')), \
                patch.object(run, 'case_budget_boundary', side_effect=AssertionError('money replay')), \
                patch.object(extensions, 'complete', side_effect=AssertionError('outcome rebuilt')):
            for _ in range(2):
                self.c.card.update(failed_gate='G10', stress_review={'status': 'unresolved'})
                with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): self.package()
                self.assertEqual({key: self.c.card.get(key) for key in projection}, projection)
        self.assertEqual(extensions.read(self.c)[-1], row)

    def test_no_repair_request_still_stops_before_g1_or_stress(self):
        self.prepare(repair=False); self.complete()
        self.assertEqual(self.calls, ['builder-9'])
        self.g1.assert_not_called(); self.early.assert_not_called()

    def test_completed_writer_checkpoint_is_consumed_without_any_execution(self):
        self.prepare(repair=False)
        receipt = self.saved(); run.complete_writer(self.c, receipt, self.work / 'attack-state.json')
        with patch.object(run, 'write_and_attack', side_effect=AssertionError('completed writer reentered')):
            self.complete()
        self.assertEqual(self.calls, [])

    def test_resume_done_writer_without_repair_stops_before_validation(self):
        self.prepare(repair=False)
        # Authored final-usage acknowledgement of a killed writer. The real
        # complete_writer and completed-writer resume branch run in the loop.
        with patch.object(run, 'writer_call_done', return_value=True): self.complete()
        self.assertEqual(self.calls, [])
        self.g1.assert_not_called()

    def test_freshness_only_no_repair_keeps_g1_and_stress_route(self):
        self.prepare(repair=False); self.search = True
        # Stop at the ordinary stress handoff to inspect whether package chose a
        # terminal writer outcome; this slice does not retest gate traversal.
        with patch.object(package, 'stress', side_effect=budget.BudgetError('test_stress_handoff')):
            with self.assertRaisesRegex(budget.BudgetError, '^test_stress_handoff$'): self.package()
        self.assertEqual(self.calls, ['builder-9', 'attacker-9'])
        self.g1.assert_called(); self.early.assert_called(); self.fresh.assert_called()
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        self.assertFalse((self.work / 'extension-snapshots/1/outcome').exists())

    def test_completed_freshness_only_no_repair_falls_through_package_entry(self):
        self.prepare(repair=False)
        with (self.case / 'freshness.jsonl').open('a') as f: f.write('\n')
        receipt = self.saved(); run.complete_writer(self.c, receipt, self.work / 'attack-state.json')
        with patch.object(package, 'stress', side_effect=budget.BudgetError('test_stress_handoff')):
            with self.assertRaisesRegex(budget.BudgetError, '^test_stress_handoff$'): self.package()
        self.assertEqual(self.calls, ['attacker-9']); self.g1.assert_called()
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_freshness_only_repair_keeps_evidence_stop_and_open_history(self):
        self.prepare(); self.search = True
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'): self.package()
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        self.g1.assert_not_called()

    def test_history_before_card_routes_completed_terminal_without_stress(self):
        self.prepare(); lagging = copy.deepcopy(self.c.card['extension_history'])
        row = self.complete(); self.c.card['extension_history'] = lagging
        with patch.object(batch_service, 'DIAGNOSIS_ENABLED', True), \
                patch.object(extensions, 'writer_receipt', side_effect=AssertionError('old writer')):
            result = diagnosis_dispatch.apply(self.c, self.work, {'exhaustion_id': row['exhaustion_id']},
                                             {'outcome': 'close_to_passing'}, resume=True)
        self.assertEqual(result, 1)
        self.assertFalse((self.work / 'extension-package/1/stress/record.json').exists())

    def test_next_diagnosis_retires_without_comparison_even_after_version_drift(self):
        self.prepare(); self.complete()
        self.c.stopped = self.c.exhaustion_occurred = True
        self.c.card['terminal_stop'] = 'extension_incomplete'
        run.finalize_accounting(self.c)
        pending = copy.deepcopy(self.c.card['diagnosis_state'])
        self.assertEqual(pending['status'], 'pending')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): self.package()
        run.finalize_accounting(self.c)
        self.assertEqual(self.c.card['diagnosis_state'], pending)
        self.c.card['diagnosis_state'].update(status='completed', outcome='close_to_passing')
        with patch.object(gate_state, 'scientific_version', return_value='d' * 64), \
                patch.object(comparison, 'current_pair', side_effect=AssertionError('comparison selection')), \
                patch.object(comparison, 'snapshot', side_effect=AssertionError('new snapshot')), \
                patch.object(comparison, 'compare', side_effect=AssertionError('paid comparison')), \
                patch.object(extension_evaluator, 'Evaluator', side_effect=AssertionError('evaluator')), \
                patch.object(run, 'writer_request', side_effect=AssertionError('new writer')), \
                patch.object(run, 'pending_call', side_effect=AssertionError('new admission')):
            with self.assertRaisesRegex(budget.BudgetError, '^retired_no_progress$'):
                diagnosis_dispatch.admit_extension(self.c, run, self.prev)

    def test_rename_before_history_retries_identical_proof(self):
        self.prepare()
        original = extensions._write
        def killed(c, history):
            if history[-1]['outcome'] is not None: raise runtime.Killed()
            return original(c, history)
        with patch.object(extensions, '_write', side_effect=killed):
            with self.assertRaises(runtime.Killed): self.package()
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        root = self.work / 'extension-snapshots/1/outcome'
        before = extensions.tree(root)
        self.complete()
        self.assertEqual(extensions.tree(root), before)
        self.assertEqual(self.calls, ['builder-9'])

    def test_receipt_authentication_and_nonterminal_shapes(self):
        self.prepare()
        self.assertFalse(package.complete_unchanged(self.c, run, self.row))
        receipt = self.saved(); run.complete_writer(self.c, receipt, self.work / 'attack-state.json')
        original = self.saved()
        for key, value in (('operation_id', str(uuid.uuid4())), ('repair_requested', None)):
            registry.atomic_json(self.work / 'attack-state.json', {**original, key: value})
            with self.assertRaises(budget.BudgetError): package.complete_unchanged(self.c, run, self.row)
        registry.atomic_json(self.work / 'attack-state.json', original)
        for key, value in (('repair_pending', True), ('output_sha256', '0' * 64)):
            with self.subTest(key=key):
                registry.atomic_json(self.work / 'attack-state.json', {**original, key: value})
                self.assertFalse(package.complete_unchanged(self.c, run, self.row))
        registry.atomic_json(self.work / 'attack-state.json', {**original, 'before_repair_sha256': '0' * 64})
        with self.assertRaises(budget.BudgetError): package.complete_unchanged(self.c, run, self.row)
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_missing_entry_and_tampered_terminal_proof_never_reroll(self):
        self.prepare()
        path = self.work / 'extension-snapshots/1/entry/evidence' / next(iter(self.row['entry']['evidence']))
        data = path.read_bytes(); path.unlink()
        with self.assertRaises(budget.BudgetError): self.package()
        self.assertEqual(self.calls, [])
        path.write_bytes(data); self.complete()
        proof = self.work / 'extension-snapshots/1/outcome/evidence/extension-terminal/1.json'
        data = proof.read_bytes(); proof.write_text('{}')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'): self.package()
        proof.write_bytes(data)
        (self.case / 'promise.md').write_text('tampered live case')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'): self.package()
        self.assertEqual(self.calls, ['builder-9'])

    def test_unreached_frontier_projects_unknown(self):
        self.prepare(unreached=True); self.complete()
        self.assertNotIn('failed_gate', self.c.card)
        self.assertEqual(diagnosis._held_stage(self.c.card, 'extension_incomplete'), 'unknown')
        self.c.stopped = self.c.exhaustion_occurred = True
        self.c.card['terminal_stop'] = 'extension_incomplete'
        run.finalize_accounting(self.c)
        self.assertEqual(self.c.card['diagnosis_state']['status'], 'pending')

    def test_all_pass_entry_is_refused(self):
        self.prepare()
        receipt = self.saved(); run.complete_writer(self.c, receipt, self.work / 'attack-state.json')
        row = copy.deepcopy(self.row)
        row['entry']['frontier'] = len(row['entry']['stages'])
        for stage in row['entry']['stages']:
            stage.update(status='pass', binding_sha256='a' * 64,
                         evidence_sha256=next(iter(row['entry']['evidence'].values())))
        extensions.validate_snapshot(row['entry'])  # authored all-pass boundary control
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
            package.complete_unchanged(self.c, run, row)
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])


class UnknownDiagnosisTests(unittest.TestCase):
    import test_stream_d_inputs as inputs
    patch = runtime.RuntimeTests.patch
    install_receipt = inputs.InputTests.install_receipt
    snapshot = UnchangedTests.snapshot
    diagnosis = states.ExtensionTests.diagnosis

    def test_unreached_frontier_passes_frozen_diagnosis_validation(self):
        self.inputs.InputTests.setUp(self)
        self.unreached = True
        self.patch(gate_state, 'source_inputs', cached_source_inputs)
        self.c.card['builder_rounds'] = 8
        self.c.args.rounds = 8
        self.diagnosis()
        proposal = extensions.propose(self.c, self.snapshot(1))
        intent = runtime.RuntimeTests.receipt(self)
        intent.update(round=9, round_limit=9, report='round-9.json', binding=run.attack_binding(self.c))
        with patch.object(run, 'opencode', side_effect=runtime.Killed):
            with self.assertRaises(runtime.Killed):
                run.pending_call(self.c, self.c.models['builder'], 'authored no-op writer', self.case,
                    'builder-9', intent, role='writer', on_complete=lambda: None, extension_proposal=proposal)
        receipt = extensions.writer_receipt(self.c)
        run.complete_writer(self.c, receipt, self.work / 'attack-state.json')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'):
            package.run(self.c, run, {}, 1)
        self.c.card.update(status='stopped', terminal_stop='extension_incomplete')
        self.c.stopped = self.c.exhaustion_occurred = True
        run.finalize_accounting(self.c)
        self.assertEqual(diagnosis._held_stage(self.c.card, 'extension_incomplete'), 'unknown')
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        self.install_receipt()
        manifest = diagnosis.queued_inputs(self.c, self.bench, quiescent=True)
        root = self.work / 'diagnosis' / self.c.card['diagnosis_state']['exhaustion_id'] / 'inputs'
        card = json.loads((root / 'card.json').read_text())
        self.assertNotIn('failed_gate', card)
        self.assertEqual(card['stress_review'], {'status': 'not_run', 'reason': 'unchanged_writer'})
        answer = dict(schema_version=1, case_id=self.c.case_id, checkpoint_sha256=self.c.source_generation,
            outcome='close_to_passing', reason='Authored diagnosis answer on frozen unknown-frontier inputs',
            evidence=[dict(path='card.json', sha256=manifest['files']['card.json'], finding='No reached failed gate')],
            factory_bug=None)
        self.assertEqual(diagnosis.validate_result(answer, case=self.c.case_id,
            generation=self.c.source_generation, evidence_root=root), answer)


if __name__ == '__main__': unittest.main()
