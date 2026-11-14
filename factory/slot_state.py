"""Bench state that bin/bench.py (and bin/checkpoint, bin/factory_pool.py) keep in a results root
between commands: what a factory slot or a running bench still uses, never evidence.

The names mirror bench.py's own literals (tests/factory/test_live_slot_fixture.py reads them from
its source, so a rename there fails the test). They live here, in factory code, so changing the
list never changes the bench version. Anything else in results (runs/, windows/, refusal evidence,
factory_pool's .factory-runs-* records) is evidence: gathered, sealed and wiped.
"""
from pathlib import PurePosixPath

LOCK = ".bench.lock"
SEED_IDS = "seed-ids.json"
FILES = frozenset({
    LOCK, SEED_IDS,
    ".prepared.json",            # factory slot readiness receipt
    ".slot-compose.yaml",        # slot port override, rewritten on every bench import
    ".guard-compose.yaml",       # guard image override
    ".inventory-services.json",  # inventory services to stop (bench.INVENTORY_STATE)
    ".inventory-compose.json",   # inventory build override
    ".inventory-ports.yaml",     # inventory port override
    ".pending.json",             # bin/checkpoint's pending-change decisions
})
DIRECTORIES = frozenset({".no-changes"})   # bin/checkpoint's no-op scenario
TEMPORARY_SUFFIX = ".tmp"                   # atomic replacements of the files above
PROGRESS_PREFIX = "bench-progress-"         # live bench status (BenchProgress)


def is_state(relative):
    """Whether a path relative to a results root (any slot) is bench state rather than evidence."""
    parts = PurePosixPath(relative).parts
    return bool(parts) and (parts[-1] in FILES or parts[-1].endswith(TEMPORARY_SUFFIX)
                            or parts[-1].startswith(PROGRESS_PREFIX) or not DIRECTORIES.isdisjoint(parts[:-1]))
