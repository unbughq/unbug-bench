#!/usr/bin/env python3
"""Task-local live reset: keep the established service and landed SQL, including approved pending changes."""
import json, os, pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]
scenarios = [root / "services/marketplace"]
state = root / "results/.landed-pending.json"
landed = json.loads(state.read_text()) if state.exists() else []
for directory in sorted((root / "changes").glob("*")):
    meta = directory / "scenario.json"
    if meta.is_file():
        meta = json.loads(meta.read_text())
        if meta.get("delivery", "announced") != "pending" or meta["id"] in landed:
            scenarios.append(directory)
os.execv(sys.executable, [sys.executable, str(root / "bin/bench.py"), "reset",
    *[value for scenario in scenarios for value in ("--scenario", str(scenario))], *sys.argv[1:]])
