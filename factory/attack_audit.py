"""Attack findings the gates never re-tested, and the attack round after the gates pass.

Both are non-blocking (FACTORY.md 4, 2026-11-10). Neither changes a gate's rule or the
two-round attack cap; they add evidence for the reviewers and a flag the exam reads.
"""
import json
import re

from attack_findings import classify

ROUND_REPORT = re.compile(r"round-([0-9]+)\.json")
AUDIT_LABEL = "audit-{}"


def _findings(report):
    return [f for f in report.get("blocking", []) if f.strip().lower() != "review incomplete"]


def last_attack_report(attacks):
    """(round, report) for the newest stress report, preferring its freshness-cleared writer copy."""
    rounds = sorted(int(m[1]) for p in attacks.glob("round-*.json") if (m := ROUND_REPORT.fullmatch(p.name)))
    if not rounds:
        return None, None
    n = rounds[-1]
    for name in (f"round-{n}-writer.json", f"round-{n}.json"):
        try:
            report = classify(json.loads((attacks / name).read_text()))
        except (OSError, ValueError):
            report = None
        if report is not None:
            return n, report
    return n, None


def open_findings(work, case_dir):
    """The last attack's blocking findings that no retained cheat replays.

    The last attack's findings get one writer fix and then GATES, with no further attack. A
    finding whose passing cheat the writer kept in guards/cheats is replayed by the writer's
    early checks and by G6. Any other finding (fairness, judge, freshness, or a cheat that was
    not kept) is checked by nobody after the fix. Matching is by the cheat's name in the
    finding's text; a finding that names no kept cheat counts as open (fail closed)."""
    n, report = last_attack_report(work / "attacks")
    if n is None:
        return None
    if report is None:
        return {"round": n, "findings": None, "replayed": 0, "open": None, "open_findings": []}
    findings = _findings(report)
    kept = {str(t.get("name")) for t in report.get("cheats_tried", []) if isinstance(t, dict)
            and t.get("passed") is True and isinstance(t.get("name"), str) and t["name"].strip()
            and "/" not in t["name"] and (case_dir / "guards" / "cheats" / t["name"]).is_dir()}
    replayed = [f for f in findings if any(name.lower() in f.lower() for name in kept)]
    unresolved = [f for f in findings if f not in replayed]
    return {"round": n, "findings": len(findings), "replayed": len(replayed), "open": len(unresolved),
            "open_findings": unresolved}


def review_note(found):
    """Text added to the G8/G9 panel request; empty when nothing is open."""
    if not found or not found.get("open_findings"):
        return ""
    return ("\nOpen attack findings. The stress tester reported these in the last attack round. The "
            "writer made one fix for them and no later attack or saved cheat re-tested them. For "
            "each one, check whether it still holds in this case. Judge it only by the fairness "
            "and realism rules above: a finding that still holds and breaks one of them belongs in "
            "that part's findings, and a finding alone is not a reason to reject.\n"
            + json.dumps(found["open_findings"], indent=1) + "\n")


def claimed_cheats(report):
    """Names of the audit's passing wrong fixes, as the attacker reported them."""
    names = []
    for t in report.get("cheats_tried", []):
        if (isinstance(t, dict) and t.get("passed") is True and isinstance(t.get("name"), str)
                and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", t["name"]) and t["name"] not in (".", "..")
                and t["name"] not in names):
            names.append(t["name"])
    return names


def find_guard(scratch, name):
    """The attacker's guard directory for a claimed cheat: one dir of that name with a guard file."""
    if not scratch.is_dir():
        return None
    found = [p for p in sorted(scratch.rglob(name)) if p.is_dir() and not p.is_symlink()
             and any((p / f).is_file() for f in ("db.sql", "app.patch"))]
    return found[0] if len(found) == 1 else None


def audit_record(n, report, confirmed, unverified):
    findings = _findings(report)
    return {"round": n, "complete": report.get("complete") is True, "findings": len(findings),
            "cheats_claimed": len(confirmed) + len(unverified), "cheats_confirmed": len(confirmed),
            "freshness_requests": len(report.get("freshness_review") or []),
            "cheat": bool(confirmed),
            "result": "cheat" if confirmed else "findings" if findings else "clean"}
