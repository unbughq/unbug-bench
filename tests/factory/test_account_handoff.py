"""Replay canary 6's public policy/launch with a synthetic Go limit; no model calls."""
import base64
import copy
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'tests/factory')]
import account_handoff as handoff
import restart
import model_router
import time
import uuid

FIXTURE = Path(__file__).with_name('fixtures') / 'opencode-failover'


def bundle():
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        for name in ('claude-token', 'claude-factory-token-2', 'opencode-go-key', 'opencode-go-key-2',
                     'openrouter-key', 'codex-auth.json'):
            value = b'synthetic fixture only:' + name.encode()
            if name == 'codex-auth.json':
                value = json.dumps({'tokens':{'access_token':'e30.eyJleHAiOjQxMDI0NDQ4MDB9.synthetic'},
                                    'last_refresh':'2026-10-28T00:00:00Z'}).encode()
            member = tarfile.TarInfo(name); member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
    return output.getvalue()


class AccountHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.card = json.loads((FIXTURE / 'input-scorecard.json').read_text())
        self.policy = next(iter(json.loads((FIXTURE / 'policy.restore.json').read_text())['jobs'].values()))
        launch = json.loads((FIXTURE / 'launch.json').read_text())
        self.env = {**launch['environment'], 'FACTORY_ACCOUNT_POLICY': json.dumps(self.policy)}
        self.stop = 'provider_limit:opencode-go/glm-5.3-flash'
        self.card['terminal_stop'] = 'provider_wait'
        self.card['continuation_budget']['terminal_stop'] = self.stop
        self.card['provider_wait'] = dict(wait_id=str(uuid.uuid4()), reason='quota', route='opencode-go/glm-5.3-flash', account='opencode-go-key-2', evidence='denied_before_work', retry_after=model_router.utc(time.time()+60), batch_deadline=model_router.utc(time.time()+86400))
        self.card['continuation_budget']['active'] = None
        archive = self.root / (self.card['case'] + '.checkpoint.tar.gz.age')
        archive.write_bytes(b'synthetic ciphertext; real public policy and ledger shape')
        self.card['sha256'] = handoff.hashlib.sha256(archive.read_bytes()).hexdigest()
        self.path = self.root / (self.card['case'] + '.scorecard.json')
        self.path.write_text(json.dumps(self.card))
        self.state = self.root / 'worker.accounts.json'
        self.held = set(handoff.ACCOUNTS['opencode'].values()) | set(handoff.ACCOUNTS['claude'].values())
        # Arguments are the real restore-10 runner allowances; host-only flags do not change restart limits.
        self.args = shlex.join(self.policy['args'][1:])

    def prepare(self, retries=0, held=None):
        return handoff.prepare(self.path, self.state, retries, 28800, self.args,
                               self.held if held is None else held)

    def test_real_canary_stop_selects_only_account_2_and_short_delay(self):
        with patch.dict(os.environ, self.env), patch.object(handoff.subprocess, 'run') as push:
            self.assertAlmostEqual(restart.plan(self.path, 0, 28800, self.args)[1], 60, delta=1)
            retries = int(json.loads((FIXTURE / 'launch-state.json').read_text())['autoresumes'])
            case, delay, seed = self.prepare(retries=retries)
            self.assertEqual((case, seed), (self.card['case'], self.card['seed'])); self.assertAlmostEqual(delay, 60, delta=1)
            handoff.apply(self.path, self.state, 'synthetic-owned-worker', bundle())
            args, kwargs = push.call_args
            self.assertEqual(args[0][-3:], ['--merge', 'synthetic-owned-worker', 'opencode-go-key-2'])
            with tarfile.open(fileobj=io.BytesIO(base64.b64decode(kwargs['input']))) as archive:
                self.assertEqual(archive.getnames(), ['opencode-go-key-2'])
            exports = handoff.exports(self.state)
            self.assertIn('export OPENCODE_SECRET_NAME=opencode-go-key-2', exports)
            self.assertIn('export OPENCODE_API_KEY=$(cat /dev/shm/secrets/opencode-go-key-2)', exports)
            self.assertEqual(json.loads(self.state.read_text())['accounts']['opencode'], 2)
            self.assertNotIn('synthetic fixture only', self.state.read_text())

    def test_waits_do_not_consume_restart_allowance(self):
        with patch.dict(os.environ, self.env):
            for retries in (0, 1, 3, 100):
                self.assertAlmostEqual(self.prepare(retries=retries)[1], 60, delta=1)

    def test_no_key_or_authorization_uses_normal_backoff(self):
        for model in ('opencode/deepseek-v4.1-flash-free', 'opencode-go/deepseek-v4.1-flash',
                      'openrouter/deepseek/deepseek-v4.1-flash'):
            card = {**self.card, 'terminal_stop': 'provider_limit:' + model}
            state = handoff.initial_state(card, self.policy)
            self.assertEqual(state['limited'], {})
            self.assertIsNone(handoff.choose(card, state, self.policy, self.held))
            self.assertEqual(handoff.launch_accounts(card, self.policy, {}, self.held)[0], 1)
        for held, allowed in (({'opencode-go-key'}, [1, 2]), (self.held, [1])):
            with patch.dict(os.environ, {**self.env, 'FACTORY_ACCOUNT_POLICY': json.dumps({'opencode_accounts': allowed})}):
                self.assertAlmostEqual(self.prepare(held=held)[1], 60, delta=1)

    def test_claude_handoff_and_existing_reset_window(self):
        self.card['continuation_budget']['terminal_stop'] = 'provider_limit:claude/claude-opus-5-5'
        self.card['provider_wait'].update(route='claude/claude-opus-5-5', account='claude-factory-token-2')
        self.card['continuation_budget']['claude_resets_at'] = 9999999999
        self.path.write_text(json.dumps(self.card))
        with patch.dict(os.environ, self.env), patch.object(handoff.subprocess, 'run') as push:
            self.assertAlmostEqual(self.prepare()[1], 60, delta=1)
            handoff.apply(self.path, self.state, 'synthetic-worker', bundle())
            self.assertEqual(push.call_args.args[0][-1], 'claude-factory-token-2')
            self.assertIn('CLAUDE_CODE_OAUTH_TOKEN=$(cat /dev/shm/secrets/claude-factory-token-2)', handoff.exports(self.state))

    def test_uncertain_push_is_reserved_and_not_repeated(self):
        with patch.dict(os.environ, self.env), patch.object(handoff.subprocess, 'run', side_effect=RuntimeError('transport')) as push:
            self.prepare()
            with self.assertRaises(RuntimeError): handoff.apply(self.path, self.state, 'synthetic-worker', bundle())
            with self.assertRaises(FileExistsError): handoff.apply(self.path, self.state, 'synthetic-worker', bundle())
            self.assertEqual(push.call_count, 1)

    def test_parked_resume_uses_same_policy_single_secret_and_delay(self):
        import key_holder
        card_path = self.root / 'sealed' / self.path.name
        card_path.parent.mkdir(); shutil.copy2(self.path, card_path)
        shutil.copy2(self.root / (self.card['case'] + '.checkpoint.tar.gz.age'), card_path.parent / (self.card['case'] + '.checkpoint.tar.gz.age'))
        job = {**self.policy, 'card': card_path.name}
        pushes = []
        def run(args, **kwargs):
            if args[0] == 'age': return handoff.subprocess.CompletedProcess(args, 0, stdout=bundle())
            if '--merge' in args:
                with tarfile.open(fileobj=io.BytesIO(base64.b64decode(kwargs['input']))) as archive:
                    pushes.append(archive.getnames())
            if args[0].endswith('resume-in-place.sh'):
                self.assertEqual(json.loads(kwargs['env']['FACTORY_ACCOUNT_STATE'])['accounts']['opencode'], 1)
                self.assertEqual(args[args.index('--case-budget') + 1], '70')
                self.assertEqual(args[args.index('--rounds') + 1], '9')
                self.assertEqual(args[args.index('--builder') + 1], self.policy['roles']['writer']['model'])
            return handoff.subprocess.CompletedProcess(args, 0)
        with patch.dict(os.environ, self.env), patch.object(handoff, '__file__', str(self.root / 'factory/account_handoff.py')), \
             patch.object(key_holder, 'CONTROL_HOME', self.root / 'control'), \
             patch.object(key_holder, 'policy_load', return_value={'jobs': {'canary': job}}), \
             patch.object(handoff.subprocess, 'run', side_effect=run), \
             patch.object(handoff.subprocess, 'check_output', return_value=json.dumps({'labels': {'expires': handoff.time.time() + 28800, 'parked': self.card['case']}}).encode()), \
             patch.object(handoff.time, 'sleep') as sleep, patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(b'synthetic identity'))):
            self.assertEqual(handoff.parked(self.root / 'policy.json', 'canary', 'owned-parked', []), 0)
            sleep.assert_not_called()
        self.assertEqual(pushes, [])

    def test_historical_limits_are_not_current_health(self):
        card = {**self.card, 'account_handoffs': [{'provider':'opencode','from':1,'to':2}], 'terminal_stop':'provider_limit:opencode-go/glm-5.3-flash'}
        state = handoff.initial_state(card, self.policy, {'opencode': 2, 'claude': 1})
        self.assertEqual(state['limited'], {})
        self.assertEqual(state['history'], card['account_handoffs'])
        self.assertIsNone(handoff.choose(card, state, self.policy, self.held))

    def test_fresh_launch_keeps_collected_accounts_unless_explicitly_overridden(self):
        state = handoff.initial_state(self.card, self.policy, {'opencode': 2, 'claude': 2})
        card = {**self.card, 'provider_accounts': state['accounts'], 'account_handoffs': state['history']}
        opencode, claude, retained = handoff.launch_accounts(card, self.policy, {}, self.held)
        self.assertEqual((opencode, claude), (2, 2))
        self.assertEqual(retained['limited'], {})
        overridden = handoff.launch_accounts(card, self.policy, {'opencode_account': 1}, self.held)
        self.assertEqual(overridden[:2], (1, 2))
        paused = {**self.card, 'terminal_stop': 'paused', 'provider_accounts': {'opencode': 1, 'claude': 2}}
        explicit_start = handoff.launch_accounts(paused, {**self.policy, 'initial_accounts': {'opencode': 2}}, {}, self.held)
        self.assertEqual(explicit_start[:2], (2, 2))

    def test_planner_cli_distinguishes_retry_refusal_from_bad_checkpoint(self):
        self.card['terminal_stop'] = self.stop; self.path.write_text(json.dumps(self.card))
        args = [sys.executable, '-B', str(ROOT / 'factory/account_handoff.py'), 'plan',
                '--card', str(self.path), '--state', str(self.state), '--remaining', '28800',
                '--retries', '3', '--args=' + self.args]
        result = handoff.subprocess.run(args, text=True, input=' '.join(self.held), capture_output=True,
                                        env={**os.environ, **self.env})
        self.assertEqual(result.returncode, 1)
        self.card['sha256'] = '0' * 64; self.path.write_text(json.dumps(self.card))
        result = handoff.subprocess.run(args, text=True, input=' '.join(self.held), capture_output=True,
                                        env={**os.environ, **self.env})
        self.assertEqual(result.returncode, 2)

    def test_worker_loader_keeps_key_bytes_out_of_argv_and_preserves_json(self):
        home = self.root / 'worker'; (home / 'sealed').mkdir(parents=True)
        secrets = self.root / 'ram'; secrets.mkdir()
        for label in ('opencode-go-key-2', 'claude-token', 'openrouter-key'):
            (secrets / label).write_text('synthetic-' + label)
        state = handoff.initial_state(self.card, self.policy, {'opencode': 2, 'claude': 1})
        with patch.object(handoff.Path, 'home', return_value=home), patch.object(handoff, 'SECRETS', secrets), \
             patch.object(handoff.subprocess, 'Popen') as spawn:
            handoff.worker_resume(self.card['case'], 'a' * 64, ['--case-budget', '70', '--rounds', '9'], json.dumps(state))
        argv = spawn.call_args.args[0]; env = spawn.call_args.kwargs['env']
        self.assertEqual(argv[0], 'python3')
        self.assertFalse(any('synthetic-' in arg for arg in argv))
        self.assertEqual(env['OPENCODE_API_KEY'], 'synthetic-opencode-go-key-2')
        self.assertEqual(env['OPENCODE_SECRET_NAME'], 'opencode-go-key-2')
        self.assertEqual(json.loads(env['FACTORY_ACCOUNT_STATE']), state)
        self.assertEqual(argv[-4:], ['--case-budget', '70', '--rounds', '9'])

    def test_parked_failure_status_reaches_entrypoint(self):
        with patch.object(sys, 'argv', ['handoff', 'parked', '--policy', 'policy', '--job', 'canary', '--worker', 'owned']), \
             patch.object(handoff, 'parked', return_value=7):
            self.assertEqual(handoff.main(), 7)

    def test_exhausted_monitor_collects_and_deletes_without_keep(self):
        from test_control_resume import ControlResumeTests
        controller = ControlResumeTests(); controller.setUp(); self.addCleanup(controller.doCleanups)
        fixture = controller.f
        shutil.copy2(ROOT / 'factory/account_handoff.py', fixture.root / 'factory/account_handoff.py')
        job = json.loads((controller.state / 'launch.json').read_text())
        job['environment']['FACTORY_ACCOUNT_POLICY'] = json.dumps(self.policy)
        (controller.state / 'launch.json').write_text(json.dumps(job))
        fixture.card['terminal_stop'] = fixture.card['continuation_budget']['terminal_stop'] = self.stop
        fixture.save_card()
        (controller.state / (fixture.worker + '.autoresumes')).write_text('3')
        controller.run_resume()
        self.assertFalse((controller.state / (fixture.worker + '.keep')).exists())
        controller.assert_finished(handoffs=0, restarts=0)

    def test_same_worker_monitor_survives_controller_resume_and_deletes(self):
        from test_control_resume import ControlResumeTests
        f = ControlResumeTests(); f.setUp(); self.addCleanup(f.doCleanups)
        fixture = f.f
        for name in ('account_handoff.py',): shutil.copyfile(ROOT / 'factory' / name, fixture.root / 'factory' / name)
        shutil.copyfile(ROOT / 'bin/push-secrets', fixture.root / 'bin/push-secrets')
        (fixture.root / 'bin/push-secrets').chmod(0o755)
        (fixture.base / 'bundle').write_bytes(bundle())
        job = json.loads((f.state / 'launch.json').read_text())
        job['environment'].update({k: v for k, v in self.env.items() if k in ('OPENCODE_SECRET_NAME', 'CLAUDE_SECRET_NAME', 'FACTORY_ACCOUNT_POLICY')})
        (f.state / 'launch.json').write_text(json.dumps(job))
        fixture.card['terminal_stop'] = fixture.card['continuation_budget']['terminal_stop'] = self.stop
        fixture.save_card()
        # Advance only the synthetic retry deadline. Real planner still asserts 60s above.
        (f.state / (fixture.worker + '.retry-at')).write_text('1')
        secrets = fixture.remote / 'secrets'; secrets.mkdir()
        for label in ('claude-token', 'opencode-go-key', 'openrouter-key', 'codex-auth.json'): (secrets / label).write_text('synthetic fixture only')
        (fixture.remote / '.codex').mkdir()
        worker = fixture.root / 'bin/worker-call'
        code = worker.read_text()
        code = '\n'.join(line for line in code.splitlines() if not line.startswith('if a[0]=="exec": cmd=cmd[:cmd.index')) + '\n'
        code = code.replace('env={**os.environ,', 'if cmd.startswith("sudo loginctl"): sys.exit()\ncmd=cmd.replace("/dev/shm/secrets", str(remote/"secrets"))\nenv={**os.environ,')
        worker.write_text(code)
        runner = fixture.remote / 'factory/run.py'
        runner.write_text(runner.read_text() + '\nimport os\n(h/"account-observed.json").write_text(json.dumps({"label":os.environ["OPENCODE_SECRET_NAME"],"key_matches_selected_account":os.environ["OPENCODE_API_KEY"] == "synthetic fixture only:opencode-go-key-2","state":json.loads(os.environ["FACTORY_ACCOUNT_STATE"])}))\n')
        process = f.start()
        self.addCleanup(lambda: f.stop(process))
        try:
            _, error = process.communicate('synthetic identity\n', timeout=60)
        except handoff.subprocess.TimeoutExpired:
            f.stop(process); _, error = process.communicate(timeout=5)
            self.fail('same-worker handoff monitor timed out: ' + error)
        self.assertEqual(process.returncode, 0, error)
        observed = json.loads((fixture.remote / 'account-observed.json').read_text())
        self.assertEqual(observed['label'], 'opencode-go-key')
        self.assertFalse(observed['key_matches_selected_account'])
        self.assertEqual(observed['state']['accounts']['opencode'], 1)
        self.assertEqual(sorted(p.name for p in secrets.iterdir()), ['claude-token', 'codex-auth.json', 'opencode-go-key', 'openrouter-key'])
        self.assertFalse((f.state / (fixture.worker + '.accounts.json')).exists(), 'no account scheduler journal is created')
        f.assert_finished(handoffs=0, restarts=1)


if __name__ == '__main__': unittest.main()
