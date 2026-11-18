"""Exam-only Harbor 0.24 patch; bin/run-exam puts this directory on Harbor's PYTHONPATH.

Harbor bind-mounts the judge's host output dir at /logs/verifier in the contestant box as well
as in the separate verifier, so a contestant process left running could rewrite reward.json or
checkpoint.json after the judge writes them. When every verify pass runs in a separate verifier,
the contestant's /logs/verifier is a sibling decoy instead. A sibling keeps
${HOST_VERIFIER_LOGS_PATH}/../<dir> overlays (medusa-oversell-v2) pointing where they did.
Lives outside harbor/** so it does not change sealed cases' calibration identity.
ponytail: the box is privileged (host-root equivalent); this closes the plain write, not an escape.
"""
try:
    from harbor.trial.trial import Trial
    from harbor.models.task.config import VerifierEnvironmentMode
    from harbor.models.task.verifier_mode import resolve_step_verifier_mode, resolve_task_verifier_mode
except ImportError:  # not a Harbor interpreter (run-audited.py itself)
    Trial = None

DECOY = "verifier-decoy"  # bin/run-exam refuses a trial without it

# This file shadows the interpreter's own sitecustomize (Homebrew, Debian); run that one too.
import importlib.machinery as _machinery, importlib.util as _util, os as _os, sys as _sys
_here = _os.path.realpath(_os.path.dirname(__file__))
_spec = _machinery.PathFinder.find_spec("sitecustomize", [p for p in _sys.path if _os.path.realpath(p or ".") != _here])
if _spec and _spec.loader:
    _spec.loader.exec_module(_util.module_from_spec(_spec))

if Trial is not None:
    _mounts = Trial._agent_env_mounts.fget

    def _isolated_mounts(self):
        mounts = _mounts(self)
        cfg = self.task.config
        modes = [resolve_step_verifier_mode(cfg, s) for s in cfg.steps or ()] or [resolve_task_verifier_mode(cfg)]
        if any(mode != VerifierEnvironmentMode.SEPARATE for mode in modes):
            return mounts  # a shared verifier writes from inside the box
        decoy = self.paths.trial_dir / DECOY
        decoy.mkdir(exist_ok=True)
        decoy.chmod(0o777)
        judge = str(self.agent_env_paths.verifier_dir)
        return [dict(m, source=decoy.resolve().as_posix()) if m.get("target") == judge else m for m in mounts]

    Trial._agent_env_mounts = property(_isolated_mounts)
