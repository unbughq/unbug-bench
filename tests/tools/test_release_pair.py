"""A proposed plumbing/bench pair must accept the calls it will actually make."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "bin/check-release-pair.py"
RUN = ROOT / "factory/run.py"
STRATEGY = ROOT / "bin/strategy"


class ReleasePairTests(unittest.TestCase):
    def preflight(self, strategy=STRATEGY, *options):
        return subprocess.run([sys.executable, str(CHECK),
                               "--plumbing-source", str(RUN),
                               "--bench-source", str(strategy), *options],
                              capture_output=True, text=True)

    def test_current_pair_accepts_the_runner_call(self):
        result = self.preflight(STRATEGY, "--changed-file", "factory/run.py",
                                "--changed-file", "bin/strategy",
                                "--send", "plumbing", "--send", "bench")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("strategy interface: compatible", result.stdout)

    def test_pr_that_changes_both_channels_cannot_send_only_plumbing(self):
        result = self.preflight(STRATEGY, "--changed-file", "factory/run.py",
                                "--changed-file", "bin/strategy", "--send", "plumbing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing release channel: bench", result.stderr)

    def test_root_markdown_change_warns_without_forcing_a_bench_release(self):
        result = self.preflight(STRATEGY, "--changed-file", "factory/run.py",
                                "--changed-file", "ARCHITECTURE.md", "--send", "plumbing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("changes judge/gate cache bindings", result.stdout)

    def test_old_bench_source_rejects_the_new_shared_call(self):
        original = STRATEGY.read_text()
        old = original.replace("restored_results_root=None, shared=None,", "restored_results_root=None,")
        self.assertNotEqual(old, original)
        with tempfile.TemporaryDirectory() as directory:
            old_strategy = Path(directory) / "strategy"
            old_strategy.write_text(old)
            result = self.preflight(old_strategy, "--changed-file", "factory/run.py",
                                    "--send", "plumbing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not accept shared=", result.stderr)

    def test_full_git_diff_catches_a_missing_bench_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            def git(*args):
                subprocess.run(["git", "-C", str(repo), *args], check=True,
                               capture_output=True, text=True)
            git("init", "-q")
            git("config", "user.name", "Release Test")
            git("config", "user.email", "release-test@example.invalid")
            (repo / "factory").mkdir()
            (repo / "bin").mkdir()
            (repo / "factory/run.py").write_text("old\n")
            (repo / "bin/strategy").write_text("old\n")
            git("add", ".")
            git("commit", "-qm", "base")
            (repo / "factory/run.py").write_text("new\n")
            (repo / "bin/strategy").write_text("new\n")
            git("commit", "-qam", "pair")
            result = self.preflight(STRATEGY, "--base", "HEAD~1", "--repo", str(repo),
                                    "--send", "plumbing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing release channel: bench", result.stderr)


if __name__ == "__main__":
    unittest.main()
