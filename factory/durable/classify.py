"""WP4: failure classification. Turns a runner stop string into exactly one Outcome.

A stop is the runner's BudgetError text or a card's terminal_stop, for example
"opencode_error", "provider_limit:claude/claude-opus-5-5" or "Budget ledger stopped:
codex_error". `classify` implements the contract's `Classifier` protocol.

Rules:
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
_MAX_WRAPPERS = 8

# The stage of an EXHAUSTED case limit is the step's own. REASON has no stage for the
# GATES step as a whole, so it uses "engine" (WP4 contract finding 2).
_STEP_STAGE = {StepKind.ADMIT: "admit", StepKind.WRITER: "writer", StepKind.STRESS: "stress",
               StepKind.GATES: "engine", StepKind.DIAGNOSIS: "diagnosis", StepKind.SEAL: "seal"}

_LIMIT_FAMILY = (("claude/", "router:claude_limit"), ("codex/", "router:codex_limit"),
                 ("opencode-go/", "router:opencode_limit"), ("opencode/", "router:opencode_limit"),
                 ("openrouter/", "router:openrouter_limit"))

_P, _I, _E = Outcome.PROVIDER_LIMIT, Outcome.INFRA_ERROR, Outcome.EXHAUSTED
_WAIT = {"quota": (_P, "router:quota"), "rate": (_P, "router:rate"),
         "credit": (_P, "router:credit"), "outage": (_I, "router:outage"),
         "credential_expiring": (_I, "router:credential_expiring"),
         "unbounded_route": (_I, "router:unbounded_route"),
         "router_unavailable": (_I, "infra:router_unavailable")}
FAILURE_STOPS = frozenset({"process_error", "claude_error", "codex_error", "opencode_error",
                           "refusal", "zero_tokens", "timeout", "stalled", "credential_expiring", "model_unavailable"})

# Exact stop heads (the text before the first ":"), after the runner wrapper is removed.
_FIXED = {
    # Provider limits and waits: durable sleep, no allowance spent.
    "provider_wait": (_P, "router:provider_wait"),
    "ProviderWait": (_P, "router:provider_wait"),
    "shared_paid_spend_wait": (_P, "router:provider_wait"),
    "provider_routes_exhausted": (_P, "router:provider_wait"),
    "codex_login_expired": (_I, "router:credential_expiring"),
    "credential_expiring": (_I, "router:credential_expiring"),
    # Model CLI and provider faults: broken runs, retried.
    "opencode_error": (_I, "router:opencode_error"),
    "codex_error": (_I, "router:codex_error"),
    "claude_error": (_I, "router:claude_error"),
    "process_error": (_I, "router:process_error"),
    "model_unavailable": (_I, "router:model_unavailable"),
    "zero_tokens": (_I, "router:zero_tokens"),
    "refusal": (_I, "router:refusal"),
    "admission_registry_unavailable": (_I, "admit:registry_unavailable"),
    "selection_board_unavailable": (_I, "admit:selection_board_unavailable"),
    "admission_dedup_unavailable": (_I, "admit:dedup_unavailable"),
    "admission_dedup_invalid": (_I, "admit:dedup_invalid"),
    "admission_idea_review_unavailable": (_I, "admit:idea_review_unavailable"),
    "admission_idea_review_invalid": (_I, "admit:idea_review_invalid"),
    "freshness_evidence_unavailable": (_I, "infra:freshness_evidence_unavailable"),
    "freshness_review_unavailable": (_I, "infra:freshness_review_unavailable"),
    "freshness_repair_state_invalid": (_I, "infra:freshness_repair_state_invalid"),
    "freshness_statement_changed": (_I, "infra:freshness_statement_changed"),
    "freshness_unresolved": (_I, "infra:freshness_unresolved"),
    # Runner and plumbing faults: broken runs, retried.
    'case_changed_during_review': (_I, 'infra:case_changed_during_review'),
    'diagnosis_cleanup_failed': (_I, 'infra:diagnosis_cleanup_failed'),
    'diagnosis_input_invalid': (_I, 'infra:diagnosis_input_invalid'),
    'diagnosis_result_invalid': (_I, 'infra:diagnosis_result_invalid'),
    'diagnosis_schema_wait': (_I, 'infra:diagnosis_schema_wait'),
    'extension_snapshot_invalid': (_I, 'infra:extension_snapshot_invalid'),
    'factory_bug_held': (_I, 'infra:factory_bug_held'),
    'malformed_output_exhausted': (_I, 'infra:malformed_output_exhausted'),
    'ordinary_retry_completion_missing': (_I, 'infra:retry_completion_missing'),
    'ordinary_retry_output_changed': (_I, 'infra:ordinary_retry_output_changed'),
    'ordinary_retry_state_invalid': (_I, 'infra:ordinary_retry_state_invalid'),
    'owner_invalid_answer': (_I, 'infra:owner_invalid_answer'),
    'stress_category_output_changed': (_I, 'infra:stress_category_output_changed'),
    'stress_category_state_invalid': (_I, 'infra:stress_category_state_invalid'),
    'stress_publication_not_quiescent': (_I, 'infra:stress_publication_not_quiescent'),
    'stress_validation_exhausted': (_I, 'infra:stress_validation_exhausted'),
    "RouterUnavailable": (_I, "infra:router_unavailable"),
    "router_unavailable": (_I, "infra:router_unavailable"),
    "unbounded_route": (_I, "infra:router_unavailable"),
    "router_batch_unconfigured": (_I, "infra:router_unavailable"),
    "stalled": (_I, "infra:stalled"),
    "timeout": (_I, "infra:timeout"),
    "cancelled": (_I, "infra:cancelled"),
    "PauseRequested": (_I, "infra:paused"),
    "paused": (_I, "infra:paused"),
    # Each keeps its own public code: one shared label hid which of these stopped a run.
    "missing_usage": (_I, "infra:missing_usage"),
    "invalid_usage": (_I, "infra:usage_unknown"),
    "unpriced_usage": (_I, "infra:unpriced_usage"),
    "free_route_mismatch": (_I, "infra:free_route_mismatch"),
    "first_token_timeout": (_I, "infra:first_token_timeout"),
    "usage_monitor": (_I, "infra:usage_monitor"),
    "usage_reservation_exceeded": (_I, "infra:usage_reservation_exceeded"),
    "reservation_spend_unknown": (_I, "infra:reservation_spend_unknown"),
    "reservation_event_missing": (_I, "infra:reservation_event_missing"),
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
    "engine_reselection_disabled": (_I, "infra:runner_error"),
    "seal_error": (_I, "infra:runner_error"),
    "complete": (_I, "infra:stop_without_failure"),
    "running": (_I, "infra:stop_without_failure"),
    "": (_I, "infra:stop_without_failure"),
    # The batch deadline (a clock, not money) passed during a provider wait (model_router.py).
    # It is the contract's attempt-deadline code.
    "provider_wait_deadline": (_I, "infra:deadline"),
}

# The attempt's own limits: EXHAUSTED, with the step's stage. Whether money was the case's or
# the batch's is the policy's call, from the Grant label, so the reason does not say.
_CASE_LIMIT = {"cost_limit": "money", "budget_exhausted": "money",
               "call_limit": "call_limit", "total_call_limit": "total_call_limit", "model_call_cap": "money"}

_USAGE = re.compile(r"(invalid_usage|usage)_[a-z_]+")
_CLI_VERSION = re.compile(r"[a-z]+_cli_not_.*", re.S)   # model_runtime.pinned_cli
_EXCEPTION = re.compile(r"[A-Z][A-Za-z0-9]*(Error|Exception|Exit|Interrupt)")

UNCLASSIFIED = "infra:unclassified_stop"

# run.provider_preflight's roles and the CLI's own stop, in short fixed forms (REASON allows 32).
PREFLIGHT_ROLES = {"stress_tester": "stress", "strong_tester": "strong", "easy_tester": "easy",
                   "reviewer": "review", "reviewer2": "second"}
PREFLIGHT_STOPS = {"process_error": "process", "claude_error": "claude", "codex_error": "codex",
                   "opencode_error": "opencode", "refusal": "refusal", "zero_tokens": "zero_tokens",
                   "timeout": "timeout", "stalled": "stalled", "credential_expiring": "credential",
                   "model_unavailable": "model"}

REASONS = frozenset({r for _, r in _FIXED.values()} | {r for _, r in _LIMIT_FAMILY}
                    | {"router:preflight_failed"}
                    | {f"router:preflight_{r}_{c}" for r in PREFLIGHT_ROLES.values() for c in PREFLIGHT_STOPS.values()}
                    | {r for _, r in _WAIT.values()}
                    | {"router:provider_limit", "infra:usage_unknown", "infra:cli_version",
                       "infra:runner_exception", UNCLASSIFIED}
                    | {f"{stage}:{code}" for stage in _STEP_STAGE.values() for code in _CASE_LIMIT.values()})

# Fixed codes that the contract and the design define outside WP4.
CONTRACT_REASONS = frozenset({"infra:deadline", "infra:version_mismatch", "infra:attempt_busy",
                              "infra:cancelled", "engine:executor_raised", "engine:executor_bad_result"})

# Fixed WP2 PoolError reasons; these reveal no provider output. The engine waits on them, within a ceiling.
# Campaign worker limits (guard.reserve_start): wait for a free slot, up to the batch deadline.
CAMPAIGN_WAIT_REASONS = frozenset({"infra:worker_slots_full", "infra:worker_start_rate"})
WORKER_POOL_REASONS = frozenset({"infra:worker_create_failed", "infra:worker_create_unknown",
                                 "infra:inventory_unavailable", "infra:worker_delete_unconfirmed"}
                                | CAMPAIGN_WAIT_REASONS)

# Reasons safe for the public scorecard. "A model refused this case" hints at the case's
# content, so router:refusal stays private. report.py shows any other reason as its
# outcome alone.
# Legacy import refusals (durable/steps/admit.py IMPORT_REFUSALS): which check failed, never what it saw.
IMPORT_REASONS = frozenset("admit:" + code for code in (
    "import_key", "import_layout", "import_layout_root", "import_layout_card", "import_layout_meta",
    "import_layout_statement", "import_layout_card_case", "import_links", "import_pin", "import_source",
    "import_spend", "import_writer", "import_writer_none", "import_writer_conflict", "import_invalid",
    "import_recertify"))
# Admission rejections (durable/admission_reasons.py REJECTION_CODES): the screen and a fixed
# evidence kind, never the idea.
REJECTION_REASONS = frozenset("admit:" + code for code in (
    "dedup_board_duplicate", "freshness_upstream_fix", "freshness_upstream_report", "freshness_app_docs",
    "freshness_third_party", "freshness_unrecorded", "freshness_mixed", "realism_rejected",
    "other_selection_failed", "other_missing_statement", "other_repeat_candidate", "other_unknown",
    "other_mixed", "rejected_mixed"))
# A board-cleanup ADMIT (durable/board_cleanup.py) ends with a plan, never a case.
BOARD_REASONS = frozenset({"admit:board_planned"})
# A preflight refusal is a refusal too: it may react to the case directory it ran in.
_PRIVATE = {"router:refusal"} | {f"router:preflight_{r}_refusal" for r in PREFLIGHT_ROLES.values()}
PUBLISHED_REASONS = frozenset((REASONS | CONTRACT_REASONS | WORKER_POOL_REASONS | IMPORT_REASONS
                               | REJECTION_REASONS | BOARD_REASONS) - _PRIVATE)

if not all(REASON.fullmatch(r) for r in REASONS | CONTRACT_REASONS | WORKER_POOL_REASONS | IMPORT_REASONS
           | REJECTION_REASONS | BOARD_REASONS):
    raise ContractError("a WP4 reason breaks the REASON grammar")


def _head(stop: str) -> tuple[str, str]:
    text = stop.strip()
    for _ in range(_MAX_WRAPPERS):   # a stored stop can come back wrapped again (budget.py:1357, :885)
        wrapper = next((w for w in _WRAPPERS if text.startswith(w)), None)
        if wrapper is None:
            break
        text = text[len(wrapper):].strip()
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
    if head == "provider_preflight_failed":
        role, _, cause = rest.strip().partition(":")
        if role in PREFLIGHT_ROLES and cause in PREFLIGHT_STOPS:
            return _I, None, f"router:preflight_{PREFLIGHT_ROLES[role]}_{PREFLIGHT_STOPS[cause]}"
        return _I, None, "router:preflight_failed"
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


def classify_wait(error, *, step, now, prior=()):
    """Classify structured waits and return an allowlisted, content-free diagnostic.

    Never copy exception text, prompts, URLs or arbitrary provider fields.
    """
    raw = [*prior, *getattr(error, 'previous_waits', ()), vars(error.wait)]
    waits = []
    for row in raw[-32:]:
        if not isinstance(row, dict): continue
        reason = row.get('reason')
        record = {'reason': reason if isinstance(reason, str) and reason in _WAIT else 'unknown'}
        if row.get('historical') is True: record['historical'] = True
        value = row.get('retry_after')
        if type(value) in (int, float) and math.isfinite(value) and 0 < value <= now + MAX_RESET_AHEAD_S:
            record['retry_after'] = value
        lease = row.get('lease_id')
        if isinstance(lease, str) and re.fullmatch('[a-f0-9]{32}', lease): record['lease_id'] = lease
        call = row.get('call_id')
        if isinstance(call, str) and re.fullmatch(r'usage-receipts/[a-f0-9]{32}\.json', call): record['call_id'] = call
        if isinstance(row.get('source_stop'), str) and row['source_stop'] in FAILURE_STOPS:
            record['source_stop'] = row['source_stop']
        if record not in waits: waits.append(record)
    active = [row for row in waits if not row.get('historical')]
    reasons = {row['reason'] for row in active}
    fault = next((r for r in ('credential_expiring', 'unbounded_route', 'router_unavailable') if r in reasons), None)
    original = next((row['source_stop'] for row in reversed(waits) if 'source_stop' in row), None)
    reason = fault or waits[-1]['reason']
    reset = max((r['retry_after'] for r in active if 'retry_after' in r), default=None)
    if original and fault is None and reason not in ('quota', 'rate', 'credit'):
        result = classify(original, step=step, now=now, reset_at=reset)
    else:
        outcome, code = _WAIT.get(reason, (_I, UNCLASSIFIED))
        result = Classified(outcome, code, _retry_at(now, reset) if outcome is _P else None)
    return result, {'schema': 1, 'waits': waits}


__all__ = ["BACKOFF_S", "MAX_RESET_AHEAD_S", "REASONS", "CONTRACT_REASONS", "PUBLISHED_REASONS",
           "UNCLASSIFIED", "classify"]
