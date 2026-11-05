"""WP4 failure classification (factory/durable/classify.py) on the real stop history.

Real artifacts (ENGINEERING section 4): every stop string is read at test time from the
50 non-dry-run scorecards in sealed/, never copied into a fixture. Design:
docs/designs/durable-execution-wp4.md; findings: docs/reports/durable-execution-wp4-stops.md.
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
                              UNCLASSIFIED, classify)
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

    def test_case_limits_name_the_step(self):
        stop = next(s for _, s in STOPS if s == "call_limit")
        stages = {kind: classify(stop, step=kind, now=NOW).reason for kind in StepKind}
        self.assertEqual(stages, {StepKind.ADMIT: "admit:call_limit", StepKind.WRITER: "writer:call_limit",
                                  StepKind.STRESS: "stress:call_limit", StepKind.GATES: "engine:call_limit",
                                  StepKind.DIAGNOSIS: "diagnosis:call_limit", StepKind.SEAL: "seal:call_limit"})
        self.assertEqual(classify("money_wait", step=StepKind.GATES, now=NOW),
                         Classified(Outcome.EXHAUSTED, "batch:money_bound"))

    def test_every_runner_label_in_budget_py_is_in_the_table(self):
        """The runner's own BudgetError labels (real source, factory/budget.py)."""
        labels = set()
        for node in ast.walk(ast.parse((ROOT / "factory" / "budget.py").read_text())):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "BudgetError" and node.args):
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    labels.add(arg.value)
                elif isinstance(arg, ast.BinOp) and isinstance(arg.left, ast.Constant):
                    labels.add(arg.left.value)   # 'provider_limit:' + route, 'Budget stopped: ' + cause
        labels -= {"Budget stopped: ", "Budget ledger stopped: "}   # wrappers, tested above
        self.assertGreater(len(labels), 30)
        for label in labels:
            self.assertNotEqual(classify(label, step=StepKind.WRITER, now=NOW).reason, UNCLASSIFIED, label)


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
        self.assertTrue(PUBLISHED_REASONS <= REASONS | CONTRACT_REASONS)
        self.assertTrue(all(REASON.fullmatch(r) for r in PUBLISHED_REASONS))
        self.assertNotIn("router:refusal", PUBLISHED_REASONS)
        self.assertEqual(REASONS - PUBLISHED_REASONS, {"router:refusal"})
        for _, stop in STOPS:
            self.assertIn(classify(stop, step=StepKind.WRITER, now=NOW).reason, PUBLISHED_REASONS)

    def test_contract_reasons_are_the_contracts_own(self):
        source = (ROOT / "factory" / "durable" / "contract.py").read_text() + \
            (ROOT / "docs" / "designs" / "durable-execution.md").read_text()
        for reason in CONTRACT_REASONS:
            self.assertIn(reason, source)


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
