"""Which step-result reasons are factory bugs, and whether recorded attempts show a fix failing.

REGISTRY maps every reason the engine can record to one kind:
  case - a genuine case outcome (a gate failed, the writer validated, a diagnosis completed);
  wait - an expected provider, money or operator wait that parks cleanly;
  bug  - a factory bug class, with fixed_in (the commits on main that fix it, all needed; None while
         open) and test (path::Class::name of the regression test that reproduces it, or None).
Single reasons are listed one by one. Families that classify.py builds as a product of its own
tables (preflight role x stop, cleanup stage x error, case limits, import and rejection codes)
and the per-gate verdicts are generated, since a new member is the same class as its siblings.
tests/factory/test_stop_registry.py fails when a reason the factory can record has no entry.

STOPS maps every stop label (the runner's BudgetError text, before classify.py names its reason) to its
scope (does one call's failure stop only that call, or the case's ledger?) and the router reason, if any,
that moves the call to its next route. budget.py, model_runtime.py and diagnostics.py read it.

`audit` is pure: attempt rows in, verdicts out. bin/stop_audit runs it as `user` on a timer and
writes `result` as JSON; the root campaign guard only reads that file (durable/guard.stop_audit_alerts).
`read_attempts`, `release_commits` and `git_contains` are the thin, bounded readers around it.
"""
from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import pickle
import subprocess
from types import SimpleNamespace
from typing import Callable, Iterable, Optional

from durable.classify import (CLEANUP_ERRORS, CLEANUP_STAGES, IMPORT_REASONS, PREFLIGHT_ROLES, PREFLIGHT_STOPS,
                              REJECTION_REASONS, _CASE_LIMIT, _STEP_STAGE)
from durable.contract import Outcome
from durable.policy import settles_as_waste

CASE, WAIT = {"kind": "case"}, {"kind": "wait"}


def bug(*fixed_in: str, test: Optional[str] = None) -> dict:
    return {"kind": "bug", "fixed_in": fixed_in or None, "test": test}


OPEN = bug()

REGISTRY = {
    # -- case outcomes --
    "admit:selected": CASE, "admit:practice": CASE, "admit:conflict": CASE, "admit:board_planned": CASE,
    "admit:imported_sealed": CASE, "admit:imported_written": CASE, "admit:imported_hand": CASE,
    "writer:validated": CASE, "writer:practice": CASE, "writer:invalid_practice": CASE, "writer:handback": CASE,
    "writer:rounds_exhausted": CASE, "writer:unchanged_repair": CASE, "writer:output_capped": CASE,
    "stress:clean": CASE, "stress:findings": CASE, "stress:public_match": CASE, "stress:practice": CASE,
    "engine:gates_passed": CASE, "g5:reference_unsolved": CASE, "g8:no_eligible_reviewer": CASE,
    "diagnosis:completed": CASE, "seal:sealed": CASE,
    # -- waits: provider limits, campaign worker limits, operator waits and the batch clock --
    "router:quota": WAIT, "router:rate": WAIT, "router:capacity": WAIT, "router:credit": WAIT,
    "router:provider_wait": WAIT, "router:provider_limit": WAIT, "router:claude_limit": WAIT,
    "router:codex_limit": WAIT, "router:opencode_limit": WAIT, "router:openrouter_limit": WAIT,
    "router:neuralwatt_limit": WAIT,
    "router:outage": WAIT, "router:credential_expiring": WAIT, "infra:credentials_unavailable": WAIT,
    "infra:worker_slots_full": WAIT, "infra:worker_start_rate": WAIT, "infra:paused": WAIT,
    "infra:campaign_deadline": WAIT,
    # -- factory bugs with a fix on main --
    # fixed_in only where the reason maps one-to-one to the cause the fix fixed; a reason that collects
    # several causes stays open (its fixes in a comment), or a new cause would read as a regression.
    # None qualifies today.
    # -- factory bugs whose reason collects several causes: open, with the fixes so far --
    # Any role's prompt over Linux's one-argument limit; 0f818fe5 created the reason and fixed the diagnosis
    # prompt (it carried the full inventory), so other roles reaching it are new causes, not regressions.
    # Since 2abb0a every prompt goes on stdin; only a non-prompt argument can still reach it.
    "infra:prompt_too_large": bug(test=
        "tests/factory/test_model_call_maxima.py::MaximaTests::"
        "test_factory_dispatch_preserves_lease_maximum_gate_and_invocation_identity"),
    # Fallback for any diagnosis exception that cannot name itself; 97d97b84 fixed the missing stress report.
    "diagnosis:processing_failed": bug(test=
        "tests/factory/test_durable_diagnosis.py::DiagnosisTests::"
        "test_a_close_verdict_on_a_case_stopped_in_a_writer_round_gives_feedback"),
    # Any runner exception; aeabd48d (strategy calls on pinned bench images) + 1d52c92d (release-pair preflight).
    "infra:runner_exception": bug(test=
        "tests/factory/test_strategy_reuse.py::StrategyPrefixRecoveryTests::"
        "test_pinned_worker_strategy_before_sharing_still_runs"),
    # Anything that runs into the batch deadline; 2fcbaf66 (doomed writer cycle) + 5694aea3 (deadline diagnostic).
    "infra:deadline": bug(test=
        "tests/factory/test_stress_loop.py::StressLoopTests::"
        "test_writer_hands_back_findings_instead_of_starting_a_doomed_cycle"),
    # Any diagnosis cleanup stage; b58ea3ec (latest of fe112d74, fa92e2eb, 956c9fa4) fixed pilot homes.
    "infra:diagnosis_cleanup_failed": bug(test=
        "tests/factory/test_pilot_home_teardown.py::PilotHomeTeardown::"
        "test_a_diagnosis_teardown_timeout_keeps_its_cause"),
    # Any silent call; 8d1093d4 fixed the silent writer route.
    "infra:stalled": bug(test=
        "tests/factory/test_silent_writer_route.py::SilentWriterRoute::"
        "test_a_stalled_selection_call_moves_to_the_next_route"),
    # Any exhausted infra allowance (incl. run.gates_result's fallback stop); 874b2727 (after f0f6e4e3,
    # 0c2b545b) fixed live-slot seed IDs and allowances; the gather class is on fix/gather-live-slot-state.
    "infra:execution_retries_exhausted": bug(test=
        "tests/factory/test_live_slot_fixture.py::LiveSlotFixtureTests::"
        "test_rebuilt_slot_gets_a_fresh_infra_allowance"),
    # Any free-text stop; f2c9199a made code stops name themselves (infra:raw_<label>).
    "infra:unclassified_stop": bug(test=
        "tests/factory/test_durable_classify.py::SelfNamingStops::test_unknown_identifier_stops_name_themselves"),
    # -- factory bugs, open or in flight --
    # Each of these collects several causes, so it stays open with its fixes named here (see above).
    # Any cancel; 0ed1ef2d stopped a call's own cancel becoming the shared ledger's stop (2abb0a gates:9).
    "infra:cancelled": bug(test=
        "tests/factory/test_budget.py::BudgetTests::test_own_cancel_does_not_stop_peers_or_later_calls"),
    # Any admission processing failure; ba032666 named the second reviewer's calls (1110a-2's preflight).
    "admit:processing_failed": bug(test=
        "tests/factory/test_preflight_role_pin.py::PreflightRolePin::"
        "test_every_call_site_in_the_source_builds_a_name_with_a_known_role"),
    # Any missing freshness evidence; fix/freshness-expired-refetch made expired rows refetchable (f46dac);
    # fix/g2-freshness-refresh lets a same-query re-run supersede an unretrievable row and never charges an
    # unretrieved row's missing note as a defect. A role still short stays a real cause, so it stays open.
    "infra:freshness_evidence_unavailable": bug(test=
        "tests/factory/test_stream_d_retries.py::RetryTests::"
        "test_an_unretrieved_rows_missing_note_is_refresh_work_not_a_defect"),
    # A refresh that fixed nothing: expired rows not re-fetched, or rows whose links never retrieve; or
    # G2 held 30 minutes on the same 429/5xx/network failures (18681d, 15 Nov: answeroverflow 429).
    # One reason, several causes (our outage, or the case's dead links), so it stays open.
    "infra:freshness_refresh_stalled": OPEN,
    # 3 identical G2 cycles held by a page behind a bot wall (401/403/451) with no archive copy: the
    # source does not answer, not our bug. The card's freshness_stalled names each URL and failure for a
    # person to open or rule out.
    "infra:freshness_source_blocked": CASE,
    # Three free 4xx rejections in a row on one call (a permanent bad request); a real stop, not a wait.
    "router:upstream_rejected": OPEN,
    # The diagnosis run left no usable result: missing, oversized, unsafe, or unreadable.
    # Each now names its cause; the causes behind them are not yet fixed, so they stay open.
    "infra:diagnosis_result_invalid": OPEN,
    "infra:diagnosis_result_missing": OPEN,
    "infra:diagnosis_result_oversized": OPEN,
    "infra:diagnosis_result_unsafe": OPEN,
    "infra:pool_failed": OPEN,   # several causes; 6ea112d fixed one (bounded_create arity)
    # model_router.running(): the router refused a renewal that came after the lease had lapsed (cae763,
    # 15 November). The stall's cause (host, process, thread starvation) is not known, so it stays open.
    "infra:worker_stalled": OPEN,
    # Containment causes fixed by 0ec53bb0 and 3fd7d011; the scratch-unmount timeout is in flight on
    # fix/sweep-leftovers.
    "infra:cleanup_failed": OPEN,
    **{r: OPEN for r in (
        "admit:dedup_invalid", "admit:dedup_unavailable", "admit:idea_review_invalid",
        "admit:idea_review_unavailable", "admit:inputs_invalid", "admit:registry_invalid",
        "admit:registry_unavailable", "admit:second_opinion_invalid", "admit:second_opinion_unavailable",
        "admit:selection_board_unavailable",
        "diagnosis:wrong_step",
        "engine:admit_unavailable", "engine:below_minimum_grant", "engine:diagnosis_unavailable",
        "engine:executor_bad_result", "engine:executor_raised", "engine:keys_failed", "engine:ledger_failed",
        "engine:not_configured", "engine:pool_failed", "engine:sealer_failed", "engine:store_failed",
        "infra:attempt_absent", "infra:attempt_busy", "infra:bad_frame", "infra:bad_result",
        "infra:bench_fingerprint_failed", "infra:bench_mismatch", "infra:blob_unavailable",
        "infra:card_write_failed", "infra:case_changed_during_review", "infra:classifier_unavailable",
        "infra:cli_version", "infra:compute_approval_unverified", "infra:context_failed",
        "infra:creation_limit", "infra:diagnosis_config_invalid",
        "infra:diagnosis_input_invalid", "infra:diagnosis_loopback_failed", "infra:diagnosis_schema_wait", "infra:dispatch_failed", "infra:extension_snapshot_invalid", "infra:factory_bug_held", "infra:free_route_mismatch",
        "infra:freshness_repair_state_invalid", "infra:freshness_review_unavailable",
        "infra:freshness_statement_changed", "infra:freshness_unresolved", "infra:gate_error",
        "infra:invalid_execution", "infra:inventory_unavailable", "infra:ledger_error",
        "infra:malformed_output_exhausted", "infra:missing_usage", "infra:model_launch_failed",
        "infra:model_wall_failed", "infra:money_authority", "infra:ordinary_retry_output_changed",
        "infra:ordinary_retry_state_invalid", "infra:output_unavailable", "infra:owner_invalid_answer",
        "infra:provider_wait_record_missing", "infra:provider_wait_unsettled", "infra:refill_failed",
        "infra:release_missing", "infra:release_unreadable", "infra:reservation_event_missing",
        "infra:reservation_spend_unknown", "infra:restore_failed", "infra:retry_completion_missing",
        "infra:roles_refused", "infra:route_feature_unsupported", "infra:router_unavailable",
        "infra:router_unconfigured", "infra:runner_error", "infra:sealer_unavailable",
        "infra:snapshot_failed", "infra:step_crashed", "infra:stop_without_failure",
        "infra:stress_category_output_changed", "infra:stress_category_state_invalid",
        "infra:stress_publication_not_quiescent", "infra:stress_validation_exhausted", "infra:sweep_failed",
        "infra:sweep_incomplete", "infra:timeout", "infra:unpriced_usage",
        "infra:usage_monitor", "infra:usage_reservation_exceeded", "infra:usage_unknown",
        "infra:version_mismatch", "infra:warm_failed", "infra:warm_stopped", "infra:worker_create_failed",
        "infra:worker_create_unknown", "infra:worker_delete_failed", "infra:worker_delete_unconfirmed",
        "infra:worker_error", "infra:worker_lost", "infra:worker_unreachable",
        # workers.BoatPool._step's PoolError("infra:<name>") for each worker install step.
        "infra:release_upload_failed", "infra:release_unpack_failed", "infra:cli_pin_failed",
        "infra:image_source_prepare_failed", "infra:image_prepare_failed", "infra:release_qualify_failed",
        "infra:release_commit_failed",
        # Model CLI faults: often the provider, sometimes us; open until triaged.
        "router:claude_error", "router:codex_error", "router:opencode_error", "router:process_error",
        "router:model_unavailable", "router:zero_tokens", "router:refusal", "router:unbounded_route",
        "router:preflight_failed",
        "seal:gates_not_passed",
        # run.engine_stress_round's infra("<code>") stops.
        "stress:writer_handback_pending", "stress:case_changed", "stress:malformed_report",
        "stress:unfinished_validation", "stress:interrupted_review", "stress:unfinished_diagnostic")},
    # -- generated families --
    **{f"g{n}:{code}": CASE for n in range(1, 18) for code in ("failed", "reviewers_disagree", "review_inconclusive")},
    **{f"{stage}:{code}": CASE for stage in _STEP_STAGE.values() for code in _CASE_LIMIT.values()},
    **{r: CASE for r in IMPORT_REASONS | REJECTION_REASONS},
    **{f"router:preflight_{r}_{s}": OPEN for r in PREFLIGHT_ROLES.values() for s in PREFLIGHT_STOPS.values()},
    **{f"infra:dcf_{s}_{e}": OPEN for s in CLEANUP_STAGES for e in (*CLEANUP_ERRORS.values(), "other")},
}


# Families named by a free label (classify.CLEANUP_PREFIX): one entry per prefix. infra:raw_* has none on
# purpose: a stop no table knows is UNKNOWN until classify.py names it.
PREFIXES = {"diagnosis:cf_": OPEN}   # a diagnosis whose cleanup also failed, named by its first error


def lookup(reason: str, registry: dict = REGISTRY) -> Optional[dict]:
    return registry.get(reason) or next((e for p, e in PREFIXES.items() if reason.startswith(p)), None)


# ---- stop labels: what one call's failure stops ---------------------------------------------
# STOPS maps every stop label the factory raises (BudgetError text) or writes as a terminal_stop, by its head
# (the text before the first ":"), to:
#   scope   - call: the failing call's own. A concurrent call's failure leaves the shared budget ledger open, so
#             its peers run on; model_runtime moves the call to its next route (reroute) or the call fails alone.
#             case: the case's money or the ledger itself is spent or untrustworthy, a process may have
#             outlived its call, or the operator paused: the ledger stops, and with it every peer call.
#             A serial call is the whole session, so its failure is the ledger's stop whatever the scope.
#             Scope acts only on labels raised inside budget.run_budgeted (the call's own process); a label raised
#             around a model call never reaches the shared ledger, and its scope only says what it would stop.
#   reroute - the router reason model_runtime.call_failure_reason gives the failed call, so it moves to its
#             chain's next route; outage_if_short / outage_if_free only for a short call / a free route.
# An unlisted label stops the case: a stop nobody gave a scope fails closed. Only an unlisted exception class name
# (a fault in the call's own reader) is its call's own. tests/factory/test_stop_registry.py fails when the factory
# raises or writes a label that has no entry here.
CALL_SCOPE, CASE_SCOPE = "call", "case"


def _stops(scope, labels, reroute=None):
    return {label: {"scope": scope, "reroute": reroute} for label in labels}


STOPS = {
    # -- one call's provider or CLI failure: its next route --
    **_stops(CALL_SCOPE, ("opencode_error", "claude_error", "codex_error", "process_error", "refusal"), "outage"),
    **_stops(CALL_SCOPE, ("provider_limit",), "quota"),
    **_stops(CALL_SCOPE, ("codex_login_expired", "credential_expiring"), "credential_expiring"),
    **_stops(CALL_SCOPE, ("stalled",), "outage_if_short"),   # a silent short call; a long one may be thinking
    # A free route's broken usage report or provider mismatch: the next route is gated.
    **_stops(CALL_SCOPE, ("missing_usage", "invalid_usage", "free_route_mismatch"), "outage_if_free"),
    # -- one call's own limit or fault: it fails alone --
    **_stops(CALL_SCOPE, (
        "timeout", "cancelled", "call_limit", "zero_tokens", "model_unavailable", "unpriced_usage",
        "usage_monitor", "usage_reservation_exceeded", "model_call_cap", "unbounded_route", "route_maximum_unknown",
        "upstream_rejected", "shared_paid_spend_wait", "route_feature_unsupported", "model_launch_failed",
        "model_wall_failed", "prompt_too_large",
        "provider_wait", "provider_routes_exhausted", "provider_wait_unsettled", "provider_wait_record_missing",
        "router_batch_unconfigured", "provider_preflight_failed",
        # step-level stops raised around model calls, never inside one
        "admission_dedup_invalid", "admission_dedup_unavailable", "admission_idea_review_invalid",
        "admission_idea_review_unavailable", "admission_registry_unavailable", "admission_second_opinion_invalid",
        "admission_second_opinion_unavailable", "selection_board_unavailable", "case_changed_during_review",
        "diagnosis_cleanup_failed", "diagnosis_config_invalid", "diagnosis_input_invalid",
        "diagnosis_loopback_failed", "diagnosis_result_invalid", "diagnosis_result_missing",
        "diagnosis_result_oversized", "diagnosis_result_unsafe", "diagnosis_schema_wait", "extension_snapshot_invalid",
        "extension_snapshot_changed",
        "factory_bug_held", "freshness_evidence_unavailable", "freshness_public_match", "freshness_refresh_stalled",
        "freshness_repair_state_invalid", "freshness_review_unavailable", "freshness_source_blocked",
        "freshness_statement_changed", "freshness_unresolved", "malformed_output_exhausted",
        "ordinary_retry_completion_missing", "ordinary_retry_output_changed", "ordinary_retry_state_invalid",
        "owner_invalid_answer", "stress_category_output_changed", "stress_category_state_invalid",
        "stress_publication_configuration_missing", "stress_publication_not_quiescent", "stress_review_unresolved",
        "stress_validation_exhausted",
        # card stops written after the step's calls ended
        "infrastructure_exhausted", "runner_error", "seal_error",
        # the ledger's live states, not failures
        "running", "complete")),
    # -- the case's money, spanning every call --
    **_stops(CASE_SCOPE, ("cost_limit", "total_call_limit", "budget_exhausted")),
    # -- a ledger the factory can no longer trust: usage, reservations or waste it cannot account for --
    **_stops(CASE_SCOPE, (
        "Invalid budget ledger; no process started", "invalid_money", "invalid_operation", "invalid_provider_wait",
        "invalid_usage_binding", "invalid_usage_event", "invalid_usage_price", "invalid_usage_receipt",
        "invalid_waste_attribution", "ordinary_limit_unknown", "reservation_already_invoked",
        "reservation_event_missing", "reservation_mismatch", "reservation_spend_unknown", "resume_while_active",
        "usage_event_conflict", "usage_event_missing", "usage_event_shared", "usage_receipt_regressed",
        "usage_reservation_missing", "usage_unknown", "wait_receipt_mismatch", "waste_attribution_mismatch",
        "waste_operations_pending")),
    # -- a process that may have outlived its call must block the next admission (cleanup_failed: a failed
    # pkill or scratch removal after the call) --
    **_stops(CASE_SCOPE, ("cancellation_failed", "containment_unavailable", "cleanup_failed")),
    # -- the operator, or the process itself, is stopping: every call goes --
    **_stops(CASE_SCOPE, ("paused", "PauseRequested", "KeyboardInterrupt", "SystemExit", "provider_wait_deadline")),
}
_UNLISTED_LABEL = {"scope": CASE_SCOPE, "reroute": None}
_UNLISTED_EXCEPTION = {"scope": CALL_SCOPE, "reroute": None}


def stop(label: str, exception: bool = False) -> dict:
    """The STOPS entry of a stop label, by its head; `exception` when the label is an exception's class name. A
    wrapped label ("Budget ledger stopped: X", raised when another call already stopped the ledger) is not X and
    has no entry: like any unlisted label it stops the case and takes no next route."""
    return STOPS.get(label.partition(":")[0], _UNLISTED_EXCEPTION if exception else _UNLISTED_LABEL)


# ---- audit (pure) ---------------------------------------------------------------------------

def audit(rows: Iterable[dict], commits: dict, contains: Optional[Callable[[str, str], Optional[bool]]],
          registry: dict = REGISTRY) -> dict:
    """rows: {case_id, batch_id, seq, attempt, plumbing_version, outcome, reason}. commits: plumbing_version ->
    source commit (or absent). contains(commit, fix) -> True/False, or None when it cannot tell.
    Rows are deduped by (case, batch, seq, attempt). A bug seen on a release whose commit contains its
    fix is a regression; one whose release commit or ancestry is unknown is unchecked, never a regression;
    one on a release from before its fix is not reported."""
    seen, releases, hits = set(), {}, {}
    for r in rows:
        key = (r["case_id"], r["batch_id"], r["seq"], r["attempt"])
        if key in seen:
            continue
        seen.add(key)
        pv = r["plumbing_version"]
        rel = releases.setdefault(pv, {"commit": commits.get(pv), "attempts": 0, "infra": 0})
        rel["attempts"] += 1
        rel["infra"] += r.get("outcome") == "infra_error"
        hit = hits.setdefault((r["reason"], pv), {"count": 0, "cases": set()})
        hit["count"] += 1
        hit["cases"].add(r["case_id"])
    out = {"regression": [], "open": [], "unknown": [], "unchecked": [], "releases": releases}
    for (reason, pv), hit in sorted(hits.items()):
        entry = lookup(reason, registry)
        row = {"reason": reason, "release": pv, "commit": commits.get(pv), "count": hit["count"],
               "cases": sorted(hit["cases"])}
        if entry is None:
            out["unknown"].append(row)
        elif entry["kind"] != "bug":
            continue
        elif entry["fixed_in"] is None:
            out["open"].append(row)
        else:
            row.update(fixed_in=entry["fixed_in"], test=entry["test"])
            has = None if row["commit"] is None or contains is None else _all(
                contains(row["commit"], fix) for fix in entry["fixed_in"])
            if has is not False:   # False: a release from before the fix, expected to show the bug
                out["regression" if has else "unchecked"].append(row)
    return out


def _all(answers) -> Optional[bool]:
    """True when every fix is in the release, False when any is not, None when git cannot tell."""
    answers = list(answers)
    return False if False in answers else None if None in answers else True


def render(report: dict) -> list:
    """One text line per finding, then one per release."""
    short = lambda v: (v or "?")[:12]
    lines = []
    for label in ("regression", "unknown", "unchecked", "open"):
        for r in report[label]:
            extra = f" fixed_in {','.join(map(short, r['fixed_in']))} test {r['test']}" if "fixed_in" in r else ""
            lines.append(f"{label.upper():<10} {r['reason']:<40} {r['count']:>4}x release {short(r['release'])} "
                         f"(commit {short(r['commit'])}) {len(r['cases'])} cases{extra}")
    for pv, rel in sorted(report["releases"].items(), key=lambda kv: kv[0] or ""):
        lines.append(f"RELEASE    {short(pv)} commit {short(rel['commit'])}: {rel['attempts']} attempts, "
                     f"{rel['infra']} infra stops")
    return lines


def result(report: dict, undecodable: int, now: float, violations: Iterable = ()) -> dict:
    """What bin/stop_audit --write records for the campaign guard (durable/guard.stop_audit_alerts).
    violations: (check, line) pairs from `invariants`."""
    lines = render(report)
    violations = list(violations)
    return {"written_at": now,
            "invariant": [line for _, line in violations],
            "invariant_reasons": sorted({check for check, _ in violations}),
            "counts": {"attempts": sum(r["attempts"] for r in report["releases"].values()),
                       "undecodable": undecodable, "invariant": len(violations), **{k: len(report[k]) for k in
                                                      ("regression", "unknown", "unchecked", "open")}},
            "regression": [l for l in lines if l.startswith("REGRESSION")],
            "unknown": [l for l in lines if l.startswith("UNKNOWN")],
            "regression_reasons": sorted({r["reason"] for r in report["regression"]}),
            "unknown_reasons": sorted({r["reason"] for r in report["unknown"]})}


# ---- invariants (pure) ----------------------------------------------------------------------

# No "case stuck" check: a quiet case is normal while a provider wait sleeps to its retry_at (up to
# 8 days, status still running) or a long step runs inside its deadline (4 h, 12 h for GATES). A stuck
# check needs each attempt's step deadline and retry_at, which this audit does not read yet.


def invariants(attempts: Iterable[dict], ledger: Optional[dict], budgets: Optional[dict]) -> list:
    """(check, line) for every violation of the live money and record invariants.
    attempts: decoded step attempts, not deduped. ledger: idempotency_key -> {state, waste, rebooked,
    draws_case_money, paid, granted} (durable_ledger_attempt). budgets: batch -> {bound, held, spent, waste}
    (SqlLedger._batch_sums). A section that could not be read is None, and only its checks are skipped."""
    out, results = [], {}
    for a in attempts:
        # The ledger key names the step: a factory_bug rerun in place (Engine.rerun_after_release) gives
        # the step after a diagnosis the diagnosis's seq, so seq and attempt alone are not one attempt
        # (1bb2ad 16 November: diagnosis/1 and writer:4/1 both at seq 8 attempt 1).
        ident = (a["case_id"], a["batch_id"], a["key"])
        results.setdefault(ident, {})[(a["outcome"], a["reason"], a["paid_usd_micros"])] = a
    for (case, batch, key), seen in sorted(results.items(), key=lambda kv: str(kv[0])):
        where = f"{batch} {key}"
        if len(seen) > 1:   # one attempt, two different recorded results
            out.append(("attempt_recorded_twice", f"INVARIANT  attempt_recorded_twice  {where}: "
                        + "; ".join(f"{o} {r} paid {p}" for o, r, p in sorted(seen, key=str))))
        if ledger is None:
            continue
        a = next(iter(seen.values()))
        row = ledger.get(a["key"])
        if row is None:
            if a["paid_usd_micros"] > 0:
                out.append(("spend_below_usage", f"INVARIANT  spend_below_usage  {where}: no ledger row, "
                            f"reported paid {a['paid_usd_micros']}"))
            continue
        if row["state"] == "held":
            continue   # not settled yet
        booked = row["granted"] if row["state"] == "lost" else row["paid"]
        if booked < a["paid_usd_micros"]:   # booked spend covers the paid usage the result reported
            out.append(("spend_below_usage", f"INVARIANT  spend_below_usage  {where}: booked {booked} "
                        f"< reported paid {a['paid_usd_micros']}"))
        if (a["settles_as_waste"] and row["draws_case_money"] and row["state"] == "settled"
                and not row["waste"] and not row["rebooked"] and row["paid"] > 0):   # waste on case money
            out.append(("waste_on_case_money", f"INVARIANT  waste_on_case_money  {where}: {a['reason']} "
                        f"paid {row['paid']} booked to the case"))
    for batch, b in sorted((budgets or {}).items()):
        if b["held"] + b["spent"] > b["bound"]:   # the ledger's own rule: used = held + spent, within the bound
            out.append(("batch_over_bound", f"INVARIANT  batch_over_bound  {batch}: held {b['held']} + spent "
                        f"{b['spent']} > bound {b['bound']}"))
    return out


# ---- readers --------------------------------------------------------------------------------

class _Builtins(pickle.Unpickler):
    """Dicts, lists, tuples, strings, numbers, booleans and None need no class lookup: refuse every class."""
    def find_class(self, module, name):
        raise pickle.UnpicklingError(f"refused {module}.{name}")


UNDECODABLE = object()


def decode(output: str, row_time: Optional[float] = None):
    """One DBOS.getResult output (base64 pickle) as an attempt row; None if it is not a step attempt;
    UNDECODABLE if it is not base64 or pickles anything but builtins. started_at falls back to row_time."""
    try:
        value = _Builtins(io.BytesIO(base64.b64decode(output, validate=True))).load()
    except Exception:
        return UNDECODABLE
    if not isinstance(value, dict) or not isinstance(value.get("input"), dict) or not isinstance(value.get("result"), dict):
        return None
    si, res = value["input"], value["result"]
    if not isinstance(res.get("reason"), str):
        return None
    started = value.get("started_at")
    step = si.get("step") if isinstance(si.get("step"), dict) else {}
    usage = res.get("usage") if isinstance(res.get("usage"), dict) else {}
    paid = usage.get("paid_usd_micros") if type(usage.get("paid_usd_micros")) is int else 0
    return {**{k: si.get(k) for k in ("case_id", "batch_id", "seq", "attempt", "plumbing_version")},
            "outcome": res.get("outcome"), "reason": res["reason"],
            "started_at": started if isinstance(started, (int, float)) else row_time,
            # contract.StepInput.idempotency_key: the ledger's key for this attempt
            "key": f"{si.get('case_id')}/{si.get('seq')}/"
                   f"{step.get('kind')}{':' + str(step['round']) if step.get('round') else ''}/{si.get('attempt')}",
            "paid_usd_micros": paid,
            # The ledger's own rule. credit_park: a row recorded before that patch was booked as waste,
            # and the check this feeds only looks at rows booked to the case.
            "settles_as_waste": settles_as_waste(SimpleNamespace(
                outcome=next((o for o in Outcome if o.value == res.get("outcome")), None), reason=res["reason"],
                usage=SimpleNamespace(paid_usd_micros=paid)), credit_park=True)}


def read_attempts(database_url: str, since: Optional[float] = None) -> tuple:
    """(attempt rows, undecodable count) from one bounded, read-only transaction. With `since`, SQL keeps
    rows whose completed_at_epoch_ms is in the window (a plain range, so an index applies); rows with no
    completed_at (written before DBOS recorded it) are dropped, not scanned. Then attempts that started
    before `since` are dropped too."""
    import sqlalchemy as sa
    url = sa.engine.make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    engine = sa.create_engine(url, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SET TRANSACTION READ ONLY"))
            conn.execute(sa.text("SET LOCAL statement_timeout = '30s'"))
            window = "" if since is None else " AND completed_at_epoch_ms >= :since_ms"
            found = conn.execute(sa.text(
                "SELECT output, completed_at_epoch_ms / 1000.0 FROM dbos.operation_outputs "
                "WHERE function_name = 'DBOS.getResult' AND workflow_uuid LIKE 'case-%@%' "
                "AND output IS NOT NULL" + window),
                {} if since is None else {"since_ms": int(since * 1000)}).all()
    finally:
        engine.dispose()
    decoded = [decode(output, None if at is None else float(at)) for output, at in found]
    rows = [r for r in decoded if isinstance(r, dict)
            and (since is None or r["started_at"] is None or r["started_at"] >= since)]
    return rows, sum(r is UNDECODABLE for r in decoded)


def _bounded(config: dict, read: Callable):
    """read(conn) in one read-only ledger transaction whose statements the server cancels after 30 s, so a
    client killed by the unit's 120 s cap leaves nothing running there."""
    import sqlalchemy as sa
    from durable.observation import readonly, readonly_engine
    engine = readonly_engine(config)
    try:
        with engine.connect() as conn:
            conn = readonly(conn)
            with conn.begin():
                if conn.dialect.name == "postgresql":
                    conn.execute(sa.text("SET LOCAL statement_timeout = '30s'"))
                    conn.execute(sa.text("SET LOCAL idle_in_transaction_session_timeout = '60s'"))
                return read(conn)
    finally:
        engine.dispose()


def read_ledger(config: dict) -> dict:
    """idempotency_key -> the attempt's booking (durable_ledger_attempt, plus whether it was rebooked as waste)."""
    import sqlalchemy as sa
    from durable.ledger import ATTEMPTS, REBOOKED
    a = ATTEMPTS.c

    def read(conn):
        rebooked = set(conn.execute(sa.select(REBOOKED.c.idempotency_key)).scalars())
        return {r.idempotency_key: {"state": r.state, "waste": r.waste, "rebooked": r.idempotency_key in rebooked,
                                    "draws_case_money": r.draws_case_money, "paid": int(r.paid_usd_micros),
                                    "granted": int(r.granted_usd_micros)}
                for r in conn.execute(sa.select(a.idempotency_key, a.state, a.waste, a.draws_case_money,
                                                a.paid_usd_micros, a.granted_usd_micros))}
    return _bounded(config, read)


def read_budgets(config: dict) -> dict:
    """batch -> {bound, held, spent, waste}: the ledger's own sums (SqlLedger._batch_sums), as observation._budget."""
    import sqlalchemy as sa
    from durable.ledger import BATCHES, SqlLedger

    def read(conn):
        out = {}
        for batch, bound in conn.execute(sa.select(BATCHES.c.batch_id, BATCHES.c.bound_usd_micros)):
            held, spent, waste = SqlLedger._batch_sums(conn, batch)
            out[batch] = {"bound": int(bound), "held": held, "spent": spent, "waste": waste}
        return out
    return _bounded(config, read)


def release_commits(work: Optional[Path], release_map: Optional[Path] = None) -> dict:
    """plumbing_version -> commit, from the release store's map (state/releases/release-commits.json, written
    by `workers.py release` given --commit or a COMMIT file) and from control/release.py build-plumbing
    records (<work>/plumbing-*/state.json)."""
    out = {}
    try:
        known = json.loads(Path(release_map).read_text()) if release_map is not None else {}
        out.update({k: v for k, v in known.items() if isinstance(k, str) and isinstance(v, str)})
    except (OSError, ValueError, AttributeError):
        pass   # no map yet, or an unreadable one: those releases read as commit ?
    if work is None:
        return out
    for path in sorted(Path(work).glob("plumbing-*/state.json")):
        try:
            state = json.loads(path.read_text())
            out[state["plumbing_version"]] = state["commit"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def git_contains(repo: Path) -> Callable[[str, str], Optional[bool]]:
    """contains(commit, fix): whether fix is an ancestor of commit in repo; None when git cannot tell.
    Local objects only (no fetch, no lazy fetch) and bounded, so a bad repo never hangs the audit."""
    cache = {}
    env = {**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}

    def contains(commit: str, fix: str) -> Optional[bool]:
        if (commit, fix) not in cache:
            try:
                # safe.directory: the checkout may belong to another user.
                code = subprocess.run(["git", "-c", f"safe.directory={repo}", "-c", "protocol.allow=never",
                                       "-C", str(repo), "merge-base", "--is-ancestor", fix, commit],
                                      capture_output=True, env=env, timeout=20).returncode
            except (OSError, subprocess.TimeoutExpired):
                code = None
            cache[commit, fix] = {0: True, 1: False}.get(code)
        return cache[commit, fix]
    return contains


__all__ = ["REGISTRY", "PREFIXES", "lookup", "STOPS", "stop", "audit", "render", "result", "invariants", "decode", "read_attempts",
           "read_ledger", "read_budgets",
           "release_commits", "git_contains"]
