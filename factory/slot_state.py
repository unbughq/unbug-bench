"""Bench state that bin/bench.py (and bin/checkpoint, bin/factory_pool.py) keep in a results root
between commands: what a factory slot or a running bench still uses, never evidence.

A bench's results root is results/ itself or results/factory-slots/<n>/ (bench.RESULTS); state
sits directly in it, never deeper, so nothing below runs/ or windows/ ever matches. The names mirror
bench.py's own literals (tests/factory/test_live_slot_fixture.py reads them from its source, so a
rename there fails the test). They live here, in factory code, so changing the list never changes
the bench version. Anything else in results (runs/, windows/, refusal evidence, an interrupted
checkpoint.json.tmp, factory_pool's .factory-runs-* records) is evidence: gathered, sealed, wiped.
"""
import re
from pathlib import PurePosixPath

LOCK = ".bench.lock"
SEED_IDS = "seed-ids.json"                 # a slot's own seed IDs (factory-slots/<n>/ only)
FILES = frozenset({
    LOCK,
    ".prepared.json", ".prepared.tmp",     # factory slot readiness receipt and its atomic replacement
    ".slot-compose.yaml",                  # slot port override, rewritten on every bench import
    ".guard-compose.yaml",                 # guard image override
    ".inventory-services.json",            # inventory services to stop (bench.INVENTORY_STATE)
    ".inventory-compose.json",             # inventory build override
    ".inventory-ports.yaml",               # inventory port override
    ".pending.json", ".pending.tmp",       # bin/checkpoint's pending-change decisions
})
DIRECTORIES = frozenset({".no-changes"})   # bin/checkpoint's no-op scenario
PROGRESS_PREFIX = "bench-progress-"         # live bench status (BenchProgress)
_SLOT = re.compile(r"factory-slots/[0-9]+")


def _in_root(relative):
    """(path within its bench's results root, whether that root is a factory slot)."""
    parts = PurePosixPath(relative).parts
    if len(parts) >= 3 and _SLOT.fullmatch("/".join(parts[:2])):
        return parts[2:], True
    return parts, False


def is_state(relative):
    """Whether a path relative to results/ is bench state rather than evidence."""
    parts, slot = _in_root(relative)
    if len(parts) == 1:
        name = parts[0]
        return name in FILES or name.startswith(PROGRESS_PREFIX) or (slot and name == SEED_IDS)
    return len(parts) > 1 and parts[0] in DIRECTORIES


def always_kept(relative):
    """The lock and a slot's seed IDs: left in place even by the wipe."""
    parts, slot = _in_root(relative)
    return parts == (LOCK,) or (slot and parts == (SEED_IDS,))
