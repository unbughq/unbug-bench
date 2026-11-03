#!/usr/bin/env python3
"""Practice checks: offline, plus --live prerequisites. Exit 0 all pass, 1 any fail, 3 unproved or needs_founder."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "factory"))
import practice_preflight as preflight
if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", type=Path)
    p.add_argument("--live", action="store_true", help="also the read-only live checks over root SSH; exit 0 only if all pass")
    p.add_argument("--name", default="unbug-control", help="control server name, as bin/control-vm")
    a = p.parse_args()
    server = False
    if a.live:
        try: server = preflight._load(ROOT / "bin/control-vm", "control_vm").selected(a.name)
        except Exception: server = None  # every SSH check then fails, and is reported
    result = preflight.check(ROOT, a.bundle, server)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(preflight.code(result))
