"""Audit copies of sealed cases; never overwrite the original namespace."""
import copy
import hashlib
import json
import pathlib
import shutil


def case_digest(case):
    from calibration import tree_digest
    return hashlib.sha256(json.dumps(tree_digest(case), sort_keys=True).encode()).hexdigest()


def verify_source(card, case_id):
    gates = card.get("gates", {})
    if (card.get("case") != case_id or card.get("failed_gate") or
            card.get("status") == "stopped" or
            any(gates.get(f"G{i}") != "pass" for i in range(1, 16)) or
            not isinstance(card.get("sha256"), str) or len(card["sha256"]) != 64):
        raise ValueError("audit requires a verified sealed case")
    return card


def delivery_contract():
    """Public implementation digest, never an attestation by itself."""
    root = pathlib.Path(__file__).parent
    from gate_state import source_inputs
    names = ("gate_state.py", "calibration.py", "sealed_audit.py", "prompts/pilot.md")
    return {"run.py": hashlib.sha256(json.dumps(source_inputs("calibrate", "make_pilots", "calibration_identity"),
                sort_keys=True).encode()).hexdigest(),
            **{name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}}


def retain_delivery(c, r):
    """Seal portable receipts with their source and exact artifacts in the age archive."""
    from calibration import completed_attempts, attempt_summary
    from registry import atomic_json
    if any(c.card.get("gates", {}).get(g) != "pass" for g in ("G10", "G16")):
        c.card.pop("delivery_provenance", None)
        return
    attempts = {}
    for folder, role, exposure in (("judge_breadth", "strong_calibrator", "statement"),
            ("strong_calibrator", "strong_calibrator", "exam"),
            ("easy_calibrator", "easy_calibrator", "blind")):
        path = c.work / folder / "results.json"
        rows = json.loads(path.read_text())
        child = copy.copy(c)
        child.factory_slot = rows[0]["identity"]["slot"]
        runs = c.args.runs if folder == "judge_breadth" else c.args.pilot_runs
        identity = r.calibration_identity(child, role, exposure, runs=runs)
        verified = completed_attempts(path, identity, c.work)
        count = 1 if folder == "judge_breadth" else c.args.pilot_tries
        if len(verified) != count: raise ValueError("missing completed delivery receipts")
        # Absolute original paths stay encrypted. Admission relocates only beneath this root.
        attempts[folder] = {"identity": identity, "rows": verified, "summary": attempt_summary(verified)}
    from gate_state import judge_dependencies
    payload = {"contract": delivery_contract(), "case": c.case_id, "source": c.card.get("audit_source"),
               "case_digest": case_digest(c.case), "work": str(c.work), "attempts": attempts,
               "roles": c.card.get("roles"), "bench": judge_dependencies(c, r.BENCH, calibration=True)}
    path = c.work / "delivery-provenance.json"
    atomic_json(path, payload)
    c.card["delivery_provenance"] = {"contract": payload["contract"],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def verify_exam_metadata(card, case_id):
    """Pre-decryption rejection only. This does not admit an exam."""
    verify_source(card, case_id)
    if (card.get("seal_audit") or {}).get("cheat") is not False and "seal_audit" in card:
        # run.engine_seal_audit: a cheat replayed after the gates passed keeps the case out until fixed.
        raise ValueError("seal audit replayed a working cheat; the case stays out of the exam until fixed")
    if card.get("dry_run") or any(card["gates"].get(g) != "pass" for g in ("G16", "G17")):
        raise ValueError("exam requires the same completed fairness checks for every case")
    from exam_responder import contract
    reviewer = card.get("roles", {}).get("reviewer")
    if not reviewer or card.get("owner_contract") != contract(pathlib.Path(__file__).resolve().parents[1], reviewer):
        raise ValueError("case needs qualification with the current reviewer owner")
    proof = card.get("delivery_provenance", {})
    if proof.get("contract") != delivery_contract() or not isinstance(proof.get("sha256"), str):
        raise ValueError("exam requires current authenticated delivery receipts")
    return card


def verify_exam(card, case_id, *, restored_work=None, archive=None):
    """Admit only after the caller decrypts the hash-verified age archive.

    Public labels/hashes alone are insufficient. The archive is the existing trust
    anchor; receipts and artifact bytes are read only from its restored work tree.
    No original worker paths or new signing credentials are needed.
    """
    verify_exam_metadata(card, case_id)
    if restored_work is None or archive is None:
        raise ValueError("exam requires delivery evidence from the authenticated restored archive")
    from calibration import tree_digest, attempt_summary, guard_submitted
    work = pathlib.Path(restored_work)
    if hashlib.sha256(pathlib.Path(archive).read_bytes()).hexdigest() != card["sha256"]:
        raise ValueError("archive differs from authenticated scorecard")
    path = work / "delivery-provenance.json"
    if hashlib.sha256(path.read_bytes()).hexdigest() != card["delivery_provenance"]["sha256"]:
        raise ValueError("delivery provenance differs from authenticated scorecard")
    proof = json.loads(path.read_text())
    if (proof["case"] != case_id or proof["contract"] != delivery_contract() or
            proof["roles"] != card.get("roles") or proof["source"] != card.get("audit_source") or
            proof["case_digest"] != case_digest(work / "case")):
        raise ValueError("delivery provenance source mismatch")
    def relocate(value):
        relative = pathlib.Path(value).relative_to(proof["work"])
        if ".." in relative.parts: raise ValueError("invalid receipt path")
        target = work / relative
        target.resolve().relative_to(work.resolve())
        for candidate in (target, *target.parents):
            if candidate == work: break
            if candidate.is_symlink(): raise ValueError("symlink in restored receipt path")
        return target
    for folder, role, exposure in (("judge_breadth", "strong_calibrator", "statement"),
            ("strong_calibrator", "strong_calibrator", "exam"),
            ("easy_calibrator", "easy_calibrator", "blind")):
        entry = proof["attempts"][folder]
        rows, identity = entry["rows"], entry["identity"]
        config = card["recovery_config"]
        if (not rows or identity["bench"] != proof["bench"] or
                len(rows) != (1 if folder == "judge_breadth" else config["pilot_tries"]) or
                entry["summary"] != attempt_summary(rows)):
            raise ValueError("delivery receipt summary mismatch")
        # Reconstruct the same effective identity; worker absolute owner paths are
        # portable only by filename plus digest, never by trusting the restored path.
        import run
        import types
        context = types.SimpleNamespace(case=work / "case", seed=card["seed"],
            args=types.SimpleNamespace(**config), card=card, factory_slot=identity["slot"],
            models={role: [card["roles"][role]["model"]],
                    "reviewers": [[card["roles"]["reviewer"]["model"]]]})
        expected = run.calibration_identity(context, role, exposure,
            runs=config["runs" if folder == "judge_breadth" else "pilot_runs"])
        def portable(value):
            value = copy.deepcopy(value)
            if "owner" in value:
                value["owner"]["files"] = {pathlib.Path(p).name: digest
                    for p, digest in value["owner"]["files"].items()}
            return value
        if (type(identity["slot"]) is not int or identity["slot"] < 0 or
                portable(identity) != portable(expected)):
            raise ValueError("stale delivery implementation, bench or case")
        original = json.loads((work / folder / "results.json").read_text())
        if original != rows: raise ValueError("receipt bundle mismatch")
        seen = set()
        for number, row in enumerate(rows, 1):
            ws = relocate(row["workspace"])
            if (row["identity"] != identity or row["try"] != number or ws in seen or
                    tree_digest(ws) != row["artifacts"] or
                    type(row["guard_submitted"]) is not bool or
                    guard_submitted(ws / "guard") != row["guard_submitted"] or
                    (row["guard_submitted"] and relocate(row["guard"]) != ws / "guard") or
                    (row["solved"] and not row["guard_submitted"])):
                raise ValueError("invalid completed delivery artifacts")
            seen.add(ws)
        if folder != "judge_breadth":
            summary = card["calibrators"]["strong" if role == "strong_calibrator" else "easy"]
            if any(summary.get(k) != entry["summary"][k] for k in ("tries", "solved", "diagnostics")):
                raise ValueError("calibrator summary differs from receipts")
    return card


def prepare(c, r):
    """Called before opening logs or performing mutations in the source workspace."""
    original = c.work
    source = verify_source(r.jload(r.SEALED / (c.case_id + ".source-scorecard.json"), {}), c.case_id)
    # The launcher authenticates the ciphertext; the restored card binds its case identity.
    restored = r.jload(original / "scorecard.json", {})
    if restored.get("case") != c.case_id or restored.get("roles") != source.get("roles"):
        raise ValueError("restored case differs from authenticated scorecard")
    kind = "rehearsal" if c.args.rehearse_only else "fairness"
    c.audit_source = {"case": c.case_id, "sha256": source["sha256"], "kind": kind}
    c.audit_previous = copy.deepcopy(source)
    c.case_id += "-" + kind
    c.work = original.with_name(c.case_id)
    if c.work.exists():
        raise ValueError("audit destination already exists")
    c.work.mkdir()
    (c.work / "logs").mkdir()
    shutil.copytree(c.case, c.work / "case", symlinks=True)
    c.case = c.work / "case"
    c.audit_source["case_sha256"] = case_digest(c.case)
    # Preserve cumulative costs; audit allowances must be explicitly above this baseline.
    budget = source.get("continuation_budget")
    if not isinstance(budget, dict) or budget.get("active"):
        raise ValueError("missing or active source ledger")
    (c.work / "continuation-budget.json").write_text(json.dumps(budget))
    (c.work / "scorecard.json").write_text(json.dumps(source))
    (c.work / "audit-baseline.json").write_text(json.dumps(source))
    c.args.seed = c.seed = source["seed"]
    c.args.resume = c.case_id
    c.args.skip_build = True
    c.args.no_early_probe = True


def recover(c, r):
    """Keep inherited checks after interruption only while the original case is intact."""
    source = getattr(c, "audit_source", None)
    if not source or hasattr(c, "audit_previous") or source.get("kind") != "fairness":
        return
    baseline = r.jload(c.work / "audit-baseline.json", {})
    if (baseline.get("case") != source.get("case") or
            baseline.get("sha256") != source.get("sha256")):
        raise ValueError("missing authenticated audit baseline")
    if case_digest(c.case) == source.get("case_sha256"):
        c.audit_previous = verify_source(baseline, source["case"])
        c.args.audit_fairness = c.args.skip_build = c.args.no_early_probe = True


def run(c, r):
    c.card["audit_source"] = c.audit_source
    if c.args.rehearse_only:
        c.audit_gates = ["G3", "G4", "G5"]
        r.run_gates(c)
        return
    source = c.audit_previous
    if source.get("roles") != c.card.get("roles"):
        raise ValueError("audit models or efforts differ from sealed source")
    c.card["gates"] = {k: v for k, v in source["gates"].items() if k not in ("G10", "G11", "G12", "G16", "G17")}
    c.card["kept_gate_source"] = c.audit_source
    c.card["calibrators"] = {"easy": copy.deepcopy(source["calibrators"]["easy"])}
    # A fresh worker must prepare its runtime, even though the old build verdict is retained.
    ok, info = r.g3(c)
    c.card["audit_runtime_preparation"] = {"ok": ok}
    if not ok:
        c.card["failed_gate"] = "G3"
        c.card["gates"]["G3"] = "fail"
        return
    c.audit_gates = ["G16", "G10", "G17", "G11"]
    c.audit_keep_easy = True
    r.validate_and_repair(c)
