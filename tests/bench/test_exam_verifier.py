"""Actual prepare -> Harbor shell/ledger -> checkpoint -> capture -> moved CLI seam.

No Docker/network: the image builder interprets COPY/RUN in a temporary root; the shell
runs with only its fixed container paths rebased there. Runtime setup/traffic/database
I/O use stubs; production selection, ledger, runner, proof, capture and scorer execute.
"""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import contextlib
import copy
import importlib.machinery
import json
import os
import pathlib
import runpy
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = _BENCH_ROOT


def runtime():
    target, *args = sys.argv[2:]
    if pathlib.Path(target).name != "checkpoint":
        os.execv(sys.executable, [sys.executable, target, *args])
    sys.path.insert(0, str(pathlib.Path(target).resolve().parent))
    import bench
    image_bench = pathlib.Path.cwd()
    (image_bench / "results").mkdir(exist_ok=True)
    observations = json.loads(pathlib.Path(os.environ["SYNTHETIC_JUDGE"]).read_text())
    with patch.object(bench, "ROOT", image_bench), patch.object(bench, "RESULTS", image_bench / "results"), \
         patch.object(bench, "prepare_app_guard"), patch.object(bench, "bench_fingerprint", return_value={}), \
         patch.object(bench, "reset", return_value={"reset_seconds": 0}), \
         patch.object(bench, "command", return_value=json.dumps(observations["traffic"])), \
         patch.object(bench, "checker", side_effect=lambda: copy.deepcopy(observations["checker"])), \
         patch.object(sys, "argv", [target, *args]):
        runpy.run_path(target, run_name="__main__")


if len(sys.argv) > 1 and sys.argv[1] == "--runtime":
    runtime()
    sys.exit()

sys.path.insert(0, str(ROOT / "bin"))
import bench
import harbor_verifier as verifier
exam = importlib.machinery.SourceFileLoader("exam_staging", str(ROOT / "bin/run-exam")).load_module()


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def run_seam(root, variant):
    case = root / "private/case"
    task = case / "harbor/synthetic"
    shutil.copytree(ROOT / "harbor/medusa-oversell-v2/tests", task / "tests")
    write(case / "contestant.md", "Synthetic permitted instruction")
    write(task / "task.toml", '[environment]\ndocker_image="synthetic-box"\ncpus=1\n[verifier.environment]\ndocker_image="synthetic-judge"\n')
    base_key = {"oracle_contract": {"version": 1, "requirements": {"base": ["base_" + variant]},
                "facts": {"type": "object", "properties": {variant: {"type": "boolean"}}}}}
    pending_key = {"correct_responses": ["keep"], "claims": {"*": ["protected"]},
                   "pending_harmful": True, "pending_correct": ["block", "escalate"], "owner_decision": "block", "escalation": "inappropriate",
                   "oracle_contract": {"version": 1, "requirements": {"policy": ["policy_" + variant]},
                   "facts": {"type": "object", "properties": {variant: {"type": "boolean"}}}}}
    for directory, name, key in (("base", "BASE", base_key), ("scenarios/P1", "P1", pending_key)):
        write(case / directory / "scenario.json", json.dumps({"id": name, "delivery": "pending" if name == "P1" else "announced"}))
        write(case / directory / "key.json", json.dumps(key))
        write(case / directory / "judge.py", "def judge(result, bench): return result[\"traffic\"][\"scenario_records\"][" + repr(name) + "]\n")
    image = root / "image"
    shutil.copytree(ROOT / "bin", image / "bench/bin", ignore=shutil.ignore_patterns("__pycache__"))
    (image / "bench/factory").mkdir()
    shutil.copy2(ROOT / "factory/case_permissions.py", image / "bench/factory/case_permissions.py")
    # Deliberately different practice key; no contract can certify selected approval.
    shutil.copytree(case / "base", image / "bench/cases/medusa-oversell-v2/base")
    write(image / "bench/cases/medusa-oversell-v2/base/key.json", '{}')
    commands = []
    def build(command, log):
        commands.append(command)
        if command[:2] != ["docker", "build"] or "-f" not in command: return 0
        context = pathlib.Path(command[-1])
        dockerfile = pathlib.Path(command[command.index("-f") + 1])
        for line in dockerfile.read_text().splitlines():
            if line.startswith("COPY "):
                _, source, destination = line.split()
                shutil.copytree(context / source, image / destination.lstrip("/"), dirs_exist_ok=True)
            elif line.startswith("RUN "):
                subprocess.run(["sh", "-c", line[4:].replace("/tests/", str(image / "tests") + "/")], check=True)
        return 0
    with patch.object(exam, "sh", side_effect=build):
        assert exam.prepare(case, task, root / "build.log") == {"cpus": 1}
    assert json.loads((image / "tests/case-root.json").read_text()) == {"mode": "selected"}
    box = root / "private/box-context"
    assert {p.name for p in box.iterdir()} == {"contestant.md", "Dockerfile"}
    paths = verifier.scenario_paths(["BASE", "P1"], image / "tests/case-root.json")
    assert [json.loads((p / "key.json").read_text()) for p in paths] == [base_key, pending_key]
    assert "policy_" + variant in runpy.run_path(str(ROOT / "bin/checkpoint"))["oracle_requirements"](
        [bench.load_scenario(p) for p in paths])[0]
    # Only path rebasing for executing container scripts on the host. No logic replacement.
    def rebase(text):
        for name in ("bench", "tests", "app", "logs", "judge-state", "deployment-out"):
            text = text.replace("/" + name, str(image / name))
        return text
    for name in ("test.sh", "pending.py"):
        p = image / "tests" / name
        p.write_text(rebase(p.read_text()))
    write(image / "bench/bin/setup", "#!/bin/sh\nexit 0\n").chmod(0o755)
    write(image / "bench/projects/medusa/verify-lock.mjs", "// runtime setup stub\n")
    for name in ("docker", "node"):
        write(root / "stubs" / name, "#!/bin/sh\nexit 0\n").chmod(0o755)
    write(root / "stubs/python3", "#!/bin/sh\nexec " + str(sys.executable) + " " + str(pathlib.Path(__file__).resolve()) + ' --runtime "$@"\n').chmod(0o755)
    guard = image / "app/guard"; guard.mkdir(parents=True)
    report = {"response": "keep", "pending_decision": "approve", "claims": [
        {"path": p, "status": "protected"} for p in sorted(set(bench.PATH_OF_KIT.values()))]}
    write(image / "app/claims.json", json.dumps(report))
    (image / "judge-state").mkdir()
    out = image / "logs/verifier"; out.mkdir(parents=True)
    checker = {**dict.fromkeys(bench.BASE_CHECKS, True), "pass": True,
               "normal_orders_placed": 5, "trigger_orders_placed": 1, "sequential_first_placed": True,
               "legit_orders_placed": 2, "draft_store_placed": True, "draft_fit_placed": True,
               "edit_store_placed": True, "edit_fit_placed": True}
    observations = {"checker": checker, "traffic": {"scenario_records": {
        "BASE": {"checks": {"base_" + variant: True}, "facts": {variant: True}},
        "P1": {"checks": {"policy_" + variant: True}, "facts": {variant: True}}}}}
    judge_file = write(root / "judge.json", json.dumps(observations))
    env = {**os.environ, "PATH": str(root / "stubs") + ":" + os.environ["PATH"],
           "BENCH": str(image / "bench"), "PYTHONDONTWRITEBYTECODE": "1", "UNBUG_RUNS": "2",
           "UNBUG_SCENARIOS": "BASE P1", "SYNTHETIC_JUDGE": str(judge_file),
           "UNBUG_CASE": "/contestant/forged", "UNBUG_CASE_DIR": "/contestant/forged"}
    def shell():
        result = subprocess.run(["bash", str(image / "tests/test.sh")], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return json.loads((out / "reward.json").read_text())
    reward = shell()
    assert reward["reward"] == 1, (reward, {p.name: p.read_text() for p in out.glob("*.log")})
    summary = json.loads((out / "checkpoint.json").read_text())
    assert summary["key"] == pending_key and summary["pending_verification"]["verified"]
    assert json.loads((image / "judge-state/decisions.json").read_text())["P1"]["landed"] is True
    # Real Harbor artifact moved away from the run root; original evidence deleted.
    moved = root / "moved/steps/synthetic/verifier"; shutil.copytree(out, moved)
    artifacts = moved.parent / "artifacts"
    write(artifacts / "claims.json", json.dumps(report))
    write(artifacts / "manifest.json", json.dumps([{"source": "/app/claims.json", "destination": "artifacts/claims.json", "status": "ok"}]))
    step_score = lambda: exam.step_card(1, {"step_name": "synthetic"}, root / "moved", 0)[0]
    assert step_score()["response_correct"]
    assert "policy_" + variant not in json.dumps(step_score())
    shutil.rmtree(image / "bench/results")
    cli = [sys.executable, str(ROOT / "bin/score-claims"), str(moved / "checkpoint.json"), str(image / "app/claims.json")]
    score = lambda: json.loads(subprocess.check_output(cli, text=True))
    assert score()["pending_approval_verified"]
    original = (moved / "01.json").read_bytes()
    (moved / "01.json").write_bytes(original + b" ")
    assert not score()["pending_approval_verified"]
    assert not step_score()["response_correct"]
    (moved / "01.json").unlink()
    assert not score()["pending_approval_verified"]
    (moved / "01.json").write_bytes(original)
    (moved / "guard").rmdir(); (moved / "guard").symlink_to(guard, target_is_directory=True)
    assert not score()["pending_approval_verified"]
    # A different case's runtime checks cannot satisfy this selected contract.
    observations["traffic"]["scenario_records"]["P1"]["checks"] = {"policy_wrong_case": True}
    judge_file.write_text(json.dumps(observations))
    assert shell()["reward"] == 0
    # Neither missing selection nor missing configuration may use existing practice inputs.
    shutil.rmtree(image / "case/scenarios/P1")
    assert shell()["judge_error"] == 1
    shutil.rmtree(image / "case")
    assert shell()["judge_error"] == 1
    (image / "tests/case-root.json").unlink()
    assert shell()["judge_error"] == 1
    # Practice is usable only with the explicit judge-image practice configuration.
    write(image / "tests/case-root.json", '{"mode":"practice"}')
    assert verifier.scenario_paths(["BASE"], image / "tests/case-root.json") == [image / "bench/cases/medusa-oversell-v2/base"]
    try: verifier.scenario_paths(["../base"], image / "tests/case-root.json")
    except ValueError: pass
    else: raise AssertionError("scenario escape accepted")
    write(task / "task.toml", '[environment]\ndocker_image="synthetic-box"\n')
    with patch.object(exam, "sh", return_value=0):
        try: exam.prepare(case, task, root / "build.log")
        except ValueError: pass
        else: raise AssertionError("exam accepted no separate selected-case judge")


with tempfile.TemporaryDirectory() as tmp:
    for variant in ("alpha", "beta"):
        run_seam(pathlib.Path(tmp) / variant, variant)
print("exam staging/Harbor shell/ledger/selected contracts/capture/moved real CLI: two cases passed; wrong/missing case and tampered/missing/symlink support rejected")
