"""The campaign guard, with the VM's real request shape and a fake Boat, socket and service."""
import http.server
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "factory"))
from durable.guard import CheckFailed, Guard, degraded, health, router_spend, scrub, webhook
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
        self.in_flight = 0
        self.deleted = []

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
        return {"status": {"cases": self.cases}, "budget": self.money, "publish": {"published": "k"},
                "in_flight": self.in_flight}[op]

    def state(self):
        return self.active, NOW - 3600, NOW - 3600

    def stop(self):
        self.stopped += 1
        self.active = "inactive"

    def delete(self, worker):
        self.deleted.append(worker)
        self.rows.remove(worker)

    def guard(self, **kw):
        return Guard(REQUEST, self.state_dir / "guard", boat=self.boat, rpc=self.rpc, service=self, ours=lambda r: True,
                     count=lambda: self.allowance, delete=self.delete, notify=self.sent.append, clock=lambda: self.clock,
                     sleep=lambda s: setattr(self, "clock", self.clock + s), **kw)

    def deletes(self):
        return self.deleted


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

    def test_a_crash_loop_cannot_hide_behind_the_grace_period(self):
        """Up for 30 seconds at a time: never ready, but alerted, and the worker still renewed."""
        self.f.active = "failed"
        self.tick()
        self.f.state = lambda: ("active", self.f.clock - 30, None)
        self.tick(601)
        self.assertEqual(len(self.f.sent), 1)
        self.assertIn(["extend", "bx_aaaaaaaa", "--ttl", "7200"], self.f.calls)

    def test_a_restart_during_an_outage_keeps_new_attempts_paused(self):
        self.f.boat_failures["usage"] = 3
        self.tick()
        self.f.state = lambda: ("active", self.f.clock - 30, None)
        self.assertEqual(self.tick()["phase"], "starting")
        self.assertTrue((self.f.state_dir / "guard/degraded.json").exists())

    def test_an_unreadable_service_state_still_checks_the_money(self):
        self.f.state = lambda: 1 / 0
        self.f.money = {"spent": 3, "bound": 2}
        self.assertEqual(self.tick()["hard_stop"], "money_ceiling")

    def test_a_malformed_controller_reply_only_degrades(self):
        self.f.money = {"unexpected": 1}
        out = self.tick()
        self.assertEqual((out["phase"], out["failed_checks"]), ("degraded", ["ledger"]))

    def test_a_malformed_case_row_degrades_and_leaves_no_bad_scorecard(self):
        self.f.cases = [{"status": "held"}]
        self.assertEqual(self.tick()["failed_checks"], ["controller_status"])
        self.assertFalse((self.f.state_dir / "guard/scorecard.json").exists())
        (self.f.state_dir / "guard/scorecard.json").write_text('{"cases": [{"status": "held"}, 1]}')
        self.f.cases = [{"case": "c", "status": "running"}]
        self.assertEqual(self.tick()["phase"], "healthy")   # an old bad file cannot crash a pass

    def test_a_batch_finishing_right_after_an_outage_leaves_no_false_down_alert(self):
        self.f.active = "failed"
        self.tick()
        self.f.active = "active"
        self.f.cases[0]["status"] = "sealed"
        self.f.state = lambda: ("active", self.f.clock - 30, None)
        self.tick(601)
        self.assertEqual(self.tick(601)["down_since"], None)
        self.assertEqual(self.f.sent, [])

    def test_a_failed_finishing_stop_is_retried(self):
        self.f.cases[0]["status"] = "sealed"
        stops = []
        def flaky():
            stops.append(1)
            if len(stops) <= 3:
                raise OSError()
        self.f.stop = flaky
        self.tick()
        self.assertEqual(self.tick()["phase"], "finished")
        self.assertEqual(len(stops), 4)

    def test_a_controller_inside_its_grace_period_is_not_judged(self):
        self.f.rpc_failures = 10 ** 6
        self.f.state = lambda: ("active", self.f.clock - 30, None)
        self.assertEqual(self.tick()["phase"], "starting")
        self.assertEqual(self.f.calls, [])

    def test_a_controller_that_never_gets_ready_is_judged_after_grace(self):
        self.f.rpc_failures = 10 ** 6
        self.f.state = lambda: ("active", self.f.clock - 300, None)
        self.assertEqual(self.tick()["phase"], "degraded")

    def hard(self, reason, *, workers=("bx_aaaaaaaa",)):
        """Nothing in flight: stopped and deleted in the same pass."""
        out = self.tick()
        self.assertEqual((out["phase"], out["hard_stop"]), ("stopped", reason))
        self.assertEqual(self.f.stopped, 1)
        self.assertEqual(self.f.deletes(), list(workers))
        self.assertNotIn("extend", [c[0] for c in self.f.calls])
        self.f.calls.clear()
        out = self.tick()   # stays stopped; renewal never resumes
        self.assertEqual(out["hard_stop"], reason)
        self.assertEqual(self.f.calls, [["list", "--json"]])
        self.assertEqual(self.f.stopped, 1)

    def test_money_ceiling_is_a_hard_stop(self):
        self.f.money = {"spent": 3, "bound": 2}
        self.hard("money_ceiling")

    def test_confirmed_rate_breach_is_a_hard_stop(self):
        self.f.usage = json.dumps({"dollars": 0.02, "billingMultiplier": 10.0, "secondsPerDollar": 1000}).encode()
        self.hard("worker_rate")

    def test_two_live_workers_is_a_hard_stop(self):
        self.f.rows = ["bx_aaaaaaaa", "bx_bbbbbbbb"]
        self.hard("worker_count", workers=("bx_aaaaaaaa", "bx_bbbbbbbb"))

    def test_exceeded_allowance_is_a_hard_stop_but_unreadable_is_not(self):
        self.f.allowance = "junk"
        self.assertEqual(self.tick()["phase"], "degraded")
        self.f.allowance = 13
        self.f.calls.clear()
        self.hard("worker_allowance")

    def test_deadline_is_a_hard_stop(self):
        self.f.clock = REQUEST["deadline_epoch"] - 60
        self.hard("deadline")

    def test_the_ttl_covers_the_grace_after_the_deadline(self):
        self.f.clock = REQUEST["deadline_epoch"] - 100
        self.tick(0)
        self.assertIn(["extend", "bx_aaaaaaaa", "--ttl", "699"], self.f.calls)

    def test_cleanup_timer_stops_without_deleting(self):
        self.f.in_flight = 1
        out = self.tick(cleanup=True)
        self.assertEqual((out["phase"], out["hard_stop"]), ("stopping", "deadline"))
        self.assertEqual((self.f.stopped, self.f.deletes()), (0, []))

    def test_steps_in_flight_get_the_grace_then_the_worker_is_deleted_regardless(self):
        self.f.money = {"spent": 3, "bound": 2}
        self.f.in_flight = 1
        out = self.tick()
        self.assertEqual((out["phase"], self.f.stopped), ("stopping", 0))
        self.assertTrue((self.f.state_dir / "guard/degraded.json").exists())
        self.assertEqual(len(self.f.sent), 1)
        self.f.calls.clear()
        for _ in range(8):
            self.assertEqual(self.tick()["phase"], "stopping")
        self.assertEqual((self.f.stopped, self.f.deletes()), (0, []))
        self.assertNotIn("extend", [c[0] for c in self.f.calls])
        self.assertEqual(self.tick(180)["phase"], "stopped")   # the grace is over; still in flight
        self.assertEqual((self.f.stopped, self.f.deletes()), (1, ["bx_aaaaaaaa"]))
        self.assertEqual(len(self.f.sent), 1)

    def test_a_step_finishing_early_means_the_worker_goes_at_once(self):
        self.f.money = {"spent": 3, "bound": 2}
        self.f.in_flight = 1
        self.assertEqual(self.tick()["phase"], "stopping")
        self.f.in_flight = 0
        self.assertEqual(self.tick()["phase"], "stopped")
        self.assertEqual(self.f.deletes(), ["bx_aaaaaaaa"])

    def test_an_unanswering_controller_keeps_the_grace_and_a_dead_one_does_not(self):
        self.f.money = {"spent": 3, "bound": 2}
        self.f.in_flight = 1
        self.tick()
        self.f.rpc_failures = 10 ** 6
        self.assertEqual(self.tick()["phase"], "stopping")
        self.f.active = "failed"
        self.assertEqual(self.tick()["phase"], "stopped")
        self.assertEqual(self.f.deletes(), ["bx_aaaaaaaa"])

    def test_a_hard_stop_holds_when_the_controller_comes_back(self):
        """A reboot restarts the unit. It must not run on unwatched, with new work open."""
        self.f.money = {"spent": 3, "bound": 2}
        self.tick()
        self.f.active = "active"
        self.f.rows = ["bx_cccccccc"]
        self.f.deleted.clear()
        out = self.tick()
        self.assertEqual((out["phase"], self.f.stopped, self.f.deleted), ("stopped", 2, ["bx_cccccccc"]))

    def test_a_failed_controller_stop_or_inventory_keeps_the_stop_going(self):
        self.f.money = {"spent": 3, "bound": 2}
        real, fails = self.f.stop, [3]
        def flaky():
            if fails[0]:
                fails[0] -= 1
                raise OSError()
            real()
        self.f.stop = flaky
        self.assertEqual(self.tick()["phase"], "stopping")
        self.assertEqual(self.f.deleted, [])
        self.f.boat_failures["list"] = 3
        self.assertEqual(self.tick()["phase"], "stopping")
        self.assertEqual(self.f.deleted, [])
        self.assertEqual(self.tick()["phase"], "stopped")
        self.assertEqual(self.f.deleted, ["bx_aaaaaaaa"])

    def test_real_router_spend_stops_when_the_ledger_reads_low(self):
        """Live on 6 November the ledger booked $0.91 for an attempt the router charged $4.91."""
        self.f.money = {"spent": 1, "bound": 2, "held": 0}
        guard = self.f.guard(router=lambda: (49.2, 49.95))   # short of it, as the router never quite reaches it
        self.f.clock += 60
        out = guard.run()
        self.assertEqual((out["phase"], out["hard_stop"]), ("stopped", "money_ceiling"))
        self.assertEqual(out["router_spent_usd"], 49.2)

    def test_router_books_are_read_for_real(self):
        db = self.f.state_dir / "router.sqlite3"
        conn = sqlite3.connect(db)
        conn.executescript("""CREATE TABLE paid_requests (charge INTEGER, state TEXT);
            CREATE TABLE paid_account (id INTEGER, ceiling INTEGER, credit INTEGER);
            INSERT INTO paid_requests VALUES (1000000000, 'settled'), (500000000, 'unknown'), (NULL, 'settled'),
                (11000000000, 'pending');""")   # holds of calls in flight are not spend
        conn.commit()
        self.assertEqual(router_spend(db), (1.5, math.inf, None))   # no ceiling row: never a false deadlock
        conn.execute("INSERT INTO paid_account VALUES (1, 49946728440, 8771396466)")
        conn.commit()
        conn.close()
        self.assertEqual(router_spend(db), (1.5, 49.94672844, 8.771396466))

    def test_low_provider_credit_and_a_credit_refusal_each_alert_once(self):
        """7 November: the account fell to $8.77 and calls were refused with no alert."""
        self.f.money = {"spent": 1, "bound": 2, "held": 0}
        self.f.cases[0]["reason"] = "router:credit"
        for _ in range(3):
            self.f.clock += 60
            self.f.guard(router=lambda: (5.0, 49.95, 8.77)).run()
        self.assertEqual(len(self.f.sent), 2)
        self.assertTrue(any("$8.77" in m for m in self.f.sent))
        self.assertTrue(any("lack of credit" in m for m in self.f.sent))
        self.f.sent.clear()
        self.f.cases[0]["reason"] = None
        self.f.clock += 60
        self.f.guard(router=lambda: (5.0, 49.95, 120.0)).run()
        self.assertEqual(self.f.sent, [])

    def test_router_below_its_ceiling_changes_nothing_and_unreadable_only_degrades(self):
        self.f.money = {"spent": 1, "bound": 2, "held": 0}
        self.f.clock += 60
        self.assertEqual(self.f.guard(router=lambda: (5.0, 49.95)).run()["phase"], "healthy")
        self.f.clock += 60
        out = self.f.guard(router=lambda: 1 / 0).run()
        self.assertEqual((out["phase"], out["failed_checks"]), ("degraded", ["router_spend"]))

    def test_no_budget_alert_while_an_attempt_holds_money(self):
        self.f.cases[0]["status"] = "waiting_for_bound"
        self.f.money = {"spent": 1, "bound": 2, "held": 1}
        self.tick()
        self.assertEqual(self.f.sent, [])
        self.f.money = {"spent": 2, "bound": 2, "held": 0}
        self.tick()
        self.assertEqual(len(self.f.sent), 1)

    def test_admission_that_keeps_failing_raises_one_alert(self):
        self.f.cases[0]["status"] = "retrying_admission"
        self.tick()
        self.tick()
        self.assertEqual(len(self.f.sent), 1)
        self.assertIn("still retrying", self.f.sent[0])

    def test_a_failed_stop_or_delete_is_retried(self):
        self.f.money = {"spent": 3, "bound": 2}
        delete, left = self.f.delete, [3]
        def flaky(worker):
            if left[0]:
                left[0] -= 1
                raise OSError()
            delete(worker)
        self.f.delete = flaky
        self.assertEqual(self.tick()["phase"], "stopping")
        self.assertEqual(self.tick()["phase"], "stopped")
        self.assertEqual(self.f.deleted, ["bx_aaaaaaaa"])
        self.assertEqual(self.f.stopped, 1)

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
