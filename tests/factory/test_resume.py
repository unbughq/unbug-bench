"""Encrypted checkpoint artifacts preserve keys and replace archives atomically."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

class ResumeTests(unittest.TestCase):
    def test_batch_key_failure_raises_and_dry_run_never_requests_case_key(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from run_artifacts import RunArtifacts
        import r2_upload
        bench = pathlib.Path(__file__).resolve().parents[2]
        saved = json.loads((bench / 'tests/factory/fixtures/c7d405-confirm-timeout-card.json').read_text())
        class BeforeEncryption(BaseException): pass
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), tempfile.TemporaryDirectory() as tmp:
                home = pathlib.Path(tmp); work = home / saved['case']; work.mkdir()
                artifacts = RunArtifacts(home, bench, home / 'sealed', home / 'absent', (),
                    lambda: [], lambda c: None)
                c = SimpleNamespace(work=work, case_id=saved['case'], recipient='public-test-recipient',
                    args=SimpleNamespace(dry_run=dry_run), card={**saved, 'batch_release_sha256': 'a' * 64})
                with patch.object(artifacts, 'results_since', return_value=[]), \
                     patch.object(r2_upload, 'case_recipient', side_effect=OSError('unavailable')) as case_key, \
                     patch('run_artifacts.processes.run', side_effect=BeforeEncryption):
                    if dry_run:
                        with self.assertRaises(BeforeEncryption): artifacts.seal(c, checkpoint=True)
                        case_key.assert_not_called()
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'batch checkpoint requires a wrapped case key'):
                            artifacts.seal(c, checkpoint=True)
                        case_key.assert_called_once()
                self.assertFalse(list((home / 'sealed').glob('*.tar.gz.age')))




    def test_checkpoint_replacement_is_atomic(self):
        import argparse, shlex
        from unittest.mock import patch
        import run, r2_upload
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            c = run.Ctx(); c.work = root / 'work'; c.work.mkdir()
            c.case_id = 'case-test'; c.card = {}; c.args = argparse.Namespace(dry_run=False)
            c.recipient = 'synthetic-recipient'
            archive = root / 'case-test.checkpoint.tar.gz.age'
            archive.write_bytes(b'previous encrypted fixture')
            def encrypt(cmd, **kwargs):
                staged = pathlib.Path(shlex.split(cmd)[-1])
                self.assertFalse(staged.exists(), 'checkpoint must use a fresh staging path')
                staged.write_bytes(b'new encrypted fixture')
                return subprocess.CompletedProcess(cmd, 0)
            with patch.object(run, 'SEALED', root), patch.object(run, 'AGENT_STATE', []), \
                 patch.object(run, 'PILOT_HOME', root / 'no-pilot'), patch.object(run.RunArtifacts, 'results_since', return_value=[]), \
                 patch.object(r2_upload, 'case_recipient', return_value=None), \
                 patch.object(r2_upload, 'upload', return_value=None):
                with patch("run_artifacts.processes.run", encrypt): run.seal(c, checkpoint=True)
                self.assertEqual(archive.read_bytes(), b'new encrypted fixture')
                with patch("run_artifacts.processes.run", return_value=subprocess.CompletedProcess([], 1)):
                    with self.assertRaisesRegex(RuntimeError, 'encryption failed'): run.seal(c, checkpoint=True)
                self.assertEqual(archive.read_bytes(), b'new encrypted fixture')


if __name__ == '__main__':
    unittest.main()
