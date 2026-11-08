"""Why free-route model calls ended early, read from a case's sealed snapshot. Read-only, no spend.

For each listed case it opens the case's latest saved snapshot in memory with the case's existing
key (as admission_reasons.py's backfill does), and for each lease ID or prefix prints:

    from usage-receipts/<lease>.json   outcome, failure_reason, source_stop, final_usage_known,
                                       invocation (a fixed role call name)
    from that invocation's transcripts each OpenCode {"type": "error"} event's error.name,
                                       data.statusCode and data.message cut to 200 characters

Nothing else from the transcripts is read or printed. It never creates a key, writes an object
or extracts the archive. Run it on the control VM:

    python3 factory/durable/free_route_errors.py --config <durable config> \\
        --case case-fresh-1108a-1 --case case-fresh-1108b-1 --lease 2575841a --lease 42aa2c2e ...
"""
from __future__ import annotations

import io
import json
import re
import sys
import tarfile
from pathlib import Path

_LEASE = re.compile(r"[a-f0-9]{8,32}")
_NAME = re.compile(r"[A-Za-z0-9_.-]{1,120}")
_ERROR_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.]{0,59}")
_RECEIPT = re.compile(r"usage-receipts/([a-f0-9]{32})\.json")
_TRANSCRIPT = re.compile(r"transcripts/([A-Za-z0-9_.-]{1,120})\.([0-9]{1,25})\.jsonl")
MESSAGE_CHARS = 200
_MEMBER_LIMIT = 64 * 1024 * 1024
_OUTCOMES = {"done", "interrupted", "denied"}
_REASONS = {"quota", "rate", "credit", "outage", "router_unavailable", "credential_expiring", "unbounded_route"}


def _receipt_fields(value):
    if not isinstance(value, dict):
        return {"receipt": "unreadable"}
    invocation = value.get("invocation")
    stop = value.get("source_stop")
    return {"outcome": value.get("outcome") if value.get("outcome") in _OUTCOMES else None,
            "failure_reason": value.get("failure_reason") if value.get("failure_reason") in _REASONS else None,
            "source_stop": stop if isinstance(stop, str) and re.fullmatch(r"[a-z_]{1,40}", stop) else None,
            "final_usage_known": value.get("final_usage_known") if type(value.get("final_usage_known")) is bool else None,
            "invocation": invocation if isinstance(invocation, str) and _NAME.fullmatch(invocation) else None}


def _error_events(stream):
    """Only {"type": "error"} events: error.name, data.statusCode and data.message (200 chars)."""
    found = []
    for line in stream:
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "error":
            continue
        error = event.get("error") if isinstance(event.get("error"), dict) else {}
        data = error.get("data") if isinstance(error.get("data"), dict) else {}
        name, status, message = error.get("name"), data.get("statusCode"), data.get("message")
        found.append({"name": name if isinstance(name, str) and _ERROR_NAME.fullmatch(name) else None,
                      "status": status if type(status) is int and 100 <= status <= 599 else None,
                      "message": message[:MESSAGE_CHARS] if isinstance(message, str) else None})
    return found


def inspect_snapshot(raw, leases):
    """A CASE_SNAPSHOT (tar.gz bytes) -> one row per lease prefix found. Reads members in memory only."""
    receipts, transcripts = {}, {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
        members = [m for m in archive if m.isfile() and m.size <= _MEMBER_LIMIT]
        for member in members:
            match = _RECEIPT.fullmatch(member.name.removeprefix("./"))
            if match and any(match.group(1).startswith(p) for p in leases):
                try:
                    receipts[match.group(1)] = json.load(archive.extractfile(member))
                except (ValueError, UnicodeError):
                    receipts[match.group(1)] = None
        wanted = {f["invocation"] for f in map(_receipt_fields, receipts.values()) if f.get("invocation")}
        for member in members:
            match = _TRANSCRIPT.fullmatch(member.name.removeprefix("./"))
            if match and match.group(1) in wanted:
                transcripts.setdefault(match.group(1), []).append(
                    {"started_ns": int(match.group(2)),
                     "errors": _error_events(io.TextIOWrapper(archive.extractfile(member), errors="replace"))})
    rows = []
    for prefix in leases:
        hits = sorted(lease for lease in receipts if lease.startswith(prefix))
        if not hits:
            rows.append({"lease": prefix, "error": "no_receipt"})
        for lease in hits:
            fields = _receipt_fields(receipts[lease])
            runs = sorted(transcripts.get(fields.get("invocation"), []), key=lambda t: t["started_ns"])
            rows.append({"lease": lease, **fields, "transcripts": runs})
    return rows


# ---- the VM read: prints content-free fields only ----------------------------------------------

def _latest_snapshot(client, case_id):
    """(seq, attempt, snapshot Ref record) of the case's latest attempt that saved a snapshot."""
    rows = client.list_workflows(workflow_id_prefix=case_id + "/", name=["attempt_workflow", "prepared_attempt_workflow"],
                                 load_input=True, load_output=True)
    found = []
    for row in rows:
        args = row.input.get("args", []) if isinstance(row.input, dict) else []
        value = args[0].get("input", {}) if args and isinstance(args[0], dict) else {}
        result = row.output.get("result") if isinstance(row.output, dict) else None
        if (value.get("case_id") == case_id and isinstance(result, dict) and isinstance(result.get("snapshot"), dict)
                and type(value.get("seq")) is int and type(value.get("attempt")) is int):
            found.append((value["seq"], value["attempt"], result["snapshot"]))
    return max(found, key=lambda f: f[:2]) if found else None


def read(config, cases, leases, *, client=None, keys=None, store=None):
    """One result per case. Never creates a key or writes anything."""
    from durable.artifacts import AgeSealer, SealedStore
    from durable.contract import CASE_ID, Ref
    if not leases or any(not _LEASE.fullmatch(p) for p in leases):
        raise ValueError("invalid_lease")
    owned = []
    if client is None:
        from dbos import DBOSClient
        client = DBOSClient(system_database_url=config["database_url"], retry_connection_errors=False,
                            observability_query_timeout_sec=3)
        owned.append(client.destroy)
    if keys is None:
        from durable.keys import AgeKeyService
        keys = AgeKeyService(config["database_url"], restore_recipient=config["restore_recipient"],
                             founder_recipient=config["founder_recipient"], restore_identity=config["restore_identity"])
        owned.append(keys.close)
    if store is None:
        from durable.runtime import objects_for
        store = SealedStore(objects_for(config))
    sealer, results = AgeSealer(), []
    try:
        for case_id in cases:
            if not CASE_ID.fullmatch(case_id):
                results.append({"case": None, "error": "invalid_case"})
                continue
            entry = {"case": case_id}
            try:
                latest = _latest_snapshot(client, case_id)
            except Exception:
                entry["error"] = "workflows_unavailable"
                results.append(entry)
                continue
            if latest is None:
                entry["error"] = "no_snapshot"
                results.append(entry)
                continue
            entry.update(seq=latest[0], attempt=latest[1])
            try:
                keys.wrapped_key(case_id)   # an existing key only: scope_key would create a missing one
                ref = Ref(**latest[2])
                raw = sealer.open(keys.scope_key(case_id), ref, store.get_sealed(case_id, ref))
            except Exception:
                entry["error"] = "snapshot_unavailable"
                results.append(entry)
                continue
            try:
                entry["leases"] = [row for row in inspect_snapshot(raw, leases) if row.get("error") != "no_receipt"]
            except Exception:
                entry["error"] = "snapshot_unreadable"
            finally:
                del raw
            results.append(entry)
    finally:
        for close in owned:
            try:
                close()
            except Exception:
                pass
    return results


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Print why listed free-route calls ended early, content-free.")
    parser.add_argument("--config", required=True, help="the durable service's owned 0600 JSON configuration file")
    parser.add_argument("--case", action="append", required=True, help="case ID (repeatable)")
    parser.add_argument("--lease", action="append", required=True, help="lease ID or 8+ hex prefix (repeatable)")
    args = parser.parse_args(argv)
    try:
        from durable.runtime import load_config
        results = read(load_config(args.config), args.case, [p.lower() for p in args.lease])
    except Exception:
        print("free_route_errors_failed", file=sys.stderr)
        return 1
    for row in results:
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
