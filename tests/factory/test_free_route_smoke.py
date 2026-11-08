"""The per-account free-route smoke (factory/free_route_smoke.py), against a fake OpenCode CLI."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import free_route_smoke
import model_runtime

KEY = 'synthetic-key-never-printed'
DEEPSEEK = 'opencode/deepseek-v4.1-flash-free'


def fake_cli(tmp, lines, record):
    script = Path(tmp) / 'opencode'
    # Records which key the call saw, so the test can check only that account's key went in.
    script.write_text('#!/bin/sh\necho "$OPENCODE_API_KEY" > %s\n' % record
                      + ''.join("echo '%s'\n" % json.dumps(l) for l in lines))
    script.chmod(0o755)
    return str(script)


def step(cost=0):
    part = {'messageID': 'm', 'id': 'p', 'cost': cost, 'modelID': 'deepseek-v4.1-flash-free', 'providerID': 'opencode',
            'tokens': {'input': 1, 'output': 1, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}}
    return [{'type': 'step_start', 'part': {'messageID': 'm'}}, {'type': 'step_finish', 'part': part}]


class Smoke(unittest.TestCase):
    def run_smoke(self, lines, account='opencode-go-key-2'):
        with tempfile.TemporaryDirectory() as tmp:
            secrets = Path(tmp) / 'secrets'; secrets.mkdir()
            (secrets / 'opencode-go-key').write_text('other-account-key\n')
            (secrets / 'opencode-go-key-2').write_text(KEY + '\n')
            record = Path(tmp) / 'seen-key'
            with mock.patch.object(model_runtime, 'OPENCODE_BIN', fake_cli(tmp, lines, record)), \
                 mock.patch.object(model_runtime, '_opencode_flags', lambda binary: ()):
                row = free_route_smoke.smoke(account, DEEPSEEK, secrets, timeout=30)
            seen = record.read_text().strip() if record.exists() else None
        self.assertNotIn(KEY, json.dumps(row))
        return row, seen

    def test_a_free_answer_is_ok_on_that_accounts_key(self):
        row, seen = self.run_smoke(step())
        self.assertEqual((row['ok'], row['error_class'], row['account']), (True, None, 'opencode-go-key-2'))
        self.assertEqual(seen, KEY)

    def test_an_error_or_a_booked_cost_reports_only_content_free_fields(self):
        row, _ = self.run_smoke([{'type': 'error', 'error': {'name': 'UnknownError',
                                                             'data': {'message': 'Unexpected server error'}}}])
        self.assertEqual((row['ok'], row['error_class'], row['error_name'], row['events_seen']),
                         (False, 'opencode_error', 'UnknownError', 1))
        self.assertNotIn('Unexpected', json.dumps(row))
        row, _ = self.run_smoke(step(cost=0.01))
        self.assertFalse(row['ok'])
        self.assertEqual(row['error_class'], 'cost_limit')

    def test_the_zen_and_go_variants_use_their_endpoint_and_model_id(self):
        env = {'PATH': '/bin', 'HOME': '/h', 'XDG_CONFIG_HOME': 'c', 'XDG_DATA_HOME': 'd', 'XDG_CACHE_HOME': 'e',
               'OPENCODE_API_KEY': KEY, 'OPENROUTER_API_KEY': 'other'}
        route, clean = free_route_smoke._probe_environment('go', DEEPSEEK, dict(env))
        cfg = json.loads(clean['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual((route, cfg['enabled_providers'], cfg['provider']['opencode-go']['whitelist']),
                         ('opencode-go/deepseek-v4.1-flash', ['opencode-go'], ['deepseek-v4.1-flash']))
        self.assertNotIn('OPENROUTER_API_KEY', clean)
        route, clean = free_route_smoke._probe_environment('zen', DEEPSEEK, dict(env))
        cfg = json.loads(clean['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual((route, cfg['provider']['opencode']['options']['baseURL']), (DEEPSEEK, 'https://opencode.ai/zen/v1'))

    def test_a_missing_account_file_is_reported_without_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = free_route_smoke.smoke('opencode-go-key', DEEPSEEK, tmp)
        self.assertEqual((row['ok'], row['error_class']), (False, 'credential_missing'))
        with self.assertRaises(ValueError):
            free_route_smoke.smoke('openrouter-key', DEEPSEEK, '/nonexistent')


if __name__ == '__main__':
    unittest.main()
