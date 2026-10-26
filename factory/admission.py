"""Worker-side admission checks. Shared transport supplies ciphertext plus a bound reservation.

The trusted coordinator must serialize reservations and include every active reservation and
accepted case in the snapshot. It must refresh/revoke the reservation on candidate changes.
No plaintext statements or keys cross the worker boundary. An unattested local directory is
not a shared registry; absent transport therefore blocks construction.
"""
import datetime
import hashlib
import json
import re
from urllib.parse import urlparse
from calibration import guard_submitted

SEARCH_TTL = datetime.timedelta(hours=24)
MAX_CANDIDATES = 3
MAX_PROTOTYPE_ATTEMPTS = 2


def search_binding(c, rows):
    statement = c.case / "statement.md"
    return {"case_id": getattr(c, "case_id", None),
            "statement_sha256": hashlib.sha256(statement.read_bytes()).hexdigest() if statement.is_file() else None,
            "reservation": getattr(c, "admission_binding", None),
            "models": getattr(c, "models", {}),
            "context": {name: hashlib.sha256((c.case / name).read_bytes()).hexdigest()
                        for name in ("case.json", "promise.md", "disclosure.md", "provenance.json")
                        if (c.case / name).is_file()},
            "evidence_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}


def reusable_search(receipt, binding, now=None):
    """Only a complete verdict for these exact inputs can avoid another search review."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not isinstance(receipt, dict) or receipt.get("version") != 1 or receipt.get("binding") != binding:
        return None
    try:
        at = datetime.datetime.fromisoformat(receipt["checked_at"])
        expires = datetime.datetime.fromisoformat(receipt["expires_at"])
        if not at.tzinfo or not expires.tzinfo or not at <= now < expires <= at + SEARCH_TTL: return None
    except (KeyError, TypeError, ValueError): return None
    if type(receipt.get("ok")) is not bool or not isinstance(receipt.get("info"), dict): return None
    info = receipt["info"]
    if any(type(info.get(k)) is not int or info[k] < 0 for k in ("searches", "hits", "flagged_hits", "invalid_evidence")): return None
    counts = info.get("counted")
    if not isinstance(counts, dict) or any(type(counts.get(k)) is not int or counts[k] < 0 for k in ("builder_web", "builder_github", "attacker")): return None
    if receipt["ok"] and (info["invalid_evidence"] or info["hits"] or counts["builder_web"] < 3 or counts["builder_github"] < 3 or counts["attacker"] < 2): return None
    return receipt["ok"], receipt["info"]


def search_receipt(binding, ok, info):
    now = datetime.datetime.now(datetime.timezone.utc)
    return {"version": 1, "binding": binding, "checked_at": now.isoformat(),
            "expires_at": (now + SEARCH_TTL).isoformat(), "ok": ok, "info": info}


def registry_snapshot(directory, case_id, statement):
    attestation = json.loads((directory / "admission.json").read_text())
    digest = hashlib.sha256(statement.encode()).hexdigest()
    if (attestation.get("version") != 1 or attestation.get("case_id") != case_id or
            attestation.get("statement_sha256") != digest or attestation.get("complete") is not True or
            type(attestation.get("registry_revision")) is not int or attestation["registry_revision"] < 0 or
            not isinstance(attestation.get("reservation"), str) or not attestation["reservation"]):
        raise ValueError("missing or stale shared admission reservation")
    expected = attestation.get("statements")
    if not isinstance(expected, dict): raise ValueError("invalid registry snapshot")
    files = {p.name.removesuffix(".statement.age"): p for p in directory.glob("*.statement.age")}
    if set(files) != set(expected): raise ValueError("incomplete registry snapshot")
    for name, path in files.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name): raise ValueError("invalid statement case id")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]:
            raise ValueError("registry ciphertext digest mismatch")
    return {name: path for name, path in files.items() if name != case_id}


def selection_snapshot(directory, case_id):
    """A complete advisory board is useful before a candidate can be reserved."""
    path = directory / "selection-board.json"
    if path.is_symlink(): raise ValueError("unsafe selection board")
    board = json.loads(path.read_text())
    if (not isinstance(board, dict) or board.get("version") != 1 or board.get("scope") != "selection_only" or
            board.get("complete") is not True or type(board.get("registry_revision")) is not int or
            board["registry_revision"] < 0 or not isinstance(board.get("statements"), dict)):
        raise ValueError("invalid selection board")
    files = {p.name.removesuffix(".statement.age"): p for p in directory.glob("*.statement.age")}
    if set(files) != set(board["statements"]): raise ValueError("incomplete selection board")
    for name, p in files.items():
        if (not re.fullmatch(r"case-[A-Za-z0-9-]+", name) or p.is_symlink() or not p.is_file() or
                hashlib.sha256(p.read_bytes()).hexdigest() != board["statements"][name]):
            raise ValueError("selection board ciphertext digest mismatch")
    return {name: p for name, p in files.items() if name != case_id}


def search_url_error(row):
    """URL validity independent of the other fields that may need repair."""
    if not isinstance(row.get('url'), str) or not row['url'].strip(): return 'missing_url'
    try: url = urlparse(row['url'])
    except ValueError: return 'invalid_url'
    if url.scheme not in ('https', 'http') or not url.hostname or '.' not in url.hostname: return 'invalid_url'
    if url.hostname in ('example.com', 'example.org', 'example.net') or url.hostname.endswith('.invalid'): return 'invalid_url'
    if row.get('kind') == 'github' and url.hostname not in ('github.com', 'www.github.com', 'api.github.com'): return 'github_url_required'
    return None


def search_evidence_error(row):
    """A fixed reason code, safe for public counters and private row-level repair."""
    if not isinstance(row, dict) or row.get("invalid_record"): return "invalid_record"
    if row.get("who") not in ("builder", "attacker"): return "invalid_who"
    if row.get("kind") not in ("web", "github"): return "invalid_kind"
    if type(row.get("hit")) is not bool: return "invalid_hit"
    if row.get("retrieved") is not True: return "retrieval_failed"
    fields = ("query", "url", "at", "note", "app_version", "version_scope")
    for field in fields:
        if not isinstance(row.get(field), str) or not row[field].strip(): return "missing_" + field
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+].*)?", row["app_version"]): return "invalid_app_version"
    if reason := search_url_error(row): return reason
    try:
        at = datetime.datetime.fromisoformat(row["at"].replace("Z", "+00:00"))
        if at.tzinfo is None: return "timestamp_timezone_missing"
        now = datetime.datetime.now(datetime.timezone.utc)
        if at > now: return "timestamp_in_future"
        if now >= at + SEARCH_TTL: return "evidence_expired"
    except (ValueError, OverflowError): return "invalid_timestamp"
    return None


def search_evidence(row):
    """Count only valid, distinct searches; keep the existing caller interface."""
    if search_evidence_error(row) is not None: return None
    return (row.get("who"), row["kind"], " ".join(row["query"].casefold().split()))


def prototype(run, c):
    """One-run rejection screen only; final seeded gates are unchanged."""
    required = ("case.json", "statement.md", "promise.md", "base/scenario.json", "base/key.json",
                "base/hooks.mjs", "base/judge.py")
    missing = [name for name in required if not (c.case / name).is_file()]
    guards = sorted(p for p in (c.case / "guards/cheats").glob("*") if p.is_dir())
    ref = c.case / "guards/reference"
    if not guard_submitted(ref): missing.append("reference guard")
    if not guards: missing.append("one plausible wrong fix")
    meta = run.jload(c.case / "case.json", {})
    if not (meta.get("promise_paths") or meta.get("promise_checks")): missing.append("promise observation")
    if missing: return False, {"missing": missing}
    ok, info = run.g3(c)
    if not ok: return False, {"setup": info}
    outcomes = {}
    for name, guard in (("none", run.BENCH / "guards/none"), ("reference", ref),
                        ("refuse-all", run.BENCH / "guards/refuse-all"), ("wrong-fix", guards[0])):
        summary, records = run.checkpoint(c, [c.case / "base"], guard, 1, c.seed, "prototype-" + name)
        rows = run.verdicts(c, records)
        valid = len(rows) == 1 and all(row["clean"] for row in rows)
        if name == "none": valid = valid and rows[0]["broken"]
        elif name == "reference": valid = valid and rows[0]["solved"] and summary.get("legit_completion", 0) >= .95
        else: valid = valid and not rows[0]["solved"]
        outcomes[name] = bool(valid)
        if not valid: return False, {"checks": outcomes}
    return True, {"checks": outcomes, "runs": 1, "final_gates_required": True}
