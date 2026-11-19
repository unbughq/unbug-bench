"""Why admission turned an idea down, as fixed codes that never hold idea text.

ADMIT (durable/steps/admit.py) records one row per rejected candidate and publishes one reason:

    admit:<screen>_<evidence>     every candidate fell to the same screen with the same evidence
    admit:<screen>_mixed          same screen, different evidence
    admit:rejected_mixed          different screens

The screens are the existing ones (run.statement_precheck): `dedup` (internal semantic duplicate
of a board entry), `freshness` (an independent reviewer confirmed a public match), `realism`
(independent idea review said no) and `other` (no candidate to judge). Evidence is a fixed word
derived from structured fields only: the dedup verdict's case ID and the registry status of that
entry, the freshness reviewer's per-URL answers (classified by URL shape, never echoed), and the
judging model's family. Free-text `reason`/`why`/`version_scope` fields are never read.

The sealed card keeps richer, still content-free details per candidate (duplicate case ID,
confirmed-source classes, a release tag's version against the pin). The backfill command below
prints those for already-finished cases. It runs on the control VM, is read-only and spends
nothing:

    python3 factory/durable/admission_reasons.py --config <durable config> <case or batch ID>...

For each case it finds the last ADMIT attempt that saved a snapshot, opens that snapshot in memory
with the case's existing key, reads only scorecard.json, freshness-verdict.json and
case/case.json (repo and pin), and prints one JSON line of codes. For a duplicate it also opens
the board that attempt screened against (its batch's STATEMENT_REGISTRY, batch key) and prints
the duplicate target's status there. It never creates a key, writes an object, extracts the
archive, decodes a stored statement or prints a URL, statement or reviewer sentence.
"""
from __future__ import annotations

import io
import json
import re
import sys
import tarfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

# run.statement_precheck's screen names -> the published screen word.
SCREENS = {"internal_duplicate": "dedup", "public_freshness": "freshness", "idea_realism": "realism"}
# Its fixed `precheck_problems` sentences for a candidate that was never judged.
_OTHER = {"candidate selection failed": "selection_failed", "missing statement.md": "missing_statement",
          "candidate was already rejected": "repeat_candidate"}
EVIDENCE = {
    "dedup": ("board_duplicate",),
    # Strongest first: an upstream fix outranks a report of the bug, which outranks docs or third parties.
    "freshness": ("upstream_fix", "upstream_report", "app_docs", "third_party", "unrecorded"),
    "realism": ("rejected",),
    "other": ("selection_failed", "missing_statement", "repeat_candidate", "unknown"),
}
REJECTION_CODES = tuple(f"{screen}_{word}" for screen, words in EVIDENCE.items()
                        for word in words + (("mixed",) if len(words) > 1 else ())) + ("rejected_mixed",)
REJECTION_REASONS = frozenset("admit:" + code for code in REJECTION_CODES)

_FAMILIES = {"anthropic", "openai", "minimax", "deepseek", "xiaomi", "meta", "xai", "alibaba", "z-ai", "google"}
_REGISTRY_STATUS = {"screening", "building", "completed", "known_public"}
_CASE = re.compile(r"case-[A-Za-z0-9-]{1,80}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SEMVER = re.compile(r"v?([0-9]+)\.([0-9]+)\.([0-9]+)(?:-[0-9A-Za-z.-]+)?")
_GITHUB_KIND = {"issues": "issue", "pull": "pull", "pulls": "pull", "commit": "commit", "commits": "commit",
                "releases": "release", "discussions": "discussion", "blob": "code", "tree": "code",
                "compare": "commit", "security": "advisory"}
_FIX = {"pull", "commit", "release", "advisory"}


def family(chain):
    """The judging model's family, from a fixed list ("other" otherwise)."""
    try:
        from model_router import family as of
        name = of(chain[0] if isinstance(chain, (list, tuple)) else chain)
    except Exception:
        return None
    return name if name in _FAMILIES else "other"


def source_class(url, app_repo):
    """A URL's shape as one fixed word. The URL itself is never returned."""
    if not isinstance(url, str):
        return "unknown"
    try:
        parts = urlsplit(url)
    except (TypeError, ValueError):
        return "unknown"
    host = (parts.hostname or "").lower()
    path = [p for p in parts.path.split("/") if p]
    if host in ("github.com", "www.github.com") and len(path) >= 2:
        own = app_repo is not None and f"{path[0]}/{path[1]}".lower() == app_repo.lower()
        kind = _GITHUB_KIND.get(path[2], "other") if len(path) > 2 else "repo"
        return ("upstream_" if own else "github_") + kind
    owner = app_repo.split("/")[0].lower() if app_repo else None
    if owner and (host == owner + ".com" or host.endswith("." + owner + ".com")):
        return "app_docs"
    if host.endswith(("npmjs.com", "npmjs.org")):
        return "package_registry"
    if host.endswith(("stackoverflow.com", "stackexchange.com", "reddit.com", "discord.com", "discord.gg")):
        return "forum"
    return "web"


def _version(text):
    match = _SEMVER.fullmatch(text) if isinstance(text, str) else None
    return tuple(int(x) for x in match.groups()) if match else None


def _release_version(url):
    """The version a release-tag URL names (github.com/<o>/<r>/releases/tag/<tag>), else None."""
    try:
        path = [p for p in urlsplit(url).path.split("/") if p]
    except (TypeError, ValueError):
        return None
    if len(path) == 5 and path[2:4] == ["releases", "tag"]:
        # Monorepo tags look like "@medusajs/medusa@2.19.1" or "v2.19.1".
        tag = unquote(path[4]).rsplit("@", 1)[-1]
        return tag.lstrip("v") if _version(tag) else None
    return None


def freshness_details(verdict, app_repo):
    """Content-free facts from the reviewer's confirmed public matches (freshness-verdict.json)."""
    hits = verdict.get("hits") if isinstance(verdict, dict) else None
    if not isinstance(hits, list):
        return {"evidence": "unrecorded"}
    # A receipt kept beside unresolved rows lists the rows G2 counted; an older one held only counted rows.
    counted = verdict.get("confirmed_rows")
    if isinstance(counted, list):
        hits = [h for i, h in enumerate(hits, 1) if i in counted]
    confirmed = [h for h in hits if isinstance(h, dict) and h.get("same_bug") is True and h.get("retrieved") is True
                 and isinstance(h.get("url"), str)]
    if not confirmed:
        return {"evidence": "unrecorded"}
    classes = sorted({source_class(h["url"], app_repo) for h in confirmed})
    kinds = {c.partition("_")[2] for c in classes if c.startswith("upstream_")}
    evidence = ("upstream_fix" if kinds & _FIX else "upstream_report" if kinds else
                "app_docs" if "app_docs" in classes else "third_party")
    details = {"evidence": evidence, "confirmed_hits": len(confirmed), "sources": classes,
               "archived_hits": sum(h.get("retrieved_from") == "archive" for h in confirmed)}
    pins = {h.get("app_version") for h in confirmed if _version(h.get("app_version"))}
    pin = pins.pop().lstrip("v") if len(pins) == 1 else None
    if pin:
        details["pin_version"] = pin
    releases = []
    for h in confirmed:
        found = _release_version(h["url"])
        if found and source_class(h["url"], app_repo) == "upstream_release":
            relation = None
            if pin:
                a, b = _version(found), _version(pin)
                relation = "before_pin" if a < b else "at_pin" if a == b else "after_pin"
            releases.append({"version": found, "relation": relation})
    if releases:
        details["fix_releases"] = sorted(releases, key=lambda r: _version(r["version"]))
    return details


def bound_verdict(verdict, statement_sha256):
    """The freshness receipt only if it judged this candidate: a later candidate whose verdict was
    never stored must not inherit an earlier candidate's sources."""
    binding = verdict.get("binding") if isinstance(verdict, dict) else None
    if isinstance(binding, dict) and binding.get("statement_sha256") not in (None, statement_sha256):
        return None
    return verdict


def candidate_row(card, *, verdict=None, app_repo=None, statuses=None, problems=None, models=None):
    """One rejected candidate's codes, from the card fields run.statement_precheck just wrote."""
    admission = card.get("admission") if isinstance(card.get("admission"), dict) else {}
    screen = SCREENS.get(admission.get("screen"))
    models = models if isinstance(models, dict) else card.get("models") if isinstance(card.get("models"), dict) else {}
    second = None
    if screen == "dedup":
        row = {"screen": screen, "evidence": "board_duplicate", "judge_family": family(models.get("easy_calibrator") or [])}
        second = (card.get("dedup") or {}).get("second_opinion")
        target = (card.get("dedup") or {}).get("duplicate_of")
        if isinstance(target, str) and _CASE.fullmatch(target):
            row["duplicate_of"] = target
            status = (statuses or {}).get(target)
            if status in _REGISTRY_STATUS:
                row["duplicate_status"] = status
    elif screen == "freshness":
        row = {"screen": screen, **freshness_details(bound_verdict(verdict, card.get("statement_sha256")), app_repo)}
        reviewers = models.get("reviewers") or [[]]
        row["judge_family"] = family(reviewers[0] if reviewers else [])
    elif screen == "realism":
        reviewers = models.get("reviewers") or [[]]
        row = {"screen": screen, "evidence": "rejected", "judge_family": family(reviewers[0] if reviewers else [])}
        second = (card.get("idea_realism") or {}).get("second_opinion")
    else:
        first = (problems or [None])[0]
        row = {"screen": "other", "evidence": _OTHER.get(first, "unknown")}
    if isinstance(second, dict):   # a second family's check of a dedup or realism rejection
        if second.get("second_family") in _FAMILIES | {"other"}:
            row["second_family"] = second["second_family"]
        if type(second.get("agreed")) is bool:
            row["agreed"] = second["agreed"]
    return {k: v for k, v in row.items() if v is not None}


def overturned(card):
    """Screens whose first-judge rejection a second family overturned on this card's last candidate."""
    found = []
    for screen, field in (("dedup", "dedup"), ("realism", "idea_realism")):
        second = (card.get(field) or {}).get("second_opinion") if isinstance(card.get(field), dict) else None
        if isinstance(second, dict) and second.get("agreed") is False:
            found.append(screen)
    return found


def reason_code(rows):
    """The one published code for a list of rejected candidates (see the module docstring)."""
    rows = [r.get("codes") if isinstance(r, dict) and isinstance(r.get("codes"), dict) else r for r in rows]
    pairs = {(r.get("screen"), r.get("evidence")) for r in rows if isinstance(r, dict)}
    pairs = {(s, e) if s in EVIDENCE and e in EVIDENCE[s] else ("other", "unknown") for s, e in pairs} or {("other", "unknown")}
    # A try that judged nothing (a repeat, a failed reselection) is bookkeeping: when any
    # candidate reached a screen, the reason is that screen's.
    judged = {(s, e) for s, e in pairs if s != "other"}
    pairs = judged or pairs
    screens = {s for s, _ in pairs}
    if len(screens) > 1:
        return "rejected_mixed"
    screen = screens.pop()
    return f"{screen}_{pairs.pop()[1]}" if len(pairs) == 1 else f"{screen}_mixed"


def legacy_rows(card, verdict=None, app_repo=None):
    """Rows for a card written before ADMIT recorded codes. Only the last candidate's own screen
    fields survive on such a card; earlier candidates keep their screen name alone."""
    rows = []
    rejected = card.get("rejected_candidates") if isinstance(card.get("rejected_candidates"), list) else []
    for index, old in enumerate(rejected):
        if not isinstance(old, dict):
            continue
        if isinstance(old.get("codes"), dict):   # recorded by ADMIT since admission_reasons existed
            rows.append(old["codes"])
            continue
        last = index == len(rejected) - 1
        screen = SCREENS.get(old.get("screen"))
        if last and screen:
            view = {**card, "admission": {"screen": old["screen"]}, "statement_sha256": old.get("statement_sha256")}
            rows.append(candidate_row(view, verdict=verdict if screen == "freshness" else None, app_repo=app_repo))
        elif screen:
            rows.append({"screen": screen, "evidence": EVIDENCE[screen][0] if len(EVIDENCE[screen]) == 1
                         else "unrecorded"})
        else:
            rows.append(candidate_row({}, problems=old.get("problems") if isinstance(old.get("problems"), list) else None))
    return rows


_MEMBERS = {"scorecard.json", "freshness-verdict.json", "case/case.json"}


def inspect_snapshot(raw):
    """A CASE_SNAPSHOT (tar.gz bytes) -> admission codes. Reads three small JSON members in memory."""
    found = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as archive:
        for member in archive:
            name = member.name.removeprefix("./")
            if name in _MEMBERS and member.isfile() and member.size <= 16 * 1024 * 1024:
                try:
                    found[name] = json.load(archive.extractfile(member))
                except (ValueError, UnicodeError):
                    found[name] = None
    card = found.get("scorecard.json")
    if not isinstance(card, dict):
        return {"error": "card_unreadable"}
    app = (found.get("case/case.json") or {}).get("app") if isinstance(found.get("case/case.json"), dict) else None
    repo = re.sub(r"^https://github\.com/|\.git$", "", str((app or {}).get("repo", "")))
    repo = repo if _REPO.fullmatch(repo) else None
    rows = legacy_rows(card, found.get("freshness-verdict.json"), repo)
    admission = card.get("admission") if isinstance(card.get("admission"), dict) else {}
    out = {"admission_status": admission.get("status") if admission.get("status") in (
               "exhausted", "rejected", "passed", "waiting", "evidence_incomplete") else "other",
           "imported": isinstance(card.get("imported_from"), dict), "candidates": rows}
    old_case = (card.get("imported_from") or {}).get("case") if isinstance(card.get("imported_from"), dict) else None
    if isinstance(old_case, str) and _CASE.fullmatch(old_case):
        out["imported_case"] = old_case
    if rows:
        out["reason"] = "admit:" + reason_code(rows)
    if overturned(card):
        out["overturned"] = overturned(card)
    return out


# ---- the VM backfill: read-only, prints codes only --------------------------------------------

def _admit_snapshots(client, case_id):
    """(seq, attempt, published reason, snapshot Ref record) for the case's ADMIT attempts with a snapshot."""
    from durable.classify import PUBLISHED_REASONS
    from durable.contract import Step, StepKind
    rows = client.list_workflows(workflow_id_prefix=case_id + "/", name=["attempt_workflow", "prepared_attempt_workflow"],
                                 load_input=True, load_output=True)
    found = []
    for row in rows:
        args = row.input.get("args", []) if isinstance(row.input, dict) else []
        value = args[0].get("input", {}) if args and isinstance(args[0], dict) else {}
        result = row.output.get("result") if isinstance(row.output, dict) else None
        try:
            admit = Step(**value["step"]).kind is StepKind.ADMIT
        except Exception:
            continue
        if (admit and value.get("case_id") == case_id and isinstance(result, dict)
                and isinstance(result.get("snapshot"), dict)
                and type(value.get("seq")) is int and type(value.get("attempt")) is int):
            reason = result.get("reason") if result.get("reason") in PUBLISHED_REASONS else None
            found.append((value["seq"], value["attempt"], reason, result["snapshot"],
                          value.get("batch_id"), value.get("registry")))
    return sorted(found, key=lambda f: f[:2])


def registry_statuses(plaintext):
    """{case ID: board status} from a STATEMENT_REGISTRY plaintext. Statements in it stay
    ciphertext and are never decoded; only each entry's fixed status is read."""
    if not plaintext:
        return {}
    value = json.loads(plaintext)
    entries = ((value.get("registry") or {}).get("entries") if isinstance(value, dict) else None) or {}
    return {case: entry["status"] for case, entry in entries.items()
            if isinstance(case, str) and _CASE.fullmatch(case) and isinstance(entry, dict)
            and entry.get("status") in _REGISTRY_STATUS | {"released"}}


def _with_statuses(entry, statuses):
    for row in entry.get("candidates", []):
        if row.get("duplicate_of") and "duplicate_status" not in row:
            row["duplicate_status"] = statuses.get(row["duplicate_of"], "not_on_board")


def _cases(client, target):
    from durable.contract import BATCH_ID, CASE_ID
    if CASE_ID.fullmatch(target):
        return [target]
    if BATCH_ID.fullmatch(target):
        cases = client.get_event(target, "cases", timeout_seconds=1) or []
        return [c for c in cases if isinstance(c, str) and CASE_ID.fullmatch(c)]
    raise ValueError("invalid_target")


def backfill(config, targets, *, client=None, keys=None, store=None, inspect=None):
    """One result per case. Never creates a key or writes anything."""
    from durable.artifacts import AgeSealer, SealedStore
    from durable.contract import Ref
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
        for target in targets:
            try:
                cases = _cases(client, target)
            except Exception:
                results.append({"target": target if re.fullmatch(r"[a-z0-9-]{1,90}", target) else None,
                                "error": "invalid_target"})
                continue
            if not cases:
                results.append({"target": target, "error": "no_cases"})
            for case_id in cases:
                entry = {"case": case_id}
                try:
                    attempts = _admit_snapshots(client, case_id)
                except Exception:
                    attempts = None
                if not attempts:
                    entry["error"] = "no_admit_snapshot" if attempts == [] else "workflows_unavailable"
                    results.append(entry)
                    continue
                seq, attempt, reason, record, batch, board = attempts[-1]
                entry.update(seq=seq, attempt=attempt, recorded_reason=reason)
                try:
                    keys.wrapped_key(case_id)   # an existing key only: scope_key would create a missing one
                    ref = Ref(**record)
                    raw = sealer.open(keys.scope_key(case_id), ref, store.get_sealed(case_id, ref))
                except Exception:
                    entry["error"] = "snapshot_unavailable"
                    results.append(entry)
                    continue
                try:
                    if inspect is not None:   # another read-only reader (board_cleanup.plan_groups)
                        entry["inspected"] = inspect(raw)
                        results.append(entry)
                        continue
                    entry.update(inspect_snapshot(raw))
                except Exception:
                    entry["error"] = "snapshot_unreadable"
                finally:
                    del raw
                # The board this ADMIT screened against: each duplicate target's status there.
                if any(r.get("duplicate_of") for r in entry.get("candidates", [])):
                    try:
                        keys.wrapped_key(batch)
                        ref = Ref(**board)
                        _with_statuses(entry, registry_statuses(
                            sealer.open(keys.scope_key(batch), ref, store.get_sealed(batch, ref))))
                    except Exception:
                        entry["board"] = "unavailable"
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
    parser = argparse.ArgumentParser(description="Print why admission rejected each listed case, as fixed codes.")
    parser.add_argument("--config", required=True, help="the durable service's owned 0600 JSON configuration file")
    parser.add_argument("targets", nargs="+", help="case IDs (case-...) or batch IDs (b-...)")
    args = parser.parse_args(argv)
    try:
        from durable.runtime import load_config
        results = backfill(load_config(args.config), args.targets)
    except Exception:
        print("admission_reasons_failed", file=sys.stderr)
        return 1
    for row in results:
        print(json.dumps(row, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
