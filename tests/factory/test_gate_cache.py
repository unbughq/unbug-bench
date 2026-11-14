"""Offline gate-cache and scoped evidence regressions; synthetic inputs only."""

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
import run


class EvidenceCacheTests(unittest.TestCase):
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

    def test_a_cache_miss_logs_the_changed_field_names_only(self):
        self.save()
        (self.c.case / 'base/secret-name.py').write_text('x')
        self.assertIsNone(gate_state.load(self.c, 'G4', self.root))
        log = (self.c.work / 'logs/runner.log').read_text()
        self.assertIn('gate cache miss G4: inputs changed: case', log)
        self.assertNotIn('secret-name', log)
        with patch.dict(os.environ, {'UNBUG_JUDGE': 'zz'}):
            self.assertIsNone(gate_state.load(self.c, 'G4', self.root))
        self.assertIn('environment.UNBUG_JUDGE', (self.c.work / 'logs/runner.log').read_text())

    def test_checked_gate_records_matched_version(self):
        self.save()
        with patch.object(run, 'BENCH', self.root), patch.object(run, 'g4') as gate:
            ok, info = run.checked_gate(self.c, 'G4')
        self.assertTrue(ok); gate.assert_not_called()
        self.assertTrue(info['reused_verified_evidence']); self.assertEqual(info['fingerprint_version'], gate_state.VERSION)

    def early_lane_g4(self, *, owner=True):
        """G4 run on run.early_lane's reserved instance (slot 2, one worker), beside a G15 writing slot 0."""
        self.c.args.bench_workers = 2
        (self.root / 'bin').mkdir(exist_ok=True); (self.root / 'bin/factory_pool.py').write_text('pool')
        with patch.object(run, 'parallel_gates', return_value=True), patch.object(run, 'g10_overlap_reason', return_value=None):
            lane = run.early_lane(self.c)
        self.assertEqual((lane.factory_slot, lane.args.bench_workers), (2, 1))
        if not owner: del lane.reuse_as
        lane.evidence_scope = lambda kind, rel: rel.startswith('factory-slots/2/') if kind == 'bench' else True
        def g4(c):
            for rel in ('factory-slots/2/runs/g4/checkpoint.json', 'runs/g15-step/checkpoint.json',
                        'bench-progress-11.json', 'factory-slots/2/bench-progress-12.json'):
                path = self.root / 'results' / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(rel)
            return True, {'broke': '3/10'}
        with patch.object(run, 'BENCH', self.root), patch.object(run, 'g4', g4):
            self.assertEqual(run.checked_gate(lane, 'G4'), (True, {'broke': '3/10'}))
        # GATES restores a fresh context: foreground pool, no slot attribute.
        gates = types.SimpleNamespace(**vars(self.c)); gates.args = copy.copy(self.c.args)
        with patch.object(run, 'BENCH', self.root), patch.object(run, 'g4', return_value=(True, {})) as gate:
            return run.checked_gate(gates, 'G4'), gate

    def test_an_early_lane_g4_is_reused_at_gates(self):
        (ok, info), gate = self.early_lane_g4()
        gate.assert_not_called()
        self.assertTrue(ok); self.assertTrue(info['reused_verified_evidence'])
        record = json.loads((self.c.work / 'gate-cache/G4.json').read_text())
        self.assertEqual([e['path'] for e in record['evidence']], ['factory-slots/2/runs/g4/checkpoint.json'],
                         "only the lane's own run: neither G15's files nor live progress files")

    def test_the_lane_owner_identity_is_what_makes_it_reusable(self):
        _, gate = self.early_lane_g4(owner=False)
        gate.assert_called_once()

    def test_a_review_the_side_lane_renames_mid_listing_is_not_a_crash(self):
        """cae763 (14 November): G16's inventory listed review-1/verdict.json, then the G8 lane's
        review() renamed review-1 before G16 read it; G16 crashed FileNotFoundError."""
        review = self.c.work / 'review-1'; review.mkdir(); (review / 'verdict.json').write_text('{}')
        listed = gate_state.inventory
        def inventory(c, bench):
            paths = listed(c, bench)
            if review.exists(): review.rename(self.c.work / 'review-superseded-1-1')
            return paths
        with patch.object(gate_state, 'inventory', inventory), patch.object(run, 'BENCH', self.root), \
                patch.object(run, 'g4', return_value=(True, {'broke': '3/10'})):
            self.assertEqual(run.checked_gate(self.c, 'G4'), (True, {'broke': '3/10'}))


if __name__ == '__main__': unittest.main()
