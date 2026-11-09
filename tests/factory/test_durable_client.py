"""Exercise the installed laptop client through a real stand-in SSH process."""
import contextlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
from durable import client


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / 'request.json'
        self.response = self.root / 'response.json'
        self.card = {'batch': 'b-default', 'sealed': 0, 'target_sealed': 1, 'cases': [{
            'case': 'case-one', 'status': 'running', 'stage': 'admit', 'reason': None,
            'writer_rounds': 0, 'extensions': 0, 'replacement_of': None, 'gates': {}}]}
        self.response.write_text(json.dumps(self.card))
        self.ssh = self.root / 'fake-ssh.py'
        self.ssh.write_text('import json,sys\nfrom pathlib import Path\n'
            'Path(sys.argv[1]).write_text(json.dumps(sys.argv[3:]))\n'
            'print(Path(sys.argv[2]).read_text())\n')
        self.profile = self.root / 'connection.json'
        self.value = {'ssh': [sys.executable, str(self.ssh), str(self.capture), str(self.response)],
                      'command': ['python3', '/remote path/unbug;literal', '--config', '/private config.json'],
                      'batch': 'b-default'}
        self.profile.write_text(json.dumps(self.value)); self.profile.chmod(0o600)

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = client.main(['--connection', str(self.profile), *args])
        return code, out.getvalue(), err.getvalue()

    def test_default_override_text_and_json_quote_remote_arguments(self):
        code, out, err = self.call('status')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('running at admit', out)
        self.assertEqual(shlex.split(json.loads(self.capture.read_text())[0]),
                         self.value['command'] + ['status', 'b-default'])
        self.card['batch'] = 'b-other'; self.response.write_text(json.dumps(self.card))
        code, out, err = self.call('report', 'b-other', '--json')
        self.assertEqual((code, json.loads(out), err), (0, self.card, ''))
        self.assertEqual(shlex.split(json.loads(self.capture.read_text())[0])[-2:], ['report', 'b-other'])

    def test_board_asks_the_controller_for_the_generated_board(self):
        board = {'at': 1000, 'unavailable': [], 'controller': {'state': 'active'}, 'guard': None, 'sealed': 0,
                 'live': 1, 'totals': {'running': 1}, 'spend_usd_micros': {'spent': 2_000_000, 'held': 0, 'waste': 0},
                 'cases': [{'batch': 'b-x', 'case': 'case-one', 'status': 'running', 'stage': 'writer:2',
                            'writer_round': 2, 'gates_passed': ['G1'], 'failed_gate': None, 'reason': None,
                            'spend_usd_micros': {'spent': 2_000_000, 'held': 0, 'waste': 0}, 'last_event_at': 900,
                            'quiet_for_s': 100, 'live': True}]}
        self.response.write_text(json.dumps(board))
        code, out, err = self.call('board', '--live')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('SEALING BOARD', out); self.assertIn('writer:2', out)
        self.assertEqual(shlex.split(json.loads(self.capture.read_text())[0]),
                         self.value['command'] + ['board', '--live'])
        code, out, err = self.call('board', '--json')
        self.assertEqual((code, json.loads(out)), (0, board))
        self.assertEqual(shlex.split(json.loads(self.capture.read_text())[0])[-1], 'board')

    def test_installed_archive_runs_without_checkout_or_optional_dependencies(self):
        target = self.root / 'installed'
        subprocess.run([sys.executable, str(ROOT / 'bin/install-unbug'), '--bin-dir', str(target)],
                       capture_output=True, check=True)
        result = subprocess.run([sys.executable, '-I', str(target / 'unbug'), '--connection',
            str(self.profile), 'status'], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('case-one: running at admit', result.stdout)

    def test_missing_private_permissions_and_malformed_connection(self):
        self.profile.chmod(0o644)
        self.assertEqual(self.call('status')[0], 1)
        self.assertFalse(self.capture.exists())
        self.profile.chmod(0o600); self.profile.write_text('sensitive invalid JSON')
        code, out, err = self.call('status')
        self.assertEqual(code, 1); self.assertNotIn('sensitive', out + err)
        self.profile.unlink()
        self.assertIn('No controller connection', self.call('status')[2])

    def test_failures_are_clear_without_echoing_remote_diagnostics(self):
        for stderr, expected in [('Permission denied: sensitive detail', 'authentication failed'),
                                 ('Host key verification failed: sensitive detail', 'host verification failed'),
                                 ('sensitive detail', 'Controller status failed')]:
            with patch.object(client.subprocess, 'run', return_value=subprocess.CompletedProcess([], 255, '', stderr)):
                code, out, err = self.call('status')
            self.assertEqual(code, 1); self.assertIn(expected, err); self.assertNotIn('sensitive', out + err)
        with patch.object(client.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ssh', 45)):
            self.assertIn('timed out', self.call('status')[2])

    def test_invalid_response_and_wrong_batch_are_not_printed(self):
        for text in ('sensitive detail', '{}', json.dumps(dict(self.card, batch='b-unrelated'))):
            self.response.write_text(text)
            code, out, err = self.call('status')
            self.assertEqual(code, 1); self.assertEqual(out, '')
            self.assertIn('invalid status response', err)
            self.assertNotIn('sensitive', err)


if __name__ == '__main__': unittest.main()
