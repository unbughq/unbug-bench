#!/usr/bin/env python3
"""Produce a fresh public recovery snapshot, optionally run one coordinator tick.

Uses the existing `bin/boat-call list --json` inventory and public monitor ID hints.
Claude quota has no reliable observer in this repository. An operator provides
explicit persistent concurrency limits; credential presence never creates capacity
or establishes quota. Unattributed live work consumes every slot conservatively.
No command installs a recurring job, unlocks credentials, or changes holder policy.
`snapshot` and `plan` query inventory/status only; only `step` may request a launch.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shlex
import subprocess
import time

import coordinator
import key_holder
from registry import atomic_json

CASE = re.compile(r"case-[A-Za-z0-9-]+")


def capacity_check(config, now):
    if (not isinstance(config, dict) or config.get("version") != 1 or
            not isinstance(config.get("claude_accounts"), list) or len(config["claude_accounts"]) > 3 or
            not isinstance(config.get("worker_accounts", {}), dict) or len(config.get("worker_accounts", {})) > 1000 or
            not isinstance(config.get("unrelated_worker_ids", []), list)):
        raise ValueError("invalid_operator_concurrency_limits")
    if "issued_at" in config and (not coordinator.finite(config["issued_at"]) or config["issued_at"] > now):
        raise ValueError("invalid_operator_capacity_timestamp")
    if "expires_at" in config and (not coordinator.finite(config["expires_at"]) or now >= config["expires_at"]):
        raise ValueError("expired_operator_capacity")
    unrelated = config.get("unrelated_worker_ids", [])
    if len(unrelated) > 1000 or len(set(unrelated)) != len(unrelated) or any(not isinstance(value, str) for value in unrelated):
        raise ValueError("invalid_unrelated_worker_scope")


def monitor_workers(states):
    rows = []
    for state in states:
        workers = state.get("workers", [])
        if isinstance(workers, dict): workers = list(workers.values())
        if not isinstance(workers, list) or len(workers) > 1000: raise ValueError("invalid_monitor_workers")
        for worker in workers:
            if not isinstance(worker, dict) or not isinstance(worker.get("id"), str): raise ValueError("invalid_monitor_worker")
            case = worker.get("case")
            if case is not None and (not isinstance(case, str) or not CASE.fullmatch(case)): raise ValueError("invalid_monitor_case")
            rows.append({"id": worker["id"], "case": case, "retired": worker.get("retired") is True,
                         "claude_account": worker.get("claude_account", worker.get("claude_account_at_launch"))})
    return rows


def build_snapshot(policy, fleet, states, config, status, *, now):
    capacity_check(config, now)
    if (not isinstance(fleet, dict) or not isinstance(fleet.get("sandboxes"), list) or len(fleet["sandboxes"]) > 1000 or
            not isinstance(fleet.get("pageInfo"), dict) or fleet["pageInfo"].get("hasMore") is not False):
        raise ValueError("provider_inventory_incomplete")
    mappings, retired = {}, {}
    def bind(worker, case):
        if case is None: return
        if worker in mappings and mappings[worker] != case: raise ValueError("conflicting_worker_case")
        mappings[worker] = case
    for row in monitor_workers(states):
        bind(row["id"], row["case"])
        # Conflicting retirement hints remain unknown; provider presence always wins.
        retired[row["id"]] = retired.get(row["id"], True) and row["retired"]
    cases = set(mappings.values())
    jobs = policy['jobs']
    if 'batch' in policy:
        from batch_money import manifest
        from batch_service import resolve_job
        record = manifest(policy, pathlib.Path(policy['root']))
        jobs = {name: resolve_job(record, name)['template'] for name in
                set(record['jobs']) | set(record.get('carry_from', {}).get('jobs', {}))}
    for job in jobs.values():
        case = job.get('case')
        if not isinstance(case, str) or not CASE.fullmatch(case): continue
        cases.add(case)
        for worker in job.get('known_worker_ids', []): bind(worker, case)
    unrelated = set(config.get("unrelated_worker_ids", []))
    if any(worker in mappings for worker in unrelated): raise ValueError("known_case_worker_cannot_be_unrelated")
    workers, present, present_cases, unknown_case = [], set(), {}, False
    unattributed = False
    for item in fleet["sandboxes"]:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] or item["id"] in present):
            raise ValueError("provider_inventory_malformed")
        worker = item["id"]; present.add(worker)
        if worker in unrelated: continue
        case = mappings.get(worker)
        name = item.get("name", "")
        if case is None and isinstance(name, str) and name.startswith("factory:"):
            matches = [value for value in cases if name.endswith(value.rsplit("-", 1)[-1])]
            if len(matches) == 1: case = matches[0]
        if case is None: unknown_case = True
        else: present_cases.setdefault(case, set()).add(worker)
        workers.append({"id": worker, "case": case or "unassigned", "state": "running" if case else "unknown"})
    for worker, case in mappings.items():
        if worker not in present:
            workers.append({"id": worker, "case": case, "state": "retired" if retired.get(worker) else "unknown"})
    unattributed = unknown_case
    # Status reports credential presence, not quota. A controller can have an
    # in-flight launch before its worker appears; do not guess its chosen account.
    active_jobs = [job for job, value in status.get("jobs", {}).items()
                   if isinstance(value, dict) and value.get("exit") is None]
    for name in active_jobs:
        case = (policy["jobs"].get(name) or {}).get("case")
        if case not in present_cases: unattributed = True
    snapshot = {"version": 1, "observed_at": now, "inventory_complete": not unknown_case,
                "workers": workers, "claude_accounts": [],
                "holder_policy_sha256": key_holder.policy_digest(policy),
                "capacity_source": "model_router", "unattributed_active_work": unattributed}
    if "expires_at" in config: snapshot["capacity_expires_at"] = config["expires_at"]
    if snapshot["inventory_complete"]: coordinator.snapshot_check(snapshot, now, 120)
    return snapshot


def prepare_admission(policy, snapshot, status, job, registry_root, destination, *, run):
    """Prepare one stopped worker's encrypted board; delivery/resume stay explicit."""
    import statement_round
    fixed = policy["jobs"][job]
    case = fixed.get("case")
    if fixed.get("mode") != "case" or not isinstance(case, str) or not CASE.fullmatch(case):
        raise ValueError("fixed_case_job_required")
    if any(value.get("exit") is None for value in status.get("jobs", {}).values() if isinstance(value, dict)):
        raise ValueError("holder_launch_active")
    workers = [w for w in snapshot["workers"] if w["case"] == case and w["state"] == "running"]
    if len(workers) != 1: raise ValueError("one_present_candidate_worker_required")
    worker = statement_round.worker_id(workers[0]["id"], "boat")
    # Public metadata plus ciphertext digest only; no case files or decryption.
    probe = """import pathlib,json,hashlib
h=pathlib.Path('/home/user/sealed'); case=CASE_ID
c=json.loads((h/(case+'.scorecard.json')).read_text())
p=h/(case+'.statement.age')
assert c.get('terminal_stop') in ('statement-ready','admission_registry_unavailable')
print(json.dumps({'case':case,'statement_sha256':c.get('statement_sha256'),'ciphertext_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))
""".replace("CASE_ID", repr(case))
    command = "test -f /home/user/sealed/DONE && ! pgrep -f '^python3 .*factory/run.py' >/dev/null && python3 -c " + shlex.quote(probe)
    done = run([str(key_holder.ROOT / "bin/boat-call"), "ssh", worker, command], capture_output=True,
               text=True, stdin=subprocess.DEVNULL,
               env={**os.environ, 'BOAT_CAPTURE_OUTPUT': '1', 'BOAT_COMMAND_TIMEOUT_SECONDS': '25'})
    if done.returncode: raise ValueError("candidate_stop_unverified")
    observed = json.loads(done.stdout)
    card = coordinator.read_public(key_holder.ROOT / "sealed" / (case + ".scorecard.json"))
    ciphertext = key_holder.ROOT / "sealed" / (case + ".statement.age")
    digest = card.get("statement_sha256")
    if (card.get("terminal_stop") not in ("statement-ready", "admission_registry_unavailable") or
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or
            observed.get("case") != case or observed.get("statement_sha256") != digest or ciphertext.is_symlink() or
            hashlib.sha256(ciphertext.read_bytes()).hexdigest() != observed.get("ciphertext_sha256")):
        raise ValueError("collected_candidate_mismatch")
    snapshots = statement_round.prepare(key_holder.ROOT / "sealed", registry_root, {case: digest}, destination)
    return {"action": "admission_prepared", "case": case, "worker": worker,
            "snapshot": str(snapshots[case]), "delivery_and_authorized_resume_required": True}


def tick(policy, config, states, snapshot_path, journal, job, *, operation="plan", deadline=None, request=None, run=None, now=None, registry_root=None, admission_destination=None):
    """One fresh inventory query plus one bounded dispatch decision; no scheduling."""
    request = key_holder.request if request is None else request
    run = subprocess.run if run is None else run
    capacity_check(config, time.time() if now is None else now)
    status = request({"op": "status"})
    if status.get("policy_sha256") != key_holder.policy_digest(policy) or status.get("unlocked") is not True:
        raise ValueError("holder_locked_or_policy_mismatch")
    done = run([str(key_holder.ROOT / "bin/boat-call"), "list", "--json"], capture_output=True,
               text=True, stdin=subprocess.DEVNULL,
               env={**os.environ, 'BOAT_CAPTURE_OUTPUT': '1', 'BOAT_COMMAND_TIMEOUT_SECONDS': '25'})
    if done.returncode: raise ValueError("provider_inventory_unavailable")
    observed = time.time() if now is None else now
    snapshot = build_snapshot(policy, json.loads(done.stdout), states, config, status, now=observed)
    pathlib.Path(snapshot_path).parent.mkdir(parents=True, exist_ok=True)
    atomic_json(snapshot_path, snapshot)
    if operation == "snapshot": return snapshot
    if not snapshot["inventory_complete"]: return {"action": "blocked", "reason": "unassigned_live_worker"}
    if operation == "admit":
        if registry_root is None or admission_destination is None: raise ValueError("admission_paths_required")
        return prepare_admission(policy, snapshot, status, job, registry_root, admission_destination, run=run)
    return coordinator.coordinate(policy, snapshot, journal, job, execute=operation == "step",
                                  now=observed, deadline=deadline, request=request)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("snapshot", "plan", "step", "admit"))
    parser.add_argument("--policy", type=pathlib.Path, required=True)
    parser.add_argument("--capacity", type=pathlib.Path, required=True, help="public persistent concurrency limits; optional explicit expiry")
    parser.add_argument("--monitor", type=pathlib.Path, action="append", help="public worker-ID hints; repeat for another monitor")
    parser.add_argument("--snapshot", type=pathlib.Path, required=True)
    parser.add_argument("--journal", type=pathlib.Path)
    parser.add_argument("--job")
    parser.add_argument("--deadline", type=float)
    parser.add_argument("--registry-root", type=pathlib.Path)
    parser.add_argument("--admission-destination", type=pathlib.Path)
    args = parser.parse_args()
    if args.operation == "admit" and (args.job is None or args.registry_root is None or args.admission_destination is None):
        parser.error("admit requires --job --registry-root --admission-destination")
    if args.operation in ("plan", "step") and (args.journal is None or args.job is None or args.deadline is None):
        parser.error("plan/step require --journal --job and the original --deadline")
    # Read-only census can qualify existing infrastructure before a new trusted
    # launcher policy is activated. Dispatch still requires the pinned policy.
    policy = coordinator.read_public(args.policy) if args.operation == "snapshot" else key_holder.policy_load(args.policy)
    if policy.get("root") != str(key_holder.ROOT) or not isinstance(policy.get("jobs"), dict):
        raise ValueError("invalid_public_policy_metadata")
    monitor_paths = args.monitor or [key_holder.ROOT / coordinator.MONITOR]
    states = [coordinator.read_public(path) for path in monitor_paths if path.exists()]
    result = tick(policy, coordinator.read_public(args.capacity), states, args.snapshot, args.journal, args.job,
                  operation=args.operation, deadline=args.deadline, registry_root=args.registry_root,
                  admission_destination=args.admission_destination)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try: main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"action": "blocked", "reason": "inventory_or_operator_capacity_unverified"}))
        raise SystemExit(1)
