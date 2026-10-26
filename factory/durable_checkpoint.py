"""Throttled full encrypted checkpoints at proven quiescent runner boundaries.

Each attempt remains durable on the worker immediately. Off-worker protection only
advances after this full archive finishes uploading; active calls are never copied.
"""
import hashlib
import json
import pathlib
import time
from registry import atomic_json



def checkpoint_progress(c, seal, *, quiescent, now=None, interval=900):
    """Call only after all workers have joined. Failures stay pending and are nonfatal.

    The first safe boundary is copied, then at most once per interval. This reuses
    the full archive path (and its cost), rather than copying each call's transcript.
    No DONE marker or terminal status is written here.
    """
    if not quiescent: return False
    now = time.monotonic() if now is None else now
    previous = getattr(c, "durable_checkpoint_at", None)
    if previous is not None and now - previous < interval: return False
    c.durable_checkpoint_at = now
    receipt = {"version": 1, "at": int(time.time()), "local_durable": False,
               "remote_durable": False, "pending": True}
    c.card["durable_checkpoint"] = receipt
    public = {key: c.card[key] for key in ("sha256", "archive", "r2_object") if key in c.card}
    for key in ("sha256", "archive", "r2_object"): c.card.pop(key, None)
    try:
        ledger = pathlib.Path(c.ledger)
        if ledger.exists():
            data = ledger.read_bytes()
            c.card["continuation_budget"] = json.loads(data)
            atomic_json(c.work / "continuation-budget.json", c.card["continuation_budget"])
        seal(c, checkpoint=True)
        archive = pathlib.Path(c.card["archive"])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != c.card["sha256"]: raise ValueError("checkpoint digest mismatch")
        receipt.update(local_durable=True, sha256=digest, archive=str(archive))
        if isinstance(c.card.get("r2_object"), str) and c.card["r2_object"]:
            receipt.update(remote_durable=True, pending=False, r2_object=c.card["r2_object"])
        else:
            receipt["reason"] = "remote_upload_unavailable_or_failed"
    except Exception as error:
        receipt["error"] = type(error).__name__
    finally:
        for key in ("sha256", "archive", "r2_object"): c.card.pop(key, None)
        c.card.update(public)
    try:
        atomic_json(c.work / "durable-checkpoint.json", receipt)
        atomic_json(c.work / "scorecard.json", c.card)
    except OSError as error:
        receipt["progress_write_error"] = type(error).__name__
    return True
