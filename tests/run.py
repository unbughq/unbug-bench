#!/usr/bin/env python3
"""Run offline regression scripts in isolated processes, including unittest files."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
SUITES = ("factory", "bench", "tools", "control", "integration", "analysis", "harbor")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suites", nargs="*", help="Subsystems to run; default: all offline suites")
    parser.add_argument("--list", action="store_true", help="List selected scripts without running them")
    args = parser.parse_args()
    selected = args.suites or SUITES
    unknown = set(selected) - set(SUITES)
    if unknown:
        parser.error("unknown suites: " + ", ".join(sorted(unknown)))
    scripts = sorted({p for suite in selected for p in (TESTS / suite).rglob("test*.py")})
    if args.list:
        for path in scripts:
            print(path.relative_to(ROOT))
        return 0
    failures = []
    for path in scripts:
        print("\n== " + str(path.relative_to(ROOT)) + " ==", flush=True)
        result = subprocess.run([sys.executable, "-B", str(path)], cwd=ROOT,
                                env={**os.environ, "BENCH": str(ROOT)})
        if result.returncode:
            failures.append(path.relative_to(ROOT))
    print(f"\n{len(scripts)} test scripts run; {len(failures)} failed.", flush=True)
    for path in failures:
        print("FAILED: " + str(path))
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
