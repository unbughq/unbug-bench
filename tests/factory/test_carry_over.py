"""Version steps, real metadata and the exhaustive allowance transition model."""
import copy
import itertools
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin")]
import carry_over as state


def event(value, kind, cause="case", **fields):
    return state.append(value, kind=kind, cause=cause, actor="recorded-test-role",
                        reason="recorded test outcome", **fields)


def attempt(value, outcome, operation="freshness_repair"):
    number = len(value["events"])
    cause = "infrastructure" if outcome == "release" else "case"
    value = event(value, "start", cause=cause, attempt_id=str(number), operation=operation,
                  scope="round-1" if operation in ("rereview", "diagnostic") else "case", estimate=1, binding="judge-contract")
    if outcome in ("deadline", "crash", "release"):
        value = event(value, "waste", cause="infrastructure", amount=0.5, evidence="kill-receipt")
        cause, stop = "infrastructure", "interrupted" if outcome != "release" else "completed"
    else:
        value = event(value, "usage", amount=1, evidence="metered-call")
        cause, stop = "case", "completed" if outcome == "pass" else "failed"
    return event(value, "stop", cause=cause, attempt_id=str(number), outcome=stop,
                 usage_known=outcome != "unknown", usage_evidence="metered-call-or-explicit-waste-resolution")


def check_model(depth=5):
    """Enumerate the same production projection for each stop kind, operation and prefix."""
    kinds = ("pass", "case_failure", "deadline", "crash", "release", "unknown")
    explored = admitted = refused = 0
    for operation in state.OPERATIONS:
        for length in range(depth + 1):
            for sequence in itertools.product(kinds, repeat=length):
                explored += 1
                value = state.new_state("case-model", budget=50, rounds=3)
                previous_spent = 0
                previous_used = {}
                for stop in sequence:
                    before = copy.deepcopy(value)
                    try:
                        value = attempt(value, stop, operation)
                    except state.Refused:
                        # The real admission operation refused: no event or allowance
                        # may have been published from the failed pure transition.
                        assert before == value
                        refused += 1
                        break
                    counters = value["counters"]
                    assert counters["known_case_spent_usd"] >= previous_spent
                    if stop in ("deadline", "crash", "release"):
                        assert counters["used"] == previous_used
                        assert counters["known_case_spent_usd"] == previous_spent
                    if stop == "unknown":
                        assert counters["case_spent_usd"] is None
                        assert value["admission"]["admitted"] is False
                    assert all(v <= counters["caps"][k.split(":")[0]] for k, v in counters["used"].items())
                    assert counters["infrastructure_attempts"] <= state.INFRASTRUCTURE_LIMIT
                    previous_spent, previous_used = counters["known_case_spent_usd"], dict(counters["used"])
                else:
                    admitted += 1
    # Pure infrastructure loops, including changing judge contracts, terminate.
    value = state.new_state("case-bound", budget=50)
    for _ in range(state.INFRASTRUCTURE_LIMIT): value = attempt(value, "release", "rereview")
    try: attempt(value, "release", "rereview")
    except state.Refused: pass
    else: raise AssertionError("infrastructure loop unbounded")
    # Every case-caused loop is bounded for one scope too.
    for operation, cap in state.OPERATIONS.items():
        value = state.new_state("case-bound", budget=50)
        for _ in range(cap): value = attempt(value, "case_failure", operation)
        try: attempt(value, "case_failure", operation)
        except state.Refused: pass
        else: raise AssertionError("case loop unbounded: " + operation)
    return {"depth": depth, "operations": len(state.OPERATIONS), "stop_kinds": len(kinds),
            "sequences": explored, "completed_sequences": admitted, "refused_sequences": refused,
            "invariants": ["infrastructure preserves every case allowance", "all retry scopes bounded",
                "spend monotonic and excludes waste", "unknown usage fails closed", "seal requires every current gate binding"]}


class CarryOverTests(unittest.TestCase):
    def test_real_saved_cards_pure_ordered_steps_and_idempotence(self):
        fixtures = Path(__file__).parent / "fixtures"
        for name, spent in (("canary6-collected-card.json", None), ("c7d405-collected-card.json", None),
                            ("e15450-collected-card.json", 39.778912756)):
            with self.subTest(name=name):
                card = json.loads((fixtures / name).read_text()); original = copy.deepcopy(card)
                v1 = state.v0_to_v1(card); v2 = state.v1_to_v2(v1)
                loaded = state.load(card)
                self.assertEqual(card, original)
                self.assertEqual(loaded, state.load(v1))
                self.assertEqual(loaded, state.load(v2))
                self.assertEqual(loaded, state.load(loaded))
                self.assertEqual(loaded["counters"]["case_spent_usd"], spent)
                self.assertFalse(loaded["admission"]["admitted"])
                self.assertFalse(loaded["counters"]["allowances_known"])
                accounted = set(v1["artifacts"]["scorecard"]) | set(v1["artifacts"]["legacy_derived"]) | set(v1["artifacts"]["dropped_volatile"])
                self.assertEqual(accounted, set(card))
                loaded["counters"] = {"invented": "allowance"}
                self.assertNotIn("invented", state.load(loaded)["counters"])

    def test_fail_closed_inputs_no_crashes(self):
        card = json.loads((Path(__file__).parent / "fixtures/e15450-collected-card.json").read_text())
        for value in (None, [], 3, {"state_version": 99}, {**card, "new_unclassified": 1},
                      {**card, "continuation_budget": {}}, {**card, "wall_minutes": float("nan")}):
            with self.subTest(shape=type(value).__name__), self.assertRaises(state.Refused): state.load(value)
        for field, bad in (("events", [None]), ("infrastructure_waste", [None]), ("cost", -1),
                           ("unpriced_invocations", {}), ("events", [{"id": "x"}, {"id": "x"}])):
            malformed = copy.deepcopy(card); malformed["continuation_budget"][field] = bad
            with self.subTest(field=field), self.assertRaises(state.Refused): state.load(malformed)

    def test_legacy_missing_history_cannot_be_cleared_by_old_projection(self):
        card = json.loads((Path(__file__).parent / "fixtures/e15450-collected-card.json").read_text())
        value = state.v0_to_v1(card); value['unresolved'] = []
        migrated = state.load(value)
        self.assertFalse(migrated['admission']['admitted'])
        migrated['unresolved'] = []
        self.assertFalse(state.load(migrated)['admission']['admitted'])
        with self.assertRaises(state.Refused):
            event(migrated, 'start', operation='round', scope='case', attempt_id='legacy-reset')

    def test_legacy_running_usage_preserves_known_spend_but_fails_closed(self):
        card = json.loads((Path(__file__).parent / "fixtures/e15450-collected-card.json").read_text())
        for active, stop in ((['unfinished'], 'running'), ([], 'running'), (['unfinished'], 'complete')):
            with self.subTest(active=bool(active), stop=stop):
                card['continuation_budget'] = dict(events=[], calls=0, cost=3, active=active, terminal_stop=stop)
                value = state.load(card)
                self.assertIsNone(value['counters']['case_spent_usd'])
                self.assertEqual(value['counters']['known_case_spent_usd'], 3)
                self.assertTrue(value['counters']['unknown_usage'])
                self.assertNotIn('active', value['artifacts']['usage']['ledger'])
                self.assertFalse(value['admission']['admitted'])

    def test_release_forced_rereview_never_consumes_case_allowance(self):
        value = state.new_state("case-e15450-regression")
        value = attempt(value, "release", "rereview")
        self.assertEqual(value["counters"]["used"], {})
        self.assertEqual(value["counters"]["release_rereviews"], ["judge-contract"])
        value = attempt(value, "case_failure", "rereview")
        self.assertEqual(value["counters"]["used"]["rereview:round-1"], 1)

    def test_pending_attempt_cannot_duplicate_or_seal(self):
        value = state.new_state("case-pending")
        value = event(value, "start", operation="round", scope="case", attempt_id="one")
        self.assertFalse(value["admission"]["admitted"])
        with self.assertRaises(state.Refused):
            event(value, "start", operation="round", scope="case", attempt_id="two")
        with self.assertRaises(state.Refused): event(value, "seal", bindings={})

    def test_scopes_and_missing_usage_cannot_reopen_allowances(self):
        value = state.new_state("case-scope")
        for _ in range(2): value = attempt(value, "case_failure")
        with self.assertRaises(state.Refused):
            event(value, "start", operation="freshness_repair", scope="invented-new-scope", attempt_id="reset")
        with self.assertRaises(state.Refused):
            event(value, "start", operation="rereview", scope="round-999", attempt_id="reset")
        value = event(value, "start", operation="round", scope="case", attempt_id="missing-usage")
        value = event(value, "stop", cause="infrastructure", attempt_id="missing-usage", outcome="interrupted")
        self.assertTrue(value["counters"]["unknown_usage"])
        self.assertFalse(value["admission"]["admitted"])
        self.assertEqual(value["counters"]["used"], {"freshness_repair:case": 2})

    def test_budget_reservation_boundary_and_unknown_usage_are_sticky(self):
        for remaining in (0, 0.5, 1):
            value = state.new_state("case-budget", budget=2)
            value = event(value, "usage", amount=2 - remaining, evidence="past-metered-spend")
            if remaining < 1:
                with self.assertRaises(state.Refused): attempt(value, "pass")
            else:
                value = attempt(value, "pass")
                self.assertEqual(value["counters"]["case_spent_usd"], 2)
                with self.assertRaises(state.Refused): attempt(value, "pass")
        value = state.new_state("case-unknown")
        value = attempt(value, "unknown")
        value = event(value, "usage", amount=1, evidence="later-known-usage")
        value = event(value, "waste", cause="infrastructure", amount=9, evidence="independent-waste")
        self.assertIsNone(value["counters"]["case_spent_usd"])
        self.assertFalse(value["admission"]["admitted"])

    def test_seal_requires_each_current_gate_including_g12(self):
        value = state.new_state("case-seal"); bindings = {}
        for gate in state.GATES:
            with self.assertRaises(state.Refused): event(value, "seal", bindings=bindings)
            bindings[gate] = "contract-" + gate
            value = event(value, "gate", gate=gate, verdict="pass", binding=bindings[gate])
        with self.assertRaises(state.Refused): event(value, "seal", bindings={**bindings, "G8": "changed-prompt"})
        sealed = event(value, "seal", bindings=bindings)
        self.assertTrue(sealed["counters"]["sealed"])
        with self.assertRaises(state.Refused): event(sealed, "usage", amount=1, evidence="late")
        for gate in state.GATES:
            invalid = event(value, "invalidate", gate=gate, binding="changed")
            with self.assertRaises(state.Refused): event(invalid, "seal", bindings=bindings)

    def test_exhaustive_model(self):
        result = check_model()
        self.assertEqual(result["sequences"], 65317)
        print("CARRY_OVER_MODEL " + json.dumps(result), flush=True)


if __name__ == "__main__": unittest.main()
