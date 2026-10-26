"""Judge-only Harbor case selection and portable checkpoint evidence capture."""
import json
import pathlib
import re
import shutil
import sys
import tempfile
import claims
from checkpoint_evidence import record_paths


def scenario_paths(names, configuration):
    # The image builder owns this file. No environment/contestant path override.
    configuration = pathlib.Path(configuration)
    if configuration.is_symlink(): raise ValueError("symlink case configuration")
    mode = json.loads(configuration.read_text())
    image = configuration.parent.parent
    if mode == {"mode": "selected"}: case = image / "case"
    elif mode == {"mode": "practice"}: case = image / "bench/cases/medusa-oversell-v2"
    else: raise ValueError("invalid judge case configuration")
    if case.is_symlink() or not (case / "base").is_dir(): raise ValueError("missing judge case")
    paths = []
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name): raise ValueError("invalid scenario name")
        path = case / ("base" if name == "BASE" else "scenarios/" + name)
        if not path.is_dir() or not path.resolve().is_relative_to(case.resolve()):
            raise ValueError("missing or escaped selected scenario")
        if any(p.is_symlink() for p in (path, *path.parents) if p != image and p.is_relative_to(image)):
            raise ValueError("symlink selected scenario")
        paths.append(path)
    if not paths: raise ValueError("no selected scenarios")
    return paths


def capture(checkpoint, destination):
    """Copy precisely the fixed proof boundary, never record-provided absolute paths."""
    checkpoint, destination = pathlib.Path(checkpoint), pathlib.Path(destination)
    if checkpoint.is_symlink() or destination.is_symlink(): raise ValueError("symlink evidence boundary")
    summary = json.loads(checkpoint.read_text())
    manifest = claims.pending_artifacts(checkpoint.parent)
    proof = summary.get("pending_verification") or {}
    if proof.get("verified") and not claims.verify_pending_artifacts(summary, checkpoint.parent):
        raise ValueError("invalid checkpoint support")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        staged = pathlib.Path(tmp)
        for name in manifest:
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checkpoint.parent / name, target)
        for name in ("guard", "scenarios"): (staged / name).mkdir(exist_ok=True)
        shutil.copyfile(checkpoint, staged / "checkpoint.json")
        if claims.pending_artifacts(staged) != manifest: raise ValueError("changed evidence during capture")
        # Replace only proof members; preserve Harbor logs/reward files, remove stale retry records.
        for old in [*record_paths(destination), destination / "guard", destination / "scenarios", destination / "checkpoint.json"]:
            if old.is_symlink(): raise ValueError("symlink evidence destination")
            if old.is_dir(): shutil.rmtree(old)
            elif old.exists(): old.unlink()
        for member in staged.iterdir(): shutil.move(str(member), destination / member.name)


if __name__ == "__main__":
    if sys.argv[1] == "scenarios":
        for path in scenario_paths(sys.argv[3:], sys.argv[2]): print(path)
    elif sys.argv[1] == "capture": capture(sys.argv[2], sys.argv[3])
    else: raise ValueError("unknown verifier operation")
