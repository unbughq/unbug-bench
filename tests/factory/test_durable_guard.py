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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "factory"))
from durable.guard import CheckFailed, Guard, degraded, health, router_spend, scrub, webhook
from durable.report import render_status

REQUEST = {"batch_id": "b-sealday20261106r3", "case_id": "case-sealday20261106r3-1",
           "approved_infrastructure_usd": 10, "prior_compute_retained_usd": 2, "control_allowance_usd": 2,
           "max_running_sandboxes": 1, "max_starts_per_hour": 30, "cleanup_margin_usd": 2, "deadline_epoch": 1794053270.0,
           "wall_seconds": 86400, "max_worker_rate_usd_per_second": 2e-05}
NOW = 1793990000.0
USAGE = json.dumps({"dollars": 0.02, "billingMultiplier": 1.0, "secondsPerDollar": 100000}).encode()


def inventory(*ids, types=None):
    rows = [{"id": i, **({"type": types[i]} if i in (types or {}) else {})} for i in ids]
    return json.dumps({"sandboxes": rows, "pageInfo": {"hasMore": False}}).encode()


class Fake:
    def __init__(self, work):
        self.clock = NOW
        self.state_dir = Path(work)
        self.calls, self.stopped, self.sent = [], 0, []
        self.boat_failures = {}
        self.boat_refusals = {}   # Boat itself answers with an error (not a timeout)
        self.rows = ["bx_aaaaaaaa"]
        self.types = {}   # Boat's type per sandbox, when the inventory says
        self.usage = USAGE
        self.active = "active"
        self.cases = [{"case": REQUEST["case_id"], "status": "running"}]
        self.money = {"spent": 1, "bound": 2}
        self.rpc_failures = 0
        self.allowance = [NOW - 7200, NOW - 600]
        self.in_flight = 0
        self.deleted = []
        self.rpc_batches, self.per_batch, self.request = [], {}, REQUEST

    def boat(self, args, timeout):
        self.calls.append(args)
        self.clock += 0.1
        if self.boat_refusals.get(args[0], 0):
            self.boat_refusals[args[0]] -= 1
            return {"code": 1, "out": b'{"code":"not_found","error":"sandbox not found","event":"error","status":404}',
                    "stderr": b"", "seconds": 0.1}
        left = self.boat_failures.get(args[0], 0)
        if left:
            self.boat_failures[args[0]] = left - 1
            self.clock += timeout
            return {"code": 124, "out": b"", "stderr": b"boat-call: timed out reaching 10.0.0.1", "seconds": timeout}
        out = {"list": inventory(*self.rows, types=self.types), "usage": self.usage}.get(args[0], b"{}")
        return {"code": 0, "out": out, "stderr": b"", "seconds": 0.1}

    def rpc(self, op, batch=None):
        if self.rpc_failures:
            self.rpc_failures -= 1
            raise ConnectionRefusedError()
        self.rpc_batches.append((op, batch))
        cases, money = self.per_batch.get(batch, (self.cases, self.money))
        return {"status": {"cases": cases}, "budget": money, "publish": {"published": "k"},
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
        return Guard(self.request, self.state_dir / "guard", boat=self.boat, rpc=self.rpc, service=self, ours=lambda r: True,
                     count=lambda: self.allowance, delete=self.delete, notify=self.sent.append, clock=lambda: self.clock,
                     sleep=lambda s: setattr(self, "clock", self.clock + s), **kw)

    def deletes(self):
        return self.deleted


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.f = Fake(self.tmp.name)

    def tick(self, seconds=60, router=None, **kw):
        self.f.clock += seconds
        return self.f.guard(**({"router": router} if router else {})).run(**kw)

    def test_a_campaign_watches_several_batches(self):
        f = self.f
        f.request = {**REQUEST, "batch_ids": ["b-one", "b-two"], "max_running_sandboxes": 2,
                          "approved_infrastructure_usd": 12}
        running, done = [{"case": "c1", "status": "running"}], [{"case": "c2", "status": "sealed"}]
        f.per_batch = {"b-one": (running, {"spent": 1, "bound": 25, "held": 3}),
                       "b-two": (done, {"spent": 2, "bound": 25, "held": 0})}
        f.rows = ["bx_aaaaaaaa", "bx_bbbbbbbb"]           # one worker per batch is not a breach
        out = self.tick()
        self.assertEqual((out["phase"], out["hard_stop"], out["money_held"]), ("healthy", None, 3))
        self.assertEqual({b for op, b in f.rpc_batches if op == "status"}, {"b-one", "b-two"})
        self.assertFalse(out["finished"])                  # one batch still running
        f.per_batch["b-one"] = (done, {"spent": 1, "bound": 25, "held": 0})
        out = self.tick()
        self.assertTrue(out["finished"])                   # every batch terminal: publish each, stop
        self.assertEqual({b for op, b in f.rpc_batches if op == "publish"}, {"b-one", "b-two"})

    def test_any_watched_batch_over_its_bound_is_a_hard_stop(self):
        self.f.request = {**REQUEST, "batch_ids": ["b-one", "b-two"], "max_running_sandboxes": 2,
                          "approved_infrastructure_usd": 12}
        self.f.per_batch = {"b-two": (self.f.cases, {"spent": 26, "bound": 25})}
        self.hard("money_ceiling")

    def test_the_compute_bound_counts_one_wall_per_running_slot(self):
        # Three slots busy for the whole wall and grace need $5.22: this request's $4 of headroom covers two.
        self.f.request = {**REQUEST, "max_running_sandboxes": 3}
        self.hard("compute_bound")
        self.f.request = {**REQUEST, "max_running_sandboxes": 3, "approved_infrastructure_usd": 12}
        self.f.calls.clear(); self.f.stopped = 0
        import shutil; shutil.rmtree(self.f.state_dir / "guard", ignore_errors=True)
        self.assertEqual(self.tick()["hard_stop"], None)

    def test_a_large_worker_is_judged_at_its_approved_type_rate(self):
        # A large (8 vCPU/16 GB) worker at $6e-05/s passes the default type's $2e-05/s cap: a false
        # worker_rate stop unless the request approves the large rate. The approval itself is unchanged.
        self.f.usage = json.dumps({"dollars": 0.02, "billingMultiplier": 1.0, "secondsPerDollar": 1 / 6e-05}).encode()
        large = {**REQUEST, "vm_type": "large", "worker_rates_usd_per_second": {"large": 8e-05},
                 "approved_infrastructure_usd": 14}
        self.f.request = large
        out = self.tick()
        self.assertEqual((out["phase"], out["hard_stop"]), ("healthy", None))
        self.f.request = {**large, "approved_infrastructure_usd": 10}   # $7.54 of large compute, $4 headroom
        self.f.calls.clear()
        self.hard("compute_bound")

    def test_a_worker_type_without_an_approved_rate_only_degrades(self):
        self.f.request = {**REQUEST, "vm_type": "large"}
        out = self.tick()
        self.assertEqual((out["phase"], out["hard_stop"]), ("degraded", None))
        self.assertLessEqual({"request", "request_rate"}, set(out["failed_checks"]))
        self.f.usage = json.dumps({"dollars": 0.02, "billingMultiplier": 1.0, "secondsPerDollar": 1 / 6e-05}).encode()
        self.f.request = REQUEST                                          # the default type keeps its cap
        self.f.calls.clear()
        self.hard("worker_rate")

    def test_each_live_worker_is_judged_at_its_own_type_rate(self):
        # The request moved to large while a default worker still runs at $6e-05/s: that worker is
        # over the default cap. A large worker at the same rate is within its approved rate.
        self.f.usage = json.dumps({"dollars": 0.02, "billingMultiplier": 1.0, "secondsPerDollar": 1 / 6e-05}).encode()
        large = {**REQUEST, "vm_type": "large", "worker_rates_usd_per_second": {"large": 8e-05},
                 "approved_infrastructure_usd": 14}
        self.f.request, self.f.types = large, {"bx_aaaaaaaa": "large"}
        self.assertEqual(self.tick()["hard_stop"], None)
        self.f.request = REQUEST   # back to default: the live large worker's rate is not approved
        out = self.tick()
        self.assertEqual((out["phase"], out["hard_stop"]), ("degraded", None))
        self.assertIn("request_rate", out["failed_checks"])
        self.f.request, self.f.types = large, {"bx_aaaaaaaa": "default"}
        self.f.calls.clear()
        self.hard("worker_rate")

    def test_a_default_key_never_overrides_the_default_rate(self):
        self.f.usage = json.dumps({"dollars": 0.02, "billingMultiplier": 1.0, "secondsPerDollar": 1 / 6e-05}).encode()
        self.f.request = {**REQUEST, "worker_rates_usd_per_second": {"default": 1.0}}
        self.hard("worker_rate")

    def test_a_malformed_worker_type_only_degrades(self):
        for bad in ({"vm_type": 7}, {"worker_rates_usd_per_second": [1]},
                    {"max_worker_rate_usd_per_second": None}):
            with self.subTest(bad=bad):
                self.f.request = {**REQUEST, **bad}
                out = self.tick()
                self.assertEqual((out["phase"], out["hard_stop"]), ("degraded", None))

    def test_starts_never_add_to_the_compute_bound(self):
        # The old lifetime cap stopped every case once 30 workers had been created.
        self.f.allowance = [NOW - 86400 + 3600 * h for h in range(24) for _ in range(5)]   # 120 starts a day
        out = self.tick()
        self.assertEqual((out["phase"], out["hard_stop"]), ("healthy", None))

    def test_a_request_without_worker_limits_only_degrades(self):
        for bad in ({"max_running_sandboxes": None}, {"max_running_sandboxes": 101},
                    {"max_starts_per_hour": 60}, {"max_starts_per_hour": True}):
            with self.subTest(bad=bad):
                self.f.request = {**REQUEST, **bad}
                out = self.tick()
                self.assertEqual((out["phase"], out["hard_stop"]), ("degraded", None))
                self.assertIn("request", out["failed_checks"])
        self.f.request = {k: v for k, v in REQUEST.items() if k != "max_running_sandboxes"}
        self.assertEqual(self.tick()["phase"], "degraded")
        self.f.request = {k: v for k, v in REQUEST.items() if k != "approved_infrastructure_usd"}
        self.assertEqual(self.tick()["phase"], "degraded")
        # The per-worker rate needs no limits and is still checked.
        self.f.usage = json.dumps({"dollars": 0.02, "billingMultiplier": 10.0, "secondsPerDollar": 1000}).encode()
        self.f.request = {**REQUEST, "max_running_sandboxes": None}
        self.f.calls.clear()
        self.hard("worker_rate")

    def test_more_live_workers_than_the_running_cap_pauses_new_attempts(self):
        # Our own cap (an operator may lower it mid-run) degrades; it is not a Boat breach.
        self.f.request = {**REQUEST, "batch_ids": ["b-one", "b-two"], "max_running_sandboxes": 2,
                          "approved_infrastructure_usd": 12}
        self.f.rows = ["bx_aaaaaaaa", "bx_bbbbbbbb", "bx_cccccccc"]
        out = self.tick()
        self.assertEqual((out["phase"], out["hard_stop"]), ("degraded", None))
        self.assertIn("running_cap", out["failed_checks"])
        self.assertEqual(self.f.deletes(), [])

    def test_more_live_workers_than_the_boat_plan_is_a_hard_stop(self):
        self.f.request = {**REQUEST, "max_running_sandboxes": 1}
        self.f.rows = [f"bx_{i:08d}" for i in range(101)]
        self.hard("worker_count", workers=tuple(self.f.rows))

    def test_live_workers_past_the_whole_compute_bound_are_a_hard_stop(self):
        # Each worker under the rate, but together past the $1.88 bound.
        self.f.request = {**REQUEST, "max_running_sandboxes": 1}
        self.f.rows = ["bx_aaaaaaaa", "bx_bbbbbbbb"]
        self.f.usage = json.dumps({"dollars": 1.0, "billingMultiplier": 1.0, "secondsPerDollar": 100000}).encode()
        self.hard("worker_rate", workers=("bx_aaaaaaaa", "bx_bbbbbbbb"))

    def test_healthy_pass_renews_the_worker(self):
        out = self.tick()
        self.assertEqual(out["phase"], "healthy")
        self.assertEqual(self.f.stopped, 0)
        self.assertIn(["extend", "bx_aaaaaaaa", "--ttl", "7200"], self.f.calls)

    def renewed(self):
        return json.loads((self.f.state_dir / "guard/renewed.json").read_text())

    def test_a_renewal_and_a_refusal_are_recorded_for_the_executor(self):
        self.tick()
        self.assertEqual(self.renewed(), {"bx_aaaaaaaa": {"ok": self.f.clock}})
        before = self.f.clock
        self.f.boat_refusals["extend"] = 3
        self.tick()
        self.assertEqual(self.renewed(), {"bx_aaaaaaaa": {"ok": before, "refused": self.f.clock}})

    def test_a_timed_out_renewal_is_unknown_and_never_retires_the_worker(self):
        # A long SSH silence: every extend times out. That is no refusal, so the executor's
        # renewing() stays unknown (None, never False) and the worker is kept.
        from durable.guard import renewing
        self.tick()
        before = self.renewed()
        self.f.boat_failures["extend"] = 3
        self.tick()
        self.assertEqual(self.renewed(), before)
        # The executor reads this right after the silent pass, when the last good renewal is already stale.
        stale = self.f.clock - before["bx_aaaaaaaa"]["ok"]
        with patch("time.time", return_value=self.f.clock + 1):
            self.assertIsNone(renewing(self.f.state_dir, "bx_aaaaaaaa", stale_s=stale))
        self.assertEqual(self.f.deletes(), [])

    def test_only_a_boat_api_refusal_of_the_sandbox_is_a_refusal(self):
        from durable.guard import boat_refused
        api = lambda status: {"code": 1, "out": ('{"event":"error","error":"x","status":%d}' % status).encode()}
        self.assertTrue(boat_refused(api(404)))
        unknown = [{"code": -9, "out": b""}, {"code": 124, "out": b""},            # killed, timed out
                   {"code": 1, "out": b'{"event":"error","error":"could not reach the Boat API"}'},   # lost link
                   {"code": 1, "out": b"boat-call: managed command refused"}, api(401), api(429), api(503)]
        for done in unknown:
            self.assertFalse(boat_refused(done), done)

    def test_a_control_plane_outage_or_operator_stop_records_no_refusal(self):
        self.tick()
        before = self.renewed()
        self.f.boat_failures["list"] = 3   # outage: no inventory, so no extend is attempted
        self.tick()
        self.f.active = "inactive"          # operator stop: no extend either
        self.tick()
        self.assertEqual(self.renewed(), before)
        from durable.guard import renewing
        self.assertIsNone(renewing(self.f.state_dir, "bx_aaaaaaaa", stale_s=0.0))

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

    def test_cases_waiting_on_credentials_or_the_router_read_degraded_and_alert(self):
        # 9 November: the router certificate expired and the guard read healthy for twenty minutes.
        for status in ("waiting_for_credentials", "waiting_for_router"):
            with self.subTest(status=status):
                self.f.sent.clear()
                self.f.cases[0]["status"] = status
                out = self.tick()
                self.assertEqual((out["phase"], out["stalled"], out["hard_stop"]), ("degraded", status, None))
                self.assertEqual(out["stalled_cases"], [REQUEST["case_id"]])
                self.assertEqual(out["failed_checks"], [])
                self.assertFalse((self.f.state_dir / "guard/degraded.json").exists())   # alerts, pauses nothing
                self.tick()
                self.assertEqual(len(self.f.sent), 1)
                self.assertIn(REQUEST["case_id"], self.f.sent[0])
                self.assertEqual((self.f.stopped, self.f.deleted), (0, []))
                text = render_status({"batch": REQUEST["batch_id"], "sealed": 0, "cases": [],
                                      "observation": {"guard": health(self.f.state_dir)}})
                self.assertIn(f"Stalled           {status}: {REQUEST['case_id']}", text)
        self.f.cases[0]["status"] = "running"
        out = self.tick()
        self.assertEqual((out["phase"], out["stalled"]), ("healthy", None))

    def test_a_case_newly_stuck_as_another_recovers_still_alerts(self):
        self.f.cases[:] = [{"case": "case-a", "status": "waiting_for_credentials"}, {"case": "case-b", "status": "running"}]
        self.tick()
        self.tick()
        self.assertEqual(len(self.f.sent), 1)
        self.assertIn("case-a", self.f.sent[0])
        self.f.cases[:] = [{"case": "case-a", "status": "running"}, {"case": "case-b", "status": "waiting_for_credentials"}]
        out = self.tick()
        self.assertEqual((out["stalled"], out["stalled_cases"]), ("waiting_for_credentials", ["case-b"]))
        self.assertEqual(len(self.f.sent), 2)
        self.assertIn("case-b", self.f.sent[1])
        self.assertNotIn("case-a", self.f.sent[1])
        self.f.cases[0]["status"] = "waiting_for_router"   # b's wait lasts: only a's new one alerts
        self.tick()
        self.tick()
        self.assertEqual(len(self.f.sent), 3)
        self.assertIn("case-a is stuck waiting for the router", self.f.sent[2])

    def test_no_progress_for_fifteen_minutes_reads_degraded_and_alerts_once(self):
        self.f.cases[0].update(stage="writer:1", writer_rounds=1)
        for _ in range(15):
            out = self.tick()
            self.assertEqual(out["phase"], "healthy")
        out = self.tick(90)
        self.assertEqual((out["phase"], out["stalled"]), ("degraded", "no_progress"))
        self.assertFalse((self.f.state_dir / "guard/degraded.json").exists())
        self.tick()
        self.assertEqual(len(self.f.sent), 1)
        self.assertIn("No case has made progress for 15 minutes", self.f.sent[0])
        self.f.cases[0]["stage"] = "stress:1"            # a step lands: healthy again
        out = self.tick()
        self.assertEqual((out["phase"], out["stalled"]), ("healthy", None))
        self.assertEqual(self.f.stopped, 0)

    def test_a_long_step_in_flight_is_progress(self):
        # A writer step on a subscription route runs for hours with no row change and no router spend.
        self.f.in_flight = 1
        for _ in range(30):
            out = self.tick()
        self.assertEqual((out["phase"], out["stalled"], self.f.sent), ("healthy", None, []))
        self.f.in_flight = 0                               # nothing in flight and nothing changes: a stall
        for _ in range(16):
            out = self.tick()
        self.assertEqual((out["phase"], out["stalled"]), ("degraded", "no_progress"))
        self.assertEqual(len(self.f.sent), 1)

    def test_a_failed_pass_between_stalled_passes_sends_nothing_again(self):
        self.f.cases[:] = [{"case": "case-a", "status": "waiting_for_credentials"}, {"case": "case-b", "status": "held"}]
        for _ in range(32):
            out = self.tick()
        self.assertEqual((out["stalled"], out["founder_waits"]), ("waiting_for_credentials", ["case-b"]))
        sent = list(self.f.sent)
        self.assertEqual(len(sent), 3)                     # held now, credentials now, founder wait at 30 minutes
        self.f.rpc_failures = 10 ** 6                      # the controller does not answer for a pass
        out = self.tick()
        self.assertEqual((out["stalled"], out["founder_waits"]), ("waiting_for_credentials", ["case-b"]))
        self.f.rpc_failures = 0
        self.tick()
        self.tick()
        self.assertEqual(self.f.sent, sent)

    def test_router_spend_counts_as_progress(self):
        spent = [1.0]
        for _ in range(20):
            spent[0] += 0.01
            out = self.tick(router=lambda: (spent[0], 100.0, 50.0))
        self.assertEqual((out["phase"], out["stalled"]), ("healthy", None))

    def test_a_case_parked_on_a_founder_decision_for_thirty_minutes_alerts(self):
        self.f.cases.append({"case": "case-other", "status": "running"})
        self.f.cases[0]["status"] = "held"
        spent = [1.0]
        for _ in range(30):                                # other work keeps moving
            spent[0] += 0.01
            out = self.tick(router=lambda: (spent[0], 100.0, 50.0))
        self.assertEqual((out["phase"], out["founder_waits"]), ("healthy", []))
        self.assertEqual(len(self.f.sent), 1)              # the existing immediate "held" message
        spent[0] += 0.01
        out = self.tick(90, router=lambda: (spent[0], 100.0, 50.0))
        self.assertEqual((out["phase"], out["stalled"], out["founder_waits"]),
                         ("degraded", "founder_wait", [REQUEST["case_id"]]))
        self.assertFalse((self.f.state_dir / "guard/degraded.json").exists())
        self.assertEqual(len(self.f.sent), 2)
        self.assertIn(f"{REQUEST['case_id']} has waited 30 minutes (held) for a decision on its hold", self.f.sent[1])
        self.f.cases[0]["status"] = "escalated"            # a new wait starts its own clock
        out = self.tick(router=lambda: (spent[0] + 1, 100.0, 50.0))
        self.assertEqual(out["founder_waits"], [])
        self.assertEqual(self.f.stopped, 0)

    def test_controller_down_alerts_after_ten_minutes_and_keeps_the_worker(self):
        self.f.active = "failed"
        self.tick()
        self.assertEqual(self.f.sent, [])
        self.tick(601)
        self.assertEqual(len(self.f.sent), 1)
        self.assertIn("down", self.f.sent[0])
        self.assertEqual(self.f.stopped, 0)
        self.assertIn(["extend", "bx_aaaaaaaa", "--ttl", "7200"], self.f.calls)

    def test_a_cleanly_stopped_controller_lets_its_idle_worker_expire(self):
        self.f.active = "inactive"   # systemctl stop: nothing runs on the worker
        self.tick()
        self.tick(601)
        self.assertNotIn("extend", [c[0] for c in self.f.calls])
        self.assertEqual((self.f.stopped, self.f.deletes()), (0, []))   # nothing deleted: Boat's timer ends it
        self.f.active = "active"     # a resume renews again
        self.tick(60)
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

    def test_starting_faster_than_boat_allows_is_a_hard_stop_and_our_own_limit_degrades(self):
        self.f.allowance = "junk"
        self.assertEqual(self.tick()["phase"], "degraded")
        self.f.allowance = [self.f.clock + 60 - 90 * i for i in range(35)]   # 35 starts in the hour; our cap is 30
        out = self.tick()
        self.assertEqual((out["phase"], out["hard_stop"]), ("degraded", None))
        self.assertIn("start_rate", out["failed_checks"])
        self.f.allowance = [self.f.clock + 60 - 50 * i for i in range(61)]   # 61 in the hour; Boat allows 60
        self.f.calls.clear()
        self.hard("worker_allowance")

    def test_each_start_window_is_checked(self):
        from durable.guard import starts_over
        self.assertFalse(starts_over([NOW - 1] * 10, 30, NOW))
        self.assertTrue(starts_over([NOW - 1] * 11, 30, NOW))                           # a minute: 10
        self.assertFalse(starts_over([NOW - 600 - i for i in range(30)], 30, NOW))
        self.assertTrue(starts_over([NOW - 600 - i for i in range(30)], 30, NOW, adding=1))
        self.assertTrue(starts_over([NOW - 7200 - 60 * i for i in range(181)], 59, NOW))  # a day: 180
        self.assertFalse(starts_over([NOW - 86400] * 500, 30, NOW))                     # older than a day

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

    def test_router_spend_at_its_ceiling_pauses_new_attempts_and_keeps_steps_in_flight(self):
        """The router refuses every paid request past its ceiling itself (a clean router:credit wait), so
        reaching it spends nothing more. A hard stop there gave steps in flight 10 minutes, then deleted
        their workers: hours-long Claude and Codex steps that cost no router money were lost as waste.
        Near the ceiling the guard now pauses new attempts until it is raised (router restart)."""
        self.f.money = {"spent": 1, "bound": 2, "held": 0}
        guard = self.f.guard(router=lambda: (49.2, 49.95))   # short of it, as the router never quite reaches it
        self.f.clock += 60
        out = guard.run()
        self.assertEqual((out["phase"], out["hard_stop"], out["failed_checks"]), ("degraded", None, ["router_spend"]))
        self.assertEqual(out["router_spent_usd"], 49.2)
        self.assertEqual(self.f.deleted, [])
        paused = [m for m in self.f.sent if "at its ceiling; new attempts paused" in m]
        self.assertEqual(len(paused), 1)                                  # at once, not after 15 minutes
        for _ in range(20):                                               # and only once, no generic alert
            self.f.clock += 60
            self.f.guard(router=lambda: (49.2, 49.95)).run()
        self.assertEqual([m for m in self.f.sent if "at its ceiling" in m], paused)
        self.assertFalse(any("keeps failing" in m for m in self.f.sent))
        self.f.clock += 60
        out = self.f.guard(router=lambda: (49.2, 80.0)).run()                # raised: resumes
        self.assertEqual((out["failed_checks"], out["hard_stop"]), ([], None))
        self.assertFalse(degraded(self.f.state_dir))

    def test_real_router_spend_past_its_ceiling_stops_when_the_ledger_reads_low(self):
        """Live on 6 November the ledger booked $0.91 for an attempt the router charged $4.91. Spend the
        router let past its own ceiling is a breach: still a hard stop."""
        self.f.money = {"spent": 1, "bound": 2, "held": 0}
        guard = self.f.guard(router=lambda: (50.2, 49.95))
        self.f.clock += 60
        out = guard.run()
        self.assertEqual((out["phase"], out["hard_stop"]), ("stopped", "money_ceiling"))

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

    def test_router_ceiling_and_low_credit_alert_early_with_time_left(self):
        """Nov 6-11: 39 attempts were cut off at the ceiling or an empty balance, found only mid-call."""
        self.f.money = {"spent": 1, "bound": 2, "held": 0}
        spend = [30.0]
        for _ in range(10):                                   # $1 a minute for ten minutes, under 80%
            self.f.clock += 60
            out = self.f.guard(router=lambda: (spend[0], 50.0, 200.0)).run()
            spend[0] += 1.0
        self.assertEqual(self.f.sent, [])
        self.assertAlmostEqual(out["router_burn_usd_per_hour"], 60.0, delta=1)
        self.f.clock += 60
        out = self.f.guard(router=lambda: (40.0, 50.0, 24.0)).run()   # 80% of the ceiling; credit under $25
        self.assertEqual(out["phase"], "healthy")             # an alert, not a stop
        ceiling = next(m for m in self.f.sent if "ceiling" in m)
        self.assertIn("$40.00 of its $50.00 ceiling (80%)", ceiling)
        self.assertRegex(ceiling, r"after \$9\.00 more, about 0\.2 hours at the last hour's \$(59|60)\.\d\d/hour")
        credit = next(m for m in self.f.sent if "credit" in m)
        self.assertIn("$24.00, below $25.00; about 0.4 hours", credit)
        self.f.clock += 60
        self.f.guard(router=lambda: (40.5, 50.0, 23.0)).run()
        self.assertEqual(len(self.f.sent), 2)                 # each alert once while it lasts
        from durable.board import render_board
        board = {"at": NOW, "controller": {}, "guard": health(self.f.state_dir), "cases": [], "sealed": 0, "live": 0,
                 "unavailable": [], "spend_usd_micros": {"spent": 0, "held": 0, "waste": 0}}
        line = next(l for l in render_board(board).splitlines() if l.startswith("Router paid"))
        self.assertIn("$40.50 of $50.00 ceiling (81%); provider credit $23.00; burning $", line)
        self.assertIn("guard pause in ~", line)

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


class StopAuditAlertTests(unittest.TestCase):
    """The guard reads bin/stop_audit's result file only; whatever is there, it alerts and never raises."""

    def alerts(self, content=None, now=NOW, make=None):
        from durable.guard import STOP_AUDIT_FILE, stop_audit_alerts
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / STOP_AUDIT_FILE
            if content is not None:
                path.write_text(content if isinstance(content, str) else json.dumps(content))
            if make is not None:
                make(path)
            return stop_audit_alerts(path, now)

    @staticmethod
    def result(**fields):
        return {"written_at": NOW - 600, "counts": {"attempts": 10, "undecodable": 0}, "regression": [],
                "unknown": [], "regression_reasons": [], "unknown_reasons": [], **fields}

    def test_a_fresh_clean_result_raises_nothing(self):
        self.assertEqual(self.alerts(self.result()), {})

    def test_regressions_and_unknown_reasons_alert_once_keyed_by_reason(self):
        out = self.alerts(self.result(written_at=NOW - 60, regression_reasons=["infra:example_fixed"],
                                      unknown_reasons=["infra:raw_key_error", "not a reason /etc/passwd"]))
        self.assertEqual(out, {"stop_audit:infra:example_fixed,infra:raw_key_error":
                               "Stop audit: fixed bugs came back: infra:example_fixed; "
                               "unclassified stops: infra:raw_key_error. Run bin/stop_audit."})

    def test_broken_invariants_alert_like_regressions(self):
        out = self.alerts(self.result(invariant=["INVARIANT  batch_over_bound  b-1: held 0 + spent 2 > bound 1"],
                                      invariant_reasons=["batch_over_bound", "waste_on_case_money", "Not A Check!"]))
        self.assertEqual(out, {"stop_audit:invariant:batch_over_bound,waste_on_case_money":
                               "Stop audit: invariants broken: batch_over_bound, waste_on_case_money. "
                               "Run bin/stop_audit."})
        self.assertEqual(list(self.alerts(self.result(invariant_reasons="batch_over_bound"))),
                         ["stop_audit:unreadable"])

    def test_mostly_undecodable_outputs_alert(self):
        self.assertEqual(self.alerts(self.result(counts={"attempts": 5, "undecodable": 5})), {})
        out = self.alerts(self.result(counts={"attempts": 4, "undecodable": 6}))
        self.assertEqual(list(out), ["stop_audit:undecodable"])
        self.assertIn("can't read step results: 6 of 10", out["stop_audit:undecodable"])

    def test_missing_stale_or_corrupt_results_alert_instead_of_raising(self):
        import os
        self.assertEqual(list(self.alerts()), ["stop_audit:missing"])
        stale = self.alerts(self.result(written_at=NOW - 3600))
        self.assertEqual(list(stale), ["stop_audit:stale"])
        self.assertIn("60 minutes old", stale["stop_audit:stale"])
        unreadable = ["{not json", "[]", "null", json.dumps({}), json.dumps(self.result(written_at="yesterday")),
                      "{" + '"written_at": 1e999' + "}", json.dumps(self.result(written_at=float("inf"))),
                      json.dumps(self.result(written_at=float("nan"))),
                      json.dumps(self.result(regression_reasons=7)), json.dumps(self.result(unknown_reasons="x")),
                      json.dumps(self.result(regression={})), json.dumps(self.result(counts={"attempts": 1})),
                      json.dumps(self.result(counts={"attempts": -1, "undecodable": 0})),
                      json.dumps(self.result(regression_reasons=["infra:x"] * 20000))]   # over 64 KiB
        for corrupt in unreadable:
            self.assertEqual(list(self.alerts(corrupt, now=NOW)), ["stop_audit:unreadable"], corrupt[:60])
        self.assertEqual(list(self.alerts(self.result(), now=float("inf"))), ["stop_audit:unreadable"])
        # A finite but absurd time cannot overflow or switch the stale alert off.
        self.assertEqual(list(self.alerts(self.result(written_at=-1e308))), ["stop_audit:stale"])

        def link(path):   # a symlink to a good result is refused, never followed
            (path.parent / "real.json").write_text(json.dumps(self.result()))
            path.symlink_to(path.parent / "real.json")
        self.assertEqual(list(self.alerts(make=link)), ["stop_audit:unreadable"])
        self.assertEqual(list(self.alerts(make=lambda path: os.mkfifo(path))), ["stop_audit:unreadable"])
        self.assertEqual(list(self.alerts(make=lambda path: path.mkdir())), ["stop_audit:unreadable"])


if __name__ == "__main__":
    unittest.main()
