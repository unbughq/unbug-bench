"""Offline setup regressions. Docker is never invoked by these tests."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str((_BENCH_ROOT / "bin")))
import bench
import factory_pool


class SetupTests(unittest.TestCase):
    def test_import_creates_results_before_lock_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bin').mkdir()
            for name in ('bench.py', 'bench_judging.py'):
                (root / 'bin' / name).write_bytes(Path(bench.__file__).with_name(name).read_bytes())
            (root / 'factory').mkdir()
            (root / 'factory/case_permissions.py').write_bytes(
                (_BENCH_ROOT / 'factory/case_permissions.py').read_bytes())
            subprocess.run([sys.executable, '-c',
                "import bench; (bench.RESULTS / '.bench.lock').open('w').close()"],
                cwd=root / 'bin', env={**os.environ, 'UNBUG_FACTORY_SLOT': '0'},
                check=True, capture_output=True, text=True)
            self.assertTrue((root / 'results/.bench.lock').is_file())

    def test_seed_failure_captures_output_and_removes_stale_container(self):
        calls = []
        def run(args, **kwargs):
            calls.append((args, kwargs))
            if args[-3:] == ['npm', 'run', 'seed']:
                return subprocess.CompletedProcess(args, 1, 'seed stdout cause', 'duplicate key seed stderr')
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch.object(bench.subprocess, 'run', run), patch.object(bench, 'FACTORY_SLOT', 1):
            with self.assertRaisesRegex(RuntimeError, 'seed stdout cause.*', msg='seed stderr must survive') as error:
                bench.setup()
        self.assertIn('duplicate key seed stderr', str(error.exception))
        commands = [c for c, _ in calls]
        seed = next(i for i, c in enumerate(commands) if c[-3:] == ['npm', 'run', 'seed'])
        self.assertIn(['docker', 'rm', '-f', 'unbug-factory-1-seed'], commands[:seed])
        self.assertIn(['docker', 'rm', '-f', 'unbug-factory-1-seed'], commands[seed + 1:])
        self.assertTrue(all(k.get('stdout') == subprocess.PIPE and k.get('stderr') == subprocess.PIPE
                            for c, k in calls if c[-3:] == ['npm', 'run', 'seed']))

    def test_slot_preparation_drops_partial_volume_and_invalidates_partial_ids(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            ids = Path(tmp) / 'seed-ids.json'; ids.write_text('{}')
            def setup():
                self.assertFalse(ids.exists())
                events.append('setup')
                ids.write_text('partial')
                raise RuntimeError('synthetic seed failed')
            with patch.multiple(bench, FACTORY_SLOT=1, IDS=ids, RESULTS=Path(tmp)), \
                 patch.object(bench, 'stop_inventory_services', lambda: events.append('inventory')), \
                 patch.object(bench, 'dc', lambda *a: events.append(a)), patch.object(bench, 'setup', setup):
                with self.assertRaisesRegex(RuntimeError, 'synthetic seed failed'):
                    bench.prepare_factory_slot()
            self.assertFalse(ids.exists(), 'failed setup must not leave a ready marker')
            self.assertLess(events.index(('down', '-v', '--remove-orphans')), events.index('setup'))
            self.assertEqual(events[-1], ('stop',))

    def test_pool_prepares_missing_slot_before_any_trials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'results').mkdir()
            events = []
            def run(args, **kwargs):
                if args[1:3] == ['-c', 'import bench; bench.prepare_factory_slot()']:
                    events.append('prepare')
                else:
                    self.assertIn('prepare', events, 'parallel trials started before preparation')
                    job = json.loads(Path(args[2]).read_text())
                    Path(args[3]).write_text(json.dumps([{'run': n} for n in job['numbers']]))
                    events.append('trial')
                return subprocess.CompletedProcess(args, 0, '', '')
            with patch.multiple(bench, ROOT=root, RESULTS=root / 'results'), \
                 patch.object(bench, 'dc', lambda *a: events.append(a)), \
                 patch.object(bench, 'stop_inventory_services', lambda: events.append('inventory')), \
                 patch.object(factory_pool.subprocess, 'run', run):
                result = factory_pool.run_records(root, [1, 2], {}, [], 2)
            self.assertEqual(set(result), {1, 2})
            self.assertLess(events.index(('stop', *bench.APP_SERVICES)), events.index('prepare'))
            self.assertEqual(events.count('prepare'), 1)

    def test_preparation_error_reaches_parent_with_command_output(self):
        with patch.object(factory_pool.subprocess, 'run', return_value=
                subprocess.CompletedProcess([], 1, 'setup stdout', 'seed stderr')):
            with self.assertRaisesRegex(RuntimeError, 'setup stdout') as error:
                factory_pool.prepare_slot(1)
        self.assertIn('seed stderr', str(error.exception))


    def test_readiness_requires_completed_setup_and_matching_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); directory = root / 'factory-slots/1'; directory.mkdir(parents=True)
            ids = directory / 'seed-ids.json'; ids.write_text('{}')
            self.assertFalse(bench.factory_slot_ready(root, 1), 'partial seed IDs are not readiness')
            with patch.multiple(bench, RESULTS=directory, IDS=ids, FACTORY_SLOT=1), \
                 patch.object(bench, 'stop_inventory_services'), patch.object(bench, 'dc'), \
                 patch.object(bench, 'setup', side_effect=lambda: ids.write_text('{}')):
                bench.prepare_factory_slot()
            self.assertTrue(bench.factory_slot_ready(root, 1))
            ids.write_text('{"changed": true}')
            self.assertFalse(bench.factory_slot_ready(root, 1))
            ids.unlink()
            self.assertFalse(bench.factory_slot_ready(root, 1))

    def test_cleanup_failure_cannot_publish_prepared_shop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); directory = root / 'factory-slots/1'; directory.mkdir(parents=True)
            ids = directory / 'seed-ids.json'
            def dc(*args):
                if args == ('stop',): raise RuntimeError('park failed')
            with patch.multiple(bench, RESULTS=directory, IDS=ids, FACTORY_SLOT=1), \
                 patch.object(bench, 'stop_inventory_services'), patch.object(bench, 'dc', dc), \
                 patch.object(bench, 'setup', side_effect=lambda: ids.write_text('{}')):
                with self.assertRaisesRegex(RuntimeError, 'park failed'): bench.prepare_factory_slot()
            self.assertFalse(ids.exists())
            self.assertFalse(bench.factory_slot_ready(root, 1))

    def test_fresh_factory_preparation_owns_retire_main_park_extra_order(self):
        calls = []
        def execute(args, **kwargs):
            calls.append((args[-1], kwargs.get('env', {}).get('UNBUG_FACTORY_SLOT')))
            return 0
        with patch.object(bench, 'FACTORY_SLOT', 0):
            self.assertTrue(factory_pool.prepare(2, previous_slots=3, fresh=True, execute=execute))
        self.assertEqual(calls, [
            ('import bench; bench.retire_factory_slot()', '2'),
            ('import bench; bench.prepare_factory_main()', None),
            ("import bench; bench.stop_inventory_services(); bench.dc('stop', *bench.APP_SERVICES)", None),
            ('import bench; bench.prepare_factory_slot()', '1')])

    def test_failed_main_preparation_does_not_start_extra_shops(self):
        calls = []
        def execute(args, **kwargs):
            calls.append(args[-1]); return 1
        with patch.object(bench, 'FACTORY_SLOT', 0):
            self.assertFalse(factory_pool.prepare(2, fresh=True, execute=execute))
        self.assertEqual(calls, ['import bench; bench.prepare_factory_main()'])

    def test_existing_ready_pool_does_not_reset_main_or_extra_shops(self):
        with patch.object(bench, 'FACTORY_SLOT', 0), \
             patch.object(bench, 'factory_slot_ready', return_value=True), \
             patch.object(factory_pool.subprocess, 'run') as command, \
             patch.object(bench, 'dc') as dc:
            self.assertTrue(factory_pool.prepare(2))
        command.assert_not_called(); dc.assert_not_called()

    def test_extra_slot_cannot_prepare_a_pool_or_retire_main(self):
        with patch.object(bench, 'FACTORY_SLOT', 1):
            with self.assertRaises(ValueError): factory_pool.prepare(2)
        with patch.object(bench, 'FACTORY_SLOT', 0):
            with self.assertRaises(ValueError): bench.retire_factory_slot()


    def lock_probe(self, root):
        """A distinct process must observe flock, not a mocked locking call."""
        program = ("import fcntl,pathlib,sys; "
                   "lock=(pathlib.Path(sys.argv[1])/'.bench.lock').open('w'); "
                   "fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)")
        return subprocess.run([sys.executable, '-c', program, str(root)], capture_output=True).returncode

    def test_fresh_preparation_holds_root_lock_across_every_phase_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phases = []
            def execute(args, **kwargs):
                phases.append(args[-1])
                self.assertNotEqual(self.lock_probe(root), 0, 'another checkpoint acquired the live preparation lock')
                return 0
            with patch.multiple(bench, RESULTS=root, FACTORY_SLOT=0):
                self.assertTrue(factory_pool.prepare(2, previous_slots=3, fresh=True, execute=execute))
            self.assertEqual(len(phases), 4, 'retirement, main setup, parking, extra setup must be covered')
            self.assertEqual(self.lock_probe(root), 0)

    def test_fresh_preparation_cannot_retire_while_checkpoint_owns_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (root / '.bench.lock').open('w') as checkpoint_lock:
                fcntl.flock(checkpoint_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.multiple(bench, RESULTS=root, FACTORY_SLOT=0), \
                     patch.object(factory_pool.subprocess, 'run') as command:
                    with self.assertRaises(BlockingIOError):
                        factory_pool.prepare(2, previous_slots=3, fresh=True)
                command.assert_not_called()

    def test_fresh_preparation_failures_release_root_lock(self):
        for failure in ('main-status', 'extra-exception'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                def execute(args, **kwargs):
                    self.assertNotEqual(self.lock_probe(root), 0)
                    if 'prepare_factory_main' in args[-1] and failure == 'main-status': return 1
                    if 'prepare_factory_slot' in args[-1]: raise RuntimeError('extra failed')
                    return 0
                with patch.multiple(bench, RESULTS=root, FACTORY_SLOT=0):
                    if failure == 'main-status':
                        self.assertFalse(factory_pool.prepare(2, fresh=True, execute=execute))
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'extra failed'):
                            factory_pool.prepare(2, fresh=True, execute=execute)
                self.assertEqual(self.lock_probe(root), 0)

    def test_pool_inside_checkpoint_does_not_reacquire_parent_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (root / '.bench.lock').open('w') as checkpoint_lock:
                fcntl.flock(checkpoint_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.multiple(bench, RESULTS=root, FACTORY_SLOT=0), \
                     patch.object(bench, 'factory_slot_ready', return_value=True):
                    self.assertTrue(factory_pool.prepare(2))
                self.assertNotEqual(self.lock_probe(root), 0)


if __name__ == '__main__': unittest.main()
