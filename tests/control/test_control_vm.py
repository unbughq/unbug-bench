#!/usr/bin/env python3
"""Offline contract tests. Every infrastructure command is a local PATH fake."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2]
# boat-cli-v1.0.85 boat-linux-x64, installed and hashed on the control VM (docs/reports/practice-run-20261102.md).
BOAT_SHA256 = '5d7933a238dcea0446bbbee0e2506692961d16537b9960003e4ece9ecb1ec498'
FAKE = r'''#!/usr/bin/env python3
import hashlib, json, os, pathlib, shutil, sys
root = pathlib.Path(os.environ['FAKE_ROOT'])
tool = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
data = sys.stdin.read()
entry = dict(tool=tool, args=args, stdin=data)
if tool == 'ssh' and 'login --key-stdin' in args[-1]:
    # Record only a digest: the fake transport must not itself persist the secret.
    entry['stdin'] = None
    entry['stdin_sha256'] = hashlib.sha256(data.encode()).hexdigest()
    if data != 'synthetic_boat_secret_42\n': sys.exit('wrong stdin')
    for path in root.rglob('*'):
        if path.is_file() and not any(part in ('repo', 'fakebin') for part in path.relative_to(root).parts):
            if b'synthetic_boat_secret_42' in path.read_bytes(): sys.exit('secret persisted on Mac')
entry['no_update'] = os.environ.get('BOAT_NO_UPDATE')
if tool == 'rsync':
    filelist = next(v.split('=', 1)[1] for v in args if v.startswith('--files-from='))
    entry['files'] = pathlib.Path(filelist).read_bytes().decode().strip('\0').split('\0')
if tool == 'hcloud' and args[:2] == ['firewall', 'create']:
    entry['rules'] = json.loads(pathlib.Path(args[args.index('--rules-file') + 1]).read_text())
with (root / 'calls.jsonl').open('a') as f:
    f.write(json.dumps(entry) + '\n')
server = dict(id=7, name='unbug-control', status='running', labels={'unbug-control':'1'},
              public_net={'ipv4':{'ip':'192.0.2.7'}})
def output(value): print(json.dumps(value))
if tool == 'hcloud':
    if args[:2] == ['server', 'list']:
        output([server] if os.environ.get('EXISTS') == '1' else [])
    elif args[:2] == ['server', 'create']:
        output({'server':server})
    elif args[:2] == ['firewall', 'list']:
        rules = [{'direction':'in', 'protocol':'tcp', 'port':'22', 'source_ips':['0.0.0.0/0','::/0']}]
        if os.environ.get('BAD_FIREWALL'): rules[0]['port'] = '443'
        output([{'id':8, 'rules':rules}] if os.environ.get('FIREWALL') else [])
    elif args[:2] == ['firewall', 'create']:
        output({'firewall':{'id':8}})
    elif args[:2] != ['server', 'delete']:
        sys.exit('unexpected hcloud operation')
elif tool == 'ssh':
    command = args[-1]
    if 'login --key-stdin' in command:
        print('synthetic_boat_secret_42')
        print('synthetic_boat_secret_42', file=sys.stderr)
        if os.environ.get('FAIL_LOGIN'): sys.exit(1)
    elif command.endswith('boat list --json'):
        print('synthetic_boat_secret_42', file=sys.stderr)
        if os.environ.get('FAIL_LIST'): sys.exit(1)
        output([])
    elif command == 'sh -s -- key-and-units':
        key = root / 'remote/control.key'; key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text('SYNTHETIC_REMOTE_PRIVATE_KEY'); key.chmod(0o600)
        print('age1publictest')
    elif command == 'sh -s -- activate' and os.environ.get('FAIL_ACTIVATE'):
        sys.exit(1)
    elif command.startswith('python3 -c '):
        manifest = json.loads(data)
        base = root / 'remote/unbug-bench/sealed'
        if command.endswith(' prepare'):
            base.mkdir(parents=True, exist_ok=True)
            sys.exit(0)
        hashes = {n:hashlib.sha256((base/n).read_bytes()).hexdigest() for n in manifest}
        if os.environ.get('CORRUPT'): hashes[manifest[0]] = 'bad'
        output(hashes)
elif tool == 'boat':
    if args == ['api-key', 'create', '--help']:
        print('unsupported help' if os.environ.get('BAD_HELP') else
              'Usage: boat api-key create [OPTIONS] [NAME] --json')
    elif args == ['api-key', 'create', 'unbug-control-unbug-control', '--json']:
        if os.environ.get('BAD_KEY_JSON'):
            print('synthetic_boat_secret_42', file=sys.stderr)
            print('{invalid synthetic_boat_secret_42')
        else:
            output({'apiKey': {'id':'key-7', 'keyPrefix':'boat_test', 'keyLastFour':'t_42'},
                    'secret':'synthetic_boat_secret_42'})
    elif args == ['--version']:
        if os.environ.get('FAIL_VERSION'): sys.exit(1)
        print('boat 1.0.66')
    elif args == ['list', '--json']:
        if os.environ.get('FAIL_LIST'): sys.exit(1)
        output([])
    else: sys.exit('unexpected boat operation')
elif tool == 'curl':
    pathlib.Path(args[args.index('-o') + 1]).write_text(pathlib.Path(__file__).read_text())
elif tool == 'uname':
    print(os.environ.get('FAKE_ARCH', 'x86_64'))
elif tool == 'systemctl':
    if args[0] == 'is-active': sys.exit(1)
elif tool == 'runuser':
    os.execvp(args[3], args[3:])
elif tool == 'install':
    # Preserve requested permissions; owner/group are asserted from the call log.
    args = list(args); mode = int(args[args.index('-m') + 1], 8)
    for flag in ('-m', '-o', '-g'):
        if flag in args:
            i = args.index(flag); del args[i:i+2]
    if args[0] == '-d':
        for name in args[1:]:
            p = pathlib.Path(name); p.mkdir(parents=True, exist_ok=True); p.chmod(mode)
    else:
        dst = pathlib.Path(args[1]); dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_dir(): dst /= pathlib.Path(args[0]).name
        shutil.copy2(args[0], dst); dst.chmod(mode)
elif tool in ('chown', 'cloud-init', 'apt-get', 'id', 'usermod', 'sshd'):
    pass
elif tool == 'rsync':
    base = pathlib.Path(args[-2])
    target = args[-1].split(':', 1)[1].replace('/home/user/', '')
    for name in entry['files']:
        src = base / name; dst = root / 'remote' / target / name
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
else:
    sys.exit('unexpected command; real infrastructure must never run')
'''


class ControlVMTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='control-vm-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        (self.repo / 'bin').mkdir(parents=True)
        shutil.copy2(SOURCE / 'bin/control-vm', self.repo / 'bin/control-vm')
        shutil.copytree(SOURCE / 'control', self.repo / 'control', ignore=shutil.ignore_patterns('__pycache__'))
        fakebin = self.root / 'fakebin'; fakebin.mkdir()
        for name in ('hcloud', 'ssh', 'rsync', 'boat', 'curl', 'uname', 'systemctl',
                     'runuser', 'install', 'chown', 'cloud-init', 'apt-get', 'id', 'usermod', 'sshd'):
            p = fakebin / name; p.write_text(FAKE); p.chmod(0o755)
        self.env = {**os.environ, 'PATH':str(fakebin) + os.pathsep + os.environ['PATH'],
                    'HOME':str(self.root / 'home'), 'FAKE_ROOT':str(self.root)}
        (self.root / 'mac-tmp').mkdir()
        self.env.update(TMPDIR=str(self.root / 'mac-tmp'), TMP=str(self.root / 'mac-tmp'),
                        TEMP=str(self.root / 'mac-tmp'))
        for name in ('EXISTS', 'FIREWALL', 'BAD_FIREWALL', 'FAIL_ACTIVATE', 'CORRUPT',
                     'FAIL_LIST', 'FAKE_ARCH', 'BAD_KEY_JSON', 'BAD_HELP', 'FAIL_LOGIN', 'FAIL_VERSION'):
            self.env.pop(name, None)

    def invoke(self, *args, **env):
        return subprocess.run([sys.executable, str(self.repo / 'bin/control-vm'), *args],
                              capture_output=True, text=True, env={**self.env, **env})

    def calls(self, tool=None):
        path = self.root / 'calls.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [r for r in rows if tool is None or r['tool'] == tool]

    def write(self, name, value='synthetic fixture'):
        path = self.repo / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def test_create_refuses_duplicate_before_mutation(self):
        p = self.invoke('create', EXISTS='1')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('already exists', p.stderr)
        self.assertEqual([r['args'][:2] for r in self.calls()], [['server', 'list']])

    def test_create_attaches_ssh_only_firewall_and_existing_key(self):
        p = self.invoke('create')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), '192.0.2.7')
        rules = next(r['rules'] for r in self.calls() if 'rules' in r)
        self.assertEqual(rules, [dict(direction='in', protocol='tcp', port='22',
                                     source_ips=['0.0.0.0/0', '::/0'])])
        args = next(r['args'] for r in self.calls() if r['args'][:2] == ['server', 'create'])
        for flag, value in (('--type','cx23'), ('--image','ubuntu-24.04'), ('--ssh-key','unbug-bench'),
                            ('--firewall','8'), ('--label','unbug-control=1'), ('--location','nbg1')):
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertNotIn('unbug-bench=1', args)

    def test_create_reuses_firewall_but_refuses_non_ssh_rules(self):
        self.assertEqual(self.invoke('create', FIREWALL='1').returncode, 0)
        self.assertFalse(any(r['args'][:2] == ['firewall', 'create'] for r in self.calls('hcloud')))
        p = self.invoke('create', FIREWALL='1', BAD_FIREWALL='1')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('not SSH-only', p.stderr)

    def test_setup_allowlist_excludes_protected_paths_and_symlinks(self):
        marker = 'blocked-' + self.root.name
        for path in ('factory/launch.sh', 'tools/helper.py', 'bin/boat-call', 'README.md',
                     'bin/setup-secrets', 'bin/push-secrets'):
            self.write(path)
        for path in ('sealed/history.statement.age', 'results/log.txt', 'factory/secrets.txt',
                     'bin/secrets.age', 'bin/secrets/bundle.json', 'bin/credentials-bundle.json',
                     'tools/.age/key.txt', 'tools/bundles/payload.json', 'tools/nested/SeCrEtS.json',
                     'tools/secrets-dir/source.py', 'factory/results/leak.py', 'factory/sealed/leak.py',
                     'factory/canary/source.py', 'factory/control.key', 'factory/credential.age'):
            self.write(path, marker)
        (self.repo / 'factory/link.py').symlink_to(self.repo / 'sealed/history.statement.age')
        p = self.invoke('setup', EXISTS='1')
        self.assertEqual(p.returncode, 0, p.stderr)
        sync = self.calls('rsync')
        self.assertEqual(len(sync), 1)
        names = sync[0]['files']
        for good in ('factory/launch.sh', 'tools/helper.py', 'bin/boat-call', 'README.md',
                     'bin/setup-secrets', 'bin/push-secrets'):
            self.assertIn(good, names)
        for unit in ('unbug-key-holder.service', 'unbug-resume-launches.service', 'unbug-resume-launches.timer'):
            name = 'control/' + unit
            self.assertIn(name, names)
            self.assertTrue((self.root / 'remote/unbug-bench' / name).is_file())
        for name in names:
            self.assertFalse(any(part.lower() in ('sealed', 'results') or
                                 ('secrets' in part.lower() and name not in ('bin/push-secrets', 'bin/setup-secrets')) or
                                 'bundle' in part.lower() or 'canary' in part.lower() for part in Path(name).parts), name)
        self.assertNotIn('factory/link.py', names)
        self.assertNotIn('factory/control.key', names)
        self.assertNotIn('--delete', sync[0]['args'])
        self.assertFalse(any(marker in p.read_text() for p in (self.root/'remote/unbug-bench').rglob('*') if p.is_file()))

    def test_setup_excludes_bundles_even_when_their_files_look_like_source(self):
        for path in ('tools/bundles/payload.json', 'bin/credentials-bundle.json'):
            self.write(path, 'synthetic protected bundle')
        p = self.invoke('setup', EXISTS='1')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(any('bundle' in name for name in self.calls('rsync')[0]['files']))

    def test_units_disable_boat_self_updates(self):
        for name in ('unbug-key-holder', 'unbug-resume-launches'):
            with self.subTest(unit=name):
                unit = (self.repo / ('control/' + name + '.service')).read_text()
                self.assertIn('BOAT_NO_UPDATE=1', unit)

    def run_setup_phase(self, phase, *, accept_fake_boat=True, **extra):
        # Execute the actual shell branches with VM filesystem paths relocated.
        vm = self.root / 'vm'
        home = vm / 'home/user'
        home.mkdir(parents=True, exist_ok=True)
        for directory in ('etc/ssh/sshd_config.d', 'etc/apt/apt.conf.d', 'usr/local/bin', 'root/.ssh'):
            (vm / directory).mkdir(parents=True, exist_ok=True)
        (vm / 'root/.ssh/authorized_keys').write_text('synthetic-public-key')
        script = (self.repo / 'control/setup.sh').read_text()
        for prefix in ('/home/user', '/usr/local/bin', '/etc/', '/root/.ssh'):
            script = script.replace(prefix, str(vm) + prefix)
        if accept_fake_boat:
            # The fake curl writes this fake; only its digest stands in for the pinned 1.0.85 asset.
            self.assertEqual(script.count(BOAT_SHA256), 1)
            script = script.replace(BOAT_SHA256, hashlib.sha256(FAKE.encode()).hexdigest())
        target = self.root / 'setup-fixture.sh'; target.write_text(script)
        # holder check and policy/bundle prerequisites are synthetic public fixtures.
        repo = home / 'unbug-bench'
        (repo / 'control').mkdir(parents=True, exist_ok=True)
        (repo / 'control/holder-command.sh').write_text('exit 0\n')
        (repo / 'bin').mkdir(exist_ok=True)
        (repo / 'bin/push-secrets').write_text('synthetic public helper')
        (repo / 'factory').mkdir(exist_ok=True)
        (repo / 'factory/recovery.py').write_text('synthetic public recovery policy')
        (home / '.unbug-control').mkdir(exist_ok=True)
        (home / '.unbug-control/policy.json').write_text('{}')
        (home / '.config/unbug-bench').mkdir(parents=True, exist_ok=True)
        (home / '.config/unbug-bench/secrets.age').write_text('synthetic bundle')
        return subprocess.run(['sh', str(target), phase], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True,
                              env={**self.env, 'HOME':str(home), **extra})

    def test_setup_downloads_pinned_boat_for_vm_arch_and_records_version(self):
        for arch, platform in (('x86_64', 'x64'),):
            with self.subTest(arch=arch):
                p = self.run_setup_phase('bootstrap', FAKE_ARCH=arch)
                self.assertEqual(p.returncode, 0, p.stderr)
                calls = self.calls('curl')
                self.assertTrue(calls, 'bootstrap must install Boat')
                args = calls[-1]['args']
                self.assertIn('https://github.com/ariana-dot-dev/agent-server/releases/download/boat-cli-v1.0.85/boat-linux-' + platform, args)
                self.assertIn('-fsSL', args)
                home = self.root / 'vm/home/user'
                boat = home / '.ascii/bin/boat'
                self.assertEqual(args[args.index('-o') + 1], str(boat) + '.download')
                self.assertFalse((home / '.ascii/bin/boat.download').exists())
                self.assertEqual(boat.stat().st_mode & 0o777, 0o755)
                self.assertTrue(any(r['args'] == ['user:user', str(boat)] for r in self.calls('chown')))
                self.assertEqual(json.loads((home / '.config/ascii/boat/config.json').read_text()),
                                 {'api_url':'https://boat.dev', 'channel':'prod'})
                self.assertEqual((self.root / 'vm/usr/local/bin/boat').resolve(), boat.resolve())
                self.assertEqual(self.calls('boat')[-1]['no_update'], '1')
                self.assertIn('boat 1.0.66', p.stderr + p.stdout)
                self.assertEqual(self.calls('boat')[-1]['args'], ['--version'])
                self.assertEqual((self.root / 'vm/etc/needrestart/conf.d/unbug.conf').read_text(),
                                 '# 2026-10-24: unattended upgrades must not restart the key holder under a live controller.\n'
                                 '$nrconf{override_rc}{qr(^unbug-)} = 0;\n')

    def test_setup_refuses_unknown_boat_arch_before_download(self):
        # arm64 too: only the x64 1.0.85 asset has a recorded SHA-256.
        for arch in ('riscv64', 'aarch64', 'arm64'):
            with self.subTest(arch=arch):
                p = self.run_setup_phase('bootstrap', FAKE_ARCH=arch)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(self.calls('curl'), [])

    def test_setup_refuses_boat_sha256_mismatch(self):
        # Real setup.sh pin; the download is replaced by a file that is not the 1.0.85 asset.
        self.assertIn('boat_sha256=' + BOAT_SHA256, (SOURCE / 'control/setup.sh').read_text())
        p = self.run_setup_phase('bootstrap', accept_fake_boat=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('Boat CLI SHA-256 mismatch; not installed', p.stderr)
        self.assertEqual(len(self.calls('curl')), 1)
        bin_dir = self.root / 'vm/home/user/.ascii/bin'
        self.assertFalse((bin_dir / 'boat').exists())
        self.assertFalse((bin_dir / 'boat.download').exists())
        self.assertEqual(self.calls('boat'), [])
        self.assertNotIn('Installed Boat CLI:', p.stdout + p.stderr)

    def test_setup_refuses_unrunnable_boat_download(self):
        p = self.run_setup_phase('bootstrap', FAIL_VERSION='1')
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('Installed Boat CLI:', p.stdout + p.stderr)

    def test_activation_requires_authenticated_boat_but_no_rtk(self):
        # Place a fake Boat at the fixed VM executable path; no rtk is installed.
        boat = self.root / 'vm/usr/local/bin/boat'
        boat.parent.mkdir(parents=True)
        boat.write_text(FAKE); boat.chmod(0o755)
        p = self.run_setup_phase('activate', FAIL_LIST='1')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual([r['args'] for r in self.calls('boat')], [['list', '--json']])
        self.assertFalse(any(r['args'][0] == 'enable' for r in self.calls('systemctl')))
        p = self.run_setup_phase('activate')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(any(r['args'][0] == 'enable' for r in self.calls('systemctl')))
        self.assertTrue(all(r['no_update'] == '1' for r in self.calls('boat')))
        self.assertTrue(all(r['args'][:3] == ['-u', 'user', '--'] for r in self.calls('runuser')))

    def test_boat_login_uses_dedicated_key_stdin_only_and_proves_auth(self):
        p = self.invoke('boat-login', EXISTS='1')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), {'id':'key-7', 'prefix':'boat_test', 'last4':'t_42'})
        boat = self.calls('boat')
        self.assertEqual(boat[0]['args'], ['api-key', 'create', '--help'])
        self.assertEqual(boat[1]['args'], ['api-key', 'create', 'unbug-control-unbug-control', '--json'])
        self.assertTrue(all(row['no_update'] == '1' for row in boat))
        login, proof = self.calls('ssh')
        self.assertIn('root@192.0.2.7', login['args'])
        self.assertIn('runuser -u user -- /usr/local/bin/boat login --key-stdin', login['args'][-1])
        self.assertEqual(login['stdin_sha256'], hashlib.sha256(b'synthetic_boat_secret_42\n').hexdigest())
        self.assertIn('list --json', proof['args'][-1])
        self.assertIn('user@192.0.2.7', proof['args'])
        self.assertNotIn('synthetic_boat_secret_42', p.stdout + p.stderr)
        for row in self.calls():
            self.assertNotIn('synthetic_boat_secret_42', json.dumps(row))
        # Scan every synthetic Mac-side file, including logs and temp manifests.
        for path in self.root.rglob('*'):
            if path.is_file() and not path.is_relative_to(self.repo) and 'fakebin' not in path.parts:
                self.assertNotIn(b'synthetic_boat_secret_42', path.read_bytes(), str(path))

    def test_boat_login_suppresses_secret_in_malformed_response(self):
        p = self.invoke('boat-login', EXISTS='1', BAD_KEY_JSON='1')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('invalid Boat API-key response', p.stderr)
        self.assertNotIn('synthetic_boat_secret_42', p.stdout + p.stderr)
        self.assertEqual(self.calls('ssh'), [])

    def test_boat_login_checks_help_before_creating_key(self):
        p = self.invoke('boat-login', EXISTS='1', BAD_HELP='1')
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('must accept [NAME] and --json', p.stderr)
        self.assertEqual([r['args'] for r in self.calls('boat')], [['api-key', 'create', '--help']])
        self.assertEqual(self.calls('ssh'), [])

    def test_boat_login_fails_closed_without_echoing_transport_or_auth_errors(self):
        for flag, expected_calls in (('FAIL_LOGIN', 1), ('FAIL_LIST', 2)):
            with self.subTest(flag=flag):
                (self.root / 'calls.jsonl').unlink(missing_ok=True)
                p = self.invoke('boat-login', EXISTS='1', **{flag:'1'})
                self.assertNotEqual(p.returncode, 0)
                self.assertTrue(p.stdout.strip(), 'retain only revocation identifiers on failure')
                self.assertEqual(json.loads(p.stdout)['id'], 'key-7')
                self.assertEqual(len(self.calls('ssh')), expected_calls)
                self.assertNotIn('synthetic_boat_secret_42', p.stdout + p.stderr)

    def test_private_key_is_remote_only_public_recipient_survives_activation_failure(self):
        p = self.invoke('setup', EXISTS='1', FAIL_ACTIVATE='1')
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), 'age1publictest')
        self.assertNotIn('SYNTHETIC_REMOTE_PRIVATE_KEY', p.stdout + p.stderr)
        key = self.root / 'remote/control.key'
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertFalse(any(p.name == 'control.key' for p in (self.root/'home').rglob('*')))
        remote = next(r for r in self.calls('ssh') if r['args'][-1] == 'sh -s -- key-and-units')
        self.assertIn('root@192.0.2.7', remote['args'])
        self.assertIn('age-keygen -o "$key" >/dev/null 2>/dev/null', remote['stdin'])
        self.assertIn('age-keygen -y "$key"', remote['stdin'])
        self.assertIn('chmod 600 "$key"', remote['stdin'])
        self.assertFalse(any('control.key' in name for r in self.calls('rsync') for name in r['files']))

    def test_setup_templates_fail_closed_and_resume_only_through_holder(self):
        setup = (self.repo / 'control/setup.sh').read_text()
        self.assertIn('PasswordAuthentication no', setup)
        self.assertIn('unattended-upgrades', setup)
        self.assertNotIn('TODO:', setup)
        self.assertNotIn('rtk', setup)
        self.assertLess(setup.index('holder-command.sh" check'), setup.index('systemctl enable unbug-key-holder'))
        wrapper = (self.repo / 'control/holder-command.sh').read_text()
        self.assertIn('serve --policy "$policy" --identity-file', wrapper)
        self.assertIn('/usr/bin/python3 "$holder" launch --resume-launches', wrapper)
        self.assertIn('reply.get("resumed")', wrapper)
        self.assertNotIn('cat ', wrapper)
        for name in ('unbug-key-holder', 'unbug-resume-launches'):
            unit = (self.repo / ('control/' + name + '.service')).read_text()
            self.assertIn('User=user', unit)
            self.assertIn('After=network-online.target', unit)
            self.assertIn('Restart=on-failure', unit)
        self.assertIn('KillMode=process', (self.repo / 'control/unbug-key-holder.service').read_text())
        resume = (self.repo / 'control/unbug-resume-launches.service').read_text()
        self.assertNotIn('RemainAfterExit=yes', resume)
        self.assertIn('BindsTo=unbug-key-holder.service', resume)
        timer = (self.repo / 'control/unbug-resume-launches.timer').read_text()
        self.assertIn('OnUnitInactiveSec=60s', timer)
        self.assertIn('unbug-resume-launches.timer', setup)

    def test_holder_wrapper_restarts_clean_expiry_and_rejects_refused_resume(self):
        # Execute the shell template against a synthetic holder, with only its
        # fixed VM/Python paths rewritten into this isolated temporary fixture.
        holder = self.write('factory/key_holder.py',
                            'import json, sys\nprint(json.dumps({"unlocked":True} if sys.argv[1]=="status" else {"error":"refused"}))\n')
        wrapper = (self.repo / 'control/holder-command.sh').read_text().replace(
            '/home/user/unbug-bench', str(self.repo)).replace('/usr/bin/python3', sys.executable)
        script = self.root / 'holder-command.sh'; script.write_text(wrapper)
        for command in ('serve', 'resume'):
            p = subprocess.run(['sh', str(script), command], capture_output=True, text=True, env=self.env)
            self.assertNotEqual(p.returncode, 0, command)
        holder.write_text('import json\nprint(json.dumps({"unlocked":True,"resumed":0}))\n')
        p = subprocess.run(['sh', str(script), 'resume'], capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_migrate_hashes_every_file_preserves_mac_and_detects_mismatch(self):
        names = ['statement-registry/objects/cipher.age', 'statement-registry/registry.sqlite',
                 'case-one.statement.age', 'case-one.scorecard.json', 'case-one.casekey.age',
                 'case-one.search.age', 'case-one.checkpoint.tar.gz.age', 'paused/case-one.tar.gz.age']
        for name in names:
            self.write('sealed/' + name, name)
        self.write('sealed/unrelated.txt', 'leave behind')
        base = self.repo / 'sealed'
        before = {n:(hashlib.sha256((base/n).read_bytes()).hexdigest(), (base/n).stat().st_mode) for n in names}
        p = self.invoke('migrate', EXISTS='1')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('Verified 8 files', p.stdout)
        self.assertEqual(self.calls('rsync')[-1]['files'], sorted(names))
        self.assertEqual(before, {n:(hashlib.sha256((base/n).read_bytes()).hexdigest(), (base/n).stat().st_mode) for n in names})
        self.assertNotEqual(self.invoke('migrate', EXISTS='1', CORRUPT='1').returncode, 0)
        self.assertNotIn('--delete', self.calls('rsync')[-1]['args'])

    def test_migrate_rejects_symlink(self):
        self.write('sealed/real.statement.age')
        (self.repo/'sealed/link.statement.age').symlink_to(self.repo/'sealed/real.statement.age')
        self.assertNotEqual(self.invoke('migrate', EXISTS='1').returncode, 0)
        self.assertEqual(self.calls('rsync'), [])

    def test_destroy_needs_yes_exact_name_and_control_label(self):
        self.assertNotEqual(self.invoke('destroy', 'unbug-control', EXISTS='1').returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertNotEqual(self.invoke('destroy', 'wrong', '--yes', EXISTS='1').returncode, 0)
        self.assertNotEqual(self.invoke('destroy', 'unbug-control', '--yes').returncode, 0)
        self.assertFalse(any(r['args'][:2] == ['server','delete'] for r in self.calls()))
        self.assertEqual(self.invoke('destroy', 'unbug-control', '--yes', EXISTS='1').returncode, 0)
        self.assertEqual(self.calls('hcloud')[-1]['args'], ['server', 'delete', '7'])
        self.assertEqual(self.calls('ssh'), [])
        self.assertEqual(self.calls('boat'), [])

    def test_status_is_read_only(self):
        p = self.invoke('status', EXISTS='1')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([r['args'][:2] for r in self.calls('hcloud')], [['server','list']])
        self.assertEqual(self.calls('rsync'), [])
        self.assertIn('systemctl show', self.calls('ssh')[0]['args'][-1])
        self.assertIn('launches', self.calls('ssh')[0]['args'][-1])


if __name__ == '__main__':
    unittest.main()
