"""Saved Boat artifacts through real local owners; no provider calls.

AST extraction executes just the production transport expressions, avoiding the
holder's credential/serve setup. Whole-function status/TTL coverage is below too.
"""
import ast
import contextlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
FIXTURES = Path(__file__).with_name('fixtures') / 'isolation-timeouts'
LOAD = lambda name: json.loads((FIXTURES / name).read_text())
SITES = [('key_holder', 0, '25'), ('batch_holder', 0, '25'),
         ('coordinator_inventory', 0, '25'), ('coordinator_inventory', 1, '25'),
         ('batch_status', 0, '30'), ('ttl_continuation', 0, '120')]
GUARD = 300


def expression(module, index):
    tree = ast.parse((ROOT / 'factory' / (module + '.py')).read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.args
             and isinstance(n.args[0], ast.List)
             and 'bin/boat-call' in ast.unparse(n.args[0])]
    calls.sort(key=lambda n: n.lineno)
    return calls[index]


def invoke_site(number):
    module, index, seconds = SITES[number]
    node = expression(module, index)
    assert not any(k.arg == 'timeout' for k in node.keywords)
    worker = LOAD('created.json')['id']
    namespace = dict(ROOT=ROOT, root=ROOT, os=os, subprocess=subprocess,
                     key_holder=types.SimpleNamespace(ROOT=ROOT), run=subprocess.run,
                     THRESHOLDS={'read_seconds': 30}, args=['list', '--json'],
                     worker=worker, command="pgrep -f '^python3 .*factory/run.py'")
    env_node = next(k.value for k in node.keywords if k.arg == 'env')
    env = eval(compile(ast.Expression(env_node), '<production-env>', 'eval'), namespace)
    assert env['BOAT_COMMAND_TIMEOUT_SECONDS'] == seconds
    assert env.get('UNBUG_PROCESS_DEADLINE') == os.environ.get('UNBUG_PROCESS_DEADLINE')
    try:
        result = eval(compile(ast.Expression(node), '<production-call>', 'eval'), namespace)
        if isinstance(result, subprocess.CompletedProcess):
            code, out = result.returncode, result.stdout
        else:
            code, out = 0, result
    except subprocess.CalledProcessError as error:
        code, out = error.returncode, error.stdout
    if isinstance(out, bytes): out = out.decode()
    print(json.dumps({'returncode': code, 'stdout': out}), flush=True)


class OuterCallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.heartbeat = self.home / (LOAD('created.json')['id'] + '.heartbeat')
        self.pids = self.home / 'pids.json'
        self.calls = self.home / 'calls.jsonl'
        self.cli = self.home / 'boat'
        # Named boat deliberately exercises pinned version discovery as well.
        self.cli.write_text('''#!/usr/bin/env python3
import json,os,pathlib,signal,subprocess,sys,time
home=pathlib.Path(os.environ['TEST_HOME'])
with (home/'calls.jsonl').open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1:]==['--version']:
 print(os.environ['TEST_VERSION']); sys.exit(0)
mode=os.environ['TEST_MODE']
if mode=='success':
 if sys.argv[1]=='ssh': print('12345')
 else: print(pathlib.Path(os.environ['TEST_LIST']).read_text())
 sys.exit(0)
if mode=='failure': sys.exit(9)
heartbeat=home/os.environ['TEST_HEARTBEAT']
code="import pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); p=pathlib.Path("+repr(str(heartbeat))+ ")\\nwhile True: p.write_text(str(time.monotonic_ns())); time.sleep(.02)"
child=subprocess.Popen([sys.executable,'-c',code],start_new_session=True)
(home/'pids.json').write_text(json.dumps({'owner':os.getppid(),'transport':os.getpid(),'child':child.pid}))
while not heartbeat.exists(): time.sleep(.01)
if mode=='escape': sys.exit(0)
time.sleep(600)
''')
        self.cli.chmod(0o755)
        # Delay only the command's cleanup, not version discovery. Escape mode
        # also delays long enough for the child to be reparented before ps runs.
        probe = self.home / 'ps'
        probe.write_text('#!/bin/sh\nif [ -f "$TEST_HOME/$TEST_HEARTBEAT" ]; then sleep 3; fi\nexec '
                         + str(shutil.which('ps')) + ' "$@"\n')
        probe.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.home) + os.pathsep + os.environ['PATH'],
                    'BOAT_CMD': str(self.cli), 'TEST_HOME': str(self.home),
                    'TEST_HEARTBEAT': self.heartbeat.name, 'TEST_MODE': 'success',
                    'TEST_VERSION': LOAD('boat-version.json')['version'],
                    'TEST_LIST': str(FIXTURES / 'list.json')}
        for key in ('UNBUG_PROCESS_DEADLINE', 'UNBUG_PROCESS_GROUP_OWNED', 'UNBUG_DIAGNOSTIC_PROCESS_GROUP'):
            self.env.pop(key, None)
        self.addCleanup(self.cleanup_processes)

    def cleanup_processes(self):
        if self.pids.exists():
            pids = json.loads(self.pids.read_text())
            for key in ('child', 'transport', 'owner'):
                with contextlib.suppress(ProcessLookupError): os.kill(pids[key], signal.SIGKILL)

    def stopped(self):
        self.assertTrue(self.heartbeat.exists(), 'injected real descendant never started')
        before = self.heartbeat.read_text(); time.sleep(.2)
        self.assertEqual(before, self.heartbeat.read_text(), 'descendant still running')

    def invoke(self, site, mode, *, deadline=False):
        env = {**self.env, 'TEST_MODE': mode}
        # Set the short inherited deadline inside the worker after its imports.
        if deadline: env['TEST_DEADLINE_SECONDS'] = '2'
        start = time.monotonic()
        result = subprocess.run([sys.executable, '-B', __file__, '--site', str(site)],
                                env=env, capture_output=True, text=True, timeout=GUARD)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout), time.monotonic() - start

    def test_six_actual_call_sites_preserve_artifacts_and_nonzero_results(self):
        for site, (module, index, _) in enumerate(SITES):
            with self.subTest(module=module, index=index):
                result, _ = self.invoke(site, 'success')
                self.assertEqual(result['returncode'], 0)
                if module == 'ttl_continuation' or (module == 'coordinator_inventory' and index == 0):
                    self.assertEqual(result['stdout'].strip(), '12345')
                else: self.assertEqual(json.loads(result['stdout']), LOAD('list.json'))
                result, _ = self.invoke(site, 'failure')
                self.assertEqual(result['returncode'], 9)

    def test_six_callers_wait_for_slow_cleanup_after_inherited_deadline(self):
        for site, (module, index, _) in enumerate(SITES):
            with self.subTest(module=module, index=index):
                result, elapsed = self.invoke(site, 'hang', deadline=True)
                self.assertEqual(result['returncode'], 124)
                self.stopped()
                self.assertGreaterEqual(elapsed, 3)
                print(f'LOCAL_TIMING {module}:{index} timeout_cleanup_seconds={elapsed:.3f}', flush=True)
                calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
                self.assertIn(['--version'], calls)
                self.assertTrue(any(call[0] != '--version' for call in calls))
                self.heartbeat.unlink(); self.pids.unlink(); self.calls.unlink()

    def wait_heartbeat(self):
        end = time.monotonic() + GUARD
        while not self.heartbeat.exists():
            self.assertLess(time.monotonic(), end, 'injected child did not start')
            time.sleep(.02)

    def test_sigterm_owner_finishes_slow_cleanup(self):
        process = subprocess.Popen([str(ROOT / 'bin/boat-call'), 'list', '--json'],
                                   env={**self.env, 'TEST_MODE': 'hang'},
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.wait_heartbeat(); start = time.monotonic(); process.terminate()
            _, err = process.communicate(timeout=GUARD)
            self.assertEqual(process.returncode, 143, err)
            self.stopped()
            print(f'LOCAL_TIMING sigterm_cleanup_seconds={time.monotonic()-start:.3f}', flush=True)
        finally:
            if process.poll() is None: process.kill()
            process.communicate(timeout=GUARD)

    def test_open_row_escaped_pipe_holder_demonstrates_remaining_hang(self):
        caller = subprocess.Popen([sys.executable, '-B', __file__, '--site', '4'],
                                  env={**self.env, 'TEST_MODE': 'escape'},
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.wait_heartbeat()
            owner = json.loads(self.pids.read_text())['owner']
            end = time.monotonic() + GUARD
            # ps's actual process state distinguishes a finished owner from a
            # still-running one even if communicate has not reaped its zombie.
            while True:
                state = subprocess.run([shutil.which('ps'), '-o', 'stat=', '-p', str(owner)],
                                       capture_output=True, text=True, timeout=GUARD).stdout.strip()
                if not state or state.startswith('Z'): break
                self.assertLess(time.monotonic(), end, 'Boat owner never finished')
                time.sleep(.05)
            self.assertIsNone(caller.poll(), 'expected the documented pipe wait')
            before = self.heartbeat.read_text(); time.sleep(.2)
            self.assertNotEqual(before, self.heartbeat.read_text())
            os.kill(json.loads(self.pids.read_text())['child'], signal.SIGKILL)
            out, err = caller.communicate(timeout=GUARD)
            self.assertEqual(caller.returncode, 0, err)
            self.assertEqual(json.loads(out)['returncode'], 0)
        finally:
            self.cleanup_processes()
            if caller.poll() is None: caller.kill()
            caller.communicate(timeout=GUARD)

    def test_whole_status_and_ttl_functions_use_real_transport(self):
        import batch_status
        import ttl_continuation
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(batch_status._boat(['list', '--json']), LOAD('list.json'))
            with patch.dict(os.environ, {'TEST_MODE': 'failure'}):
                with self.assertRaises(subprocess.CalledProcessError) as error:
                    batch_status._boat(['list', '--json'])
                self.assertEqual(error.exception.returncode, 9)
            launch = LOAD('launch.json')['argv']; case = launch[launch.index('--restore') + 1]
            bounds = dict(started_at=1000, deadline=58600, max_attempts=1, max_spend=.75,
                          launch_spend=.75, initial_spend=0, ttl_hours=16)
            self.assertEqual(LOAD('created.json')['ttlSeconds'], bounds['deadline']-bounds['started_at'])
            job = dict(mode='case', case=case, card=case+'.scorecard.json', archive_prefix=case,
                       args=launch, ttl_continuation=bounds)
            # Real copied executable/module, only output records go into tmp.
            (self.home / 'bin').mkdir()
            for name in ('boat-call', 'processes.py'): shutil.copy2(ROOT / 'bin' / name, self.home / 'bin' / name)
            request = ttl_continuation.request_retirement(self.home, LOAD('created.json')['id'], job, now=2000)
            self.assertEqual(request['runner_pid'], 12345)
            self.assertEqual(request['case'], case)
            with patch.dict(os.environ, {'TEST_MODE': 'failure'}):
                with self.assertRaises(subprocess.CalledProcessError) as error:
                    ttl_continuation.request_retirement(self.home, LOAD('created.json')['id'], job, now=2000)
                self.assertEqual(error.exception.returncode, 9)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--site']:
        if os.environ.get('TEST_DEADLINE_SECONDS'):
            os.environ['UNBUG_PROCESS_DEADLINE'] = str(time.monotonic() + float(os.environ['TEST_DEADLINE_SECONDS']))
        invoke_site(int(sys.argv[2]))
    else: unittest.main()
