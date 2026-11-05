"""WP4: failure classification. Turns a runner stop string into exactly one Outcome.

A stop is the runner's BudgetError text or a card's terminal_stop, for example
"opencode_error", "provider_limit:claude/claude-opus-5-5" or "Budget ledger stopped:
codex_error". `classify` implements the contract's `Classifier` protocol.

Rules (docs/designs/durable-execution-wp4.md):
- Pure: no I/O, no clock, no engine import. The same input always gives the same result.
- A reason is never built from stop text. Every reason is a member of the fixed set
  REASONS, so nothing a stop carries (paths, routes, messages) can reach the engine
  database or the public card.
- Broken runs (model-CLI errors, stalls, timeouts, pauses, accounting faults, runner
  exceptions, and any stop not listed here) are INFRA_ERROR. They are never scored.
- Every PROVIDER_LIMIT has a finite retry_at: a trusted reset time when the caller has
  one, otherwise now + BACKOFF_S.
- classify never returns OK, GATE_FAILED or NEEDS_FOUNDER: a stop is not a verdict.
"""
from __future__ import annotations

import math
import re
from typing import Optional

from durable.contract import REASON, Classified, ContractError, Outcome, StepKind

# A limit with no usable reset time sleeps this long. It equals model_router.retry_at's
# first-failure delay (900 s) for every reason except router_unavailable, so the engine
# and the router back off alike (tests/factory/test_durable_classify.py pins the two).
BACKOFF_S = 900.0
# A reset time further ahead than this is not trusted (weekly windows are 7 days).
MAX_RESET_AHEAD_S = 8 * 24 * 3600.0

_WRAPPERS = ("Budget stopped: ", "Budget ledger stopped: ")

# The stage of an EXHAUSTED case limit is the step's own. REASON has no stage for the
# GATES step as a whole, so it uses "engine" (WP4 contract finding 2).
_STEP_STAGE = {StepKind.ADMIT: "admit", StepKind.WRITER: "writer", StepKind.STRESS: "stress",
               StepKind.GATES: "engine", StepKind.DIAGNOSIS: "diagnosis", StepKind.SEAL: "seal"}

_LIMIT_FAMILY = (("claude/", "router:claude_limit"), ("codex/", "router:codex_limit"),
                 ("opencode-go/", "router:opencode_limit"), ("opencode/", "router:opencode_limit"),
                 ("openrouter/", "router:openrouter_limit"))

_P, _I, _E = Outcome.PROVIDER_LIMIT, Outcome.INFRA_ERROR, Outcome.EXHAUSTED

# Exact stop heads (the text before the first ":"), after the runner wrapper is removed.
_FIXED = {
    # Provider limits and waits: durable sleep, no allowance spent.
    "provider_wait": (_P, "router:provider_wait"),
    "ProviderWait": (_P, "router:provider_wait"),
    "shared_paid_spend_wait": (_P, "router:provider_wait"),
    "provider_routes_exhausted": (_P, "router:provider_wait"),
    "codex_login_expired": (_P, "router:credential_expiring"),
    "credential_expiring": (_P, "router:credential_expiring"),
    # Model CLI and provider faults: broken runs, retried.
    "opencode_error": (_I, "router:opencode_error"),
    "codex_error": (_I, "router:codex_error"),
    "claude_error": (_I, "router:claude_error"),
    "process_error": (_I, "router:process_error"),
    "zero_tokens": (_I, "router:zero_tokens"),
    "refusal": (_I, "router:refusal"),
    "provider_preflight_failed": (_I, "router:preflight_failed"),
    # Runner and plumbing faults: broken runs, retried.
    "RouterUnavailable": (_I, "infra:router_unavailable"),
    "router_unavailable": (_I, "infra:router_unavailable"),
    "unbounded_route": (_I, "infra:router_unavailable"),
    "router_batch_unconfigured": (_I, "infra:router_unavailable"),
    "stalled": (_I, "infra:stalled"),
    "timeout": (_I, "infra:timeout"),
    "cancelled": (_I, "infra:cancelled"),
    "PauseRequested": (_I, "infra:paused"),
    "paused": (_I, "infra:paused"),
    "missing_usage": (_I, "infra:usage_unknown"),
    "invalid_usage": (_I, "infra:usage_unknown"),
    "unpriced_usage": (_I, "infra:usage_unknown"),
    "usage_monitor": (_I, "infra:usage_unknown"),
    "Invalid budget ledger; no process started": (_I, "infra:ledger_error"),
    "resume_while_active": (_I, "infra:ledger_error"),
    "reservation_mismatch": (_I, "infra:ledger_error"),
    "reservation_already_invoked": (_I, "infra:ledger_error"),
    "invalid_money": (_I, "infra:ledger_error"),
    "invalid_operation": (_I, "infra:ledger_error"),
    "invalid_provider_wait": (_I, "infra:ledger_error"),
    "wait_receipt_mismatch": (_I, "infra:ledger_error"),
    "invalid_waste_attribution": (_I, "infra:ledger_error"),
    "waste_attribution_mismatch": (_I, "infra:ledger_error"),
    "waste_operations_pending": (_I, "infra:ledger_error"),
    "ordinary_limit_unknown": (_I, "infra:ledger_error"),
    "route_maximum_unknown": (_I, "infra:ledger_error"),
    "cleanup_failed": (_I, "infra:cleanup_failed"),
    "cancellation_failed": (_I, "infra:cleanup_failed"),
    "containment_unavailable": (_I, "infra:cleanup_failed"),
    "runner_error": (_I, "infra:runner_error"),
    "seal_error": (_I, "infra:runner_error"),
    "complete": (_I, "infra:stop_without_failure"),
    "running": (_I, "infra:stop_without_failure"),
    "": (_I, "infra:stop_without_failure"),
    # The batch bound ran out under this attempt; the policy reads the Grant label.
    "money_wait": (_E, "batch:money_bound"),
    "retired_batch_bound": (_E, "batch:money_bound"),
}

# The case's own limits: EXHAUSTED, with the step's stage.
_CASE_LIMIT = {"cost_limit": "money", "budget_exhausted": "money", "call_limit": "call_limit",
               "total_call_limit": "total_call_limit", "model_call_cap": "call_cap"}

_USAGE = re.compile(r"(invalid_usage|usage)_[a-z_]+")
_CLI_VERSION = re.compile(r"(codex|claude|opencode)_cli_not_.*", re.S)
_EXCEPTION = re.compile(r"[A-Z][A-Za-z0-9]*(Error|Exception|Exit|Interrupt)")

UNCLASSIFIED = "infra:unclassified_stop"

REASONS = frozenset({r for _, r in _FIXED.values()} | {r for _, r in _LIMIT_FAMILY}
                    | {"router:provider_limit", "infra:usage_unknown", "infra:cli_version",
                       "infra:runner_exception", UNCLASSIFIED}
                    | {f"{stage}:{code}" for stage in _STEP_STAGE.values() for code in _CASE_LIMIT.values()})

# Fixed codes that the contract and the design define outside WP4.
CONTRACT_REASONS = frozenset({"infra:deadline", "infra:version_mismatch", "infra:attempt_busy",
                              "infra:cancelled", "engine:executor_raised", "engine:executor_bad_result"})

# Reasons safe for the public scorecard. "A model refused this case" hints at the case's
# content, so router:refusal stays private. report.py shows any other reason as its
# outcome alone.
PUBLISHED_REASONS = frozenset((REASONS | CONTRACT_REASONS) - {"router:refusal"})

if not all(REASON.fullmatch(r) for r in REASONS | CONTRACT_REASONS):
    raise ContractError("a WP4 reason breaks the REASON grammar")


def _head(stop: str) -> tuple[str, str]:
    text = stop.strip()
    for wrapper in _WRAPPERS:
        if text.startswith(wrapper):
            text = text[len(wrapper):].strip()
            break
    head, _, rest = text.partition(":")
    return head, rest


def _lookup(stop) -> tuple[Outcome, Optional[str], str]:
    """(outcome, case-limit code or None, reason). The reason is from the fixed tables."""
    if not isinstance(stop, str):
        return _I, None, UNCLASSIFIED
    head, rest = _head(stop)
    if head == "provider_limit":
        route = rest.strip()
        return _P, None, next((r for prefix, r in _LIMIT_FAMILY if route.startswith(prefix)), "router:provider_limit")
    if head in _FIXED:
        outcome, reason = _FIXED[head]
        return outcome, None, reason
    if head in _CASE_LIMIT:
        return _E, _CASE_LIMIT[head], ""
    if _CLI_VERSION.fullmatch(head):
        return _I, None, "infra:cli_version"
    if _USAGE.fullmatch(head):
        return _I, None, "infra:usage_unknown"
    if _EXCEPTION.fullmatch(head) and not rest:
        return _I, None, "infra:runner_exception"
    return _I, None, UNCLASSIFIED


def _retry_at(now: float, reset_at) -> float:
    if (type(reset_at) in (int, float) and math.isfinite(reset_at)
            and now < reset_at <= now + MAX_RESET_AHEAD_S):
        return float(reset_at)
    return now + BACKOFF_S


def classify(stop, *, step, now: float, reset_at: Optional[float] = None) -> Classified:
    """The Classifier protocol, plus an optional trusted reset time (epoch seconds) that
    a caller holding the ledger's claude_resets_at or provider_failure.reset_at may pass.

    Raises ContractError only for a caller bug (a bad step or a non-finite now); the
    executor reaches it through guarded_run, which contains it."""
    try:
        kind = StepKind(step)
    except ValueError:
        raise ContractError("step must be a StepKind") from None
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ContractError("now must be a finite number")
    outcome, case_code, reason = _lookup(stop)
    if case_code is not None:
        reason = f"{_STEP_STAGE[kind]}:{case_code}"
    return Classified(outcome, reason, _retry_at(float(now), reset_at) if outcome is _P else None)


__all__ = ["BACKOFF_S", "MAX_RESET_AHEAD_S", "REASONS", "CONTRACT_REASONS", "PUBLISHED_REASONS",
           "UNCLASSIFIED", "classify"]
