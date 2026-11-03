#!/usr/bin/env python3
"""Run offline regression scripts in isolated processes, including unittest files."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
SUITES = ("factory", "bench", "tools", "control", "integration", "analysis", "harbor")
SLOTS = Path(os.environ.get("TEST_SLOT_DIR", "/tmp/unbug-test-slots"))
SLOT_COUNT = int(os.environ.get("TEST_SLOTS", os.cpu_count() or 1))


@contextlib.contextmanager
def machine_slot():
    """Hold one of SLOT_COUNT machine-wide slots, shared by every suite on this host.
    flock releases on process exit, so a killed suite never leaks a slot."""
    SLOTS.mkdir(exist_ok=True)
    while True:
        for i in range(SLOT_COUNT):
            with open(SLOTS / f"{i}.lock", "w") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                yield
                return
        time.sleep(0.2)


def run(path):
    with machine_slot():
        result = subprocess.run([sys.executable, "-B", str(path)], cwd=ROOT, env={**os.environ, "BENCH": str(ROOT)},
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return path, result.returncode, result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suites", nargs="*", help="Subsystems to run; default: all offline suites")
    parser.add_argument("--list", action="store_true", help="List selected scripts without running them")
    parser.add_argument("-j", "--jobs", type=int, default=int(os.environ.get("TEST_JOBS", os.cpu_count() or 1)),
                        help="Scripts to run at once (default: CPU count, or TEST_JOBS)")
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
    # Output is buffered per script and printed in order, so logs read like a serial run.
    pool = ThreadPoolExecutor(max(1, args.jobs))
    try:
        for path, code, output in pool.map(run, scripts):
            print("\n== " + str(path.relative_to(ROOT)) + " ==", flush=True)
            sys.stdout.buffer.write(output)
            if code:
                failures.append(path.relative_to(ROOT))
    finally:
        pool.shutdown(cancel_futures=True)
    print(f"\n{len(scripts)} test scripts run; {len(failures)} failed.", flush=True)
    for path in failures:
        print("FAILED: " + str(path))
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
