"""The campaign controller's create wrapper against the real BoatPool.acquire call.

BoatPool.acquire calls self._create(case, bench, vm_type) since helper machines got their own size.
The controller's wrapper took two arguments, so every worker request raised TypeError and the
engine booked infra:pool_failed. Here the real acquire and the real _create run behind the real
wrapper; only Boat, the release store and the post-create setup are stand-ins. The Boat `created`
event is the saved real output (fixtures/isolation-timeouts/created.json)."""
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
from durable import workers as W   # noqa: E402

CREATED = json.loads((ROOT / "tests/factory/fixtures/isolation-timeouts/created.json").read_text())
USAGE = json.dumps({"dollars": 0.02, "billingMultiplier": 1.0, "secondsPerDollar": 100000}).encode()
DIGEST = "a" * 64


class Boat:
    def __init__(self):
        self.calls = []

    def run(self, args, timeout):
        self.calls.append(args)
        if args[0] == "new":
            return 0, json.dumps(CREATED).encode()
        if args[0] == "usage":
            return 0, USAGE
        raise AssertionError(args)


class Store:
    def has_bundle(self, plumbing_version):
        return True

    def image_for(self, bench_version, default):
        return default


class LauncherVmTypeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.request = {"batch_ids": ["b-one"], "deadline_epoch": time.time() + 86400,
                        "wall_seconds": 86400, "max_worker_rate_usd_per_second": 2e-05,
                        "max_running_sandboxes": 3, "max_starts_per_hour": 30,
                        "approved_infrastructure_usd": 12, "prior_compute_retained_usd": 2,
                        "control_allowance_usd": 2, "cleanup_margin_usd": 2}
        (self.root / "campaign-request.json").write_text(json.dumps(self.request))
        with mock.patch.dict(os.environ, {"UNBUG_CAMPAIGN_ROOT": str(self.root)}):
            spec = importlib.util.spec_from_file_location("campaign_controller_vm_type",
                                                          ROOT / "control/campaign/campaign_controller.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.boat = Boat()
        pool = W.BoatPool(self.root / "pool", Store(), "wp2-test", boat=self.boat)
        pool._inventory = lambda: []                       # nothing else is running
        pool._wait_ready = lambda worker: None             # setup after the create is not under test
        pool._install = lambda worker, p, b, prepare_image=False: None
        pool.credential_bundle = None
        self.pool = pool

        def init(runtime, config):
            runtime.pool, runtime.state = pool, self.root
        with mock.patch.object(module.Runtime, "__init__", init):
            module.BoundedRuntime({})

    def news(self):
        return [c for c in self.boat.calls if c[0] == "new"]

    def test_a_case_gets_a_worker_through_the_bounded_create(self):
        lease = self.pool.acquire("case-t-1", DIGEST, DIGEST)
        self.assertEqual(lease.worker_id, W.lease_worker_id(CREATED["id"]))
        new = self.news()[0]
        self.assertEqual(new[new.index("--type") + 1], "default")

    def test_a_helper_of_the_approved_type_gets_a_worker(self):
        self.pool.acquire("case-t-1", DIGEST, DIGEST, vm_type="default")
        self.assertEqual(len(self.news()), 1)

    def test_a_helper_of_another_type_is_refused_before_any_start(self):
        with self.assertRaises(W.PoolError) as caught:
            self.pool.acquire("case-t-1", DIGEST, DIGEST, vm_type="large")
        self.assertEqual(caught.exception.reason, "infra:compute_approval_unverified")
        self.assertEqual(self.news(), [])
        self.assertFalse((self.root / "campaign-starts.json").exists())   # no start booked against the rate

    def test_a_warm_worker_create_still_fits_the_wrapper(self):
        self.pool._create("case-warm-0123456789ab", DIGEST)
        self.assertEqual(len(self.news()), 1)


if __name__ == "__main__":
    unittest.main()
