#!/usr/bin/env python3
"""Arm one explicit pre-transport publication failure; never launches anything."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "factory"))
import batch_money as money
import practice
import key_holder


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy", type=Path, required=True)
    p.add_argument("--operation", required=True)
    a = p.parse_args()
    if a.policy.resolve() != (key_holder.CONTROL_HOME / "policy.json").resolve(): raise ValueError()
    policy = key_holder.policy_load(a.policy)
    with money.locked(key_holder.CONTROL_HOME, practice.BATCH):
        practice.fault(policy, key_holder.ROOT, key_holder.CONTROL_HOME, a.operation, arm=True)
    return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError): raise SystemExit("practice fault refused")
