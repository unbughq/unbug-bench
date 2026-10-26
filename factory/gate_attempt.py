"""Gate attempt lifecycle; scheduling and scientific verdicts remain with callers."""
from dataclasses import dataclass
import time


@dataclass(frozen=True)
class Outcome:
    ok: bool
    info: dict
    elapsed_seconds: float
    crashed: bool = False


def execute(invoke, *, publish, record_crash, interruption, attempts=1, raise_crash=False):
    """Publish one lifecycle, retaining private diagnostics for each failed attempt.

    Only operational exceptions are retried. A scored rejection returns immediately;
    budget stops and process interruptions always propagate. Callers decide whether
    an exhausted operational failure stops the run or defers to a later gate.
    """
    if type(attempts) is not int or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    started = time.monotonic()
    publish('running')
    for attempt in range(attempts):
        try:
            ok, info = invoke()
        except interruption:
            publish('interrupted', time.monotonic() - started)
            raise
        except Exception as error:
            record_crash(error)
            if attempt + 1 < attempts:
                continue
            elapsed = time.monotonic() - started
            publish('failed', elapsed)
            if raise_crash:
                raise
            return Outcome(False, {'error': type(error).__name__}, elapsed, crashed=True)
        except BaseException:
            publish('interrupted', time.monotonic() - started)
            raise
        elapsed = time.monotonic() - started
        publish('completed' if ok else 'failed', elapsed,
                bool(info.get('reused_verified_evidence') or info.get('reused_from_early_check')))
        return Outcome(ok, info, elapsed)
