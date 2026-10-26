"""Synthetic public fixture: phase metadata, isolation invariants and trial accounting."""
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'bin'))

SPEC = importlib.util.spec_from_file_location('bench_progress_test', pathlib.Path(__file__).resolve().parents[2] / 'bin/bench.py')
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


class ProgressTests(unittest.TestCase):
    def test_reset_keeps_clean_state_and_times_each_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            events = []
            def dc(*args, **kwargs):
                events.append(('dc', args))
            def sql(query, **kwargs):
                events.append(('sql', query))
                return '1'
            with mock.patch.object(bench, 'RESULTS', root), mock.patch.object(bench, 'resolve_guard', return_value=root), \
                 mock.patch.object(bench, 'stop_inventory_services', side_effect=lambda: events.append(('stop_inventory',))), \
                 mock.patch.object(bench, 'inventory_services', return_value=[]), mock.patch.object(bench, 'dc', side_effect=dc), \
                 mock.patch.object(bench, 'sql', side_effect=sql), mock.patch.object(bench, 'checker', return_value=bench.EXPECTED_BASELINE), \
                 mock.patch.object(bench, 'start_app', side_effect=lambda patches: events.append(('start_app',))), \
                 mock.patch.object(bench, 'start_inventory_services', return_value={}):
                progress = bench.BenchProgress(2)
                with mock.patch.object(bench, '_PROGRESS', progress):
                    for _ in range(2):
                        bench.reset(app_prepared=True)
                self.assertEqual(sum(e[0] == 'sql' and 'DROP DATABASE IF EXISTS medusa' in e[1] for e in events), 2)
                self.assertEqual(events.count(('dc', ('exec', '-T', 'redis', 'redis-cli', 'FLUSHALL'))), 2)
                self.assertEqual(events.count(('start_app',)), 2)
                self.assertEqual(set(progress.data['phase_seconds']), {'reset_stop', 'reset_database_cache', 'reset_app_start', 'reset_inventory_start'})
                self.assertTrue(all(t >= 0 for t in progress.data['phase_seconds'].values()))

    def test_completed_trials_do_not_leak_labels_or_verdicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            guard = root / 'private-guard'; guard.mkdir()
            seen = []
            def run_once(path, i, *args):
                seen.append(i)
                state = json.loads(next(root.glob('bench-progress-*.json')).read_text())
                self.assertEqual(state['completed_trials'], len(seen) - 1)
                return {'checker': {'valid': True, 'pass': False}, 'traffic': {}, 'errors': [], 'reset_seconds': 0}
            with mock.patch.multiple(bench, ROOT=root, RESULTS=root), \
                 mock.patch.object(bench, 'resolve_guard', return_value=guard), mock.patch.object(bench, 'prepare_app_guard') as prepare, \
                 mock.patch.object(bench, 'bench_fingerprint', return_value={}), mock.patch.object(bench, 'run_once', side_effect=run_once):
                bench.run_case(guard, 2, run_numbers=[3, 9], label='private-label')
                prepare.assert_called_once()
            state = json.loads(next(root.glob('bench-progress-*.json')).read_text())
            self.assertEqual(seen, [3, 9])
            self.assertEqual(state['completed_trials'], 2)
            self.assertEqual(state['status'], 'completed')  # completion means executed, not passed
            self.assertNotIn('private', json.dumps(state))
            self.assertNotIn('checker', state)
            self.assertIn('prepare', state['phase_seconds'])

    def test_phase_clock_measures_elapsed_and_restores_parent(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(bench, 'RESULTS', pathlib.Path(tmp)):
            progress = bench.BenchProgress(1)
            with mock.patch.object(bench.time, 'monotonic', side_effect=[10.0, 12.0, 15.0, 18.0]):
                with progress.phase('reset'):
                    with progress.phase('reset_app_start'):
                        state = json.loads(progress.path.read_text())
                        self.assertEqual(state['phase'], 'reset_app_start')
                    self.assertEqual(progress.data['phase'], 'reset')
            self.assertEqual(progress.data['phase_seconds'], {'reset_app_start': 3.0, 'reset': 8.0})

    def test_failure_is_terminal_without_exception_text(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(bench, 'RESULTS', pathlib.Path(tmp)), \
             mock.patch.object(bench, '_run_case', side_effect=RuntimeError('private content')):
            with self.assertRaises(RuntimeError):
                bench.run_case('secret', 3)
            state = json.loads(next(pathlib.Path(tmp).glob('bench-progress-*.json')).read_text())
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['completed_trials'], 0)
            self.assertNotIn('private', json.dumps(state))
            self.assertIsNone(bench._PROGRESS)

if __name__ == '__main__':
    unittest.main()
