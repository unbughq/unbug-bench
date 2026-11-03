#!/usr/bin/env python3
"""Record safe runner exit metadata; retry only an untouched startup, never a case."""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(os.environ.get('BENCH', Path.home() / 'unbug-bench')) / 'bin'))
import processes


def supervise(command, home, seconds):
    end = time.monotonic() + processes.positive(seconds)
    grace = max(0, min(720, float(os.environ.get('FACTORY_RUNNER_GRACE_SECONDS', '720'))))
    hard_end = end + grace  # caller reserves this inside the provider collection margin
    sealed = home / 'sealed'; sealed.mkdir(parents=True, exist_ok=True)
    path = sealed / 'runner-status.json'
    stopping = False
    child = None

    def stop(_signum, _frame):
        nonlocal stopping, end
        stopping = True
        end = min(hard_end, time.monotonic() + grace)
        if child is not None and child.poll() is None:
            child.send_signal(signal.SIGTERM)  # runner pauses and seals

    def save(attempt, phase, reason, code=None):
        # Never retain argv, environment, stderr or exception text here.
        data = dict(schema=1, attempt=attempt, phase=phase, reason=reason,
                    exit_status=code, observed_at=time.time())
        temporary = path.with_suffix('.tmp')
        with temporary.open('w') as stream:
            json.dump(data, stream); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        try:
            processes.prepare_model_containment(home)
        except processes.ContainmentError:
            save(0, 'startup', 'containment_unavailable', 78)
            print('containment_unavailable', file=sys.stderr)
            return 78
        for attempt in range(1, 4):
            ready = sealed / ('runner-ready-' + str(attempt))
            ready.unlink(missing_ok=True)
            save(attempt, 'running', 'running')
            child = None
            try:
                child = subprocess.Popen(command, start_new_session=True, stderr=subprocess.DEVNULL,
                    env={**os.environ, 'FACTORY_RUNNER_READY': str(ready), 'UNBUG_PROCESS_DEADLINE': str(end)})
                if stopping: child.send_signal(signal.SIGTERM)
                while child.poll() is None and time.monotonic() < end:
                    time.sleep(min(.2, max(0, end - time.monotonic())))
                timed_out = not stopping and time.monotonic() >= end
                if timed_out and child.poll() is None:
                    child.send_signal(signal.SIGTERM)  # same pause/seal path as collection
                    while child.poll() is None and time.monotonic() < hard_end:
                        time.sleep(min(.2, max(0, hard_end - time.monotonic())))
                if child.poll() is None:
                    processes.kill_tree(child.pid)
                    child.wait(timeout=2)
                    save(attempt, 'stopped', 'cancelled' if stopping else 'timeout', child.returncode)
                    return 143 if stopping else 124
                code = child.returncode
                if timed_out:
                    save(attempt, 'stopped', 'timeout', code)
                    return 124
            except OSError:
                code = 127  # safe classification; no OS error text
            finally:
                if child is not None:
                    processes.kill_tree(child.pid, alive=child.poll() is None)
                    child.wait(timeout=2)
            if stopping:
                save(attempt, 'stopped', 'cancelled', code)
                return 128 + signal.SIGTERM
            if ready.exists() or (sealed / 'DONE').exists():
                save(attempt, 'finished', 'finished', code)
                return code
            untouched = not any((home / 'work').glob('*')) and not any(sealed.glob('*.continuation-budget.json'))
            retry = (attempt < 3 and untouched and (code in (1, 126, 127) or code < 0)
                     and time.monotonic() + 1 < end)
            save(attempt, 'startup', 'startup_retry' if retry else 'startup_failed', code)
            if not retry: return code or 1
            time.sleep(1)
            if stopping:
                save(attempt, 'stopped', 'cancelled', code)
                return 143
    finally:
        for sig, handler in previous.items(): signal.signal(sig, handler)


def main():
    os.umask(0o077)
    command = sys.argv[1:]
    if command[:1] == ['--']: command.pop(0)
    if not command: return 2
    return supervise(command, Path.home(), float(os.environ.get('FACTORY_RUNNER_SECONDS', '14400')))


if __name__ == '__main__':
    sys.exit(main())
