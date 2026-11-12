"""A multi-hour quota or money wait keeps its worker: reuse leases in 2-5 s, a new worker 37-350 s."""
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory")]
os.environ.setdefault("BENCH", str(ROOT))
from durable.engine import _Case  # noqa: E402


def keeps(limit, seconds, patched=True):
    return _Case.keeps_worker_for(SimpleNamespace(spec=SimpleNamespace(release_worker_after_sleep_s=limit)),
                                  seconds, patched)


class KeepWorker(unittest.TestCase):
    def test_default_limit_keeps_hours(self):
        self.assertTrue(keeps(1_800.0, 3 * 3600))
        self.assertFalse(keeps(1_800.0, 12 * 3600))

    def test_explicit_limit_is_honored(self):
        self.assertFalse(keeps(0.5, 3.0))
        self.assertTrue(keeps(60.0, 30.0))

    def test_unpatched_replay_keeps_the_old_limit(self):
        self.assertFalse(keeps(1_800.0, 3 * 3600, patched=False))


if __name__ == "__main__":
    unittest.main()
