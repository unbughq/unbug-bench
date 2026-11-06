"""WP4 failure classification (factory/durable/classify.py) on the real stop history.

Stop strings are read at test time from the 50 non-dry-run scorecards in
sealed/, never copied into a fixture.
"""
import ast
import collections
import json
import math
import os
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory")]
os.environ.setdefault("BENCH", str(ROOT))

from durable import classify as wp4
from durable.classify import (BACKOFF_S, CONTRACT_REASONS, MAX_RESET_AHEAD_S, PUBLISHED_REASONS, REASONS,
                              UNCLASSIFIED, WORKER_POOL_REASONS, classify)
from durable.contract import (REASON, ArtifactKind, Classified, ContractError, Outcome, Ref, Step, StepKind,
                              StepResult, check_result_for)

NOW = 1_792_400_000.0   # 2026-10-19, inside the real runs' window
NEVER_FROM_A_STOP = (Outcome.OK, Outcome.GATE_FAILED, Outcome.NEEDS_FOUNDER)


def real_cards():
    cards = []
    for path in sorted((ROOT / "sealed").glob("case-*.scorecard.json")):
        card = json.loads(path.read_text())
        if card.get("dry_run") is False:
            cards.append(card)
    return cards


def real_stops(cards):
    """(source, stop) for every stop string the cards record."""
    out = []
    for card in cards:
        budget = card.get("continuation_budget") or {}
        if budget:
            out += [("history", s) for s in budget.get("previous_stops") or []]
            out.append(("history", budget.get("terminal_stop")))
        if "terminal_stop" in card:
            out.append(("card", card["terminal_stop"]))
        if "error" in card:
            out.append(("error", card["error"]))
    return out


CARDS = real_cards()
STOPS = real_stops(CARDS)


def head(stop):
    for wrapper in ("Budget stopped: ", "Budget ledger stopped: "):
        if stop.startswith(wrapper):
            stop = stop[len(wrapper):]
    return stop.split(":", 1)[0]


def as_result(c):
    return StepResult(c.outcome, c.reason, retry_at=c.retry_at,
                      snapshot=Ref("0" * 64, ArtifactKind.CASE_SNAPSHOT) if c.outcome is Outcome.OK else None)


def step_of(kind):
    return Step(kind, 1 if kind.numbered else 0)


class RealStops(unittest.TestCase):
    def test_structured_waits_are_distinct_and_do_not_export_arbitrary_text(self):
        from model_router import ProviderWait, Wait
        expected = {'quota': (Outcome.PROVIDER_LIMIT, 'router:quota'),
                    'rate': (Outcome.PROVIDER_LIMIT, 'router:rate'),
                    'credit': (Outcome.PROVIDER_LIMIT, 'router:credit'),
                    'credential_expiring': (Outcome.INFRA_ERROR, 'router:credential_expiring'),
                    'unbounded_route': (Outcome.INFRA_ERROR, 'router:unbounded_route'),
                    'outage': (Outcome.INFRA_ERROR, 'router:outage'),
                    'router_unavailable': (Outcome.INFRA_ERROR, 'infra:router_unavailable')}
        for cause, want in expected.items():
            for step in StepKind:
                error = ProviderWait('writer', Wait(cause, NOW + 120, route='private-prompt-sentinel',
                                                    account='secret-token-sentinel'))
                result, details = wp4.classify_wait(error, step=step, now=NOW)
                self.assertEqual((result.outcome, result.reason), want)
                self.assertNotIn('sentinel', json.dumps(details))
                self.assertIn(result.reason, REASONS)
                self.assertEqual(result.retry_at, NOW + 120 if result.outcome is Outcome.PROVIDER_LIMIT else None)
        error = ProviderWait('writer', Wait('outage', NOW + 120))
        error.previous_waits = [{'reason': 'outage', 'source_stop': 'process_error'}]
        result, _ = wp4.classify_wait(error, step=StepKind.ADMIT, now=NOW)
        self.assertEqual(result.reason, 'router:process_error')
        error.wait = Wait('quota', NOW + 120)
        result, _ = wp4.classify_wait(error, step=StepKind.ADMIT, now=NOW)
        self.assertEqual(result.outcome, Outcome.PROVIDER_LIMIT)
        error.wait = Wait('credential_expiring', NOW + 120)
        result, details = wp4.classify_wait(error, step=StepKind.ADMIT, now=NOW)
        self.assertEqual(result.reason, 'router:credential_expiring')
        self.assertEqual(details['waits'][0]['source_stop'], 'process_error')

    def test_corpus_is_the_fifty_real_cards(self):
        self.assertEqual(len(CARDS), 50)
        history = [s for src, s in STOPS if src == "history"]
        self.assertEqual(len(history), 511)
        self.assertEqual(len(STOPS), 511 + 33 + 1)

    def test_every_real_stop_maps_to_exactly_one_valid_outcome_for_every_step(self):
        for _, stop in STOPS:
            for kind in StepKind:
                c = classify(stop, step=kind, now=NOW)
                self.assertIsInstance(c, Classified)
                self.assertIsInstance(c.outcome, Outcome)
                self.assertIn(c.reason, REASONS, stop)
                self.assertIsNotNone(REASON.fullmatch(c.reason))
                self.assertNotEqual(c.reason, UNCLASSIFIED, f"real stop {stop!r} is not in the table")
                self.assertNotIn(c.outcome, NEVER_FROM_A_STOP, stop)
                check_result_for(step_of(kind), as_result(c))   # the outcome is legal for this step
                if c.outcome is Outcome.PROVIDER_LIMIT:
                    self.assertTrue(math.isfinite(c.retry_at) and c.retry_at > NOW)
                else:
                    self.assertIsNone(c.retry_at)

    def test_counts_by_kind_and_outcome_match_the_report(self):
        got = collections.Counter((src, head(s), classify(s, step=StepKind.WRITER, now=NOW).outcome.value,
                                   classify(s, step=StepKind.WRITER, now=NOW).reason) for src, s in STOPS)
        I, P, E = "infra_error", "provider_limit", "exhausted"
        want = {
            ("history", "opencode_error", I, "router:opencode_error"): 210,
            ("history", "provider_limit", P, "router:claude_limit"): 68,
            ("history", "provider_limit", P, "router:openrouter_limit"): 22,
            ("history", "provider_limit", P, "router:opencode_limit"): 9,
            ("history", "stalled", I, "infra:stalled"): 74,
            ("history", "PauseRequested", I, "infra:paused"): 52,
            ("history", "timeout", I, "infra:timeout"): 24,
            ("history", "complete", I, "infra:stop_without_failure"): 17,
            ("history", "codex_error", I, "router:codex_error"): 12,
            ("history", "process_error", I, "router:process_error"): 9,
            ("history", "paused", I, "infra:paused"): 6,
            ("history", "call_limit", E, "writer:call_limit"): 2,
            ("history", "total_call_limit", E, "writer:total_call_limit"): 2,
            ("history", "PermissionError", I, "infra:runner_exception"): 2,
            ("history", "cancelled", I, "infra:cancelled"): 2,
            ("card", "paused", I, "infra:paused"): 22,
            ("card", "provider_limit", P, "router:openrouter_limit"): 5,
            ("card", "provider_limit", P, "router:claude_limit"): 3,
            ("card", "call_limit", E, "writer:call_limit"): 1,
            ("card", "stalled", I, "infra:stalled"): 1,
            ("card", "codex_error", I, "router:codex_error"): 1,
            ("error", "LookupError", I, "infra:runner_exception"): 1,
        }
        self.assertEqual(dict(got), want)

    def test_broken_runs_are_infra_errors_never_scored(self):
        for _, stop in STOPS:
            if head(stop) in ("opencode_error", "codex_error", "process_error", "stalled", "timeout", "cancelled",
                              "PauseRequested", "paused", "PermissionError", "LookupError", "complete"):
                for kind in StepKind:
                    self.assertIs(classify(stop, step=kind, now=NOW).outcome, Outcome.INFRA_ERROR, stop)

    def test_wrapped_runner_text_classifies_as_its_cause(self):
        wrapped = [s for _, s in STOPS if s.startswith("Budget ledger stopped: ")]
        self.assertEqual(wrapped, ["Budget ledger stopped: codex_error"])
        self.assertEqual(classify(wrapped[0], step=StepKind.STRESS, now=NOW),
                         classify("codex_error", step=StepKind.STRESS, now=NOW))
        self.assertEqual(classify("Budget stopped: stalled", step=StepKind.WRITER, now=NOW).reason, "infra:stalled")
        # A stored stop can come back wrapped again (budget.py:358 stores str(error)).
        rewrapped = "Budget ledger stopped: " + wrapped[0]
        self.assertEqual(classify(rewrapped, step=StepKind.STRESS, now=NOW).reason, "router:codex_error")
        self.assertEqual(classify("Budget stopped: " * 9 + "stalled", step=StepKind.WRITER, now=NOW).reason,
                         UNCLASSIFIED)   # the loop is bounded

    def test_case_limits_name_the_step(self):
        stop = next(s for _, s in STOPS if s == "call_limit")
        stages = {kind: classify(stop, step=kind, now=NOW).reason for kind in StepKind}
        self.assertEqual(stages, {StepKind.ADMIT: "admit:call_limit", StepKind.WRITER: "writer:call_limit",
                                  StepKind.STRESS: "stress:call_limit", StepKind.GATES: "engine:call_limit",
                                  StepKind.DIAGNOSIS: "diagnosis:call_limit", StepKind.SEAL: "seal:call_limit"})

    def test_cost_limit_is_the_attempts_money_and_the_policy_tells_case_from_batch(self):
        self.assertEqual(classify("cost_limit", step=StepKind.WRITER, now=NOW),
                         Classified(Outcome.EXHAUSTED, "writer:money"))
        self.assertNotIn("batch:money_bound", REASONS)

    def test_batch_deadline_stops_are_the_contracts_deadline_not_money(self):
        # provider_wait_deadline: model_router.py.
        for kind in StepKind:
            self.assertEqual(classify("provider_wait_deadline", step=kind, now=NOW),
                             Classified(Outcome.INFRA_ERROR, "infra:deadline"))
        self.assertIn("infra:deadline", CONTRACT_REASONS)

    RUNNER_FILES = ("budget.py", "model_router.py", "model_runtime.py", "model_call_gate.py", "run.py")
    # Reviewed: what every BudgetError label raised in RUNNER_FILES classifies to.
    MAPPED = {
        "Invalid budget ledger; no process started": ("infra_error", "infra:ledger_error"),
        "budget_exhausted": ("exhausted", "writer:money"),
        "call_limit": ("exhausted", "writer:call_limit"),
        "cancellation_failed": ("infra_error", "infra:cleanup_failed"),
        "cancelled": ("infra_error", "infra:cancelled"),
        "claude_error": ("infra_error", "router:claude_error"),
        "cleanup_failed": ("infra_error", "infra:cleanup_failed"),
        "codex_error": ("infra_error", "router:codex_error"),
        "codex_login_expired": ("infra_error", "router:credential_expiring"),
        "cost_limit": ("exhausted", "writer:money"),
        "budget_exhausted:grant_insufficient": ("exhausted", "writer:money"),
        "credential_expiring": ("infra_error", "router:credential_expiring"),
        "invalid_money": ("infra_error", "infra:ledger_error"),
        "invalid_operation": ("infra_error", "infra:ledger_error"),
        "invalid_provider_wait": ("infra_error", "infra:ledger_error"),
        "invalid_usage": ("infra_error", "infra:usage_unknown"),
        "invalid_usage_binding": ("infra_error", "infra:usage_unknown"),
        "invalid_usage_event": ("infra_error", "infra:usage_unknown"),
        "invalid_usage_price": ("infra_error", "infra:usage_unknown"),
        "invalid_usage_receipt": ("infra_error", "infra:usage_unknown"),
        "invalid_waste_attribution": ("infra_error", "infra:ledger_error"),
        "missing_usage": ("infra_error", "infra:usage_unknown"),
        "model_call_cap": ("exhausted", "writer:money"),
        "opencode_error": ("infra_error", "router:opencode_error"),
        "process_error": ("infra_error", "router:process_error"),
        "provider_limit:": ("provider_limit", "router:provider_limit"),
        "provider_preflight_failed": ("infra_error", "router:preflight_failed"),
        "provider_routes_exhausted": ("provider_limit", "router:provider_wait"),
        "provider_wait_deadline": ("infra_error", "infra:deadline"),
        "refusal:": ("infra_error", "router:refusal"),
        "reservation_already_invoked": ("infra_error", "infra:ledger_error"),
        "reservation_mismatch": ("infra_error", "infra:ledger_error"),
        "resume_while_active": ("infra_error", "infra:ledger_error"),
        "route_maximum_unknown": ("infra_error", "infra:ledger_error"),
        "router_batch_unconfigured": ("infra_error", "infra:router_unavailable"),
        "shared_paid_spend_wait": ("provider_limit", "router:provider_wait"),
        "stalled": ("infra_error", "infra:stalled"),
        "timeout": ("infra_error", "infra:timeout"),
        "total_call_limit": ("exhausted", "writer:total_call_limit"),
        "unbounded_route": ("infra_error", "infra:router_unavailable"),
        "unpriced_usage": ("infra_error", "infra:usage_unknown"),
        "usage_event_conflict": ("infra_error", "infra:usage_unknown"),
        "usage_event_missing": ("infra_error", "infra:usage_unknown"),
        "usage_event_shared": ("infra_error", "infra:usage_unknown"),
        "usage_monitor:": ("infra_error", "infra:usage_unknown"),
        "usage_unknown": ("infra_error", "infra:usage_unknown"),
        "usage_reservation_exceeded": ("infra_error", "infra:usage_unknown"),
        "usage_receipt_regressed": ("infra_error", "infra:usage_unknown"),
        "usage_reservation_missing": ("infra_error", "infra:usage_unknown"),
        "wait_receipt_mismatch": ("infra_error", "infra:ledger_error"),
        "waste_attribution_mismatch": ("infra_error", "infra:ledger_error"),
        "waste_operations_pending": ("infra_error", "infra:ledger_error"),
        "x_cli_not_x": ("infra_error", "infra:cli_version"),   # f'{kind}_cli_not_{want}', model_runtime.py
        "zero_tokens": ("infra_error", "router:zero_tokens"),
    }
    # Reviewed: labels that stay infra:unclassified_stop (still INFRA_ERROR, never scored).
    # The two bare wrappers only ever prefix a cause. The rest are run.py lifecycle stops
    # (admission, freshness, extension, stress review, provider-wait records) that the
    # engine replaces, or dispatch faults with no engine meaning.
    UNCLASSIFIED_BY_DESIGN = {
        "Budget ledger stopped: ", "Budget stopped: ",
        "admission_dedup_invalid", "admission_dedup_unavailable", "admission_idea_review_invalid",
        "admission_idea_review_unavailable", "admission_registry_unavailable",

        "freshness_evidence_unavailable", "freshness_public_match", "freshness_repair_state_invalid",
        "freshness_review_unavailable", "freshness_statement_changed", "freshness_unresolved",

        "provider_wait_record_missing", "provider_wait_unsettled", "route_feature_unsupported",
        "selection_board_unavailable", "stress_publication_configuration_missing",
        "stress_review_unresolved:",
    }

    def runner_labels(self):
        """Every BudgetError label literal raised in the runner's real source files."""
        labels = set()
        for name in self.RUNNER_FILES:
            for node in ast.walk(ast.parse((ROOT / "factory" / name).read_text())):
                if not (isinstance(node, ast.Call) and node.args and
                        getattr(node.func, "id", getattr(node.func, "attr", None)) == "BudgetError"):
                    continue
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    labels.add(arg.value)
                elif isinstance(arg, ast.BinOp) and isinstance(arg.left, ast.Constant):
                    labels.add(arg.left.value)   # 'provider_limit:' + route, 'Budget stopped: ' + cause
                elif isinstance(arg, ast.IfExp):
                    labels |= {x.value for x in (arg.body, arg.orelse) if isinstance(x, ast.Constant)}
                elif isinstance(arg, ast.JoinedStr):
                    labels.add("".join(v.value if isinstance(v, ast.Constant) else "x" for v in arg.values))
        return labels

    def test_every_runner_label_has_its_reviewed_outcome(self):
        labels = self.runner_labels()
        self.assertEqual(labels, set(self.MAPPED) | self.UNCLASSIFIED_BY_DESIGN,
                         "a runner label was added or removed: review its mapping")
        for label, want in self.MAPPED.items():
            c = classify(label, step=StepKind.WRITER, now=NOW)
            self.assertEqual((c.outcome.value, c.reason), want, label)
        for label in self.UNCLASSIFIED_BY_DESIGN:
            self.assertEqual(classify(label, step=StepKind.WRITER, now=NOW),
                             Classified(Outcome.INFRA_ERROR, UNCLASSIFIED), label)


class RetryAt(unittest.TestCase):
    def test_limit_without_reset_time_backs_off_like_the_router(self):
        import model_router
        limits = [s for _, s in STOPS if head(s) == "provider_limit"]
        self.assertEqual(len(limits), 107)
        for stop in limits:
            for now in (0.0, NOW, NOW + 0.5):
                c = classify(stop, step=StepKind.WRITER, now=now)
                self.assertIs(c.outcome, Outcome.PROVIDER_LIMIT)
                self.assertEqual(c.retry_at, now + BACKOFF_S)
                self.assertEqual(c.retry_at, model_router.retry_at("quota", now=now))

    def test_real_claude_reset_time_is_used_when_passed(self):
        resets = sorted({c["continuation_budget"]["claude_resets_at"] for c in CARDS
                         if (c.get("continuation_budget") or {}).get("claude_resets_at")})
        self.assertEqual(resets, [1792511400, 1792695600])
        for reset in resets:
            c = classify("provider_limit:claude/claude-opus-5-5", step=StepKind.WRITER, now=reset - 7200,
                         reset_at=reset)
            self.assertEqual((c.reason, c.retry_at), ("router:claude_limit", float(reset)))

    def test_untrusted_reset_times_fall_back_to_the_backoff(self):
        stop = "provider_limit:claude/claude-opus-5-5"
        for bad in (NOW - 1, NOW, NOW + MAX_RESET_AHEAD_S + 1, float("inf"), float("nan"), "1792695600", True, None):
            self.assertEqual(classify(stop, step=StepKind.GATES, now=NOW, reset_at=bad).retry_at, NOW + BACKOFF_S, bad)

    def test_reset_time_never_reaches_a_non_limit(self):
        self.assertIsNone(classify("opencode_error", step=StepKind.WRITER, now=NOW, reset_at=NOW + 60).retry_at)

    def test_caller_bugs_raise_contract_error(self):
        for now in (float("nan"), float("inf"), "1", None):
            with self.assertRaises(ContractError):
                classify("provider_limit:claude/claude-opus-5-5", step=StepKind.WRITER, now=now)
        with self.assertRaises(ContractError):
            classify("stalled", step="gates:1", now=NOW)


class Secrecy(unittest.TestCase):
    def test_no_stop_text_reaches_a_reason(self):
        secret = "src/modules/inventory/reserve.ts SECRET_KEY=sk-live-42"
        for stop in (secret, "provider_limit:" + secret, "refusal:" + secret, "runner_error:" + secret,
                     "Budget stopped: " + secret, "usage_monitor:" + secret, "KeyError: " + secret,
                     "g5:reference_unsolved", "x" * 10_000, b"opencode_error", None, 7, ["stalled"]):
            for kind in StepKind:
                c = classify(stop, step=kind, now=NOW)
                self.assertIn(c.reason, REASONS)
                for token in ("src", "reserve", "SECRET", "sk", "42", "g5"):
                    self.assertNotIn(token, c.reason.split(":", 1)[1])
        self.assertEqual(classify(secret, step=StepKind.WRITER, now=NOW),
                         Classified(Outcome.INFRA_ERROR, UNCLASSIFIED))

    def test_published_allowlist(self):
        self.assertTrue(PUBLISHED_REASONS <= REASONS | CONTRACT_REASONS | WORKER_POOL_REASONS)
        self.assertTrue(all(REASON.fullmatch(r) for r in PUBLISHED_REASONS))
        self.assertNotIn("router:refusal", PUBLISHED_REASONS)
        self.assertEqual(REASONS - PUBLISHED_REASONS, {"router:refusal"})
        for _, stop in STOPS:
            self.assertIn(classify(stop, step=StepKind.WRITER, now=NOW).reason, PUBLISHED_REASONS)



class Purity(unittest.TestCase):
    def test_imports_only_the_contract_and_stdlib(self):
        tree = ast.parse(Path(wp4.__file__).read_text())
        mods = {n.module if isinstance(n, ast.ImportFrom) else a.name
                for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in (n.names if isinstance(n, ast.Import) else [n])}
        self.assertEqual(mods, {"__future__", "math", "re", "typing", "durable.contract"})

    def test_deterministic(self):
        for _, stop in STOPS:
            self.assertEqual(classify(stop, step=StepKind.GATES, now=NOW), classify(stop, step=StepKind.GATES, now=NOW))

    def test_step_accepts_the_enum_or_its_value(self):
        self.assertEqual(classify("call_limit", step="stress", now=NOW).reason, "stress:call_limit")


if __name__ == "__main__":
    unittest.main()
