"""Synthetic-only unlock checks: no real identities, age, models, or cloud."""

# Keep direct execution independent of the working directory.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))

import collections
import contextlib
import hashlib
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

import unlock_sealed_audit as audit


CASE = audit.ALLOWLIST[0][0]
IDENTITY = 'AGE-SECRET-KEY-1' + 'SYNTHETIC' * 4


def packed(entries, root=CASE):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, data in entries:
            member = tarfile.TarInfo(root + '/' + name)
            if data is None:
                member.type = tarfile.SYMTYPE
                member.linkname = '/tmp/escape'
                archive.addfile(member)
            else:
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
    buffer.seek(0)
    return buffer


class UnlockTest(unittest.TestCase):
    def test_large_workspace_exceeds_old_member_limit(self):
        # Streaming fixture: >100k entries without allocating a huge tar buffer.
        with tempfile.TemporaryFile() as source, tempfile.TemporaryDirectory() as directory:
            with tarfile.open(fileobj=source, mode='w:gz') as archive:
                for i in range(100_001):
                    member = tarfile.TarInfo(CASE + '/workspace/d' + str(i))
                    member.type = tarfile.DIRTYPE
                    archive.addfile(member)
                member = tarfile.TarInfo(CASE + '/case/statement.md')
                member.size = 4
                archive.addfile(member, io.BytesIO(b'test'))
            source.seek(0)
            counts, _ = audit.extract_evidence(source, CASE, Path(directory))
            self.assertEqual(counts['archive_members'], 100_002)
            self.assertEqual((Path(directory) / 'case/statement.md').read_bytes(), b'test')

    def test_freshness_jsonl_is_evidence_not_transcript(self):
        data = b'{"who":"attacker","hit":true,"url":"https://example.org"}\n'
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            audit.extract_evidence(packed([('case/freshness.jsonl', data)]), CASE, target)
            self.assertEqual((target / 'case/freshness.jsonl').read_bytes(), data)

    def test_projection_preserves_three_driver_actions_errors_and_text(self):
        secret = 'RAW_REASONING_SENTINEL'
        events = [
            {'part': {'type': 'reasoning', 'text': secret}},
            {'part': {'type': 'tool', 'tool': 'bash', 'state': {'input': {'command': 'inspect'},
                'output': 'diagnostic execution failed', 'reasoning': secret}}, 'extra': secret},
            {'part': {'type': 'text', 'text': 'opencode final'}},
            {'type': 'item.completed', 'item': {'type': 'reasoning', 'text': secret}},
            {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'inspect', 'aggregated_output': 'failed'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'codex final'}},
            {'type': 'assistant', 'message': {'content': [
                {'type': 'thinking', 'thinking': secret},
                {'type': 'tool_use', 'name': 'Read', 'input': {'path': 'case'}},
                {'type': 'text', 'text': 'claude final'}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'x',
                'content': [{'type': 'text', 'text': 'tool result'}, {'type': 'thinking', 'thinking': secret}]}]}},
            {'type': 'error', 'message': 'provider failed'},
        ]
        counts = collections.Counter()
        result = audit.project_transcript(('\n'.join(map(json.dumps, events)) + '\ninvalid').encode(), counts).decode()
        self.assertNotIn(secret, result)
        for expected in ('diagnostic execution failed', 'opencode final', 'codex final', 'claude final', 'tool result', 'provider failed'):
            self.assertIn(expected, result)
        self.assertEqual(counts['malformed_transcript_lines'], 1)
        self.assertEqual(counts['retained_transcript_events'], 7)

    def test_private_regular_evidence_and_coverage(self):
        events = b'{"part":{"type":"reasoning","text":"RAW_SENTINEL"}}\n{"part":{"type":"text","text":"answer"}}'
        entries = [('case/statement.md', b'private case'), ('case/sub/data.json', b'{}'),
                   ('calibrators/strong/results.json', b'[]'), ('bench-results/judge.json', b'{}'),
                   ('fixes/0/app.patch', b'patch'), ('verdict.json', b'{}'), ('history/verdict-1.json', b'{}'),
                   ('transcripts/attempt.jsonl', events), ('logs/runner.log', b'raw'),
                   ('agent-state/db', b'raw'), ('case/.env', b'key'), ('case/auth.json', b'key'),
                   ('case/id_ed25519', b'key'), ('case/key.txt', IDENTITY.encode()),
                   ('case/link', None), ('notes/analysis-reasoning.txt', b'raw')]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            old = os.umask(0o077)
            try:
                counts, inventory = audit.extract_evidence(packed(entries), CASE, destination)
            finally:
                os.umask(old)
            self.assertEqual(counts['retained_files'], 8)
            self.assertEqual(len(inventory), len(entries))
            self.assertNotIn('RAW_SENTINEL', (destination / 'transcripts/attempt.jsonl').read_text())
            for path in destination.rglob('*'):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
            self.assertEqual(counts['omitted_nonregular_files'], 1)
            self.assertEqual(counts['omitted_secret_content'], 1)

    def test_traversal_wrong_root_duplicates_and_limits_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            for entries, root in [([('../escape', b'x')], CASE), ([('case/x', b'x')], 'wrong'),
                                  ([('case/x', b'x'), ('case/x', b'y')], CASE)]:
                with self.subTest(entries=entries), self.assertRaises(ValueError):
                    audit.extract_evidence(packed(entries, root), CASE, Path(directory))
            with patch.object(audit, 'MAX_FILE', 1), self.assertRaises(ValueError):
                audit.extract_evidence(packed([('case/large', b'xx')]), CASE, Path(directory))
            with patch.object(audit, 'MAX_TOTAL', 1), self.assertRaises(ValueError):
                audit.extract_evidence(packed([('case/x', b'xx')]), CASE, Path(directory))
            with patch.object(audit, 'MAX_MEMBERS', 0), self.assertRaises(ValueError):
                audit.extract_evidence(packed([('case/x', b'x')]), CASE, Path(directory))

    def test_g11_fixed_root_and_evidence(self):
        archive_id = audit.ALLOWLIST[-1][0]
        with tempfile.TemporaryDirectory() as directory:
            counts, _ = audit.extract_evidence(packed([('evidence/judge.json', b'{}'),
                ('reproductions/check.py', b'pass')], 'g11-audit'), archive_id, Path(directory))
            self.assertEqual(counts['retained_files'], 2)

    def make_inputs(self, root):
        (root / 'sealed').mkdir()
        allowlist = []
        for archive_id, _ in audit.ALLOWLIST:
            payload = b'synthetic ciphertext: ' + archive_id.encode()
            digest = hashlib.sha256(payload).hexdigest()
            allowlist.append((archive_id, digest))
            archive = root / 'sealed' / (archive_id + '.tar.gz.age')
            archive.write_bytes(payload)
            archive.with_name(archive_id + '.scorecard.json').write_text(json.dumps({
                'case': archive_id.removeprefix('g11-review-'), 'sha256': digest,
                'archive': '/elsewhere/' + archive.name}))
        return tuple(allowlist)

    def test_batch_one_prompt_public_manifest_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowlist = self.make_inputs(root)
            output = root / 'private'
            def private_dir(**kwargs):
                output.mkdir(mode=0o700)
                return str(output)
            def decrypt(age, stream, identity, archive_id, destination):
                self.assertEqual(identity, IDENTITY)
                audit.write_private(destination / 'case.txt', b'PRIVATE_CASE_SENTINEL')
                return {'retained_files': 1}, [{'path': 'PRIVATE_PATH_SENTINEL'}]
            with patch.object(audit, 'ROOT', root), patch.object(audit, 'ALLOWLIST', allowlist), \
                 patch.object(audit.shutil, 'which', return_value='/usr/bin/age'), \
                 patch.object(audit.sys.stdin, 'isatty', return_value=True), \
                 patch.object(audit.getpass, 'getpass', return_value=IDENTITY) as prompt, \
                 patch.object(audit.tempfile, 'mkdtemp', side_effect=private_dir), \
                 patch.object(audit, 'decrypt_one', side_effect=decrypt) as decrypt_mock:
                captured = io.StringIO()
                with contextlib.redirect_stdout(captured):
                    audit.main()
                self.assertEqual(prompt.call_count, 1)
                self.assertEqual(decrypt_mock.call_count, 4)
                text = captured.getvalue()
                for forbidden in (IDENTITY, 'PRIVATE_CASE_SENTINEL', 'PRIVATE_PATH_SENTINEL'):
                    self.assertNotIn(forbidden, text)
                self.assertEqual(len(json.loads(text)['archives']), 4)
                audit.shutil.rmtree(output)
                decrypt_mock.side_effect = RuntimeError('PRIVATE_ERROR_SENTINEL')
                with self.assertRaises(RuntimeError):
                    audit.main()
                self.assertFalse(output.exists())
                # A mismatch in the LAST input must prevent even the first prompt.
                prompt.reset_mock()
                (root / 'sealed' / (allowlist[-1][0] + '.tar.gz.age')).write_bytes(b'tampered')
                with self.assertRaises(ValueError):
                    audit.main()
                prompt.assert_not_called()

    def test_age_key_is_only_stdin_and_auth_failure_is_error(self):
        class Pipe(io.BytesIO):
            def close(self):
                self.saved = self.getvalue()
                super().close()
        class Process:
            def __init__(self):
                self.stdin = Pipe()
                self.stdout = packed([('case/statement.md', b'synthetic')])
            def wait(self, **kwargs): return 1
            def poll(self): return 1
        process = Process()
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryFile() as ciphertext, \
             patch.object(audit.subprocess, 'Popen', return_value=process) as popen:
            with self.assertRaises(RuntimeError):
                audit.decrypt_one('/usr/bin/age', ciphertext, IDENTITY, CASE, Path(directory))
            args, kwargs = popen.call_args
            self.assertNotIn(IDENTITY, repr(args) + repr(kwargs))
            self.assertEqual(process.stdin.saved, (IDENTITY + '\n').encode())
            self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
            self.assertNotIn('env', kwargs)

    def test_help_and_arguments_never_accept_keys(self):
        script = str(Path(audit.__file__))
        result = subprocess.run([sys.executable, script, '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('AGE-SECRET-KEY-1', result.stdout)
        result = subprocess.run([sys.executable, script, '--key', 'synthetic'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
