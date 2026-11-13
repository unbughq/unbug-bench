"""A finished gate checkpoint is kept in c.work/gate-checkpoints and skipped on retry; any input change reruns."""
import fnmatch
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import run
import gate_state
import claims
from durable import checkpoints as engine_checkpoints
from checkpoint_evidence import publish
from test_invalid_runs import batch, PRACTICE


class GateCheckpointReceipts(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(run, 'BENCH', ROOT), patch.object(run, 'case_budget_boundary')):
            p.start(); self.addCleanup(p.stop)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        case = self.work / 'case'; case.mkdir()
        for name, content in PRACTICE['files'].items():
            path = case / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
        self.c = SimpleNamespace(work=self.work, case=case, seed=42, card={'gates': {}}, manifest0='b1',
            args=run.argument_parser().parse_args([]))
        self.out = self.work / 'out'; self.out.mkdir()
        summary, records = batch('reference')
        self.runs = summary['runs']
        for n, row in enumerate(records, 1): (self.out / f'{n:02}.json').write_text(json.dumps(row))
        (self.out / 'checkpoint.json').write_text(json.dumps(summary))
        self.receipt = publish(self.out, summary, self.runs)

    def call(self, slot=None, seed=42, label='g5-reference'):
        return run.checkpoint(self.c, [self.c.case / 'base'], self.c.case / 'guards/reference',
                              self.runs, seed, label, slot=slot)

    def shell(self):
        return patch.object(run, 'sh', side_effect=lambda *a, **k: subprocess.CompletedProcess([], 0, self.receipt, ''))

    def test_finished_checkpoint_is_not_rerun_and_gives_same_result(self):
        with self.shell() as sh:
            first = self.call()
            self.c.args.bench_workers = 4  # worker count is not part of the identity
            again = self.call()
        self.assertEqual(sh.call_count, 1)
        self.assertEqual(first, again)

    def test_survives_a_fresh_worker_that_only_has_the_snapshot(self):
        with self.shell():
            first = self.call()
        for f in self.out.glob('*.json'): f.unlink()  # the bench results are gone with the old worker
        with self.shell() as sh:
            self.assertEqual(self.call(), first)
        sh.assert_not_called()

    def test_any_input_change_reruns(self):
        with self.shell() as sh:
            self.call()
            self.call(seed=43)
            self.call(label='g5-other')
            (self.c.case / 'base/NEW').write_text('x')
            self.call()
        self.assertEqual(sh.call_count, 4)

    def test_execution_environment_change_reruns(self):
        for key in ('MEDUSA_DEPS_IMAGE', 'UNBUG_JUDGE'):
            with self.subTest(key), self.shell() as sh:
                with patch.dict('os.environ', {key: 'one'}):
                    self.call()
                with patch.dict('os.environ', {key: 'two'}):
                    self.call()
                    self.call()   # the same environment again is reused
                self.assertEqual(sh.call_count, 2)

    def test_deps_image_file_binds_the_gate_identity_when_the_variable_is_unset(self):
        # bin/bench.py runs with /opt/medusa-deps-image when MEDUSA_DEPS_IMAGE is unset; a saved gate
        # pass must not be reused once that file names another image.
        deps = self.work / 'medusa-deps-image'
        env = {k: v for k, v in run.os.environ.items() if k != 'MEDUSA_DEPS_IMAGE'}
        with patch.object(gate_state, 'DEPS_IMAGE_FILE', deps, create=True), patch.dict('os.environ', env, clear=True):
            deps.write_text('one\n')
            first = gate_state.fingerprint(self.c, 'G5', ROOT), gate_state.scientific_version(self.c, 'G5', ROOT)
            deps.write_text('two\n')
            second = gate_state.fingerprint(self.c, 'G5', ROOT), gate_state.scientific_version(self.c, 'G5', ROOT)
        self.assertNotEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])
        # Set but empty, bench.py passes the empty value to Docker and never reads the file.
        with patch.object(gate_state, 'DEPS_IMAGE_FILE', deps), patch.dict('os.environ', {**env, 'MEDUSA_DEPS_IMAGE': ''}, clear=True):
            self.assertEqual(gate_state.environment('MEDUSA_DEPS_IMAGE'), {'MEDUSA_DEPS_IMAGE': ''})
            self.assertNotEqual(gate_state.fingerprint(self.c, 'G5', ROOT), second[0])

    def test_forget_receipts_survives_a_concurrent_note(self):
        mine = {}
        class Label(str):   # another lane notes a receipt while forget_receipts walks the labels
            def startswith(self, *a):
                mine.setdefault('g5-late', 'x'); return str.startswith(self, *a)
        mine[Label('g6-a')] = 'x'
        with patch.dict(gate_state.RECEIPTS, {str(self.c.work): mine}):
            gate_state.forget_receipts(self.c, 'G6')
        self.assertEqual(list(mine), ['g5-late'])

    def test_saved_batch_with_a_missing_run_is_not_reused(self):
        with self.shell():
            self.call()
        next(self.work.glob('gate-checkpoints/*/01.json')).unlink()
        with self.shell() as sh:
            self.call()
        self.assertEqual(sh.call_count, 1)

    def test_g10_and_rerun_labels_are_never_reused(self):
        with self.shell() as sh:
            self.call(label='g10-x'); self.call(label='g10-x'); self.call(label='g11-rerun'); self.call(label='g11-rerun')
        self.assertEqual(sh.call_count, 4)

    def cheats(self, n):
        guards = []
        for i in range(n):
            g = self.c.case / f'guards/cheats/c{i}'; g.mkdir(parents=True, exist_ok=True); (g / 'x').write_text(str(i)); guards.append(g)
        return guards

    def test_killed_g6_retried_reruns_only_unfinished_cheats_with_same_verdicts(self):
        guards = self.cheats(5)
        calls = []
        patch.object(run, 'verdicts', return_value=[{'solved': True}]).start(); self.addCleanup(patch.stopall)
        def killed(*a, **k):
            if len(calls) == 3: raise KeyboardInterrupt  # the worker dies in the middle of the fourth cheat
            calls.append(1); return subprocess.CompletedProcess([], 0, self.receipt, '')
        with patch.object(run, 'sh', side_effect=killed):
            with self.assertRaises(KeyboardInterrupt): run.cheat_runs(self.c, 42, 'g6', guards=guards, runs=self.runs)
        with self.shell() as sh:
            retried = run.cheat_runs(self.c, 42, 'g6', guards=guards, runs=self.runs)
        self.assertEqual(sh.call_count, 2)
        with self.shell():
            # an uninterrupted pass over fresh receipts gives the same verdicts
            import shutil; shutil.rmtree(self.work / 'gate-checkpoints')
            self.assertEqual(run.cheat_runs(self.c, 42, 'g6', guards=guards, runs=self.runs), retried)

    def test_scoring_identity_change_reruns(self):
        with self.shell() as sh:
            self.call()
            with patch.object(claims, 'scoring_identity', return_value={'scoring_source_sha256': 'other'}):
                self.call()
        self.assertEqual(sh.call_count, 2)

    def test_bench_manifest_change_reruns(self):
        with self.shell() as sh:
            self.call(); self.c.manifest0 = 'b2'; self.call()
        self.assertEqual(sh.call_count, 2)

    def test_saved_batch_whose_summary_disagrees_with_its_records_is_not_reused(self):
        with self.shell():
            self.call()
        d = next(self.work.glob('gate-checkpoints/*'))
        summary = json.loads((d / 'checkpoint.json').read_text()); summary['runs'] += 1
        (d / 'checkpoint.json').write_text(json.dumps(summary))
        with self.shell() as sh:
            self.call()
        self.assertEqual(sh.call_count, 1)

    def test_gate_evidence_covers_reused_and_moved_checkpoints(self):
        bench = self.work / 'bench'; (bench / 'results').mkdir(parents=True)
        before = {k: gate_state.digest(p) for k, p in gate_state.inventory(self.c, bench).items()}
        gate_state.forget_receipts(self.c, 'G5')
        with self.shell():
            self.call(); self.call(label='g5-other')
        gate_state.forget_receipts(self.c, 'G5')
        with self.shell() as sh:  # the retry reuses both; nothing new appears under bench/results
            self.call(); self.call(label='g5-other')
        sh.assert_not_called()
        moved = self.work / 'bench-results/factory-slots/1/r.json'; moved.parent.mkdir(parents=True); moved.write_text('{}')
        with patch.object(gate_state, 'inputs', return_value={}), patch.object(gate_state, 'scientific_version', return_value='v'):
            gate_state.save(self.c, 'G5', {}, 'sig', before, bench)
        record = json.loads((self.work / 'gate-cache/G5.json').read_text())
        paths = {e['path'] for e in record['evidence']}
        self.assertEqual(len([p for p in paths if p.startswith('gate-checkpoints/')]), 2 * (1 + self.runs + 1))
        self.assertIn('factory-slots/1/r.json', paths)

    def test_receipt_helpers_do_not_change_gate_runner_digests(self):
        for gate in ('G4', 'G5', 'G6'):
            names = gate_state.runner_inputs(gate)
            for n in ('_save_checkpoint', '_checkpoint_receipt_dir', 'under_engine', 'shutil'):
                self.assertNotIn(n, names, (gate, n))
            # Which saved samples stand in for a fresh run is verdict code: loosening it invalidates caches.
            self.assertIn('_saved_checkpoint', names, gate)

    def test_g5_key_threads_run_inside_a_concurrent_section(self):
        c = self.c; c.engine = SimpleNamespace(); c.args.bench_workers = 2; c.args.runs = 1
        for d in ('s1', 's2'):
            (c.case / 'scenarios' / d).mkdir(parents=True); (c.case / 'scenarios' / d / 'key.json').write_text('{"expected_judge": {"a": 1}}')
        seen = []
        def fake(c_, scenarios, guard, runs, seed, label, slot=None, **k):
            seen.append((label, engine_checkpoints._unsettled(c_))); return {'legit_completion': 1, 'key_consistent': True}, []
        with patch.object(run, 'checkpoint', side_effect=fake), patch.object(run, 'verdicts', return_value=[{'solved': True}]), \
             patch.object(run, 'find_guard', return_value=c.case / 'base'), patch.object(run, 'no_fixed_port_services', return_value=True):
            ok, _ = run.g5(c)
        self.assertTrue(ok)
        keys = [u for label, u in seen if label == 'g5-key']
        self.assertTrue(keys and all(keys))

    def test_snapshot_keeps_receipts(self):
        for n in ('gate-checkpoints', 'strategy-g15-checkpoints', 'strategy-g14-checkpoints',
                  'helper-tries', 'helper-results', 'helper-ledger.jsonl'):
            self.assertTrue(any(fnmatch.fnmatch(n, pat) for pat in run.SNAPSHOT_RETAINED), n)

    def test_a_helper_batch_is_registered_as_gate_evidence(self):
        from durable import helpers
        files = {f.name: f.read_text() for f in self.out.glob('*.json')}
        with patch.dict(gate_state.RECEIPTS, {}, clear=True):
            helpers._read_batch(self.c, {'runs': self.runs, 'label': 'g5-reference'}, files, 'g5-reference')
            (directory,) = gate_state.RECEIPTS[str(self.c.work)]['g5-reference']
        self.assertEqual(directory.parent, self.work / 'helper-results')


if __name__ == '__main__':
    unittest.main()
