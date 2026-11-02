"""Saved practice/5813be admission with real categories and package receipts.

CLI answers, diagnostic status and checkpoint ACK are authored controls. No live
worker, model, HTTP or diagnostic process runs; no Murphy closure is claimed.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'factory'), str(ROOT/'bin'), str(ROOT/'tests/factory')]
import budget
import extension_compare as comparison
import extension_package as package
import extensions
import model_runtime
import registry
import run
from run_validity import InvalidInfra
import test_stream_d_execution as execution
import test_stream_d_runtime as runtime

REAL_CATEGORIES = run.stress_categories
REAL_FRESHNESS = run.loop_freshness


class BlockingStressTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    snapshot = execution.ExecutionTests.snapshot
    diagnosis = execution.ExecutionTests.diagnosis

    def setUp(self):
        execution.ExecutionTests.setUp(self)
        self.single_stress = run.stress_categories
        self.patch(run, 'stress_categories', REAL_CATEGORIES)
        self.c.stress_checkpoint = lambda: True  # Authored remote durability ACK.
        self.blocking = ['Authored completed-call case defect']
        self.unfinished = ['Authored remaining validation']
        self.freshness = []
        self.diagnostic = True
        self.use_legacy = False
        self.legacy_complete = False
        self.error = None
        original = model_runtime.ModelRuntime._invoke
        def invoke(rt, c, models, text, cwd, name, **kwargs):
            if name == 'builder-9': return original(rt, c, models, text, cwd, name, **kwargs)
            self.assertEqual(name, 'attacker-9')
            self.calls.append(name); c.model_process_state['started'] = True
            if self.diagnostic:
                folder = c.work/'diagnostic-budgets/attacker-9'; folder.mkdir(parents=True, exist_ok=True)
                (folder/'claimed').touch()
                registry.atomic_json(folder/'status.json', {'status': 'interrupted', 'authored': True})
            value = dict(blocking=copy.deepcopy(self.blocking), unfinished_validation=self.unfinished,
                         freshness_review=self.freshness, cheats_tried=[], non_blocking=[])
            if self.use_legacy:
                target = self.work/'attacks/round-9.json'
                value['complete'] = self.legacy_complete
            else:
                config = json.loads(text.split('CATEGORY MODE (overrides whole-review completion instructions):\n')[1].split('\n')[0])
                target = Path(config['category_output'])
                value.update(category=config['category'], category_complete=False,
                             completed_subchecks=[config['required_subchecks'][0]])
            registry.atomic_json(target, value)
            if self.error is not None: raise self.error
            return 0
        self.patch(model_runtime.ModelRuntime, '_invoke', invoke)
        self.patch(run, 'run_gates', side_effect=AssertionError('no gate after scored stress failure'))

    def package(self):
        return package.run(self.c, run, self.prev, 1)

    def prepared(self):
        with self.assertRaisesRegex(budget.BudgetError, '^stress_review_unresolved:rounds_exhausted$'):
            run.write_and_attack(self.c, self.prev, extension_id=1)
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        return json.loads((self.work/'attack-state.json').read_text())

    def completed(self):
        with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): self.package()
        row = extensions.read(self.c)[-1]
        self.assertEqual(row['outcome']['stages'][0]['status'], 'fail')
        self.assertEqual(row['outcome']['frontier'], 0)
        self.assertTrue(all(stage['status']=='unreached' for stage in row['outcome']['stages'][1:]))
        self.assertEqual(self.calls, ['builder-9', 'attacker-9'])
        self.assertEqual(len(extensions.read(self.c)), 1)
        ledger = json.loads(self.ledger.read_text())
        self.assertTrue(all(item['state']=='settled' for item in ledger['invocation_reservations'].values()))
        return row

    def mutate_producer_input(self, value, **changes):
        # Boundary controls after a real completed call, not claimed CLI artifacts.
        report = self.work/'attacks/round-9.json'
        registry.atomic_json(report, value)
        path = self.work/'attack-state.json'; receipt = json.loads(path.read_text())
        receipt.update(changes)
        receipt['review_completed']['report_sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
        registry.atomic_json(path, receipt)

    def test_completed_category_blocker_wins_over_unfinished_diagnostics_and_replays(self):
        row = self.completed()
        report = json.loads((self.work/'attacks/round-9.json').read_text())
        self.assertFalse(report['complete']); self.assertEqual(report['status'], 'scored')
        self.assertTrue(report['unfinished_validation']); self.assertTrue(run.attack_diagnostic_unfinished(self.c, 9))
        receipt = json.loads((self.work/'attack-state.json').read_text())
        self.assertFalse(receipt['review_pending']); self.assertTrue(receipt['review_completed'])
        retained = self.work/'extension-snapshots/1/outcome/evidence'
        self.assertTrue(any('wrong_fixes-0.json' in name for name in row['outcome']['evidence']))
        self.assertTrue(any(path.read_bytes()==(self.work/'attacks/round-9.json').read_bytes()
                            for path in retained.rglob('round-9.json')))
        history, ledger = (self.work/'extension-history.json').read_bytes(), self.ledger.read_bytes()
        with patch.object(run, 'write_and_attack', side_effect=AssertionError('paid replay')):
            for _ in range(2):
                self.c.card.update(failed_gate='G8', gate_results={'G8': {'stale': True}})
                with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): self.package()
                self.assertNotIn('failed_gate', self.c.card)
        self.assertEqual((self.work/'extension-history.json').read_bytes(), history)
        self.assertEqual(self.ledger.read_bytes(), ledger)
        self.c.stopped = self.c.exhaustion_occurred = True
        self.c.card['terminal_stop'] = 'extension_incomplete'
        run.finalize_accounting(self.c); state = copy.deepcopy(self.c.card['diagnosis_state'])
        run.finalize_accounting(self.c)
        self.assertEqual(state['status'], 'pending'); self.assertEqual(self.c.card['diagnosis_state'], state)

    def test_real_excluded_url_without_request_line_needs_no_clearance(self):
        self.freshness = ['https://example.com/authored-excluded-reference']
        self.fresh.side_effect = REAL_FRESHNESS
        def excluded(c, rows, **kwargs):
            self.assertTrue(rows)
            c.freshness_confirmed_hits = 0
            c.freshness_verdict_path = 'authored-exclusion-control'
            c.freshness_review_reason = 'all_excluded'
            return []
        with patch.object(run, 'confirm_hits', side_effect=excluded) as confirmation:
            row = self.completed()
        self.assertEqual(confirmation.call_count, 1)
        self.assertEqual(self.c.card['loop_freshness']['outcome'], 'excluded')
        self.assertFalse((self.work/'attacks/round-9.clearance.json').exists())
        self.assertFalse((self.work/'attacks/round-9-writer.json').exists())
        self.assertEqual(package.Records(self.c, run, row).load('stress')['info']['blocking'], self.blocking)

    def test_complete_legacy_blocker_still_fails(self):
        self.use_legacy = True; self.legacy_complete = True
        self.unfinished = []; self.diagnostic = False
        self.patch(run, 'stress_categories', self.single_stress)
        row = self.completed()
        self.assertTrue(package.Records(self.c, run, row).load('stress')['info']['complete'])

    def test_record_and_outcome_publication_kill_points_recover_without_work(self):
        original = extensions._write
        for boundary in ('stress_record', 'outcome_directory'):
            with self.subTest(boundary=boundary):
                if boundary == 'stress_record':
                    with patch.object(comparison, 'snapshot', side_effect=runtime.Killed):
                        with self.assertRaises(runtime.Killed): self.package()
                else:
                    def killed(c, history):
                        if history[-1]['outcome'] is not None: raise runtime.Killed()
                        return original(c, history)
                    with patch.object(extensions, '_write', side_effect=killed):
                        with self.assertRaises(runtime.Killed): self.package()
                self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
                self.assertTrue((self.work/'extension-package/1/stress/record.json').is_file())
                if boundary == 'outcome_directory':
                    before = extensions.tree(self.work/'extension-snapshots/1/outcome')
                    with patch.object(run, 'write_and_attack', side_effect=AssertionError('paid restart')):
                        self.completed()
                    self.assertEqual(extensions.tree(self.work/'extension-snapshots/1/outcome'), before)

    def test_partial_blocking_bytes_before_timeout_never_score(self):
        self.error = budget.BudgetError('timeout')
        with self.assertRaisesRegex(budget.BudgetError, '^timeout$'): self.package()
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        receipt = json.loads((self.work/'attack-state.json').read_text())
        self.assertEqual(receipt['phase'], 'pending'); self.assertNotIn('review_completed', receipt)
        aggregate = json.loads((self.work/'attacks/round-9.json').read_text())
        self.assertEqual(aggregate['blocking'], []); self.assertEqual(aggregate['status'], 'pending')
        self.assertTrue(list((self.work/'attacks/round-9-categories').rglob('*-partial-*.json')))
        self.assertFalse((self.work/'extension-package/1/stress/record.json').exists())

    def test_no_finding_inputs_stay_pending_at_producer(self):
        self.prepared()
        claim = self.work/'diagnostic-budgets/attacker-9/claimed'
        claim.unlink()
        cases = [dict(complete=False, blocking=[], unfinished_validation=[], status='scored'),
                 dict(complete=True, blocking=[' REVIEW INCOMPLETE '], unfinished_validation=[]),
                 dict(complete=True, blocking=['validation unfinished: authored missing validation']),
                 dict(complete=True, blocking=[], unfinished_validation=[])]
        for index, value in enumerate(cases):
            if index == len(cases)-1: claim.touch()
            with self.subTest(value=value):
                self.mutate_producer_input(value)
                with self.assertRaisesRegex(budget.BudgetError, '^extension_execution_pending$'):
                    package.stress(self.c, run, package.Records(self.c, run, extensions.active(self.c)))
                self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_request_only_with_missing_or_empty_metadata_deliberately_holds(self):
        receipt = self.prepared()
        self.assertTrue(receipt['exhausted']); self.assertFalse(receipt['review_pending'])
        (self.work/'diagnostic-budgets/attacker-9/claimed').unlink()
        self.assertFalse(run.attack_diagnostic_unfinished(self.c, 9))
        for metadata in ({}, {'freshness_review': []}, {'freshness_review': ['https://example.com/request']}):
            with self.subTest(metadata=metadata):
                self.mutate_producer_input(dict(complete=True,
                    blocking=['[freshness-review] independent verdict required'], **metadata))
                with self.assertRaisesRegex(budget.BudgetError, '^extension_execution_pending$'):
                    package.stress(self.c, run, package.Records(self.c, run, extensions.active(self.c)))
                self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_pending_receipt_and_missing_exhaustion_cannot_score(self):
        self.prepared()
        path = self.work/'attack-state.json'; saved = path.read_bytes()
        for changes, label in [({'review_pending': True}, 'extension_execution_pending'),
                               ({'phase': 'pending'}, 'extension_execution_pending'),
                               ({'exhausted': False}, 'extension_snapshot_changed'),
                               ({'stop_reason': 'budget_exhausted'}, 'extension_snapshot_changed'),
                               ({'review_completed': {}}, 'extension_execution_pending')]:
            with self.subTest(changes=changes):
                receipt = json.loads(saved); receipt.update(changes); registry.atomic_json(path, receipt)
                with self.assertRaisesRegex(budget.BudgetError, '^'+label+'$'):
                    package.stress(self.c, run, package.Records(self.c, run, extensions.active(self.c)))
                self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        path.write_bytes(saved)

    def test_changed_hash_and_malformed_report_cannot_score(self):
        self.prepared()
        report = self.work/'attacks/round-9.json'
        report.write_bytes(report.read_bytes()+b'\n')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_execution_pending$'):
            package.stress(self.c, run, package.Records(self.c, run, extensions.active(self.c)))
        self.mutate_producer_input({'complete': True, 'blocking': 'not a list'})
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
            package.stress(self.c, run, package.Records(self.c, run, extensions.active(self.c)))
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_invalid_execution_detail_does_not_become_case_failure(self):
        self.prepared()
        self.mutate_producer_input(dict(complete=False, blocking=self.blocking,
                                       classification='invalid-infra'))
        with self.assertRaises(InvalidInfra):
            package.stress(self.c, run, package.Records(self.c, run, extensions.active(self.c)))
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_legacy_unfinished_label_has_completion_but_no_outcome(self):
        self.blocking = ['validation unfinished: Authored missing diagnostic coverage']
        self.diagnostic = False
        with self.assertRaisesRegex(budget.BudgetError, '^stress_review_unresolved:unfinished_validation$'):
            self.package()
        receipt = json.loads((self.work/'attack-state.json').read_text())
        self.assertTrue(receipt['review_completed']); self.assertEqual(receipt['phase'], 'validated')
        self.assertEqual(json.loads((self.work/'attacks/round-9.json').read_text())['status'], 'scored')
        self.assertEqual(run.attack_report(self.work/'attacks/round-9.json')['blocking'], [])
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_legacy_sentinel_and_category_diagnostic_stops_propagate(self):
        self.use_legacy = True; self.legacy_complete = True; self.unfinished = []
        self.blocking = ['review incomplete']
        self.patch(run, 'stress_categories', self.single_stress)
        with self.assertRaisesRegex(budget.BudgetError, '^stress_review_unresolved:interrupted_review$'):
            self.package()
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_no_defect_unfinished_diagnostic_propagates_category_stop(self):
        self.blocking = []
        with self.assertRaisesRegex(budget.BudgetError, '^stress_validation_exhausted$'): self.package()
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_raised_freshness_stop_is_not_scored(self):
        self.fresh.side_effect = budget.BudgetError('freshness_unresolved')
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_unresolved$'): self.package()
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])


if __name__ == '__main__': unittest.main()
