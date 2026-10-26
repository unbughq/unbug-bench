"""Worker-only accounting import after authenticated checkpoint extraction.

The trusted transport supplies the digest of the archive it actually restored.
An archived scorecard need not equal the final public card. Accounting, however,
must match a retained ledger exactly: a public correction is not its own proof.
This guard authenticates accounting only; it grants no attempt/gate allowances.
"""
import argparse
import copy
import fcntl
import json
from pathlib import Path
import re
import sys

from carry_over import Refused, digest, require, usage_facts
from budget import case_spending
from registry import atomic_json, identifier


def read_object(path):
    require(not path.is_symlink() and path.is_file(), "missing retained accounting metadata")
    try:
        value = json.loads(path.read_text())
        require(isinstance(value, dict), "invalid accounting metadata")
        # Includes nested NaN/Infinity and invalid usage shapes, without leaking data.
        digest(value)
        return value
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise Refused("invalid accounting metadata") from None


def authenticate(work, case, generation, public_card, *, founder_ruling=None):
    """Read only restored metadata; never infer a usage delta from totals or time.

    The separate ledger is the seal's accounting snapshot. Older archives without
    it can use their embedded scorecard ledger. If both exist they must agree.
    Newer public labels (including G12, archive paths and terminal status) do not
    invalidate the ledger, and do not authenticate any other public verdict.
    """
    require(isinstance(case, str) and re.fullmatch(r"case-[A-Za-z0-9-]+", case), "invalid restore case")
    require(isinstance(generation, str) and re.fullmatch(r"[0-9a-f]{64}", generation),
            "invalid restored generation")
    require(isinstance(public_card, dict) and public_card.get("case") == case and
            public_card.get("sha256") == generation, "public card does not name restored generation")
    work = Path(work)
    require(work.name == case and not work.is_symlink(), "invalid restored work directory")
    archived_card = read_object(work / "scorecard.json")
    require(archived_card.get("case") == case, "archived case identity mismatch")
    embedded = archived_card.get("continuation_budget")
    path = work / "continuation-budget.json"
    if path.exists() or path.is_symlink():
        retained = read_object(path)
        require(embedded is None or digest(retained) == digest(embedded), "retained accounting snapshots disagree")
    else:
        retained = embedded
    usage_facts(retained)
    imported = public_card.get("continuation_budget")
    usage_facts(imported)
    require(digest(imported) == digest(retained) or founder_ruling is not None,
            "public ledger differs from retained accounting; authenticated delta/correction receipt required")
    # Keep the exact provenance and historical totals. Normalization is used only
    # to detect sticky unknown usage; never overwrite the original with projections.
    normalized = usage_facts(imported)["ledger"]
    summary = case_spending(normalized)
    require(summary["spent_usd"] is not None, "retained usage is unknown; worker reconciliation required")
    receipt = {
        "version": 1, "case": case, "generation": generation,
        "public_card_sha256": digest(public_card), "ledger_sha256": digest(imported),
        "accounting_authenticated": True, "case_spent_usd": summary["spent_usd"],
        "infrastructure_waste_usd": summary["infrastructure_waste_usd"],
        "attempt_allowances_authenticated": False,
    }
    if founder_ruling is not None:
        receipt.update(founder_ruling=founder_ruling, retained_ledger_sha256=digest(retained),
                       accounting_authority='explicit founder ruling for exact generation and public ledger')
    return copy.deepcopy(imported), receipt


def install(work, sealed, case, generation, public_card, *, ruling_path=None, ruling_sha256=None):
    """Publish only after all checks; never replace a newer worker-owned ledger.

    A retry after a kill before/after the atomic ledger rename is idempotent. A
    different existing ledger is never overwritten, even if the import is valid.
    This is an import boundary, not model-return/operation-commit recovery.
    """
    require((ruling_path is None) == (ruling_sha256 is None), 'founder ruling requires pinned hash and file')
    accepted = None
    if ruling_path is not None:
        import founder_ruling
        accepted = founder_ruling.authenticate(ruling_path, ruling_sha256, case, generation, public_card)
    ledger, receipt = authenticate(work, case, generation, public_card, founder_ruling=accepted)
    sealed = Path(sealed)
    require(not sealed.is_symlink(), "invalid sealed directory")
    sealed.mkdir(parents=True, exist_ok=True)
    target = sealed / f"{case}.continuation-budget.json"
    # Same lock as the usage writer: a concurrent newer update cannot disappear
    # between the comparison and publication.
    with Path(str(target) + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.exists() or target.is_symlink():
            require(digest(read_object(target)) == digest(ledger), "worker ledger already differs; refusing replacement")
        if accepted is not None:
            receipt['founder_ruling'] = founder_ruling.apply(work, accepted)
            receipt['attempt_allowances_authenticated'] = True
        if not target.exists():
            atomic_json(target, ledger)
        atomic_json(sealed / f"{case}.restore-accounting.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--case", required=True, type=identifier)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--founder-ruling", type=Path)
    parser.add_argument("--founder-ruling-sha256")
    args = parser.parse_args()
    try:
        receipt = install(args.home / "work" / args.case, args.home / "sealed", args.case,
                          args.generation, json.load(sys.stdin), ruling_path=args.founder_ruling,
                          ruling_sha256=args.founder_ruling_sha256)
    except (Refused, OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as error:
        # Never print parser values, filesystem paths or unexpected exception text.
        reason = str(error) if isinstance(error, Refused) else "invalid restore accounting input"
        print(json.dumps({"accounting_authenticated": False, "reason": reason}))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
