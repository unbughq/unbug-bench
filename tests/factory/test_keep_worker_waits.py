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


class BoundWait(unittest.TestCase):
    """The engine:money path (wait_for_bound) keeps the worker until the wait passes the keep limit."""

    def run_wait(self, clock, patched=True):
        import durable.engine as eng
        released, polls, times = [], iter([None, None, "wake"]), iter(clock)
        me = SimpleNamespace(replaying=False, worker_id="w1", status="", card=lambda: None, tell=lambda *_: None)
        me.release_worker = lambda: (released.append(me.worker_id), setattr(me, "worker_id", None))
        saved = (eng.DBOS.patch, eng.DBOS.recv, eng.now_step)
        eng.DBOS.patch = lambda name: patched or name == "bound_wait_blocks"
        eng.DBOS.recv = lambda *a, **k: next(polls)
        eng.now_step = lambda: next(times)
        try:
            _Case.wait_for_bound(me)
        finally:
            eng.DBOS.patch, eng.DBOS.recv, eng.now_step = saved
        return released

    def test_short_money_wait_keeps_worker(self):
        self.assertEqual(self.run_wait([0, 60, 120]), [])

    def test_wait_past_limit_releases(self):
        self.assertEqual(self.run_wait([0, 60, 21_700]), ["w1"])

    def test_unpatched_replay_releases_up_front(self):
        self.assertEqual(self.run_wait([0, 60, 120], patched=False), ["w1"])


if __name__ == "__main__":
    unittest.main()
