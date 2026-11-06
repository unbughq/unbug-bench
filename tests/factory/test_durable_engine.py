"""WP1 engine on real DBOS 3.4.0 (SQLite), against the fakes in test_durable_engine_fakes.py.

docs/designs/durable-execution-wp1.md, "Tests". Each test runs the engine program in a child
process on a fresh database, then reads the fake worker's log, the ledger and the cards.
"""
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(Path(__file__).resolve().parent)]
os.environ.setdefault("BENCH", str(ROOT))

from test_durable_engine_fakes import ALL_GATES, EngineRun  # noqa: E402

C1, C2, C3 = "case-t-1", "case-t-2", "case-t-3"
M = 1_000_000


def run(scenario, timeout=120):
    r = EngineRun(scenario)
    try:
        return r, r.run(timeout=timeout)
    except Exception:
        r.close()
        raise


def card(out, case_id):
    return next(c for c in out["cards"] if c["case_id"] == case_id)


def start(r, key):
    return next(x for x in r.worker_log() if x["op"] == "start" and x["key"] == key)


def steps(r, case):
    return [k[1] for k in r.keys(case)]


class StepSequence(unittest.TestCase):
    def test_admission_wait_restores_checkpoint_on_replacement_worker(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                r, out = run({'legacy_admit_snapshot': legacy,
                    'spec': {'max_cases_started': 1},
                    'script': {'1/admit/1': {'outcome': 'provider_limit', 'reason': 'router:quota',
                        'retry_in': .01, 'paid': 0, 'checkpoint': True}}})
                self.addCleanup(r.close)
                first = start(r, C1 + '/1/admit/1')
                retry = start(r, C1 + '/1/admit/2')
                self.assertNotEqual(first['worker'], retry['worker'])
                self.assertEqual(retry['opened'].get('snapshot'), None if legacy else 'snapshot ' + C1 + '/1/admit/1')
                self.assertEqual(out['result']['cases'], {C1: 'sealed'})

    def test_queued_admission_expires_without_dispatch_or_retaining_money(self):
        r, out = run({"deadline_in": 3.0,
                      "spec": {"target_sealed": 2, "max_cases_started": 2},
                      "script": {"1/admit/1": {"dur": 4.0}, "2/admit/1": {"dur": 4.0}}})
        self.addCleanup(r.close)
        self.assertCountEqual(out["result"]["cases"].values(), ["sealed", "stopped_admission"])
        expired = next(c for c, status in out["result"]["cases"].items() if status == "stopped_admission")
        self.assertFalse(any(x["key"].startswith(expired + "/") for x in r.starts()))
        self.assertFalse(any(x.get("case") == expired for x in r.pool_log()))
        self.assertEqual(out["ledger"]["batches"]["b-t"]["held"], 0)
        self.assertEqual(card(out, expired)["reason"], "infra:deadline")

    def test_unfunded_admission_expires_while_waiting_for_the_bound(self):
        r, out = run({"deadline_in": 3.0,
                      "spec": {"money_bound_usd_micros": 500_000, "max_cases_started": 1}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "stopped_admission"})
        self.assertFalse(r.starts())
        self.assertEqual(out["ledger"]["batches"]["b-t"]["held"], 0)

    def test_admitted_case_keeps_its_provider_retry_after_the_cutoff(self):
        r, out = run({"deadline_in": 3.0, "spec": {"max_cases_started": 1},
                      "script": {"1/admit/1": {"outcome": "provider_limit", "reason": "router:claude_limit",
                                               "retry_in": 4.0, "paid": 0}}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        self.assertEqual(steps(r, 1)[:2], ["admit", "admit"])

    def test_straight_to_seal(self):
        r, out = run({})
        self.addCleanup(r.close)
        self.assertEqual(r.keys(1), [("1", "admit", "1"), ("2", "writer:1", "1"), ("3", "stress:1", "1"),
                                     ("4", "gates:1", "1"), ("5", "seal", "1")])
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        self.assertEqual([s["case_id"] for s in out["result"]["sealed"]], [C1])
        self.assertTrue(any(x["op"] == "release" and x["case"] == C1 for x in r.pool_log()))
        # Only ADMIT receives the batch key. Later steps use their restored case snapshot.
        for x in r.starts(1):
            self.assertIsNotNone(x["opened"], x["key"])
            if x["key"].split("/")[2] == "admit":
                self.assertEqual(x["opened"]["inputs"], "inputs: app pin and promise")
            else:
                self.assertNotIn("inputs", x["opened"])
        self.assertEqual(start(r, f"{C1}/2/writer:1/1")["opened"]["snapshot"], f"snapshot {C1}/1/admit/1")
        # The grant is the ceiling: what the case's own money has left (each attempt pays 1000).
        self.assertEqual([x["ceiling"] for x in r.starts(1)], [50 * M - 1000 * i for i in range(5)])
        # GATES gets its own deadline.
        self.assertEqual(start(r, f"{C1}/4/gates:1/1")["deadline_s"], 43_200.0)
        self.assertEqual(start(r, f"{C1}/2/writer:1/1")["deadline_s"], 14_400.0)
        ops = [(x["op"], x["key"]) for x in r.ledger_log() if x["op"] in ("reserve", "settle")]
        self.assertEqual(len(ops), 10)
        led = out["ledger"]
        self.assertEqual(led["cases"][C1], {"spent": 5000, "held": 0})
        self.assertEqual(led["batches"]["b-t"]["held"], 0)
        # The scorecard comes from `passed`.
        sc = out["scorecard"]
        self.assertEqual(sc["sealed"], 1)
        self.assertEqual(set(sc["cases"][0]["gates"]), set(ALL_GATES))
        self.assertIs(sc["cases"][0]["hard"], False)

    def test_repair_from_stress_findings_and_a_repairable_gate(self):
        r, out = run({"script": {
            "1/stress:1/1": {"feedback": True},
            "1/gates:2/1": {"outcome": "gate_failed", "gate": "G5", "repairable": True, "passed": ["G1", "G2"]}}})
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1), ["admit", "writer:1", "stress:1", "writer:2", "stress:2", "gates:2",
                                       "writer:3", "stress:3", "gates:3", "seal"])
        self.assertEqual(start(r, f"{C1}/4/writer:2/1")["opened"]["feedback"], f"findings {C1}/3/stress:1/1")
        self.assertEqual(start(r, f"{C1}/7/writer:3/1")["opened"]["feedback"], f"repair {C1}/6/gates:2/1")
        # The writer round after the failed GATES restores that GATES snapshot.
        self.assertEqual(start(r, f"{C1}/7/writer:3/1")["opened"]["snapshot"], f"snapshot {C1}/6/gates:2/1")
        self.assertEqual(card(out, C1)["writer_rounds"], 3)

    def test_scorecard_shows_the_failed_gate_and_only_allowlisted_reasons(self):
        r, out = run({"script": {"1/gates:1/1": {"outcome": "gate_failed", "gate": "G5", "reason": "g5:reference_unsolved",
                                                 "passed": ["G1", "G2", "G3", "G4"]}},
                      "spec": {"max_cases_started": 1}, "allowlist": ["g5:reference_unsolved"]})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "retired"})
        row = out["scorecard"]["cases"][0]
        self.assertEqual(row["gates"], {"G1": "pass", "G2": "pass", "G3": "pass", "G4": "pass", "G5": "fail"})
        self.assertEqual(row["reason"], "g5:reference_unsolved")
        self.assertEqual(row["stage"], "gates:1")


class Outcomes(unittest.TestCase):
    def test_seal_is_counted_if_worker_cleanup_fails_after_the_verified_result(self):
        r, out = run({"release_step_failure": True, "spec": {"max_cases_started": 1}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        self.assertEqual([seal["case_id"] for seal in out["result"]["sealed"]], [C1])
        self.assertEqual(out["scorecard"]["sealed"], 1)
        self.assertEqual(out["scorecard"]["cases"][0]["status"], "sealed")
        self.assertIs(out["scorecard"]["cases"][0]["cleanup_error"], True)
        self.assertFalse(any(x["op"] == "release" for x in r.pool_log()))

    def test_failure_after_successful_release_does_not_claim_cleanup_failed(self):
        r, out = run({"post_release_failure": True, "spec": {"max_cases_started": 1}})
        self.addCleanup(r.close)
        self.assertTrue(any(x["op"] == "release" and x["case"] == C1 for x in r.pool_log()))
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        self.assertEqual(out["scorecard"]["sealed"], 1)
        self.assertIs(out["scorecard"]["cases"][0]["cleanup_error"], False)

    def test_executor_exception_after_dispatch_reconciles_before_retry(self):
        key = f"{C1}/2/writer:1/1"
        r, out = run({"raise_after_start": key, "spec": {"max_cases_started": 1},
                      "script": {"1/writer:1/1": {"dur": 2.0}}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        log = r.worker_log()
        self.assertTrue(any(x["op"] == "cancelled" and x["key"] == key for x in log))
        self.assertEqual([x["op"] for x in r.ledger_log() if x.get("key") == key], ["reserve", "settle_lost"])
        self.assertEqual(steps(r, 1)[:3], ["admit", "writer:1", "writer:1"])
        self.assertFalse([x for x in log if x["op"] == "start" and x["mode"] != "run"])

    def test_transient_output_verification_does_not_repeat_completed_admit(self):
        r, out = run({"verification_failures": 2, "spec": {"max_cases_started": 1}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        self.assertEqual(steps(r, 1), ["admit", "writer:1", "stress:1", "gates:1", "seal"])
        self.assertEqual(len([x for x in r.starts() if x["key"] == f"{C1}/1/admit/1"]), 1)
        self.assertEqual(start(r, f"{C1}/2/writer:1/1")["opened"]["snapshot"], f"snapshot {C1}/1/admit/1")

    def test_pool_failure_releases_the_grant_and_retries(self):
        r, out = run({"pool_failures": 1, "spec": {"max_cases_started": 1}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        key = f"{C1}/1/admit/1"
        self.assertFalse(any(x["key"] == key for x in r.starts()))
        self.assertEqual([x["op"] for x in r.ledger_log() if x.get("key") == key], ["reserve", "settle"])
        self.assertEqual(out["ledger"]["batches"]["b-t"]["held"], 0)

    def test_worker_create_outage_waits_without_spending_the_infra_allowance(self):
        # Four failed creates with an allowance of one: ADMIT still completes, a wait apart.
        r, out = run({"pool_failures": 4, "pool_reason": "infra:worker_create_failed",
                      "spec": {"max_cases_started": 1, "max_infra_retries_per_step": 1},
                      "timing": {"pause_retry_s": 0.3}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        reserves = [x["t"] for x in r.ledger_log() if x["op"] == "reserve" and "/admit/" in x["key"]]
        self.assertEqual(len(reserves), 5)
        self.assertTrue(all(b - a >= 0.3 for a, b in zip(reserves, reserves[1:])), reserves)

    def test_credential_delivery_recovers_without_spending_the_infra_allowance(self):
        r, out = run({"pool_failures": 4, "pool_reason": "infra:credentials_unavailable",
                      "spec": {"max_cases_started": 1, "max_infra_retries_per_step": 1},
                      "timing": {"credential_retry_s": 0.2}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        self.assertEqual(len([x for x in r.ledger_log() if x["op"] == "reserve" and "/admit/" in x["key"]]), 5)

    def test_boat_inventory_outage_waits_like_a_create_failure(self):
        r, out = run({"pool_failures": 4, "pool_reason": "infra:inventory_unavailable",
                      "spec": {"max_cases_started": 1, "max_infra_retries_per_step": 1},
                      "timing": {"pause_retry_s": 0.2}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})

    def test_unconfirmed_delete_during_an_outage_waits_without_spending_the_allowance(self):
        r, out = run({"pool_failures": 4, "pool_reason": "infra:worker_delete_unconfirmed",
                      "spec": {"max_cases_started": 1, "max_infra_retries_per_step": 1},
                      "timing": {"pause_retry_s": 0.2}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})

    def test_a_lasting_create_outage_ends_at_the_wait_ceiling_then_the_infra_allowance(self):
        r, out = run({"pool_failures": 1000, "pool_reason": "infra:worker_create_failed",
                      "spec": {"max_cases_started": 1, "max_infra_retries_per_step": 1, "max_factory_bug_resumes": 0},
                      "timing": {"pause_retry_s": 0.2, "pool_wait_ceiling_s": 5.0}}, timeout=60)
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "held"})
        reserves = [x["t"] for x in r.ledger_log() if x["op"] == "reserve" and "/admit/" in x["key"]]
        self.assertGreaterEqual(len(reserves), 4)   # waited attempts, then the allowance's two
        self.assertLess(reserves[-1] - reserves[0], 30)

    def test_a_create_outage_does_not_outlive_the_batch_deadline_in_admit(self):
        r, out = run({"pool_failures": 1000, "pool_reason": "infra:worker_create_failed", "deadline_in": 2.0,
                      "spec": {"max_cases_started": 1, "max_infra_retries_per_step": 1000}, "timing": {"pause_retry_s": 0.3}}, timeout=60)
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "stopped_admission"})

    def test_admit_and_other_steps_share_the_concurrency_limit(self):
        r, out = run({"spec": {"target_sealed": 2, "max_concurrency": 1},
                      "script": {"1/admit/1": {"outcome": "provider_limit", "reason": "router:claude_limit",
                                               "retry_in": 1.5, "paid": 0},
                                 "2/writer:1/1": {"dur": 3.0}}})
        self.addCleanup(r.close)
        self.assertEqual(set(out["result"]["cases"].values()), {"sealed"})
        ran = {x["key"]: x["done_at"] for x in r.worker_log() if x["op"] == "ran"}
        spans = sorted((x["t"], ran[x["key"]], x["key"]) for x in r.starts())
        for previous, current in zip(spans, spans[1:]):
            self.assertGreaterEqual(current[0], previous[1], (previous, current))

    def test_batch_only_zero_spend_money_stop_increases_the_next_grant(self):
        # A single call can exceed the finite request before any money is spent.
        r, out = run({"spec": {"max_cases_started": 1, "money_bound_usd_micros": 500 * M},
                      "script": {"1/writer:1/1": {"outcome": "exhausted", "reason": "writer:rounds"},
                                 "1/diagnosis/1": {"outcome": "exhausted", "reason": "diagnosis:money", "paid": 0},
                                 "1/diagnosis/2": {"verdict": "not_converging"}}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "retired"})
        grants = [x["amount"] for x in r.ledger_log() if x["op"] == "reserve" and "/diagnosis/" in x["key"]]
        self.assertEqual(grants, [50 * M, 100 * M])

    def test_batch_only_paid_money_stops_increase_the_next_grant(self):
        r, out = run({"spec": {"max_cases_started": 1, "money_bound_usd_micros": 500 * M},
                      "script": {"1/writer:1/1": {"outcome": "exhausted", "reason": "writer:rounds"},
                                 "1/diagnosis/1": {"outcome": "exhausted", "reason": "diagnosis:money", "paid": M},
                                 "1/diagnosis/2": {"outcome": "exhausted", "reason": "diagnosis:money", "paid": 2 * M},
                                 "1/diagnosis/3": {"verdict": "not_converging"}}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "retired"})
        grants = [x["amount"] for x in r.ledger_log() if x["op"] == "reserve" and "/diagnosis/" in x["key"]]
        self.assertEqual(grants, [50 * M, 100 * M, 200 * M])
        self.assertGreaterEqual(out["ledger"]["batches"]["b-t"]["spent"], 3 * M)

    def test_infra_retries_then_diagnosis_with_the_engine_history(self):
        r, out = run({"spec": {"max_infra_retries_per_step": 2, "max_cases_started": 2},
                      "script": {"1/writer:1/*": {"outcome": "infra_error", "reason": "infra:stalled", "paid": 7000,
                                                  "diagnostic": True},
                                 "1/diagnosis/1": {"verdict": "not_converging"}}})
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1), ["admit", "writer:1", "writer:1", "writer:1", "diagnosis"])
        self.assertEqual(out["result"]["cases"], {C1: "retired", C2: "sealed"})
        self.assertEqual(card(out, C2)["replacement_of"], C1)
        # Broken runs are waste: the case's own money is untouched by the three infra attempts.
        led = out["ledger"]
        self.assertEqual(led["cases"][C1]["spent"], 1000)              # the ADMIT only
        self.assertEqual(led["batches"]["b-t"]["waste"], 21000)
        # The diagnosis evidence: the three attempts' diagnostics, then the engine's own history.
        diag = start(r, f"{C1}/3/diagnosis/1")
        self.assertEqual(diag["evidence"], ["diagnostic"] * 4)
        history = json.loads(diag["opened"]["evidence3"])
        self.assertEqual([(h["step"], h["outcome"]) for h in history],
                         [("admit", "ok")] + [("writer:1", "infra_error")] * 3)
        self.assertNotIn("stalled", json.dumps(history).replace("infra:stalled", ""))
        # Diagnosis is batch-only: it asked for the finite batch-only figure and drew no case money.
        res = next(x for x in r.ledger_log() if x["op"] == "reserve" and x["key"] == f"{C1}/3/diagnosis/1")
        self.assertEqual((res["amount"], res["draws"]), (50 * M, False))

    def test_provider_sleep_releases_the_admit_queue(self):
        # Case 1's ADMIT hits a limit; case 2 admits while case 1 sleeps, and case 1's next ADMIT
        # reads the registry case 2 wrote.
        r, out = run({"spec": {"target_sealed": 2},
                      "script": {"1/admit/1": {"outcome": "provider_limit", "reason": "router:claude_limit",
                                               "retry_in": 2.0, "paid": 0}}})
        self.addCleanup(r.close)
        a1, a2 = start(r, f"{C1}/1/admit/1"), start(r, f"{C1}/1/admit/2")
        b = start(r, f"{C2}/1/admit/1")
        # Case 2 never waited out case 1's sleep, which happened outside the queue.
        self.assertLess(b["t"], a2["t"])
        self.assertLess(b["t"], a1["t"] + 1.0)
        self.assertGreaterEqual(a2["t"] - a1["t"], 1.9)
        # Each ADMIT read the newest registry when it was dequeued.
        if b["t"] < a1["t"]:
            self.assertEqual(b["opened"]["registry"], "registry: empty")
        else:
            self.assertEqual(b["opened"]["registry"], a1["opened"]["registry"])
        self.assertTrue(a2["opened"]["registry"].startswith("registry ") and a2["opened"]["registry"].endswith(C2))
        self.assertEqual(out["result"]["cases"], {C1: "sealed", C2: "sealed"})
        # A free limit is not waste and spends no allowance.
        self.assertEqual([x["op"] for x in r.ledger_log() if x.get("key") == f"{C1}/1/admit/1"], ["reserve", "settle"])

    def test_operator_pauses_retry_without_diagnosis(self):
        # Four pauses on one step, with an infra allowance of one: still no diagnosis.
        paused = {"outcome": "infra_error", "reason": "infra:paused", "paid": 2000}
        r, out = run({"spec": {"max_infra_retries_per_step": 1},
                      "timing": {"pause_retry_s": 0.3},
                      "script": {f"1/writer:1/{n}": paused for n in range(1, 5)}})
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1), ["admit"] + ["writer:1"] * 5 + ["stress:1", "gates:1", "seal"])
        w = [start(r, f"{C1}/2/writer:1/{n}")["t"] for n in range(1, 6)]
        self.assertTrue(all(b - a >= 0.3 for a, b in zip(w, w[1:])), w)   # the pause wait
        self.assertEqual(out["ledger"]["batches"]["b-t"]["waste"], 8000)   # waste, not case money
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})

    def test_batch_deadline_stops_after_the_deadline_never_diagnose(self):
        # The deadline passes while case 1 writes; four batch-deadline stops follow, with an infra
        # allowance of one. The running case still seals: the deadline only stops new work.
        stop = {"outcome": "infra_error", "reason": "infra:deadline", "paid": 0}
        r, out = run({"deadline_in": 4.0, "spec": {"max_infra_retries_per_step": 1},
                      "timing": {"pause_retry_s": 0.2},
                      "script": {"1/2/writer:1/1": {"dur": 5.0}, **{f"1/3/stress:1/{n}": stop for n in range(1, 5)}}})
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1), ["admit", "writer:1"] + ["stress:1"] * 5 + ["gates:1", "seal"])
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})

    def test_genuine_free_limits_continue_past_96_then_succeed(self):
        limit = {"outcome": "provider_limit", "reason": "router:claude_limit", "retry_in": 0.01,
                 "paid": 0, "dur": 0.01}
        r, out = run({"spec": {"max_cases_started": 1},
                      "script": {f"1/writer:1/{n}": limit for n in range(1, 98)}},
                     timeout=600)
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1), ["admit"] + ["writer:1"] * 98 + ["stress:1", "gates:1", "seal"])
        writers = [x for x in r.starts(1) if "/2/writer:1/" in x["key"]]
        workers = [x["worker"] for x in writers]
        releases = {x["worker"] for x in r.pool_log() if x["op"] == "release" and x["case"] == C1}
        self.assertEqual(len(set(workers)), 98)
        self.assertTrue(set(workers[:-1]) <= releases)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})

    def test_paid_provider_waits_book_waste_and_keep_running(self):
        limit = {"outcome": "provider_limit", "reason": "router:claude_limit", "retry_in": 0.05}
        r, out = run({"spec": {"max_cases_started": 1}, "script": {
            "1/writer:1/1": {**limit, "paid": 2000}, "1/writer:1/2": {**limit, "paid": 3000}}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        self.assertEqual(out["ledger"]["batches"]["b-t"]["waste"], 5000)
        self.assertEqual(out["ledger"]["cases"][C1]["spent"], 5000)

    def test_credential_wait_is_visible_releases_worker_and_resumes(self):
        credential = {"outcome": "infra_error", "reason": "router:credential_expiring", "paid": 0}
        r = EngineRun({"spec": {"max_cases_started": 1}, "timing": {"credential_retry_s": 12.0}, "trace_credential_sleep": True,
                       "script": {"1/writer:1/1": credential, "1/writer:1/2": {"dur": 0.6}},
                       "actions": [{"when": {"case": 1, "status": "waiting_for_credentials"}},
                                   {"when": {"case": 1, "status": "running", "started": f"{C1}/2/writer:1/2"}}]})
        self.addCleanup(r.close)
        process = r.spawn()
        deadline = time.monotonic() + 30
        actions_path = r.work / "state/worker/actions.log"
        sleep_row = None
        while time.monotonic() < deadline:
            if (actions_path.exists() and '"i": 0' in actions_path.read_text()
                    and any(x["op"] == "release" and x["case"] == C1 for x in r.pool_log())):
                with sqlite3.connect(r.work / "sys.sqlite") as db:
                    sleep_row = db.execute(
                        "SELECT function_id, output, completed_at_epoch_ms FROM operation_outputs "
                        "WHERE workflow_uuid = ? AND function_name = 'DBOS.sleep' ORDER BY function_id DESC LIMIT 1",
                        (C1,)).fetchone()
                if sleep_row and sleep_row[2] > (time.time() + 1.0) * 1000:
                    break
            if process.poll() is not None:
                self.fail("engine exited before credential wait: " + r.tail())
            time.sleep(0.05)
        else:
            process.kill()
            process.wait()
            self.fail("credential wait was not observed: " + r.tail())
        process.send_signal(signal.SIGKILL)
        process.wait()
        time.sleep(5.0)
        self.assertGreater(sleep_row[2] / 1000, time.time() + 0.25)
        out = r.run()
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        with sqlite3.connect(r.work / "sys.sqlite") as db:
            replayed_sleep = db.execute(
                "SELECT function_id, output, completed_at_epoch_ms FROM operation_outputs "
                "WHERE workflow_uuid = ? AND function_id = ? AND function_name = 'DBOS.sleep'",
                (C1, sleep_row[0])).fetchone()
        self.assertEqual(replayed_sleep, sleep_row)
        sleep_entries = [json.loads(line) for line in
                         (r.work / "state/worker/credential-sleep.log").read_text().splitlines()]
        self.assertEqual(len(sleep_entries), 2)
        self.assertLess(sleep_entries[1]["t"], sleep_row[2] / 1000)
        retry_started = start(r, f"{C1}/2/writer:1/2")["t"]
        self.assertGreaterEqual(retry_started, sleep_row[2] / 1000 - 0.05)
        self.assertLess(retry_started, sleep_row[2] / 1000 + 3.0)
        actions = [json.loads(line)["i"] for line in actions_path.read_text().splitlines()]
        self.assertEqual(set(actions), {0, 1})
        self.assertTrue(any(x["op"] == "release" and x["case"] == C1 for x in r.pool_log()))
        self.assertEqual(len([x for x in r.starts() if x["key"] == f"{C1}/2/writer:1/1"]), 1)
        self.assertNotEqual(start(r, f"{C1}/2/writer:1/1")["worker"], start(r, f"{C1}/2/writer:1/2")["worker"])

    def test_credential_problem_retries_without_using_infra_allowance(self):
        reason = "router:credential_expiring"
        first, second = f"{C1}/2/writer:1/1", f"{C1}/2/writer:1/2"
        r, out = run({"spec": {"max_cases_started": 1, "max_infra_retries_per_step": 1},
                      "timing": {"credential_retry_s": 1.0},
                      "script": {"1/writer:1/1": {"outcome": "infra_error", "reason": reason},
                                 "1/writer:1/2": {"outcome": "infra_error", "reason": reason, "dur": 0.8},
                                 "1/writer:1/3": {"outcome": "infra_error", "reason": "infra:stalled"}},
                      "actions": [{"when": {"case": 1, "status": "waiting_for_credentials", "ran": first}},
                                  {"when": {"case": 1, "status": "running", "started": second}},
                                  {"when": {"case": 1, "status": "waiting_for_credentials", "ran": second}}]})
        self.addCleanup(r.close)
        actions = {row["i"]: row for row in
                   (json.loads(line) for line in (r.work / "state/worker/actions.log").read_text().splitlines())}
        self.assertEqual(set(actions), {0, 1, 2})
        for index, next_attempt in ((0, 2), (2, 3)):
            self.assertEqual((actions[index]["status"], actions[index]["reason"]),
                             ("waiting_for_credentials", reason))
            self.assertLess(actions[index]["t"], start(r, f"{C1}/2/writer:1/{next_attempt}")["t"])
        self.assertEqual((actions[1]["status"], actions[1]["reason"]), ("running", None))
        ran = {x["key"]: x["t"] for x in r.worker_log() if x["op"] == "ran"}
        self.assertLess(ran[first], actions[0]["t"])
        self.assertLess(start(r, second)["t"], actions[1]["t"])
        self.assertLess(actions[1]["t"], ran[second])
        self.assertLess(ran[second], actions[2]["t"])
        workers = [start(r, f"{C1}/2/writer:1/{n}")["worker"] for n in range(1, 4)]
        releases = {x["worker"] for x in r.pool_log() if x["op"] == "release" and x["case"] == C1}
        self.assertEqual(len(set(workers)), 3)
        self.assertTrue(set(workers[:2]) <= releases)
        self.assertEqual(steps(r, 1), ["admit"] + ["writer:1"] * 4 + ["stress:1", "gates:1", "seal"])
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})

    def test_long_sleep_releases_the_worker(self):
        r, out = run({"spec": {"release_worker_after_sleep_s": 0.5},
                      "script": {"1/stress:1/1": {"outcome": "provider_limit", "reason": "router:claude_limit",
                                                  "retry_in": 3.0, "paid": 0}}})
        self.addCleanup(r.close)
        self.assertIn({"op": "release", "case": C1, "worker": "w-1-1"},
                      [{k: v for k, v in x.items() if k != "t"} for x in r.pool_log()])
        self.assertEqual(start(r, f"{C1}/3/stress:1/2")["worker"], "w-1-2")
        self.assertEqual(start(r, f"{C1}/3/stress:1/2")["opened"]["snapshot"], f"snapshot {C1}/2/writer:1/1")
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})

    def test_stop_admission(self):
        r, out = run({"spec": {"target_sealed": 2},
                      "script": {"1/admit/1": {"outcome": "exhausted", "reason": "admit:no_fresh_bug"},
                                 "2/gates:1/1": {"outcome": "gate_failed", "gate": "G2", "reason": "g2:public_fix"}}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "stopped_admission", C2: "retired"})   # no replacement

    def test_one_replacement_per_case_bounded_by_cases_started(self):
        fail = {"outcome": "gate_failed", "gate": "G2", "reason": "g2:public_fix"}
        r, out = run({"spec": {"max_cases_started": 2}, "script": {"1/gates:1/1": fail, "2/gates:1/1": fail}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "retired", C2: "retired"})
        self.assertEqual(card(out, C2)["replacement_of"], C1)

    def test_factory_bug_holds(self):
        r, out = run({"spec": {"max_cases_started": 1},
                      "script": {"1/writer:1/1": {"outcome": "exhausted", "reason": "writer:rounds"},
                                 "1/diagnosis/1": {"verdict": "factory_bug"}}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "held"})
        self.assertEqual(card(out, C1)["verdict"], "factory_bug")

    def test_worker_lost_restores_the_snapshot_on_a_new_worker(self):
        r, out = run({"dead_on_start": [f"{C1}/3/stress:1/1"]})
        self.addCleanup(r.close)
        self.assertEqual(start(r, f"{C1}/3/stress:1/2")["worker"], "w-1-2")
        self.assertEqual(start(r, f"{C1}/3/stress:1/2")["opened"]["snapshot"], f"snapshot {C1}/2/writer:1/1")
        lost = [x for x in r.ledger_log() if x.get("key") == f"{C1}/3/stress:1/1"]
        self.assertEqual([x["op"] for x in lost], ["reserve", "settle_lost"])
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})


class Extensions(unittest.TestCase):
    def test_extensions_with_progress_never_repair_and_draw_batch_money(self):
        rep = {"outcome": "gate_failed", "gate": "G5", "repairable": True}
        r, out = run({"spec": {"max_writer_rounds": 1, "max_cases_started": 1},
                      "script": {"1/gates:1/1": {**rep, "passed": ["G1"]},
                                 "1/diagnosis/*": {"verdict": "close_to_passing"},
                                 "1/gates:2/1": {**rep, "passed": ["G1", "G2"]}}})
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1), ["admit", "writer:1", "stress:1", "gates:1", "diagnosis",
                                       "writer:2", "stress:2", "gates:2", "diagnosis",   # extension 1: no repair
                                       "writer:3", "stress:3", "gates:3", "seal"])      # extension 2, after progress
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        c = card(out, C1)
        self.assertEqual((c["writer_rounds"], c["extensions"], c["diagnoses"]), (1, 2, 2))
        self.assertTrue(start(r, f"{C1}/6/writer:2/1")["opened"]["feedback"].startswith("guidance "))
        draws = {x["key"].split("/", 1)[1]: x["draws"] for x in r.ledger_log() if x["op"] == "reserve"}
        self.assertTrue(draws["1/admit/1"] and draws["2/writer:1/1"] and draws["4/gates:1/1"])
        for k in ("5/diagnosis/1", "6/writer:2/1", "7/stress:2/1", "8/gates:2/1", "13/seal/1"):
            self.assertFalse(draws[k], k)   # batch only after the first diagnosis

    def test_an_extension_without_progress_retires(self):
        rep = {"outcome": "gate_failed", "gate": "G5", "repairable": True, "passed": ["G1"]}
        r, out = run({"spec": {"max_writer_rounds": 1, "max_cases_started": 1},
                      "script": {"1/gates:1/1": rep, "1/gates:2/1": rep,
                                 "1/diagnosis/*": {"verdict": "close_to_passing"}}})
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1)[-2:], ["gates:2", "diagnosis"])
        self.assertEqual(out["result"]["cases"], {C1: "retired"})


class Escalation(unittest.TestCase):
    def test_continue_reruns_the_step_with_the_ruling(self):
        r, out = run({"script": {"1/4/gates:1/1": {"outcome": "needs_founder", "gate": "G16", "reason": "g16:split_review"}},
                      "actions": [{"when": {"case": 1, "status": "escalated"}, "reply": {"action": "continue"}}]})
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1), ["admit", "writer:1", "stress:1", "gates:1", "gates:1", "seal"])
        self.assertTrue(start(r, f"{C1}/5/gates:1/1")["opened"]["ruling"].startswith("ruling"))
        # ESCALATE ends the line of work, so a replacement started; both seals are kept.
        self.assertEqual(out["result"]["cases"], {C1: "sealed", C2: "sealed"})

    def test_retire_reply(self):
        r, out = run({"spec": {"max_cases_started": 1},
                      "script": {"1/stress:1/1": {"outcome": "needs_founder", "reason": "stress:split_review"}},
                      "actions": [{"when": {"case": 1, "status": "escalated"}, "reply": {"action": "retire"}}]})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "retired"})
        self.assertTrue(any(x["op"] == "release" and x["case"] == C1 for x in r.pool_log()))


class Money(unittest.TestCase):
    def test_bound_wait_is_woken_by_another_cases_settle(self):
        # The bound fits one case's request at a time: whoever is short waits, and wakes on the
        # other's settle, with no BOUND_RAISED.
        r, out = run({"spec": {"target_sealed": 2, "money_bound_usd_micros": 50 * M + 500_000},
                      "script": {"1/writer:1/1": {"dur": 1.0}}}, timeout=180)
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed", C2: "sealed"})
        log = r.ledger_log()
        self.assertFalse([x for x in log if x["op"] == "raise_bound"])
        short = [x for x in log if x["op"] == "reserve" and x["label"] == "batch" and x["amount"] < M]
        self.assertTrue(short)
        for x in short:   # a sub-minimum BATCH grant never started an attempt
            self.assertFalse([s for s in r.worker_log() if s["op"] == "start" and s["key"] == x["key"]])

    def test_bound_raised_wakes_a_waiting_case(self):
        r, out = run({"spec": {"money_bound_usd_micros": 500_000},
                      "actions": [{"when": {"case": 1, "status": "waiting_for_bound"}, "bound": 10_000 * M}]})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        self.assertTrue([x for x in r.ledger_log() if x["op"] == "raise_bound"])
        self.assertEqual(start(r, f"{C1}/1/admit/2")["ceiling"], 50 * M)

    def test_exhausting_a_batch_grant_waits_then_retries(self):
        # ADMIT is granted what the bound has left; using it all is a money wait, not a case result.
        r, out = run({"spec": {"money_bound_usd_micros": 2 * M},
                      "script": {"1/admit/1": {"paid": 5 * M}},
                      "actions": [{"when": {"ran": f"{C1}/1/admit/1"}, "bound": 10_000 * M}]})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        first = next(x for x in r.worker_log() if x["op"] == "ran" and x["key"] == f"{C1}/1/admit/1")
        self.assertEqual(first["outcome"], "exhausted")
        self.assertIn(f"{C1}/1/admit/2", [x["key"] for x in r.starts(1)])

    def test_a_money_stop_before_any_spend_waits_on_the_bound(self):
        # The runner refused the first call (its maximum did not fit the BATCH grant): no usage,
        # yet it is a bound wait, not a case result.
        r, out = run({"spec": {"money_bound_usd_micros": 2 * M},
                      "script": {"1/admit/1": {"outcome": "exhausted", "reason": "admit:money", "paid": 0}},
                      "actions": [{"when": {"case": 1, "status": "waiting_for_bound"}, "bound": 10_000 * M}]})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        self.assertEqual(steps(r, 1)[:2], ["admit", "admit"])

    def test_sub_minimum_case_grant_diagnoses_without_starting(self):
        r, out = run({"spec": {"case_money_usd_micros": 1_500_000, "max_cases_started": 1},
                      "script": {"1/writer:1/1": {"paid": 1_000_000}}})
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1), ["admit", "writer:1", "diagnosis"])   # stress never started
        stress = next(x for x in r.ledger_log() if x["op"] == "reserve" and "/stress:1/" in x["key"])
        self.assertEqual(stress["label"], "case")
        self.assertLess(stress["amount"], M)
        self.assertEqual(start(r, f"{C1}/4/diagnosis/1")["ceiling"], 33 * M)
        self.assertEqual(out["result"]["cases"], {C1: "retired"})


class Releases(unittest.TestCase):
    def test_never_dispatched_admission_does_not_park_after_cutoff_during_provisioning(self):
        r, out = run({'pool_failures': 1, 'pool_reason': 'infra:worker_create_failed',
            'pool_acquire_delay_s': 8, 'deadline_in': 6,
            'spec': {'max_cases_started': 1, 'max_infra_retries_per_step': 0, 'max_factory_bug_resumes': 0},
            'timing': {'pool_wait_ceiling_s': 0}})
        self.addCleanup(r.close)
        self.assertEqual(out['result']['cases'], {C1: 'stopped_admission'})
        self.assertFalse(r.starts())
        self.assertEqual(json.loads((r.work/'state/pool/acquire-failures.json').read_text()), 1)
        self.assertEqual(out['ledger']['batches']['b-t']['held'], 0)

    def test_admission_infrastructure_failure_waits_for_fix_and_retains_state(self):
        r, out = run({'spec': {'max_cases_started': 1, 'max_infra_retries_per_step': 0},
            'script': {'1/admit/1': {'outcome': 'infra_error', 'reason': 'admit:registry_unavailable',
                                    'paid': 12000, 'checkpoint': True}},
            'actions': [{'when': {'case': 1, 'status': 'waiting_for_release'}, 'plumbing': '3'*64}]})
        self.addCleanup(r.close)
        self.assertEqual(out['result']['cases'], {C1: 'sealed'})
        first, retry = start(r, C1+'/1/admit/1'), start(r, C1+'/1/admit/2')
        self.assertNotEqual(first['worker'], retry['worker'])
        self.assertEqual(retry['pv'], '3333')
        self.assertEqual(retry['opened']['snapshot'], 'snapshot '+C1+'/1/admit/1')
        self.assertEqual(len(r.starts(1)), 6)
        self.assertEqual(out['ledger']['batches']['b-t']['held'], 0)
        self.assertGreaterEqual(out['ledger']['batches']['b-t']['waste'], 12000)
        actions = [json.loads(line) for line in (r.work/'state/worker/actions.log').read_text().splitlines()]
        self.assertEqual(actions[0]['status'], 'waiting_for_release')
        self.assertEqual(actions[0]['reason'], 'admit:registry_unavailable')
        self.assertEqual(actions[0]['held'], 0)

    def test_repeated_or_unrelated_updates_do_not_retry_a_failed_release(self):
        r, out = run({'spec': {'max_cases_started': 1, 'max_infra_retries_per_step': 0},
            'script': {'1/admit/1': {'outcome': 'infra_error', 'reason': 'infra:unclassified_stop'}},
            'actions': [
                {'when': {'case': 1, 'status': 'waiting_for_release'}, 'plumbing': '1'*64,
                 'bench': '4'*64, 'bound': 500_000_000},
                {'when': {'case': 1, 'status': 'waiting_for_release'}, 'delay_s': 1, 'plumbing': '3'*64}]})
        self.addCleanup(r.close)
        actions = [json.loads(line) for line in (r.work/'state/worker/actions.log').read_text().splitlines()]
        self.assertGreaterEqual(start(r, C1+'/1/admit/2')['t']-actions[0]['t'], .9)
        self.assertEqual(out['result']['cases'], {C1: 'sealed'})
        self.assertEqual(len([s for s in r.starts() if '/admit/' in s['key']]), 2)

    def test_admission_repair_resumptions_are_capped_at_three(self):
        r, out = run({'spec': {'max_cases_started': 1, 'max_infra_retries_per_step': 0,
                              'max_factory_bug_resumes': 9},
            'script': {'1/admit/*': {'outcome': 'infra_error', 'reason': 'infra:unclassified_stop'}},
            'actions': [{'when': {'case': 1, 'status': 'waiting_for_release',
                                 'ran': f'{C1}/1/admit/{i}'}, 'plumbing': str(i+2)*64}
                        for i in range(1, 4)]})
        self.addCleanup(r.close)
        self.assertEqual(out['result']['cases'], {C1: 'held'})
        self.assertEqual(steps(r, 1), ['admit']*4)
        self.assertEqual(out['ledger']['batches']['b-t']['held'], 0)

    def test_legacy_admission_failure_replay_keeps_terminal_behavior(self):
        r, out = run({'disabled_patches': ['admission_release_recovery'],
            'spec': {'max_cases_started': 1, 'max_infra_retries_per_step': 0},
            'script': {'1/admit/1': {'outcome': 'infra_error', 'reason': 'infra:unclassified_stop'}}})
        self.addCleanup(r.close)
        self.assertEqual(out['result']['cases'], {C1: 'stopped_admission'})

    def test_fix_arriving_during_the_failed_attempt_is_used(self):
        r, out = run({'spec': {'max_cases_started': 1, 'max_infra_retries_per_step': 0},
            'script': {'1/admit/1': {'outcome': 'infra_error', 'reason': 'infra:unclassified_stop', 'dur': 1}},
            'actions': [{'when': {'started': C1+'/1/admit/1'}, 'plumbing': '3'*64}]})
        self.addCleanup(r.close)
        self.assertEqual(start(r, C1+'/1/admit/2')['pv'], '3333')
        self.assertEqual(out['result']['cases'], {C1: 'sealed'})

    def test_control_restart_preserves_admission_release_wait(self):
        r = EngineRun({'spec': {'max_cases_started': 1, 'max_infra_retries_per_step': 0},
            'script': {'1/admit/1': {'outcome': 'infra_error', 'reason': 'infra:unclassified_stop',
                                   'checkpoint': True}},
            'actions': [
                {'when': {'case': 1, 'status': 'waiting_for_release'}, 'plumbing': '1'*64},
                {'when': {'case': 1, 'status': 'waiting_for_release'}, 'delay_s': 2, 'plumbing': '3'*64}]})
        self.addCleanup(r.close)
        p = r.spawn()
        try:
            deadline = time.monotonic()+30
            while not (r.work/'state/worker/actions.log').exists() and time.monotonic()<deadline:
                time.sleep(.05)
            self.assertTrue((r.work/'state/worker/actions.log').exists(), r.tail())
            self.assertEqual(len(r.starts()), 1)
            p.send_signal(signal.SIGKILL); p.wait()
            out = r.run(timeout=60)
        finally:
            if p.poll() is None: p.kill(); p.wait()
        self.assertEqual(out['result']['cases'], {C1: 'sealed'})
        self.assertEqual(len([s for s in r.starts() if s['key']==C1+'/1/admit/1']), 1)
        self.assertEqual(start(r, C1+'/1/admit/2')['opened']['snapshot'], 'snapshot '+C1+'/1/admit/1')

    def test_a_plumbing_release_reaches_a_step_waiting_in_the_queue(self):
        p3 = "3" * 64
        r, out = run({"spec": {"target_sealed": 2, "max_concurrency": 1},
                      "script": {"2/admit/1": {"dur": 3.0}},
                      "actions": [{"when": {"started": f"{C2}/1/admit/1"}, "plumbing": p3}]})
        self.addCleanup(r.close)
        release_at = start(r, f"{C2}/1/admit/1")["t"]
        for x in r.starts():
            if x["t"] > release_at + 2.0:
                self.assertEqual(x["pv"], "3333", x["key"])
        self.assertEqual(set(out["result"]["cases"].values()), {"sealed"})

    def test_seal_reruns_gates_after_a_release(self):
        p3, b4 = "3" * 64, "4" * 64
        r, out = run({"script": {"1/4/gates:1/1": {"dur": 1.5}},
                      "actions": [{"when": {"started": f"{C1}/4/gates:1/1"}, "plumbing": p3, "bench": b4}]})
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1), ["admit", "writer:1", "stress:1", "gates:1", "gates:1", "seal"])
        seen = [(x["key"].split("/", 1)[1], x["pv"], x["bv"]) for x in r.starts(1)]
        self.assertEqual(seen[3], ("4/gates:1/1", "1111", "2222"))
        self.assertEqual(seen[4], ("5/gates:1/1", "3333", "4444"))     # adopted at the next GATES
        self.assertEqual(seen[5], ("6/seal/1", "3333", "4444"))        # SEAL only under its GATES versions
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})

    def test_plumbing_release_reaches_the_next_step(self):
        p3 = "3" * 64
        r, out = run({"script": {"1/2/writer:1/1": {"dur": 1.0}},
                      "actions": [{"when": {"started": f"{C1}/2/writer:1/1"}, "plumbing": p3}]})
        self.addCleanup(r.close)
        seen = {x["key"].split("/", 1)[1]: (x["pv"], x["bv"]) for x in r.starts(1)}
        self.assertEqual(seen["2/writer:1/1"], ("1111", "2222"))
        self.assertEqual(seen["3/stress:1/1"], ("3333", "2222"))        # bench waits for GATES
        self.assertEqual(seen["5/seal/1"], ("3333", "2222"))


class Restart(unittest.TestCase):
    def test_queues_are_registered_before_recovered_admits_run(self):
        # Kill the engine while three ADMITs are queued behind a slow one. The restart registers
        # the queues after launch(); the recovered ADMITs still run one at a time.
        slow = {"dur": 1.0}
        r = EngineRun({"spec": {"target_sealed": 3}, "script": {"1/admit/1": slow, "2/admit/1": slow, "3/admit/1": slow}})
        self.addCleanup(r.close)
        p = r.spawn()
        deadline = time.time() + 60
        while not r.starts() and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)
        p.send_signal(signal.SIGKILL)
        p.wait()
        self.assertEqual(len([x for x in r.starts() if "/admit/" in x["key"]]), 1)
        out = r.run()
        self.assertEqual(set(out["result"]["cases"].values()), {"sealed"})
        spans = []
        ran = {x["key"]: x["done_at"] for x in r.worker_log() if x["op"] == "ran"}
        for x in r.starts():
            if "/admit/" in x["key"]:
                spans.append((x["t"], ran[x["key"]]))
        spans.sort()
        self.assertEqual(len(spans), 3)
        for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
            self.assertGreaterEqual(s2, e1, spans)


class Conductor(unittest.TestCase):
    def test_conductor_is_refused_before_and_after_construction(self):
        from dbos import DBOS
        from dbos._utils import GlobalParams
        from durable.contract import ContractError
        from durable.engine import Engine, check_instance
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        url = f"sqlite:///{tmp.name}/sys.sqlite"
        with self.assertRaises(ContractError):
            Engine(system_database_url=url, executor=None, environ={"DBOS_CONDUCTOR_KEY": "k"}).launch()
        dbos = DBOS(config=Engine(system_database_url=url, executor=None).config())
        self.addCleanup(DBOS.destroy)
        check_instance(dbos)                          # the real constructed instance is clean
        dbos.conductor_key = "k"
        with self.assertRaises(ContractError):
            check_instance(dbos)
        dbos.conductor_key = None
        GlobalParams.dbos_cloud = True
        try:
            with self.assertRaises(ContractError):
                check_instance(dbos)
        finally:
            GlobalParams.dbos_cloud = False


if __name__ == "__main__":
    unittest.main()
