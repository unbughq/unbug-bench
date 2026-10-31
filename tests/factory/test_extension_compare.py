"""Real practice/ledger/execution bytes with authored comparison orchestration.

G4/G5 use the real evaluators on saved executions. Other stage verdicts, version
changes and interruptions are controls, not a live extension qualification.
"""
import copy
from dataclasses import replace
import os
import gzip
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
from case_contract import CaseProblem
import extension_compare as compare
import extensions
import gate_state
import run
from run_validity import InvalidInfra, require_valid
import test_stream_d_extensions as history_tests
import test_stream_d_runtime as runtime

REAL = json.loads(gzip.decompress((ROOT / 'tests/factory/fixtures/invalid-runs-real.json.gz').read_bytes()))


def execution(label):
    files = REAL[label]['files']
    return dict(summary=files['checkpoint.json'],
                records=[files[n] for n in sorted(files) if Path(n).stem.isdigit()])


# Cache only identical source bytes/root queries across these replay scenarios.
# Every edit still runs the real source inventory, including scoped drift tests.
SOURCE_INPUTS = gate_state.source_inputs
SOURCE_CACHE = {}
def cached_source_inputs(*roots, path=None):
    key = (roots, (path or gate_state.RUNNER).read_bytes())
    if key not in SOURCE_CACHE:
        SOURCE_CACHE[key] = SOURCE_INPUTS(*roots, path=path)
    return copy.deepcopy(SOURCE_CACHE[key])


class CompareTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    diagnosis = history_tests.ExtensionTests.diagnosis
    reserve = history_tests.ExtensionTests.reserve
    begin = history_tests.ExtensionTests.begin

    def setUp(self):
        runtime.RuntimeTests.setUp(self)
        # Saved execution's matching promise contract, also used by item 5.
        (self.case / 'case.json').write_text(json.dumps(REAL['suffix-case']['files']['case.json']))
        self.c.args.runs = self.c.args.pilot_runs = self.c.args.pilot_tries = 1
        self.c.args.rehearse_only = True
        self.c.models['easy_calibrator'] = ['opencode/minimax-m3.1-flash-free']
        # Version changes operate on independent source copies, never the repo.
        factory = self.work / 'source'; factory.mkdir()
        for source in (ROOT / 'factory').glob('*.py'):
            shutil.copy2(source, factory / source.name)
        self.patch(gate_state, 'RUNNER', factory / 'run.py')
        self.patch(gate_state, 'source_inputs', cached_source_inputs)
        self.calls = []

    def workspace(self):
        return compare.Workspace(self.case, self.work, ROOT, copy.deepcopy(self.c.args),
            copy.deepcopy(self.c.models), {'roles': copy.deepcopy(self.c.card['roles'])},
            self.c.seed, 0, self.c.case_id)

    def evaluator(self, w, stage):
        self.calls.append((w.case.name, stage))
        changed = (w.case / 'authored-revision.txt').exists()
        saved = execution('plain' if stage == 'G4' or not changed else 'reference')
        proof = w.work / 'execution.json'
        proof.write_text(json.dumps(saved))
        require_valid(saved['summary'], saved['records'])
        if stage in ('G4', 'G5'):
            with patch.object(run, 'checkpoint', return_value=(saved['summary'], saved['records'])):
                ok, detail = getattr(run, stage.lower())(w)
        else:
            ok, detail = stage != 'G16', {'authored_stage_control': stage}
        return ok, detail, ['execution.json']

    def prepare(self, *, receipts=False):
        if receipts:
            entry = compare.snapshot(self.workspace(), self.c.source_generation, self.evaluator)
        else:
            entry = history_tests.ExtensionTests.snapshot(self, 4)
        self.begin(entry)
        (self.case / 'authored-revision.txt').write_text('authored repair perturbation on saved practice bytes')
        if receipts:
            outcome = compare.snapshot(self.workspace(), self.c.source_generation, self.evaluator)
        else:
            outcome = history_tests.ExtensionTests.snapshot(self, 5)
        extensions.complete(self.c, outcome)
        self.calls.clear()

    def compare(self, evaluate=None):
        return compare.compare(self.c, 1, ROOT, evaluate or self.evaluator)

    def test_real_gate_progress_isolated_and_next_admission_uses_retained_outcome(self):
        self.prepare()
        card = copy.deepcopy(self.c.card)
        before = extensions.tree(self.case)
        original = copy.deepcopy(extensions.read(self.c)[0])
        (self.work / 'gate-cache').mkdir()
        cache = self.work / 'gate-cache/live.json'; cache.write_text('{"live": true}')
        def evaluate(w, stage):
            self.assertFalse(w.work.is_relative_to(self.work))
            self.assertFalse(hasattr(w, 'ledger'))
            self.assertIn('roles', w.card)
            return self.evaluator(w, stage)
        self.assertEqual(self.compare(evaluate), 'progress')
        self.assertEqual(extensions.tree(self.case), before)
        self.assertEqual(self.c.card, card)
        self.assertEqual(cache.read_text(), '{"live": true}')
        row = extensions.read(self.c)[0]
        self.assertEqual(row['entry'], original['entry'])
        self.assertEqual(row['outcome'], original['outcome'])
        outcome = row['comparisons'][-1]['outcome']
        self.assertFalse((self.work / 'comparison-receipts').exists())
        proposal, lease, operation = self.reserve(outcome)
        extensions.verify_proposal(self.c, proposal)
        admitted = extensions.admit(self.c, proposal, lease, operation)
        self.assertEqual(admitted['extension_id'], 2)
        self.assertEqual(extensions.admit(self.c, proposal, lease, operation), admitted)
        extensions.read(self.c)

    def test_completed_pair_and_original_receipts_are_sticky(self):
        self.prepare(receipts=True)
        before = (self.work / 'extension-history.json').read_bytes()
        with patch.object(self, 'evaluator', side_effect=AssertionError('rerolled')):
            self.assertEqual(self.compare(), 'progress')
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)

    def test_execution_plumbing_cannot_reroll_scored_pair_or_disagree_with_admission(self):
        # Stay pooled: serial-to-pool selects new scientific executor code.
        self.c.args.bench_workers = 4
        self.prepare()
        self.assertEqual(self.compare(), 'progress')
        history = extensions.read(self.c)
        outcome = history[0]['comparisons'][0]['outcome']
        versions = compare._versions(self.workspace())
        self.diagnosis()
        proposal = extensions.propose(self.c, outcome)
        before = (self.work / 'extension-history.json').read_bytes()
        self.c.args.bench_workers = 2
        self.c.args.concurrent_roles = not self.c.args.concurrent_roles
        self.c.factory_slot = 7
        self.c.seed += 5
        with patch.dict(os.environ, {'UNBUG_FACTORY_SLOT': '7'}):
            self.assertEqual(compare._versions(self.workspace()), versions)
            with patch.object(self, 'evaluator', side_effect=AssertionError('rerolled plumbing')):
                self.assertEqual(self.compare(), 'progress')
            self.assertEqual(extensions.propose(self.c, outcome), proposal)
            extensions.verify_proposal(self.c, proposal)
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)
        selected = extensions.comparison_pair(history[0], list(versions.values()))
        self.assertEqual(selected['outcome'], outcome)

    def test_adapter_programming_errors_propagate_without_scoring(self):
        self.prepare()
        before = (self.work / 'extension-history.json').read_bytes()
        for kind in (ValueError, TypeError, FileNotFoundError):
            def broken(*args):
                raise kind('authored adapter bug')
            with self.assertRaisesRegex(kind, 'authored adapter bug'):
                self.compare(broken)
            self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)

    def test_pending_invalid_execution_retry_then_no_reroll(self):
        self.prepare()
        def invalid(w, stage):
            if stage == 'G5':
                saved = execution('reset-invalid')
                require_valid(saved['summary'], saved['records'])
            return self.evaluator(w, stage)
        self.assertEqual(self.compare(invalid), 'pending')
        pair = extensions.read(self.c)[0]['comparisons'][-1]
        self.assertEqual(next(r['status'] for r in pair['entry']['stages'] if r['stage'] == 'G5'), 'pending')
        self.calls.clear()
        self.assertEqual(self.compare(), 'progress')
        self.assertNotIn('G4', [stage for _, stage in self.calls])
        before = (self.work / 'extension-history.json').read_bytes()
        with patch.object(self, 'evaluator', side_effect=AssertionError('rerolled')):
            self.assertEqual(self.compare(), 'progress')
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)

    def test_classifier_matches_runner_and_preserves_inconclusive_failure(self):
        w = self.workspace()
        for detail in ({'classification': 'invalid-infra'}, {'error': 'transport'},
                       {'invalid_infra': True}, {'execution_valid': False}):
            def evaluate(w, stage):
                (w.work / 'proof.json').write_text(json.dumps(execution('plain')))
                return False, detail, ['proof.json']
            result = compare.snapshot(w, self.c.source_generation, evaluate)
            self.assertEqual(result['stages'][0]['status'], 'pending')
        def problem(w, stage):
            raise CaseProblem('saved case violates authored contract control')
        result = compare.snapshot(w, self.c.source_generation, problem)
        self.assertEqual(result['stages'][0]['status'], 'fail')
        def inconclusive(w, stage):
            (w.work / 'proof.json').write_text(json.dumps(execution('plain')))
            return stage != 'G16', ({'review_inconclusive': True, 'verdict_valid': False}
                                    if stage == 'G16' else {}), ['proof.json']
        result = compare.snapshot(w, self.c.source_generation, inconclusive)
        self.assertEqual(next(r['status'] for r in result['stages'] if r['stage'] == 'G16'), 'fail')

    def test_stress_freshness_and_g2_mutation_refused_without_live_changes(self):
        self.prepare()
        before = (self.work / 'extension-history.json').read_bytes()
        live = extensions.tree(self.case)
        for target in ('stress', 'G2'):
            def mutate(w, stage):
                if stage == target:
                    (w.case / 'freshness.jsonl').write_text('authored incorrect adapter mutation')
                return self.evaluator(w, stage)
            self.assertEqual(self.compare(mutate), 'pending')
            self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)
            self.assertEqual(extensions.tree(self.case), live)
        def unresolved(w, stage):
            raise budget.BudgetError('freshness_unresolved')
        self.assertEqual(self.compare(unresolved), 'pending')
        self.assertEqual(extensions.tree(self.case), live)
        # Read-only stress/G2 paths already consume the original case unchanged.
        self.assertEqual(self.compare(), 'progress')

    def test_configuration_mutation_and_version_drift_are_pending(self):
        self.prepare()
        original = (self.work / 'extension-history.json').read_bytes()
        before = copy.deepcopy(vars(self.c.args))
        def mutate(w, stage):
            w.args.runs += 1
            return self.evaluator(w, stage)
        self.assertEqual(self.compare(mutate), 'pending')
        self.assertEqual(vars(self.c.args), before)
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), original)
        def drift(w, stage):
            if stage == 'stress':
                source = gate_state.RUNNER
                source.write_text(source.read_text().replace('broke >= 1, {"broke"', 'broke >= 2, {"broke"'))
            return self.evaluator(w, stage)
        self.assertEqual(self.compare(drift), 'pending')
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), original)

    def test_scoped_gate_change_reuses_other_passes_and_plumbing_keeps_pair(self):
        self.prepare(receipts=True)
        source = gate_state.RUNNER
        source.write_text(source.read_text().replace('broke >= 1, {"broke"', 'broke >= 2, {"broke"'))
        self.assertEqual(self.compare(), 'progress')
        self.assertIn('G4', [stage for _, stage in self.calls])
        # Outcome G5 is a retained pass; entry G5 is a fail and must re-execute.
        self.assertEqual(sum(stage == 'G5' for _, stage in self.calls), 1)
        before = (self.work / 'extension-history.json').read_bytes()
        source.with_name('budget.py').write_text('# authored pure plumbing change\n')
        self.calls.clear()
        self.assertEqual(self.compare(), 'progress')
        self.assertEqual(self.calls, [])
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)

    def test_receipt_reader_requires_support_and_g16_calibration_binding(self):
        w = self.workspace()
        (self.work / 'proof.json').write_text(json.dumps(execution('reference')))
        version = gate_state.scientific_version(w, 'G16', ROOT)
        row, evidence = compare._save(w, 'G16', version, True, {}, ['proof.json'])
        self.assertIsNotNone(compare._load(w, row, evidence))
        moved = replace(w, seed=w.seed + 1, factory_slot=9)
        moved.args.bench_workers = 2
        with patch.dict(os.environ, {'UNBUG_FACTORY_SLOT': '9'}):
            self.assertIsNotNone(compare._load(moved, row, evidence))
        with patch.object(gate_state, 'calibration_binding', return_value={'changed': True}):
            self.assertIsNone(compare._load(w, row, evidence))
        support = next(name for name in evidence if name.startswith('comparison-support/'))
        (self.work / support).write_text('{}')
        self.assertIsNone(compare._load(w, row, evidence))
        (self.work / support).unlink()
        self.assertIsNone(compare._load(w, row, evidence))

    def test_stage_support_is_copied_and_missing_or_symlink_proof_is_pending(self):
        w = self.workspace()
        def evaluate(w, stage):
            (w.work / 'same.json').write_text(json.dumps({'stage': stage, 'saved': execution('plain')}))
            return stage != 'G16', {}, ['same.json']
        result = compare.snapshot(w, self.c.source_generation, evaluate)
        stress = result['stages'][0]
        self.assertIsNotNone(compare._load(w, stress, result['evidence']))
        middle = next(r for r in result['stages'] if r['stage'] == 'G5')
        self.assertIsNotNone(compare._load(w, middle, result['evidence']))
        support = self.work / 'comparison-support/G5/same.json'
        self.assertEqual(json.loads(support.read_text())['stage'], 'G5')
        proof = self.work / 'same.json'; proof.unlink(); proof.symlink_to(self.ledger)
        result = compare.snapshot(w, self.c.source_generation, lambda *a: (True, {}, ['same.json']))
        self.assertEqual(result['stages'][0]['status'], 'pending')
        result = compare.snapshot(w, self.c.source_generation, lambda *a: (True, {}, ['missing.json']))
        self.assertEqual(result['stages'][0]['status'], 'pending')

    def test_crash_before_history_append_keeps_original_and_retry_deduplicates(self):
        self.prepare()
        before = (self.work / 'extension-history.json').read_bytes()
        with patch.object(extensions, '_write', side_effect=RuntimeError('crash control')):
            with self.assertRaisesRegex(RuntimeError, 'crash control'):
                self.compare()
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)
        self.assertEqual(self.compare(), 'progress')
        self.assertEqual(len(extensions.read(self.c)[0]['comparisons']), 1)
        self.assertEqual(len(list((self.work / 'extension-snapshots/1').glob('comparison-*'))), 1)

    def test_same_version_regression_is_sticky_and_cannot_borrow_later_progress(self):
        self.prepare()
        def regression(w, stage):
            ok, detail, paths = self.evaluator(w, stage)
            if stage == 'G4' and (w.case / 'authored-revision.txt').exists():
                saved = execution('reference')
                (w.work / 'execution.json').write_text(json.dumps(saved))
                with patch.object(run, 'checkpoint', return_value=(saved['summary'], saved['records'])):
                    ok, detail = run.g4(w)
            return ok, detail, paths
        self.assertEqual(self.compare(regression), 'regression')
        before = (self.work / 'extension-history.json').read_bytes()
        self.assertEqual(self.compare(), 'regression')
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)
        outcome = extensions.read(self.c)[0]['comparisons'][0]['outcome']
        self.diagnosis()
        with self.assertRaisesRegex(budget.BudgetError, 'retired_no_progress'):
            extensions.propose(self.c, outcome)

    def test_no_progress_and_provider_wait_are_not_confused(self):
        self.prepare()
        before = (self.work / 'extension-history.json').read_bytes()
        with self.assertRaisesRegex(budget.BudgetError, 'provider_wait'):
            self.compare(lambda *a: (_ for _ in ()).throw(budget.BudgetError('provider_wait')))
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)
        def same_frontier(w, stage):
            ok, detail, paths = self.evaluator(w, stage)
            if stage == 'G5':
                saved = execution('plain')
                (w.work / 'execution.json').write_text(json.dumps(saved))
                with patch.object(run, 'checkpoint', return_value=(saved['summary'], saved['records'])):
                    ok, detail = run.g5(w)
            return ok, detail, paths
        self.assertEqual(self.compare(same_frontier), 'no_progress')

    def test_changed_live_case_and_retained_support_cannot_authorize_admission(self):
        self.prepare()
        self.assertEqual(self.compare(), 'progress')
        pair = extensions.read(self.c)[0]['comparisons'][0]
        self.diagnosis()
        proposal = extensions.propose(self.c, pair['outcome'])
        changed = self.case / 'after-comparison.txt'; changed.write_text('authored changed candidate')
        with self.assertRaisesRegex(budget.BudgetError, 'extension_snapshot_changed'):
            extensions.verify_proposal(self.c, proposal)

        changed.unlink()
        root = self.work / 'extension-snapshots/1' / ('comparison-' + extensions.digest(pair)) / 'outcome'
        proof = next(name for name in pair['outcome']['evidence'] if name.startswith('comparison-support/'))
        (root / proof).write_text('{}')
        with self.assertRaisesRegex(budget.BudgetError, 'extension_snapshot_changed'):
            extensions.verify_proposal(self.c, proposal)

    def test_opaque_current_version_original_cannot_override_reconstruction(self):
        versions = compare._versions(self.workspace())
        def opaque(frontier):
            result = history_tests.ExtensionTests.snapshot(self, frontier)
            for row in result['stages']:
                row['version'] = versions[row['stage']]
            return result
        self.begin(opaque(4))
        (self.case / 'authored-revision.txt').write_text('authored revision')
        extensions.complete(self.c, opaque(5))
        self.assertEqual(self.compare(lambda *a: (False, {'classification': 'invalid-infra'}, [])), 'pending')
        self.diagnosis()
        with self.assertRaisesRegex(budget.BudgetError, 'extension_comparison_pending'):
            extensions.propose(self.c, opaque(5))
        self.assertEqual(self.compare(), 'progress')
        outcome = extensions.read(self.c)[0]['comparisons'][-1]['outcome']
        proposal, lease, operation = self.reserve(outcome)
        extensions.verify_proposal(self.c, proposal)
        self.assertEqual(extensions.admit(self.c, proposal, lease, operation)['extension_id'], 2)



if __name__ == '__main__':
    unittest.main()
