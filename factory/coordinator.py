#!/usr/bin/env python3
"""Bounded recovery coordinator over the existing unlocked key-holder interface.

`plan` is read-only; `step` reserves durably before requesting one approved launch.
Neither command fetches inventory or credentials. A fresh, complete public inventory
snapshot is required. Unknown launches remain blocked until the holder's existing
verified collected-generation reconciliation proves a successor; worker absence
alone is never a retry authorization. Invoke `step` periodically for each fixed job.
"""
import argparse
import contextlib
import fcntl
import json
import math
import os
import pathlib
import re
import shlex
import time

import key_holder
import restart
from registry import atomic_json

MAX_ACTIONS = 1000
MONITOR = pathlib.Path("results/infrastructure/2026-10-18-claude-return/monitor-state.json")
CONFIG_FIELDS = ("rounds", "case_budget", "runs", "scenario_runs", "pilot_tries", "pilot_runs", "calibrator_minutes",
                 "max_role_calls", "max_total_calls", "max_cost", "no_progress_minutes", "max_zero_tokens", "agent_timeout", "max_repairs")
ROLE_FLAGS = {"writer": "builder", "stress_tester": "attacker", "reviewer": "reviewer1",
              "reviewer2": "reviewer2", "strong_calibrator": "strong-calibrator", "easy_calibrator": "easy-calibrator"}


def read_public(path):
    path = pathlib.Path(path)
    if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024: raise ValueError("invalid public metadata file")
    return json.loads(path.read_text())



def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def roles(value):
    if not isinstance(value, dict) or not value: raise ValueError("missing fixed model roles")
    out = {}
    for role, data in value.items():
        if not isinstance(data, dict) or not isinstance(data.get("model"), str) or not isinstance(data.get("effort"), str):
            raise ValueError("missing fixed model effort")
        out[role] = (data["model"], data["effort"])
    return out


def snapshot_check(snapshot, now, max_age):
    if (not isinstance(snapshot, dict) or snapshot.get("version") != 1 or snapshot.get("inventory_complete") is not True or
            not finite(snapshot.get("observed_at")) or not 0 <= now - snapshot["observed_at"] <= max_age or
            not isinstance(snapshot.get("workers"), list) or len(snapshot["workers"]) > 1000 or
            not isinstance(snapshot.get("claude_accounts"), list) or len(snapshot["claude_accounts"]) > 3):
        raise ValueError("stale or incomplete public inventory")
    if "capacity_expires_at" in snapshot and (not finite(snapshot["capacity_expires_at"]) or now >= snapshot["capacity_expires_at"]):
        raise ValueError("operator capacity allowance expired")
    ids = set()
    for worker in snapshot["workers"]:
        if (not isinstance(worker, dict) or not isinstance(worker.get("id"), str) or worker["id"] in ids or
                not isinstance(worker.get("case"), str) or worker.get("state") not in ("running", "retired", "unknown")):
            raise ValueError("invalid worker inventory")
        ids.add(worker["id"])
    for provider in ("opencode", "codex"):
        provider_accounts_check(snapshot.get(provider + "_accounts", []), provider, now)
    accounts = set()
    for account in snapshot["claude_accounts"]:
        if (not isinstance(account, dict) or type(account.get("id")) is not int or account["id"] not in key_holder.CLAUDE_ACCOUNTS or
                account["id"] in accounts or type(account.get("available")) is not bool or
                type(account.get("capacity")) is not int or not 0 <= account["capacity"] <= 100 or
                type(account.get("used")) is not int or not 0 <= account["used"] <= account["capacity"] or
                not finite(account.get("blocked_until", 0))):
            raise ValueError("invalid account capacity")
        accounts.add(account["id"])


def provider_accounts_check(accounts, provider, now):
    """Public observations are evidence, never inferred from credential presence."""
    allowed = key_holder.OPENCODE_ACCOUNTS if provider == "opencode" else {1: "codex-auth.json"}
    if not isinstance(accounts, list) or len(accounts) > len(allowed): raise ValueError("invalid provider accounts")
    seen = set()
    for row in accounts:
        if (not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] not in allowed or row["id"] in seen or
                type(row.get("capacity")) is not int or not 0 <= row["capacity"] <= 10 or
                type(row.get("used", 0)) is not int or not 0 <= row.get("used", 0) <= row["capacity"] or
                type(row.get("available")) is not bool or not finite(row.get("blocked_until", 0)) or
                not isinstance(row.get("models"), list) or not row["models"] or len(row["models"]) > 20):
            raise ValueError("invalid provider capacity")
        seen.add(row["id"])
        for model in row["models"]:
            prefix = ("codex/",) if provider == "codex" else ("opencode/", "opencode-go/")
            if (not isinstance(model, dict) or not isinstance(model.get("model"), str) or
                    not model["model"].startswith(prefix) or not isinstance(model.get("effort"), str) or not model["effort"]):
                raise ValueError("invalid provider model")
        quota = row.get("quota", {})
        if (not isinstance(quota, dict) or quota.get("state") not in ("available", "unknown", "exhausted") or
                not finite(quota.get("observed_at")) or not finite(quota.get("expires_at")) or
                not quota["observed_at"] <= now < quota["expires_at"] or
                quota["expires_at"] - quota["observed_at"] > 3600 or
                quota.get("source") != "operator_observation" or
                (quota.get("credit_remaining") is not None and
                 (not finite(quota["credit_remaining"]) or quota["credit_remaining"] < 0))):
            raise ValueError("unverified provider quota")


def journal_check(journal, digest):
    if (not isinstance(journal, dict) or journal.get("version") != 1 or journal.get("policy_sha256") != digest or
            not isinstance(journal.get("actions"), list) or len(journal["actions"]) > MAX_ACTIONS): return False
    ids = set()
    for row in journal["actions"]:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in ids or
                not isinstance(row.get("case"), str) or not re.fullmatch(r"case-[A-Za-z0-9-]+", row["case"]) or
                not isinstance(row.get("job"), str) or not re.fullmatch(r"[a-z0-9-]+", row["job"]) or
                not isinstance(row.get("generation"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["generation"]) or
                not isinstance(row.get("recovery_config_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["recovery_config_sha256"]) or
                not finite(row.get("at")) or type(row.get("seed")) is not int or
                not finite(row.get("deadline")) or row["deadline"] <= row["at"] or
                type(row.get("budget_calls")) is not int or row["budget_calls"] < 0 or
                not finite(row.get("budget_cost")) or row["budget_cost"] < 0 or
                row.get("state") not in ("reserved", "started", "unknown", "collected") or
                (row.get("claude_account") is not None and (type(row["claude_account"]) is not int or row["claude_account"] not in key_holder.CLAUDE_ACCOUNTS))):
            return False
        for provider, allowed in (("opencode", key_holder.OPENCODE_ACCOUNTS), ("codex", {1: "codex-auth.json"})):
            if provider + "_account" in row and (type(row[provider + "_account"]) is not int or row[provider + "_account"] not in allowed): return False
        ids.add(row["id"])
    return True


def configuration_args(card, job):
    """Legacy absence is uncertainty. Reviewed explicit flags avoid default drift."""
    config = card.get("recovery_config")
    if not isinstance(config, dict) or config.get("version") != 1: raise ValueError("missing original configuration")
    argv = job["args"][1:]
    proposed = list(job["args"])
    forbidden = {"--dry-run", "--statement-only", "--audit-g11", "--continue-g11-review", "--probe"}
    if any(value.split("=", 1)[0] in forbidden for value in argv): raise ValueError("recovery mode changed")
    def option(flag):
        values = []
        for index, value in enumerate(argv):
            if value == flag:
                if index + 1 == len(argv): raise ValueError("missing flag value")
                values.append(argv[index + 1])
            elif value.startswith(flag + "="): values.append(value.split("=", 1)[1])
        if len(values) > 1: raise ValueError("duplicate policy flag")
        return values[0] if values else None
    def require(flag, value, numeric=False):
        current = option(flag)
        if current is None: proposed.extend((flag, str(value)))
        elif (float(current) != value if numeric else current != value): raise ValueError("policy changes original configuration")
    if card.get("source") not in ("port", "hunt", "plant") or type(card.get("rotation_slot")) is not int or card["rotation_slot"] < 1:
        raise ValueError("missing original source or rotation")
    require("--source", card["source"])
    require("--rotation-slot", card["rotation_slot"], numeric=True)
    for field in CONFIG_FIELDS:
        if field == "case_budget" and field not in config: continue  # legacy cases predate this ceiling
        original = config.get(field)
        if not finite(original) or original < (0 if field == "max_repairs" else 1e-300): raise ValueError("missing original limit")
        if field not in ("calibrator_minutes", "case_budget", "max_cost", "no_progress_minutes", "agent_timeout") and type(original) is not int:
            raise ValueError("invalid integer limit")
        require("--" + field.replace("_", "-"), original, numeric=True)
    for role, (model, effort) in roles(job["roles"]).items():
        flag = ROLE_FLAGS.get(role)
        if flag is None: raise ValueError("unsupported role")
        require("--" + flag, model); require("--" + flag + "-effort", effort)
    # A second reviewer cannot be added silently; the same applies to caller seed overrides.
    if "reviewer2" not in job["roles"] and option("--reviewer2") is not None: raise ValueError("reviewer added")
    if option("--seed") is not None and option("--seed") != str(card.get("seed")): raise ValueError("seed changed")
    return proposed


def decision(policy, snapshot, journal, name, status, *, now, deadline, max_age=120):
    """Compute one bounded action; all returned/stored metadata is allowlisted."""
    base = {"job": name, "action": "blocked"}
    def stop(reason, action="blocked", **extra): return {**base, "action": action, "reason": reason, **extra}
    snapshot_check(snapshot, now, max_age)
    digest = key_holder.policy_digest(policy)
    if not journal_check(journal, digest):
        return stop("journal_or_policy_mismatch")
    if (status.get("unlocked") is not True or status.get("policy_sha256") != digest or
            not finite(status.get("seconds_remaining")) or status["seconds_remaining"] < 120):
        return stop("holder_locked_or_policy_mismatch")
    job = policy["jobs"][name]
    if job.get("mode") != "case": return stop("fixed_case_job_required")
    if job.get('ttl_continuation') and deadline != job['ttl_continuation'].get('deadline'):
        return stop('original_deadline_changed')
    case = job["case"]; base["case"] = case
    if any(w["case"] == case and w["state"] != "retired" for w in snapshot["workers"]):
        return stop("case_worker_present", "active")
    holder_job = status.get("jobs", {}).get(name)
    if isinstance(holder_job, dict) and holder_job.get("exit") is None: return stop("holder_launch_active", "active")
    card_path = key_holder.ROOT / "sealed" / job["card"]
    card = read_public(card_path)
    from recovery import explicit_pause
    ttl_retired = card.get('terminal_stop') == 'ttl_retired'
    if explicit_pause(card):
        return stop("explicit_pause")
    if roles(card.get("roles")) != roles(job.get("roles")): return stop("model_or_effort_changed")
    try: proposed_args = configuration_args(card, job)
    except (TypeError, ValueError): return stop("original_configuration_not_verified")
    if proposed_args != job["args"]:
        return stop("missing_policy_config", proposed_args=proposed_args)
    try: generation = key_holder.current_generation(job)
    except (OSError, ValueError, KeyError, TypeError): return stop("unverified_checkpoint_or_budget")
    if card.get("sha256") != generation: return stop("generation_changed_during_plan", "reconcile")
    budget = card["continuation_budget"]
    actions = [row for row in journal["actions"] if row.get("case") == case]
    if any(row["deadline"] != deadline for row in actions): return stop("original_deadline_changed")
    if any(budget["calls"] < row["budget_calls"] or budget["cost"] + 1e-9 < row["budget_cost"] for row in actions):
        return stop("cumulative_budget_regressed")
    unresolved = [row for row in actions if row.get("state") != "collected"]
    reconciled = []
    if unresolved:
        # Use the same local verified collection evidence as the trusted holder,
        # never a caller-provided inventory claim that an uncertain worker vanished.
        try: collected = read_public(key_holder.ROOT / MONITOR)
        except (OSError, ValueError): collected = {}
        for row in unresolved:
            if not key_holder.collected_successor(job, generation, row, collected):
                return stop("previous_launch_outcome_unknown", "reconcile", generation=generation)
            reconciled.append(row["id"])
    if len(actions) >= 3 or len(journal["actions"]) >= MAX_ACTIONS: return stop("launch_allowance_exhausted")
    conditions = roles(job["roles"])
    claude = sorted(set(value for value in conditions.values() if value[0].startswith("claude/")))
    account_id = None
    limited_account = None
    if claude:
        allowed = set(job.get("claude_accounts") or [1])
        if actions:
            previous = actions[-1]
            verified_successor = (previous["id"] in reconciled or
                                  (previous.get("state") == "collected" and previous.get("successor") == generation))
            if (verified_successor and previous["generation"] != generation and
                    card.get("terminal_stop") in {"provider_limit:" + model for model, effort in claude}):
                limited_account = previous.get("claude_account")
        # A verified Claude limit prefers another authorized account. This does
        # not declare the first account unavailable or bypass the normal backoff.
        for account in sorted(snapshot["claude_accounts"], key=lambda value: (value["id"] == limited_account, value["id"])):
            used = sum(row.get("claude_account") == account["id"] and row.get("state") != "collected" and row.get("id") not in reconciled
                       for row in journal["actions"])
            if (account["id"] not in allowed or not account["available"] or account.get("blocked_until", 0) > now or
                    max(account["used"], used) >= account["capacity"] or
                    status.get("claude_accounts", {}).get(str(account["id"])) is not True): continue
            supported = {(v.get("model"), v.get("effort")) for v in account.get("models", []) if isinstance(v, dict)}
            if not set(claude) <= supported: continue
            account_id = account["id"]; break
        if account_id is None: return stop("authorized_account_capacity_unavailable")
    selected = {}
    opencode_handoff = False
    for provider, prefix in (("opencode", ("opencode/", "opencode-go/")), ("codex", ("codex/",))):
        required = {value for value in conditions.values() if value[0].startswith(prefix)}
        if not required: continue
        allowed = set(job.get("opencode_accounts", [])) if provider == "opencode" else {1}
        previous_account = None
        if actions:
            previous = actions[-1]
            verified = previous["id"] in reconciled or (previous.get("state") == "collected" and previous.get("successor") == generation)
            from account_handoff import limited_provider
            if (verified and previous["generation"] != generation and
                    limited_provider(card.get("terminal_stop", "")) == provider and
                    card.get("terminal_stop") in {"provider_limit:" + m for m, e in required}):
                previous_account = previous.get(provider + "_account")
        for account in sorted(snapshot.get(provider + "_accounts", []), key=lambda a: (a["id"] == previous_account, a["id"])):
            quota = account["quota"]
            used = sum(row.get(provider + "_account") == account["id"] and row.get("state") != "collected" and row["id"] not in reconciled for row in journal["actions"])
            supported = {(m["model"], m["effort"]) for m in account["models"]}
            if (account["id"] not in allowed or not account["available"] or account.get("blocked_until", 0) > now or
                    max(account.get("used", 0), used) >= account["capacity"] or not required <= supported or
                    quota["state"] != "available" or quota.get("credit_remaining") == 0 or
                    (provider == "opencode" and status.get("opencode_accounts", {}).get(str(account["id"])) is not True)):
                continue
            selected[provider + "_account"] = account["id"]
            if provider == "opencode" and previous_account is not None and previous_account != account["id"]: opencode_handoff = True
            break
        else: return stop(provider + "_capacity_or_quota_unverified")
    try:
        if ttl_retired:
            from ttl_continuation import ready
            ready(key_holder.ROOT, job, card, now=now)
            if deadline != job['ttl_continuation']['deadline']: return stop('original_deadline_changed')
            if len(actions) >= job['ttl_continuation']['max_attempts']: return stop('launch_allowance_exhausted')
            delay, seed = 0, card['seed']
        else:
            _, delay, seed = restart.plan(card_path, len(actions), deadline - now, shlex.join(job["args"][1:]),
                                     claude_account_handoff=limited_account is not None and account_id != limited_account,
                                     opencode_account_handoff=opencode_handoff)
    except (OSError, ValueError, TypeError, KeyError, IndexError): return stop("stop_or_original_budget_not_retryable")
    # Collection timestamps anchor transient backoff; account-specific reset
    # windows apply only while retaining the account that hit the Claude limit.
    stopped_at = card_path.stat().st_mtime
    if stopped_at > now: return stop("future_collection_timestamp")
    ready_at = stopped_at + delay
    if now < ready_at: return stop("restart_backoff", "wait", not_before=ready_at)
    return {**base, "action": "launch", "generation": generation, "seed": seed,
            "deadline": deadline,
            "recovery_config_sha256": key_holder.recovery_conditions_digest(card),
            "claude_account": account_id, "budget_calls": budget["calls"], "budget_cost": budget["cost"],
            "reconciled": reconciled, **selected}


@contextlib.contextmanager
def locked(path):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally: os.close(fd)


def coordinate(policy, snapshot, journal_path, name, *, execute=False, now=None, deadline, request=None):
    now = time.time() if now is None else now
    if not finite(now) or not finite(deadline): raise ValueError("invalid coordinator deadline")
    request = key_holder.request if request is None else request
    with locked(journal_path):
        path = pathlib.Path(journal_path)
        journal = read_public(path) if path.exists() else {"version": 1, "policy_sha256": key_holder.policy_digest(policy), "actions": []}
        status = request({"op": "status"})
        result = decision(policy, snapshot, journal, name, status, now=now, deadline=deadline)
        if not execute or result["action"] != "launch": return result
        for row in journal["actions"]:
            if row["id"] in result["reconciled"]: row.update(state="collected", successor=result["generation"])
        action_id = str(len(journal["actions"]) + 1)
        row = {key: result[key] for key in ("case", "job", "generation", "seed", "deadline", "recovery_config_sha256", "claude_account", "budget_calls", "budget_cost")}
        row.update({key: result[key] for key in ("opencode_account", "codex_account") if key in result})
        row.update(id=action_id, at=now, state="reserved")
        journal["actions"].append(row)
        atomic_json(path, journal)  # a crash from here onward requires reconciliation, never blind replay
        payload = {"op": "launch", "job": name, "expected_generation": row["generation"],
                   "expected_recovery_config_sha256": row["recovery_config_sha256"]}
        if row["claude_account"] is not None: payload["claude_account"] = row["claude_account"]
        if "opencode_account" in row: payload["opencode_account"] = row["opencode_account"]
        try:
            reply = request(payload)
            if reply.get("started") is True and reply.get("job") == name and type(reply.get("pid")) is int and reply["pid"] > 0:
                row.update(state="started", pid=reply["pid"])
            else: row["state"] = "unknown"  # refusals can follow a consumed holder reservation
        except Exception:
            row["state"] = "unknown"
        atomic_json(path, journal)
        return {**result, "action": row["state"], "reservation": action_id}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "step"))
    parser.add_argument("--policy", type=pathlib.Path, required=True)
    parser.add_argument("--snapshot", type=pathlib.Path, required=True)
    parser.add_argument("--journal", type=pathlib.Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--deadline", type=float, required=True, help="original collection deadline, Unix seconds")
    args = parser.parse_args()
    policy = key_holder.policy_load(args.policy)
    result = coordinate(policy, read_public(args.snapshot), args.journal, args.job,
                        execute=args.operation == "step", deadline=args.deadline)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try: main()
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"action": "blocked", "reason": "invalid_metadata_or_holder_unavailable"}))
        raise SystemExit(1)
