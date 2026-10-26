#!/usr/bin/env python3
"""Deploy the previous verifier's approvals to the live shop before the next step.

The receipt is a one-way, read-only mount. This local applied list is reset convenience,
not scoring authority; the judge never consumes either file from the contestant.
"""
import json, pathlib, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]

def sync(root=ROOT, receipt=pathlib.Path("/deployments/decisions.json"), prior=()):
    decisions = json.loads(receipt.read_text()) if receipt.exists() else {}
    if set(prior) - decisions.keys(): raise RuntimeError("missing previous deployment receipt")
    state = root / "results/.landed-pending.json"
    applied = json.loads(state.read_text()) if state.exists() else []
    for directory in sorted((root / "changes").glob("*")):
        meta = directory / "scenario.json"
        if not meta.is_file(): continue
        meta = json.loads(meta.read_text()); sid = meta["id"]
        if meta.get("delivery") != "pending" or sid in applied: continue
        if not decisions.get(sid, {}).get("landed"): continue
        subprocess.run([str(root / "bin/land"), str(directory), "--approved"], cwd=root, check=True)
        applied.append(sid)
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(applied) + "\n")

if __name__ == "__main__":
    import sys
    sync(prior=sys.argv[1:])
