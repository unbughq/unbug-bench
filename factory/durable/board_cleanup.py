"""Dedupe the statement board: release abandoned and duplicate entries, one change log to undo it.

Finding duplicates needs the statements, so it runs on a worker: a one-case batch whose INPUTS
carry `"board_dedup": true` (the import's real INPUTS otherwise, with `legacy_registry` for the
October board) makes ADMIT open the board's statements in worker RAM, exactly as the dedup screen
does, ask the easy calibrator (GLM) once to group the same bugs, and end with
`admit:board_planned`. It records only case IDs and a model family on the sealed card and never
returns a registry, so the board is unchanged. Everything below runs on the control VM, opens
no statement, and changes only statuses.

The board is a STATEMENT_REGISTRY plaintext, the JSON an operator passes to
`cli.py prepare <batch> registry <file>` (version 1, or the legacy form with "legacy": true).
Its statements are age ciphertext and are never opened here; only entry statuses change.

    board_cleanup.py plan    BOARD [--config CFG] [--plan-case CASE] [--duplicates BACKFILL.jsonl] [--group A,B ...]
                             [--sealed CASE ...] [--keep CASE ...]
    board_cleanup.py apply   BOARD --out NEW_BOARD --log CHANGES.json  (same options as plan)
    board_cleanup.py revert  BOARD --log CHANGES.json --out NEW_BOARD
    board_cleanup.py export  --config CFG BATCH --out BOARD     (the batch's newest board, read-only)

`plan` is the dry run and writes nothing. `apply` computes the same plan and writes a new board
file and a change log; it never overwrites a file. `revert` puts back every status the log
changed, but only where the entry still has the status the log gave it. A new board takes effect
only once an operator prepares it for a batch.

Rules, per entry:
  * known_public and sealed entries stay. Sealed means a durable `verified_seal` event (needs
    --config), a public scorecard in sealed/ with G1-G15 all passing, or --sealed.
  * live entries stay: a durable case whose workflow is still pending (needs --config), or
    status `building`. Without --config a durable `screening` entry is assumed live.
  * a group of mutual duplicates (the worker's GLM groups via --plan-case, the admission-reasons
    backfill output via --duplicates, or --group; overlapping groups merge) keeps
    its most advanced member (sealed > live > rest, then public gates passed, then oldest ID) and
    releases the others, unless they are sealed, live or known_public.
  * any other entry that is not sealed, live or known_public is abandoned: released.
  * --keep overrides everything for the cases it names.

Released duplicates get the status `released` (every screen already skips it) with reason
`duplicate_released` and their group in the plan and the log; a separate "duplicate" status would
need every registry reader changed.

Output is one JSON line per entry: case ID, old and new status, a fixed reason word and, for a
group, its members and the one kept. No statement, digest or reviewer text is printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

_CASE = re.compile(r"case-[A-Za-z0-9-]{1,80}")
_STATUSES = {"screening", "building", "completed", "known_public", "released"}
_SEAL_GATES = tuple(f"G{i}" for i in range(1, 16))
REPO = Path(__file__).resolve().parents[2]


class BoardError(ValueError):
    pass


def load_board(raw):
    value = json.loads(raw) if raw else {"version": 1, "registry": {"revision": 0, "entries": {}}, "objects": {}, "refs": {}}
    state = value.get("registry") if isinstance(value, dict) else None
    if (value.get("version") != 1 or not isinstance(state, dict) or type(state.get("revision")) is not int
            or not isinstance(state.get("entries"), dict)):
        raise BoardError("board_invalid")
    for case, entry in state["entries"].items():
        if not (isinstance(case, str) and _CASE.fullmatch(case) and isinstance(entry, dict)
                and entry.get("status") in _STATUSES):
            raise BoardError("board_invalid")
    return value


def public_gates(case, root=REPO / "sealed"):
    """Gates a case's public scorecard records as passed (0 when there is none)."""
    try:
        gates = json.loads((root / f"{case}.scorecard.json").read_text()).get("gates")
    except (OSError, ValueError):
        return 0
    return sum(v == "pass" for v in gates.values()) if isinstance(gates, dict) else 0


def publicly_sealed(case, root=REPO / "sealed"):
    try:
        card = json.loads((root / f"{case}.scorecard.json").read_text())
    except (OSError, ValueError):
        return False
    gates = card.get("gates") if isinstance(card.get("gates"), dict) else {}
    return card.get("failed_gate") is None and all(gates.get(g) == "pass" for g in _SEAL_GATES)


def duplicate_groups(backfill_lines, groups=()):
    """Connected groups of cases that a recorded dedup verdict (or the operator) tied together."""
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def join(a, b):
        parent[find(a)] = find(b)
    for line in backfill_lines:
        row = json.loads(line) if isinstance(line, str) else line
        if not isinstance(row, dict):
            continue
        # A rejected import is its October case's idea: tie that ID, not the new batch's.
        own = row.get("imported_case") if isinstance(row.get("imported_case"), str) else row.get("case")
        for candidate in row.get("candidates", []) if isinstance(row.get("candidates"), list) else []:
            other = candidate.get("duplicate_of") if isinstance(candidate, dict) else None
            if isinstance(own, str) and isinstance(other, str) and _CASE.fullmatch(own) and _CASE.fullmatch(other):
                join(own, other)
    for group in groups:
        members = [m for m in group if _CASE.fullmatch(m)]
        for m in members[1:]:
            join(members[0], m)
    out = {}
    for x in parent:
        out.setdefault(find(x), set()).add(x)
    return [g for g in out.values() if len(g) > 1]


def plan_groups(raw):
    """The groups a board-cleanup ADMIT recorded, from its CASE_SNAPSHOT (tar.gz) card only."""
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
        for member in archive:
            if member.name.removeprefix("./") == "scorecard.json" and member.isfile():
                card = json.load(archive.extractfile(member))
                break
        else:
            raise BoardError("plan_missing")
    groups = (card.get("board_dedup") or {}).get("groups")
    if not isinstance(groups, list) or not all(
            isinstance(g, list) and all(isinstance(m, str) and _CASE.fullmatch(m) for m in g) for g in groups):
        raise BoardError("plan_missing")
    return groups


def recorded_plan(config, case):
    """Open the last ADMIT snapshot of the board-cleanup case (existing key only) for its groups."""
    from durable import admission_reasons
    from durable.contract import CASE_ID
    if not CASE_ID.fullmatch(case):
        raise BoardError("invalid_case")
    rows = admission_reasons.backfill(config, [case], inspect=plan_groups)
    if rows[0].get("error"):
        raise BoardError("plan_" + rows[0]["error"])
    return rows[0]["inspected"]


def liveness(config, cases):
    """{case: (sealed, live)} for durable cases, from DBOS. Read-only."""
    from dbos import DBOSClient
    from durable.report import verified_seal
    client = DBOSClient(system_database_url=config["database_url"], retry_connection_errors=False,
                        observability_query_timeout_sec=3)
    try:
        out = {}
        for case in cases:
            runs = (client.list_workflows(workflow_ids=[case], load_input=False, load_output=False)
                    + client.list_workflows(workflow_id_prefix=case + "@", load_input=False, load_output=False))
            if not runs:
                continue
            sealed = verified_seal(client.get_event(case, "verified_seal", timeout_seconds=1)) is not None
            out[case] = (sealed, any(w.status in ("PENDING", "ENQUEUED") for w in runs))
        return out
    finally:
        client.destroy()


def plan(board, *, groups=(), sealed=(), keep=(), durable=None, sealed_root=REPO / "sealed"):
    """[{case, status, new, reason}] for every entry, sorted by case. Pure: nothing is written.
    `durable` maps case -> (sealed, live) from liveness(); None means unknown."""
    entries = board["registry"]["entries"]
    sealed, keep = set(sealed), set(keep)

    def kind(case):
        entry = entries[case]
        state = (durable or {}).get(case)
        if entry["status"] == "released":
            return "released"
        if entry["status"] == "known_public":
            return "known_public"
        if case in sealed or (state and state[0]) or publicly_sealed(case, sealed_root):
            return "sealed"
        if entry["status"] == "building" or (state and state[1]):
            return "live"
        if durable is None and entry["status"] == "screening":
            return "live"   # assumed: without DBOS a reservation may belong to a running case
        return "abandoned"

    kinds = {case: kind(case) for case in entries}
    rank = {"sealed": 3, "known_public": 3, "live": 2, "abandoned": 1, "released": 0}
    group_of = {}
    for group in groups:
        on_board = sorted(c for c in group if c in entries and kinds[c] != "released")
        if len(on_board) < 2:
            continue
        best = sorted(on_board, key=lambda c: (-rank[kinds[c]], -public_gates(c, sealed_root), c))[0]
        for c in on_board:
            group_of[c] = best
    rows = []
    for case in sorted(entries):
        status, k = entries[case]["status"], kinds[case]
        if case in keep:
            new, why = status, "operator_keep"
        elif k in ("released", "known_public", "sealed", "live"):
            new, why = status, k
        elif case in group_of and group_of[case] == case:
            new, why = status, "group_kept"
        elif case in group_of:
            new, why = "released", "duplicate_released"
        else:
            new, why = "released", "abandoned"
        row = {"case": case, "status": status, "new": new, "reason": why}
        if case in group_of:
            row["group_kept"] = group_of[case]
            row["group"] = sorted(c for c in group_of if group_of[c] == group_of[case])
        rows.append(row)
    return rows


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def apply_changes(board, changes):
    """A new board with each change's status written; the revision moves once per change."""
    value = json.loads(json.dumps(board))
    state = value["registry"]
    for case, old, new in changes:
        entry = state["entries"].get(case)
        if entry is None or entry["status"] != old:
            raise BoardError("board_changed")
        entry["status"] = new
        state["revision"] += 1
    return value


def _write_new(path, data):
    path = Path(path)
    with path.open("xb") as f:   # never overwrite a board or a log
        f.write(data)
    path.chmod(0o600)


def _options(parser):
    parser.add_argument("board", help="STATEMENT_REGISTRY plaintext JSON (the file given to `prepare`)")
    parser.add_argument("--config", help="durable config: read seals and live workflows from DBOS")
    parser.add_argument("--plan-case", help="the board-cleanup ADMIT case whose GLM groups to use (needs --config)")
    parser.add_argument("--duplicates", help="admission_reasons backfill output (JSON lines)")
    parser.add_argument("--group", action="append", default=[], help="comma-separated cases that are one idea")
    parser.add_argument("--sealed", action="append", default=[], help="a case to treat as sealed")
    parser.add_argument("--keep", action="append", default=[], help="a case whose status must not change")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="op", required=True)
    _options(commands.add_parser("plan", help="dry run: print the proposed change for every entry"))
    applying = commands.add_parser("apply", help="write a new board and a change log")
    _options(applying)
    applying.add_argument("--out", required=True)
    applying.add_argument("--log", required=True)
    reverting = commands.add_parser("revert", help="undo a change log on a board")
    reverting.add_argument("board")
    reverting.add_argument("--log", required=True)
    reverting.add_argument("--out", required=True)
    export = commands.add_parser("export", help="write a batch's newest board (read-only on the VM)")
    export.add_argument("--config", required=True)
    export.add_argument("batch")
    export.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.op == "export":
            from durable.runtime import load_config
            _write_new(args.out, export_board(load_config(args.config), args.batch))
            print(json.dumps({"exported": args.batch}))
            return 0
        raw = Path(args.board).read_bytes()
        board = load_board(raw)
        if args.op == "revert":
            log = json.loads(Path(args.log).read_text())
            if log.get("version") != 1:
                raise BoardError("log_invalid")
            entries = board["registry"]["entries"]
            # Undo only what still carries the logged status; anything changed since is reported.
            undo = [(c["case"], c["new"], c["status"]) for c in log["changes"]
                    if entries.get(c["case"], {}).get("status") == c["new"]]
            skipped = sorted(c["case"] for c in log["changes"] if entries.get(c["case"], {}).get("status") != c["new"])
            _write_new(args.out, json.dumps(apply_changes(board, undo), sort_keys=True).encode())
            print(json.dumps({"reverted": len(undo), "skipped_changed_since": skipped}))
            return 0
        lines = Path(args.duplicates).read_text().splitlines() if args.duplicates else []
        manual = [g.split(",") for g in args.group]
        durable = None
        if args.config:
            from durable.runtime import load_config
            config = load_config(args.config)
            if args.plan_case:
                manual += recorded_plan(config, args.plan_case)
            durable = liveness(config, list(board["registry"]["entries"]))
        elif args.plan_case:
            raise BoardError("plan_case_needs_config")
        groups = duplicate_groups([l for l in lines if l.strip()], manual)
        rows = plan(board, groups=groups, sealed=args.sealed, keep=args.keep, durable=durable)
        for row in rows:
            print(json.dumps(row, sort_keys=True))
        changes = [r for r in rows if r["new"] != r["status"]]
        summary = {"entries": len(rows), "release": len(changes), "liveness": "dbos" if durable is not None else "assumed",
                   "groups": len(groups)}
        if args.op == "apply":
            new = json.dumps(apply_changes(board, [(r["case"], r["status"], r["new"]) for r in changes]),
                             sort_keys=True).encode()
            log = {"version": 1, "board_sha256": digest(raw), "new_board_sha256": digest(new),
                   "changes": [{"case": r["case"], "status": r["status"], "new": r["new"], "reason": r["reason"]}
                               for r in changes]}
            _write_new(args.log, json.dumps(log, indent=1, sort_keys=True).encode())
            _write_new(args.out, new)
            summary["written"] = True
        print(json.dumps({"summary": summary}, sort_keys=True))
        return 0
    except FileExistsError:
        print("board_cleanup_refused_existing_output", file=sys.stderr)
        return 1
    except BoardError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print("board_cleanup_failed", file=sys.stderr)
        return 1


def export_board(config, batch):
    """The batch's newest board: its newest successful ADMIT's registry, else its initial one."""
    from dbos import DBOSClient
    from durable.artifacts import AgeSealer, SealedStore
    from durable.contract import BATCH_ID, Ref
    from durable.keys import AgeKeyService
    from durable.runtime import objects_for
    if not BATCH_ID.fullmatch(batch):
        raise BoardError("invalid_batch")
    client = DBOSClient(system_database_url=config["database_url"], retry_connection_errors=False,
                        observability_query_timeout_sec=3)
    keys = AgeKeyService(config["database_url"], restore_recipient=config["restore_recipient"],
                         founder_recipient=config["founder_recipient"], restore_identity=config["restore_identity"])
    try:
        rows = client.list_workflows(workflow_ids=[batch], load_input=True, load_output=False)
        if not rows:
            raise BoardError("unknown_batch")
        record, newest = rows[0].input["args"][0]["initial_registry"], -1
        for w in client.list_workflows(workflow_id_prefix=f"case-{batch[2:]}-", status="SUCCESS",
                                       name=["attempt_workflow", "prepared_attempt_workflow"],
                                       load_input=False, load_output=True):
            out = w.output if isinstance(w.output, dict) else {}
            result = out.get("result") if isinstance(out.get("result"), dict) else {}
            if out.get("started") and result.get("registry") and (w.updated_at or 0) > newest:
                newest, record = w.updated_at or 0, result["registry"]
        keys.wrapped_key(batch)   # an existing key only
        ref = Ref(**record)
        raw = AgeSealer().open(keys.scope_key(batch), ref, SealedStore(objects_for(config)).get_sealed(batch, ref))
        load_board(raw)
        return raw
    finally:
        client.destroy()
        keys.close()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
