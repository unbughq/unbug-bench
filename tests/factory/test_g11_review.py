"""Offline audit-output redaction checks; no private case or model calls."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import pathlib
import sys
import tempfile
from unittest import mock
sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory")))
from g11_review import public_verdict, digest, legacy_digest

secret = "SYNTHETIC_PRIVATE_CASE_DETAIL"
for labels, expected in [(["checker_false_positive"] * 2, "checker_false_positive"),
                         (["rule_violation"] * 2, "rule_violation"),
                         (["rule_violation", "checker_false_positive"], "inconclusive")]:
    out = public_verdict({"fixes": [{"classification": label, "evidence": secret} for label in labels]}, 2)
    assert out["verdict"] == expected and secret not in json.dumps(out)
for bad in [None, {}, {"fixes": []}, {"fixes": [{"classification": secret}]}]:
    try: public_verdict(bad, 1)
    except ValueError: pass
    else: raise AssertionError("malformed review must not become a public verdict")
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp); p = root / "fixture"; p.write_text("before")
    before = digest([root]); p.write_text("after")
    assert digest([root]) != before
print("PASS G11 review labels, mixed/malformed verdicts, redaction and input drift")
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp); (root / "a").write_text("b"); (root / "b").write_text("different contents")
    old, framed = legacy_digest([root]), digest([root])
    (root / "a").unlink(); (root / "a").symlink_to("b")
    assert legacy_digest([root]) == old and digest([root]) != framed
    (root / "a").unlink(); (root / "a").write_bytes(b"x"); (root / "b").write_bytes(b"b\0y")
    old, framed = legacy_digest([root]), digest([root])
    (root / "a").write_bytes(b"xb\0"); (root / "b").write_bytes(b"y")
    assert legacy_digest([root]) == old and digest([root]) != framed
print("PASS framed digests reject symlink/type substitution and ambiguous file boundaries")

# Audit dispatch happens before the normal builder, Docker setup, or any case gate.
import run
import g11_review
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp); (root / "work/case-synthetic/case").mkdir(parents=True)
    argv = ["run.py", "--source", "port", "--resume", "case-synthetic", "--resume-bench-sha", "0" * 64, "--audit-g11"]
    with mock.patch.object(sys, "argv", argv), mock.patch.object(run, "HOME", root), \
         mock.patch.object(run, "bench_manifest", return_value="0" * 64), \
         mock.patch.object(g11_review, "review") as audit, mock.patch.object(run, "build") as build, \
         mock.patch.object(run, "sh") as command:
        run.main()
        audit.assert_called_once(); build.assert_not_called(); command.assert_not_called()
print("PASS audit dispatch bypasses build and gates")

# Real audit flow with a fake model/sealer: caps, interruption, integrity and public outputs.
import argparse
import types
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    for mode in ("success", "interrupted", "changed", "copy_changed", "preparation_interrupted", "interrupted_seal_failure"):
        original = root / mode / "case-synthetic"; (original / "case").mkdir(parents=True)
        (original / "case/contract.md").write_text(secret)
        guard = original / "guard"; guard.mkdir(); (guard / "db.sql").write_text("-- synthetic")
        evidence = original / "bench-results/fake-pass"; evidence.mkdir(parents=True)
        (evidence / "report.json").write_text(json.dumps({"guards": [{"guard": str(guard)}]}))
        roles = {"reviewer": {"model": "openrouter/meta/synthetic"}, "writer": {"model": "claude/synthetic"},
                 "strong_calibrator": {"model": "codex/synthetic"}}
        prior = {"failed_gate": "G11", "roles": roles}
        (original / "scorecard.json").write_text(json.dumps(prior))
        sealed = root / mode / "sealed"; sealed.mkdir()
        ledger = sealed / "case-synthetic.continuation-budget.json"
        ledger.write_text(json.dumps({"cost": 0.25, "calls": 20, "active": []}))
        def load(p, default=None):
            try: return json.loads(pathlib.Path(p).read_text())
            except (OSError, ValueError): return default
        def model(c, models, prompt, cwd, name):
            assert models == [roles["reviewer"]["model"]]
            assert (c.args.max_cost, c.args.max_total_calls, c.args.max_role_calls, c.args.agent_timeout) == (0.75, 100, 80, 1200)
            if mode == "interrupted": raise run.BudgetError("cost_limit")
            if mode == "interrupted_seal_failure": raise run.BudgetError('codex_login_expired')
            (cwd / "verdict.json").write_text(json.dumps({"fixes": [{"classification": "checker_false_positive", "evidence": secret}]}))
            if mode == "changed": (guard / "db.sql").write_text("changed")
            if mode == "copy_changed": (cwd / "fixes/0/db.sql").write_text("changed")
        def seal(c):
            if mode == 'interrupted_seal_failure': raise OSError(secret)
            assert (c.work / "verdict.json").exists() or mode in ("interrupted", "preparation_interrupted")
            c.card["sha256"] = "a" * 64
        factory = types.SimpleNamespace(jload=load, family=run.family, bench_manifest=lambda: "bench-sha",
            SEALED=sealed, BENCH=root / "bench", PROMPTS=root / "factory/prompts", FOUNDER_RECIPIENT="synthetic-recipient",
            pause_on_term=run.pause_on_term, PauseRequested=run.PauseRequested, opencode=model, seal=seal)
        c = run.Ctx(); c.work = original; c.case = original / "case"; c.case_id = "case-synthetic"
        c.args = argparse.Namespace(reviewer1=None, max_cost=5, max_total_calls=2000, max_role_calls=400, agent_timeout=3600)
        if mode == "preparation_interrupted":
            with mock.patch.object(g11_review.shutil, "copytree", side_effect=run.PauseRequested()):
                g11_review.review(c, factory)
        else: g11_review.review(c, factory)
        public = load(sealed / "g11-review-case-synthetic.scorecard.json")
        assert secret not in json.dumps(public)
        assert (sealed / "DONE").read_text().strip() == "g11-review-case-synthetic"
        assert load(original / "scorecard.json") == prior
        assert public["status"] == {"success": "complete", "interrupted": "stopped", "changed": "invalidated", "copy_changed": "invalidated", "preparation_interrupted": "stopped", "interrupted_seal_failure":"stopped"}[mode]
        if mode == 'interrupted_seal_failure':
            assert public['terminal_stop'] == 'codex_login_expired' and public['checkpoint_error'] == 'OSError'
        assert public["verdict"] == ("checker_false_positive" if mode == "success" else "inconclusive")
print("PASS audit caps, separate reports, interrupted sealing, protected-input drift and unchanged original gate")

# A resumed audit needs only its sealed audit tree, never a rebuilt case or reset ledger.
with tempfile.TemporaryDirectory() as tmp:
    for mode in ("resume", "tampered", "bench_changed", "ledger_changed", "exhausted", "legacy_resume", "legacy_collision", "legacy_evidence_collision"):
        root = pathlib.Path(tmp) / mode; original = root / "case-synthetic"
        (original / "case").mkdir(parents=True); (original / "case/contract.md").write_text(secret)
        guard = original / "guard"; guard.mkdir(); (guard / "db.sql").write_text("-- synthetic")
        reports = original / "bench-results/fake-pass"; reports.mkdir(parents=True)
        (reports / "report.json").write_text(json.dumps({"guards": [{"guard": str(guard)}]}))
        roles = {"reviewer": {"model": "openrouter/meta/synthetic"}, "writer": {"model": "claude/synthetic"},
                 "strong_calibrator": {"model": "codex/synthetic"}}
        (original / "scorecard.json").write_text(json.dumps({"failed_gate": "G11", "roles": roles}))
        sealed = root / "sealed"; sealed.mkdir(); ledger = sealed / "case-synthetic.continuation-budget.json"
        ledger.write_text(json.dumps({"cost": .25, "calls": 20, "active": []}))
        calls = []
        def load(p, default=None):
            try: return json.loads(pathlib.Path(p).read_text())
            except (OSError, ValueError): return default
        def model(c, models, prompt, cwd, name):
            calls.append(c.args.continue_g11_review)
            if not c.args.continue_g11_review:
                (cwd / "transcripts/prior.jsonl").write_text(secret)
                (cwd / "notes.txt").write_text(secret)
                (cwd / "verdict.json").write_text(json.dumps({"fixes": [{"classification": "rule_violation"}]}))
                ledger.write_text(json.dumps({"cost": .32, "calls": 49, "active": [], "terminal_stop": "timeout"}))
                raise run.BudgetError("timeout")
            assert (c.args.max_cost, c.args.max_total_calls, c.args.max_role_calls, c.args.agent_timeout) == (.75, 100, 51, 1200)
            assert (cwd / "notes.txt").read_text() == secret and "transcripts/prior.jsonl" in prompt
            assert not (cwd / "verdict.json").exists() and (cwd / "history/verdict-1.json").is_file()
            assert (original / "case").exists() == mode.startswith("legacy_")
            (cwd / "verdict.json").write_text(json.dumps({"fixes": [{"classification": "checker_false_positive", "evidence": secret}]}))
            ledger.write_text(json.dumps({"cost": .33, "calls": 51, "active": [], "terminal_stop": "complete"}))
        def seal(c):
            (c.work / "scorecard.json").write_text(json.dumps(c.card))
            c.card["sha256"] = "a" * 64
        factory = types.SimpleNamespace(jload=load, family=run.family, bench_manifest=lambda: "bench-sha",
            SEALED=sealed, BENCH=root / "bench", PROMPTS=root / "factory/prompts", FOUNDER_RECIPIENT="synthetic-recipient",
            pause_on_term=run.pause_on_term, PauseRequested=run.PauseRequested, opencode=model, seal=seal)
        def context(continuing):
            c = run.Ctx(); c.work = original; c.case = original / "case"; c.case_id = "case-synthetic"
            c.args = argparse.Namespace(continue_g11_review=continuing, reviewer1=None, max_cost=5,
                max_total_calls=2000, max_role_calls=400, agent_timeout=3600, resume="case-synthetic")
            return c
        g11_review.review(context(False), factory)
        stopped = load(original / "g11-audit/scorecard.json")
        assert stopped["terminal_stop"] == "time_limit" and stopped["inputs_unchanged"] is True
        import shutil
        if mode.startswith("legacy_"):
            stopped["digest_version"] = 1
            stopped["source_inputs_sha256"] = legacy_digest([original / "case", guard])
            stopped["audit_inputs_sha256"] = legacy_digest([original / "g11-audit" / n for n in ("case", "fixes", "evidence")])
            (original / "g11-audit/scorecard.json").write_text(json.dumps(stopped))
            if mode == "legacy_collision":
                copied = original / "g11-audit/fixes/0/db.sql"; copied.unlink(); copied.symlink_to("-- synthetic")
            if mode == "legacy_evidence_collision":
                copied = original / "g11-audit/evidence/fake-pass.json"; value = copied.read_text()
                copied.unlink(); copied.symlink_to(value)
        else:
            for path in (original / "case", guard, original / "bench-results"): shutil.rmtree(path)
        if mode == "tampered": (original / "g11-audit/fixes/0/db.sql").write_text("tampered")
        if mode == "bench_changed": factory.bench_manifest = lambda: "different-bench"
        if mode == "ledger_changed": ledger.write_text(json.dumps({"cost": .25, "calls": 20}))
        if mode == "exhausted":
            stopped["limits"]["max_total_calls"] = 49
            (original / "g11-audit/scorecard.json").write_text(json.dumps(stopped))
        if mode in ("ledger_changed", "exhausted"):
            try: g11_review.review(context(True), factory)
            except ValueError: pass
            else: raise AssertionError("bad or exhausted saved ledger must stop before the model")
        else:
            g11_review.review(context(True), factory)
            result = load(sealed / "g11-review-case-synthetic.scorecard.json")
            assert secret not in json.dumps(result)
            if mode in ("resume", "legacy_resume"):
                assert calls == [False, True] and result["status"] == "complete"
                assert result["verdict"] == "checker_false_positive" and result["inputs_unchanged"] is True
                assert result["limits"]["max_cost"] == .75 and result["limits"]["max_total_calls"] == 100
                assert result["continuation_budget"]["calls"] == 51 and result["audit_calls_total"] == 31
                assert abs(result["audit_cost_total"] - .08) < 1e-9
                assert result["digest_version"] == 2
            else:
                assert result["status"] == "stopped" and result["inputs_unchanged"] is False
        if mode not in ("resume", "legacy_resume"): assert calls == [False]
print("PASS audit continuation preserves notes, cumulative limits, prior spending and input identities; rejects reset/exhausted ledgers")

# Standalone restored audit dispatch has no original case tree or Docker setup.
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp); (root / "work/case-synthetic/g11-audit/case").mkdir(parents=True)
    argv = ["run.py", "--source", "port", "--resume", "case-synthetic", "--resume-bench-sha", "0" * 64, "--continue-g11-review"]
    with mock.patch.object(sys, "argv", argv), mock.patch.object(run, "HOME", root), \
         mock.patch.object(run, "bench_manifest", return_value="0" * 64), \
         mock.patch.object(g11_review, "review") as audit, mock.patch.object(run, "build") as build, mock.patch.object(run, "sh") as command:
        run.main(); audit.assert_called_once(); build.assert_not_called(); command.assert_not_called()
print("PASS standalone continuation bypasses builders, original-case requirement and gates")

# A failed seal must not make audit-only private work look empty to the collector.
with tempfile.TemporaryDirectory() as tmp:
    import os, subprocess
    root = pathlib.Path(tmp); (root / "factory").mkdir(); (root / "bin").mkdir()
    import shutil
    shutil.copy((pathlib.Path(__file__).resolve().parents[2] / "factory") / "collect.sh", root / "factory/collect.sh")
    vm = root / "vm"; private = vm / "work/case-synthetic/g11-audit/case"; private.mkdir(parents=True)
    (private / "promise.md").write_text(secret)
    fake = root / "bin/boat-call"
    fake.write_text('''#!/usr/bin/env python3
import os, subprocess, sys
assert sys.argv[1] == "ssh", "unsealed audit must not be copied as plaintext"
command = sys.argv[3]
if command.startswith("if [ ! -f ~/sealed/DONE ]"): sys.exit(0)
sys.exit(subprocess.run(["/bin/sh", "-c", command], env=os.environ.copy()).returncode)
'''); fake.chmod(0o755)
    result = subprocess.run(["/bin/sh", str(root / "factory/collect.sh"), "synthetic-vm"],
        env={**os.environ, "HOME": str(vm)}, capture_output=True, text=True)
    assert result.returncode == 1 and "holds unsealed case work" in result.stderr
    assert secret not in result.stdout + result.stderr and (private / "promise.md").is_file()
print("PASS collector refuses to retire unsealed audit-only work")
