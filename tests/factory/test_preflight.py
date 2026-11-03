"""Live preflight (docs/designs/preflight.md), offline.

Real artifacts: the retained practice manifest (factory/batches/b-plumbing-practice-2.json)
bound into the HolderTests practice policy and release fixture, the real router
(router_delivery_support: model_router.Server over verified TLS with a real 0600
client config), the retained Boat list/billing receipts, and the installed
`boat 1.0.87` label from docs/reports/practice-run-20261102.md. age bundles are
encrypted with the real age CLI to an identity made for the test. The Codex JWT
is AUTHORED for these tests: the practice report kept labels only, no token.
OpenRouter /credits, R2 and SSH are doubled at their transport edge only.
"""
import base64
from contextlib import ExitStack
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import batch_holder as holder
import codex_login
import model_router
import model_runtime
import practice_preflight as preflight
import key_holder
from router_delivery_support import router
# Modules, not classes: importing a TestCase class would rerun its tests here.
import test_batch_holder as holder_tests
import test_practice_readiness as readiness_tests

FIXTURES = ROOT / 'tests/factory/fixtures/isolation-timeouts'
REPORT = (ROOT / 'docs/reports/practice-run-20261102.md').read_text()
INSTALLED = re.search(r'Installed CLI label: (boat [0-9.]+)\.', REPORT).group(1)
RECORD = json.loads((ROOT / preflight.MANIFEST).read_text())
PRACTICE_ARGS = RECORD['jobs']['practice']['args']


def jwt(exp):
    """AUTHORED Codex login: no real token exists to replay."""
    payload = base64.urlsafe_b64encode(json.dumps({'exp': exp}).encode()).decode().rstrip('=')
    return {'tokens': {'access_token': 'e30.' + payload + '.authored', 'refresh_token': 'authored-refresh'},
            'last_refresh': '2026-11-02T00:00:00Z'}


def tar(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name); member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return stream.getvalue()


def bundle(**changes):
    files = {'claude-factory-token-2': b'authored', 'claude-token': b'authored', 'opencode-go-key': b'authored',
             'openrouter-key': b'authored-openrouter\n', 'codex-auth.json': json.dumps(jwt(1)).encode(),
             'r2-env': b'R2_ACCOUNT_ID=authored\nR2_ACCESS_KEY_ID=authored\nR2_SECRET_ACCESS_KEY=authored\nR2_BUCKET=authored\n'}
    files.update(changes)
    return {k: v for k, v in files.items() if v is not None}


@unittest.skipUnless(shutil.which('age') and shutil.which('openssl'), 'age and openssl required')
class DispatchHoldTests(unittest.TestCase):
    """Phase B through the real batch_holder.dispatch, against the retained practice policy."""
    setUpBase = holder_tests.HolderTests.setUpBase
    freeze = holder_tests.HolderTests.freeze
    answers = holder_tests.HolderTests.answers
    ops = holder_tests.HolderTests.ops
    practice_policy = readiness_tests.PracticeTests.practice_policy

    def setUp(self):
        holder_tests.HolderTests.setUp(self)
        self.policy = self.practice_policy(RECORD)
        self.directory = self.home / 'batches' / RECORD['id']
        (self.root / 'bin').mkdir(exist_ok=True)
        shutil.copy2(ROOT / 'bin/r2-presign', self.root / 'bin/r2-presign')  # the real signer
        keys = self.root / 'keys'; keys.mkdir()
        for name in ('control', 'other'):
            subprocess.run(['age-keygen', '-o', str(keys / name)], check=True, capture_output=True)
        self.identity = (keys / 'control').read_bytes()
        self.recipient = subprocess.check_output(['age-keygen', '-y', str(keys / 'control')], text=True).strip()
        self.other = subprocess.check_output(['age-keygen', '-y', str(keys / 'other')], text=True).strip()
        self.policy.update(code_sha256='fingerprint', path='/usr/bin:/bin', recipient=self.recipient)
        self.secrets = self.root / 'secrets.age'
        self.tls = tempfile.TemporaryDirectory(); self.addCleanup(self.tls.cleanup)
        context = router(self.tls.name); self.client, self.store, _ = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def write_bundle(self, files, recipient=None):
        subprocess.run(['age', '-r', recipient or self.recipient, '-o', str(self.secrets)], input=tar(files), check=True)

    def dispatch(self, *, credit=Decimal('11.3637556'), r2=404, client=None):
        op = holder.reserve(self.policy, self.root, self.home, 'practice', None)
        real, real_popen, spawned, probes = subprocess.run, subprocess.Popen, [], []
        def run(argv, **kwargs):
            if argv[0] in ('age', 'age-keygen'): return real(argv, **kwargs)
            if argv[1:] == ['list', '--json']:
                return SimpleNamespace(stdout=(FIXTURES / 'list.json').read_bytes())
            raise AssertionError(argv)
        def popen(argv, **kwargs):
            if argv[0] in ('age', 'age-keygen'): return real_popen(argv, **kwargs)
            self.assertTrue(self.ops()[op['operation_id']]['dispatch_started'])
            spawned.append(kwargs['env']['CLAUDE_SECRET_NAME'])
            return SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 0)
        def available(token=None):
            probes.append(token)
            return credit
        log = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, UNBUG_SECRETS_FILE=str(self.secrets),
                                           UNBUG_ROUTER_CLIENT_FILE=str(client or self.client)))
            stack.enter_context(patch.object(key_holder, 'fingerprint', return_value='fingerprint'))
            stack.enter_context(patch.object(holder.subprocess, 'run', side_effect=run))
            stack.enter_context(patch.object(holder.subprocess, 'Popen', side_effect=popen))
            stack.enter_context(patch.object(model_router, 'available_credit', side_effect=available))
            stack.enter_context(patch.object(preflight, '_status', return_value=r2))
            stack.enter_context(patch.object(sys, 'stderr', log))
            try: result = holder.dispatch(self.policy, self.root, self.home, op['operation_id'], self.identity)
            except ValueError as error: result = error
        return result, self.ops()[op['operation_id']], spawned, log.getvalue(), probes

    def assertHeld(self, outcome, reason):
        result, op, spawned, log, _ = outcome
        self.assertEqual(result, holder.TEMPFAIL)
        self.assertEqual((op['state'], op['dispatch_started'], op['incident']), ('pending', False, None))
        self.assertEqual(spawned, [])
        self.assertIn('preflight hold: ', log)
        self.assertIn(reason, log)
        self.assertNotIn('authored-openrouter', log)
        return log

    def test_all_checks_pass_then_dispatch_starts(self):
        self.write_bundle(bundle())
        result, op, spawned, log, probes = self.dispatch()
        self.assertEqual((result, op['dispatch_started'], op['incident']), (0, True, None))
        self.assertEqual(spawned, ['claude-factory-token-2'])  # the retained manifest's initial account
        self.assertEqual(probes, ['authored-openrouter'])  # the bundle's key, never os.environ
        self.assertNotIn('OPENROUTER_API_KEY', os.environ)
        self.assertEqual(log, '')

    def test_undecryptable_bundle_holds_pending(self):
        self.write_bundle(bundle(), recipient=self.other)  # stop 8: refreshed for a different identity
        self.assertHeld(self.dispatch(), 'credentials: bundle not decryptable')

    def test_missing_label_holds_pending(self):
        self.write_bundle(bundle(**{'claude-factory-token-2': None, 'openrouter-key': None}))
        log = self.assertHeld(self.dispatch(), 'credentials: missing claude-factory-token-2 openrouter-key')
        self.assertIn('openrouter', log.split('credentials: missing claude-factory-token-2 openrouter-key', 1)[1])

    def test_pack_failure_holds_pending(self):
        config = json.loads(self.client.read_text()); config['token'] = 'wrong'
        bad = self.root / 'bad-client.json'; bad.write_text(json.dumps(config)); bad.chmod(0o600)
        self.write_bundle(bundle())
        self.assertHeld(self.dispatch(client=bad), 'preflight hold: router\n')

    def test_none_credit_holds_pending(self):
        self.write_bundle(bundle())
        self.assertHeld(self.dispatch(credit=None), 'preflight hold: openrouter\n')

    def test_nonzero_outstanding_holds_pending(self):
        value = json.loads(self.client.read_text())
        with patch.dict(os.environ, FACTORY_ROUTER_URL=value['url'], FACTORY_ROUTER_TOKEN=value['token'],
                        FACTORY_ROUTER_CA_FILE=str(Path(self.tls.name) / 'cert.pem')):
            lease = model_router._rpc('acquire', dict(id=uuid.uuid4().hex, model='openrouter/minimax/minimax-m3.1-flash',
                                      accounts=['openrouter-key'], role='writer', deadline=time.time() + 3600, paid_protocol=1))
            model_router._rpc('start', {'lease_id': lease['lease_id']})
            self.assertTrue(model_router._rpc('paid_reserve', dict(lease_id=lease['lease_id'], request_id=uuid.uuid4().hex))['granted'])
            self.assertNotEqual(model_router._rpc('status', {})['paid']['outstanding_usd'], '0.000000000')
        self.write_bundle(bundle())
        self.assertHeld(self.dispatch(), 'preflight hold: router\n')

    def test_r2_refusal_holds_and_every_failure_is_named(self):
        self.write_bundle(bundle(**{'opencode-go-key': None}))
        self.assertHeld(self.dispatch(credit=None, r2=403), 'credentials: missing opencode-go-key; openrouter; r2')

    def test_recipient_mismatch_still_marks_failed(self):
        self.policy['recipient'] = self.other
        self.write_bundle(bundle())
        result, op, spawned, log, _ = self.dispatch()
        self.assertIsInstance(result, ValueError)
        self.assertEqual((op['state'], op['incident'], op['dispatch_started']), ('failed', 'preflight_refused', False))
        self.assertEqual(spawned, [])


class CheckUnitTests(unittest.TestCase):
    def test_credit_reads_given_token_not_environment(self):
        seen = []
        class Opener:
            def open(self, request, timeout):
                seen.append(request.get_header('Authorization'))
                raise OSError('offline')
        with patch.dict(os.environ, OPENROUTER_API_KEY='environment-key'), \
             patch.object(model_router.urllib.request, 'build_opener', return_value=Opener()):
            self.assertIsNone(model_router.available_credit('bundle-key'))
            self.assertIsNone(model_router.available_credit(''))  # an empty bundle key never falls back
            model_router.available_credit()
        self.assertEqual(seen, ['Bearer bundle-key', 'Bearer environment-key'])

    def test_r2_signs_one_get_of_the_absent_key(self):
        env = bundle()['r2-env'].decode()
        urls = []
        for code, passes in ((404, True), (200, True), (403, False), (401, False)):
            with self.subTest(code=code), patch.object(preflight, '_status', side_effect=lambda u: urls.append(u) or code):
                if passes: preflight.r2(ROOT, env)
                else:
                    with self.assertRaises(ValueError): preflight.r2(ROOT, env)
        self.assertTrue(all('/authored/preflight/absent?' in u and 'X-Amz-Signature=' in u for u in urls))
        with patch.object(preflight, '_status', side_effect=OSError('transport')), self.assertRaises(OSError):
            preflight.r2(ROOT, env)
        with self.assertRaises(ValueError): preflight.r2(ROOT, 'R2_BUCKET=only\n')

    def test_worker_names_match_launch_selection(self):
        names = ['claude-token', 'claude-factory-token-2', 'claude-token-2', 'opencode-go-key', 'opencode-go-key-2',
                 'r2-env', '._codex-auth.json', 'codex-auth.json', 'openrouter-key']
        self.assertEqual(preflight.worker_names(names, 'claude-factory-token-2', 'opencode-go-key'),
                         ['claude-factory-token-2', 'opencode-go-key', 'codex-auth.json', 'openrouter-key'])


class CodexGateTests(unittest.TestCase):
    def gate(self, args, valid=False, ttl='1'):
        stream = tar({'codex-auth.json': json.dumps(jwt(9999999999 if valid else 1)).encode()})
        return subprocess.run([sys.executable, '-B', str(ROOT / 'factory/codex_login.py'), '--ttl-hours', ttl,
                               '--job-args', '--', *args], input=stream, capture_output=True)

    def test_practice_args_skip_the_gate(self):
        self.assertFalse(codex_login.codex_role(PRACTICE_ARGS))
        result = self.gate(PRACTICE_ARGS)
        self.assertEqual((result.returncode, result.stderr), (0, b''))

    def test_rotation_default_resolves_codex_and_enforces(self):
        args = [a for a in PRACTICE_ARGS]
        i = args.index('--strong-calibrator'); del args[i:i + 2]
        args += ['--rotation-table', 'rotation-3writers.json']
        parsed, _ = codex_login.job_parser().parse_known_args(args)
        parsed.batch_release_sha256 = 'resolution-only'
        c = SimpleNamespace(args=parsed, card={})
        model_runtime.select_models(c, log=lambda *_: None)  # resolves; not an unparseable fallback
        self.assertEqual(c.card['roles']['strong_calibrator']['model'], 'codex/gpt-6.1-sol')
        self.assertTrue(codex_login.codex_role(args))
        self.assertEqual(self.gate(args).returncode, 1)
        self.assertEqual(self.gate(args, valid=True).returncode, 0)
        with patch.dict(os.environ, FACTORY_ROTATION='rotation.json'):
            self.assertTrue(codex_login.codex_role(args[:-2]))

    def test_unparseable_args_enforce(self):
        for args in (['--rotation-slot', '99'], ['--rotation-slot'], ['--strong-calibrator', 'unknown/route']):
            with self.subTest(args=args):
                self.assertTrue(codex_login.codex_role(args))
                result = self.gate(args)
                self.assertEqual(result.returncode, 1)
                self.assertIn(b'codex_login_expired', result.stderr)
                self.assertNotIn(b'authored-refresh', result.stdout + result.stderr)

    def test_launcher_gate_passes_its_args(self):
        launch = (ROOT / 'factory/launch.sh').read_text()
        body = launch[launch.index('codex_login_gate() {'):]
        body = body[:body.index('\n}\n')]
        self.assertIn('eval "set -- $args"', body)
        self.assertIn('--job-args -- "$@"', body)
        self.assertEqual(launch.count('codex_login_gate'), 4)  # definition plus the three call sites
        # The real shell function, with the launcher's own quoting of practice args.
        quoted = ' '.join("'" + a.replace("'", "'\\''") + "'" for a in PRACTICE_ARGS[1:])
        script = ('here=' + str(ROOT / 'factory') + '; ttl_hours=8; args=' + json.dumps(quoted) + '\n' +
                  'secrets_b64=$(base64 < "$1")\n' + body + '\n}\ncodex_login_gate\n')
        with tempfile.NamedTemporaryFile() as stream:
            stream.write(tar({'codex-auth.json': json.dumps(jwt(1)).encode()})); stream.flush()
            self.assertEqual(subprocess.run(['/bin/sh', '-c', script, 'sh', stream.name]).returncode, 0)
            script = script.replace("'--strong-calibrator' 'claude/claude-opus-4-5-20251101:compact'", '')
            self.assertEqual(subprocess.run(['/bin/sh', '-c', script, 'sh', stream.name], capture_output=True).returncode, 1)


class LiveReportTests(unittest.TestCase):
    """Phase A with root SSH doubled; command outputs are the retained receipts."""
    SERVER = dict(id=7, public_net={'ipv4': {'ip': '192.0.2.7'}})

    def ssh(self, refuse_root=False, installed=INSTALLED, names=None):
        names = names if names is not None else ['./' + n for n in bundle()]
        calls, real = [], subprocess.run
        def run(argv, **kwargs):
            if argv[0] == 'git': return real(argv, **kwargs)
            self.assertEqual(argv[0], 'ssh')
            self.assertIn('BatchMode=yes', argv)
            self.assertIn('IdentitiesOnly=yes', argv)
            self.assertEqual(argv[-2], 'root@192.0.2.7')
            command = argv[-1]; calls.append(command)
            out, code = '', 0
            if command == 'true': code = 255 if refuse_root else 0
            elif command.endswith('/usr/local/bin/boat --version'): out = installed + '\n'
            elif command.endswith('bin/boat-call list --json'): out = (FIXTURES / 'list.json').read_text()
            elif command.endswith('bin/boat-call billing --json'): out = (FIXTURES / 'billing.json').read_text()
            elif 'tar -tf -' in command: out = '\n'.join(names) + '\n'
            else: raise AssertionError(command)
            if command != 'true': self.assertTrue(command.startswith(preflight.VM_USER))
            return subprocess.CompletedProcess(argv, code, out, '')
        return patch.object(preflight.subprocess, 'run', side_effect=run), calls

    def live(self, **kwargs):
        double, calls = self.ssh(**kwargs)
        with double, patch.object(preflight, 'verify_bundle'):  # offline pins are covered elsewhere
            report = preflight.check(ROOT, Path('authored-bundle'), self.SERVER)
        return report, {r['id']: r for r in report['preflight']}, calls

    def test_three_failures_all_reported(self):
        report, rows, calls = self.live(refuse_root=True, names=['./' + n for n in bundle() if n != 'openrouter-key'])
        failed = {k: r['reason'] for k, r in rows.items() if r['status'] == 'fail'}
        self.assertEqual(failed, {'deploy_access': 'root_ssh_refused',
                                  'boat_cli': 'installed boat 1.0.87, pinned boat 1.0.85',
                                  'credentials': 'missing openrouter-key'})
        self.assertEqual(rows['boat_wallet']['status'], 'pass')  # retained $4.17171 receipt, cap $5
        self.assertEqual(rows['login_lifetimes'], dict(id='login_lifetimes', status='pass', reason='no_codex_role'))
        self.assertEqual(preflight.code(report), 1)
        self.assertNotIn('boat-call list', ' '.join(calls))  # a refused version is never listed with

    def test_missing_decisions_need_founder_and_exit_3(self):
        report, rows, _ = self.live(installed='boat 1.0.85')
        self.assertFalse(preflight.decisions_file(ROOT).exists())
        self.assertEqual(rows['founder_decisions'], dict(id='founder_decisions', status='needs_founder',
                         reason='missing topup_off accounts_unverified_accepted router_ram_openrouter'))
        self.assertTrue(all(r['status'] == 'pass' for k, r in rows.items() if k != 'founder_decisions'))
        self.assertEqual(preflight.code(report), 3)

    def test_recorded_decisions_pass_and_change_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'factory/batches').mkdir(parents=True)
            path = preflight.decisions_file(root)
            self.assertEqual(preflight.founder_decisions(root), list(preflight.DECISIONS[RECORD['id']]))
            rows = [dict(id=d, text='authored', recorded_utc='2026-11-03T00:00:00+00:00') for d in preflight.DECISIONS[RECORD['id']][:2]]
            path.write_text(json.dumps(rows))
            self.assertEqual(preflight.founder_decisions(root), ['router_ram_openrouter'])
            path.write_text(json.dumps(rows + [dict(rows[0], id='router_ram_openrouter')]))
            self.assertEqual(preflight.founder_decisions(root), [])
            for bad in ([dict(rows[0], recorded_utc='2026-11-03T00:00:00')], [dict(rows[0], extra=1)], {}):
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError): preflight.founder_decisions(root)
        source = (ROOT / 'factory/practice_preflight.py').read_text()
        self.assertIn('decisions_sha256=digest(decisions_file(root))', source)

    def test_unresolved_server_fails_every_ssh_check(self):
        with patch.object(preflight, 'verify_bundle'):
            report = preflight.check(ROOT, Path('authored-bundle'), None)
        rows = {r['id']: r['status'] for r in report['preflight']}
        self.assertEqual(rows, dict(founder_decisions='needs_founder', deploy_access='fail', boat_cli='fail',
                                    boat_wallet='fail', credentials='fail', login_lifetimes='pass'))
        self.assertEqual(preflight.code(report), 1)


if __name__ == '__main__': unittest.main()
