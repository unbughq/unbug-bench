#!/usr/bin/env python3
"""Screen case ideas before a batch is started, so start slots go only to ideas that can pass ADMIT.

    python3 control/prescreen.py MANIFEST [--board BOARD] [--history BACKFILL.jsonl]
                                 [--group A,B ...] [--identity AGE_KEY]

MANIFEST is a JSON list, one object per idea the operator means to start:
    {"label": "...", "inputs": "<INPUTS plaintext JSON>", "archive": "<checkpoint, optional>",
     "case": "<old case ID, optional>"}
Paths are relative to the manifest. Only the existing deterministic checks run, read-only and
without any model call, so this spends nothing:

  * inputs: `admit._inputs` (admit:inputs_invalid); a `board_dedup` run is flagged
    admit:board_planned, since it never produces a case.
  * import: with --identity (any age identity that opens the archive: the founder's key with the
    original checkpoint, or the statement key with the rewrapped one) `admit._import_legacy` runs
    in a temporary directory, then ADMIT's writer-family checks. Codes are ADMIT's own
    (import_layout*, import_pin, import_writer, import_idea_family, ...). Without it: unchecked.
  * dedup: an exact statement digest already held by an unreleased board entry, or by an earlier
    idea in the manifest; and every duplicate group known from the admission-reasons backfill
    (--history), --group, tied by `board_cleanup.duplicate_groups`. A group keeps the member
    `board_cleanup.plan` keeps (most advanced, then oldest ID); ADMIT dedups even the keeper
    against members still unreleased on the board, so those must be released first.
  * history: a final dedup, freshness or realism rejection already recorded for this same idea
    (a second family that overturned it does not count).

Freshness and realism need models and are never run here. Nothing looks at difficulty: a check
only predicts an admission refusal. Statements stay sealed on the board; an opened archive lives
in a temporary directory that is removed. Output is a table: drop (ADMIT will refuse), review
(likely refusal, or a step to take first), ok.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "factory"))
os.environ.setdefault("BENCH", str(REPO))   # run.BENCH: _same_app reads the pinned Medusa lockfile

from durable import board_cleanup   # noqa: E402
from durable.steps import admit   # noqa: E402

FINAL_SCREENS = ("admit:dedup_", "admit:freshness_", "admit:realism_")
_PROBE = "case-prescreen"
_FROM_BOARD = b"(statement held by the board)\n"


def check_import(raw, inputs, identity, entries):
    """(codes, old case ID, statement sha256 or None) for one archive, through ADMIT's own code."""
    import model_runtime
    import worker_secrets
    from model_router import family
    from run import argument_parser
    if inputs["dry_run"] or inputs.get("board_dedup"):
        return ["admit:inputs_invalid"], None, None
    from_board = []

    def board_statement(old):
        entry = entries.get(old)
        if not entry or entry["status"] == "released":
            return None
        from_board.append(old)
        return _FROM_BOARD

    with tempfile.TemporaryDirectory(prefix="prescreen-") as tmp:
        keys, work = Path(tmp) / "secrets", Path(tmp) / "work" / _PROBE
        keys.mkdir()
        work.parent.mkdir()
        (keys / "statements-key").symlink_to(Path(identity).resolve())
        saved, worker_secrets.SECRETS = worker_secrets.SECRETS, keys
        try:
            summary = admit._import_legacy(raw, work, inputs, _PROBE, board_statement)
        except (ValueError, KeyError, AttributeError, TypeError, tarfile.TarError) as error:
            code = str(error) if str(error) in admit.IMPORT_REFUSALS else "import_invalid"
            return ["admit:" + code], None, None
        except OSError:
            return ["import_unchecked"], None, None
        finally:
            worker_secrets.SECRETS = saved
        card = json.loads((work / "scorecard.json").read_text())
        statement = None if from_board else hashlib.sha256((work / "case/statement.md").read_bytes()).hexdigest()
    old = summary["case"]
    # Today's roles, as ADMIT will have them: pinned models, else the card's rotation slot.
    pinned = inputs.get("models") or {}
    roles = model_runtime.rotation(card["rotation_slot"]) if not pinned else {}
    writer = (pinned.get("builder") or [roles.get("writer", {}).get("model")])[0]
    judges = ([chain[0] for chain in pinned["reviewers"]] if pinned else [roles["reviewer"]["model"]])
    judges.append((pinned.get("easy_calibrator") or [argument_parser().parse_args(["--source", "port"]).easy_calibrator])[0])
    codes = []
    if summary.get("mode") == admit.IDEA_ONLY:
        if family(writer) not in admit.IDEA_WRITERS:
            codes.append("admit:import_idea_writer")
        if any(family(m) in summary["idea_families"] for m in judges):
            codes.append("admit:import_idea_family")
        recorded = (entries.get(old) or {}).get("statement_sha256")
        if statement is not None and recorded not in (None, statement):
            codes.append("admit:import_idea_statement")
    elif family(summary["writer"]) != family(writer):
        codes.append("admit:import_writer")
    if inputs.get("recertify") is True and not summary.get("recertify"):
        codes.append("admit:import_recertify")
    if statement is None:
        statement = (entries.get(old) or {}).get("statement_sha256")
    return codes, old, statement


def keepers(board, groups):
    """{case: the group member board_cleanup.plan keeps} for every member of every group."""
    kept = {r["case"]: r["group_kept"] for r in board_cleanup.plan(board, groups=groups) if "group_kept" in r}
    for group in groups:
        if not any(c in kept for c in group):   # members off the board or already released
            best = sorted(group, key=lambda c: (-board_cleanup.public_gates(c), c))[0]
            kept.update({c: best for c in group})
    return kept


def screen(ideas, board, history=(), manual=(), identity=None):
    """One row per idea: label, idea (old case ID), verdict, codes, keeper. Pure apart from the archives."""
    entries = board["registry"]["entries"]
    groups = board_cleanup.duplicate_groups(history, manual)
    keep = keepers(board, groups)
    prior = {}
    for row in history:
        own = row.get("imported_case") or row.get("case")
        if isinstance(row.get("reason"), str) and row["reason"].startswith(FINAL_SCREENS) and not row.get("overturned"):
            prior[own] = row["reason"]
    rows, seen = [], {}
    for idea in ideas:
        codes, keeper, case, digest = [], None, idea.get("case"), None
        try:
            inputs = admit._inputs(idea["inputs_raw"])
        except admit._Invalid:
            rows.append({"label": idea["label"], "idea": case, "verdict": "drop", "codes": ["admit:inputs_invalid"]})
            continue
        if inputs.get("board_dedup"):
            codes.append("admit:board_planned")
        if inputs.get("candidate"):
            digest = inputs["candidate"]["statement_sha256"]
        if idea.get("archive_raw") is not None:
            if identity:
                found, old, statement = check_import(idea["archive_raw"], inputs, identity, entries)
                codes += found
                case, digest = old or case, statement or digest
            else:
                codes.append("import_unchecked")
        elif inputs.get("recertify") is True:
            codes.append("admit:import_recertify")
        if digest:
            twin = next((c for c, e in sorted(entries.items()) if c != case and e["status"] != "released"
                         and e.get("statement_sha256") == digest), None)
            if twin:
                codes.append("admit:dedup_board_duplicate")
                keeper = twin
            elif digest in seen:
                codes.append("duplicate_in_manifest")
                keeper = seen[digest]
            seen.setdefault(digest, case or idea["label"])
        if case in keep:
            group = next(g for g in groups if case in g)
            if keep[case] != case:
                codes.append("admit:dedup_board_duplicate")
                keeper = keep[case]
            elif any(entries.get(c, {}).get("status") not in (None, "released") for c in group - {case}):
                codes.append("release_group_first")   # board_cleanup apply, then prepare the new board
                keeper = case
        if (entries.get(case) or {}).get("status") == "known_public":
            codes.append("board_known_public")
        if case in prior:
            codes.append("prior:" + prior[case].removeprefix("admit:"))
        hard = [c for c in codes if c.startswith("admit:") or c == "duplicate_in_manifest"]
        verdict = "drop" if hard else "review" if codes else "ok"
        rows.append({"label": idea["label"], "idea": case, "verdict": verdict, "codes": codes, "keep": keeper})
    return rows


def table(rows):
    head = ("LABEL", "IDEA", "VERDICT", "CHECKS", "KEEP")
    cells = [head] + [(r["label"], r.get("idea") or "-", r["verdict"], ",".join(r["codes"]) or "-", r.get("keep") or "-")
                      for r in rows]
    widths = [max(len(str(row[i])) for row in cells) for i in range(len(head))]
    return "\n".join("  ".join(str(v).ljust(w) for v, w in zip(row, widths)).rstrip() for row in cells) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("manifest")
    parser.add_argument("--board", help="STATEMENT_REGISTRY plaintext (board_cleanup.py export)")
    parser.add_argument("--history", help="admission_reasons.py backfill output (JSON lines)")
    parser.add_argument("--group", action="append", default=[], help="comma-separated cases that are one idea")
    parser.add_argument("--identity", help="age identity that opens the import archives")
    args = parser.parse_args(argv)
    base = Path(args.manifest).resolve().parent
    ideas = []
    for i, item in enumerate(json.loads(Path(args.manifest).read_text())):
        ideas.append({"label": item.get("label") or f"#{i + 1}", "case": item.get("case"),
                      "inputs_raw": (base / item["inputs"]).read_bytes(),
                      "archive_raw": (base / item["archive"]).read_bytes() if item.get("archive") else None})
    board = board_cleanup.load_board(Path(args.board).read_bytes() if args.board else b"")
    history = [json.loads(l) for l in Path(args.history).read_text().splitlines() if l.strip()] if args.history else []
    rows = screen(ideas, board, history, [g.split(",") for g in args.group], args.identity)
    sys.stdout.write(table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
