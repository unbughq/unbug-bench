"""Offline auth lifetime and first-stop regressions. Synthetic credentials only."""
import argparse
import base64
import datetime
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import budget
import model_runtime
import model_router
from router_test_support import offline_router
_ROUTING = offline_router()
import recovery
import run


def auth(exp, last_refresh='2026-10-01T00:00:00Z'):
    payload = base64.urlsafe_b64encode(json.dumps({'exp': exp}).encode()).decode().rstrip('=')
    return {'tokens': {'access_token': 'e30.' + payload + '.synthetic',
                       'refresh_token': 'synthetic-refresh', 'id_token': 'synthetic-id'},
            'last_refresh': last_refresh}


class LoginTests(unittest.TestCase):
    def test_gate_boundaries_and_expiry_precedence(self):
        self.addCleanup(offline_router()[0].close)
        import codex_login
        now = int(datetime.datetime(2026, 10, 28, tzinfo=datetime.timezone.utc).timestamp())
        end = now + 8 * 3600 + 1800 + 300
        for expiry, allowed in ((end - 1, False), (end, False), (end + 1, True)):
            if allowed:
                codex_login.validate(auth(expiry), 8 * 3600, now=now)
            else:
                with self.assertRaisesRegex(ValueError, 'refresh with bin/setup-secrets codex'):
                    codex_login.validate(auth(expiry), 8 * 3600, now=now)

    def test_gate_refuses_unverifiable_and_invalid_inputs_without_echo(self):
        self.addCleanup(offline_router()[0].close)
        import codex_login
        for value in ({}, {'tokens': {'access_token': 'secret-not-a-jwt'}},
                      auth(True), auth(float('nan')), auth(9999999999.0), auth(10**30),
                      auth(9999999999, 'invalid-secret')):
            with self.assertRaises(ValueError) as caught:
                codex_login.validate(value, 3600)
            self.assertNotIn('secret-not-a-jwt', str(caught.exception))
            self.assertNotIn('invalid-secret', str(caught.exception))
        for ttl in (0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValueError): codex_login.validate(auth(9999999999), ttl)

    def test_bundle_gate_is_before_worker_creation_and_restore(self):
        self.addCleanup(offline_router()[0].close)
        launch = (ROOT / 'factory/launch.sh').read_text()
        self.assertLess(launch.index('codex_login_gate\n'), launch.index('if [ -n "$restore" ] &&'))
        self.assertLess(launch.index('if ! codex_login_gate;'), launch.index('if ! guard_new;'))
        for valid in (False, True):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w') as archive:
                raw = json.dumps(auth(9999999999 if valid else 1)).encode()
                member = tarfile.TarInfo('codex-auth.json'); member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'factory/codex_login.py'),
                                     '--ttl-hours', '8'], input=stream.getvalue(), capture_output=True)
            self.assertEqual(result.returncode, 0 if valid else 1)
            self.assertNotIn(b'synthetic-refresh', result.stdout + result.stderr)

    def test_real_launcher_rejects_expired_bundle_before_any_cloud_call(self):
        self.addCleanup(offline_router()[0].close)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with tarfile.open(root/'bundle', 'w') as archive:
                raw = json.dumps(auth(1)).encode()
                member = tarfile.TarInfo('codex-auth.json'); member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
            (root/'age').write_text('#!/bin/sh\ncat "$SYNTHETIC_BUNDLE"\n')
            (root/'boat').write_text('#!/bin/sh\ntouch "$SYNTHETIC_CLOUD_CALLED"\nexit 99\n')
            for name in ('age','boat'): (root/name).chmod(0o755)
            env = {**os.environ, 'PATH':str(root)+os.pathsep+os.environ['PATH'],
                   'UNBUG_CONTROL_HOME':str(root/'control'), 'BOAT_CMD':str(root/'boat'),
                   'SYNTHETIC_BUNDLE':str(root/'bundle'), 'SYNTHETIC_CLOUD_CALLED':str(root/'called')}
            for extra in ([], ['--restore','case-synthetic']):
                result = subprocess.run(['/bin/sh', str(ROOT/'factory/launch.sh'), '1',
                    '--source','port',*extra], input='synthetic-identity', capture_output=True, text=True, env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('refresh with bin/setup-secrets codex', result.stderr)
                self.assertFalse((root/'called').exists())

    def test_worker_copy_cannot_rotate_and_preserves_source(self):
        self.addCleanup(offline_router()[0].close)
        import codex_login
        value = auth(9999999999)
        original = json.dumps(value)
        result = codex_login.worker_auth(value)
        self.assertEqual(result['auth_mode'], 'chatgptAuthTokens')
        self.assertEqual(result['tokens']['refresh_token'], '')
        self.assertEqual(json.dumps(value), original)

    def test_runtime_stages_access_only_auth_with_private_permissions(self):
        self.addCleanup(offline_router()[0].close)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'transcripts').mkdir(); (root/'.codex').mkdir()
            source=model_router.SECRETS/'codex-auth.json'; source.write_text(json.dumps(auth(9999999999)))
            before=source.read_bytes()
            c=SimpleNamespace(work=root,case=root,card={},ledger=root/'ledger',
                args=argparse.Namespace(agent_timeout=5,max_cost=5,max_role_calls=10,
                    max_total_calls=10,no_progress_minutes=1,max_zero_tokens=3))
            runtime=model_runtime.ModelRuntime(root,Mock(),Mock(),lambda p,**kw: __import__('shutil').rmtree(p),Mock())
            def execute(cmd,cwd,env,*args,**kw):
                staged=Path(env['CODEX_HOME'])/'auth.json'
                self.assertEqual(json.loads(staged.read_text())['auth_mode'],'chatgptAuthTokens')
                self.assertFalse(json.loads(staged.read_text())['tokens']['refresh_token'])
                self.assertEqual(staged.stat().st_mode & 0o777,0o600)
                return subprocess.CompletedProcess(cmd,0)
            with patch.dict(os.environ,{'CODEX_HOME':str(source.parent)}), \
                 patch.object(model_runtime,'pinned_cli',return_value='synthetic'), \
                 patch.object(model_runtime,'run_budgeted',side_effect=execute):
                runtime.call(c,['codex/gpt-6.1-sol'],'synthetic',root,'reviewer-1')
            self.assertEqual(source.read_bytes(),before)

    def test_auth_diagnostics_are_distinct_and_sticky(self):
        self.addCleanup(offline_router()[0].close)
        messages = ['Failed to refresh token: Your access token could not be refreshed because your refresh token was already used. Please log out and sign in again.',
                    'workspace routing discovery unauthorized (401)',
                    json.dumps({'type':'turn.failed','error':{'message':'Your authentication token has expired. Please sign in again.'}})]
        with tempfile.TemporaryDirectory() as tmp:
            for i, message in enumerate(messages):
                folder = Path(tmp) / str(i); folder.mkdir()
                with self.assertRaisesRegex(budget.BudgetError, '^codex_login_expired$'):
                    budget.run_budgeted([sys.executable, '-c', 'print(' + repr(message) + ')'],
                        folder, os.environ.copy(), folder/'transcript', folder/'ledger', 5,
                        driver='codex', configured_model='codex/gpt-6.1-sol')
                self.assertEqual(json.loads((folder/'ledger').read_text())['terminal_stop'], 'codex_login_expired')

    def test_preflight_retains_login_reason_and_deliberate_restore_is_allowed(self):
        self.addCleanup(offline_router()[0].close)
        c = SimpleNamespace(card={}, case=Path('.'), models={'attacker':['codex/gpt-6.1-sol'],
            'reviewers':[['reviewer']], 'strong_calibrator':['strong'], 'easy_calibrator':['easy']})
        with patch.object(run, 'opencode', side_effect=budget.BudgetError('codex_login_expired')):
            with self.assertRaisesRegex(budget.BudgetError, '^codex_login_expired$'): run.provider_preflight(c)
        card = {'status':'stopped','terminal_stop':'codex_login_expired',
                'continuation_budget':{'terminal_stop':'codex_login_expired'}}
        recovery.require_holder_stop(card, [], 'case')
        self.assertTrue(recovery.ledger_agrees(card, route='holder'))
        with self.assertRaises(ValueError): recovery.require_restart_stop(card, [])


class CleanupTests(unittest.TestCase):
    def test_launch_exit_preserves_primary_exit_code_and_records_cleanup(self):
        self.addCleanup(offline_router()[0].close)
        script = '''
root=$1; state=$2; primary=$3; cleanup_fail=$4
. "$root/bin/boat-launch-guards.sh"
guard_ids() { echo synthetic > "$state/ids"; }
guard_retire() { [ "$cleanup_fail" = no ] || return 1; touch "$state/$1.deleted"; }
boat() { printf '{"sandboxes":[]}'; }
UNBUG_LAUNCH_STATE=$state; spend_file=""; bundle=""
guard_exit "$primary"
'''
        for primary, fail, expected in ((143,'yes',143),(0,'yes',1),(7,'no',7)):
            with tempfile.TemporaryDirectory() as tmp:
                result=subprocess.run(['/bin/sh','-c',script,'sh',str(ROOT),tmp,str(primary),fail],
                                      capture_output=True,text=True)
                self.assertEqual(result.returncode,expected,result.stderr)
                self.assertEqual(json.loads((Path(tmp)/'cleanup-status.json').read_text()),
                    {'primary_exit_code':primary,'cleanup_failed':fail=='yes'})

    def test_budget_process_cleanup_cannot_replace_auth_stop(self):
        self.addCleanup(offline_router()[0].close)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            original=budget.os.killpg
            def kill_then_fail(pid,sig):
                original(pid,sig)
                raise OSError('private-stop-error')
            with patch.object(budget.os,'killpg',side_effect=kill_then_fail):
                with self.assertRaisesRegex(budget.BudgetError,'^codex_login_expired$'):
                    budget.run_budgeted([sys.executable,'-c',
                        'import time; print("401 Unauthorized",flush=True); time.sleep(5)'],
                        root,os.environ.copy(),root/'transcript',root/'ledger',10,
                        driver='codex',configured_model='codex/gpt-6.1-sol')
            ledger=json.loads((root/'ledger').read_text())
            self.assertEqual(ledger['terminal_stop'],'codex_login_expired')
            self.assertEqual(ledger['cleanup_errors'],[{'stage':'process_cancellation','error':'OSError'}])

    def test_scratch_cleanup_preserves_model_stop_and_attempts_both_steps(self):
        self.addCleanup(offline_router()[0].close)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'transcripts').mkdir()
            c = SimpleNamespace(work=root, case=root, card={}, ledger=root/'ledger',
                args=argparse.Namespace(agent_timeout=5,max_cost=5,max_role_calls=10,
                    max_total_calls=10,no_progress_minutes=1,max_zero_tokens=3))
            command = Mock(side_effect=OSError('private-cleanup-detail'))
            cleanup = Mock(side_effect=PermissionError('private-cleanup-detail'))
            runtime = model_runtime.ModelRuntime(root, command, Mock(), cleanup, lambda u: root/u)
            with patch.object(model_runtime, 'pinned_cli', return_value='synthetic'), \
                 patch.object(model_runtime.ModelRuntime, '_hand_to', side_effect=lambda c,u,p:p), \
                 patch.object(model_runtime, 'run_budgeted', side_effect=budget.BudgetError('codex_login_expired')):
                with self.assertRaisesRegex(budget.BudgetError, '^provider_wait$'):
                    runtime.call(c, ['claude/synthetic'], 'synthetic', root, 'reviewer-1', user='synthetic')
            cleanup.assert_called_once()  # Uncertain cleanup must not start another model.
            self.assertEqual([v['stage'] for v in c.card['cleanup_errors']], ['model_process', 'model_scratch'])
            self.assertNotIn('private-cleanup-detail', json.dumps(c.card))

    def test_final_accounting_preserves_stop_and_keeps_ledger_on_summary_error(self):
        self.addCleanup(offline_router()[0].close)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ledger = root/'ledger'
            value = {'terminal_stop':'codex_login_expired','events':[], 'calls':0, 'cost':0}
            ledger.write_text(json.dumps(value))
            c = SimpleNamespace(work=root, ledger=ledger, stopped=True,
                card={'terminal_stop':'codex_login_expired'})
            with patch.object(run, 'update_case_budget', side_effect=ValueError('private')):
                run.finalize_accounting(c)
            self.assertEqual(c.card['terminal_stop'], 'codex_login_expired')
            self.assertEqual(json.loads((root/'continuation-budget.json').read_text()), value)
            self.assertEqual(c.card['cleanup_errors'], [{'stage':'budget_summary','error':'ValueError'}])


if __name__ == '__main__': unittest.main()
