"""Public SQL-only repair bundles must carry their checkpoint prerequisite."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPAIRS = (
    'scenarios/dev/S7a-safety-stock/examples/repaired',
    'scenarios/dev/S11-monitor-blind/examples/repaired',
    'scenarios/dev/S13-marketplace/examples/cross-service',
)


class CompensationCoverageTests(unittest.TestCase):
    def test_correct_repairs_load_the_reviewed_checkpoint_queue(self):
        reference = (ROOT / 'guards/reference/app.patch').read_text()
        module = reference[reference.index('diff --git a/src/reference-checkpoints.ts'):]
        for repair in REPAIRS:
            with self.subTest(repair=repair), tempfile.TemporaryDirectory() as tmp:
                patch = ROOT / repair / 'app.patch'
                self.assertTrue(patch.is_file(), repair)
                self.assertIn(module, patch.read_text())
                subprocess.run(['git', 'apply', str(patch)], cwd=tmp, check=True)
                middleware = pathlib.Path(tmp, 'src/api/middlewares.ts').read_text()
                self.assertIn('import "../reference-checkpoints";', middleware)

    def test_harbor_stages_and_installs_the_complete_reference(self):
        build = (ROOT / 'harbor/build.sh').read_text()
        solve = (ROOT / 'harbor/medusa-oversell/solution/solve.sh').read_text()
        self.assertIn('cp "$root/guards/reference/app.patch" "$task/solution/guard/app.patch"', build)
        self.assertIn('cp /solution/guard/app.patch /app/guard/app.patch', solve)


if __name__ == '__main__':
    unittest.main()
