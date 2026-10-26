"""Pure metadata migrations and allowance projections. No archive or secret access.

Legacy observations are evidence about old code, never a new allowance. Refused
continuations retain their monetary summary and explicit missing-history reasons.
The worker restore integration is deliberately separate from this pure boundary.
"""
import copy
import hashlib
import json
import math
import re

from budget import case_spending

STATE_VERSION = 2
GATES = ("G1", "G2", "G3", "G4", "G5", "G16", "G8", "G9", "G6", "G13", "G14", "G15", "G7", "G10", "G17", "G11", "G12")
FACTS = frozenset("""
case source seed dry_run rotation_slot models roles models_used model kind verdict
status terminal_stop failed_gate failed_detail gates gate_results early_gates counts
cheats_passed fake_pass fix_verdicts plain_app_broke reference_fix scenario_keys_match
negative_probes_ok reviewers_fairness reviewers_realism difficulty calibrators
calibration_progress calibration_interruptions early_probe strategy_reuse flakiness_rerun
stress_review admission admission_freshness selection_board rejected_candidates dedup
dedup_skipped idea_realism public_search prototype freshness_repair freshness_reverify
freshness_confirmation freshness_topup loop_freshness repair_blocked builder_note
build_deferred budget_raised rounds_raised recovery_config limits restore_adjustment
resume_rereview salvaged_from kept_from_previous_run kept_gate_source free_model_fallback
model_transition provider_routes provider_preflight driver_qualification audit_source
audit_inputs_sha256 source_inputs_sha256 review_bench_sha256 digest_version inputs_unchanged
audit_runtime_preparation delivery_provenance owner_contract archive sha256 r2_object
statement_sha256 statement_cipher_sha256 durable_checkpoint dry_run_roundtrip wall_minutes
gate_minutes error checkpoint_error public_progress_error wipe calls_delta cost_delta
audit_calls_total audit_cost_total continuations continuation_budget
""".split())
DERIVED = frozenset("builder_rounds candidate_attempts repairs case_budget".split())
VOLATILE = frozenset("resume bench_workers_effective factory_slots_prepared".split())
OPERATIONS = {"freshness_repair": 2, "rereview": 2, "round": 8, "repair": 2,
              "prototype": 2, "candidate": 3, "diagnostic": 1}
INFRASTRUCTURE_LIMIT = 8  # finite across carry-overs; never refreshed by a new release


class Refused(ValueError):
    """A metadata-only, non-sensitive reason suitable for a public corpus report."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def classification():
    return {"durable": sorted(FACTS), "derived": sorted(DERIVED), "volatile": sorted(VOLATILE)}


def usage_facts(ledger):
    """Validate before using the older accounting reader; never turn bad data into zero.

    Historical totals without per-turn events are immutable unattributed facts.
    This is the only legacy remainder, never an imported allowance/call cap.
    """
    require(isinstance(ledger, dict), "missing or invalid usage ledger")
    events = ledger.get("events")
    require(isinstance(events, list), "missing usage events")
    identities = set()
    observed = dict.fromkeys(("cost", "list_cost_usd", "estimated_subscription_cost_usd", "calls"), 0)
    for event in events:
        require(isinstance(event, dict), "invalid usage event")
        identity = event.get("id")
        require(isinstance(identity, str) and identity and identity not in identities,
                "missing or duplicate usage event id")
        identities.add(identity)
        for key in observed:
            value = event.get(key, 1 if key == "calls" else 0)
            require(number(value) and (key != "calls" or type(value) is int), "invalid usage event amount")
            observed[key] += value
    remainder = {}
    for key, value in observed.items():
        total = ledger.get(key, value)
        require(number(total) and (key != "calls" or type(total) is int), "invalid usage total")
        # Some historical streaming events represent several calls; conversely a
        # Codex result has calls=0. Refuse inconsistent totals, don't drop events.
        if key != "calls":
            require(total + 1e-8 >= value, "usage total below recorded events")
        remainder[key] = max(0, total - value)
    for key in ("infrastructure_waste", "unpriced_invocations", "resolved_unpriced_invocations"):
        require(isinstance(ledger.get(key, []), list) and
                all(isinstance(v, dict) for v in ledger.get(key, [])), "invalid " + key)
    waste_ids = [r.get("id") for r in ledger.get("infrastructure_waste", [])]
    require(all(isinstance(i, str) and i for i in waste_ids) and len(waste_ids) == len(set(waste_ids)),
            "missing or duplicate infrastructure waste id")
    durable = {k: copy.deepcopy(v) for k, v in ledger.items() if k not in ("active", "zero_token_streak")}
    require(isinstance(ledger.get("active", []), list) and
            all(isinstance(v, str) and v for v in ledger.get("active", [])), "invalid active invocation metadata")
    if ledger.get("active") or ledger.get("terminal_stop") == "running":
        marker = {"role": "legacy_unfinished", "model": ledger.get("configured_model", "unknown"),
                  "reason": "active or running at checkpoint; usage not reconciled"}
        unpriced = durable.setdefault("unpriced_invocations", [])
        if marker not in unpriced: unpriced.append(marker)
    return {"ledger": durable, "legacy_remainder": remainder,
            "calls": max(observed["calls"], ledger.get("calls", observed["calls"]))}


def v0_to_v1(card):
    """Split observations from projections without fabricating a retry history."""
    require(isinstance(card, dict), "scorecard is not an object")
    unknown = set(card) - FACTS - DERIVED - VOLATILE - {"state_version"}
    require(not unknown, "unclassified scorecard fields: " + ", ".join(sorted(unknown)))
    require(isinstance(card.get("case"), str) and re.fullmatch(r"(?:g11-review-)?case-[A-Za-z0-9-]+", card["case"]),
            "missing or invalid case identity")
    observations = {k: copy.deepcopy(v) for k, v in card.items() if k in FACTS}
    usage = usage_facts(card.get("continuation_budget"))
    observations["continuation_budget"] = copy.deepcopy(usage["ledger"])
    return {"state_version": 1, "case": card["case"],
            "artifacts": {"scorecard": observations, "legacy_derived": {
                k: copy.deepcopy(v) for k, v in card.items() if k in DERIVED},
                "source_sha256": digest(card), "source_fields": sorted(card),
                "dropped_volatile": sorted(set(card) & VOLATILE),
                "dropped_volatile_nested": ["continuation_budget." + k for k in ("active", "zero_token_streak")
                    if k in card["continuation_budget"]], "usage": usage},
            "events": [], "unresolved": ["legacy checkpoint has no attempt/cause event history"]}


def v1_to_v2(state):
    """Normalize historical budget facts into append-only events, once only."""
    require(state.get("state_version") == 1, "expected state version 1")
    result = copy.deepcopy(state)
    require(isinstance(result.get("unresolved"), list) and
            all(isinstance(v, str) for v in result["unresolved"]), "invalid missing-history reasons")
    reason = "legacy checkpoint has no attempt/cause event history"
    if reason not in result["unresolved"]: result["unresolved"].append(reason)
    require(isinstance(result.get("events"), list) and not result["events"], "v1 events already populated")
    try:
        usage = usage_facts(result["artifacts"]["usage"]["ledger"])
        result["artifacts"]["usage"] = usage
        ledger = usage["ledger"]
        result["artifacts"]["scorecard"]["continuation_budget"] = copy.deepcopy(ledger)
        summary = case_spending(ledger, result["artifacts"]["scorecard"].get("models_used"))
    except (KeyError, TypeError, AttributeError, OverflowError):
        raise Refused("invalid legacy accounting facts") from None
    # Existing validated resolutions remain explicit; a timeout alone never
    # resolves unpriced usage. No per-case special cases or one-time resets.
    for index, (kind, amount) in enumerate((("usage", summary.get("spent_usd", 0)),
                                           ("waste", summary["infrastructure_waste_usd"]))):
        if amount is None: amount = summary.get("known_spent_usd", 0)
        result["events"].append({"id": f"legacy-{index}", "kind": kind, "actor": "legacy-import",
            "reason": "preserved recorded usage" if kind == "usage" else "preserved evidenced infrastructure waste",
            "cause": "unknown" if kind == "usage" else "infrastructure", "amount": amount,
            "evidence": digest(ledger), **({"calls": usage_facts(ledger)["calls"]} if kind == "usage" else {})})
    config = result["artifacts"]["scorecard"].get("recovery_config", {})
    if isinstance(config, dict) and "case_budget" in config and "rounds" in config:
        result["events"].append({"id": "legacy-limits", "kind": "limits", "actor": "legacy-import",
            "cause": "infrastructure", "reason": "preserved authorized configuration",
            "budget": config["case_budget"], "caps": {**OPERATIONS, "round": config["rounds"],
                "repair": config.get("max_repairs", 2)}, "infrastructure_limit": INFRASTRUCTURE_LIMIT})
    if summary.get("spent_usd") is None:
        result["events"].append({"id": "legacy-unknown", "kind": "unknown_usage", "actor": "legacy-import",
            "cause": "unknown", "reason": "unpriced or invalid recorded usage", "evidence": digest(ledger)})
    result["state_version"] = 2
    return result


MIGRATIONS = {0: v0_to_v1, 1: v1_to_v2}


def new_state(case, *, budget=50, rounds=8, repairs=2):
    """A genuinely new case has no missing historical attempts."""
    state = {"state_version": STATE_VERSION, "case": case, "artifacts": {}, "events": [], "unresolved": []}
    return append(state, kind="limits", actor="founder", cause="infrastructure", reason="authorized case limits",
                  budget=budget, caps={**OPERATIONS, "round": rounds, "repair": repairs},
                  infrastructure_limit=INFRASTRUCTURE_LIMIT)


def project(state):
    """The single allowance state machine used by admission and the model check.

    Pending starts reserve execution, never debit case allowances. A result
    debits only a case-caused completed/failed attempt; infrastructure results
    use their own finite bound. Unknown cause/usage blocks all execution.
    """
    caps, budget_limit, infrastructure_limit = dict(OPERATIONS), None, INFRASTRUCTURE_LIMIT
    pending, attempts, seen, gates, bindings = {}, {}, set(), {}, {}
    used, infrastructure, release_reviews = {}, 0, []
    case_spent = waste = 0.0
    calls = 0
    unknown_usage, sealed = False, False
    for event in state["events"]:
        require(isinstance(event, dict), "event is not an object")
        require(not sealed, "event after seal")
        identity = event.get("id")
        require(isinstance(identity, str) and identity and identity not in seen, "missing or duplicate event id")
        seen.add(identity)
        require(all(isinstance(event.get(k), str) and event[k] for k in ("actor", "reason")), "event missing actor or reason")
        require(event.get("cause") in ("case", "infrastructure", "unknown"), "invalid stop cause")
        kind = event.get("kind")
        if kind == "limits":
            require(not attempts, "limits cannot change after attempts")
            budget_limit = event.get("budget")
            require(number(budget_limit) and budget_limit > 0, "invalid budget limit")
            require(set(event.get("caps", {})) == set(OPERATIONS), "missing operation caps")
            caps = dict(event["caps"])
            require(all(type(v) is int and v >= 0 for v in caps.values()), "invalid operation cap")
            infrastructure_limit = event.get("infrastructure_limit")
            require(type(infrastructure_limit) is int and infrastructure_limit > 0, "invalid infrastructure bound")
        elif kind in ("usage", "waste"):
            amount = event.get("amount")
            require(number(amount) and isinstance(event.get("evidence"), str) and event["evidence"], "invalid monetary fact")
            if kind == "usage":
                call_count = event.get("calls", 0)
                require(type(call_count) is int and call_count >= 0, "invalid usage call count")
                calls += call_count
                case_spent += amount
            else:
                require(event["cause"] == "infrastructure", "waste must have infrastructure cause")
                waste += amount
        elif kind == "unknown_usage":
            unknown_usage = True
        elif kind == "start":
            operation, scope = event.get("operation"), event.get("scope")
            attempt = event.get("attempt_id")
            require(operation in OPERATIONS and isinstance(scope, str) and scope, "invalid attempt operation/scope")
            if operation in ("rereview", "diagnostic"):
                match = re.fullmatch(r"round-([1-9][0-9]*)", scope)
                require(match is not None and int(match[1]) <= caps["round"], "retry scope outside round bound")
            else:
                require(scope == "case", "operation requires whole-case scope")
            require(isinstance(attempt, str) and attempt and attempt not in attempts, "duplicate attempt")
            require(not unknown_usage and not state["unresolved"] and budget_limit is not None and case_spent < budget_limit,
                    "unknown history/usage or exhausted budget")
            require(not pending, "pending attempt must be resolved before another start")
            require(infrastructure < infrastructure_limit, "infrastructure retry cap exhausted")
            require(event["cause"] != "unknown", "unknown attempt cause")
            key = operation + ":" + scope
            require(event["cause"] == "infrastructure" or used.get(key, 0) < caps[operation], "case allowance exhausted")
            estimate = event.get("estimate", 0)
            require(number(estimate) and case_spent + estimate <= budget_limit, "next attempt budget not admitted")
            if operation == "rereview" and event["cause"] == "infrastructure":
                require(isinstance(event.get("binding"), str) and event["binding"], "release re-review needs a binding")
            attempts[attempt] = pending[attempt] = event
        elif kind == "stop":
            attempt = event.get("attempt_id")
            require(isinstance(attempt, str) and attempt in pending, "stop without pending attempt")
            start = pending.pop(attempt)
            require(event.get("outcome") in ("completed", "failed", "interrupted"), "invalid attempt outcome")
            cause = event["cause"]
            usage_known = event.get("usage_known")
            if usage_known is not True:
                unknown_usage = True
            else:
                require(isinstance(event.get("usage_evidence"), str) and event["usage_evidence"],
                        "known usage needs evidence")
            if cause == "unknown": unknown_usage = True
            elif cause == "infrastructure": infrastructure += 1
            else:
                require(event["outcome"] != "interrupted", "case interruption needs a known outcome")
            # A release-forced call is infrastructure even when it completes.
            # Its findings may cause a later case repair, never a re-review debit.
            effective = "infrastructure" if start["cause"] == "infrastructure" else cause
            if effective == "case":
                key = start["operation"] + ":" + start["scope"]
                used[key] = used.get(key, 0) + 1
                require(used[key] <= caps[start["operation"]], "case allowance exceeded")
            elif effective == "infrastructure" and cause != "infrastructure":
                infrastructure += 1
            if start["operation"] == "rereview" and start["cause"] == "infrastructure":
                release_reviews.append(start["binding"])
        elif kind in ("gate", "invalidate"):
            gate = event.get("gate")
            require(gate in GATES and isinstance(event.get("binding"), str) and event["binding"], "invalid gate binding")
            if kind == "invalidate":
                gates.pop(gate, None)
                bindings.pop(gate, None)
            else:
                require(event.get("verdict") in ("pass", "fail"), "invalid gate verdict")
                gates[gate] = event["verdict"]
                bindings[gate] = event["binding"]
        elif kind == "seal":
            require(not pending and not unknown_usage and not state["unresolved"] and
                    budget_limit is not None and case_spent <= budget_limit and
                    all(gates.get(g) == "pass" for g in GATES) and event.get("bindings") == bindings,
                    "seal requires every current gate binding")
            sealed = True
        else:
            raise Refused("unknown event kind")
    require(infrastructure <= infrastructure_limit, "infrastructure allowance exceeded")
    return {"used": used, "caps": caps, "calls": calls, "allowances_known": not state["unresolved"], "pending": sorted(pending),
            "infrastructure_attempts": infrastructure, "infrastructure_remaining": infrastructure_limit - infrastructure,
            "release_rereviews": release_reviews, "case_spent_usd": None if unknown_usage else round(case_spent, 9),
            "known_case_spent_usd": round(case_spent, 9), "infrastructure_waste_usd": round(waste, 9),
            "budget_limit_usd": budget_limit, "unknown_usage": unknown_usage,
            "gates": gates, "sealed": sealed}


def admission(state, counters):
    reasons = list(state["unresolved"])
    if counters["unknown_usage"]: reasons.append("unknown usage fails closed")
    if counters["pending"]: reasons.append("pending attempt requires worker reconciliation")
    if counters["budget_limit_usd"] is None: reasons.append("no authorized budget/caps event")
    elif counters["case_spent_usd"] is not None and counters["case_spent_usd"] >= counters["budget_limit_usd"]:
        reasons.append("case budget exhausted")
    if not counters["infrastructure_remaining"]: reasons.append("infrastructure retry cap exhausted")
    if counters["sealed"]: reasons.append("already sealed")
    return {"admitted": not reasons, "reasons": reasons}


def load(value):
    """Apply every pure schema step, then recompute (never trust saved projections)."""
    try:
        # Reject NaN, non-JSON values and cycles without ever including contents in errors.
        value = json.loads(json.dumps(value, allow_nan=False))
        require(isinstance(value, dict), "state is not an object")
        version = value.get("state_version", 0)
        require(type(version) is int and 0 <= version <= STATE_VERSION, "unsupported state version")
        while version < STATE_VERSION:
            value = MIGRATIONS[version](value)
            version += 1
            require(value.get("state_version") == version, "migration skipped a version")
        require(set(value) <= {"state_version", "case", "artifacts", "events", "unresolved", "counters", "admission"},
                "unclassified state fields")
        require(isinstance(value.get("case"), str) and value["case"], "missing case identity")
        require(isinstance(value.get("artifacts"), dict) and isinstance(value.get("events"), list) and
                isinstance(value.get("unresolved"), list) and all(isinstance(v, str) for v in value["unresolved"]), "invalid state shape")
        if "legacy_derived" in value["artifacts"]:
            reason = "legacy checkpoint has no attempt/cause event history"
            if reason not in value["unresolved"]: value["unresolved"].append(reason)
            legacy = usage_facts(value["artifacts"]["usage"]["ledger"])
            summary = case_spending(legacy["ledger"])
            known = summary.get("known_spent_usd", summary["spent_usd"])
            require(len(value["events"]) >= 2 and
                    value["events"][0].get("kind") == "usage" and value["events"][0].get("amount") == known and
                    value["events"][1].get("kind") == "waste" and value["events"][1].get("amount") == summary["infrastructure_waste_usd"],
                    "legacy monetary facts disagree with imported events")
            if summary["spent_usd"] is None and not any(e.get("kind") == "unknown_usage" for e in value["events"]):
                value["events"].append({"id": "legacy-unknown-recomputed", "kind": "unknown_usage", "actor": "legacy-import",
                    "cause": "unknown", "reason": "unpriced or unfinished legacy usage", "evidence": digest(legacy["ledger"])})
        value["counters"] = project(value)
        value["admission"] = admission(value, value["counters"])
        return value
    except Refused:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise Refused("malformed state metadata") from None


def append(state, **event):
    """Return a new state; persisted callers atomically publish before execution."""
    result = copy.deepcopy(state)
    event.setdefault("id", "event-" + str(len(result["events"])))
    result["events"].append(event)
    return load(result)
