"""The contestant box never mounts the judge's /logs/verifier output dir.

Run with Harbor 0.24's interpreter:
  ~/.local/share/uv/tools/harbor/bin/python tests/bench/test_exam_verifier_isolation.py
"""
import os, pathlib, subprocess, sys, tempfile, tomllib, types

ROOT = pathlib.Path(__file__).resolve().parents[2]
# Harbor sees exactly the PYTHONPATH bin/run-exam gives it.
sys.path.insert(0, str(ROOT / "bin"))
import importlib.machinery
exam = importlib.machinery.SourceFileLoader("run_exam", str(ROOT / "bin/run-exam")).load_module()
probe = """
import sys, sitecustomize
from harbor.trial.trial import Trial
print(Trial._agent_env_mounts.fget.__module__, sitecustomize.__file__)
"""
env = dict(os.environ, PYTHONPATH=exam.harbor_pythonpath())
patched = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, check=True).stdout.strip()
assert patched == f"sitecustomize {ROOT}/bin/exam_harbor/sitecustomize.py", patched

# In-process, the interpreter's own sitecustomize already holds that name; load ours by path.
sitecustomize = importlib.machinery.SourceFileLoader("exam_sitecustomize", str(ROOT / "bin/exam_harbor/sitecustomize.py")).load_module()
from harbor.models.task.config import TaskConfig, TaskOS
from harbor.models.trial.paths import TrialPaths, EnvironmentPaths
from harbor.trial.trial import Trial
from harbor.environments.docker.compose_env import legacy_log_mount_env_vars

with tempfile.TemporaryDirectory() as tmp:
    paths = TrialPaths(pathlib.Path(tmp) / "trial")
    paths.mkdir()
    cfg = TaskConfig.model_validate(tomllib.loads((ROOT / "harbor/medusa-oversell/task.toml").read_text()))
    trial = types.SimpleNamespace(task=types.SimpleNamespace(config=cfg), paths=paths, user_agent=None,
                                  agent_env_paths=EnvironmentPaths.for_os(TaskOS.LINUX),
                                  _main_artifacts_mount_dir=paths.artifacts_dir,
                                  config=types.SimpleNamespace(environment=types.SimpleNamespace(mounts=[])))
    mounts = Trial._agent_env_mounts.fget(trial)
    judge = paths.verifier_dir.resolve().as_posix()
    assert judge not in [m["source"] for m in mounts], mounts
    host = legacy_log_mount_env_vars(mounts, host_value="source")["HOST_VERIFIER_LOGS_PATH"]
    assert pathlib.Path(host).parent == pathlib.Path(judge).parent  # v2's ../deployment-state is unchanged
    assert (paths.trial_dir / sitecustomize.DECOY).is_dir()
    # A task whose verifier shares the box keeps Harbor's mount.
    shared = cfg.model_copy(update={"steps": None, "verifier": type(cfg.verifier)()})
    trial.task.config = shared
    assert judge in [m["source"] for m in Trial._agent_env_mounts.fget(trial)]
print("ok")
