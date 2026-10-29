"""Offline salvage and scoped evidence regressions; synthetic inputs only."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import gate_state
import restart
import run


class SalvageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.c = c = types.SimpleNamespace(work=self.root / 'work', seed=7, manifest0='old',
            args=types.SimpleNamespace(runs=10, scenario_runs=3, dry_run=False, resume=True, max_repairs=2, bench_workers=1),
            card={'gates': {}}, models={})
        c.case = c.work / 'case'; (c.case / 'base').mkdir(parents=True)
        (c.work / 'logs').mkdir(); (c.case / 'base/judge.py').write_text('judge')
        self.card = {'case': 'case-test', 'seed': 7, 'status': 'stopped', 'terminal_stop': 'runner_error:RuntimeError',
            'gates': {'G4': 'pass', 'G15': 'fail'}, 'failed_gate': 'G15', 'failed_detail': {'error': 'RuntimeError'},
            'gate_results': {'G15': {'error': 'RuntimeError'}},
            'continuation_budget': {'cost': 1, 'calls': 2, 'events': [], 'terminal_stop': 'complete'}}
        archive = self.root / 'case-test.checkpoint.tar.gz.age'; archive.write_bytes(b'synthetic ciphertext')
        self.card['sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.path = self.root / 'case-test.scorecard.json'
        self.runner = self.root / 'run.py'
        self.runner.write_text('LIMIT = 1\ndef helper(c):\n    return LIMIT\ndef g4(c):\n    return helper(c)\ndef unrelated():\n    return 1\n')
        p = patch.object(gate_state, 'RUNNER', self.runner, create=True); p.start(); self.addCleanup(p.stop)

    def plan(self, card):
        self.path.write_text(json.dumps(card))
        return restart.plan(self.path, 0, 7200, '--max-cost 2 --max-total-calls 10')

    def crash(self, error='RuntimeError', attempt=1):
        directory = self.c.work / 'gate-details'; directory.mkdir(exist_ok=True)
        (directory / f'G15.crash-{attempt}.json').write_text(json.dumps({'error': error, 'message': 'synthetic', 'traceback': 'synthetic'}))

    def test_public_crash_stop_is_restorable_but_real_failure_is_not(self):
        self.assertEqual(self.plan(self.card), ('case-test', 60, 7))
        for detail in ({'problems': ['defect']}, {'error': 'RuntimeError', 'problems': []}, {'error': ''}, ['RuntimeError']):
            with self.subTest(detail=detail), self.assertRaises(ValueError):
                self.plan({**self.card, 'failed_detail': detail})
        with self.assertRaises(ValueError): self.plan({**self.card, 'terminal_stop': 'cost_limit'})
        conflict = copy.deepcopy(self.card); conflict['gate_results']['G15'] = {'problems': ['defect']}
        with self.assertRaises(ValueError): self.plan(conflict)

    def test_worker_requires_matching_crash_and_never_charges_writer(self):
        with self.assertRaises(ValueError): run.restore_gate_crash(self.c, self.card)
        self.crash('OSError')
        with self.assertRaises(ValueError): run.restore_gate_crash(self.c, self.card)
        self.crash(attempt=2)
        run.restore_gate_crash(self.c, self.card)
        self.assertEqual(self.c.card['salvaged_from'], {'gate': 'G15', 'error_type': 'RuntimeError', 'attempt': 2})
        self.assertTrue(self.c.args.skip_build)
        self.c.audit_gates = ['G15']
        with patch.object(run.GatePipeline, 'check', return_value=(True, {})) as gate, patch.object(run, 'write_and_attack') as writer:
            run.validate_and_repair(self.c)
        gate.assert_called_once_with(self.c, 'G15'); writer.assert_not_called()
        self.assertNotIn('builder_rounds', self.c.card)
        (self.c.case / 'statement.md').write_text('changed statement')
        with self.assertRaises(ValueError):
            run.restore_gate_crash(self.c, {**self.card, 'statement_sha256': 'old'})

    def test_main_resume_keeps_writer_rounds_and_verified_gate_evidence(self):
        harness = r'''
import hashlib, json, pathlib, sys, types
from unittest.mock import patch
import run, gate_state, worker_release
root = pathlib.Path(sys.argv[1]); work = root / 'work/case-test'
(work / 'case/base').mkdir(parents=True); (work / 'logs').mkdir()
(work / 'case/base/judge.py').write_text('synthetic judge')
(work / 'case/statement.md').write_text('synthetic statement')
(work / 'gate-details').mkdir()
(work / 'gate-details/G15.crash-1.json').write_text(json.dumps({'error': 'RuntimeError', 'message': 'synthetic', 'traceback': 'synthetic'}))
(work / 'review-1').mkdir(); (work / 'review-1/verdict.json').write_text('{}')
(work / 'scorecard.json').write_text(json.dumps({'failed_gate': 'G15', 'failed_detail': {'error': 'RuntimeError'},
    'gates': {'G4': 'pass', 'G15': 'fail'}, 'builder_rounds': 2, 'admission': {'status': 'passed'},
    'statement_sha256': hashlib.sha256(b'synthetic statement').hexdigest()}))
run.HOME, run.SEALED, run.BENCH = root, root / 'output', root / 'bench'
run.GATES = ['G4', 'G15']
run.sh = lambda *a, **kw: 0
run.bench_manifest = lambda: 'trusted'
run.pilot_homes = lambda: []
run.seal = lambda *a, **kw: None
run.wipe = lambda *a: None
run.build = lambda *a: (_ for _ in ()).throw(AssertionError('writer must not run'))
run.g4 = lambda *a: (_ for _ in ()).throw(AssertionError('verified G4 must not run'))
def models(c):
    assert (work / 'review-1/verdict.json').exists(), 'resume moved verified review evidence'
    c.models = {'builder': ['synthetic/test']}
    gate_state.save(c, 'G4', {'broke': '1/1'}, gate_state.fingerprint(c, 'G4', run.BENCH), {}, run.BENCH)
    return c.models
def gate(c):
    (root / 'retried-G15').touch()
    return True, {}
run.pick_models, run.g15 = models, gate
worker_release.verify_selected_drivers = lambda *a: {}
with patch.object(run.shutil, 'which', return_value='synthetic'), patch.object(sys, 'argv',
        ['run.py', '--source', 'port', '--resume', 'case-test', '--resume-bench-sha', 'trusted', '--no-early-probe']):
    run.main()
'''
        result = subprocess.run([sys.executable, '-c', harness, str(self.root)],
            cwd=pathlib.Path(run.__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        card = json.loads((self.root / 'output/case-test.scorecard.json').read_text())
        self.assertNotIn('terminal_stop', card, card)
        self.assertTrue((self.root / 'retried-G15').exists(), card)
        self.assertEqual(card['builder_rounds'], 2)
        self.assertEqual(card['admission'], {'status': 'passed'})
        self.assertEqual(card['statement_sha256'], hashlib.sha256(b'synthetic statement').hexdigest())
        self.assertEqual(card['salvaged_from'], {'gate': 'G15', 'error_type': 'RuntimeError', 'attempt': 1})
        self.assertEqual(card['gate_results']['G4']['fingerprint_version'], gate_state.VERSION)

    def test_repeat_crash_keeps_failed_gate_and_is_operational_on_resume(self):
        self.c.audit_gates = ['G15']; self.c.stopped = False
        with patch.object(run.GatePipeline, 'check', side_effect=RuntimeError('synthetic')), patch.object(run, 'write_and_attack') as writer:
            run.validate_and_repair(self.c)
        writer.assert_not_called()
        self.assertTrue(self.c.stopped)
        self.assertNotIn('failed_gate', self.c.card)
        self.assertNotIn('failed_detail', self.c.card)
        self.assertEqual(self.c.card['terminal_stop'], 'infrastructure_exhausted')

    def save(self):
        evidence = self.root / 'results/trial.json'; evidence.parent.mkdir(exist_ok=True); evidence.write_text('{}')
        signature = gate_state.fingerprint(self.c, 'G4', self.root)
        gate_state.save(self.c, 'G4', {'pass': True}, signature, {}, self.root)
        return self.c.work / 'gate-cache/G4.json'

    def test_unrelated_bench_and_runner_changes_keep_verified_reuse(self):
        self.save()
        (self.root / 'bin').mkdir(exist_ok=True)
        (self.root / 'bin/factory_pool.py').write_text('unrelated serial orchestration')
        self.c.manifest0 = 'different whole bench'
        self.runner.write_text(self.runner.read_text().replace('def unrelated():\n    return 1', 'def unrelated():\n    return 2'))
        self.assertEqual(gate_state.load(self.c, 'G4', self.root), {'pass': True})
        self.assertEqual(self.c.gate_fingerprint_versions['G4'], gate_state.VERSION)

    def test_gate_dependencies_invalidate_reuse(self):
        for relative in ('work/case/base/judge.py', 'cases/medusa-oversell/checker/check.sql', 'bin/bench.py'):
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('before'); self.save(); path.write_text('after')
            with self.subTest(path=relative): self.assertIsNone(gate_state.load(self.c, 'G4', self.root))
        for before, after in (('return helper(c)', 'return False'), ('LIMIT = 1', 'LIMIT = 2'), ('return LIMIT', 'return 3')):
            self.save(); source = self.runner.read_text(); self.runner.write_text(source.replace(before, after))
            with self.subTest(source=before): self.assertIsNone(gate_state.load(self.c, 'G4', self.root))
            self.runner.write_text(source)
        self.save()
        judge = '' if os.environ.get('UNBUG_JUDGE') else '1'
        with patch.dict(os.environ, {'UNBUG_JUDGE': judge}):
            self.assertIsNone(gate_state.load(self.c, 'G4', self.root))

    def test_parallel_pool_dispatch_is_conservatively_bound(self):
        self.c.args.bench_workers = 2
        path = self.root / 'bin/factory_pool.py'; path.parent.mkdir(exist_ok=True)
        path.write_text('before'); self.save(); path.write_text('after')
        self.assertIsNone(gate_state.load(self.c, 'G4', self.root))

    def test_strategy_checkpoint_cache_changes_invalidate_gate_passes(self):
        self.runner.write_text(self.runner.read_text() + ''.join(
            f'\ndef {gate.lower()}(c):\n    return True\n' for gate in ('G13', 'G14', 'G15')))
        dependency = self.root / 'bin/strategy_resume.py'
        dependency.parent.mkdir()
        evidence = self.root / 'results/strategy.json'
        evidence.parent.mkdir(); evidence.write_text('{}')
        for gate in ('G13', 'G14', 'G15'):
            with self.subTest(gate=gate):
                dependency.write_text('original checkpoint reuse implementation')
                signature = gate_state.fingerprint(self.c, gate, self.root)
                gate_state.save(self.c, gate, {'pass': True}, signature, {}, self.root)
                self.assertEqual(gate_state.load(self.c, gate, self.root), {'pass': True})
                dependency.write_text('corrected checkpoint reuse implementation')
                self.assertIsNone(gate_state.load(self.c, gate, self.root))

    def test_v1_opaque_hash_cannot_authorize_reuse(self):
        path = self.save(); record = json.loads(path.read_text())
        self.assertEqual(record['fingerprint_version'], gate_state.VERSION)
        self.assertIn('inputs', record); self.assertIn('runner', record['inputs'])
        record.pop('fingerprint_version'); record.pop('inputs'); path.write_text(json.dumps(record))
        self.assertIsNone(gate_state.load(self.c, 'G4', self.root))

    def test_checked_gate_records_matched_version(self):
        self.save()
        with patch.object(run, 'BENCH', self.root), patch.object(run, 'g4') as gate:
            ok, info = run.checked_gate(self.c, 'G4')
        self.assertTrue(ok); gate.assert_not_called()
        self.assertTrue(info['reused_verified_evidence']); self.assertEqual(info['fingerprint_version'], gate_state.VERSION)


if __name__ == '__main__': unittest.main()
