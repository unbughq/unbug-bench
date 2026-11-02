#!/usr/bin/env python3
"""Offline practice checks. Exit 3 means live evidence remains unproved."""
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
    a = p.parse_args()
    result = preflight.check(ROOT, a.bundle)
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(preflight.code(result))
