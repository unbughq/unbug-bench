"""The installed OpenCode resumes a diagnosis session that stopped before its result
(design diagnosis-continue, Murphy row new-diagnosis-early-stop-1).

This test runs the real binary twice, the way model_runtime._invoke runs a diagnosis:
- as a throwaway UID with a 2 GB tmpfs home (run.make_pilots, diagnosis=True);
- with HOME, TMPDIR and XDG_DATA_HOME in that home, and fresh config and cache dirs per run;
- with the openrouter provider shape that model_call_gate.openrouter_environment writes;
- with the prompt on stdin and `sh -c cd` under `sudo -H -u`.

The provider is a local stub, so the test costs nothing and uses no case content.
- The first session replies with no tool call, as cb5e26-h5's MiMo diagnoses did, so it ends
  with no result.
- The second run passes `--continue`. It must resume that session, with the first prompt and
  reply in its history, and write the result.

The test creates and deletes a system user, so it runs only on Linux with passwordless sudo
and FACTORY_LIVE_OPENCODE=1. Provisioning the provider package needs npm access, as a worker
does."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USER = 'factory-continue-probe'
MODEL = 'xiaomi/mimo-v2.6-pro'
FIRST = 'PROBE: start the diagnosis.'
FIRST_REPLY = 'I will read the inputs first.'
SECOND = 'PROBE: continue and write the result file.'


def live():
    if not sys.platform.startswith('linux') or os.environ.get('FACTORY_LIVE_OPENCODE') != '1': return False
    return bool(shutil.which('opencode')) and subprocess.run(['sudo', '-n', 'true']).returncode == 0


class Stub(BaseHTTPRequestHandler):
    """An OpenRouter chat-completions stand-in.
    - The first user turn gets a plain reply, so the session stops.
    - The next user turn gets one `write` tool call.
    - A tool result gets a plain reply."""
    def log_message(self, *a): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append(body)
        last = body['messages'][-1]
        if not body.get('tools') or last['role'] == 'tool':
            delta, finish = {'role': 'assistant', 'content': 'done' if body.get('tools') else 'title'}, 'stop'
        elif sum(m['role'] == 'user' for m in body['messages']) == 1:
            delta, finish = {'role': 'assistant', 'content': FIRST_REPLY}, 'stop'
        else:
            call = {'index': 0, 'id': 'call_probe', 'type': 'function', 'function': {
                'name': 'write', 'arguments': json.dumps({'filePath': self.server.result, 'content': '{"probe": 1}'})}}
            delta, finish = {'role': 'assistant', 'content': None, 'tool_calls': [call]}, 'tool_calls'
        chunk = lambda **k: {'id': 'gen-probe', 'object': 'chat.completion.chunk', 'created': 0, 'model': MODEL, **k}
        events = [chunk(choices=[{'index': 0, 'delta': delta, 'finish_reason': None}]),
                  chunk(choices=[{'index': 0, 'delta': {}, 'finish_reason': finish}],
                        usage={'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15})]
        data = ''.join(f'data: {json.dumps(e)}\n\n' for e in events) + 'data: [DONE]\n\n'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data.encode())


def sudo(*args, check=True):
    return subprocess.run(['sudo', '-n', *args], check=check, capture_output=True)


@unittest.skipUnless(live(), 'needs Linux, passwordless sudo, opencode and FACTORY_LIVE_OPENCODE=1')
class OpenCodeContinue(unittest.TestCase):
    def setUp(self):
        sudo('useradd', '-m', '-s', '/bin/bash', USER)
        self.home = Path('/home') / USER
        self.addCleanup(self.cleanup)
        uid, gid = (int(sudo('id', flag, USER).stdout) for flag in ('-u', '-g'))
        sudo('mount', '-t', 'tmpfs', '-o', f'mode=0700,size=2g,nodev,nosuid,uid={uid},gid={gid}', 'tmpfs', str(self.home))
        sudo('install', '-d', '-m', '700', '-o', USER, '-g', USER, str(self.home / '.cache'))
        self.work = Path(tempfile.mkdtemp(prefix='factory-continue-'))
        self.work.chmod(0o711)
        self.output = self.work / 'output'
        sudo('install', '-d', '-m', '700', '-o', USER, '-g', USER, str(self.output))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
        self.server.requests, self.server.result = [], str(self.output / 'result.json')
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        sudo('pkill', '-KILL', '-u', USER, check=False)
        sudo('umount', str(self.home), check=False)
        sudo('userdel', '-r', USER, check=False)
        sudo('rm', '-rf', str(self.work), check=False)

    def run_opencode(self, prompt, *extra):
        scratch = Path(tempfile.mkdtemp(prefix='factory-tester-state-', dir=self.work))
        sudo('chown', '-R', f'{USER}:{USER}', str(scratch))
        cfg = dict(model='openrouter/' + MODEL, small_model='openrouter/' + MODEL, enabled_providers=['openrouter'],
                   permission={'task': 'deny'}, compaction={'auto': True}, provider={'openrouter': {
                       'npm': '@openrouter/ai-sdk-provider', 'whitelist': [MODEL],
                       'options': {'baseURL': f'http://127.0.0.1:{self.server.server_port}/api/v1', 'apiKey': 'stub'},
                       'models': {MODEL: {'id': MODEL, 'name': MODEL, 'limit': {'context': 262144, 'output': 32768},
                                          'modalities': {'input': ['text'], 'output': ['text']}}}}})
        env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL') if k in os.environ}
        env.update(HOME=str(self.home), TMPDIR=str(self.home / '.cache'),
                   XDG_CONFIG_HOME=str(scratch / 'config'), XDG_CACHE_HOME=str(scratch / 'cache'),
                   XDG_DATA_HOME=str(self.home / '.local/share'),   # the change under test
                   OPENCODE_CONFIG_CONTENT=json.dumps(cfg), OPENCODE_PURE='1', OPENCODE_DISABLE_PROJECT_CONFIG='1',
                   OPENCODE_DISABLE_MODELS_FETCH='1', OPENCODE_DISABLE_AUTOUPDATE='1')
        binary = shutil.which('opencode')
        flags = ['--standalone'] if '--standalone' in subprocess.run(
            [binary, 'run', '--help'], capture_output=True, text=True).stdout else []
        cmd = ['sudo', '-n', '--preserve-env', '-H', '-u', USER, 'sh', '-c', 'cd "$1" && shift && exec "$@"', 'sh',
               str(self.output), binary, 'run', *flags, '-m', 'openrouter/' + MODEL, '--format', 'json', '--auto',
               '--title', 'factory-diagnosis-probe', *extra]
        done = subprocess.run(cmd, input=prompt, env=env, capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith('{')]
        return {e['sessionID'] for e in events if 'sessionID' in e}, events

    def test_a_stopped_session_is_resumed_and_writes_its_result(self):
        first, events = self.run_opencode(FIRST)
        self.assertEqual(len(first), 1, events)
        self.assertFalse(any(e.get('type') == 'tool_use' for e in events), events)
        self.assertFalse(Path(self.server.result).exists())
        before = len(self.server.requests)

        second, events = self.run_opencode(SECOND, '--continue')
        self.assertEqual(second, first, events)   # the same session, not a new one
        resumed = next(r for r in self.server.requests[before:] if r.get('tools'))
        history = json.dumps(resumed['messages'])
        self.assertIn(FIRST, history)             # the first run's prompt and reply are in context
        self.assertIn(FIRST_REPLY, history)
        self.assertTrue(sudo('test', '-f', self.server.result, check=False).returncode == 0, events)
        print('opencode', subprocess.run(['opencode', '--version'], capture_output=True, text=True).stdout.strip(),
              'session', sorted(first), 'requests', len(self.server.requests))


if __name__ == '__main__':
    unittest.main()
