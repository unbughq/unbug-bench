"""Synthetic durable calibration checks; no Docker, providers or sealed case data."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack, nullcontext
from unittest import mock

sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory")))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "bin"))
import run
import bench
import exam_responder
import calibration
from calibration import atomic_results


def exercise(root, *, solved=False):
    c = run.Ctx(); c.work = root / "work"; c.work.mkdir()
    c.case = c.work / "case"; (c.case / "base").mkdir(parents=True)
    for name in ("promise.md", "contestant.md"): (c.case / name).write_text("synthetic contract")
    c.args = argparse.Namespace(pilot_tries=3, pilot_runs=2, calibrator_minutes=30, resume=None)
    c.models = {"strong_calibrator": ["synthetic/strong"], "reviewers": [["synthetic/reviewer"]]}
    c.seed = 7; c.card = {}; c.pilot_passes = []
    app = root / "bench/projects/medusa"; app.mkdir(parents=True); (app / "fixture.js").write_text("app")
    protocol = root / "bench/harbor/responder"
    protocol.mkdir(parents=True)
    for name in ("responder.py", "ask-human"):
        (protocol / name).write_text("synthetic protocol identity")
    home = root / "pilot"; home.mkdir()
    calls, seeds = [], []
    def shell(c, argv, **kwargs):
        if argv[:3] == ["sudo", "cp", "-a"] and pathlib.Path(argv[3]).exists(): shutil.copytree(argv[3], argv[4])
    def model(c, models, text, dest, name, **kwargs):
        calls.append(name)
        (dest / "guard").mkdir(); (dest / "guard/db.sql").write_text("-- synthetic " + name)
    def checkpoint(c, scenarios, guard, runs, seed, label):
        seeds.append(seed); return None, [{}] * runs
    stack = ExitStack()
    for owner, name, value in [(exam_responder, "owner_channel", lambda *a: nullcontext("synthetic owner channel")),
            (run, "BENCH", root / "bench"), (run, "pilot_home", lambda _: home),
            (run, "sh", shell), (run, "shred_tree", lambda p, **kw: shutil.rmtree(p) if p.exists() else None),
            (bench, "load_scenario", lambda _: {}), (bench, "reset", lambda *a, **kw: None),
            (run, "model_call", model), (run, "prompt", lambda *a: "synthetic prompt"),
            (run, "try_checkpoint", checkpoint), (run, "verdicts", lambda c, records: [{"clean": True, "solved": solved}] * len(records))]:
        stack.enter_context(mock.patch.object(owner, name, value))
    return c, stack, calls, seeds


with tempfile.TemporaryDirectory() as tmp:
    c, stack, calls, seeds = exercise(pathlib.Path(tmp))
    stale = pathlib.Path(tmp) / 'pilot/strong_calibrator-try-1/guard'
    stale.mkdir(parents=True); (stale / 'db.sql').write_text('-- stale interrupted guard')
    with stack:
        result = run.calibrate(c, 'strong_calibrator', tries=1)
    assert result['tries'] == 1 and len(calls) == 1
    row = json.loads((c.work / 'strong_calibrator/results.json').read_text())[0]
    assert pathlib.Path(row['guard']).joinpath('db.sql').read_text() == '-- synthetic strong-calibrator-strong_calibrator-1'
    assert not (pathlib.Path(row['workspace']) / 'try-1').exists(), 'cp must never nest into an interrupted destination'


with tempfile.TemporaryDirectory() as tmp:
    c, stack, calls, seeds = exercise(pathlib.Path(tmp))
    c.ledger = c.work / "continuation-budget.json"
    ledger_bytes = b'{"cost":1.25,"calls":37,"events":[]}'
    c.ledger.write_bytes(ledger_bytes)
    with stack:
        # A hard process death immediately after the first durable commit cannot erase it.
        import os, signal
        child = os.fork()
        if child == 0:
            def commit_then_kill(path, rows):
                atomic_results(path, rows)
                if pathlib.Path(path).name == 'results.json': os.kill(os.getpid(), signal.SIGKILL)
            with mock.patch.object(calibration, "atomic_results", commit_then_kill): run.calibrate(c, "strong_calibrator")
            os._exit(1)
        _, status = os.waitpid(child, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
        path = c.work / "strong_calibrator/results.json"
        assert len(json.loads(path.read_text())) == 1
        c.args.resume = "synthetic"
        result = run.calibrate(c, "strong_calibrator")
        assert result["tries"] == 3 and len(calls) == 2 and seeds == [9, 10]
        resumed = json.loads(c.ledger.read_text())
        assert resumed["cost"] == 1.25 and resumed["calls"] == 37
        rows = json.loads(path.read_text())
        assert [row["try"] for row in rows] == [1, 2, 3]
        # Stale configuration invalidates every attempt, with original receipts retained.
        c.args.calibrator_minutes += 1
        run.calibrate(c, "strong_calibrator")
        assert len(calls) == 5 and list(path.parent.glob("results-unverified-*.json"))
        # Missing failed guards are invalid too: artifact validation is symmetric.
        pathlib.Path(json.loads(path.read_text())[1]["guard"]).joinpath("db.sql").unlink()
        run.calibrate(c, "strong_calibrator")
        assert len(calls) == 7  # keep valid try 1, repeat exactly 2 and 3
        # Legacy rows never satisfy durable recovery.
        atomic_results(path, [{"try": 1, "solved": True, "guard": "/missing"}])
        run.calibrate(c, "strong_calibrator")
        assert len(calls) == 10

for solved in (True, False):
    for changed in (None, "case", "effort", "seed", "slot", "runs"):
        with tempfile.TemporaryDirectory() as tmp:
            c, stack, calls, seeds = exercise(pathlib.Path(tmp), solved=solved)
            with stack:
                probe = run.calibrate(c, "strong_calibrator", tries=1, name="early_probe")
                c.card["early_probe"] = {**probe, "label": "solvable" if solved else "likely_hard"}
                if changed == "case": (c.case / "promise.md").write_text("changed synthetic contract")
                if changed == "effort": c.card["roles"] = {"strong_calibrator": {"effort": "low"}}
                if changed == "seed": c.seed += 1
                if changed == "slot": c.factory_slot = 1
                if changed == "runs": c.args.pilot_runs += 1
                result = run.calibrate(c, "strong_calibrator")
                assert result["tries"] == 3 and result["solved"] == (3 if solved else 0)
                kept = changed in (None, "slot")  # a tester slot never invalidates a finished try
                assert len(calls) == (3 if kept else 4)
                assert seeds == ([8, 9, 10] if kept else [8, *range(c.seed + 1, c.seed + 4)])
                assert c.card["early_probe"]["label"] == ("solvable" if solved else "likely_hard")
                rows = json.loads((c.work / "strong_calibrator/results.json").read_text())
                assert (rows[0].get("source") == "early_probe") == kept

# Legacy gates revalidate; matching release/configuration still requires evidence.
# G10/G11 always reach their durable receipt and solved-guard verification paths.
harness = r'''
import copy, json, pathlib, sys, types
from unittest import mock
import run
import gate_state
root = pathlib.Path(sys.argv[1]); mode = sys.argv[2]; work = root / "work/case-synthetic"
(work / "case").mkdir(parents=True); (work / "logs").mkdir()
(work / "case/authored").write_text("synthetic authored case")
(work / "case/base").mkdir(); (work / "case/base/judge.py").write_text("synthetic checker")
config = dict(version=1, rounds=3, runs=10, scenario_runs=3, pilot_tries=3, pilot_runs=5,
    dry_run=False, calibrator_minutes=30, max_role_calls=400, max_total_calls=1000, max_cost=5,
    no_progress_minutes=45, max_zero_tokens=3, agent_timeout=14400, max_repairs=2)
roles = {"writer": {"model": "synthetic/writer", "effort": "high"}}
previous = {"gates": {gate: "pass" for gate in run.GATES},
    "gate_results": {"G4": {"synthetic_evidence": "retained"}},
    "factory_release": "historical-release", "recovery_config": copy.deepcopy(config),
    "seed": 42, "roles": copy.deepcopy(roles)}
if mode == "legacy":
    for key in ("factory_release", "recovery_config", "seed", "roles"): previous.pop(key)
elif mode == "release": previous["factory_release"] = "stale-release"
elif mode == "config": previous["recovery_config"]["runs"] += 1
elif mode == "seed": previous["seed"] += 1
elif mode == "roles": previous["roles"]["writer"]["effort"] = "low"
(work / "scorecard.json").write_text(json.dumps(previous))
bench = root / "bench"; (bench / "results").mkdir(parents=True)
(bench / "results/g4.json").write_text('{"synthetic_pass": true}')
receipt_context = types.SimpleNamespace(work=work, case=work / "case", manifest0="synthetic", seed=42,
    args=types.SimpleNamespace(**config), card={"roles": roles}, models={})
gate_state.save(receipt_context, "G4", {"synthetic_pass": True},
    gate_state.fingerprint(receipt_context, "G4", bench), {}, bench)
if mode == "case": (work / "case/base/judge.py").write_text("changed checker")
if mode == "freshness": (work / "case/freshness.jsonl").write_text('{"hit": true}')
for role in ("strong_calibrator", "easy_calibrator"):
    (work / role).mkdir(); (work / role / "results.json").write_text('[{"solved": true}]')
def gates(c):
    assert not c.card["gates"], (mode, c.card["gates"])
    assert not c.card.get("gate_results"), "old pass flags must not bypass receipt validation"
    if mode == "unchanged":
        assert gate_state.load(c, "G4", bench) == {"synthetic_pass": True}, "verified applicable work must remain reusable"
    elif mode == "case":
        assert gate_state.load(c, "G4", bench) is None, "changed case must invalidate retained evidence"
    for role in ("strong_calibrator", "easy_calibrator"):
        assert (work / role / "results.json").exists(), "legacy evidence must reach verification"
    assert (work / "case/authored").read_text() == "synthetic authored case"
    (root / "checked").touch()
    raise run.BudgetError("synthetic-test-stop")
c = receipt_context
c.card, c.stopped = previous, False
with mock.patch.object(run, "run_gates", gates), \
     mock.patch.object(run, "g1", return_value=(True, {"problems": []})), \
     mock.patch.object(run, "ensure_freshness"):
    try:
        run.engine_gates(c)
    except run.BudgetError as error:
        assert str(error) == "synthetic-test-stop"
    else:
        raise AssertionError("gate verification did not run")
'''
for mode in ("legacy", "unchanged", "release", "config", "seed", "roles", "case", "freshness"):
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run([sys.executable, "-c", harness, tmp, mode], cwd=(pathlib.Path(__file__).resolve().parents[2] / "factory"), capture_output=True, text=True)
        assert result.returncode == 0, (mode, result.stderr)
        assert (pathlib.Path(tmp) / "checked").exists(), (mode, result.stdout)

print("PASS calibration recovery: SIGKILL, partial resume, identity and artifact checks, legacy rejection, symmetric probe reuse, three independent attempts, kept-gate verification")
