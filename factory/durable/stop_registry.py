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

`audit` is pure: attempt rows in, verdicts out. bin/stop_audit and the campaign guard both use it;
`read_attempts` and `release_commits` are the thin readers around it.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import pickle
import subprocess
from typing import Callable, Iterable, Optional

from durable.classify import (CLEANUP_ERRORS, CLEANUP_STAGES, IMPORT_REASONS, PREFLIGHT_ROLES, PREFLIGHT_STOPS,
                              REJECTION_REASONS, _CASE_LIMIT, _STEP_STAGE)

CASE, WAIT = {"kind": "case"}, {"kind": "wait"}


def bug(*fixed_in: str, test: Optional[str] = None) -> dict:
    return {"kind": "bug", "fixed_in": fixed_in or None, "test": test}


OPEN = bug()

REGISTRY = {
    # -- case outcomes --
    "admit:selected": CASE, "admit:practice": CASE, "admit:conflict": CASE, "admit:board_planned": CASE,
    "admit:imported_sealed": CASE, "admit:imported_written": CASE,
    "writer:validated": CASE, "writer:practice": CASE, "writer:invalid_practice": CASE, "writer:handback": CASE,
    "writer:rounds_exhausted": CASE, "writer:unchanged_repair": CASE, "writer:output_capped": CASE,
    "stress:clean": CASE, "stress:findings": CASE, "stress:public_match": CASE, "stress:practice": CASE,
    "engine:gates_passed": CASE, "g5:reference_unsolved": CASE, "g8:no_eligible_reviewer": CASE,
    "diagnosis:completed": CASE, "seal:sealed": CASE,
    # -- waits: provider limits, campaign worker limits, operator waits and the batch clock --
    "router:quota": WAIT, "router:rate": WAIT, "router:capacity": WAIT, "router:credit": WAIT,
    "router:provider_wait": WAIT, "router:provider_limit": WAIT, "router:claude_limit": WAIT,
    "router:codex_limit": WAIT, "router:opencode_limit": WAIT, "router:openrouter_limit": WAIT,
    "router:outage": WAIT, "router:credential_expiring": WAIT, "infra:credentials_unavailable": WAIT,
    "infra:worker_slots_full": WAIT, "infra:worker_start_rate": WAIT, "infra:paused": WAIT,
    "infra:campaign_deadline": WAIT,
    # -- factory bugs with a fix on main (fixes on parallel branches are all listed) --
    # 97d97b84: a writer-round case's diagnosis read a stress report that did not exist yet.
    "diagnosis:processing_failed": bug("97d97b84d73135b916ebcc78c734715052cf755d", test=
        "tests/factory/test_durable_diagnosis.py::DiagnosisTests::"
        "test_a_close_verdict_on_a_case_stopped_in_a_writer_round_gives_feedback"),
    # 0f818fe5: the diagnosis prompt carried the full inventory past Linux's one-argument limit.
    "infra:prompt_too_large": bug("0f818fe5783950ec591cf6b24a93ef5807b948f6", test=
        "tests/factory/test_model_call_maxima.py::MaximaTests::"
        "test_factory_dispatch_preserves_lease_maximum_gate_and_invocation_identity"),
    # aeabd48d: strategy calls broke on pinned worker bench images; 1d52c92d preflights the release pair.
    "infra:runner_exception": bug("aeabd48dadb3f057fd6670f9fc9507d7376cbad1",
                                  "1d52c92d7c196dadbe09bec2414782a94a3e4417", test=
        "tests/factory/test_strategy_reuse.py::StrategyPrefixRecoveryTests::"
        "test_pinned_worker_strategy_before_sharing_still_runs"),
    # 2fcbaf66: writer findings handed to a fresh attempt instead of a cycle doomed to hit the deadline;
    # 5694aea3: a deadline kill seals its diagnostic.
    "infra:deadline": bug("2fcbaf669024fde16c7523a968f61abadbe27dea",
                          "5694aea3968ced5844d6a67ed0e1db5cae75470e", test=
        "tests/factory/test_stress_loop.py::StressLoopTests::"
        "test_writer_hands_back_findings_instead_of_starting_a_doomed_cycle"),
    # b58ea3ec, the latest of fe112d74, fa92e2eb, 956c9fa4: pilot homes removed in their own window.
    "infra:diagnosis_cleanup_failed": bug("b58ea3ec6057c40f25f16c14eb55bc9de5a5d2e2", test=
        "tests/factory/test_pilot_home_teardown.py::PilotHomeTeardown::"
        "test_a_diagnosis_teardown_timeout_keeps_its_cause"),
    # 8d1093d4: a silent writer route fails fast instead of stalling.
    "infra:stalled": bug("8d1093d46b0f9028d048e680427cd4095d237bd2", test=
        "tests/factory/test_silent_writer_route.py::SilentWriterRoute::"
        "test_a_stalled_selection_call_moves_to_the_next_route"),
    # 874b2727 (after f0f6e4e3, 0c2b545b): a live slot's seed IDs and a rebuilt slot's infra allowance.
    # The gather class is still being fixed on fix/gather-live-slot-state.
    "infra:execution_retries_exhausted": bug("874b2727a4b52d2d2d34c3908bf08a271ed4ea21", test=
        "tests/factory/test_live_slot_fixture.py::LiveSlotFixtureTests::"
        "test_rebuilt_slot_gets_a_fresh_infra_allowance"),
    # f2c9199a: unknown code stops name themselves (infra:raw_<label>); only free text is left here.
    "infra:unclassified_stop": bug("f2c9199aebed5ccb881b26a59d607f7adccc2544", test=
        "tests/factory/test_durable_classify.py::SelfNamingStops::test_unknown_identifier_stops_name_themselves"),
    # -- factory bugs, open or in flight --
    "infra:cancelled": OPEN,                        # in flight: fix/probe-cap-no-shared-stop
    "admit:processing_failed": OPEN,                # in flight: fix/reviewer2-preflight-role
    "infra:freshness_evidence_unavailable": OPEN,   # in flight: fix/freshness-expired-refetch
    "infra:diagnosis_result_invalid": OPEN,         # in flight: fix/sweep-leftovers
    "infra:pool_failed": OPEN,   # several causes; 6ea112d fixed one (bounded_create arity)
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
        entry = registry.get(reason)
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


def alerts(report: dict) -> dict:
    """At most one guard alert: the regressed and unknown reasons, keyed by them so a new one alerts again."""
    regressed = sorted({r["reason"] for r in report["regression"]})
    unknown = sorted({r["reason"] for r in report["unknown"]})
    if not regressed and not unknown:
        return {}
    parts = ([f"fixed bugs came back: {', '.join(regressed)}"] if regressed else []) + \
            ([f"unclassified stops: {', '.join(unknown)}"] if unknown else [])
    return {"stop_audit:" + ",".join(regressed + unknown): "Stop audit: " + "; ".join(parts) + ". Run bin/stop_audit."}


# ---- readers --------------------------------------------------------------------------------

def decode(output: str) -> Optional[dict]:
    """One DBOS.getResult output (base64 pickle) as an attempt row, or None if it is not a step attempt."""
    value = pickle.loads(base64.b64decode(output))   # our own DBOS database; DBOS itself reads it so
    if not isinstance(value, dict) or not isinstance(value.get("input"), dict) or not isinstance(value.get("result"), dict):
        return None
    si, result = value["input"], value["result"]
    if not isinstance(result.get("reason"), str):
        return None
    return {**{k: si.get(k) for k in ("case_id", "batch_id", "seq", "attempt", "plumbing_version")},
            "outcome": result.get("outcome"), "reason": result["reason"], "started_at": value.get("started_at")}


def read_attempts(database_url: str) -> list:
    """Every recorded step attempt, in one read-only transaction."""
    import sqlalchemy as sa
    url = sa.engine.make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SET TRANSACTION READ ONLY"))
            outputs = conn.execute(sa.text(
                "SELECT output FROM dbos.operation_outputs WHERE function_name = 'DBOS.getResult' "
                "AND workflow_uuid LIKE 'case-%@%' AND output IS NOT NULL")).scalars().all()
    finally:
        engine.dispose()
    return [row for row in map(decode, outputs) if row is not None]


def release_commits(work: Optional[Path], release_map: Optional[Path] = None) -> dict:
    """plumbing_version -> commit, from the release store's map (state/releases/release-commits.json, written
    by `workers.py release` given --commit or a COMMIT file) and from control/release.py build-plumbing
    records (<work>/plumbing-*/state.json)."""
    out = {}
    if release_map is not None and Path(release_map).is_file():
        out.update(json.loads(Path(release_map).read_text()))
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
    """contains(commit, fix): whether fix is an ancestor of commit in repo; None when git cannot tell."""
    cache = {}

    def contains(commit: str, fix: str) -> Optional[bool]:
        if (commit, fix) not in cache:
            # safe.directory: the guard runs as root over the operator's checkout.
            code = subprocess.run(["git", "-c", f"safe.directory={repo}", "-C", str(repo), "merge-base", "--is-ancestor", fix, commit],
                                  capture_output=True).returncode
            cache[commit, fix] = {0: True, 1: False}.get(code)
        return cache[commit, fix]
    return contains


__all__ = ["REGISTRY", "audit", "alerts", "decode", "read_attempts", "release_commits", "git_contains"]
