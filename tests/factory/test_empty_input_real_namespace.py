"""Empty input on real retained sealed artifacts and real Git (docs/designs/empty-input-namespace.md).

Real: the tracked sealed/ inventory (used read-only, or copied byte-identically
under its real name) and the real git binary. Authored: temporary repositories
and, in HolderWiringTests, the fixture batch's case name. Retained case names are
unreachable from a batch manifest (uppercase T/Z), so these tests do not close
new-batch-auth-inputs-1.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tests/factory'), str(ROOT / 'factory')]
import batch
import batch_holder as holder
import test_batch_holder as holder_fixtures

CASE_FILE = re.compile(r'\.?(case-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6})\..+')


def real_case_files(sealed):
    """Top-level real files whose name is <case>.* or .<case>.* (transfer locks)."""
    return sorted((p, CASE_FILE.fullmatch(p.name).group(1)) for p in sealed.iterdir()
                  if CASE_FILE.fullmatch(p.name) and p.is_file() and not p.is_symlink())


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args, cwd, env=None):
    return subprocess.run(['git', *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=30)


def refused(root, directory, case):
    try: holder.empty_input(root, directory, case)
    except ValueError as error: return str(error) == 'request_refused'
    return False


class RealInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.tmp = Path(self.tmp.name)

    def test_every_real_retained_file_alone_occupies_its_namespace(self):
        files = real_case_files(ROOT / 'sealed')
        names = [p.name for p, _ in files]
        # Guard against a vacuous pass: the real suffixes outside collection_files are present.
        self.assertGreaterEqual(len(files), 100)
        self.assertTrue(any(n.endswith('.throwaway-key.txt') for n in names))
        self.assertTrue(any(n.startswith('.') and n.endswith('.transfer.lock') for n in names))
        for index, (original, case) in enumerate(files):
            with self.subTest(name=original.name):
                root = self.tmp / str(index); (root / 'sealed').mkdir(parents=True)
                copy = root / 'sealed' / original.name
                shutil.copyfile(original, copy)
                self.assertEqual(digest(copy), digest(original))
                self.assertTrue(refused(root, root / 'batch', case))
                for neighbour in (case + '0', case[:-1]):
                    holder.empty_input(root, root / 'batch', neighbour)
                self.assertFalse((root / 'batch').exists())
                shutil.rmtree(root)

    @unittest.skipIf(not os.path.lexists(ROOT / '.git'), 'installed release: no Git metadata to discover')
    def test_real_checkout_in_place_with_real_git(self):
        directories = batch.sealed_directories(ROOT)
        result = git('rev-parse', '--path-format=absolute', '--git-common-dir', cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        common = Path(result.stdout.strip()).resolve().parent / 'sealed'
        self.assertIn(ROOT / 'sealed', directories); self.assertIn(common, directories)
        entries = [entry for sealed in directories if sealed.is_dir() for entry in real_case_files(sealed)]
        self.assertTrue(entries)
        before = {str(p): (p.lstat().st_mtime_ns, digest(p)) for p, _ in entries}
        batch_directory = self.tmp / 'batches/practice'
        for case in sorted({case for _, case in entries}):
            with self.subTest(case=case):
                self.assertTrue(refused(ROOT, batch_directory, case))
        fresh = 'case-b-empty-input-fresh-j'
        self.assertFalse(any(p.name.startswith(fresh) for sealed in directories if sealed.is_dir()
                             for p in sealed.iterdir()))
        holder.empty_input(ROOT, batch_directory, fresh)
        # Only entries this test enumerated: the common sealed/ is shared with other sessions.
        self.assertEqual({str(p): (p.lstat().st_mtime_ns, digest(p)) for p, _ in entries}, before)
        self.assertFalse(batch_directory.exists())


class RealGitDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name).resolve() / 'parent'
        self.parent.mkdir()
        self.assertEqual(git('init', '-q', cwd=self.parent).returncode, 0)
        # Real retained ciphertext under an authored archive name, only in the enclosing repository.
        cipher = ROOT / 'sealed/case-20261017T212118Z-1ad7fa.statement.age'
        (self.parent / 'sealed').mkdir()
        shutil.copyfile(cipher, self.parent / 'sealed/case-b-x-j.checkpoint.tar.gz.age')
        self.checkout = self.parent / 'checkout'; (self.checkout / 'sealed').mkdir(parents=True)

    def assert_bounded(self):
        with self.assertRaises((subprocess.SubprocessError, OSError)):
            batch.sealed_directories(self.checkout)
        self.assertTrue(refused(self.checkout, self.checkout / 'batch', 'case-b-x-j'))
        self.assertEqual(batch.restore_inventory(self.checkout), [])  # Local-only fallback.

    def test_dangling_git_symlink_does_not_walk_up(self):
        (self.checkout / '.git').symlink_to('absent-git-metadata')
        result = git('-C', str(self.checkout), 'rev-parse', '--git-common-dir', cwd=self.checkout)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '../.git'))  # Unbounded Git walks up.
        self.assert_bounded()

    def test_empty_git_directory_does_not_walk_up(self):
        (self.checkout / '.git').mkdir()
        self.assert_bounded()

    def test_inherited_git_dir_is_ignored(self):
        self.assertEqual(git('init', '-q', cwd=self.checkout).returncode, 0)
        env = {'GIT_DIR': str(self.parent / '.git'), 'GIT_COMMON_DIR': str(self.parent / '.git'),
               'GIT_WORK_TREE': str(self.parent)}
        with patch.dict(os.environ, env):
            self.assertEqual(batch.sealed_directories(self.checkout), [self.checkout / 'sealed'])
            self.assertEqual(batch.restore_inventory(self.checkout), [])
            holder.empty_input(self.checkout, self.checkout / 'batch', 'case-b-x-j')

    def test_valid_gitfile_still_reaches_the_common_checkout(self):
        (self.checkout / '.git').write_text('gitdir: ' + str(self.parent / '.git') + '\n')
        self.assertEqual(batch.sealed_directories(self.checkout),
                         [self.parent / 'sealed', self.checkout / 'sealed'])
        self.assertTrue(refused(self.checkout, self.checkout / 'batch', 'case-b-x-j'))


class HolderWiringTests(unittest.TestCase):
    """Contract-level: real retained ledger bytes under the fixture case's authored name."""

    def setUp(self):
        self.h = holder_fixtures.HolderTests('test_lifecycle_status_ack_retirement_source_and_replay')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)
        ledger = next(r['card']['continuation_budget'] for r in holder_fixtures.accounting_fixtures.d.cards()
                      if r['card']['case'].endswith('e15450'))
        self.ledger = json.dumps(ledger).encode()
        self.case = self.h.record['jobs']['j']['case']

    def place(self, root=None):
        path = (root or self.h.root) / 'sealed' / (self.case + '.continuation-budget.json')
        path.parent.mkdir(exist_ok=True); path.write_bytes(self.ledger)
        return path

    def assert_terminal(self, op, result, spawns):
        self.assertIsInstance(result, ValueError); self.assertEqual(spawns, [])
        saved = self.h.ops()[op['operation_id']]
        self.assertEqual((saved['state'], saved['incident'], saved['dispatch_started']),
                         ('failed', 'preflight_refused', False))

    def test_new_empty_reservation_refuses_non_collection_name(self):
        self.place()
        with self.assertRaisesRegex(ValueError, 'request_refused'): self.h.reserve()
        self.assertFalse((self.h.directory / 'money.json').exists())
        self.assertFalse((self.h.directory / 'reservations.json').exists())

    def test_replay_survives_and_dispatch_is_terminal_at_first_check(self):
        op = self.h.reserve(); self.place()
        self.assertEqual(self.h.reserve(), op)  # Replay is a lookup, not new admission.
        self.assert_terminal(op, *self.h.preflight(op))

    def test_second_locked_check_catches_name_placed_during_preflight(self):
        op = self.h.reserve(); original = holder.empty_input; calls = []
        def observe(root, directory, case):
            original(root, directory, case); calls.append(case)
            if len(calls) == 1: self.place(root)
        with patch.object(holder, 'empty_input', side_effect=observe):
            result, spawns = self.h.preflight(op)
        self.assertEqual(len(calls), 1)  # The second call raised.
        self.assert_terminal(op, result, spawns)

    def test_unreadable_sealed_path_is_terminal_not_tempfail(self):
        op = self.h.reserve()
        sealed = self.h.root / 'sealed'
        if sealed.exists(): shutil.rmtree(sealed)
        sealed.write_bytes(b'')  # NotADirectoryError from os.scandir.
        with self.assertRaisesRegex(ValueError, 'request_refused'):
            holder.empty_input(self.h.root, self.h.directory, self.case)
        self.assert_terminal(op, *self.h.preflight(op))


if __name__ == '__main__':
    unittest.main()
