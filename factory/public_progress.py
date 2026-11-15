"""Atomic public stage progress: only fixed operational metadata, never case content."""
import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading

_LOCK = threading.RLock()
_ROLES = {"writer", "stress_tester", "reviewer", "strong_tester", "easy_tester", "second_writer", "diagnoser"}
_STATUSES = {"running", "completed", "failed", "interrupted"}
# Fixed writer-step phases (run.writer_phase), for measuring time to seal; "freshness" is timed
# in the stress step since it left the writer round (older writer records keep it).
PHASES = ("bench_prepare", "writer_model", "g1", "early_checks", "freshness")


def _stage(stage):
    return isinstance(stage, str) and (re.fullmatch(r"(?:early:)?G(?:[1-9]|1[0-7])", stage) is not None
           or re.fullmatch(r"comparison(?::(?:stress|G(?:[1-9]|1[0-7])))?", stage) is not None
           or stage in {"role:" + role for role in _ROLES}
           or stage in {"phase:writer:" + phase for phase in PHASES} or stage == "phase:stress:freshness")


def _timestamp(value):
    if not isinstance(value, str): return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None: return None
        return parsed.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def _row(value):
    if not isinstance(value, dict) or not isinstance(value.get("status"), str) or value["status"] not in _STATUSES: return None
    stamp = _timestamp(value.get("updated_at"))
    if stamp is None: return None
    clean = {"status": value["status"], "updated_at": stamp, "reused": value.get("reused") is True}
    elapsed = value.get("elapsed_seconds")
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
        clean["elapsed_seconds"] = elapsed
    return clean


def publish(path, stage, status, elapsed_seconds=None, reused=False):
    """One canonical path per case. Repeated roles replace their latest state, not history.

    Completed stages remain separate while a new attempt runs. This is observational
    metadata, not a gate result, checkpoint receipt, or proof of collection.
    """
    if not _stage(stage) or not isinstance(status, str) or status not in _STATUSES or type(reused) is not bool:
        raise ValueError("invalid public progress stage or status")
    if elapsed_seconds is not None and (type(elapsed_seconds) not in (int, float)
            or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0):
        raise ValueError("invalid elapsed seconds")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            previous = json.loads(path.read_text()) if not path.is_symlink() else {}
        except (OSError, ValueError):
            previous = {}
        if not isinstance(previous, dict): previous = {}
        # Rebuild even existing records from the allowlist rather than copying arbitrary JSON.
        data = {"schema": 1, "stages": {}, "completed": {}}
        for section in ("stages", "completed"):
            rows = previous.get(section, {})
            if isinstance(rows, dict):
                for name, row in rows.items():
                    clean = _row(row)
                    if _stage(name) and clean and (section != "completed" or clean["status"] == "completed"):
                        data[section][name] = clean
        now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        row = {"status": status, "updated_at": now, "reused": reused}
        if elapsed_seconds is not None: row["elapsed_seconds"] = round(elapsed_seconds, 3)
        data["stages"][stage] = row
        if status == "completed": data["completed"][stage] = row
        data["updated_at"] = now
        data["last_completed_at"] = max((r["updated_at"] for r in data["completed"].values()), default=None)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix="." + path.name + ".", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
    return data
