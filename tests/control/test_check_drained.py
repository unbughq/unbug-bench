"""control/check-drained.py: restarts and release sends wait until no step runs and no router lease is held."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_drained", ROOT / "control/check-drained.py")
drained = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drained)


class FakeClient:
    """The two DBOSClient reads the check makes, over fixed rows."""

    def __init__(self, workflows):
        self.workflows = workflows   # {workflow_id: (name, status, [(step name, output)])}

    def list_workflows(self, *, name, status, load_input, load_output):
        return [types.SimpleNamespace(workflow_id=w) for w, (n, s, _) in self.workflows.items()
                if n in name and s in status]

    def list_workflow_steps(self, workflow_id):
        return [{"function_name": f, "output": o} for f, o in self.workflows[workflow_id][2]]

    def destroy(self):
        pass


LEASED = ("lease_step", {"worker_id": "bx_abcdefgh", "reason": None})


class StepsInFlight(unittest.TestCase):
    def test_only_a_leased_attempt_without_its_attempt_step_is_in_flight(self):
        client = FakeClient({
            "c/3/writer:1/1": ("attempt_workflow", "PENDING", [("reserve_step", {}), LEASED, ("now_step", 1.0)]),
            "c/2/stress:1/1": ("attempt_workflow", "PENDING", [LEASED, ("now_step", 1.0), ("attempt_step", {})]),
            "c/4/gates:1/1": ("attempt_workflow", "PENDING", [("reserve_step", {})]),          # waiting for money
            "c/5/gates:1/1": ("attempt_workflow", "PENDING", [("lease_step", {"worker_id": None, "reason": "x"})]),
            "d/1/admit/1": ("prepared_attempt_workflow", "PENDING", [("lease_alive_step", True)]),
            "d/1/admit/2": ("prepared_attempt_workflow", "PENDING", [("lease_alive_step", False)]),
            "e/1/writer:1/1": ("attempt_workflow", "SUCCESS", [LEASED]),
            "e": ("case_workflow", "PENDING", [LEASED]),
        })
        self.assertEqual(drained.steps_in_flight(client), ["c/3/writer:1/1", "d/1/admit/1"])


class Main(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.config = self.dir / "config.json"
        self.config.write_text(json.dumps({"database_url": "sqlite:///unused", "state_dir": str(self.dir)}))
        self.router = self.dir / "factory.sqlite3"
        with sqlite3.connect(self.router) as db:   # model_router's schema
            db.execute("CREATE TABLE leases (id TEXT PRIMARY KEY, route TEXT, expires REAL, outcome TEXT, receipt TEXT)")
            db.execute("INSERT INTO leases VALUES ('done', '{}', 9e9, 'ok', NULL)")
            db.execute("INSERT INTO leases VALUES ('stale', '{}', 1, NULL, NULL)")

    def check(self, workflows):
        fake = types.ModuleType("dbos")
        fake.DBOSClient = lambda **kw: FakeClient(workflows)
        with patch.dict("sys.modules", {"dbos": fake}), \
                patch("sys.stdout", new_callable=io.StringIO) as out, patch("sys.stderr", new_callable=io.StringIO):
            code = drained.main(["--config", str(self.config), "--router-db", str(self.router)])
        return code, out.getvalue()

    def test_drained_when_no_step_or_live_lease(self):
        before = self.router.read_bytes()
        self.assertEqual(self.check({"c/2/stress:1/1": ("attempt_workflow", "SUCCESS", [LEASED])}),
                         (0, "router leases active: 0\ndrained\n"))
        self.assertEqual(self.router.read_bytes(), before)   # read-only: the stale lease is not expired here

    def test_a_running_step_or_a_live_router_lease_is_not_drained(self):
        code, out = self.check({"c/3/writer:1/1": ("attempt_workflow", "PENDING", [LEASED])})
        self.assertEqual(code, 1)
        self.assertIn("step in flight: c/3/writer:1/1", out)
        with sqlite3.connect(self.router) as db:
            db.execute("INSERT INTO leases VALUES ('live', '{}', 9e9, NULL, NULL)")
        code, out = self.check({})
        self.assertEqual(code, 1)
        self.assertIn("router leases active: 1", out)

    def test_an_unreadable_input_is_never_drained(self):
        self.router.unlink()
        self.assertEqual(self.check({})[0], 2)


if __name__ == "__main__":
    unittest.main()
