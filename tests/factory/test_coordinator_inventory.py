"""Fresh-inventory glue: public synthetic metadata, no cloud or credential access."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy
import contextlib
import io
import json
import pathlib
import subprocess
import tempfile
import sys
from unittest import mock

import coordinator_inventory as inv
import key_holder

NOW = 1_000_000
CASE = "case-synthetic-abcdef"
policy = {"jobs": {"recovery": {"mode": "case", "case": CASE, "known_worker_ids": ["old"],
                               "claude_accounts": [1, 2]}}}
status = {"unlocked": True, "policy_sha256": key_holder.policy_digest(policy), "jobs": {},
          "claude_accounts": {"1": True, "2": True}}
capacity = {"version": 1, "issued_at": NOW - 10, "expires_at": NOW + 600,
            "claude_accounts": [{"id": n, "available": True, "capacity": 1,
                                  "models": [{"model": "claude/synthetic", "effort": "high"}]} for n in (1, 2)],
            "worker_accounts": {"old": 1, "live": 1}}
monitor = {"workers": [{"id": "old", "case": CASE, "retired": True}]}
empty = {"sandboxes": [], "pageInfo": {"hasMore": False}}


def build(fleet=empty, states=None, config=None, holder=None):
    return inv.build_snapshot(policy, fleet, [monitor] if states is None else states,
                              capacity if config is None else config, status if holder is None else holder, now=NOW)


snapshot = build()
assert snapshot["inventory_complete"] and snapshot["observed_at"] == NOW
assert snapshot["workers"] == [{"id": "old", "case": CASE, "state": "retired"}]
assert snapshot["claude_accounts"] == [] and snapshot["capacity_source"] == "model_router"
persistent = {key: value for key, value in capacity.items() if key not in ("issued_at", "expires_at")}
persistent_snapshot = build(config=persistent)
assert persistent_snapshot["claude_accounts"] == [] and "capacity_expires_at" not in persistent_snapshot
inv.capacity_check(persistent, NOW + 7 * 24 * 3600)  # no human refresh is required
assert build(config={**capacity, "expires_at": NOW + 7200})["capacity_expires_at"] == NOW + 7200

# Live provider presence wins over historical retirement. Immutable account
# assignments count work against its account, leaving another approved one free.
live = {"sandboxes": [{"id": "old", "name": "factory: repair — abcdef", "private_provider_detail": "DO_NOT_EXPORT"}],
        "pageInfo": {"hasMore": False}}
snapshot = build(live)
assert snapshot["workers"][0]["state"] == "running"
assert snapshot["claude_accounts"] == []
assert "DO_NOT_EXPORT" not in json.dumps(snapshot)
active_holder = {**status, "jobs": {"recovery": {"pid": 123, "exit": None}}}
assert not build(live, holder=active_holder)["unattributed_active_work"]
assert build(holder=active_holder)["unattributed_active_work"]  # uncertain in-flight launch

# Existing monitor list and dict schemas are both accepted, without copying raw
# provider progress, transcripts or credential-like extra fields to the snapshot.
dict_monitor = {"workers": {"live": {"id": "live", "case": CASE, "retired": False, "claude_account": 1,
                                   "observed": {"not_public_payload": "DO_NOT_EXPORT"}}}}
snapshot = build({"sandboxes": [{"id": "live", "name": "unnamed"}], "pageInfo": {"hasMore": False}}, states=[dict_monitor])
assert snapshot["workers"] == [{"id": "live", "case": CASE, "state": "running"},
                               {"id": "old", "case": CASE, "state": "unknown"}]
assert "DO_NOT_EXPORT" not in json.dumps(snapshot)
assert build(states=[{"workers": [{"id": "old", "case": CASE}]}])["workers"][0]["state"] == "unknown"

# An unassigned live worker never becomes free capacity or a complete inventory.
unknown = {"sandboxes": [{"id": "unknown", "name": "unidentified"}], "pageInfo": {"hasMore": False}}
snapshot = build(unknown)
assert not snapshot["inventory_complete"] and snapshot["unattributed_active_work"]
assert snapshot["claude_accounts"] == []
ignored = {**capacity, "unrelated_worker_ids": ["unknown"]}
assert build(unknown, config=ignored)["inventory_complete"]
unmapped = {"sandboxes": [{"id": "new", "name": "factory: slot 1 — repair — abcdef"}], "pageInfo": {"hasMore": False}}
snapshot = build(unmapped)
assert snapshot["inventory_complete"] and snapshot["workers"][0]["case"] == CASE
assert all(row["used"] == row["capacity"] for row in snapshot["claude_accounts"])  # auth is not account attribution

# Explicit operator blocks/expiry constrain quota assumptions; holder auth does
# not create missing allowances or mark a blocked account available.
blocked = copy.deepcopy(capacity); blocked["claude_accounts"][0]["blocked_until"] = NOW + 100
assert build(config=blocked)["claude_accounts"] == []
assert not any(row["available"] for row in build(holder={**status, "claude_accounts": {}})["claude_accounts"])
assert not build(config={**capacity, "claude_accounts": [], "worker_accounts": {}})["claude_accounts"]
try: inv.coordinator.snapshot_check({**snapshot, "observed_at": NOW, "inventory_complete": True, "capacity_expires_at": NOW + 1}, NOW + 2, 120)
except ValueError: pass
else: raise AssertionError("fresh snapshot extended an expired operator allowance")
for bad in ({**capacity, "expires_at": NOW},
            {**capacity, "issued_at": NOW + 1}):
    try: build(config=bad)
    except ValueError: pass
    else: raise AssertionError("invalid or explicitly expired limits accepted")
for bad in ({}, {"sandboxes": [], "pageInfo": {"hasMore": True}},
            {"sandboxes": [{"id": "same"}, {"id": "same"}], "pageInfo": {"hasMore": False}}):
    try: build(bad)
    except ValueError: pass
    else: raise AssertionError("partial or malformed provider inventory accepted")

with tempfile.TemporaryDirectory() as temp:
    root = pathlib.Path(temp); snapshot_path = root / "snapshot.json"
    queried, requests = [], []
    def provider(argv, **kwargs):
        assert argv[-2:] == ["list", "--json"] and kwargs["timeout"] == 25
        queried.append(argv); return subprocess.CompletedProcess(argv, 0, json.dumps(empty), "")
    def holder(payload):
        requests.append(payload); assert payload == {"op": "status"}; return status
    result = inv.tick(policy, capacity, [monitor], snapshot_path, None, None, operation="snapshot",
                      request=holder, run=provider, now=NOW)
    assert json.loads(snapshot_path.read_text()) == result and len(queried) == 1
    for operation in ("plan", "step"):
        with mock.patch.object(inv.coordinator, "coordinate", return_value={"action": "synthetic"}) as dispatch:
            assert inv.tick(policy, capacity, [monitor], snapshot_path, root / "journal.json", "recovery",
                            operation=operation, deadline=NOW + 7200, request=holder, run=provider, now=NOW)["action"] == "synthetic"
            assert dispatch.call_args.kwargs["execute"] == (operation == "step")
            assert dispatch.call_args.kwargs["request"] is holder
    with mock.patch.object(inv.coordinator, "coordinate") as dispatch:
        def unknown_provider(argv, **kwargs): return subprocess.CompletedProcess(argv, 0, json.dumps(unknown), "")
        result = inv.tick(policy, capacity, [monitor], snapshot_path, root / "journal.json", "recovery",
                          operation="step", deadline=NOW + 7200, request=holder, run=unknown_provider, now=NOW)
        assert result == {"action": "blocked", "reason": "unassigned_live_worker"}
        dispatch.assert_not_called()
    assert all(request == {"op": "status"} for request in requests)

    # A census can run against the current holder's exact older public policy;
    # planning/dispatch still requires the current trusted launcher fingerprint.
    policy_path = root / "policy.json"; capacity_path = root / "capacity.json"; monitor_path = root / "monitor.json"
    policy_path.write_text(json.dumps({**policy, "root": str(key_holder.ROOT), "code_sha256": "old-reviewed-code"}))
    capacity_path.write_text(json.dumps(capacity)); monitor_path.write_text(json.dumps(monitor))
    argv = ["coordinator_inventory.py", "snapshot", "--policy", str(policy_path), "--capacity", str(capacity_path),
            "--monitor", str(monitor_path), "--snapshot", str(snapshot_path)]
    with mock.patch.object(sys, "argv", argv), mock.patch.object(inv, "tick", return_value={"action": "census"}) as census, \
         mock.patch.object(key_holder, "policy_load", side_effect=ValueError("old code fingerprint")) as trusted, \
         contextlib.redirect_stdout(io.StringIO()):
        inv.main(); trusted.assert_not_called(); census.assert_called_once()
    argv[1] = "plan"; argv += ["--journal", str(root / "journal.json"), "--job", "recovery", "--deadline", str(NOW + 7200)]
    with mock.patch.object(sys, "argv", argv), mock.patch.object(inv, "tick") as census, \
         mock.patch.object(key_holder, "policy_load", side_effect=ValueError("old code fingerprint")) as trusted:
        try: inv.main()
        except ValueError: pass
        else: raise AssertionError("plan skipped the trusted-code policy check")
        trusted.assert_called_once(); census.assert_not_called()

print("PASS inventory wiring: fresh provider list, monitor schemas, persistent concurrency caps, optional expiry, account occupancy, unknown-work blocks, sanitization and one-tick dispatch")

# Model-account/quota observations no longer create another admission authority.
providers = copy.deepcopy(capacity)
providers['opencode_accounts'] = [{'quota': {'expires_at':0}}]
assert 'opencode_accounts' not in build(live, config=providers)

# Explicit admission tick prepares locally only after a fresh stopped-worker proof.
with tempfile.TemporaryDirectory() as temp, mock.patch.object(key_holder, "ROOT", pathlib.Path(temp)):
    import hashlib
    import statement_round
    root = pathlib.Path(temp); (root / "sealed").mkdir()
    encrypted = root / "sealed" / (CASE + ".statement.age")
    encrypted.write_bytes(b"age-encryption.org/v1 synthetic encrypted statement")
    digest = "a" * 64
    (root / "sealed" / (CASE + ".scorecard.json")).write_text(json.dumps({"terminal_stop": "statement-ready", "statement_sha256": digest}))
    proof = {"case": CASE, "statement_sha256": digest, "ciphertext_sha256": hashlib.sha256(encrypted.read_bytes()).hexdigest()}
    calls = []
    def stopped_provider(argv, **kwargs):
        calls.append(argv)
        if argv[-2:] == ["list", "--json"]: return subprocess.CompletedProcess(argv, 0, json.dumps(live), "")
        assert argv[1:3] == ["ssh", "old"] and "DONE" in argv[3] and "pgrep" in argv[3]
        return subprocess.CompletedProcess(argv, 0, json.dumps(proof), "")
    with mock.patch.object(statement_round, "prepare", return_value={CASE: root / "out"}) as prepare:
        result = inv.tick(policy, capacity, [monitor], root / "snapshot.json", None, "recovery", operation="admit",
                          request=lambda p: status, run=stopped_provider, now=NOW, registry_root=root / "registry", admission_destination=root / "out")
        assert result["action"] == "admission_prepared" and result["delivery_and_authorized_resume_required"]
        prepare.assert_called_once()
        encrypted.write_bytes(b"changed synthetic ciphertext")
        try:
            inv.tick(policy, capacity, [monitor], root / "snapshot.json", None, "recovery", operation="admit",
                     request=lambda p: status, run=stopped_provider, now=NOW, registry_root=root / "registry", admission_destination=root / "out")
        except ValueError: pass
        else: raise AssertionError("collected ciphertext mismatch admitted")
        prepare.assert_called_once()
print("PASS admission tick: stopped public proof, collected ciphertext binding, local preparation only")
