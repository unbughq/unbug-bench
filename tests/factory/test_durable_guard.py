"""The campaign guard, with the VM's real request shape and a fake Boat, socket and service."""
import http.server
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "factory"))
from durable.guard import CheckFailed, Guard, degraded, health, scrub, webhook
from durable.report import render_status

REQUEST = {"batch_id": "b-sealday20261106r3", "case_id": "case-sealday20261106r3-1",
           "approved_infrastructure_usd": 10, "prior_compute_retained_usd": 2, "control_allowance_usd": 2,
           "max_workers_lifetime": 12, "cleanup_margin_usd": 2, "deadline_epoch": 1794053270.0,
           "wall_seconds": 86400, "max_worker_rate_usd_per_second": 2e-05}
NOW = 1793990000.0
USAGE = json.dumps({"dollars": 0.02, "billingMultiplier": 1.0, "secondsPerDollar": 100000}).encode()


def inventory(*ids):
    return json.dumps({"sandboxes": [{"id": i} for i in ids], "pageInfo": {"hasMore": False}}).encode()


class Fake:
    def __init__(self, work):
        self.clock = NOW
        self.state_dir = Path(work)
        self.calls, self.stopped, self.sent = [], 0, []
        self.boat_failures = {}
        self.rows = ["bx_aaaaaaaa"]
        self.usage = USAGE
        self.active = "active"
        self.cases = [{"case": REQUEST["case_id"], "status": "running"}]
        self.money = {"spent": 1, "bound": 2}
        self.rpc_failures = 0
        self.allowance = 7

    def boat(self, args, timeout):
        self.calls.append(args)
        self.clock += 0.1
        left = self.boat_failures.get(args[0], 0)
        if left:
            self.boat_failures[args[0]] = left - 1
            self.clock += timeout
            return {"code": 124, "out": b"", "stderr": b"boat-call: timed out reaching 10.0.0.1", "seconds": timeout}
        out = {"list": inventory(*self.rows), "usage": self.usage}.get(args[0], b"{}")
        return {"code": 0, "out": out, "stderr": b"", "seconds": 0.1}

    def rpc(self, op):
        if self.rpc_failures:
            self.rpc_failures -= 1
            raise ConnectionRefusedError()
        return {"status": {"cases": self.cases}, "budget": self.money, "publish": {"published": "k"}}[op]

    def state(self):
        return self.active, NOW - 3600, NOW - 3600

    def stop(self):
        self.stopped += 1

    def guard(self, **kw):
        return Guard(REQUEST, self.state_dir / "guard", boat=self.boat, rpc=self.rpc, service=self, ours=lambda r: True,
                     count=lambda: self.allowance, notify=self.sent.append, clock=lambda: self.clock,
                     sleep=lambda s: setattr(self, "clock", self.clock + s), **kw)

    def deletes(self):
        return [c for c in self.calls if c[0] in ("delete", "rm", "destroy")]


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.f = Fake(self.tmp.name)

    def tick(self, seconds=60, **kw):
        self.f.clock += seconds
        return self.f.guard().run(**kw)

    def test_healthy_pass_renews_the_worker(self):
        out = self.tick()
        self.assertEqual(out["phase"], "healthy")
        self.assertEqual(self.f.stopped, 0)
        self.assertIn(["extend", "bx_aaaaaaaa", "--ttl", "7200"], self.f.calls)

    def test_the_hung_usage_call_of_6_november_only_degrades(self):
        """All three tries hang: the batch degrades, nothing stops, and the worker stays."""
        self.f.boat_failures["usage"] = 3
        out = self.tick()
        self.assertEqual(out["phase"], "degraded")
        self.assertEqual(out["failed_checks"], ["boat_usage"])
        self.assertEqual(self.f.stopped, 0)
        self.assertEqual(self.f.deletes(), [])
        self.assertIn(["extend", "bx_aaaaaaaa", "--ttl", "7200"], self.f.calls)
        self.assertTrue((self.f.state_dir / "guard/degraded.json").exists())
        evidence = json.loads((self.f.state_dir / "guard/evidence.json").read_text())
        self.assertEqual([(e["check"], e["try"], e["code"]) for e in evidence],
                         [("boat_usage", n, "exit_124") for n in (1, 2, 3)])
        self.assertGreaterEqual(evidence[0]["seconds"], 30)
        self.assertNotIn("10.0.0.1", json.dumps(evidence))

    def test_a_retry_that_works_leaves_no_degradation(self):
        self.f.boat_failures["usage"] = 2
        self.assertEqual(self.tick()["phase"], "healthy")

    def test_recovery_clears_the_pause(self):
        self.f.boat_failures["list"] = 3
        self.assertEqual(self.tick()["phase"], "degraded")
        self.assertEqual(self.tick()["phase"], "healthy")
        self.assertFalse((self.f.state_dir / "guard/degraded.json").exists())

    def test_sustained_failure_alerts_once_and_never_stops(self):
        self.f.rpc_failures = 10 ** 6
        for _ in range(20):
            out = self.tick()
        self.assertEqual(out["phase"], "degraded")
        self.assertEqual(self.f.stopped, 0)
        self.assertEqual(len(self.f.sent), 1)
        self.assertIn("paused", self.f.sent[0])
        self.assertIn("controller_status", self.f.sent[0])

    def test_an_alert_that_failed_to_send_is_retried(self):
        self.f.cases[0]["status"] = "escalated"
        tries = []
        def flaky(message):
            tries.append(message)
            if len(tries) == 1:
                raise OSError()
        self.f.clock += 60
        guard = self.f.guard()
        guard.notify = flaky
        guard.run()
        guard = self.f.guard()
        guard.notify = flaky
        guard.run()
        guard = self.f.guard()
        guard.notify = flaky
        guard.run()
        self.assertEqual(len(tries), 2)

    def test_every_founder_wait_gets_one_message(self):
        for status, phrase in (("escalated", "ruling"), ("waiting_for_bound", "Raise the batch bound"),
                               ("stopped_admission", "stopped admission")):
            self.f.sent.clear()
            self.f.cases[0]["status"] = status
            self.tick()
            self.tick()
            self.assertEqual(len(self.f.sent), 1, status)
            self.assertIn(phrase, self.f.sent[0])

    def test_controller_down_alerts_after_ten_minutes_and_keeps_the_worker(self):
        self.f.active = "failed"
        self.tick()
        self.assertEqual(self.f.sent, [])
        self.tick(601)
        self.assertEqual(len(self.f.sent), 1)
        self.assertIn("down", self.f.sent[0])
        self.assertEqual(self.f.stopped, 0)
        self.assertIn(["extend", "bx_aaaaaaaa", "--ttl", "7200"], self.f.calls)

    def test_a_controller_inside_its_grace_period_is_not_judged(self):
        self.f.rpc_failures = 10 ** 6
        self.f.state = lambda: ("active", self.f.clock - 30, None)
        self.assertEqual(self.tick()["phase"], "starting")
        self.assertEqual(self.f.calls, [])

    def test_a_controller_that_never_gets_ready_is_judged_after_grace(self):
        self.f.rpc_failures = 10 ** 6
        self.f.state = lambda: ("active", self.f.clock - 300, None)
        self.assertEqual(self.tick()["phase"], "degraded")

    def hard(self, reason):
        out = self.tick()
        self.assertEqual((out["phase"], out["hard_stop"]), ("stopped", reason))
        self.assertEqual(self.f.stopped, 1)
        self.assertEqual(self.f.deletes(), [])
        self.assertNotIn("extend", [c[0] for c in self.f.calls])
        self.f.calls.clear()
        out = self.tick()   # stays stopped; renewal never resumes
        self.assertEqual(out["hard_stop"], reason)
        self.assertEqual(self.f.calls, [])

    def test_money_ceiling_is_a_hard_stop(self):
        self.f.money = {"spent": 3, "bound": 2}
        self.hard("money_ceiling")

    def test_confirmed_rate_breach_is_a_hard_stop(self):
        self.f.usage = json.dumps({"dollars": 0.02, "billingMultiplier": 10.0, "secondsPerDollar": 1000}).encode()
        self.hard("worker_rate")

    def test_two_live_workers_is_a_hard_stop(self):
        self.f.rows = ["bx_aaaaaaaa", "bx_bbbbbbbb"]
        self.hard("worker_count")

    def test_exceeded_allowance_is_a_hard_stop_but_unreadable_is_not(self):
        self.f.allowance = "junk"
        self.assertEqual(self.tick()["phase"], "degraded")
        self.f.allowance = 13
        self.f.calls.clear()
        self.hard("worker_allowance")

    def test_deadline_is_a_hard_stop(self):
        self.f.clock = REQUEST["deadline_epoch"] - 60
        self.hard("deadline")

    def test_cleanup_timer_stops_without_deleting(self):
        out = self.tick(cleanup=True)
        self.assertEqual(out["hard_stop"], "deadline")
        self.assertEqual(self.f.stopped, 1)
        self.assertEqual(self.f.calls, [])

    def test_a_finished_batch_publishes_and_stops(self):
        self.f.cases[0]["status"] = "sealed"
        out = self.tick()
        self.assertEqual(out["phase"], "finished")
        self.assertEqual(self.f.stopped, 1)
        self.assertEqual(self.tick()["phase"], "finished")
        self.assertEqual(self.f.stopped, 1)

    def test_a_guard_bug_only_degrades(self):
        guard = self.f.guard()
        guard.ours = lambda row: 1 / 0
        self.f.clock += 60
        out = guard.run()
        self.assertEqual((out["phase"], self.f.stopped), ("degraded", 0))

    def test_webhook_posts_one_text_message(self):
        received = []
        class Hook(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(204)
                self.end_headers()
            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Hook)
        threading.Thread(target=server.handle_request, daemon=True).start()
        webhook(f"http://127.0.0.1:{server.server_port}/alerts")("needs a ruling")
        server.server_close()
        self.assertEqual(received, [{"text": "needs a ruling"}])

    def test_marker_is_read_and_goes_stale(self):
        self.assertFalse(degraded(self.f.state_dir))
        directory = self.f.state_dir / "guard"
        directory.mkdir()
        import time
        (directory / "degraded.json").write_text(json.dumps({"until": time.time() + 60}))
        self.assertTrue(degraded(self.f.state_dir))
        (directory / "degraded.json").write_text(json.dumps({"until": time.time() - 1}))
        self.assertFalse(degraded(self.f.state_dir))
        (directory / "degraded.json").write_text("junk")
        self.assertFalse(degraded(self.f.state_dir))

    def test_status_shows_health_alerts_and_evidence(self):
        self.f.boat_failures["usage"] = 3
        self.f.cases[0]["status"] = "waiting_for_bound"
        self.tick()
        record = health(self.f.state_dir)
        text = render_status({"batch": REQUEST["batch_id"], "sealed": 0, "cases": [], "observation": {"guard": record}})
        self.assertIn("FACTORY HEALTH", text)
        self.assertIn("DEGRADED", text)
        self.assertIn("boat_usage try 3: exit_124", text)
        self.assertIn("NEEDS YOU:", text)

    def test_scrub_removes_addresses_paths_and_tokens(self):
        text = scrub("connect 2.31.89.209 failed /home/user/.config/x token " + "a" * 40 + " " + "z" * 500)
        for secret in ("2.31.89.209", "/home/user", "a" * 40):
            self.assertNotIn(secret, text)
        self.assertLessEqual(len(text), 240)

    def test_check_failed_detail_is_scrubbed(self):
        self.assertEqual(CheckFailed("x", "from 1.2.3.4").detail, "from [ip]")


if __name__ == "__main__":
    unittest.main()
