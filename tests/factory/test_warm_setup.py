"""Step setup: timed phases, warm prepared workers, and snapshot reuse on a worker.

Runs on the stand-in Boat of test_durable_workers.py (real saved Boat CLI outputs).
"""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests/factory"), str(ROOT / "factory"), str(ROOT / "bin")]
os.environ.setdefault("BENCH", str(ROOT))

import test_durable_workers as support   # noqa: E402
import test_durable_channel as chan      # noqa: E402
from durable import workers as W         # noqa: E402
from durable import channel as channel_module   # noqa: E402
from durable.channel import blob_name    # noqa: E402
from durable.contract import attempt_paths   # noqa: E402

CASE, OTHER = support.CASE, "case-20261105T000000Z-def456"


class WarmTests(unittest.TestCase):
    def setUp(self):
        self.h = support.Harness(self)
        self.bench = self.h.benches["bench-env"]
        self.pool = self.h.pool(warm_target=1)

    def news(self):
        return [c for c in self.h.calls() if c[0] == "new"]

    def deletes(self):
        return [c[1] for c in self.h.calls() if c[0] == "delete"]

    def slots(self):
        return sorted(p.stem for p in self.pool.state.glob(W.WARM_PREFIX + "*.json"))

    def age(self, plumbing):
        path = self.pool.state / "warm-releases.json"
        rows = json.loads(path.read_text())
        for row in rows:
            if row["plumbing_version"] == plumbing:
                row["at"] -= self.pool.warm_idle + 1
        path.write_text(json.dumps(rows))

    def remember(self):
        """A first step ran: the pool now knows the release a warm worker must carry."""
        self.pool.release(self.pool.acquire(CASE, self.h.plumbing, self.bench))

    def test_setup_phases_are_timed(self):
        self.pool.acquire(CASE, self.h.plumbing, self.bench)
        rows = [json.loads(line) for line in (self.pool.state / "setup-timings.jsonl").read_text().splitlines()]
        phases = {r["phase"] for r in rows}
        for phase in ("acquire_total", "create", "wait_ready", "release_upload_failed", "cli_pin_failed",
                      "release_qualify_failed", "bench_fingerprint_failed"):
            self.assertIn(phase, phases)
        self.assertTrue(all(r["seconds"] >= 0 for r in rows))

    def test_refill_waits_for_a_known_release_then_prepares_one_worker(self):
        self.pool.refill()
        self.assertEqual(self.slots(), [])   # nothing asked yet: no release to install
        self.remember()
        self.pool.refill()
        self.assertEqual(len(self.slots()), 1)
        worker = self.pool._read(self.slots()[0])["worker"]
        self.assertEqual(json.loads((self.h.home(worker) / "factory-release/RELEASE.json").read_text()),
                         {"plumbing_version": self.h.plumbing, "bench_version": self.bench})
        self.pool.refill()   # already full: nothing more is created
        self.assertEqual(len(self.news()), 2)

    def test_a_lease_takes_the_warm_worker_without_creating_or_installing(self):
        self.remember()
        self.pool.refill()
        warm = self.pool._read(self.slots()[0])["worker"]
        before = len(self.h.calls())
        lease = self.pool.acquire(OTHER, self.h.plumbing, self.bench)
        later = self.h.calls()[before:]
        self.assertEqual(lease.worker_id, W.lease_worker_id(warm))
        self.assertFalse([c for c in later if c[0] in ("new", "delete")])
        self.assertTrue(self.pool.refill_wanted.is_set())
        self.assertEqual(self.slots(), [])
        self.assertTrue(self.pool.alive(lease))
        self.assertEqual(self.pool.acquire(OTHER, self.h.plumbing, self.bench), lease)   # idempotent
        # neither sweep nor recover may treat the leased worker as a stray
        deleted = len(self.deletes())
        self.pool.sweep()
        self.pool.recover()
        self.assertEqual(len(self.deletes()), deleted)
        self.assertTrue(self.pool.alive(lease))
        self.pool.refill()   # the taken one is replaced
        self.assertEqual(len(self.slots()), 1)
        self.pool.release(lease)
        self.assertEqual(self.deletes()[deleted:], [warm])
        self.assertIsNone(self.pool._read(OTHER))

    def test_a_warm_worker_of_another_release_is_not_leased(self):
        self.remember()
        self.pool.refill()
        warm = self.pool._read(self.slots()[0])["worker"]
        lease = self.pool.acquire(OTHER, self.h.second_plumbing(), self.bench)
        self.assertNotEqual(lease.worker_id, W.lease_worker_id(warm))   # built fresh, not the stale one

    def test_a_lease_for_another_machine_size_never_takes_a_warm_worker(self):
        # helper-transport leases helpers with their own vm_type; a warm worker has the pool's default size.
        self.remember()
        self.pool.refill()
        warm = self.pool._read(self.slots()[0])["worker"]
        lease = self.pool.acquire(OTHER, self.h.plumbing, self.bench, vm_type="large")
        self.assertNotEqual(lease.worker_id, W.lease_worker_id(warm))
        self.assertEqual(self.slots() and self.pool._read(self.slots()[0])["worker"], warm)   # still warm
        self.assertIn("large", self.news()[-1])

    def test_two_releases_in_flight_do_not_make_the_pool_thrash(self):
        self.remember()
        self.pool.refill()
        warm = self.pool._read(self.slots()[0])["worker"]
        second = self.h.second_plumbing()
        self.pool.release(self.pool.acquire(OTHER, second, self.bench))   # B asked last
        news = len(self.news())
        self.pool.refill()
        self.assertEqual((len(self.news()), self.pool._read(self.slots()[0])["worker"]), (news, warm))
        self.assertNotIn(warm, self.deletes())

    def test_a_release_nobody_asks_for_any_more_is_replaced_and_an_idle_pool_drains(self):
        self.remember()
        self.pool.refill()
        stale = self.pool._read(self.slots()[0])["worker"]
        second = self.h.second_plumbing()
        self.age(self.h.plumbing)   # nobody has asked for A in an hour
        self.pool.release(self.pool.acquire(OTHER, second, self.bench))   # only B is recent now
        self.pool.refill()
        self.assertIn(stale, self.deletes())
        fresh = self.pool._read(self.slots()[0])["worker"]
        self.assertEqual(json.loads((self.h.home(fresh) / "factory-release/RELEASE.json").read_text())["plumbing_version"], second)
        self.age(second)   # nobody asks any more: no idle worker is kept or made
        self.pool.refill()
        self.assertEqual(self.slots(), [])
        self.assertIn(fresh, self.deletes())
        news = len(self.news())
        self.pool.refill()
        self.assertEqual(len(self.news()), news)

    def test_a_release_whose_bundle_is_gone_is_not_built(self):
        self.remember()
        self.pool.store._bundle_path(self.h.plumbing).unlink()
        self.pool.refill()
        self.assertEqual((self.slots(), len(self.news())), ([], 1))

    def test_no_warm_worker_is_made_once_the_runtime_stops(self):
        self.remember()
        self.pool.stopping.set()
        self.pool.refill()
        self.assertEqual((self.slots(), len(self.news())), ([], 1))

    def test_a_worker_finished_after_the_stop_is_deleted_not_left_orphaned(self):
        self.remember()
        install = self.pool._install
        def late(*a, **k):
            install(*a, **k)
            self.pool.stopping.set()
        with mock.patch.object(self.pool, "_install", late):
            self.pool.refill()
        self.assertEqual(self.slots(), [])
        self.assertEqual(len(self.deletes()), 2)

    def test_the_warm_count_is_capped(self):
        with self.assertRaises(Exception):
            self.h.pool(warm_target=W.WARM_MAX + 1)

    def test_a_leased_case_record_keeps_the_old_three_key_shape(self):
        self.remember()
        self.pool.refill()
        self.pool.acquire(OTHER, self.h.plumbing, self.bench)
        raw = json.loads(self.pool._record_path(OTHER).read_text())
        self.assertEqual(set(raw), {"intent", "worker", "deleting"})   # a rolled-back controller still reads it
        self.assertTrue(self.pool._read(OTHER)["slot"].startswith(W.WARM_PREFIX))

    def test_surplus_warm_workers_are_released(self):
        self.remember()
        self.pool.refill()
        self.pool.warm_target = 0
        self.pool.refill()
        self.assertEqual(self.slots(), [])
        self.assertEqual(len(self.deletes()), 2)   # the first case's worker and the surplus one

    def test_real_cases_cannot_use_warm_ids(self):
        with self.assertRaises(Exception):
            self.pool.acquire(W.WARM_PREFIX + "x", self.h.plumbing, self.bench)


class SnapshotReuseTests(unittest.TestCase):
    def test_a_snapshot_the_worker_already_holds_is_not_sent_again(self):
        base = chan.ChannelTests("test_start_then_running_then_done_with_outputs_in_the_store")
        base.setUp()
        self.addCleanup(base.doCleanups)
        name, data = blob_name(base.snapshot), base.blobs[blob_name(base.snapshot)]
        worker, folder = W.boat_id(base.lease.worker_id), attempt_paths("k" * 64)["blobs"]
        sent, ssh = [], base.h.boat.ssh

        def spy(host, script, *, stdin=None, timeout=120.0):
            if stdin is not None and len(stdin) >= len(data):
                sent.append(1)
            return ssh(host, script, stdin=stdin, timeout=timeout)

        with mock.patch.object(base.h.boat, "ssh", spy), mock.patch.object(channel_module, "REUSE_MIN_BYTES", len(data)):
            self.assertTrue(base.channel._push(worker, folder, name, data))
            self.assertEqual(len(sent), 1)
            self.assertTrue(base.channel._push(worker, folder, name, data))
            self.assertEqual(len(sent), 1)   # present with the right sha256: not sent again
            (base.home / folder / name).write_bytes(b"bad")   # a damaged copy is replaced, never trusted
            self.assertTrue(base.channel._push(worker, folder, name, data))
            self.assertEqual(len(sent), 2)
            self.assertEqual((base.home / folder / name).read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
