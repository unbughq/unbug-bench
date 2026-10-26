"""Offline deployment checks against hermetic synthetic release inputs."""
import hashlib
import importlib.util
import json
import os
import py_compile
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from deployment_fixture import build_release, folding_sequence

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('deployment', ROOT / 'bin/qualified-release.py')
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)
LAUNCHER = (ROOT / 'factory/launch.sh').read_text()


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        bundle = self.home / 'factory.tgz'
        release_inputs = self.home / 'release-inputs'
        self.source_files, pins, adapter = build_release(release_inputs)
        for patcher in (mock.patch.object(deployment, 'PINS', pins),
                        mock.patch.object(deployment, 'QUALIFIED_ADAPTER_BYTES', adapter, create=True)):
            patcher.start(); self.addCleanup(patcher.stop)
        deployment.prepare(release_inputs, bundle)
        with tarfile.open(bundle) as archive:
            archive.extractall(self.home, filter='data')
        self.release = self.home / 'qualified-release'

    def install(self):
        return deployment.deploy(self.release, self.home)

    def test_exact_bundle_excludes_dirty_host_and_preserves_dependencies(self):
        expected = self.source_files
        actual = {p.relative_to(self.home).as_posix() for p in (self.home / 'factory').rglob('*') if p.is_file()}
        self.assertEqual(actual, {n for n in expected if n.startswith('factory/')})
        self.assertNotIn('factory/public_collector.py', actual)
        self.assertNotIn('factory/finish.py', actual)
        source = self.home / 'unbug-bench'
        old = source / 'bin/check'; old.parent.mkdir(parents=True); old.write_text('old baked source')
        dependency = source / 'projects/medusa/node_modules/keep'
        dependency.parent.mkdir(parents=True); dependency.write_text('image dependency')
        dep_cache = dependency.parent / '__pycache__/dependency.pyc'
        dep_cache.parent.mkdir(); dep_cache.write_bytes(b'preserved dependency bytecode')
        self.assertEqual(self.install()['source_files_verified'], len(self.source_files))
        self.assertEqual(dep_cache.read_bytes(), b'preserved dependency bytecode')
        self.assertEqual(dependency.read_text(), 'image dependency')
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(), expected['bin/check'])

    def test_installed_npm_links_and_hardlinks_survive_exact_source_replacement(self):
        source = self.home / 'unbug-bench'
        deps = source / 'projects/medusa/node_modules'
        cli = deps / '@medusajs/cli/cli.js'
        cli.parent.mkdir(parents=True); cli.write_text('public CLI fixture')
        binary = deps / '.bin/medusa'
        binary.parent.mkdir(); binary.symlink_to('../@medusajs/cli/cli.js')
        package = deps / 'linked-package'
        package.symlink_to('@medusajs/cli', target_is_directory=True)
        hardlink = deps / 'binary-copy'
        os.link(cli, hardlink)
        build = source / 'projects/medusa/.medusa'
        build.mkdir(); (build / 'linked-output').symlink_to('../node_modules/linked-package')
        before = {p: p.lstat().st_ino for p in (deps, cli, binary, package, hardlink, build)}
        self.assertEqual(self.install()['source_files_verified'], len(self.source_files))
        self.assertEqual({p: p.lstat().st_ino for p in before}, before)
        self.assertEqual(os.readlink(binary), '../@medusajs/cli/cli.js')
        self.assertEqual(os.readlink(package), '@medusajs/cli')
        self.assertEqual(cli.stat().st_ino, hardlink.stat().st_ino)
        self.assertEqual(hardlink.stat().st_nlink, 2)
        self.assertEqual(binary.read_text(), 'public CLI fixture')
        self.assertEqual(deployment.deploy(self.release, self.home, True)['source_files_verified'], len(self.source_files))

    def boundary(self, drift=''):
        start = LAUNCHER.index('  if [ -n "$qualified_release" ]; then\n    boat ssh', LAUNCHER.index('batch_status=0'))
        end = LAUNCHER.index('  # Real keys, not boat', start)
        script = '''set -eu
qualified_release=yes; id=fixture; state=$HOME; root=$HOME/host; here=$root/factory
admission_snapshot=""; selection_snapshot=""; reuse_worker=""
boat() {
  test "$1" = ssh
  case "$3" in
    *"--version"*) DRIFT ;;
    *factory/worker_release.py*) touch "$HOME/runtime-imported" ;;
    *"print(run.bench_manifest())"*) printf '%064d\n' 0 ;;
    *) /bin/sh -c "$3" ;;
  esac
}
opencode_pin='--version'
''' .replace('DRIFT', drift or ':')
        script += LAUNCHER[start:end] + '\ntouch "$HOME/credentials-delivered"\n'
        return subprocess.run(['/bin/sh', '-c', script], env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True)

    def test_launcher_success_verifies_all_source_before_delivery(self):
        result = self.boundary()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / 'credentials-delivered').exists())
        self.assertEqual(json.loads((self.home / 'fixture.source-verify.json').read_text())['source_files_verified'], len(self.source_files))

    def test_full_source_mismatch_and_extra_factory_stop_before_delivery(self):
        for command in ('echo drift > "$HOME/unbug-bench/bin/check"',
                        'touch "$HOME/factory/extra.py"',
                        'touch "$HOME/unbug-bench/factory/extra.py"'):
            with self.subTest(command=command):
                self.install()
                result = self.boundary(command)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('full source verification failed before credentials', result.stderr)
                self.assertFalse((self.home / 'credentials-delivered').exists())
                for path in (self.home / 'factory/extra.py', self.home / 'unbug-bench/factory/extra.py'):
                    path.unlink(missing_ok=True)

    def cached_payload(self, target):
        payload = self.home / 'harmless-cache-payload.py'
        marker = self.home / 'cache-executed'
        payload.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        cache = Path(importlib.util.cache_from_source(str(target)))
        cache.parent.mkdir(parents=True, exist_ok=True)
        py_compile.compile(str(payload), cfile=str(cache), dfile=str(target), doraise=True,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        return cache, marker

    def test_inherited_unchecked_hash_cache_cleaned_before_import_or_delivery(self):
        self.install()
        for name in ('factory/budget.py', 'unbug-bench/factory/budget.py', 'unbug-bench/bin/bench.py'):
            with self.subTest(name=name):
                target = self.home / name
                cache, marker = self.cached_payload(target)
                # Establish that -B alone still executes this deterministic payload.
                control = subprocess.run(['python3', '-B', '-c',
                    'import sys; sys.path.insert(0, sys.argv[1]); __import__(sys.argv[2])',
                    str(target.parent), target.stem], capture_output=True, text=True)
                self.assertEqual(control.returncode, 0, control.stderr)
                self.assertTrue(marker.exists())
                marker.unlink()
                with self.assertRaises(ValueError):
                    deployment.deploy(self.release, self.home, verify_only=True)
                result = self.boundary()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((self.home / 'credentials-delivered').exists())
                (self.home / 'credentials-delivered').unlink()
                (self.home / 'runtime-imported').unlink()
                self.assertFalse(marker.exists())
                self.assertFalse(cache.exists())  # Quarantined, never imported.
                receipt = (self.home / 'fixture.source-install.json').read_text()
                saved = json.loads((self.home / json.loads(receipt)['preparation_receipt']).read_text())
                self.assertIn({'path': cache.relative_to(self.home).as_posix(), 'type': 'file'}, saved['extra_entries'])

    def test_post_preparation_cache_and_mode_drift_stop_before_import_admission_credentials(self):
        self.install()
        cache, marker = self.cached_payload(self.home / 'payload-target.py')
        source_cache = str(cache)
        factory_cache = Path(importlib.util.cache_from_source(str(self.home / 'factory/budget.py')))
        source_cache_path = Path(importlib.util.cache_from_source(str(self.home / 'unbug-bench/bin/bench.py')))
        original_factory_mode = (self.home / 'factory/budget.py').stat().st_mode & 0o7777
        for command in (
            'mkdir -p "$HOME/factory/__pycache__"; cp "' + source_cache + '" "' + str(factory_cache) + '"',
            'mkdir -p "$HOME/unbug-bench/bin/__pycache__"; cp "' + source_cache + '" "' + str(source_cache_path) + '"',
            'chmod 0666 "$HOME/unbug-bench/bin/run-exam"',
            'chmod 4755 "$HOME/factory/budget.py"',
            'chmod 2644 "$HOME/unbug-bench/factory/budget.py"',
        ):
            with self.subTest(command=command):
                result = self.boundary(command)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('full source verification failed before credentials', result.stderr)
                for sentinel in (marker, self.home / 'runtime-imported', self.home / 'statements',
                                 self.home / 'credentials-delivered'):
                    self.assertFalse(sentinel.exists())
                for path in (factory_cache, source_cache_path):
                    path.unlink(missing_ok=True)
                (self.home / 'factory/budget.py').chmod(original_factory_mode)
                (self.home / 'unbug-bench/factory/budget.py').chmod(0o644)
                (self.home / 'unbug-bench/bin/run-exam').chmod(0o755)
                self.install()

    def test_existing_work_refuses_install_without_reset(self):
        work = self.home / 'work'; work.mkdir(); ledger = work / 'ledger'; ledger.write_text('keep')
        with self.assertRaisesRegex(ValueError, 'fresh worker'):
            self.install()
        self.assertEqual(ledger.read_text(), 'keep')
        ledger.unlink(); work.rmdir()

    def test_symlink_source_refused_before_any_source_update(self):
        outside = self.home / 'outside'; outside.mkdir()
        sentinel = outside / 'check'; sentinel.write_text('keep')
        root = self.home / 'unbug-bench'; root.mkdir()
        (root / 'bin').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.install()
        self.assertEqual(sentinel.read_text(), 'keep')
        self.assertFalse((root / 'CONTESTANT.md').exists())

    def test_old_image_extras_quarantined_with_paths_only_receipt(self):
        self.install()
        extras = []
        for directory in sorted(deployment.OWNED_DIRS):
            path = self.home / 'unbug-bench' / directory / 'stale.py'
            path.write_text('raise RuntimeError("PRIVATE FIXTURE CONTENT")')
            extras.append(path.relative_to(self.home).as_posix())
        extra = self.home / 'factory/finish.py'
        extra.write_text('PRIVATE FIXTURE CONTENT')
        extras.append('factory/finish.py')
        sentinels = ['unrelated/keep', 'unbug-bench/unrelated/keep',
                     'unbug-bench/projects/medusa/node_modules/keep',
                     'unbug-bench/projects/medusa/.medusa/keep',
                     'unbug-bench/projects/medusa/seed-ids.json']
        for name in sentinels:
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('preserved')
        result = self.install()
        receipt = (self.home / result['preparation_receipt']).read_text()
        self.assertNotIn('PRIVATE FIXTURE CONTENT', receipt)
        self.assertEqual(json.loads(receipt)['extra_entries'],
                         [{'path': n, 'type': 'file'} for n in sorted(extras)])
        for name in extras:
            self.assertFalse((self.home / name).exists())
        for name in sentinels:
            self.assertEqual((self.home / name).read_text(), 'preserved')
        self.assertEqual(deployment.deploy(self.release, self.home, True)['source_files_verified'], len(self.source_files))

    def test_unsafe_entries_and_occupied_sealed_refuse_without_mutation(self):
        self.install()
        sentinel = self.home / 'unbug-bench/bin/check'
        before = sentinel.read_bytes()
        for kind in ('symlink', 'fifo', 'writable', 'sealed', 'dependency-link'):
            with self.subTest(kind=kind):
                path = self.home / ('sealed/ledger' if kind == 'sealed' else
                                    'unbug-bench/projects/medusa/node_modules' if kind == 'dependency-link' else
                                    'unbug-bench/tests/unsafe')
                path.parent.mkdir(parents=True, exist_ok=True)
                if kind in ('symlink', 'dependency-link'):
                    path.symlink_to(sentinel)
                elif kind == 'fifo':
                    os.mkfifo(path)
                else:
                    path.write_text('keep')
                    if kind == 'writable': path.chmod(0o666)
                stages = set(self.home.glob('.qualified-source-*'))
                with self.assertRaises(ValueError):
                    self.install()
                self.assertEqual(sentinel.read_bytes(), before)
                self.assertEqual(set(self.home.glob('.qualified-source-*')), stages)
                path.unlink()

    def test_target_drift_during_staging_refuses_before_replacement(self):
        self.install()
        sentinel = self.home / 'unbug-bench/bin/check'
        before = sentinel.read_bytes()
        original = deployment.inspect_targets
        calls = []
        def changed(*args):
            calls.append(True)
            if len(calls) == 2:
                (self.home / 'factory/appeared.py').write_text('race fixture')
            return original(*args)
        with mock.patch.object(deployment, 'inspect_targets', changed):
            with self.assertRaisesRegex(ValueError, 'changed during preparation'):
                self.install()
        self.assertEqual(sentinel.read_bytes(), before)
        self.assertFalse((self.home / deployment.INCOMPLETE).exists())

    def test_interrupted_swap_blocks_delivery_and_verify_even_if_source_matches(self):
        self.install()
        original = Path.rename
        swapped = []
        def interrupt(path, target):
            if 'quarantine' in str(target):
                swapped.append(str(path))
                if len(swapped) == 2:
                    raise OSError('simulated interruption')
            return original(path, target)
        with mock.patch.object(Path, 'rename', interrupt):
            with self.assertRaisesRegex(OSError, 'interruption'):
                self.install()
        with self.assertRaisesRegex(ValueError, 'incomplete source preparation'):
            deployment.deploy(self.release, self.home, True)
        result = self.boundary()
        self.assertNotEqual(result.returncode, 0)
        for name in ('runtime-imported', 'credentials-delivered', 'statements'):
            self.assertFalse((self.home / name).exists())

    def test_release_input_and_helper_tamper_are_rejected(self):
        for name in deployment.PINS:
            with self.subTest(name=name):
                path = self.release / name
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b'\n')
                    with self.assertRaisesRegex(ValueError, 'unqualified release input'):
                        self.install()
                finally:
                    path.write_bytes(original)
        adapter = self.home / 'bin/qualified-release.py'
        adapter.parent.mkdir(); adapter.write_text('raise SystemExit("EXECUTED")')
        start = LAUNCHER.index('qualified_adapter() {')
        end = LAUNCHER.index('\nif [ -n "$qualified_release" ]', start)
        result = subprocess.run(['/bin/sh', '-c', 'root=$1\n' + LAUNCHER[start:end] + '\nqualified_adapter prepare', 'sh', str(self.home)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('review launcher fingerprint', result.stderr)
        self.assertNotIn('EXECUTED', result.stderr)

    def test_installer_requires_explicit_digest_and_count_bindings(self):
        source = ROOT / 'tools/install_source.py'
        namespace = {'__name__': 'installer_fixture', '__file__': str(source)}
        exec(compile(source.read_bytes(), str(source), 'exec'), namespace)
        manifest = self.release / 'source-manifest.json'
        with self.assertRaisesRegex(ValueError, 'unqualified manifest'):
            namespace['load_manifest'](manifest)
        namespace['MANIFEST_SHA'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
        for count in (None, True, 0, len(self.source_files) + 1):
            with self.subTest(count=count):
                namespace['SOURCE_COUNT'] = count
                with self.assertRaisesRegex(ValueError, 'source count'):
                    namespace['load_manifest'](manifest)
        namespace['SOURCE_COUNT'] = len(self.source_files)
        files = namespace['load_manifest'](manifest)
        with self.assertRaisesRegex(ValueError, 'unqualified bundle'):
            namespace['bundle_modes'](self.release / 'public-source.tar.gz', files)

    def readiness_boundary(self, response, delayed=False, sequence=None):
        (self.home / 'host-public-source.tgz').write_bytes((self.home / 'factory.tgz').read_bytes())
        host = self.home / 'host'
        (host / 'tools').mkdir(parents=True, exist_ok=True)
        (host / 'bin').mkdir(exist_ok=True)
        (host / 'tools/boat_readiness.py').write_bytes((ROOT / 'tools/boat_readiness.py').read_bytes())
        provider = host / 'bin/boat-call'
        provider.write_text('#!/usr/bin/env python3\n' +
            'import json, pathlib, sys, time\n' +
            'h=pathlib.Path(' + repr(str(self.home)) + ')\n' +
            'assert sys.argv[1:]==["info","fixture","--json"]\n' +
            ('if not (h/"polled").exists():\n (h/"polled").touch()\n print(json.dumps({"sandbox":' + repr({**response, 'hydrated': False}) + '}));sys.exit()\n' +
             '(h/"stop-writer").touch()\nwhile not (h/"writer-stopped").exists(): time.sleep(.001)\n' if delayed else '') +
            'print(json.dumps({"sandbox":' + repr(response) + '}))\n')
        if sequence is not None:
            provider.write_text('#!/usr/bin/env python3\nimport json,pathlib,sys\n' +
                'h=pathlib.Path(' + repr(str(self.home)) + ')\n' +
                'assert sys.argv[1:]==["info","fixture","--json"]\n' +
                'p=h/"poll-count"; n=int(p.read_text()) if p.exists() else 0; p.write_text(str(n+1))\n' +
                'values=' + repr(sequence) + '\n' +
                'if n < len(values)-1: assert not (h/"events").exists()\n' +
                'print(json.dumps({"sandbox":values[min(n,len(values)-1)]}))\n')
            (self.home / 'writer-stopped').touch()
        provider.chmod(0o755)
        a = LAUNCHER.index('qualified_readiness() {')
        b = LAUNCHER.index('\nif [ -n "$qualified_release" ]', a)
        start = LAUNCHER.index('  if [ -n "$qualified_release" ]; then\n    readiness_mono=', LAUNCHER.index('batch_status=0'))
        end = LAUNCHER.index('  # Fork hydration', start)
        gate = LAUNCHER[a:b]
        if sequence is not None:
            # Advance only the helper clock; exercise its actual pinned bytes and shell order.
            gate = gate.replace('import hashlib, pathlib, sys',
                'import hashlib, pathlib, sys, time\nclock=[time.monotonic()]\ntime.monotonic=lambda:clock[0]\ntime.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)')
        script = 'set -eu\n' + gate + '''
root=$HOME/host; qualified_release=yes; reuse_worker=""; serial=0
state=$HOME; ttl_seconds=1800; margin=420; spend_file=$HOME/public-spend.json
bundle=$HOME/host-public-source.tgz
boat() {
  if [ "$1" = --stdin ]; then
    shift
    test -f "$HOME/writer-stopped"
  fi
  echo "$1" >> "$HOME/events"
  test "$1" = ssh
  /bin/sh -c "$3"
}
guard_new() { id=fixture; }
''' + LAUNCHER[start:end] + '\ntouch "$HOME/credentials-delivered"\n'
        return subprocess.run(['/bin/sh', '-c', script], env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True)

    def test_readiness_refusals_never_transfer_install_or_deliver(self):
        import datetime
        value = dict(id='fixture', type='default', ttlSeconds=1800,
            archiveAfter=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=1800)).isoformat(),
            holdsCreatorLogins=False, monitoring=False, snapshots=False, state='idle', health='ok',
            error=None, setupError=None, setupStatus=None, degradedSince=None, hydrated=True, hydration=None)
        missing = dict(value); del missing['hydrated']
        missing_progress = dict(value); del missing_progress['hydration']
        expired = dict(value, archiveAfter=datetime.datetime.now(datetime.timezone.utc).isoformat())
        cases = [missing, missing_progress, expired] + [{**value, **patch} for patch in
            ({'id':'other'}, {'hydrated':'true'}, {'error':'failed'}, {'hydration':{}}, {'health':'bad'})]
        for case in cases:
            result = self.readiness_boundary(case)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            for name in ('events', 'credentials-delivered', 'unbug-bench', '.qualified-source-incomplete'):
                self.assertFalse((self.home / name).exists(), name)
            receipt = self.home / 'public-spend-fixture.readiness.json'
            self.assertEqual(json.loads(receipt.read_text())['outcome'], 'refused')
            receipt.unlink()

    def test_actual_launcher_waits_through_folding_to_completion(self):
        import datetime
        expiry = (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=1800)).isoformat()
        sequence = folding_sequence('fixture', expiry)
        result = self.readiness_boundary(sequence[-1], sequence=sequence)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads((self.home/'public-spend-fixture.readiness.json').read_text())
        self.assertEqual(receipt['attempts'], 6)
        self.assertEqual(receipt['observed']['hydrated'], True)
        self.assertEqual(receipt['outcome'], 'ready')
        self.assertEqual(json.loads((self.home/'fixture.source-install.json').read_text())['source_files_verified'], len(self.source_files))

    def test_actual_launcher_never_complete_times_out_before_mutation(self):
        import datetime
        expiry = (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=1800)).isoformat()
        value = folding_sequence('fixture', expiry)[0]
        result = self.readiness_boundary(value, sequence=[value])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('TimeoutError: readiness deadline reached', result.stderr)
        self.assertFalse((self.home/'events').exists())
        self.assertFalse((self.home/'credentials-delivered').exists())
        receipt = json.loads((self.home/'public-spend-fixture.readiness.json').read_text())
        self.assertEqual(receipt['outcome'], 'refused')
        self.assertEqual(receipt['attempts'], 60)

    def test_actual_launcher_waits_until_background_destination_writer_finishes(self):
        import datetime
        import threading
        value = dict(id='fixture', type='default', ttlSeconds=1800,
            archiveAfter=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=1800)).isoformat(),
            holdsCreatorLogins=False, monitoring=False, snapshots=False, state='idle', health='ok',
            error=None, setupError=None, setupStatus=None, degradedSince=None, hydrated=True, hydration=None)
        done = threading.Event()
        def writer():
            while not done.is_set() and not (self.home / 'stop-writer').exists():
                dest = self.home / 'unbug-bench/projects/hydrating'
                dest.mkdir(parents=True, exist_ok=True)
                (dest / 'background').write_text('public hydration fixture')
                done.wait(.001)
            (self.home / 'writer-stopped').touch()
        thread = threading.Thread(target=writer); thread.start()
        try:
            result = self.readiness_boundary(value, delayed=True)
        finally:
            done.set(); thread.join()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.home/'fixture.source-install.json').read_text())['source_files_verified'], len(self.source_files))
        self.assertTrue((self.home/'credentials-delivered').exists())
        self.assertEqual(json.loads((self.home/'public-spend-fixture.readiness.json').read_text())['attempts'], 2)
        self.assertFalse((self.home/'unbug-bench/projects/hydrating').exists())

    def test_destination_recreation_at_swap_refuses_with_incomplete_marker(self):
        self.install()
        original = Path.rename
        def recreate(path, target):
            result = original(path, target)
            if path == self.home / 'unbug-bench/projects' and 'quarantine' in str(target):
                path.mkdir(); (path / 'background').write_text('public writer fixture')
            return result
        with mock.patch.object(Path, 'rename', recreate):
            with self.assertRaises(OSError): self.install()
        self.assertTrue((self.home / deployment.INCOMPLETE).exists())
        with self.assertRaisesRegex(ValueError, 'incomplete source preparation'):
            deployment.deploy(self.release, self.home, True)
        for name in ('credentials-delivered', 'runtime-imported', 'statements'):
            self.assertFalse((self.home / name).exists())

    def test_holder_still_pins_launcher_and_original_root(self):
        spec = importlib.util.spec_from_file_location('holder', ROOT / 'factory/key_holder.py')
        holder = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, 'path', [str(ROOT / 'factory'), *sys.path]):
            spec.loader.exec_module(holder)
        self.assertIn('factory/launch.sh', holder.PINNED)
        baseline = holder.fingerprint(ROOT)
        # Compute the same fingerprint over public temporary copies, then mutate.
        fixture = self.home / 'holder-root'
        for name in holder.PINNED:
            path = fixture / name; path.parent.mkdir(parents=True, exist_ok=True)
            if (ROOT / name).is_file(): path.write_bytes((ROOT / name).read_bytes())
        self.assertEqual(holder.fingerprint(fixture), baseline)
        (fixture / 'factory/launch.sh').write_text('changed')
        self.assertNotEqual(holder.fingerprint(fixture), baseline)
        self.assertIn("policy['root'] != str(ROOT)", (ROOT / 'factory/key_holder.py').read_text())


if __name__ == '__main__':
    unittest.main()
