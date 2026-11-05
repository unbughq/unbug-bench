"""Saved Boat artifacts through real local owners; no provider calls.

AST extraction executes just the production transport expressions, avoiding the
holder's credential/serve setup. Whole-function status/TTL coverage is below too.
"""
import ast
import contextlib
import json
import os
import runpy
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
    assert env['BOAT_CAPTURE_OUTPUT'] == '1'
    assert env.get('UNBUG_PROCESS_DEADLINE') == os.environ.get('UNBUG_PROCESS_DEADLINE')
    try:
        result = eval(compile(ast.Expression(node), '<production-call>', 'eval'), namespace)
        if isinstance(result, subprocess.CompletedProcess):
            code, out, err = result.returncode, result.stdout, result.stderr
        else:
            code, out, err = 0, result, None
    except subprocess.CalledProcessError as error:
        code, out, err = error.returncode, error.stdout, error.stderr
    if isinstance(out, bytes): out = out.decode()
    if isinstance(err, bytes): err = err.decode()
    print(json.dumps({'returncode': code, 'stdout': out, 'stderr': err}), flush=True)


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
assert 'BOAT_CAPTURE_OUTPUT' not in os.environ
mode=os.environ['TEST_MODE']
if mode=='oversize':
 os.write(int(os.environ['TEST_OUTPUT_FD']), b'x'*(8*1024*1024+1)); sys.exit(9)
if mode.startswith('escape'):
 if sys.argv[1]=='ssh': print('12345',flush=True)
 else: print(pathlib.Path(os.environ['TEST_LIST']).read_text(),end='',flush=True)
 print('injected transport diagnostic',file=sys.stderr,flush=True)
if mode=='success':
 if sys.argv[1]=='ssh': print('12345')
 else: print(pathlib.Path(os.environ['TEST_LIST']).read_text())
 sys.exit(0)
if mode=='failure': sys.exit(9)
heartbeat=home/os.environ['TEST_HEARTBEAT']
code="import pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); p=pathlib.Path("+repr(str(heartbeat))+ ")\\nwhile True: p.write_text(str(time.monotonic_ns())); time.sleep(.02)"
if mode=='escape-write':
 code=code.replace('import pathlib,signal,time;', 'import os,pathlib,signal,time;').replace('time.sleep(.02)', 'os.write(1,b" "); os.write(2,b" "); time.sleep(.002)')
child=subprocess.Popen([sys.executable,'-c',code],start_new_session=True)
(home/'pids.json').write_text(json.dumps({'owner':os.getppid(),'transport':os.getpid(),'child':child.pid}))
while not heartbeat.exists(): time.sleep(.01)
if mode.startswith('escape'): sys.exit(9 if mode=='escape-failure' else 0)
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
        data = json.loads(result.stdout)
        if data['stderr'] is None: data['stderr'] = result.stderr
        return data, time.monotonic() - start

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
                                   env={**self.env, 'TEST_MODE': 'hang', 'BOAT_CAPTURE_OUTPUT': '1'},
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

    def test_six_callers_return_while_escaped_descendant_holds_streams(self):
        for mode in ('escape', 'escape-write', 'escape-failure'):
            for site, (module, index, _) in enumerate(SITES):
                with self.subTest(mode=mode, module=module, index=index):
                    result, elapsed = self.invoke(site, mode)
                    self.assertEqual(result['returncode'], 9 if mode=='escape-failure' else 0)
                    expected = ('12345\n' if module == 'ttl_continuation' or
                                (module == 'coordinator_inventory' and index == 0)
                                else (FIXTURES / 'list.json').read_text())
                    self.assertTrue(result['stdout'].startswith(expected), result)
                    self.assertEqual(result['stdout'][len(expected):].strip(), '')
                    diagnostic = 'injected transport diagnostic\n'
                    self.assertTrue(result['stderr'].startswith(diagnostic), result)
                    self.assertEqual(result['stderr'][len(diagnostic):].strip(), '')
                    if mode == 'escape-write':
                        self.assertGreater(len(result['stdout']), len(expected))
                        self.assertGreater(len(result['stderr']), len(diagnostic))
                    before = self.heartbeat.read_text(); time.sleep(.1)
                    self.assertNotEqual(before, self.heartbeat.read_text(),
                                        'escaped child must still be alive at caller return')
                    print(f'LOCAL_TIMING {module}:{index} {mode}_seconds={elapsed:.3f}', flush=True)
                    # Successful return proves neither descendant death nor remote cleanup.
                    self.cleanup_processes()
                    self.heartbeat.unlink(); self.pids.unlink(); self.calls.unlink()

    def test_oversize_either_stream_fails_without_partial_output(self):
        for fd in ('1', '2'):
            with self.subTest(fd=fd):
                result = subprocess.run([str(ROOT / 'bin/boat-call'), 'list', '--json'],
                    env={**self.env, 'TEST_MODE': 'oversize', 'TEST_OUTPUT_FD': fd,
                         'BOAT_CAPTURE_OUTPUT': '1'}, capture_output=True, timeout=GUARD)
                self.assertEqual(result.returncode, 125)
                self.assertEqual(result.stdout, b'')
                self.assertEqual(result.stderr, b'boat-call: captured metadata exceeds 8 MiB\n')

    def test_snapshot_preserves_shared_offset_with_short_reads_and_growth(self):
        snapshot = runpy.run_path(str(ROOT / 'bin/boat-call'))['snapshot']
        saved = (FIXTURES / 'list.json').read_bytes()
        pread = os.pread
        with tempfile.TemporaryFile() as stream:
            stream.write(saved); stream.flush()
            def append_and_read(fd, count, offset):
                # Model an ordinary inherited writer sharing the descriptor's offset.
                self.assertGreaterEqual(os.lseek(fd, 0, os.SEEK_CUR), len(saved))
                os.write(fd, b' ')
                return pread(fd, min(count, 7), offset)
            with patch('os.pread', side_effect=append_and_read) as reader:
                self.assertEqual(snapshot(stream, len(saved)), saved)
                self.assertGreater(reader.call_count, 1)
                self.assertEqual(stream.tell(), len(saved) + reader.call_count)
            # A truncation cannot leak an apparently successful prefix.
            stream.truncate(1)
            with self.assertRaises(OSError): snapshot(stream, len(saved))

    def test_default_output_is_streamed_before_transport_finishes(self):
        output = self.home / 'streaming-output'
        with output.open('wb') as stream:
            process = subprocess.Popen([str(ROOT / 'bin/boat-call'), 'list', '--json'],
                env={**self.env, 'TEST_MODE': 'escape'}, stdout=stream,
                stderr=subprocess.DEVNULL)
            try:
                self.wait_heartbeat()
                self.assertIsNone(process.poll(), 'slow cleanup should still be running')
                self.assertEqual(output.read_bytes(), (FIXTURES / 'list.json').read_bytes())
                self.assertEqual(process.wait(timeout=GUARD), 0)
            finally:
                self.cleanup_processes()
                if process.poll() is None: process.kill()
                process.wait(timeout=GUARD)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--site']:
        if os.environ.get('TEST_DEADLINE_SECONDS'):
            os.environ['UNBUG_PROCESS_DEADLINE'] = str(time.monotonic() + float(os.environ['TEST_DEADLINE_SECONDS']))
        invoke_site(int(sys.argv[2]))
    else: unittest.main()
