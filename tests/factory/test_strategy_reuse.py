"""Synthetic call-seam tests: a restarted runner reuses only intact completion evidence."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy
import json
import pathlib
import tempfile
import types
import unittest
import shutil
import sys
from unittest.mock import patch
import run


class StrategyReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.c = types.SimpleNamespace(work=self.root / 'work', case=self.root / 'case',
            seed=7, card={}, args=types.SimpleNamespace(scenario_runs=3, bench_workers=2))
        self.c.work.mkdir(); self.c.case.mkdir()
        (self.c.case / 'judge.py').write_text('synthetic judge')
        self.calls = 0
        self.implementation = 'v1'
        self.module = types.SimpleNamespace(STRATEGIES=('honest-reference', 'frozen-first-fix'), simulate=self.simulate,
            execute_shared=object(),
            steps=lambda case: [{'id': 'establish'}])
        for p in (patch.object(run, 'BENCH', self.root),
                  patch.object(run, 'bench_manifest', lambda: self.implementation),
                  patch.object(run, 'strategy_module', lambda: self.module)):
            p.start(); self.addCleanup(p.stop)

    def simulate(self, case, name, runs, seed, factory_workers, checkpoint_cache_dir, checkpoint_binding,
                 restored_results_root, shared, shared_binding):
        self.calls += 1
        self.assertIs(shared, self.c.strategy_shared)
        self.assertIsInstance(shared_binding(), str)
        self.assertEqual(factory_workers, self.c.args.bench_workers)
        self.assertEqual(checkpoint_cache_dir, self.c.work / ('strategy-' + name + '-checkpoints'))
        self.assertEqual(restored_results_root, self.c.work / 'bench-results')
        self.assertIsInstance(checkpoint_binding(), str)
        evidence = self.root / 'results' / 'runs' / str(self.calls) / 'checkpoint.json'
        evidence.parent.mkdir(parents=True)
        evidence.write_text(json.dumps({'runs': runs, 'seed': seed}))
        (evidence.parent / 'guard.sql').write_text('synthetic immutable guard')
        return {'strategy': name, 'steps': [{'step': 'establish', 'unsafe': False, 'response_correct': True, 'human_minutes': 1}],
                'totals': {'steps': 1, 'unsafe': 0, 'wrong': 0, 'human_minutes': 1}, 'skipped': [],
                '_evidence_paths': [str(evidence)]}

    def invoke(self):
        return run.strategy_run(self.c, 'honest-reference')

    def test_restart_reuses_and_moved_evidence_is_supported(self):
        first = self.invoke()
        self.c = copy.deepcopy(self.c)  # no in-memory result cache survives
        (self.root / 'results').rename(self.c.work / 'bench-results')
        self.assertEqual(first, self.invoke())
        self.assertEqual(self.calls, 1)
        self.assertTrue(self.c.card['strategy_reuse']['honest-reference'])

    def test_inputs_and_result_and_evidence_invalidate(self):
        self.invoke()
        (self.root / 'bin').mkdir()
        self.implementation = 'plumbing-release-v2'
        self.invoke(); self.assertEqual(self.calls, 1)
        for change in (lambda: (self.c.case / 'judge.py').write_text('changed'),
                       lambda: setattr(self.c, 'seed', 8),
                       lambda: setattr(self.c.args, 'scenario_runs', 4),
                       lambda: setattr(self.c.args, 'bench_workers', 3),
                       lambda: (self.root / 'bin/bench_judging.py').write_text('# changed scientific evaluator'),
                       lambda: (self.c.work / 'strategy-honest-reference.json').write_text('{}'),
                       lambda: (self.root / 'results' / 'runs' / str(self.calls) / 'checkpoint.json').unlink(),
                       lambda: (self.c.work / 'strategy-honest-reference.receipt.json').write_text('{')):
            previous = self.calls
            change(); self.invoke()
            self.assertEqual(self.calls, previous + 1)

    def test_only_root_author_metadata_is_ignored(self):
        self.invoke()
        for name in ('freshness.jsonl', 'BUILD-NOTES.md'):
            (self.c.case / name).write_text('synthetic author metadata')
            self.invoke()
            self.assertEqual(self.calls, 1)
        nested = self.c.case / 'guards/reference/BUILD-NOTES.md'
        nested.parent.mkdir(parents=True)
        nested.write_text('could be consumed by a guard')
        self.invoke()
        self.assertEqual(self.calls, 2)

    def test_unrelated_concurrent_progress_is_never_receipt_evidence(self):
        original = self.module.simulate
        progress = self.root / 'results/factory-slots/9/bench-progress-999.json'
        def simulate(*a, **kw):
            result = original(*a, **kw)
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text('{"status":"running"}')
            return result
        with patch.object(self.module, 'simulate', simulate):
            self.invoke()
        receipt = json.loads((self.c.work / 'strategy-honest-reference.receipt.json').read_text())
        self.assertEqual([e['path'] for e in receipt['evidence']], ['runs/1'])
        progress.write_text('{"status":"completed"}')
        self.invoke()
        self.assertEqual(self.calls, 1)

    def test_tampered_or_missing_owned_artifacts_force_rerun(self):
        self.invoke()
        artifact = self.root / 'results/runs/1/guard.sql'
        artifact.write_text('tampered')
        self.invoke()
        self.assertEqual(self.calls, 2)
        (self.root / 'results/runs/2/guard.sql').unlink()
        self.invoke()
        self.assertEqual(self.calls, 3)

    def test_missing_or_foreign_provenance_cannot_authorize_reuse(self):
        original = self.module.simulate
        for provenance in ([], [str(self.c.work / 'checkpoint.json')],
                           [str(self.root / 'results/bench-progress-999.json')]):
            def simulate(*a, **kw):
                result = original(*a, **kw)
                result['_evidence_paths'] = provenance
                return result
            with patch.object(self.module, 'simulate', simulate):
                self.invoke()
                self.assertFalse((self.c.work / 'strategy-honest-reference.receipt.json').exists())

    def test_incomplete_result_and_receipt_never_authorize_reuse(self):
        self.invoke()
        receipt_path = self.c.work / 'strategy-honest-reference.receipt.json'
        receipt = json.loads(receipt_path.read_text())
        receipt['status'] = 'running'
        receipt_path.write_text(json.dumps(receipt))
        self.invoke()
        self.assertEqual(self.calls, 2)
        with patch.object(self.module, 'simulate', return_value={'strategy': 'honest-reference', 'steps': []}):
            receipt_path.unlink()
            with self.assertRaisesRegex(ValueError, 'incomplete strategy result'):
                self.invoke()
        self.assertFalse(receipt_path.exists())
        self.invoke()
        self.assertEqual(self.calls, 3)

    def test_strategy_and_environment_are_bound(self):
        self.invoke()
        run.strategy_run(self.c, 'frozen-first-fix')
        self.assertEqual(self.calls, 2)
        self.invoke()
        self.assertEqual(self.calls, 2)
        with patch.dict(run.os.environ, {'MEDUSA_DEPS_IMAGE': 'synthetic:test'}):
            self.invoke()
        self.assertEqual(self.calls, 3)

    def test_interruption_never_publishes_completion(self):
        with patch.object(self.module, 'simulate', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError): self.invoke()
        self.assertFalse((self.c.work / 'strategy-honest-reference.receipt.json').exists())
        self.invoke(); self.assertEqual(self.calls, 1)

    def test_no_evidence_or_changed_inputs_cannot_authorize_reuse(self):
        original = self.module.simulate
        for mode in ('no-evidence', 'changed-input'):
            def broken(*a, **kw):
                if mode == 'no-evidence':
                    return {'strategy': 'honest-reference', 'steps': [{'step': 'establish', 'unsafe': False,
                            'response_correct': True, 'human_minutes': 1}],
                            'totals': {'steps': 1, 'unsafe': 0, 'wrong': 0, 'human_minutes': 1}, 'skipped': []}
                result = original(*a, **kw)
                (self.c.case / 'judge.py').write_text(str(self.calls))
                return result
            with patch.object(self.module, 'simulate', broken):
                self.invoke()
                self.assertFalse((self.c.work / 'strategy-honest-reference.receipt.json').exists())


class StrategyPrefixRecoveryTests(unittest.TestCase):
    """Real strategy/cache/runner wiring against generated synthetic checkpoints."""
    def setUp(self):
        with patch.object(sys, 'path', [str(pathlib.Path(__file__).resolve().parents[2] / 'bin'), *sys.path]):
            import test_strategy
        self.fixture = test_strategy
        self.module = test_strategy.strategy
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name) / 'first-machine'
        self.root.mkdir()
        self.c = types.SimpleNamespace(work=self.root / 'work', case=self.root / 'case', seed=7, card={},
                                       args=types.SimpleNamespace(scenario_runs=3, bench_workers=2))
        self.c.work.mkdir(); self.c.case.mkdir(); test_strategy.fixture(self.c.case)
        self.calls = []
        self.interrupt_at = 2
        self.implementation = 'synthetic-v1'

    def driver(self, scenarios, guard, report, runs, seed, label, factory_workers):
        if len(self.calls) == self.interrupt_at: raise RuntimeError('synthetic interruption')
        self.calls.append(label)
        self.assertEqual(factory_workers, 2)
        summary = self.fixture.execute(scenarios, guard, report, runs, seed, label)
        checkpoint = self.root / 'results/factory-slots/2/runs' / str(len(self.calls)) / 'checkpoint.json'
        self.fixture.write(checkpoint, summary)
        (checkpoint.parent / 'artifact.txt').write_text('synthetic evidence')
        return {**summary, '_evidence_path': str(checkpoint)}

    def invoke(self):
        with patch.object(run, 'BENCH', self.root), patch.object(self.module, 'BENCH', self.root), \
             patch.object(run, 'bench_manifest', lambda: self.implementation), \
             patch.object(run, 'strategy_module', lambda: self.module), patch.object(self.module, 'checkpoint', self.driver):
            return run.strategy_run(self.c, 'honest-reference')

    def restore_prefix(self):
        with self.assertRaisesRegex(RuntimeError, 'synthetic interruption'): self.invoke()
        self.assertEqual(len(self.calls), 2)
        self.assertFalse((self.c.work / 'strategy-honest-reference.receipt.json').exists())
        (self.root / 'results').rename(self.c.work / 'bench-results')
        restored = self.root.parent / 'second-machine'
        restored.mkdir()
        shutil.move(str(self.c.work), restored / 'work')
        shutil.move(str(self.c.case), restored / 'case')
        self.root = restored
        self.c.work, self.c.case = restored / 'work', restored / 'case'
        self.interrupt_at = None

    def test_interrupted_prefix_reuses_after_cross_machine_move_and_publishes_final_receipt(self):
        self.restore_prefix()
        result = self.invoke()
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(result['totals'], {'steps': 4, 'unsafe': 0, 'wrong': 0, 'human_minutes': 5})
        self.assertTrue(all(not pathlib.Path(p).is_absolute() for p in result['_evidence_paths']))
        self.assertEqual(self.invoke(), result)
        self.assertTrue(self.c.card['strategy_reuse']['honest-reference'])
        # Even without the final receipt, the mixed restored/new checkpoint set is reusable.
        (self.c.work / 'strategy-honest-reference.receipt.json').unlink()
        self.assertEqual(self.invoke(), result)
        self.assertEqual(len(self.calls), 4)
        third = self.root.parent / 'third-machine'
        self.root.rename(third)
        self.root = third
        self.c.work, self.c.case = third / 'work', third / 'case'
        self.assertEqual(self.invoke(), result)
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(self.c.card['strategy_reuse']['honest-reference'])

    def test_pinned_worker_strategy_before_sharing_still_runs(self):
        # Byte-identical to bin/strategy at 72def83e and the live pinned worker image.
        import hashlib
        import importlib.machinery
        import importlib.util
        path = _TestPath(__file__).resolve().parents[1] / 'fixtures/strategy-pre-sharing.py'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         '6e8aa9037f347c4519fae691eacfdff8ea657e68dd0694f59d39b4c70c6d629f')
        loader = importlib.machinery.SourceFileLoader('strategy_before_sharing', str(path))
        self.module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(self.module)
        self.interrupt_at = None
        result = self.invoke()
        self.assertEqual(result['totals'], {'steps': 4, 'unsafe': 0, 'wrong': 0, 'human_minutes': 5})
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(self.invoke(), result)
        self.assertEqual(len(self.calls), 4)

    def test_one_runner_executes_identical_strategy_steps_once(self):
        self.interrupt_at = None
        def invoke(name):
            with patch.object(run, 'BENCH', self.root), patch.object(self.module, 'BENCH', self.root), \
                 patch.object(run, 'bench_manifest', lambda: self.implementation), \
                 patch.object(run, 'strategy_module', lambda: self.module), patch.object(self.module, 'checkpoint', self.driver):
                return run.strategy_run(self.c, name)
        counts = {}
        for name in ('frozen-first-fix', 'honest-reference', 'claim-without-evidence', 'ask-everything', 'block-all-pending'):
            before = len(self.calls); invoke(name); counts[name] = len(self.calls) - before
            # Each strategy still earns its own completion receipt over the evidence it scored.
            self.assertTrue((self.c.work / f'strategy-{name}.receipt.json').is_file(), name)
        # G13's frozen-first-fix keeps its own executions; only the G15 strategies share.
        self.assertEqual(counts, {'frozen-first-fix': 4, 'honest-reference': 4, 'claim-without-evidence': 3,
                                  'ask-everything': 0, 'block-all-pending': 1})
        # A changed case is a different execution for every strategy.
        (self.c.case / 'promise.md').write_text('changed')
        before = len(self.calls); invoke('ask-everything')
        self.assertEqual(len(self.calls), before + 4)
        # A fresh runner process shares nothing in memory; the strategy's own receipt decides.
        del self.c.strategy_shared
        before = len(self.calls); invoke('ask-everything')
        self.assertEqual(len(self.calls), before)

    def test_moved_prefix_tampered_missing_inputs_seed_and_code_invalidate(self):
        self.restore_prefix()
        evidence = self.c.work / 'bench-results/factory-slots/2/runs'
        (evidence / '1/artifact.txt').write_text('tampered')
        (evidence / '2/checkpoint.json').unlink()
        self.invoke()
        self.assertEqual(len(self.calls), 6)
        (self.root / 'bin').mkdir()
        self.implementation = 'plumbing-release-v2'
        self.invoke(); self.assertEqual(len(self.calls), 6)
        for change in (lambda: (self.c.case / 'guards/reference/db.sql').write_text('-- changed synthetic input'),
                       lambda: setattr(self.c, 'seed', 8),
                       lambda: (self.root / 'bin/bench_judging.py').write_text('# changed scientific evaluator')):
            before = len(self.calls)
            change(); self.invoke()
            self.assertEqual(len(self.calls), before + 4)

    def test_factory_wiring_reuses_other_steps_and_reruns_the_silent_window(self):
        self.interrupt_at = None
        meta = json.loads((self.c.case / 'case.json').read_text())
        meta['steps'].insert(1, 'quiet')
        self.fixture.write(self.c.case / 'case.json', meta)
        self.fixture.write(self.c.case / 'scenarios/quiet/scenario.json', {'id': 'quiet', 'delivery': 'unannounced'})
        self.fixture.write(self.c.case / 'scenarios/quiet/key.json', {'correct_responses': ['keep']})
        windows, interrupt = [], [False]
        def silent(case, step, prior, guard, report, watching):
            # Like production: a valid window leaves checkpoint.json under results/windows/.
            if interrupt[0]: raise RuntimeError('synthetic window interruption')
            windows.append(step['id'])
            summary = {'latest_claims': {}, 'claims_score': {'unsafe_checkpoint': False, 'response_correct': True,
                       'human_minutes': {'total': 0}, 'exposure': {}}}
            path = self.root / 'results/windows' / f'quiet-{len(windows)}' / 'checkpoint.json'
            self.fixture.write(path, summary)
            return {**summary, '_evidence_path': str(path)}
        def invoke(name):
            with patch.object(run, 'BENCH', self.root), patch.object(self.module, 'BENCH', self.root), \
                 patch.object(run, 'bench_manifest', lambda: self.implementation), \
                 patch.object(run, 'strategy_module', lambda: self.module), patch.object(self.module, 'checkpoint', self.driver), \
                 patch.object(self.module, 'silent_checkpoint', silent):
                return run.strategy_run(self.c, name)
        invoke('frozen-first-fix')
        self.assertEqual((len(self.calls), len(windows)), (4, 1))
        # Incomplete strategy: the window is cut after establish and blind completed.
        interrupt[0] = True
        with self.assertRaisesRegex(RuntimeError, 'synthetic window interruption'): invoke('honest-reference')
        self.assertEqual(len(self.calls), 6, 'G13 executions are never shared with G15 strategies')
        self.assertFalse((self.c.work / 'strategy-honest-reference.receipt.json').exists())
        # Restarted runner: completed checkpoints come from the per-step cache, the window runs again.
        interrupt[0] = False
        del self.c.strategy_shared
        first = invoke('honest-reference')
        self.assertEqual((len(self.calls), len(windows)), (8, 2))
        self.assertFalse(self.c.card['strategy_reuse']['honest-reference'])
        invoke('ask-everything')
        self.assertEqual((len(self.calls), len(windows)), (8, 3), 'shared steps, its own fresh window')
        # A strategy that completed in full (window evidence included) is reused as a whole, as before.
        del self.c.strategy_shared
        self.assertEqual(invoke('honest-reference'), first)
        self.assertEqual((len(self.calls), len(windows)), (8, 3))
        self.assertTrue(self.c.card['strategy_reuse']['honest-reference'])
        self.assertTrue((self.c.work / 'strategy-honest-reference-checkpoints').is_dir())

if __name__ == '__main__': unittest.main()
