#!/usr/bin/env python3
"""Run offline regression scripts in isolated processes, including unittest files."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import contextlib
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
SUITES = ("factory", "bench", "tools", "control", "integration", "analysis", "harbor")
SLOTS = Path(os.environ.get("TEST_SLOT_DIR", "/tmp/unbug-test-slots"))
SLOT_COUNT = max(1, int(os.environ.get("TEST_SLOTS", os.cpu_count() or 1)))
# Scripts whose test classes run as separate jobs. The engine file starts a real DBOS engine per
# test (about 13 s each, 21 minutes for the file on 10 November), so as one job it set the floor
# for the whole suite. Every top-level class of a listed script becomes a job; none is left out.
SPLIT_BY_CLASS = ("factory/test_durable_engine.py",)
STOP = threading.Event()  # set on interrupt so threads still waiting for a slot give up


@contextlib.contextmanager
def machine_slot():
    """Hold one of SLOT_COUNT machine-wide slots, shared by every suite on this host.
    flock releases on process exit, so a killed suite never leaks a slot."""
    SLOTS.mkdir(exist_ok=True)
    while not STOP.is_set():
        for i in range(SLOT_COUNT):
            with open(SLOTS / f"{i}.lock", "w") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                yield True
                return
        time.sleep(0.2)
    yield False


def jobs(scripts):
    """(script, test class or None) per job; a split script yields one job per top-level class."""
    for path in scripts:
        if path.relative_to(TESTS).as_posix() not in SPLIT_BY_CLASS:
            yield path, None
            continue
        classes = [node.name for node in ast.parse(path.read_text()).body if isinstance(node, ast.ClassDef)]
        if not classes:
            raise SystemExit(f"{path}: listed in SPLIT_BY_CLASS but has no classes")
        for name in classes:
            yield path, name


def run(job):
    path, name = job
    # Output goes to a file, not a pipe: a pipe would wait for any child the script leaked, not for the script.
    with machine_slot() as held, tempfile.TemporaryFile() as out:
        if not held:
            return job, 130, b"interrupted before start\n"
        code = subprocess.run([sys.executable, "-B", str(path), *([name] if name else [])], cwd=ROOT, env={**os.environ, "BENCH": str(ROOT)},
                              stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT).returncode
        out.seek(0)
        return job, code, out.read()


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
    work = list(jobs(scripts))
    label = lambda job: str(job[0].relative_to(ROOT)) + (f" [{job[1]}]" if job[1] else "")
    if args.list:
        for job in work:
            print(label(job))
        return 0
    failures = []
    # Output is buffered per script and printed in order, so logs read like a serial run.
    pool = ThreadPoolExecutor(max(1, args.jobs))
    try:
        for job, code, output in pool.map(run, work):
            print("\n== " + label(job) + " ==", flush=True)
            sys.stdout.buffer.write(output)
            if code:
                failures.append(label(job))
    finally:
        STOP.set()
        pool.shutdown(cancel_futures=True)
    print(f"\n{len(scripts)} test scripts run as {len(work)} jobs; {len(failures)} failed.", flush=True)
    for name in failures:
        print("FAILED: " + name)
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
