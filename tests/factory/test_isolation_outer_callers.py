"""Saved Boat artifacts through the transport wrapper; no provider calls.
"""
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
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
FIXTURES = Path(__file__).with_name('fixtures') / 'isolation-timeouts'
LOAD = lambda name: json.loads((FIXTURES / name).read_text())
GUARD = 300


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


if __name__ == '__main__': unittest.main()
