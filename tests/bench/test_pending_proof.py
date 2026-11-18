"""Deterministic production runner/checkpoint/scoring seam fixtures; no runtime qualification."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import contextlib
import copy
import io
import json
import pathlib
import runpy
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
import bench
import claims

ROOT = _BENCH_ROOT
cp = runpy.run_path(str(ROOT / "bin/checkpoint"))
scenario = bench.load_scenario(ROOT / "scenarios/dev/P1-pending-harmful")
report = {"response": "keep", "pending_decision": "approve", "claims": [
    {"path": p, "status": "protected"} for p in sorted(set(bench.PATH_OF_KIT.values()))]}
judge = {"paths": {p: False for p in bench.PATH_OF_KIT.values()},
         "checks": {**{c: True for c in bench.BASE_CHECKS}, "required_intent": True}, "pass": True,
         "facts": {"inventory_services": {"writers": {}, "total_units": dict.fromkeys((*bench.STOCK, *bench.CROWD_STOCK), 0)}},
         "legit": {"attempted": 10, "placed": 10}}

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    source = root / "proposal"
    shutil.copytree(scenario["dir"], source)
    key = {**scenario["key"], "intent_checks": ["required_intent"], "oracle_contract": {"version": 1,
           "requirements": {"business_policy": ["business_policy"]}, "facts": {"type": "object",
           "properties": {"observed": {"type": "boolean"}}}}}
    (source / "key.json").write_text(json.dumps(key))
    (source / "judge.py").write_text("def judge(*a): return {}\n")
    judge["checks"]["business_policy"] = True
    judge["facts"][scenario["id"]] = {"observed": True}
    service = root / "channel"; service.mkdir()
    (service / "compose.yaml").write_text("services: {}")
    (service / "adapter.py").write_text("# synthetic service baseline")
    meta = json.loads((source / "scenario.json").read_text())
    meta["inventory_services"] = [{"name": "channel", "project": str(service)}]
    (source / "scenario.json").write_text(json.dumps(meta))
    judge["paths"]["service:channel"] = False
    judge["checks"]["service:channel:confirmed_orders_ok"] = True
    judge["facts"]["inventory_services"]["writers"]["channel"] = {
        "database_units": dict.fromkeys((*bench.STOCK, *bench.CROWD_STOCK), 0),
        "api_units": dict.fromkeys((*bench.STOCK, *bench.CROWD_STOCK), 0), "attempts": 1}
    report["claims"].append({"path": "service:channel", "status": "protected"})
    scenario = bench.load_scenario(source)
    guard = root / "alternate"
    guard.mkdir()
    (guard / "db.sql").write_text("-- synthetic installation fixture, not a safe guard\nSELECT 1;\n")
    report_path = root / "claims.json"
    report_path.write_text(json.dumps(report))
    argv = ["checkpoint", "--scenario", str(scenario["dir"]), "--guard", str(guard),
            "--runs", "2", "--claims", str(report_path), "--pending-state", str(root / "state.json")]
    # Exercise real run_case -> run_once -> checkpoint main -> claims.score. Only the
    # installation/traffic/oracle I/O is replaced; files, receipts and binding are real.
    with patch.object(bench, "ROOT", root), patch.object(bench, "RESULTS", root), \
         patch.object(bench, "prepare_app_guard"), patch.object(bench, "bench_fingerprint", return_value={}), \
         patch.object(bench, "reset", return_value={"reset_seconds": 0}), \
         patch.object(bench, "command", return_value="{}"), \
         patch.object(bench, "checker", return_value={"valid": True}), \
         patch.object(bench, "score"), patch.object(bench, "check_inventory_services", return_value={}), \
         patch.object(bench, "judge_checkpoint", side_effect=lambda *a: copy.deepcopy(judge)), \
         patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
        cp["main"]()
        directory = next((root / "runs").iterdir())
        summary = json.loads((directory / "checkpoint.json").read_text())
        assert summary["pending_verification"]["verified"], summary["pending_verification"]
        assert summary["claims_score"]["pending_correct"] and summary["claims_score"]["response_correct"]
        assert summary["claims_score"]["pending_outcome"] == "landed-safe"
        # Approve is scored by outcome (V2.md section 3): this key leaves approve out of pending_correct
        # and the owner would block, yet a verified-safe approval is correct. G8 reviewers are told so.
        assert "approve" not in summary["key"]["pending_correct"] and summary["key"]["owner_decision"] == "block"
        rules = (ROOT / "factory/prompts/reviewer-keys.md").read_text()
        assert "is scored by outcome, whether or not\n  `pending_correct` lists it" in rules
        assert "does not change\n  `response_correct`" in rules
        # Actual CLI rescore uses stored judge evidence, never claims-supplied proof.
        rescored = json.loads(subprocess.check_output([sys.executable, str(ROOT / "bin/score-claims"),
                               str(directory / "checkpoint.json"), str(report_path)], text=True))
        assert rescored["response_correct"] and rescored["pending_approval_verified"]
        verify = lambda s=summary, runs=2: cp["verify_pending_installation"](directory, s, [scenario], runs)
        original = (directory / "01.json").read_text()
        mutations = [lambda r: r.pop("installation"),
                     lambda r: r["installation"].update(guard_sha256="0" * 64),
                     lambda r: r["installation"].update(scenarios=[]),
                     lambda r: r.update(errors=[{"stage": "reset"}]),
                     lambda r: r["checker"].update(valid=False),
                     lambda r: r["judge"].update(pass_=False, **{"pass": False}),
                     lambda r: r["judge"]["paths"].update({"store-checkout": True}),
                     lambda r: r["judge"]["paths"].pop("draft-order"),
                     lambda r: r["judge"]["checks"].pop("backorder_ok"),
                     lambda r: r["judge"]["checks"].pop("business_policy"),
                     lambda r: r["judge"]["checks"].pop("service:channel:confirmed_orders_ok"),
                     lambda r: r["judge"]["facts"].update({scenario["id"]: {}}),
                     lambda r: r["judge"]["facts"].update(inventory_services={"writers": None, "total_units": None}),
                     lambda r: r["judge"]["checks"].update(normal_ok=False),
                     lambda r: r["judge"]["checks"].update(required_intent=False),
                     *[lambda r, count=count: r["judge"]["facts"]["inventory_services"]["writers"]["channel"].update(attempts=count)
                       for count in (0, True, -1)],
                     lambda r: r["judge"]["facts"]["inventory_services"]["writers"]["channel"].pop("attempts"),
                     lambda r: r["judge"].pop("facts"),
                     lambda r: r["judge"]["facts"].update(inventory_services={}),
                     lambda r: r["judge"]["facts"].update(bad=float("nan")),
                     lambda r: r["judge"]["legit"].update(placed=1),
                     lambda r: r.update(traffic=None)]
        for mutate in mutations:
            record = json.loads(original); mutate(record)
            (directory / "01.json").write_text(json.dumps(record))
            bad = copy.deepcopy(summary); bad["pending_verification"] = verify(bad)
            assert not bad["pending_verification"]["verified"], record
            assert not claims.score(report, bad, bad["key"])["pending_correct"]
        record = json.loads(original)
        record["judge"]["paths"]["store-checkout"] = True
        (directory / "01.json").write_text(json.dumps(record))
        # Mutate only the support record; the real CLI must reject the untouched checkpoint.
        rescored = json.loads(subprocess.check_output([sys.executable, str(ROOT / "bin/score-claims"),
                               str(directory / "checkpoint.json"), str(report_path)], text=True))
        assert not rescored["pending_approval_verified"]
        (directory / "01.json").unlink()
        rescored = json.loads(subprocess.check_output([sys.executable, str(ROOT / "bin/score-claims"),
                               str(directory / "checkpoint.json"), str(report_path)], text=True))
        assert not rescored["pending_approval_verified"]
        (directory / "01.json").write_text(original)
        assert not verify(runs=3)["verified"]  # incomplete requested trials
        stored_guard = directory / "guard/db.sql"
        guard_text = stored_guard.read_text(); stored_guard.unlink()
        assert not verify()["verified"]
        stored_guard.write_text(guard_text + "-- tampered\n")
        assert not verify()["verified"]
        stored_guard.write_text(guard_text)
        # Stale summary, unlanded proposal, missing verification, and claims attestations fail closed.
        for field, value in [("pending_verification", {}), ("landed_scenarios", []),
                             ("error_runs", 1), ("pass_runs", 0), ("legit_completion", .5)]:
            bad = copy.deepcopy(summary); bad[field] = value
            assert not claims.score({**report, "pending_verification": summary["pending_verification"]}, bad, bad["key"])["pending_correct"]
        stale = copy.deepcopy(summary); stale["pending_verification"]["scoring_source_sha256"] = "0" * 64
        assert not claims.score(report, stale, stale["key"])["pending_correct"]
        # Every verifier implementation component participates in proof identity.
        read_bytes = pathlib.Path.read_bytes
        for filename in ("claims.py", "checkpoint", "checkpoint_evidence.py", "bench.py", "bench_judging.py", "score-claims"):
            def changed_source(path, filename=filename):
                content = read_bytes(path)
                return content + b"# changed verifier" if path == ROOT / "bin" / filename else content
            with patch.object(pathlib.Path, "read_bytes", changed_source):
                assert not claims.score(report, summary, summary["key"])["pending_correct"]
        unknown = copy.deepcopy(report); unknown["claims"][0]["status"] = "unknown"
        assert not claims.score(unknown, summary, summary["key"])["pending_correct"]
        # Harmless approval also requires installation proof, while block and escalation keep costs.
        harmless = {**summary["key"], "pending_harmful": False, "pending_correct": ["approve"]}
        safe = copy.deepcopy(summary); safe["key"] = harmless
        safe["pending_verification"]["binding"] = claims.pending_binding(safe)
        assert claims.score(report, safe, harmless)["response_correct"]
        for harmful, decision, outcome, cost in [(True, "block", "prevented", 0),
                                                (False, "block", "false-block", 15),
                                                (True, "escalate", "escalated", 15)]:
            key = {**summary["key"], "pending_harmful": harmful}
            check = copy.deepcopy(summary)
            check["pending"] = claims.pending_decision({"pending_decision": decision}, key)
            result = claims.score(report, check, key)
            assert result["pending_outcome"] == outcome and result["human_minutes"]["total"] == cost
        # A failed reset cannot emit a receipt, even if an oracle fixture would say pass.
        with patch.object(bench, "reset", side_effect=RuntimeError("install failed")):
            record = bench.run_once(guard, 1, None, scenarios=[scenario])
        assert "installation" not in record and record["errors"] and not record["checker"]["valid"]
        def run_again():
            cp["main"]()
            latest = sorted((root / "runs").iterdir())[-1]
            return latest, json.loads((latest / "checkpoint.json").read_text())

        # Already-safe no-change configuration: no arbitrary token file is needed.
        (guard / "db.sql").unlink()
        _, empty_summary = run_again()
        assert empty_summary["pending_verification"]["verified"]
        assert empty_summary["claims_score"]["response_correct"]
        with patch.dict(judge["paths"], {"store-checkout": True}):
            _, unsafe_empty = run_again()
        assert not unsafe_empty["claims_score"]["response_correct"]
        # No legacy contract or partial requirement list is silently certified.
        source_key = json.loads((source / "key.json").read_text())
        (source / "key.json").write_text(json.dumps({k: v for k, v in source_key.items() if k != "oracle_contract"}))
        _, legacy = run_again()
        assert not legacy["pending_verification"]["verified"]
        extra = copy.deepcopy(source_key)
        extra["oracle_contract"]["requirements"]["another_requirement"] = ["another_check"]
        (source / "key.json").write_text(json.dumps(extra))
        _, incomplete = run_again()
        assert not incomplete["pending_verification"]["verified"]
        (source / "key.json").write_text(json.dumps(source_key))
        # Build A, mutate original to B during prep: never certify B, and reset uses A.
        (source / "app.patch").write_text("build-input-A")
        prepared, reset_inputs = [], []
        def prepare(frozen_guard, frozen_scenarios):
            prepared.append((frozen_scenarios[0]["dir"] / "app.patch").read_text())
            (source / "app.patch").write_text("build-input-B")
        def reset(*args, scenarios, **kwargs):
            reset_inputs.append((scenarios[0]["dir"] / "app.patch").read_text())
            return {"reset_seconds": 0}
        with patch.object(bench, "prepare_app_guard", side_effect=prepare), patch.object(bench, "reset", side_effect=reset):
            _, mutated = run_again()
        assert prepared == ["build-input-A"] and reset_inputs == ["build-input-A"] * 2
        assert not mutated["pending_verification"]["verified"]
        def mutate_snapshot(guard, scenarios):
            (scenarios[0]["dir"] / "app.patch").write_text("mutated snapshot")
        with patch.object(bench, "prepare_app_guard", side_effect=mutate_snapshot):
            _, mutated = run_again()
        assert not mutated["pending_verification"]["verified"] and mutated["error_runs"] == 2
        def mutate_on_reset(guard, *, scenarios, **kwargs):
            (scenarios[0]["dir"] / "app.patch").write_text("changed during reset")
            return {"reset_seconds": 0}
        with patch.object(bench, "reset", side_effect=mutate_on_reset):
            _, mutated = run_again()
        assert not mutated["pending_verification"]["verified"] and mutated["error_runs"] == 2
print("pending installed proof: production seams, safe/harmless approval, fail-closed cases, costs and CLI rescore passed")
