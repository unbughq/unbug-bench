#!/usr/bin/env python3
"""Run offline regression scripts in isolated processes, including unittest files."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import fcntl
import hashlib
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
CACHE = Path(os.environ.get("TEST_CACHE_DIR", Path.home() / ".cache" / "unbug-tests"))


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


def code_key():
    """Hash of every tracked file outside docs/, or None if anything outside docs/ is uncommitted.
    Passes are reused only for byte-identical code, so docs-only commits never force a rerun."""
    # ponytail: whole-tree key, so any code change reruns all scripts; per-script import tracing if that bites.
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    status, tree = git("status", "--porcelain", "--", ".", ":(exclude)docs"), git("ls-tree", "-r", "HEAD")
    if status.returncode or tree.returncode or status.stdout.strip():
        return None
    code = [line for line in tree.stdout.splitlines() if not line.split("\t", 1)[1].startswith("docs/")]
    return hashlib.sha256("\n".join([sys.version, *code]).encode()).hexdigest()


def run(path, key):
    marker = key and CACHE / key / (str(path.relative_to(ROOT)) + ".pass")
    if marker and marker.exists():
        return path, 0, b"(cached pass for this exact code)\n"
    with machine_slot():
        result = subprocess.run([sys.executable, "-B", str(path)], cwd=ROOT, env={**os.environ, "BENCH": str(ROOT)},
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if marker and result.returncode == 0:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    return path, result.returncode, result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suites", nargs="*", help="Subsystems to run; default: all offline suites")
    parser.add_argument("--list", action="store_true", help="List selected scripts without running them")
    parser.add_argument("-j", "--jobs", type=int, default=int(os.environ.get("TEST_JOBS", os.cpu_count() or 1)),
                        help="Scripts to run at once (default: CPU count, or TEST_JOBS)")
    parser.add_argument("--no-cache", action="store_true", help="Rerun scripts that already passed on identical code")
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
    key = None if args.no_cache else code_key()
    print("code key: " + (key or "none (uncommitted changes or --no-cache; nothing reused)"), flush=True)
    failures = []
    # Output is buffered per script and printed in order, so logs read like a serial run.
    with ThreadPoolExecutor(max(1, args.jobs)) as pool:
        for path, code, output in pool.map(lambda p: run(p, key), scripts):
            print("\n== " + str(path.relative_to(ROOT)) + " ==", flush=True)
            sys.stdout.buffer.write(output)
            if code:
                failures.append(path.relative_to(ROOT))
    print(f"\n{len(scripts)} test scripts run; {len(failures)} failed.", flush=True)
    for path in failures:
        print("FAILED: " + str(path))
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
