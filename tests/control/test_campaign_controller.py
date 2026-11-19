"""The campaign controller's worker limits: a running-sandbox cap and start rates, never a lifetime count.
Offline: the durable Runtime is replaced by a fake pool."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "factory"))
from durable.classify import WORKER_POOL_REASONS
from durable.guard import STARTS_PER_MINUTE, reserve_start
from durable.workers import PoolError

USAGE = json.dumps({"dollars": 0.02, "billingMultiplier": 1.0, "secondsPerDollar": 100000}).encode()


class FakePool:
    def __init__(self):
        self.ttl, self.vm_type = None, None
        self.live, self.records, self.deleted, self.created = [], {}, [], []
        self.boat = self

    def run(self, args, timeout):
        return 0, USAGE

    def _create(self, case, bench, vm_type=None):   # BoatPool._create's signature
        worker = f"bx_{len(self.created):08d}"
        self.created.append((worker, self.ttl))
        self.live.append(worker)
        return worker

    def _deliver_credentials(self, worker):
        return worker

    def _inventory(self):
        return [{"id": w, "state": "running", "name": "ours"} for w in self.live]

    @staticmethod
    def _live(row):
        return row["state"] == "running"

    @staticmethod
    def _ours(row):
        return {} if row["name"] == "ours" else None

    def _records(self):
        return dict(self.records)

    def _settled(self, case):
        return self.records[case].get("settled", False)

    def _delete_raw(self, worker):
        self.deleted.append(worker)
        self.live.remove(worker)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.request = {"batch_ids": ["b-one", "b-two"], "deadline_epoch": time.time() + 86400,
                        "wall_seconds": 86400, "max_worker_rate_usd_per_second": 2e-05,
                        "max_running_sandboxes": 3, "max_starts_per_hour": 30,
                        "approved_infrastructure_usd": 12, "prior_compute_retained_usd": 2,
                        "control_allowance_usd": 2, "cleanup_margin_usd": 2}
        self.write()
        with mock.patch.dict(os.environ, {"UNBUG_CAMPAIGN_ROOT": str(self.root)}):
            spec = importlib.util.spec_from_file_location("campaign_controller_under_test",
                                                          ROOT / "control/campaign/campaign_controller.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.module, self.pool = module, FakePool()

        def init(runtime, config):
            runtime.pool, runtime.state = self.pool, self.root
        with mock.patch.object(module.Runtime, "__init__", init):
            self.runtime = module.BoundedRuntime({})

    def write(self):
        (self.root / "campaign-request.json").write_text(json.dumps(self.request))

    def create(self, case="case-t-1"):
        return self.runtime.pool._create(case, "b" * 64)

    def test_creations_never_run_out_while_slots_free_up(self):
        # 40 creations: more than any lifetime cap the campaign used to have (12, then 30).
        with mock.patch("durable.guard.STARTS_PER_MINUTE", 1000), mock.patch("durable.guard.STARTS_PER_DAY", 1000):
            self.request["max_starts_per_hour"] = 59
            self.write()
            for n in range(40):
                worker = self.create()
                self.pool._delete_raw(worker)
                starts = json.loads((self.root / "campaign-starts.json").read_text())
                if len(starts) >= 59:   # an hour later
                    (self.root / "campaign-starts.json").write_text(json.dumps([t - 3600 for t in starts]))
        self.assertEqual(len(self.pool.created), 40)
        self.assertFalse((self.root / "campaign-create-count.json").exists())

    def test_a_full_set_of_slots_waits_instead_of_stopping(self):
        for _ in range(3):
            self.create()
        with self.assertRaises(PoolError) as caught:
            self.create()
        self.assertEqual(caught.exception.reason, "infra:worker_slots_full")
        self.assertIn("infra:worker_slots_full", WORKER_POOL_REASONS)   # the engine waits on it
        self.pool._delete_raw(self.pool.live[0])
        self.create()                                                      # a freed slot is reused
        self.assertEqual(len(self.pool.created), 4)

    def test_an_unsettled_create_request_holds_a_slot(self):
        self.create(); self.create()
        self.pool.records["case-t-9"] = {"intent": "n", "worker": None, "deleting": None}
        with self.assertRaises(PoolError):
            self.create()
        self.pool.records["case-t-9"]["settled"] = True
        self.create()

    def test_a_create_boat_does_not_list_yet_holds_a_slot(self):
        self.create(); self.create()
        self.pool.records["case-t-9"] = {"intent": "n", "worker": "bx_late0000", "deleting": None}
        with self.assertRaises(PoolError):
            self.create()

    def test_an_unreadable_pool_waits_like_an_inventory_outage(self):
        def gone(case):
            raise FileNotFoundError(case)
        self.pool.records["case-t-9"] = {"intent": "n", "worker": None, "deleting": None}
        self.pool._settled = gone
        with self.assertRaises(PoolError) as caught:
            self.create()
        self.assertEqual(caught.exception.reason, "infra:inventory_unavailable")
        self.assertEqual(self.pool.created, [])

    def test_an_old_request_refuses_startup_and_never_deletes_a_running_worker(self):
        worker = self.create()
        old = {k: v for k, v in self.request.items() if k not in ("max_running_sandboxes", "max_starts_per_hour")}
        (self.root / "campaign-request.json").write_text(json.dumps({**old, "max_workers_lifetime": 30}))
        with self.assertRaises(PoolError) as caught:
            self.runtime.pool._deliver_credentials(worker)
        self.assertEqual(caught.exception.reason, "infra:compute_approval_unverified")
        self.assertEqual(self.pool.deleted, [])
        with self.assertRaises(SystemExit):
            self.module.BoundedRuntime({})

    def test_sandboxes_not_ours_or_not_live_hold_no_slot(self):
        self.create(); self.create()
        orig = self.pool._inventory
        self.pool._inventory = lambda: orig() + [{"id": "bx_other00", "state": "running", "name": "theirs"},
                                                 {"id": "bx_dead0000", "state": "deleted", "name": "ours"}]
        self.create()

    def test_a_burst_of_starts_waits_on_the_rate_limit(self):
        self.request["max_running_sandboxes"] = 20
        self.request["approved_infrastructure_usd"] = 100
        self.write()
        for _ in range(STARTS_PER_MINUTE):
            self.pool._delete_raw(self.create())
        with self.assertRaises(PoolError) as caught:
            self.create()
        self.assertEqual(caught.exception.reason, "infra:worker_start_rate")
        self.assertIn("infra:worker_start_rate", WORKER_POOL_REASONS)

    def test_slots_that_do_not_fit_the_approval_delete_the_worker(self):
        self.request["max_running_sandboxes"] = 5   # 5 x $1.74 > $6 of headroom
        self.write()
        with self.assertRaises(PoolError) as caught:
            self.create()
        self.assertEqual(caught.exception.reason, "infra:compute_approval_unverified")
        self.assertEqual(self.pool.deleted, [self.pool.created[0][0]])

    def test_a_request_without_limits_refuses_before_creating(self):
        del self.request["max_running_sandboxes"]
        self.write()
        with self.assertRaises(PoolError) as caught:
            self.create()
        self.assertEqual(caught.exception.reason, "infra:compute_approval_unverified")
        self.assertEqual(self.pool.created, [])

    def test_a_large_worker_type_creates_at_its_approved_rate(self):
        self.assertEqual(self.pool.vm_type, None)
        self.create()
        self.assertEqual(self.pool.vm_type, "default")   # unchanged without a vm_type
        # $6e-05/s passes the default type's cap; the request approves it for large workers only.
        self.pool.run = lambda args, timeout: (0, json.dumps({"dollars": 0.02, "billingMultiplier": 1.0,
                                                              "secondsPerDollar": 1 / 6e-05}).encode())
        self.request.update(vm_type="large", worker_rates_usd_per_second={"large": 8e-05},
                            approved_infrastructure_usd=30)
        self.write()
        self.create()
        self.assertEqual((self.pool.vm_type, self.pool.deleted), ("large", []))
        del self.request["worker_rates_usd_per_second"]   # no approved large rate: nothing is created
        self.write()
        with self.assertRaises(PoolError) as caught:
            self.create()
        self.assertEqual(caught.exception.reason, "infra:compute_approval_unverified")
        self.assertEqual(len(self.pool.created), 2)
        for bad in ({"vm_type": ["large"]}, {"vm_type": "default", "max_worker_rate_usd_per_second": None}):
            with self.subTest(bad=bad):   # a pool wait, never a raw KeyError/TypeError
                self.request.update(bad)
                self.write()
                with self.assertRaises(PoolError):
                    self.create()
                self.assertEqual(len(self.pool.created), 2)

    def test_the_ttl_ends_at_the_deadline_plus_grace(self):
        self.request["deadline_epoch"] = time.time() + 1000
        self.write()
        self.create()
        self.assertTrue(1590 <= self.pool.created[0][1] <= 1600)
        bound = json.loads((self.root / "campaign-compute-bound.json").read_text())
        self.assertEqual((bound["max_running_sandboxes"], bound["max_starts_per_hour"]), (3, 30))

    def test_a_slow_inventory_is_timed_after_it_answers(self):
        # Review of PR #40: an inventory call that takes 120 s must not backdate the start or stretch the TTL.
        clock = [1000.0]
        orig = self.pool._inventory
        def slow():
            clock[0] += 120
            self.pool._inventory = orig   # only the first lookup is slow
            return orig()
        self.pool._inventory = slow
        self.request["deadline_epoch"] = 2000
        self.request["max_running_sandboxes"] = 20
        self.request["approved_infrastructure_usd"] = 100
        self.write()
        with mock.patch("time.time", lambda: clock[0]):
            self.create()
            self.assertEqual(json.loads((self.root / "campaign-starts.json").read_text()), [1120.0])
            self.assertEqual(self.pool.created[0][1], 2000 + 600 - 1120)   # expires at deadline + grace
            for _ in range(STARTS_PER_MINUTE - 1):
                self.pool._delete_raw(self.create())
            with self.assertRaises(PoolError) as caught:
                self.create()
        self.assertEqual(caught.exception.reason, "infra:worker_start_rate")

    def test_helper_boxes_leave_a_reserve_of_slots_and_starts_for_cases(self):
        self.request["max_running_sandboxes"] = 4
        self.request["approved_infrastructure_usd"] = 100
        self.write()
        helper = "case-import-04d417-h2-1-h3"   # helper_link.helper_case_id of case-import-04d417-h2-1
        self.create(helper); self.create(helper)
        starts = (self.root / "campaign-starts.json").read_text()
        with self.assertRaises(PoolError) as caught:
            self.create(helper)                                 # 2 of 4 slots stay for case workers
        self.assertEqual(caught.exception.reason, "infra:worker_slots_full")
        self.assertEqual((self.root / "campaign-starts.json").read_text(), starts)   # a refusal books no start
        self.create("case-import-04d417-h2-1"); self.create("case-import-04d417-h2-1")   # cases use the reserve
        self.assertEqual(len(self.pool.created), 4)
        for worker in list(self.pool.live):
            self.pool._delete_raw(worker)
        now = time.time()
        (self.root / "campaign-starts.json").write_text(json.dumps([now - 3000] * 24))
        with self.assertRaises(PoolError) as caught:
            self.create(helper)                                 # 24 of 30 hourly starts used: 6 stay for cases
        self.assertEqual(caught.exception.reason, "infra:worker_start_rate")
        self.create("case-import-04d417-h2-1")

    def test_helper_boxes_leave_a_reserve_of_daily_and_minute_starts_for_cases(self):
        from durable.guard import STARTS_PER_DAY
        helper, case = "case-import-04d417-h2-1-h3", "case-import-04d417-h2-1"
        now = time.time()
        day = [now - 7200 - i for i in range(STARTS_PER_DAY - self.module.HELPER_RESERVE_DAY)]
        (self.root / "campaign-starts.json").write_text(json.dumps(day))
        with self.assertRaises(PoolError) as caught:
            self.create(helper)                                 # the last daily starts stay for cases
        self.assertEqual(caught.exception.reason, "infra:worker_start_rate")
        self.pool._delete_raw(self.create(case))
        minute = [now - 1] * (STARTS_PER_MINUTE - self.module.HELPER_RESERVE_MINUTE)
        (self.root / "campaign-starts.json").write_text(json.dumps(minute))
        with self.assertRaises(PoolError) as caught:
            self.create(helper)                                 # and the last starts of each minute
        self.assertEqual(caught.exception.reason, "infra:worker_start_rate")
        self.create(case)

    def test_reserve_start_keeps_one_day_of_starts(self):
        path = self.root / "starts.json"
        now = time.time()
        path.write_text(json.dumps([now - 90000, now - 100]))
        self.assertEqual(reserve_start(path, self.request, lambda: 0, lambda: now), now)
        self.assertEqual(json.loads(path.read_text()), [now - 100, now])


if __name__ == "__main__":
    unittest.main()
