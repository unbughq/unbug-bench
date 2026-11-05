"""WP1 engine on real DBOS 3.4.0 (SQLite), against the fakes in test_durable_engine_fakes.py.

docs/designs/durable-execution-wp1.md, "Tests". Each test runs the engine program in a child
process on a fresh database, then reads the fake worker's log, the ledger and the cards.
"""
import json
import os
from pathlib import Path
import signal
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

    def test_pool_failure_releases_the_grant_and_retries(self):
        r, out = run({"pool_failures": 1, "spec": {"max_cases_started": 1}})
        self.addCleanup(r.close)
        self.assertEqual(out["result"]["cases"], {C1: "sealed"})
        key = f"{C1}/1/admit/1"
        self.assertFalse(any(x["key"] == key for x in r.starts()))
        self.assertEqual([x["op"] for x in r.ledger_log() if x.get("key") == key], ["reserve", "settle"])
        self.assertEqual(out["ledger"]["batches"]["b-t"]["held"], 0)

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

    def test_a_free_limit_that_never_clears_gives_up(self):
        # credential_expiring for a missing local secret: free, never clears. The 96th
        # free limit gives up to diagnosis instead of sleeping forever.
        never = {"outcome": "provider_limit", "reason": "router:credential_expiring", "retry_in": 0.01,
                 "paid": 0, "dur": 0.01}
        r, out = run({"spec": {"max_cases_started": 1},
                      "script": {"1/writer:1/*": never, "1/diagnosis/1": {"verdict": "not_converging"}}},
                     timeout=600)
        self.addCleanup(r.close)
        self.assertEqual(steps(r, 1), ["admit"] + ["writer:1"] * 96 + ["diagnosis"])
        self.assertEqual(out["result"]["cases"], {C1: "retired"})

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
