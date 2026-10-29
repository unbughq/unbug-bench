"""Real launch envelopes, with local crash/hang injection; no cloud or decryption."""
import argparse
import asyncio
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
os.environ['BENCH'] = str(ROOT)
import processes
import run
import exam_responder
from gate_pipeline import GatePipeline

FIXTURES = Path(__file__).with_name('fixtures') / 'isolation-timeouts'
LOAD = lambda name: json.loads((FIXTURES / name).read_text())
LAUNCH = LOAD('launch.json')['argv']
CREATED = LOAD('created.json')


def option(name):
    return LAUNCH[LAUNCH.index(name) + 1]


def worker_args():
    argv = LAUNCH[1:]
    result = []
    i = 0
    while i < len(argv):
        if argv[i] == '--restore':
            result.extend(['--resume', argv[i+1], '--resume-bench-sha', LOAD('launch.json')['bench_sha']])
            i += 2
        elif argv[i] in ('--qualified-release', '--ttl-hours', '--max-spend'):
            i += 2
        else:
            result.append(argv[i]); i += 1
    return result


def strategy_module():
    loader = importlib.machinery.SourceFileLoader('isolation_strategy', str(ROOT / 'bin/strategy'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    return module


class ProcessesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.c = types.SimpleNamespace(work=self.home, args=run.argument_parser().parse_args(worker_args()))
        self.c.args.bench_workers = 1  # reproduce the formerly unsafe serial path
        (self.home / 'logs').mkdir()
        self.heartbeat = self.home / (CREATED['id'] + '.heartbeat')
        child = ("import pathlib,time,signal; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                 f"p=pathlib.Path({str(self.heartbeat)!r})\n"
                 "while True:\n p.write_text(str(time.monotonic_ns())); time.sleep(.02)")
        self.command = [sys.executable, '-c',
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True); time.sleep(60)"]

    def stopped(self):
        self.assertTrue(self.heartbeat.exists(), 'fault-injected real lifecycle command never started')
        before = self.heartbeat.read_text(); time.sleep(.15)
        self.assertEqual(self.heartbeat.read_text(), before, 'descendant survived owner cleanup')

    def test_real_launch_envelope_serial_sh_timeout_kills_nested_session(self):
        self.assertEqual(CREATED['ttlSeconds'], LOAD('monitor.json')['ttl_seconds'])
        with self.assertRaises(subprocess.TimeoutExpired):
            run.sh(self.c, self.command, timeout=.6, capture=True)
        self.stopped()

    def test_role_cancel_and_pause_kill_before_seal(self):
        for pause in (False, True):
            self.c.role_cancel = threading.Event()
            old = signal.signal(signal.SIGTERM, run.pause_on_term) if pause else None
            timer = threading.Timer(.6, lambda: os.kill(os.getpid(), signal.SIGTERM)
                                    if pause else self.c.role_cancel.set())
            timer.start()
            try:
                with patch.object(run, 'SEALED', self.home / 'sealed'):
                    with self.assertRaises(run.PauseRequested if pause else run.BudgetError):
                        run.sh(self.c, self.command, timeout=5, capture=True)
            finally:
                timer.cancel()
                if old is not None: signal.signal(signal.SIGTERM, old)
            self.stopped()

    def test_async_strategy_real_exec_cancellation_kills_shell_descendant(self):
        strategy = strategy_module()
        task = self.home / 'harbor' / option('--restore') / 'steps/quiet'
        task.mkdir(parents=True)
        (task.parent.parent / 'task.toml').touch()
        (task / 'window.json').write_text('{"duration_sec":1}')
        async def window(environment, spec):
            pending = asyncio.create_task(environment.exec(shlex.join(self.command), timeout_sec=10))
            await asyncio.sleep(.6)
            pending.cancel()
            await pending
        bench = types.SimpleNamespace(reset=lambda *a, **k: None, RESULTS=self.home)
        with patch.dict(sys.modules, {'bench': bench, 'silent_window': types.SimpleNamespace(run_window=window)}):
            with self.assertRaises(asyncio.CancelledError):
                strategy.silent_checkpoint(self.home, {'name': 'quiet'}, [], self.home, {}, False)
        self.stopped()

    def test_successful_foreground_shell_cleans_its_background_group(self):
        child = "import pathlib,time; p=pathlib.Path(" + repr(str(self.heartbeat)) + ")\nwhile True:\n p.write_text(str(time.monotonic_ns())); time.sleep(.02)"
        parent = ("import subprocess,sys,pathlib,time; subprocess.Popen([sys.executable,'-c'," + repr(child)
                  + "],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                  + "p=pathlib.Path(" + repr(str(self.heartbeat)) + ")\nwhile not p.exists(): time.sleep(.01)")
        self.assertEqual(run.sh(self.c, [sys.executable, '-c', parent], timeout=5), 0)
        self.stopped()

    def test_context_deadline_is_nested_and_finalization_independent(self):
        with processes.deadline(.15):
            with self.assertRaises(subprocess.TimeoutExpired):
                with processes.deadline(5):
                    processes.run([sys.executable, '-c', 'import time; time.sleep(2)'])
            with processes.deadline(1, independent=True):
                self.assertEqual(processes.run([sys.executable, '-c', 'pass']).returncode, 0)

    def test_shared_diagnostic_owner_survives_its_child_timeout(self):
        code = """import os,sys,subprocess
sys.path.insert(0,sys.argv[1]); import processes
os.environ['UNBUG_DIAGNOSTIC_PROCESS_GROUP']='1'
try: processes.run([sys.executable,'-c','import time; time.sleep(60)'],timeout=.2)
except subprocess.TimeoutExpired: print('owner survived')
"""
        result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'bin')], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'owner survived')

    def test_gate_deadline_is_operational_and_does_not_send_writer_feedback(self):
        c = types.SimpleNamespace(args=run.argument_parser().parse_args(worker_args()),
                                  work=self.home, card=LOAD('scorecard.json'), audit_gates=['G13'])
        c.args.agent_timeout = .1  # fault injection inside the real saved launch envelope
        c.card['gates'] = {}
        c.case_id = LOAD('scorecard.json')['case']
        pipeline = run._gate_pipeline()
        def hang(ctx, gate):
            processes.run([sys.executable, '-c', 'import time; time.sleep(60)'])
        pipeline.evaluate = hang
        pipeline.budget_boundary = lambda c: None
        pipeline.after_gate = lambda *a: None
        pipeline.publish = lambda *a: None
        pipeline.run(c)
        self.assertTrue(c.stopped)
        self.assertEqual(c.card['terminal_stop'], 'runner_error:TimeoutExpired')
        self.assertEqual(c.card['failed_detail'], {'error': 'TimeoutExpired'})


class SupervisorTests(unittest.TestCase):
    def invoke(self, code, *, prior_work=False, seconds=8):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        if prior_work:
            (self.home / 'work' / option('--restore')).mkdir(parents=True)
        command = [sys.executable, str(ROOT / 'factory/runner_supervisor.py'), '--', sys.executable, '-c', code,
                   *worker_args()]  # real saved worker arguments; injected interpreter ignores them
        return subprocess.run(command, env={**os.environ, 'HOME': str(self.home),
            'FACTORY_RUNNER_SECONDS': str(seconds)}, capture_output=True, text=True, timeout=12)

    def test_startup_retry_then_ready_uses_safe_receipt(self):
        result = self.invoke("""import os,pathlib,sys
p=pathlib.Path.home()/'attempts'; n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n))
if n==1:
 print('synthetic private diagnostic',file=sys.stderr); sys.exit(1)
pathlib.Path(os.environ['FACTORY_RUNNER_READY']).touch()
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.home / 'sealed/runner-status.json').read_text())
        self.assertEqual((data['attempt'], data['reason'], data['exit_status']), (2, 'finished', 0))
        self.assertNotIn('synthetic private diagnostic', result.stderr)
        self.assertEqual(set(data), {'schema','attempt','phase','reason','exit_status','observed_at'})

    def test_deadline_pauses_and_allows_a_bounded_seal_before_kill(self):
        result = self.invoke("""import os,pathlib,signal,time
def pause(sig,frame):
 pathlib.Path.home().joinpath('paused').touch(); time.sleep(.1); raise SystemExit(0)
signal.signal(signal.SIGTERM,pause)
pathlib.Path(os.environ['FACTORY_RUNNER_READY']).touch()
time.sleep(60)
""", seconds=.4)
        self.assertEqual(result.returncode, 124)
        self.assertTrue((self.home / 'paused').exists())
        data = json.loads((self.home / 'sealed/runner-status.json').read_text())
        self.assertEqual((data['reason'], data['exit_status']), ('timeout', 0))

    def test_restored_work_and_usage_error_never_retry(self):
        for prior_work, code in ((True, 1), (False, 2)):
            result = self.invoke(f'raise SystemExit({code})', prior_work=prior_work)
            data = json.loads((self.home / 'sealed/runner-status.json').read_text())
            self.assertEqual(data['attempt'], 1)
            self.assertEqual(data['reason'], 'startup_failed')
            self.assertFalse((self.home / 'sealed/DONE').exists())


class BoatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.cli = self.home / 'boat'
        self.cli.write_text("""#!/usr/bin/env python3
import json,os,sys,pathlib
assert os.environ['BOAT_NO_UPDATE']=='1'
if sys.argv[1:]==['--version']: print(os.environ['TEST_VERSION'])
elif sys.argv[1:]==['billing','--json']: print(pathlib.Path(os.environ['TEST_BILLING']).read_text())
elif sys.argv[1:] in (['list','--json'], ['list','--all','--json']): print(pathlib.Path(os.environ['TEST_LIST']).read_text())
else: raise SystemExit(9)
""")
        self.cli.chmod(0o755)
        self.env = {**os.environ, 'BOAT_CMD': str(self.cli), 'BOAT_NO_UPDATE': '0',
            'TEST_VERSION': LOAD('boat-version.json')['version'],
            'TEST_BILLING': str(FIXTURES / 'billing.json'), 'TEST_LIST': str(FIXTURES / 'list.json'),
            'UNBUG_CONTROL_HOME': str(self.home / 'control')}

    def test_pinned_control_cmd_and_saved_json_shapes(self):
        for command in ('billing', 'list'):
            result = subprocess.run([str(ROOT / 'bin/boat-call'), command, '--json'],
                env=self.env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), LOAD(command + '.json'))
        bad = subprocess.run([str(ROOT / 'bin/boat-call'), 'list', '--json'],
            env={**self.env, 'TEST_VERSION': 'boat wrong'}, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(bad.returncode, 0)
        self.assertEqual(bad.stdout, '')

    def test_unknown_creation_stays_pending_and_does_not_finish_reservation(self):
        state = self.home / 'launch'; state.mkdir()
        (state / 'ids').touch()
        spend = self.home / 'spend.json'
        spend.write_text(json.dumps({'provider':'boat', 'balance_before_usd':10}))
        lost = self.home / 'lost-response'
        lost.write_text('#!/bin/sh\nexit 124\n'); lost.chmod(0o755)
        script = r"""root=$1; state=$2; spend_file=$3; serial=0; bundle=''; label=factory
ttl_seconds=$4; purpose=case; margin=1800
. "$root/bin/boat-launch-guards.sh"
guard_new
guard_exit 1
"""
        result = subprocess.run(['sh', '-c', script, 'sh', str(ROOT), str(state), str(spend),
            str(CREATED['ttlSeconds'])], env={**self.env, 'BOAT_CMD':str(lost),
            'UNBUG_LAUNCH_STATE':str(state)}, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((state / 'new.1.pending').exists())
        self.assertFalse((state / 'complete').exists())
        self.assertNotIn('finished_at', json.loads(spend.read_text()))
        self.assertIn('pending reconciliation', result.stderr)

    def test_concurrent_admission_reserves_whole_envelope_and_finish_observes_account(self):
        balance = float(LOAD('billing.json')['limits']['creditBalanceSeconds']) / 100000
        # Two individual jobs fit; their aggregate must be refused under one lock.
        hours = max(1, balance * .75 / .036)
        jobs = []
        for i in (1, 2):
            record = self.home / f'spend-{i}.json'
            jobs.append((record, subprocess.Popen([str(ROOT / 'bin/boat-spend'), '--check', '1', str(hours),
                str(balance * 2), str(record)], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)))
        for _, process in jobs: process.communicate(timeout=8)
        self.assertEqual(sorted(p.returncode for _, p in jobs), [0, 1])
        record = next(path for path, p in jobs if p.returncode == 0)
        ledger_path = self.home / 'control/boat-reservations.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['reservations'][str(record.resolve())]['expires_at'] = time.time() - 1
        ledger_path.write_text(json.dumps(ledger))  # fault injection: abandoned controller
        refused = next(path for path,p in jobs if p.returncode != 0)
        retry = subprocess.run([str(ROOT / 'bin/boat-spend'), '--check', '1', str(hours),
            str(balance * 2), str(refused)], env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(json.loads(ledger_path.read_text())['reservations'][str(record.resolve())]['status'],
                         'reconciled_expired')
        ids = self.home / 'ids'; ids.write_text(CREATED['id'] + '\n')
        result = subprocess.run([str(ROOT / 'bin/boat-spend'), '--finish', str(record), '0', str(ids)],
            env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(record.read_text())
        self.assertIsNone(data['actual_spend_usd'])
        self.assertEqual(data['attribution'], 'account_observation')
        self.assertEqual(data['ids'], [CREATED['id']])


class OwnerTests(unittest.TestCase):
    def test_body_admission_rejects_oversize_missing_length_and_nonobject(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); case = home / option('--restore'); case.mkdir()
            (case / 'fact-sheet.md').write_text('Synthetic owner fact for request fault injection.')
            c = types.SimpleNamespace(case=case, args=argparse.Namespace(), card={}, models={'reviewers': [['unused']]})
            with exam_responder.owner_server(c, types.SimpleNamespace(BENCH=ROOT), home) as url:
                parsed = urlparse(url)
                for headers, body, expected in (('Content-Length: 17000\r\n', '', b'413'),
                        ('', '', b'400'), ('Content-Length: 2\r\n', '[]', b'400')):
                    with socket.create_connection((parsed.hostname, parsed.port), timeout=2) as client:
                        client.sendall(f'POST {parsed.path} HTTP/1.0\r\n{headers}\r\n{body}'.encode())
                        self.assertIn(expected, client.recv(200))

    def test_real_protocol_partial_body_and_trickle_do_not_block_health_or_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); case = home / option('--restore'); case.mkdir()
            (case / 'fact-sheet.md').write_text('Synthetic owner fact for protocol fault injection.')
            c = types.SimpleNamespace(case=case, args=argparse.Namespace(), card={}, models={'reviewers': [['unused']]})
            r = types.SimpleNamespace(BENCH=ROOT)
            start = time.monotonic()
            with patch.object(exam_responder, 'REQUEST_SECONDS', .2):
                with exam_responder.owner_server(c, r, home) as url:
                    parsed = urlparse(url)
                    slow = socket.create_connection((parsed.hostname, parsed.port), timeout=2)
                    try:
                        request = f'POST {parsed.path} HTTP/1.0\r\nContent-Length: 100\r\n\r\n{{'.encode()
                        slow.sendall(request)
                        healthy = socket.create_connection((parsed.hostname, parsed.port), timeout=2)
                        healthy.sendall(b'GET /healthz HTTP/1.0\r\n\r\n')
                        self.assertIn(b'200', healthy.recv(100)); healthy.close()
                        time.sleep(.3)
                        self.assertIn(slow.recv(100)[:4], (b'', b'HTTP'))
                    finally: slow.close()
            self.assertLess(time.monotonic() - start, 2)


if __name__ == '__main__': unittest.main()
