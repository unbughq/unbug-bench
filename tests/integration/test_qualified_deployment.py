"""Offline deployment checks against hermetic synthetic release inputs."""
import hashlib
import importlib.util
import json
import os
import py_compile
import runpy
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


    def cached_payload(self, target):
        payload = self.home / 'harmless-cache-payload.py'
        marker = self.home / 'cache-executed'
        payload.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        cache = Path(importlib.util.cache_from_source(str(target)))
        cache.parent.mkdir(parents=True, exist_ok=True)
        py_compile.compile(str(payload), cfile=str(cache), dfile=str(target), doraise=True,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        return cache, marker


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

    def test_image_prunes_resurrected_files_and_refuses_source_drift(self):
        installer = runpy.run_path(str(self.release / 'install-source.py'))
        files = installer['load_manifest'](self.release / 'source-manifest.json')
        root = self.home / 'unbug-bench'
        bundle = self.release / 'public-source.tar.gz'
        installer['install'](bundle, root, files)
        extra = root / 'retired/launcher.py'
        extra.parent.mkdir(); extra.write_text('old snapshot file')
        dependency = root / 'projects/medusa/node_modules/keep'
        dependency.parent.mkdir(parents=True); dependency.write_text('generated dependency')
        installer['prune_image'](root, files, bundle)
        self.assertFalse(extra.exists())
        self.assertEqual(dependency.read_text(), 'generated dependency')
        installer['prune_image'](root, files, bundle)  # a replay is harmless
        extra.write_text('must survive refused preparation')
        source = root / 'bin/check'; original = source.read_bytes()
        source.write_bytes(b'changed scientific source')
        with self.assertRaises(ValueError): installer['prune_image'](root, files, bundle)
        self.assertTrue(extra.exists())
        self.assertEqual(source.read_bytes(), b'changed scientific source')
        source.write_bytes(original)
        link = root / 'unexpected-link'; link.symlink_to(self.home)
        with self.assertRaises(ValueError): installer['prune_image'](root, files, bundle)
        self.assertTrue(extra.exists()); self.assertTrue(link.is_symlink())


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


if __name__ == '__main__':
    unittest.main()
