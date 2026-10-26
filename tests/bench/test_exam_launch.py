"""Launcher preflight ordering, using synthetic modules and no real keys or APIs."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class ExamLaunchPreflightTests(unittest.TestCase):
    def test_metadata_only_preflight_before_local_identity_handling(self):
        for accepted in (False, True):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'bin').mkdir()
                (root / 'factory').mkdir()
                launcher = root / 'bin/exam-launch'
                shutil.copyfile((_BENCH_ROOT / "bin" / 'exam-launch'), launcher)
                (root / 'factory/sealed_audit.py').write_text(
                    'import os\nfrom pathlib import Path\n'
                    'def verify_exam_metadata(card, case_id):\n'
                    '    assert case_id == "synthetic"\n'
                    '    Path(os.environ["PREFLIGHT_PROBE"]).write_text("metadata")\n'
                    '    if os.environ["PREFLIGHT_ACCEPT"] != "1": raise ValueError("synthetic rejection")\n'
                    '    return card\n'
                    'def verify_exam(*args, **kwargs):\n'
                    '    raise AssertionError("full restored admission cannot run on launcher")\n')
                age = root / 'bin/age'
                age.write_text('#!/bin/sh\n: > "$IDENTITY_STAGE_PROBE"\nexit 1\n')
                age.chmod(0o700)
                archive = root / 'synthetic.tar.gz.age'
                archive.write_bytes(b'synthetic ciphertext')
                (root / 'synthetic.scorecard.json').write_text('{}')
                environment = dict(os.environ, PATH=str(root / 'bin') + os.pathsep + os.environ['PATH'],
                    PREFLIGHT_PROBE=str(root / 'preflight'),
                    IDENTITY_STAGE_PROBE=str(root / 'identity-stage'),
                    PREFLIGHT_ACCEPT='1' if accepted else '0')
                result = subprocess.run(['/bin/sh', str(launcher), str(archive), '--arm', 'nop'],
                    input='synthetic identity\n', text=True, capture_output=True, env=environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((root / 'preflight').read_text(), 'metadata')
                self.assertEqual((root / 'identity-stage').exists(), accepted)


if __name__ == '__main__':
    unittest.main()
