"""Synthetic crypto with throwaway keys; saved real PUBLIC card layout as payload.

No real keys/case archives, cloud or model calls. No Murphy closure claimed.
"""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('migration', ROOT / 'tools/migrate-legacy-checkpoints.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
PUBLIC_CARD = (ROOT / 'tests/factory/fixtures/isolation-timeouts/scorecard.json').read_bytes()
CASE = json.loads(PUBLIC_CARD)['case']


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.sealed = self.root / 'sealed'; self.sealed.mkdir()
        self.founder = bytearray(m.small(['age-keygen']))
        self.vm = bytearray(m.small(['age-keygen']))
        self.fpub, self.vpub = m.public(self.founder), m.public(self.vm)
        self.addCleanup(lambda: self.founder.__setitem__(slice(None), b'\0' * len(self.founder)))
        self.addCleanup(lambda: self.vm.__setitem__(slice(None), b'\0' * len(self.vm)))
        self.plan = dict(schema=1, founder_recipient=self.fpub, restore_recipient=self.vpub,
                         vm_restore_recipient=self.vpub, mac_root=str(self.sealed),
                         output_root=str(self.sealed / 'generations'), entries=[])
        self.card_path = self.sealed / (CASE + '.scorecard.json')
        self.input = self.sealed / (CASE + '.checkpoint.tar.gz.age')
        self.output = Path(self.plan['output_root'])

    def payload(self, large=False):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            info = tarfile.TarInfo(CASE + '/scorecard.json'); info.size = len(PUBLIC_CARD)
            archive.addfile(info, io.BytesIO(PUBLIC_CARD))
            if large:
                data = os.urandom(3 * m.CHUNK)
                info = tarfile.TarInfo(CASE + '/synthetic-random'); info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return stream.getvalue()

    def archive_entry(self, *, absent=False, large=False):
        data = self.payload(large)
        self.input.write_bytes(m.small(['age', '-r', self.fpub], data))
        source = m.file_sha(self.input)
        card = json.loads(PUBLIC_CARD)
        card['sha256'] = '1' * 64 if absent else source
        # Deliberate operational edits to a saved real public card; no generated case.
        self.card_path.write_text(json.dumps(card))
        row = dict(case=CASE, kind='card_bound_absent' if absent else 'checkpoint',
                   local_path=str(self.input), size=self.input.stat().st_size,
                   archive_sha256=source, card_path=str(self.card_path),
                   card_sha256=m.file_sha(self.card_path), card_archive_sha256=card['sha256'],
                   active_source=not absent)
        self.plan['entries'] = [row]
        return row

    def rewrap_entry(self):
        key = bytearray(m.small(['age-keygen']))
        self.input.write_bytes(m.small(['age', '-r', self.fpub, '-r', m.public(key)], self.payload()))
        archive_before = self.input.read_bytes()
        cache = self.root / 'cache/vm-only'; cache.mkdir(parents=True)
        old = cache / (CASE + '.casekey.age')
        old.write_bytes(m.small(['age', '-r', self.fpub], key))
        card = json.loads(PUBLIC_CARD); card['sha256'] = m.file_sha(self.input)
        self.card_path = cache / (CASE + '.scorecard.json'); self.card_path.write_text(json.dumps(card))
        archive = dict(name=self.input.name, size=self.input.stat().st_size,
                       sha256=card['sha256'], source_host='vm', source_path=str(self.input))
        row = dict(case=CASE, kind='rewrap_key', local_path=str(old), size=old.stat().st_size,
                   key_size=old.stat().st_size, key_sha256=m.file_sha(old),
                   archive_sha256=card['sha256'], card_archive_sha256=card['sha256'],
                   card_path=str(self.card_path), card_sha256=m.file_sha(self.card_path),
                   active_source=True, archives=[archive, {**archive, 'source_host': 'mac'}])
        self.plan['entries'] = [row]
        return row, key, archive_before, old.read_bytes()

    def freeze(self):
        path = self.root / 'plan.json'; path.write_text(json.dumps(self.plan))
        pin = m.file_sha(path)
        return path, pin, m.load_plan(path, pin, self.fpub, self.vpub)

    def migrate(self):
        _, pin, plan = self.freeze(); self.output.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            opened = m.preflight(plan, stack)
            with redirect_stderr(io.StringIO()):
                return m.run(plan, opened, self.founder, self.output, pin)

    def generation(self, row):
        _, pin, _ = self.freeze()
        return m.existing(self.output, row, pin)

    def test_archive_roundtrip_and_restart_keep_originals(self):
        row = self.archive_entry(); before = self.input.read_bytes(); card = self.card_path.read_bytes()
        self.assertEqual(self.migrate(), dict(migrated=1, failed=0, skipped=0))
        gen = self.generation(row)
        with (gen / 'casekey.age').open('rb') as stream:
            founder_key = m.unwrap(stream, self.founder)
            vm_key = m.unwrap(stream, self.vm)
        try:
            self.assertTrue(founder_key == vm_key)
            with m.processes(row['size']) as children:
                expected = m.plaintext_hash(self.input, self.founder, children)
                self.assertEqual(m.plaintext_hash(gen / 'archive.age', vm_key, children), expected)
            self.assertEqual(self.migrate(), dict(migrated=0, failed=0, skipped=1))
            self.assertEqual(self.input.read_bytes(), before)
            self.assertEqual(self.card_path.read_bytes(), card)
            self.assertEqual((gen / 'original-card.json').read_bytes(), card)
            self.assertFalse((self.output / 'current').exists())
            (gen / 'archive.age').write_bytes(b'corrupt')
            self.assertEqual(self.migrate()['failed'], 1)
        finally:
            founder_key[:] = b'\0' * len(founder_key); vm_key[:] = b'\0' * len(vm_key)

    def test_existing_key_from_vm_cache_rewraps_without_archive_copy(self):
        row, key, archive_before, old_before = self.rewrap_entry()
        try:
            self.assertEqual(m.stanzas(Path(row['local_path'])), 1)
            self.assertEqual(self.migrate()['migrated'], 1)
            gen = self.generation(row)
            self.assertEqual(gen.name, 'key-' + row['key_sha256'])
            self.assertEqual({p.name for p in gen.iterdir()},
                             {'casekey.age', 'original-card.json', 'migration.json', 'manifest.json'})
            for owner in (self.founder, self.vm):
                with (gen / 'casekey.age').open('rb') as stream:
                    opened = m.unwrap(stream, owner)
                try:
                    self.assertTrue(opened == key)
                    with m.processes(row['size']) as children:
                        self.assertEqual(m.plaintext_hash(self.input, opened, children),
                                         m.plaintext_hash(self.input, self.founder, children))
                finally:
                    opened[:] = b'\0' * len(opened)
            self.assertEqual(Path(row['local_path']).read_bytes(), old_before)
            self.assertEqual(self.input.read_bytes(), archive_before)
            record = json.loads((gen / 'migration.json').read_text())
            self.assertEqual(len(record['archives']), 1)  # duplicate host copies are one digest.
            self.assertFalse(record['vm_unwrap_verified'])  # real VM proof is still outstanding.
            self.assertEqual(self.migrate()['skipped'], 1)
            wrong = bytearray(m.small(['age-keygen']))
            try:
                with (gen / 'casekey.age').open('rb') as stream, self.assertRaises(ValueError):
                    m.unwrap(stream, wrong)
            finally:
                wrong[:] = b'\0' * len(wrong)
        finally:
            key[:] = b'\0' * len(key)

    def test_absent_card_never_gets_a_current_binding(self):
        row = self.archive_entry(absent=True); before = self.card_path.read_bytes()
        self.assertEqual(self.migrate()['migrated'], 1)
        gen = self.generation(row)
        projected = json.loads((gen / 'projected-card.json').read_text())
        self.assertEqual(projected['bound_archive'], {'status': 'absent', 'sha256': '1' * 64})
        self.assertFalse(projected['migration']['active_source'])
        self.assertEqual(projected['sha256'], '1' * 64)
        self.assertEqual((gen / 'original-card.json').read_bytes(), before)

    def test_truncated_authentication_tail_cannot_publish_partial_plaintext(self):
        row = self.archive_entry(large=True)
        self.input.write_bytes(self.input.read_bytes()[:-1])
        row['size'] = self.input.stat().st_size; row['archive_sha256'] = m.file_sha(self.input)
        card = json.loads(self.card_path.read_bytes()); card['sha256'] = row['archive_sha256']
        self.card_path.write_text(json.dumps(card)); row['card_sha256'] = m.file_sha(self.card_path)
        row['card_archive_sha256'] = row['archive_sha256']
        self.assertEqual(self.migrate()['failed'], 1)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_killed_decrypt_cleans_children_and_staging(self):
        self.archive_entry(large=True)
        real = m.decrypt
        children_seen = []
        def killed(stream, identity, children):
            child = real(stream, identity, children); children_seen.append(child)
            if os.fstat(stream.fileno()).st_ino == self.input.stat().st_ino:
                original = child.stdout
                class KillAfterRead:
                    def read(self, size):
                        block = original.read(size)
                        child.kill()
                        return block
                    def __getattr__(self, name):
                        return getattr(original, name)
                child.stdout = KillAfterRead()
            return child
        with patch.object(m, 'decrypt', killed):
            self.assertEqual(self.migrate()['failed'], 1)
        self.assertTrue(all(p.poll() is not None for p in children_seen))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_enospc_and_interrupt_preserve_original(self):
        self.archive_entry(); before = self.input.read_bytes()
        with patch.object(m, 'write_private', side_effect=OSError(errno.ENOSPC, 'synthetic')):
            self.assertEqual(self.migrate()['failed'], 1)
        self.assertEqual(list(self.output.iterdir()), [])
        with patch.object(m, 'reencrypt', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.migrate()
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.input.read_bytes(), before)

    def test_plan_wrong_identity_and_symlink_fail_before_decryption(self):
        row = self.archive_entry(); path, pin, plan = self.freeze()
        with self.assertRaises(ValueError):
            m.load_plan(path, '0' * 64, self.fpub, self.vpub)
        with ExitStack() as stack:
            opened = m.preflight(plan, stack)
            with patch.object(m, 'decrypt') as decoder:
                with self.assertRaises(ValueError):
                    m.run(plan, opened, self.vm, self.output, pin)
                decoder.assert_not_called()
        target = self.input.with_suffix('.backup'); self.input.rename(target); self.input.symlink_to(target)
        with ExitStack() as stack, self.assertRaises(OSError):
            m.preflight(plan, stack)

    def test_dry_run_no_prompt_and_real_run_one_prompt(self):
        self.archive_entry(); path, pin, _ = self.freeze()
        trusted = self.root / 'trusted/factory'; trusted.mkdir(parents=True)
        (trusted / 'run.py').write_text('FOUNDER_RECIPIENT = "' + self.fpub + '"\n')
        (trusted / 'control-recipient.txt').write_text(self.vpub)
        args = ['--plan', str(path), '--plan-sha256', pin]
        with patch.object(m, 'ROOT', trusted.parent), patch.object(m.getpass, 'getpass') as prompt:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(m.main(args + ['--dry-run']), 0)
                prompt.assert_not_called()
                self.assertFalse(self.output.exists())
                with patch.object(m.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 0})()):
                    self.assertEqual(m.main(args + ['--dry-run']), 2)
                    prompt.assert_not_called()
        # Native identity line only; generated throwaway comments are not a user prompt.
        line = next(x for x in self.founder.decode().splitlines() if x.startswith('AGE-SECRET-KEY-'))
        stale = self.output / '.migration-stage-dead-process'
        stale.mkdir(parents=True); (stale / 'archive.age').write_bytes(b'incomplete ciphertext')
        with patch.object(m, 'ROOT', trusted.parent), patch.object(m.sys.stdin, 'isatty', return_value=True):
            with patch.object(m.getpass, 'getpass', return_value=line) as prompt:
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(m.main(args), 0)
                self.assertEqual(prompt.call_count, 1)
                self.assertFalse(stale.exists())

    def test_failed_entry_does_not_block_a_valid_sibling(self):
        valid = self.archive_entry()
        broken = self.sealed / (CASE + '.tar.gz.age')
        broken.write_bytes(self.input.read_bytes()[:-1])
        failed = {**valid, 'active_source': False, 'kind': 'final', 'local_path': str(broken),
                  'size': broken.stat().st_size, 'archive_sha256': m.file_sha(broken)}
        self.plan['entries'] = [failed, valid]
        self.assertEqual(self.migrate(), dict(migrated=1, failed=1, skipped=0))
        self.assertIsNotNone(self.generation(valid))

    def test_identity_is_never_in_process_arguments_or_environment(self):
        self.archive_entry()
        real = subprocess.Popen
        commands = []
        def inspected(command, *args, **kwargs):
            commands.append(command)
            self.assertFalse(any('AGE-SECRET-KEY-' in str(value) for value in command))
            self.assertFalse(any('AGE-SECRET-KEY-' in str(value) for value in kwargs.get('env', {}).values()))
            return real(command, *args, **kwargs)
        with patch.object(m.subprocess, 'Popen', inspected):
            self.assertEqual(self.migrate()['migrated'], 1)
        self.assertGreater(len(commands), 5)


if __name__ == '__main__':
    unittest.main()
