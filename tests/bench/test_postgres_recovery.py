"""Synthetic fixture: a crashed bench Postgres is restarted once at reset, else the case stops as infra."""
import contextlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

BIN = pathlib.Path(__file__).resolve().parents[2] / 'bin'
sys.path.insert(0, str(BIN))
SPEC = importlib.util.spec_from_file_location('bench_postgres_recovery_test', BIN / 'bench.py')
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)

CRASH = RuntimeError('Command failed: psql\nFATAL:  the database system is in recovery mode')
STATE = {'Status': 'running', 'ExitCode': 0, 'OOMKilled': True, 'Restarting': False}
OOM = '[812.5] Memory cgroup out of memory: Killed process 4242 (postgres) total-vm:900000kB'


class Stack:
    """Fake Docker/Postgres: `crashes` DROP DATABASE attempts fail with recovery mode."""
    def __init__(self, crashes, ready=True, baseline=None):
        self.crashes, self.ready, self.events = crashes, ready, []
        self.baseline = bench.EXPECTED_BASELINE if baseline is None else baseline

    def dc(self, *args, **kwargs):
        self.events.append(args)
        if args[:3] == ('exec', '-T', 'postgres') and 'pg_isready' in args and not self.ready:
            raise RuntimeError('Command failed: pg_isready')
        return 'container-id' if args[0] == 'ps' else ''

    def sql(self, query, **kwargs):
        if 'DROP DATABASE IF EXISTS medusa' in query and self.crashes:
            self.crashes -= 1
            raise CRASH
        return '1'

    def patches(self, root):
        dmesg = subprocess.CompletedProcess(['dmesg'], 0, stdout='boot\n' + OOM + '\n', stderr='')
        return [mock.patch.object(bench, 'RESULTS', root), mock.patch.object(bench, 'resolve_guard', return_value=root),
                mock.patch.object(bench, 'stop_inventory_services'), mock.patch.object(bench, 'inventory_services', return_value=[]),
                mock.patch.object(bench, 'dc', side_effect=self.dc), mock.patch.object(bench, 'sql', side_effect=self.sql),
                mock.patch.object(bench, 'command', return_value=json.dumps(STATE)),
                mock.patch.object(bench.subprocess, 'run', return_value=dmesg),
                mock.patch.object(bench, 'checker', return_value=self.baseline),
                mock.patch.object(bench, 'start_app'), mock.patch.object(bench, 'start_inventory_services', return_value={}),
                mock.patch.object(bench.time, 'sleep')]


def run(stack, root, body):
    with contextlib.ExitStack() as patches:
        for patch in stack.patches(root): patches.enter_context(patch)
        return body()


class PostgresRecoveryTests(unittest.TestCase):
    def test_recovery_mode_restarts_postgres_and_reset_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack, progress = Stack(crashes=1), {}
            out = run(stack, pathlib.Path(tmp), lambda: bench.reset(app_prepared=True, progress=progress))
            self.assertEqual(out['checker'], bench.EXPECTED_BASELINE)
            self.assertEqual(stack.events.count(('restart', 'postgres')), 1)
            self.assertTrue(progress['fresh_database'])
            evidence = progress['postgres_restart']
            self.assertIn('recovery mode', evidence['first_error'])
            self.assertIs(evidence['OOMKilled'], True)
            self.assertEqual(evidence['dmesg_oom'], OOM)

    def test_unrelated_reset_error_with_healthy_postgres_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack = Stack(crashes=0, baseline={'valid': False})
            with self.assertRaisesRegex(RuntimeError, 'Unexpected reset baseline') as caught:
                run(stack, pathlib.Path(tmp), lambda: bench.reset(app_prepared=True))
            self.assertNotIsInstance(caught.exception, bench.PostgresUnrecoverable)
            self.assertNotIn(('restart', 'postgres'), stack.events)

    def test_unrecoverable_postgres_stops_case_with_one_infra_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            guard = root / 'guard'; guard.mkdir()
            stack = Stack(crashes=99)
            def body():
                with mock.patch.multiple(bench, ROOT=root), mock.patch.object(bench, 'prepare_app_guard'), \
                     mock.patch.object(bench, 'bench_fingerprint', return_value={}), \
                     mock.patch.object(bench, 'resolve_guard', return_value=guard):
                    bench.run_case(guard, 3, label='case')
            with self.assertRaises(bench.PostgresUnrecoverable) as caught:
                run(stack, root, body)
            self.assertIn('run 1', str(caught.exception))
            self.assertIs(caught.exception.evidence['OOMKilled'], True)
            self.assertEqual(stack.events.count(('restart', 'postgres')), 1)  # one restart, no cascade
            records = sorted(root.glob('runs/*-case/*.json'))
            self.assertEqual([r.name for r in records], ['01.json'])  # runs 2 and 3 never started
            record = json.loads(records[0].read_text())
            self.assertFalse(record['checker']['valid']); self.assertIsNone(record['traffic'])
            reset_error = next(e for e in record['errors'] if e['stage'] == 'reset')
            self.assertIn('second_error', reset_error['postgres_unrecoverable'])
            self.assertEqual(reset_error['postgres_unrecoverable']['dmesg_oom'], OOM)

    def test_recovered_trial_runs_traffic_and_keeps_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            guard = root / 'guard'; guard.mkdir()
            stack = Stack(crashes=1)
            def body():
                with mock.patch.multiple(bench, ROOT=root), mock.patch.object(bench, 'prepare_app_guard'), \
                     mock.patch.object(bench, 'bench_fingerprint', return_value={}), \
                     mock.patch.object(bench, 'resolve_guard', return_value=guard):
                    return bench.run_case(guard, 2, label='case')
            summary = run(stack, root, body)
            self.assertEqual((summary['runs'], summary['errors']), (2, 0))
            self.assertEqual(stack.events.count(('restart', 'postgres')), 1)
            first, second = (json.loads(r.read_text()) for r in sorted(root.glob('runs/*-case/0*.json')))
            self.assertEqual(first['errors'], []); self.assertIsNotNone(first['traffic'])
            self.assertIs(first['postgres_restart']['OOMKilled'], True)
            self.assertNotIn('postgres_restart', second)

    def test_postgres_never_ready_after_restart_is_unrecoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack = Stack(crashes=1, ready=False)
            clock = iter(range(0, 10_000, 30))
            with mock.patch.object(bench.time, 'monotonic', lambda: next(clock)):
                with self.assertRaisesRegex(bench.PostgresUnrecoverable, 'not ready'):
                    run(stack, pathlib.Path(tmp), lambda: bench.reset(app_prepared=True))


if __name__ == '__main__':
    unittest.main()
