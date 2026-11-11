"""Synthetic fixture: a crashed bench Postgres is restarted once at reset, else the case stops as infra.
Only hard evidence (pg_isready, container state) counts; a guard's own SQL failure never does."""
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
import factory_pool

CRASH = RuntimeError('Command failed: psql\nFATAL:  the database system is in recovery mode')
# What a guard can print on its own: pg_terminate_backend(pg_backend_pid()) or RAISE with crash wording.
GUARD_KILL = RuntimeError('Command failed: psql\nFATAL:  terminating connection due to administrator command\n'
                          'ERROR:  terminating connection because of crash of another server process')
OOM = '[812.5] Memory cgroup out of memory: Killed process 4242 (postgres) total-vm:900000kB'


class Stack:
    """Fake Docker/Postgres. `crashes` DROP DATABASE attempts really crash it (down, OOM-killed)
    until a restart; `guard` makes the guard's db.sql fail, crashing Postgres too when 'crash'."""
    def __init__(self, crashes=0, ready=True, baseline=None, guard=None):
        self.crashes, self.ready, self.guard, self.down, self.events = crashes, ready, guard, False, []
        self.baseline = bench.EXPECTED_BASELINE if baseline is None else baseline

    def dc(self, *args, **kwargs):
        self.events.append(args)
        if args == ('restart', 'postgres'):
            self.down = False
        if args[:3] == ('exec', '-T', 'postgres') and 'pg_isready' in args and (self.down or not self.ready):
            raise RuntimeError('Command failed: pg_isready')
        return 'container-id' if args[0] == 'ps' else ''

    def sql(self, query, user='medusa', **kwargs):
        if self.down:
            raise CRASH
        if 'DROP DATABASE IF EXISTS medusa' in query and self.crashes:
            self.crashes -= 1
            self.down = True
            raise CRASH
        if user == 'bench_guard' and self.guard:
            self.events.append(('guard_failed',))
            self.down = self.guard == 'crash'
            raise GUARD_KILL
        return '1'

    def command(self, args, **kwargs):
        if args[:2] == ['docker', 'inspect']:
            return json.dumps({'Status': 'running', 'ExitCode': 0, 'OOMKilled': self.down, 'Restarting': False})
        return '{}'  # traffic

    def patches(self, root):
        dmesg = subprocess.CompletedProcess(['dmesg'], 0, stdout='boot\n' + OOM + '\n', stderr='')
        return [mock.patch.object(bench, 'RESULTS', root), mock.patch.object(bench, 'resolve_guard', return_value=root),
                mock.patch.object(bench, 'stop_inventory_services'), mock.patch.object(bench, 'inventory_services', return_value=[]),
                mock.patch.object(bench, 'dc', side_effect=self.dc), mock.patch.object(bench, 'sql', side_effect=self.sql),
                mock.patch.object(bench, 'command', side_effect=self.command),
                mock.patch.object(bench.subprocess, 'run', return_value=dmesg),
                mock.patch.object(bench, 'checker', side_effect=lambda *a: self.baseline),
                mock.patch.object(bench, 'start_app'), mock.patch.object(bench, 'start_inventory_services', return_value={}),
                mock.patch.object(bench.time, 'sleep')]


def run(stack, root, body):
    with contextlib.ExitStack() as patches:
        for patch in stack.patches(root): patches.enter_context(patch)
        return body()


def run_case(stack, root, runs, db_sql=None):
    guard = root / 'guard'; guard.mkdir()
    if db_sql: (guard / 'db.sql').write_text(db_sql)
    def body():
        with mock.patch.multiple(bench, ROOT=root), mock.patch.object(bench, 'prepare_app_guard'), \
             mock.patch.object(bench, 'bench_fingerprint', return_value={}), \
             mock.patch.object(bench, 'resolve_guard', return_value=guard), \
             contextlib.redirect_stdout(None):
            return bench.run_case(guard, runs, label='case')
    return run(stack, root, body)


def records(root):
    return [json.loads(r.read_text()) for r in sorted(root.glob('runs/*-case/0*.json'))]


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
            self.assertIs(evidence['pg_isready'], False)
            self.assertIs(evidence['OOMKilled'], True)
            self.assertEqual(evidence['dmesg_oom'], OOM)

    def test_crash_wording_with_healthy_postgres_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack = Stack()
            with mock.patch.object(stack, 'sql', side_effect=CRASH):  # text alone is not evidence
                with self.assertRaisesRegex(RuntimeError, 'recovery mode') as caught:
                    run(stack, pathlib.Path(tmp), lambda: bench.reset(app_prepared=True))
            self.assertNotIsInstance(caught.exception, bench.PostgresUnrecoverable)
            self.assertNotIn(('restart', 'postgres'), stack.events)

    def test_unrelated_reset_error_with_healthy_postgres_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack = Stack(baseline={'valid': False})
            with self.assertRaisesRegex(RuntimeError, 'Unexpected reset baseline') as caught:
                run(stack, pathlib.Path(tmp), lambda: bench.reset(app_prepared=True))
            self.assertNotIsInstance(caught.exception, bench.PostgresUnrecoverable)
            self.assertNotIn(('restart', 'postgres'), stack.events)

    def test_guard_killing_its_own_backend_is_an_ordinary_trial_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            stack = Stack(guard='kill')
            summary = run_case(stack, root, 3, 'SELECT pg_terminate_backend(pg_backend_pid());')
            self.assertNotIn(('restart', 'postgres'), stack.events)
            self.assertEqual(stack.events.count(('guard_failed',)), 3)  # once per trial, no retry
            self.assertEqual((summary['runs'], summary['invalid']), (3, 3))
            for record in records(root):
                error = next(e for e in record['errors'] if e['stage'] == 'reset')
                self.assertIn('administrator command', error['message'])
                self.assertNotIn('postgres_unrecoverable', error)
                self.assertNotIn('postgres_restart', record)

    def test_guard_that_really_crashes_postgres_stays_a_guard_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            stack = Stack(guard='crash')
            summary = run_case(stack, root, 3, 'SELECT crash();')
            # Never retried inside a trial; the next trial heals the stack before its guard runs.
            self.assertEqual(stack.events.count(('guard_failed',)), 3)
            self.assertEqual(stack.events.count(('restart', 'postgres')), 2)
            self.assertEqual((summary['runs'], summary['invalid']), (3, 3))
            rows = records(root)
            self.assertTrue(all('postgres_unrecoverable' not in e for r in rows for e in r['errors']))
            self.assertEqual(['postgres_restart' in r for r in rows], [False, True, True])

    def test_recovered_trial_runs_traffic_and_keeps_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            stack = Stack(crashes=1)
            summary = run_case(stack, root, 2)
            self.assertEqual((summary['runs'], summary['errors']), (2, 0))
            self.assertEqual(stack.events.count(('restart', 'postgres')), 1)
            first, second = records(root)
            self.assertEqual(first['errors'], []); self.assertIsNotNone(first['traffic'])
            self.assertIs(first['postgres_restart']['OOMKilled'], True)
            self.assertNotIn('postgres_restart', second)

    def test_unrecoverable_postgres_stops_case_with_one_infra_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            stack = Stack(crashes=99)
            with self.assertRaises(bench.PostgresUnrecoverable) as caught:
                run_case(stack, root, 3)
            self.assertIn('run 1', str(caught.exception))
            self.assertIs(caught.exception.evidence['OOMKilled'], True)
            self.assertEqual(stack.events.count(('restart', 'postgres')), 1)  # one restart, no cascade
            rows = records(root)
            self.assertEqual([r['run'] for r in rows], [1])  # runs 2 and 3 never started
            self.assertFalse(rows[0]['checker']['valid']); self.assertIsNone(rows[0]['traffic'])
            reset_error = next(e for e in rows[0]['errors'] if e['stage'] == 'reset')
            self.assertIn('second_error', reset_error['postgres_unrecoverable'])
            self.assertIs(reset_error['postgres_unrecoverable']['after_restart']['pg_isready'], False)
            self.assertEqual(reset_error['postgres_unrecoverable']['dmesg_oom'], OOM)

    def test_postgres_never_ready_after_restart_is_unrecoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            stack = Stack(crashes=1, ready=False)
            clock = iter(range(0, 10_000, 30))
            with mock.patch.object(bench.time, 'monotonic', lambda: next(clock)):
                with self.assertRaisesRegex(bench.PostgresUnrecoverable, 'not ready'):
                    run(stack, pathlib.Path(tmp), lambda: bench.reset(app_prepared=True))


class ParallelPoolTests(unittest.TestCase):
    """Each pool slot has its own Compose stack. The slot whose Postgres is unrecoverable stops at
    that trial inside its own serial run_case (its child exits non-zero); healthy slots finish their
    chunk on their own stacks, then the pool raises one infra error and returns no records."""
    def test_one_unrecoverable_slot_fails_the_pool_without_records(self):
        slots = []
        def child(args, *, env, check=False, **kwargs):
            slot = int(env['UNBUG_FACTORY_SLOT']); slots.append(slot)
            job = json.loads(pathlib.Path(args[2]).read_text())
            if slot == 0:
                raise subprocess.CalledProcessError(1, args, stderr='PostgresUnrecoverable: run 3')
            pathlib.Path(args[3]).write_text(json.dumps([{'run': n} for n in job['numbers']]))
            return subprocess.CompletedProcess(args, 0)
        with mock.patch.object(factory_pool, 'prepare'), mock.patch.object(factory_pool.subprocess, 'run', child):
            with self.assertRaises(subprocess.CalledProcessError):
                factory_pool.run_records(pathlib.Path('/guard'), [1, 2, 3, 4], {}, [], 2)
        self.assertEqual(sorted(slots), [0, 1])


if __name__ == '__main__':
    unittest.main()
