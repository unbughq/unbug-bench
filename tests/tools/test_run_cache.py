#!/usr/bin/env python3
"""tests/run.py reuses a pass only for byte-identical, committed code; docs-only commits keep it."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

RUN = Path(__file__).resolve().parents[1] / "run.py"


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo, self.cache, self.count = self.tmp / "repo", self.tmp / "cache", self.tmp / "count"
        (self.repo / "tests" / "tools").mkdir(parents=True)
        (self.repo / "docs").mkdir()
        shutil.copy(RUN, self.repo / "tests" / "run.py")
        (self.repo / "tests" / "tools" / "test_a.py").write_text(
            f"open({str(self.count)!r}, 'a').write('x')\n")
        (self.repo / "code.py").write_text("A = 1\n")
        (self.repo / "docs" / "note.md").write_text("one\n")
        self.git("init", "-q"); self.commit()

    def git(self, *args):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=self.repo, check=True,
                       capture_output=True)

    def commit(self):
        self.git("add", "-A"); self.git("commit", "-qm", "c")

    def runs(self):
        env = {**os.environ, "TEST_CACHE_DIR": str(self.cache), "TEST_SLOT_DIR": str(self.tmp / "slots")}
        result = subprocess.run([sys.executable, "-B", "tests/run.py", "tools"], cwd=self.repo, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return len(self.count.read_text()) if self.count.exists() else 0

    def test_reuse_rules(self):
        self.assertEqual(self.runs(), 1)                 # first run executes
        self.assertEqual(self.runs(), 1)                 # identical code: reused
        (self.repo / "docs" / "note.md").write_text("two\n"); self.commit()
        self.assertEqual(self.runs(), 1)                 # prose-only commit: still reused
        (self.repo / "docs" / "note.md").write_text("three\n")
        self.assertEqual(self.runs(), 1)                 # uncommitted prose: still reused
        self.git("checkout", "--", "docs/note.md")
        (self.repo / "docs" / "reports").mkdir()
        (self.repo / "docs" / "reports" / "data.json").write_text("{}\n"); self.commit()
        self.assertEqual(self.runs(), 2)                 # docs data file can feed tests: reruns
        self.assertEqual(self.runs(), 2)
        (self.repo / "code.py").write_text("A = 2\n"); self.commit()
        self.assertEqual(self.runs(), 3)                 # code changed: reruns
        (self.repo / "code.py").write_text("A = 3\n")    # uncommitted code change
        self.assertEqual(self.runs(), 4)                 # dirty tree: never reused
        self.assertEqual(self.runs(), 5)

    def test_skipped_pass_is_never_cached(self):
        (self.repo / "tests" / "tools" / "test_a.py").write_text(
            f"open({str(self.count)!r}, 'a').write('x'); print('OK (skipped=1)')\n"); self.commit()
        self.assertEqual(self.runs(), 1)
        self.assertEqual(self.runs(), 2)

    def test_commit_during_run_caches_nothing(self):
        (self.repo / "tests" / "tools" / "test_a.py").write_text(
            f"import subprocess; open({str(self.count)!r}, 'a').write('x')\n"
            "open('code.py', 'a').write('#\\n')\n"
            "subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qam', 'mid'], check=True)\n")
        self.commit()
        self.assertEqual(self.runs(), 1)
        self.git("reset", "-q", "--hard", "HEAD~1")      # back to the code the run started on
        self.assertEqual(self.runs(), 2)                 # that run saw changed code mid-run: nothing was cached

    def test_failure_is_never_cached(self):
        (self.repo / "tests" / "tools" / "test_a.py").write_text(
            f"open({str(self.count)!r}, 'a').write('x'); raise SystemExit(1)\n"); self.commit()
        env = {**os.environ, "TEST_CACHE_DIR": str(self.cache), "TEST_SLOT_DIR": str(self.tmp / "slots")}
        for expected in (1, 2):
            result = subprocess.run([sys.executable, "-B", "tests/run.py", "tools"], cwd=self.repo, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(len(self.count.read_text()), expected)


if __name__ == "__main__":
    unittest.main()
