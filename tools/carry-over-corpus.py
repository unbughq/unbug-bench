#!/usr/bin/env python3
"""Read public scorecard metadata only; never open archives, prompts or search rows."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "factory"))
import carry_over


def paths(repo, developer):
    result = set((repo / "sealed").glob("*.scorecard.json"))
    for root in developer.glob("unbug-bench-*-restore-*"):
        result.update((root / "sealed").glob("*.scorecard.json"))
        if (root / "input-scorecard.json").is_file(): result.add(root / "input-scorecard.json")
    return sorted(result)


def inspect(path):
    result = {"path": str(path), "status": "REFUSED", "reasons": [], "case": None,
              "state_version": None, "case_spent_usd": None, "waste_usd": None,
              "remaining_usd": None, "allowances": None, "next_step": "worker reconciliation",
              "admitted": False}
    try:
        raw = path.read_bytes()
        result["source_sha256"] = hashlib.sha256(raw).hexdigest()
        card = json.loads(raw)
        value = carry_over.load(card)
        c = value["counters"]
        result.update(case=value["case"], state_version=value["state_version"],
                      case_spent_usd=c["case_spent_usd"], known_case_spent_usd=c["known_case_spent_usd"],
                      waste_usd=c["infrastructure_waste_usd"], allowances=(c["used"] if c["allowances_known"] else None),
                      reasons=value["admission"]["reasons"], admitted=value["admission"]["admitted"])
        limit = c["budget_limit_usd"]
        if c["case_spent_usd"] is not None and limit is not None:
            result["remaining_usd"] = round(limit - c["case_spent_usd"], 9)
        if result["admitted"]: result.update(status="MIGRATED", next_step="evaluate current gate bindings")
    except carry_over.Refused as error:
        result["reasons"] = [str(error)]
    except (OSError, UnicodeError, ValueError, RecursionError):
        result["reasons"] = ["unreadable or invalid JSON metadata"]
    return result


def table(rows):
    lines = ["| Scorecard | Case spend USD | Waste USD | Allowances | Result / reason |",
             "| --- | ---: | ---: | --- | --- |"]
    for row in rows:
        lines.append("| " + " | ".join((row["path"], str(row["case_spent_usd"]), str(row["waste_usd"]),
            "unknown" if row["allowances"] is None else json.dumps(row["allowances"], sort_keys=True),
            row["status"] + ": " + "; ".join(row["reasons"]))) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--developer-root", type=Path, default=ROOT.parent)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [inspect(path) for path in paths(args.repo, args.developer_root)]
    report = {"state_version": carry_over.STATE_VERSION, "scorecards": len(rows),
              "migrated": sum(r["status"] == "MIGRATED" for r in rows),
              "refused": sum(r["status"] == "REFUSED" for r in rows), "rows": rows,
              "metadata_only": True, "source_files_modified": False}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "corpus.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (args.output / "corpus.md").write_text(table(rows))
    print(table(rows), end="")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, sort_keys=True))


if __name__ == "__main__": main()
