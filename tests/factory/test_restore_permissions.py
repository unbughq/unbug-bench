"""Real tar restore under a private umask, including legacy stripped checkpoints."""
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
from case_permissions import restore_archive, normalize_case_tree


class RestorePermissions(unittest.TestCase):
    def archive(self, root, stripped):
        source = root / 'source/case-test'
        (source / 'case/projects/trade').mkdir(parents=True)
        for name, mode in [('case/projects/trade/service.py', 0o644),
                           ('case/projects/trade/start.sh', 0o755), ('.casekey', 0o600),
                           ('case/.env', 0o600)]:
            p = source / name; p.write_text('synthetic fixture'); p.chmod(mode)
        bundle = root / 'checkpoint.tgz'
        with tarfile.open(bundle, 'w:gz') as archive:
            def modes(m):
                if stripped:
                    m.mode = 0o700 if m.isdir() or m.mode & 0o111 else 0o600
                return m
            archive.add(source, arcname='case-test', filter=modes)
        return bundle

    def test_private_restore_repairs_legacy_and_preserves_secrets(self):
        for stripped in (False, True):
            with self.subTest(stripped=stripped), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); archive = self.archive(root, stripped)
                with tarfile.open(archive) as stored:
                    self.assertEqual(stored.getmember('case-test/case/projects/trade/service.py').mode, 0o600 if stripped else 0o644)
                baseline = root / 'baseline'; baseline.mkdir()
                with archive.open('rb') as stream:
                    subprocess.run(['tar', '-xzf', '-', '-C', str(baseline)], stdin=stream, check=True, umask=0o077)
                self.assertEqual((baseline / 'case-test/case/projects/trade/service.py').stat().st_mode & 0o044, 0)
                home = root / 'home'; home.mkdir(mode=0o700)
                for name in ('casekey', '.factory-r2', 'keys'):
                    p = home / name; p.write_text('secret'); p.chmod(0o600)
                destination = home / 'work'; destination.mkdir(mode=0o700)
                with archive.open('rb') as stream:
                    subprocess.run([sys.executable, str(ROOT / 'factory/case_permissions.py'),
                        '--extract-to', str(destination), '--case-tree', str(destination / 'case-test/case')],
                        stdin=stream, umask=0o077, check=True)
                case = destination / 'case-test/case'
                self.assertEqual(stat.S_IMODE((case / 'projects/trade/service.py').stat().st_mode), 0o644)
                self.assertEqual(stat.S_IMODE((case / 'projects/trade/start.sh').stat().st_mode), 0o755)
                self.assertEqual(stat.S_IMODE((case / 'projects/trade').stat().st_mode), 0o755)
                for p in [home / n for n in ('casekey', '.factory-r2', 'keys')] + [destination / 'case-test/.casekey', case / '.env']:
                    self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)

    def test_links_cannot_change_outside_secret_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); case = root / 'case'; case.mkdir()
            secret = root / 'secret'; secret.write_text('secret'); secret.chmod(0o600)
            (case / 'link').symlink_to(secret)
            (case / 'dir-link').symlink_to(root, target_is_directory=True)
            normalize_case_tree(case)
            self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
            os.link(secret, case / 'hardlink')
            with self.assertRaisesRegex(ValueError, 'hardlink'):
                normalize_case_tree(case)
            self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)

    def test_bench_copy_bound_separately_from_runner_copy(self):
        sys.path.insert(0, str(ROOT / 'bin'))
        import bench
        import gate_state
        import run
        from types import SimpleNamespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); public = root / 'unbug-bench'; factory = root / 'factory'
            factory.mkdir(); (factory / 'case_permissions.py').write_text('runner copy')
            names = ('factory/case_permissions.py', 'cases/medusa-oversell/checker/check.sql',
                     'cases/medusa-oversell/traffic/run.mjs', 'bin/bench.py', 'bin/bench_judging.py',
                     'bin/refusal.py', 'projects/medusa/seed-ids.json')
            for name in names:
                p = public / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('original')
            c = SimpleNamespace(args=SimpleNamespace(bench_workers=1))
            helper = public / 'factory/case_permissions.py'
            with patch.object(run, 'BENCH', public), patch.object(bench, 'ROOT', public), \
                 patch.object(bench, 'IDS', public / 'projects/medusa/seed-ids.json'), \
                 patch.object(gate_state, 'RUNNER', factory / 'run.py'):
                dependencies = lambda: gate_state.dependency_files(c, ['factory/case_permissions.py'], public)
                before = dependencies(); manifest = run.bench_manifest(); fingerprint = bench.bench_fingerprint()
                helper.write_text('changed bench copy only')
                self.assertNotEqual(before, dependencies())
                self.assertNotEqual(manifest, run.bench_manifest())
                self.assertNotEqual(fingerprint, bench.bench_fingerprint())
                self.assertEqual(before['factory/case_permissions.py'], dependencies()['factory/case_permissions.py'])

    def test_inventory_patch_created_under_private_umask(self):
        sys.path.insert(0, str(ROOT / 'bin'))
        import bench
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); project = root / 'project'; project.mkdir()
            (project / 'service.py').write_text('synthetic')
            (project / 'service.py').chmod(0o600)
            guard = root / 'guard'; guard.mkdir()
            (guard / 'services.patch').touch()
            def command(args, **kwargs):
                if args[:3] == ['git', 'apply', '--numstat']: return '1\t0\ttrade/new.py\n'
                if args[:2] == ['git', 'apply'] and '--check' not in args:
                    p = kwargs['cwd'] / 'trade/new.py'; p.write_text('synthetic'); p.chmod(0o600)
                if 'build' in args:
                    config = __import__('json').loads((root / 'override.json').read_text())
                    context = Path(config['services']['trade']['build']['context'])
                    for name in ('new.py', 'service.py'):
                        self.assertEqual(stat.S_IMODE((context / name).stat().st_mode), 0o644)
                return ''
            with patch.object(bench, 'command', side_effect=command):
                bench.build_inventory_services([{'name':'trade','project':project}], guard, [], [], root / 'override.json')
            self.assertEqual(stat.S_IMODE((project / 'service.py').stat().st_mode), 0o600)


if __name__ == '__main__': unittest.main()
