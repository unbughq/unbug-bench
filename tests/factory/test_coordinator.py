"""Coordinator uses synthetic public metadata and a fake holder; no cloud or secrets."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy
import datetime
import hashlib
import json
import os
import pathlib
import tempfile
import time
from unittest import mock

import coordinator as ctrl
import key_holder


def fixture(root):
    now = time.time()
    (root / "sealed").mkdir()
    case = "case-synthetic"
    archive = root / "sealed" / (case + ".checkpoint.tar.gz.age")
    archive.write_bytes(b"synthetic encrypted checkpoint")
    roles = {"strong_calibrator": {"model": "claude/synthetic", "effort": "high", "family": "anthropic"}}
    config = {field: 1 for field in ctrl.CONFIG_FIELDS}
    config.update(version=1, case_budget=50, rounds=1, runs=10, scenario_runs=3, pilot_tries=3, pilot_runs=5,
                  calibrator_minutes=30, max_role_calls=400, max_total_calls=1000, max_cost=5,
                  no_progress_minutes=45, max_zero_tokens=3, agent_timeout=14400, max_repairs=0)
    card = {"case": case, "source": "port", "rotation_slot": 1, "seed": 42, "roles": roles, "status": "stopped", "terminal_stop": "stalled",
            "recovery_config": config, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "continuation_budget": {"calls": 20, "cost": 1.25, "events": [], "terminal_stop": "stalled"}}
    card_path = root / "sealed" / (case + ".scorecard.json")
    def write_card():
        card_path.write_text(json.dumps(card)); os.utime(card_path, (now - 1000, now - 1000))
    write_card()
    job = {"case": case, "mode": "case", "card": card_path.name, "archive_prefix": case,
           "roles": roles, "max_calls": 1000, "max_cost": 5, "claude_accounts": [1, 2],
           "allow_collected_generation_reconciliation": True, "args": ["1", "--restore", case]}
    job["args"] = ctrl.configuration_args(card, job)
    policy = {"jobs": {"synthetic": job}}
    status = {"unlocked": True, "policy_sha256": key_holder.policy_digest(policy), "seconds_remaining": 7200,
              "jobs": {}, "claude_accounts": {"1": True, "2": True}}
    snapshot = {"version": 1, "observed_at": now, "inventory_complete": True, "workers": [],
                "claude_accounts": [{"id": n, "available": True, "capacity": 1, "used": 0,
                                     "models": [{"model": "claude/synthetic", "effort": "high"}]} for n in (1, 2)]}
    journal = root / "coordinator.json"
    requests = []
    def request(payload):
        requests.append(payload)
        if payload == {"op": "status"}: return copy.deepcopy(status)
        return {"started": True, "job": "synthetic", "pid": 123}
    def run(execute=False):
        return ctrl.coordinate(policy, snapshot, journal, "synthetic", execute=execute, now=now, deadline=now + 7200, request=request)
    return locals()


with tempfile.TemporaryDirectory() as temp, mock.patch.object(key_holder, "ROOT", pathlib.Path(temp)):
    f = fixture(pathlib.Path(temp))
    run, snapshot, status, requests = (f[k] for k in ("run", "snapshot", "status", "requests"))
    # This coordinator proves cloud ownership only; model_router alone admits roles.
    snapshot['claude_accounts'][0]['blocked_until'] = f['now'] + 3600
    result = run()
    assert result['action'] == 'launch' and result['claude_account'] is None
    assert not f['journal'].exists() and not any(r['op'] == 'launch' for r in requests)
    result = run(True)
    assert result['action'] == 'started' and 'claude_account' not in requests[-1]
    saved = json.loads(f["journal"].read_text())
    assert saved["actions"][0]["budget_calls"] == 20 and saved["actions"][0]["budget_cost"] == 1.25
    assert run(True)["action"] == "reconcile"  # empty fleet is never proof of a failed start
    assert len([r for r in requests if r["op"] == "launch"]) == 1
    status["jobs"]["synthetic"] = {"pid": 123, "exit": None}
    assert run(True)["action"] == "active"
    status["jobs"]["synthetic"]["exit"] = 1
    assert run(True)["action"] == "reconcile"  # failed launcher may have already created a worker
    status["jobs"].clear()
    # A signed-like claim in caller inventory is insufficient. Only the holder's
    # existing verified collected-successor reconciliation can clear a reservation.
    snapshot["workers"] = [{"id": "synthetic", "case": f["case"], "state": "retired", "archive_verified": True}]
    assert run(True)["action"] == "reconcile"
    f["archive"].write_bytes(b"verified newer synthetic encrypted checkpoint")
    f["card"]["sha256"] = hashlib.sha256(f["archive"].read_bytes()).hexdigest()
    f["card"]["continuation_budget"].update(calls=25, cost=1.5)
    f["write_card"]()
    monitor = pathlib.Path(temp) / ctrl.MONITOR; monitor.parent.mkdir(parents=True)
    monitor.write_text(json.dumps({"workers": [{"id": "synthetic", "case": f["case"], "retired": True,
        "terminal": {"retired": True, "archive_verified": True, "expected_archive_sha256": f["card"]["sha256"],
                     "cumulative_calls": 25, "cumulative_cost": 1.5,
                     "card_mtime_utc": datetime.datetime.fromtimestamp(f["now"] + 1, datetime.timezone.utc).isoformat()}}]}))
    result = run(True)
    assert result["action"] == "started", result
    saved = json.loads(f["journal"].read_text())
    assert saved["actions"][0]["state"] == "collected" and len(saved["actions"]) == 2
    assert saved["actions"][1]["budget_calls"] == 25

for seam in ("reservation", "request"):
    with tempfile.TemporaryDirectory() as temp, mock.patch.object(key_holder, "ROOT", pathlib.Path(temp)):
        f = fixture(pathlib.Path(temp))
        original_save = ctrl.atomic_json
        def interrupted_save(path, journal):
            original_save(path, journal)
            if seam == "reservation": raise KeyboardInterrupt()
        def timeout(payload):
            if payload["op"] == "status": return f["status"]
            raise TimeoutError("uncertain synthetic launch")
        if seam == "reservation":
            with mock.patch.object(ctrl, "atomic_json", interrupted_save):
                try: f["run"](True)
                except KeyboardInterrupt: pass
                else: raise AssertionError("interruption was swallowed")
            assert not any(r["op"] == "launch" for r in f["requests"])
        else:
            result = ctrl.coordinate(f["policy"], f["snapshot"], f["journal"], "synthetic", execute=True,
                                    now=f["now"], deadline=f["now"] + 7200, request=timeout)
            assert result["action"] == "unknown"
        assert f["run"](True)["action"] == "reconcile"
        assert len(json.loads(f["journal"].read_text())["actions"]) == 1

for change, reason in (("paused", "explicit_pause"), ("budget", "unverified_checkpoint_or_budget"),
                       ("config", "original_configuration_not_verified"), ("legacy", "original_configuration_not_verified"),
                       ("model", "model_or_effort_changed"), ("missing", "missing_policy_config")):
    with tempfile.TemporaryDirectory() as temp, mock.patch.object(key_holder, "ROOT", pathlib.Path(temp)):
        f = fixture(pathlib.Path(temp))
        if change == "paused": f["card"]["terminal_stop"] = "paused"
        if change == "budget": f["card"]["continuation_budget"]["calls"] = 1000
        if change == "config": f["card"]["recovery_config"]["pilot_tries"] = 4
        if change == "legacy": f["card"].pop("recovery_config")
        if change == "model": f["card"]["roles"] = {"strong_calibrator": {"model": "claude/different", "effort": "high"}}
        if change == "missing":
            index = f["job"]["args"].index("--pilot-tries"); del f["job"]["args"][index:index+2]
            f["status"]["policy_sha256"] = key_holder.policy_digest(f["policy"])
        f["write_card"]()
        result = f["run"](True)
        assert result["reason"] == reason, (change, result)
        if change == "missing": assert "--pilot-tries" in result["proposed_args"]
        assert not any(r["op"] == "launch" for r in f["requests"])

with tempfile.TemporaryDirectory() as temp, mock.patch.object(key_holder, "ROOT", pathlib.Path(temp)):
    f = fixture(pathlib.Path(temp)); f["snapshot"]["observed_at"] -= 121
    try: f["run"](True)
    except ValueError: pass
    else: raise AssertionError("stale inventory was accepted")
    assert not f["journal"].exists()

with tempfile.TemporaryDirectory() as temp, mock.patch.object(key_holder, "ROOT", pathlib.Path(temp)):
    f = fixture(pathlib.Path(temp))
    f["job"]["claude_accounts"] = [1]
    f["status"]["policy_sha256"] = key_holder.policy_digest(f["policy"])
    f["snapshot"]["claude_accounts"][0]["available"] = False
    f["snapshot"]["claude_accounts"][0]["available"] = True
    assert f["run"](True)["action"] == "started"
    journal = json.loads(f["journal"].read_text())
    journal["actions"][0]["budget_calls"] = 21
    ctrl.atomic_json(f["journal"], journal)
    assert f["run"](True)["reason"] == "cumulative_budget_regressed"
    journal["actions"][0].update(budget_calls=20, state="collected")
    journal["actions"] = [{**journal["actions"][0], "id": str(n)} for n in range(1, 4)]
    ctrl.atomic_json(f["journal"], journal)
    assert f["run"](True)["reason"] == "launch_allowance_exhausted"
    journal["actions"][0]["state"] = "invented"
    ctrl.atomic_json(f["journal"], journal)
    assert f["run"](True)["reason"] == "journal_or_policy_mismatch"

print("PASS coordinator: bounded durable reservations, crash/timeout reconciliation, verified successor, freshness, exact config/model/effort, authorized account takeover, pause and budget blocks")

# Legacy quota rows are ignored; admission is always delegated to model_router.
for provider, model in (("opencode", "opencode-go/synthetic"), ("codex", "codex/synthetic")):
    with tempfile.TemporaryDirectory() as temp, mock.patch.object(key_holder, "ROOT", pathlib.Path(temp)):
        f = fixture(pathlib.Path(temp))
        f['card']['roles']['strong_calibrator']['model'] = model
        f['job']['args'] = ctrl.configuration_args(f['card'], {**f['job'], 'args':['1','--restore',f['case']]})
        f['status']['policy_sha256'] = key_holder.policy_digest(f['policy'])
        f['write_card']()
        result = f['run'](True)
        assert result['action'] == 'started' and provider + '_account' not in result
        assert f['run']()['action'] == 'reconcile'
print('PASS model account scheduling removed; cloud reservation/replay protection retained')
