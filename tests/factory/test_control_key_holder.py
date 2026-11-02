"""Offline control identities; only generated keys, temp bundles and local fakes."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import hashlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock

HERE = (Path(__file__).resolve().parents[2] / "factory")


@unittest.skipUnless(shutil.which('age') and shutil.which('age-keygen'),
                     'age and age-keygen are required for synthetic control-key tests')
class ControlKeyHolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pkg2-', dir='/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        for name in ('factory', 'bin', 'home', 'sealed'):
            (self.root/name).mkdir()
        for name in ('worker_secrets.py', 'key_holder.py', 'recovery.py', 'control_resume.py', 'launch.sh', 'account_handoff.py', 'codex_login.py', 'launch_manifest.py'):
            shutil.copyfile(HERE/name, self.root/'factory'/name)
        shutil.copyfile(HERE.parent/'bin/setup-secrets', self.root/'bin/setup-secrets')
        setup = self.root/'bin/setup-secrets'
        # This step never prompts; omit only terminal restoration in the fixture's EXIT cleanup.
        setup.write_text(setup.read_text().replace('stty echo < /dev/tty 2>/dev/null; ', ''))
        self.keys = []
        self.recipients = []
        for name in ('founder', 'control', 'other'):
            path = self.root/name
            subprocess.run(['age-keygen', '-o', str(path)], check=True, capture_output=True)
            path.chmod(0o600)
            self.keys.append(path)
            self.recipients.append(subprocess.check_output(['age-keygen', '-y', str(path)], text=True).strip())
        self.key = next(v for v in self.keys[1].read_bytes().splitlines() if v.startswith(b'AGE-SECRET-KEY-')) + b'\n'
        (self.root/'factory/run.py').write_text('FOUNDER_RECIPIENT = "' + self.recipients[0] + '"\n')
        self.bundle = self.root/'bundle.age'
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as archive:
            for name in ('claude-token', 'codex-auth.json', 'openrouter-key', 'opencode-go-key', 'statements-key'):
                value = self.keys[2].read_bytes() if name == 'statements-key' else b'synthetic credential'
                if name == 'codex-auth.json':
                    value = json.dumps({'tokens':{'access_token':'e30.eyJleHAiOjQxMDI0NDQ4MDB9.synthetic'},
                                        'last_refresh':'2026-10-28T00:00:00Z'}).encode()
                info = tarfile.TarInfo(name); info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
        subprocess.run(['age', '-r', self.recipients[0], '-r', self.recipients[1], '-o', str(self.bundle)],
                       input=data.getvalue(), check=True, capture_output=True)
        self.env = {**os.environ, 'HOME': str(self.root/'home'), 'UNBUG_SECRETS_FILE': str(self.bundle),
                    'UNBUG_CONTROL_HOME': str(self.root/'control-home')}
        spec = importlib.util.spec_from_file_location('fixture_holder', self.root/'factory/key_holder.py')
        self.holder = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.holder)
        self.holder.RUNTIME = self.root/'runtime'; self.holder.SOCKET = self.holder.RUNTIME/'control.sock'
        self.launcher = self.root/'factory/launch.sh'
        self.launcher.write_text("""#!/bin/sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
if [ "${UNBUG_CONTROL_PID:-}" != "$$" ]; then exec python3 "$here/control_resume.py" "$@"; fi
exec python3 "$here/proof.py" "$@"
""")
        (self.root/'factory/proof.py').write_text("""import hashlib,json,os,pathlib,sys
raw=sys.stdin.buffer.read()
state=pathlib.Path(os.environ['UNBUG_LAUNCH_STATE'])
(state/'monitor.sh').touch()
with pathlib.Path('proof.jsonl').open('a') as f:
 f.write(json.dumps(dict(argv=sys.argv[1:],identity_sha256=hashlib.sha256(raw).hexdigest(),environment=dict(os.environ)))+'\\n')
""")
        boat = self.root/'bin/boat-call'
        boat.write_text("#!/bin/sh\nprintf '%s\\n' '{\"sandboxes\":[],\"pageInfo\":{\"hasMore\":false}}'\n")
        boat.chmod(0o755)
        self.policy = {'root': str(self.root), 'recipient': self.recipients[0], 'path': os.environ['PATH'],
                       'code_sha256': self.holder.fingerprint(self.root), 'jobs': {
                           'allowed': {'mode':'new', 'case':'new-synthetic', 'max_calls':10, 'max_cost':1,
                                       'args':['1','--source','hunt','--rotation-slot','1']},
                           'restore': {'mode':'case', 'case':'case-synthetic', 'max_calls':10, 'max_cost':1,
                                       'args':['1','--restore','case-synthetic']}}}
        self.policy_path = self.root/'policy.json'; self.save_policy()

    def save_policy(self):
        self.policy['code_sha256'] = self.holder.fingerprint(self.root)
        self.policy_path.write_text(json.dumps(self.policy))

    def command(self, *args):
        # Explicit fixture socket; never discover or stop a real holder.
        code = ('import pathlib,sys; sys.path.insert(0,' + repr(str(self.root/'factory')) + '); '
                'import key_holder as h; h.RUNTIME=pathlib.Path(' + repr(str(self.holder.RUNTIME)) + '); '
                'h.SOCKET=h.RUNTIME/"control.sock"; h.main()')
        return [sys.executable, '-c', code, *args]

    def start(self, identity=None):
        p = subprocess.Popen(self.command('serve', '--policy', str(self.policy_path),
                                          '--identity-file', str(identity or self.keys[1]), '--hours', '.02'),
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
        self.addCleanup(self.stop, p)
        for _ in range(100):
            if p.poll() is not None:
                self.fail('synthetic holder failed: ' + p.stderr.read().decode())
            try:
                if self.holder.request({'op':'status'}).get('unlocked'): return p
            except (OSError, ValueError): pass
            time.sleep(.03)
        self.fail('synthetic holder did not become ready')

    @staticmethod
    def stop(p):
        if p.poll() is None: p.terminate()
        p.communicate(timeout=10)

    def launch(self):
        reply = self.holder.request({'op':'launch', 'job':'allowed'})
        self.assertTrue(reply.get('started'), reply)
        self.wait('allowed')
        return reply

    def wait(self, name):
        for _ in range(150):
            status = self.holder.request({'op':'status'})
            if status['jobs'][name]['exit'] is not None:
                self.assertEqual(status['jobs'][name]['exit'], 0); return
            time.sleep(.02)
        self.fail('fixture launch did not exit')

    def test_identity_file_refuses_modes_symlinks_owner_and_non_age(self):
        reader = self.holder.read_control_identity
        self.assertEqual(reader(self.keys[1]), self.key)
        for mode in (0o644, 0o400, 0o700):
            self.keys[1].chmod(mode)
            with self.assertRaisesRegex(ValueError, '0600'): reader(self.keys[1])
        self.keys[1].chmod(0o600)
        link = self.root/'link'; link.symlink_to(self.keys[1])
        with self.assertRaises((ValueError, OSError)): reader(link)
        with mock.patch.object(self.holder.os, 'getuid', return_value=os.getuid()+1):
            with self.assertRaisesRegex(ValueError, 'owner'): reader(self.keys[1])
        self.keys[1].write_text('not an age identity\n')
        with self.assertRaisesRegex(ValueError, 'identity'): reader(self.keys[1])

    def test_control_identity_serves_policy_job_and_refuses_unlisted_job(self):
        self.start(); self.launch()
        self.assertIn('error', self.holder.request({'op':'launch', 'job':'unlisted'}))
        self.assertEqual(self.holder.SOCKET.stat().st_mode & 0o777, 0o600)
        for _ in range(2): self.launch()
        self.assertIn('error', self.holder.request({'op':'launch', 'job':'allowed'}))
        self.launcher.write_text(self.launcher.read_text()+'# drift\n')
        self.assertIn('error', self.holder.request({'op':'launch', 'resume_launches':True}))
        for path in self.holder.RUNTIME.rglob('*'):
            if path.is_file(): self.assertNotIn(self.key.strip(), path.read_bytes())

    def test_control_identity_requires_decryptable_bundle(self):
        with self.assertRaisesRegex(AssertionError, 'credential bundle'):
            self.start(self.keys[2])

    def test_control_holder_refuses_founder_restore_before_provider(self):
        (self.root/'bin/boat-call').write_text('#!/bin/sh\ntouch provider-called\nexit 1\n')
        self.save_policy(); self.start()
        reply = self.holder.request({'op':'launch', 'job':'restore'})
        self.assertIn('founder identity required', reply.get('error',''))
        self.assertFalse((self.root/'provider-called').exists())

    def test_resume_receives_identity_only_on_pipe_and_keeps_receipt(self):
        p = self.start(); self.launch(); self.stop(p)
        receipts_path = self.holder.RUNTIME/'reservations.json'
        before = json.loads(receipts_path.read_text())
        self.start()
        result = subprocess.run(self.command('launch', '--resume-launches'), capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        reply = json.loads(result.stdout)
        self.assertEqual(reply.get('resumed'), 1, reply)
        self.wait('resume-'+before[0]['launch_id'])
        proofs = [json.loads(v) for v in (self.root/'proof.jsonl').read_text().splitlines()]
        self.assertEqual(len(proofs), 2)
        for proof in proofs:
            self.assertEqual(proof['identity_sha256'], hashlib.sha256(self.key).hexdigest())
            self.assertNotIn(self.key.strip().decode(), json.dumps(proof))
        after = json.loads(receipts_path.read_text())
        self.assertEqual(len(after), len(before))
        self.assertEqual(after[0]['at'], before[0]['at'])
        for path in (self.root/'control-home').rglob('*'):
            if path.is_file():
                self.assertNotIn(self.key.strip(), path.read_bytes())
                self.assertNotIn(b'synthetic credential', path.read_bytes())

    def test_resume_refuses_modified_launch_state(self):
        self.start(); self.launch()
        state = next((self.root/'control-home/launches').iterdir())/'launch.json'
        saved = json.loads(state.read_text()); saved['argv'].append('--arbitrary-option')
        state.write_text(json.dumps(saved))
        reply = self.holder.request({'op':'launch','resume_launches':True})
        self.assertEqual(reply['resumed'], 0)
        self.assertEqual(reply['refused'][0]['error'], 'reserved launch policy or routing changed')

    def resume_policy_scenario(self, live=False, changed=False, mixed=False):
        p = self.start(); self.launch(); self.stop(p)
        path = self.holder.RUNTIME/'reservations.json'
        rows = json.loads(path.read_text())
        row = rows[0]
        state = self.root/'control-home/launches'/row['launch_id']
        if changed or mixed:
            row['policy_sha256'] = '0'*64
        if mixed:
            # A refused orphan preceding an eligible orphan cannot abort the batch.
            other = {**row, 'launch_id': 'a'*32, 'policy_sha256': self.holder.policy_digest(self.policy)}
            shutil.copytree(state, state.with_name(other['launch_id']))
            rows.append(other)
        path.write_text(json.dumps(rows))
        with (state/'controller.lock').open('a+') as lock:
            if live:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # A live launch must be skipped before even reading routing state.
                (state/'launch.json').write_text('not JSON')
            self.start()
            result = subprocess.run(self.command('launch', '--resume-launches'), capture_output=True, text=True, env=self.env)
            self.assertEqual(result.returncode, 0, result.stderr)
            reply = json.loads(result.stdout)
            expected = int(mixed or (not live and not changed))
            self.assertEqual(reply.get('resumed'), expected, reply)
            refused = reply.get('refused', [])
            self.assertEqual(len(refused), int((changed or mixed) and not live), reply)
            if refused:
                self.assertEqual(refused[0], {'launch_id': row['launch_id'], 'error': 'reserved launch policy or routing changed'})
            if expected:
                self.wait('resume-'+rows[-1]['launch_id'])
            after = json.loads(path.read_text())
            if live or changed or mixed:
                self.assertEqual(after[0], row, 'skipped/refused reservation changed')
        return reply

    def test_resume_live_controller_under_old_policy_is_skipped(self):
        self.resume_policy_scenario(live=True, changed=True)

    def test_resume_orphan_under_changed_policy_is_refused(self):
        self.resume_policy_scenario(changed=True)

    def test_resume_orphan_under_same_policy_is_resumed(self):
        self.resume_policy_scenario()

    def test_resume_refused_orphan_does_not_block_eligible_orphan(self):
        self.resume_policy_scenario(mixed=True)

    def test_setup_secrets_encrypts_both_public_recipients(self):
        self.env['CONTROL_RECIPIENT'] = self.recipients[1]
        self.run_setup()
        for key in self.keys[:2]:
            result = subprocess.run(['age','-d','-i',str(key),str(self.bundle)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
                self.assertIn('statements-key', archive.getnames())
                self.assertNotIn('control-recipient.txt', archive.getnames())
        del self.env['CONTROL_RECIPIENT']
        self.run_setup()
        founder = subprocess.run(['age','-d','-i',str(self.keys[0]),str(self.bundle)], capture_output=True)
        control = subprocess.run(['age','-d','-i',str(self.keys[1]),str(self.bundle)], capture_output=True)
        self.assertEqual(founder.returncode, 0)
        self.assertNotEqual(control.returncode, 0)

    def test_setup_secrets_public_file_and_invalid_recipient(self):
        (self.root/'factory/control-recipient.txt').write_text(self.recipients[1]+'\n')
        self.run_setup()
        result = subprocess.run(['age','-d','-i',str(self.keys[1]),str(self.bundle)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = self.bundle.read_bytes()
        self.env['CONTROL_RECIPIENT'] = self.key.strip().decode()
        result = self.run_setup(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('public age recipient', result.stderr)
        self.assertEqual(self.bundle.read_bytes(), before)

    def run_setup(self, check=True):
        result = subprocess.run(['/bin/sh',str(self.root/'bin/setup-secrets'),'statements'],
                                input=self.keys[0].read_text(), text=True, capture_output=True, env=self.env)
        if check: self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_launch_restore_refuses_control_before_worker_or_archive_access(self):
        shutil.copyfile(HERE/'launch.sh', self.launcher)
        # Real launcher through its key/restore preflight; no cloud commands are available.
        shutil.copyfile(HERE.parent/'bin/boat-launch-guards.sh', self.root/'bin/boat-launch-guards.sh')
        result = subprocess.run(['/bin/sh',str(self.launcher),'1','--restore','case-synthetic'],
                                input=self.key, capture_output=True, env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'founder identity required', result.stderr)


if __name__ == '__main__': unittest.main()
