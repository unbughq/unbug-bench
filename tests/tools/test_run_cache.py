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
        self.assertEqual(self.runs(), 1)                 # docs-only commit: still reused
        (self.repo / "code.py").write_text("A = 2\n"); self.commit()
        self.assertEqual(self.runs(), 2)                 # code changed: reruns
        (self.repo / "code.py").write_text("A = 3\n")    # uncommitted code change
        self.assertEqual(self.runs(), 3)                 # dirty tree: never reused
        self.assertEqual(self.runs(), 4)

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
