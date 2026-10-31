"""Real launch envelopes, with local crash/hang injection; no cloud or decryption."""
import argparse
import asyncio
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch
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
# Hang guard only, never a deadline under test: a loaded host may need minutes.
HANG_GUARD_SECONDS = 300
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
                        run.sh(self.c, self.command, timeout=HANG_GUARD_SECONDS, capture=True)
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
        self.assertEqual(run.sh(self.c, [sys.executable, '-c', parent], timeout=HANG_GUARD_SECONDS), 0)
        self.stopped()

    def test_loaded_host_slow_ps_and_zombie_group_still_clean_up(self):
        # A loaded control host makes ps slow, not hung; cleanup must still see descendants.
        tools = self.home / 'tools'; tools.mkdir()
        (tools / 'ps').write_text(f'#!/bin/sh\nsleep 3\nexec {shutil.which("ps")} "$@"\n')
        (tools / 'ps').chmod(0o755)
        with patch.dict(os.environ, {'PATH': str(tools) + os.pathsep + os.environ['PATH']}):
            with self.assertRaises(subprocess.TimeoutExpired):
                processes.run(self.command, timeout=.6)
        self.stopped()
        # An exited, unreaped session leader: macOS refuses killpg on a zombie-only group.
        zombie = subprocess.Popen(['true'], start_new_session=True)
        try:
            end = time.monotonic() + HANG_GUARD_SECONDS
            while subprocess.run(['ps', '-o', 'stat=', '-p', str(zombie.pid)],
                                 capture_output=True, text=True, timeout=HANG_GUARD_SECONDS).stdout.strip()[:1] != 'Z':
                self.assertLess(time.monotonic(), end, 'child never became a zombie')
                time.sleep(.01)
            processes.kill_tree(zombie.pid, alive=True)
        finally:
            zombie.wait(timeout=HANG_GUARD_SECONDS)

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
        result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'bin')], capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'owner survived')

    def test_standalone_bench_build_allows_over_120_seconds_but_honors_inherited_deadline(self):
        import bench
        actual_popen = subprocess.Popen
        clock = [time.monotonic()]
        ready, finished = self.home / 'ready', self.home / 'finished'
        complete = [True]
        code = (f'import pathlib,time; ready=pathlib.Path({str(ready)!r}); '
                f'finished=pathlib.Path({str(finished)!r}); ready.touch()\n'
                'while not finished.exists(): time.sleep(.01)\n'
                f'print({LOAD("boat-version.json")["version"]!r})')
        command = [sys.executable, '-c', code]
        def elapsed(args, **kwargs):
            child = actual_popen(args, **kwargs)
            if args == command:
                for _ in range(200):
                    if ready.exists(): break
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                clock[0] += 121  # advance only after the real child has started
                if complete[0]: finished.touch()
            return child
        with patch.dict(os.environ):
            os.environ.pop('UNBUG_PROCESS_DEADLINE', None)
            with patch.object(processes.time, 'monotonic', lambda: clock[0]), \
                 patch.object(processes.subprocess, 'Popen', elapsed):
                self.assertEqual(bench.command(command), LOAD('boat-version.json')['version'])
                ready.unlink(); finished.unlink(); complete[0] = False
                os.environ['UNBUG_PROCESS_DEADLINE'] = str(clock[0] + 60)
                with self.assertRaises(subprocess.TimeoutExpired): bench.command(command)

    def test_parallel_wipe_executes_real_child_and_removes_slot_guard(self):
        from run_artifacts import RunArtifacts
        bench = self.home / 'bench'
        for name in ('bin/bench.py', 'bin/bench_judging.py', 'bin/processes.py',
                     'factory/case_permissions.py', 'projects/medusa/compose.yaml'):
            target = bench / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        tools = self.home / 'tools'; tools.mkdir()
        calls = self.home / 'docker.jsonl'
        docker = tools / 'docker'
        docker.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['TEST_DOCKER_CALLS'],'a') as f:
 f.write(json.dumps({'slot':os.environ.get('UNBUG_FACTORY_SLOT'),'args':sys.argv[1:]})+'\\n')
''')
        docker.chmod(0o755)
        home = self.home / 'runner'; home.mkdir()
        c = types.SimpleNamespace(work=home / 'work' / LOAD('scorecard.json')['case'],
                                  card=LOAD('scorecard.json'), t0=time.time() - 1)
        c.work.mkdir(parents=True)
        def cleanup(path, **kwargs):
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink(missing_ok=True)
        artifacts = RunArtifacts(home, bench, home / 'sealed', ROOT / 'factory/statements-recipient.txt',
            (), lambda: [], lambda *a, **k: None, lambda c: int(option('--bench-workers')),
            lambda c: None, cleanup)
        with patch.dict(os.environ, {'PATH':str(tools)+os.pathsep+os.environ['PATH'],
                                     'TEST_DOCKER_CALLS':str(calls)}):
            artifacts.wipe(c)  # execute the actual python -c snippet, not a process mock
        self.assertTrue(c.card['wipe']['factory_cleanup_ok'])
        events = [json.loads(line) for line in calls.read_text().splitlines()]
        self.assertIn({'slot':'1','args':['image','rm','-f','unbug-bench-medusa:guard-1']}, events)

    def test_gate_deadline_is_operational_and_does_not_send_writer_feedback(self):
        c = types.SimpleNamespace(args=run.argument_parser().parse_args(worker_args()),
                                  work=self.home, case=self.home / 'case', card=LOAD('scorecard.json'), audit_gates=['G13'])
        c.case.mkdir()
        c.args.agent_timeout = .1  # fault injection inside the real saved launch envelope
        c.card['gates'] = {}
        c.case_id = LOAD('scorecard.json')['case']
        pipeline = run._gate_pipeline()
        def hang(ctx, gate):
            processes.run([sys.executable, '-c', 'import time; time.sleep(60)'])
        pipeline.evaluate = hang
        pipeline.budget_boundary = lambda c: None
        pipeline.after_gate = Mock()
        pipeline.publish = lambda *a: None
        pipeline.run(c)
        self.assertTrue(c.stopped)
        self.assertEqual(c.card['terminal_stop'], 'infrastructure_exhausted')
        self.assertEqual(c.card['gates']['G13'], 'invalid-infra')
        self.assertNotIn('failed_gate', c.card)
        self.assertNotIn('failed_detail', c.card)
        pipeline.after_gate.assert_not_called()


class SupervisorTests(unittest.TestCase):
    def test_real_runner_early_import_and_ready_boundary(self):
        for dependency, ready, attempts in (('gate_pipeline.py', False, 3), ('free_models.py', True, 1)):
            with self.subTest(dependency=dependency), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp); factory = home / 'factory'
                factory.mkdir()
                for path in (ROOT / 'factory').glob('*.py'):
                    shutil.copy2(path, factory / path.name)
                self.assertEqual((factory / 'run.py').read_bytes(), (ROOT / 'factory/run.py').read_bytes())
                (factory / dependency).write_text('raise ImportError("injected dependency unavailable")\n')
                # Preserve the recorded source/routes/caps, using a fresh dry-run namespace.
                args = worker_args(); fresh = []; i = 0
                while i < len(args):
                    if args[i] in ('--resume', '--resume-bench-sha'): i += 2
                    else: fresh.append(args[i]); i += 1
                result = subprocess.run([sys.executable, str(ROOT / 'factory/runner_supervisor.py'), '--',
                    sys.executable, '-B', str(factory / 'run.py'), *fresh, '--dry-run'],
                    env={**os.environ,'HOME':str(home),'FACTORY_RUNNER_SECONDS':str(HANG_GUARD_SECONDS)},
                    capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
                self.assertEqual(result.returncode, 1)
                data = json.loads((home / 'sealed/runner-status.json').read_text())
                self.assertEqual((data['attempt'], data['exit_status']), (attempts, 1))
                self.assertEqual(data['reason'], 'finished' if ready else 'startup_failed')
                self.assertEqual((home / 'sealed/runner-ready-1').exists(), ready)
                self.assertFalse((home / 'sealed/DONE').exists())
                self.assertEqual(len(list((home / 'work').glob('*'))), 1 if ready else 0)

    def invoke(self, code, *, prior_work=False, seconds=8):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        if prior_work:
            (self.home / 'work' / option('--restore')).mkdir(parents=True)
        command = [sys.executable, str(ROOT / 'factory/runner_supervisor.py'), '--', sys.executable, '-c', code,
                   *worker_args()]  # real saved worker arguments; injected interpreter ignores them
        return subprocess.run(command, env={**os.environ, 'HOME': str(self.home),
            'FACTORY_RUNNER_SECONDS': str(seconds)}, capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)

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
                env=self.env, capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), LOAD(command + '.json'))
        bad = subprocess.run([str(ROOT / 'bin/boat-call'), 'list', '--json'],
            env={**self.env, 'TEST_VERSION': 'boat wrong'}, capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
        self.assertNotEqual(bad.returncode, 0)
        self.assertEqual(bad.stdout, '')

    def test_default_home_discovery_pins_without_an_interactive_shell(self):
        installed = self.home / '.ascii/bin/boat'; installed.parent.mkdir(parents=True)
        shutil.copy2(self.cli, installed)
        env = {**self.env, 'HOME':str(self.home)}; env.pop('BOAT_CMD')
        result = subprocess.run([str(ROOT / 'bin/boat-call'), 'list', '--json'],
            env=env, capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), LOAD('list.json'))
        bad = subprocess.run([str(ROOT / 'bin/boat-call'), 'list', '--json'],
            env={**env,'TEST_VERSION':'boat wrong'}, capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
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
            'UNBUG_LAUNCH_STATE':str(state)}, capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
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
        for _, process in jobs: process.communicate(timeout=HANG_GUARD_SECONDS)
        self.assertEqual(sorted(p.returncode for _, p in jobs), [0, 1])
        record = next(path for path, p in jobs if p.returncode == 0)
        ledger_path = self.home / 'control/boat-reservations.json'
        ledger = json.loads(ledger_path.read_text())
        ledger['reservations'][str(record.resolve())]['expires_at'] = time.time() - 1
        ledger_path.write_text(json.dumps(ledger))  # fault injection: abandoned controller
        refused = next(path for path,p in jobs if p.returncode != 0)
        retry = subprocess.run([str(ROOT / 'bin/boat-spend'), '--check', '1', str(hours),
            str(balance * 2), str(refused)], env=self.env, capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(json.loads(ledger_path.read_text())['reservations'][str(record.resolve())]['status'],
                         'reconciled_expired')
        ids = self.home / 'ids'; ids.write_text(CREATED['id'] + '\n')
        result = subprocess.run([str(ROOT / 'bin/boat-spend'), '--finish', str(record), '0', str(ids)],
            env=self.env, capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(record.read_text())
        self.assertIsNone(data['actual_spend_usd'])
        self.assertEqual(data['attribution'], 'account_observation')
        self.assertEqual(data['ids'], [CREATED['id']])


class OwnerTests(unittest.TestCase):
    def test_concurrent_owner_ask_is_bounded_and_does_not_overlap_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); case = home / option('--restore'); case.mkdir()
            (case / 'fact-sheet.md').write_text('Synthetic owner fact for concurrent request injection.')
            c = types.SimpleNamespace(case=case, args=argparse.Namespace(), card={}, models={'reviewers': [['unused']]})
            entered, release = threading.Event(), threading.Event()
            def call(ctx, chain, text, directory, name, **kwargs):
                entered.set(); release.wait(2)
                (directory / 'answer.json').write_text('{"answer":"synthetic answer"}')
                return 0
            r = types.SimpleNamespace(BENCH=ROOT, model_call=call, BudgetError=run.BudgetError,
                jload=lambda path, default: json.loads(path.read_text()))
            results = []
            with exam_responder.owner_server(c, r, home) as url:
                def ask():
                    with urllib.request.urlopen(urllib.request.Request(url,
                            data=b'{"question":"synthetic question"}'), timeout=3) as response:
                        results.append(response.status)
                thread = threading.Thread(target=ask); thread.start()
                try:
                    self.assertTrue(entered.wait(2))
                    with self.assertRaises(urllib.error.HTTPError) as error: ask()
                    self.assertEqual(error.exception.code, 503); error.exception.close()
                finally:
                    release.set(); thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
                self.assertEqual(results, [200])

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
                        for _ in range(6):
                            try: slow.sendall(b' ')
                            except OSError: break
                            time.sleep(.05)  # activity must not refresh the total parsing deadline
                        slow.settimeout(.05)
                        try: reply = slow.recv(100)
                        except ConnectionResetError: reply = b''
                        self.assertIn(reply[:4], (b'', b'HTTP'))
                    finally: slow.close()
            self.assertLess(time.monotonic() - start, 2)


if __name__ == '__main__': unittest.main()
