"""Test-only clock for the copied boat-call; transport events advance deadlines.

Freeze scheduling time while real setup runs. A fake transport can then advance
its own command's clock and wait for observation, without racing interpreter
startup or changing production timeout/cleanup code.
"""
import os
from pathlib import Path
import time
from types import SimpleNamespace


def install(processes):
    event = Path(os.environ['FAKE_STATE']) / f'clock-{os.getpid()}-{time.monotonic_ns()}'
    observed = event.with_suffix('.observed')
    os.environ['FAKE_COMMAND_CLOCK'] = str(event)
    start = time.monotonic()

    def monotonic():
        if not event.exists():
            return start
        elapsed = float(event.read_text())
        observed.touch()
        return start + elapsed

    # Do not patch Python's shared time module (subprocess needs its real clock).
    processes.time = SimpleNamespace(monotonic=monotonic)
