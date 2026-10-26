"""Content-free diagnostics and real calibrate() control flow; no Docker or model calls."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse
import json
import pathlib
import shutil
import sys
import tempfile
from unittest import mock
from contextlib import nullcontext

sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory")))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "bin"))
from calibration import attempt_summary, interruption_label
import run
import bench
import exam_responder

# Stop and outcome are independent, including a timed-out solver that leaves a good fix.
rows = [
    {"solved": True, "stop_reason": "time_limit"},
    {"solved": False, "stop_reason": "call_limit", "guard_submitted": False},
    {"solved": False, "stop_reason": "completed", "checked_runs": 5, "solved_runs": 2, "errors": 0},
    {"solved": False, "checked_runs": 5, "solved_runs": 0, "errors": 0},
    {"solved": False, "checked_runs": 5, "solved_runs": 1, "errors": 1},
]
s = attempt_summary(rows)
assert (s["tries"], s["solved"]) == (5, 1)
assert s["diagnostics"]["stop_reasons"] == {"completed": 1, "time_limit": 1, "call_limit": 1, "unrecorded": 2}
assert s["diagnostics"]["outcomes"] == {"solved": 1, "no_fix_submitted": 1, "fix_failed_some_runs": 1,
                                      "fix_failed_all_runs": 1, "fix_failed_runs": 0, "run_error": 1, "unknown": 0}

# Legacy data is not invented, and arbitrary sealed strings never reach the report.
secret = "SYNTHETIC_PRIVATE_DETAIL"
legacy = [{"solved": False, "why": "no guard written (timeout)"},
          {"solved": False, "guard": secret, "errors": 0, "failed_checks": [secret]},
          {"solved": False, "why": secret, "stop_reason": secret}]
s = attempt_summary(legacy)
assert secret not in json.dumps(s)
assert s["diagnostics"]["stop_reasons"]["unrecorded"] == 2
assert s["diagnostics"]["outcomes"]["fix_failed_runs"] == 1
assert s["diagnostics"]["outcomes"]["unknown"] == 1
for bad in ({}, [{"solved": secret}], [{"solved": 1}]):
    try: attempt_summary(bad)
    except ValueError: pass
    else: raise AssertionError("malformed results must not leak or become solve counts")
for reason, want in [("provider_limit:" + secret, "provider_limit"), ("process_error", "model_process_error"),
                     ("usage_monitor:" + secret, "usage_monitor_error"), (secret, "unknown"),
                     ("Budget stopped: cost_limit", "cost_limit"),
                     ("Budget stopped: total_call_limit", "total_call_limit"),
                     ("Budget ledger stopped: provider_limit:" + secret, "provider_limit")]:
    assert interruption_label(run.BudgetError(reason)) == want
assert interruption_label(run.BudgetError("timeout")) == "time_limit"
assert interruption_label(run.BudgetError("Budget stopped: call_limit")) == "call_limit"

# Exercise the real attempt writer, cap handling, aggregate publication and resume path.
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    app = root / "bench/projects/medusa"; app.mkdir(parents=True)
    (app / "fixture.js").write_text("synthetic app")
    protocol = root / "bench/harbor/responder"
    protocol.mkdir(parents=True)
    for name in ("responder.py", "ask-human"):
        (protocol / name).write_text("synthetic protocol identity")
    pilot = root / "pilot"; pilot.mkdir()
    def shell(c, argv, **kwargs):
        if argv[:3] == ["sudo", "cp", "-a"] and pathlib.Path(argv[3]).exists():
            shutil.copytree(argv[3], argv[4])
    for mode in ("partial", "timed_success", "no_fix", "provider_stop"):
        c = run.Ctx(); c.work = root / mode; c.work.mkdir()
        c.case = c.work / "case"; (c.case / "base").mkdir(parents=True)
        for f in ("promise.md", "contestant.md"): (c.case / f).write_text("synthetic public contract")
        c.args = argparse.Namespace(pilot_tries=1, pilot_runs=5, calibrator_minutes=30, resume=None)
        c.models = {"strong_calibrator": ["synthetic/strong"], "reviewers": [["synthetic/reviewer"]]}
        c.seed = 3; c.card = {}; c.pilot_passes = []
        c.force_budget_resume = False
        def model(c, models, text, dest, name, **kwargs):
            if mode == "provider_stop": raise run.BudgetError("provider_limit:" + secret)
            if mode != "no_fix":
                (dest / "guard").mkdir(); (dest / "guard/db.sql").write_text("-- synthetic")
            if mode in ("timed_success", "no_fix"): raise run.BudgetError("timeout")
            return 0
        verdicts = [{"clean": True, "solved": mode == "timed_success" or i < 2} for i in range(5)]
        with mock.patch.object(exam_responder, "owner_channel", lambda *a: nullcontext("synthetic owner")), \
             mock.patch.object(run, "BENCH", root / "bench"), mock.patch.object(run, "pilot_home", return_value=pilot), \
             mock.patch.object(run, "sh", shell), mock.patch.object(run, "shred_tree", lambda p, **kw: shutil.rmtree(p) if p.exists() else None), \
             mock.patch.object(bench, "load_scenario", return_value={}), mock.patch.object(bench, "reset"), \
             mock.patch.object(run, "model_call", model), mock.patch.object(run, "prompt", return_value="synthetic"), \
             mock.patch.object(run, "checkpoint", return_value=(None, [{}] * 5)), mock.patch.object(run, "verdicts", return_value=verdicts):
            if mode == "provider_stop":
                try: run.calibrate(c, "strong_calibrator")
                except run.BudgetError: pass
                else: raise AssertionError("provider stops must not become scored failures")
                assert not (c.work / "strong_calibrator/results.json").exists()
                assert c.card["calibration_interruptions"] == {"strong_calibrator": {"provider_limit": 1}}
                assert secret not in json.dumps(c.card)
                shutil.rmtree(pilot / "strong_calibrator-try-1")
                continue
            result = run.calibrate(c, "strong_calibrator")
            saved = json.loads((c.work / "strong_calibrator/results.json").read_text())
            assert result["solved"] == (1 if mode == "timed_success" else 0)
            assert c.card["calibration_progress"]["strong_calibrator"] == result
            assert saved[0]["stop_reason"] == ("completed" if mode == "partial" else "time_limit")
            want = {"partial": "fix_failed_some_runs", "timed_success": "solved", "no_fix": "no_fix_submitted"}[mode]
            assert result["diagnostics"]["outcomes"][want] == 1
            # Cached attempts retain their outcomes without any new call or reset.
            c.args.resume = "synthetic"
            with mock.patch.object(run, "model_call") as caller:
                cached = run.calibrate(c, "strong_calibrator")
                caller.assert_not_called()
                assert cached == {**result, "kept": True}

print("PASS calibration diagnostics: redaction, legacy uncertainty, caps, judged outcomes, interrupted calls and resume")
