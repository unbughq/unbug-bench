#!/usr/bin/env python3
"""Cut public practice pins from the current reviewed merged head; never deploy."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "factory"))
import batch
import practice_preflight as preflight


def build(root, output):
    if not output.is_absolute() or output.exists(): raise ValueError("new absolute output required")
    head = preflight.git(root, "rev-parse", "HEAD")
    if head != preflight.git(root, "rev-parse", "factory-simplify") or preflight.git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("clean merged head required")
    report = preflight.check(root)
    if any(r["status"] != "pass" for r in report["offline"] if r["id"] != "pins"): raise ValueError("offline checks refused")
    output.mkdir()
    incomplete = output / "INCOMPLETE"; incomplete.write_text("Pinning incomplete; do not deploy.\n")
    sha = batch.build(root, head, output / "release")
    batch.verify(output / "release", sha, root)
    batch.save(output / "policy.json", preflight.policy(root, sha))
    (output / preflight.practice_cleanup.UNIT).write_bytes((root / "control" / preflight.practice_cleanup.UNIT).read_bytes())
    (output / "practice.conf").write_text(preflight.DROPIN)
    (output / "tools").mkdir()
    for name in ("tools/practice-fault.py", "tools/qualify-batch-inputs.py"):
        (output / name).write_bytes((root / name).read_bytes())
    batch.save(output / "pins.json", preflight.pins(root, output))
    incomplete.unlink()
    try:
        report = preflight.check(root, output)
        if preflight.code(report) != 3: raise ValueError("pins refused")
        batch.save(output / "preflight.json", report)
    except Exception:
        incomplete.write_text("Pin verification failed; do not deploy.\n")
        raise
    return report

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        build(ROOT, a.output)
        print("Practice pins cut; live evidence remains unproved.")
    except Exception: raise SystemExit("practice pin refused; no deployment")
