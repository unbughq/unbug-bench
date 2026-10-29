"""Independent judge breadth and zero-solve diagnosis. Findings never leave the seal."""
import json
import pathlib
import shutil

LABELS = ("wrong_fix", "missing_info", "judge_too_narrow")
VERSION = 1


def verdict(payload, attempts):
    rows = payload.get("tries") if isinstance(payload, dict) else None
    if (isinstance(payload, dict) and payload.get("inconclusive") is True) or not attempts or not isinstance(rows, list) or len(rows) != len(attempts):
        return None
    if any(not isinstance(a, dict) or type(a.get("try")) is not int for a in attempts):
        return None
    expected = {a["try"] for a in attempts}
    if len(expected) != len(attempts):
        return None
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("try")) is not int or
                row["try"] not in expected or row["try"] in seen or row.get("label") not in LABELS or
                any(not isinstance(row.get(k), str) or not row[k].strip() for k in ("finding", "evidence"))):
            return None
        seen.add(row["try"])
    return {label: sum(row["label"] == label for row in rows) for label in LABELS}


def independent(c, r):
    writer = r.family(c.models["builder"][0])
    solver = r.family(c.models["strong_calibrator"][0])
    reviewer = r.family(c.models["reviewers"][0][0])
    if writer == solver or reviewer in (writer, solver):
        raise ValueError("fairness roles require independent writer, solver and reviewer families")


def review_attempts(c, r, gate, folder):
    independent(c, r)
    attempts = r.jload(c.work / folder / "results.json", [])
    directory = c.work / ("review-" + gate.lower())
    if directory.exists():
        directory.rename(directory.with_name(directory.name + "-" + str(r.time.time_ns())))
    directory.mkdir()
    shutil.copytree(c.case, directory / "case")
    shutil.copytree(c.work / folder, directory / "attempts")
    # G10 can reuse an early attempt; its evidence remains in that original workspace.
    for attempt in attempts:
        workspace = pathlib.Path(attempt["workspace"]).resolve()
        workspace.relative_to(c.work.resolve())
        if workspace.parent.name != folder:
            shutil.copytree(workspace, directory / "attempts" / ("kept-try-" + str(attempt["try"])))
    evidence = directory / "transcripts"
    evidence.mkdir()
    for path in (c.work / "transcripts").glob("strong-calibrator-" + folder + "-*.jsonl"):
        shutil.copy(path, evidence / path.name)
    if any(a.get("source") == "early_probe" for a in attempts):
        for path in (c.work / "transcripts").glob("strong-calibrator-early_probe-*.jsonl"):
            shutil.copy(path, evidence / path.name)
    output = directory / "verdict.json"
    text = (
        "Review whether these independent fixes failed because they are wrong, the contestant lacked information, "
        "or the judge rejects a valid alternative. Read case/promise.md, case/contestant.md, the fact sheet, "
        "the judge, attempted fixes, owner questions/answers and transcripts. Reference code is not the definition "
        "of correctness: judge observable behavior against the promise. Never edit a case or fix. "
        "Classify EVERY recorded try as wrong_fix, missing_info, or judge_too_narrow. "
        "For missing_info identify a necessary fact unavailable in the supplied materials AND owner channel. "
        "For judge_too_narrow identify the valid behavior rejected and the offending judge condition. "
        "For wrong_fix explain the concrete error against the promise, not merely that the judge rejected it. "
        "A missing/capped attempt or infrastructure failure alone does not prove wrong_fix; if evidence is "
        'insufficient write {"inconclusive":true,"reason":"specific missing evidence"} instead of guessing. '
        "Findings and evidence citations required. "
        "Write {\"tries\":[{\"try\":1,\"label\":\"wrong_fix\",\"finding\":\"...\",\"evidence\":\"...\"}]} to "
        + str(output) + ".")
    code = r.model_call(c, c.models["reviewers"][0], text, directory, "reviewer-" + gate.lower())
    payload = r.jload(output, {})
    counts = None if code else verdict(payload, attempts)
    details = c.work / "gate-details"
    details.mkdir(exist_ok=True)
    (details / (gate + ".json")).write_text(json.dumps({"verdict": payload, "valid": counts is not None}))
    if counts is None:
        raise ValueError("fairness review unavailable, invalid or inconclusive")
    return counts


def breadth(c, r):
    independent(c, r)
    r.make_pilots(c, [("pilot", 0)], False)
    result = r.calibrate(c, "strong_calibrator", tries=1, name="judge_breadth", exposure="statement",
                         runs=c.args.runs, collect_passes=False)
    if result["solved"] == 1:
        info = {"version": VERSION, "accepted": True, "verdict_valid": True}
        details = c.work / "gate-details"
        details.mkdir(exist_ok=True)
        (details / "G16.json").write_text(json.dumps(info))
        return True, info
    counts = review_attempts(c, r, "G16", "judge_breadth")
    # Missing information is a defect too; an inconclusive review never certifies breadth.
    ok = counts is not None and counts["wrong_fix"] == sum(counts.values()) == 1
    return ok, {"version": VERSION, "accepted": False, "verdict_valid": counts is not None,
                "labels": counts or {}, "review_inconclusive": counts is None}


def diagnose(c, r):
    strong = c.card.get("calibrators", {}).get("strong", {})
    c.card.pop("difficulty", None)
    if (type(strong.get("solved")) is not int or type(strong.get("tries")) is not int or
            strong["tries"] < 1 or not 0 <= strong["solved"] <= strong["tries"]):
        raise ValueError("missing valid strong calibration results")
    if strong["solved"] > 0:
        c.card["difficulty"] = "normal"
        return True, {"version": VERSION, "needed": False}
    counts = review_attempts(c, r, "G17", "strong_calibrator")
    ok = counts is not None and counts["wrong_fix"] == sum(counts.values()) == strong["tries"]
    if ok:
        c.card["difficulty"] = "hard"
    return ok, {"version": VERSION, "needed": True, "verdict_valid": counts is not None,
                "labels": counts or {}, "review_inconclusive": counts is None}
