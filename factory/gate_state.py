"""Conservative reuse of passed checks during bounded repairs.

G7 is reusable on resume: it is the same seeded run (c.seed + 7919), so identical inputs mean the
same samples. G10 validates its own attempt receipts; G11 is
never cached here. Stored evidence must still exist, including after sealing moves
bench results into the case workspace.
"""
import ast
import hashlib
import os
import json
import pathlib
import re
from registry import atomic_json

REUSABLE = {"G4", "G5", "G6", "G7", "G8", "G9", "G13", "G14", "G15", "G16"}


# Receipt directories each gate's checkpoints used (fresh or reused), per work dir and label:
# a gate's evidence must cover all of them, including ones a retry did not rerun.
RECEIPTS = {}


def note_receipt(c, label, directory):
    RECEIPTS.setdefault(str(c.work), {}).setdefault(label, set()).add(directory)


def forget_receipts(c, gate):
    mine = RECEIPTS.get(str(c.work), {})
    # A copy first: a concurrent lane's note_receipt may add a label meanwhile.
    for label in [k for k in list(mine) if k.startswith(gate.lower() + "-")]: mine.pop(label, None)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()



VERSION = 3
RUNNER = pathlib.Path(__file__).with_name("run.py")
DEPS_IMAGE_FILE = pathlib.Path("/opt/medusa-deps-image")


def environment(*keys):
    """The bench execution environment; the deps image as bin/bench.py resolves it: the variable's value
    when it is set (even empty), else DEPS_IMAGE_FILE."""
    result = {key: os.environ.get(key) for key in keys}
    if "MEDUSA_DEPS_IMAGE" in result and "MEDUSA_DEPS_IMAGE" not in os.environ and DEPS_IMAGE_FILE.is_file():
        result["MEDUSA_DEPS_IMAGE"] = DEPS_IMAGE_FILE.read_text().strip()
    return result
MEASURE = ("factory/case_permissions.py", "bin/bench.py", "bin/bench_judging.py", "bin/checkpoint", "bin/checkpoint_evidence.py", "bin/claims.py", "bin/refusal.py", "bin/factory_pool.py", "bin/diagnostic_budget.py",
           "cases/medusa-oversell/checker/**", "cases/medusa-oversell/traffic/**", "projects/**", "guards/**")
STRATEGY = ("bin/strategy", "bin/strategy_resume.py", "bin/silent_window.py", "bin/exposure.py", "bin/live_shop.py",
            "bin/live_traffic.py", "bin/shoppers", "factory/calibration.py")
MODEL = ("factory/calibration.py",)
DEPENDENCIES = {"G4": MEASURE + ("bin/run_validity.py",), "G5": MEASURE + ("bin/run_validity.py", "factory/durable/helpers.py", "factory/durable/helper_link.py"), "G6": MEASURE + ("bin/run_validity.py",) + ("bin/verify-negative", "factory/durable/helpers.py", "factory/durable/helper_link.py"),
                "G7": MEASURE + ("bin/run_validity.py", "factory/durable/helpers.py", "factory/durable/helper_link.py"),
                "G8": MEASURE + STRATEGY + MODEL + ("*.md", "harbor/**"),
                "G9": MEASURE + STRATEGY + MODEL + ("*.md", "harbor/**"),
                "G13": MEASURE + STRATEGY + ("bin/run_validity.py",),
                "G14": MEASURE + STRATEGY + ("bin/run_validity.py",),
                "G15": MEASURE + STRATEGY + ("bin/run_validity.py",),
                "G16": MEASURE + MODEL + ("bin/run_validity.py", "factory/independent_review.py", "factory/fairness.py", "factory/exam_responder.py",
                    "harbor/responder/**", "bin/run-exam", "bin/score-claims", "bin/land")}
# fairness.py invokes these through its runner argument, rather than direct names.
EXTRA_ROOTS = {gate: ("make_pilots", "calibrate", "family", "jload", "calibration_identity")
               for gate in ("G10", "G16", "G17")}
# Inventories for stages without a generic pass cache. Their execution/freshness
# contracts remain in the runner; extension comparison consumes versions only.
STAGE_DEPENDENCIES = {**DEPENDENCIES,
    "G1": ("factory/calibration.py", "bin/claims.py", "bin/exposure.py", "projects/**"),
    "G2": ("factory/admission.py", "factory/freshness_retrieval.py", "factory/independent_review.py"),
    "G3": MEASURE + ("bin/setup", "compose*.y*ml", "Dockerfile*"),
    "G10": MEASURE + STRATEGY + MODEL + ("bin/run_validity.py", "factory/exam_responder.py", "factory/durable/helpers.py", "factory/durable/helper_link.py", "harbor/**"),
    "G11": MEASURE + ("bin/run_validity.py", "bin/fake-pass-check", "factory/independent_review.py"),
    "G17": DEPENDENCIES["G16"]}
MODEL_STAGES = {"G2", "G8", "G9", "G10", "G11", "G16", "G17"}
# Gates whose verdict the second reviewer can decide: the G8/G9 panel (run.review), and G11, G16 and G17,
# whose independent review (independent_review.review) asks it when the first reviewer is inconclusive.
SECOND_REVIEWER_GATES = {"G8", "G9", "G11", "G16", "G17"}
# Execution/checkpoint side effects cannot determine a scientific verdict.
# External model/checker code remains conservatively pinned as whole modules.
SIDE_EFFECTS = {"checked_gate", "_gate_pipeline", "_gate_completed", "seal", "wipe", "_run_artifacts",
                "log", "public_progress", "update_case_budget", "case_budget_boundary", "bench_manifest",
                "sh", "opencode", "_opencode", "model_call", "resume_provider_wait", "shred_tree",
                # Retry/allowance plumbing around bench calls: never selects samples or reads a verdict.
                "_checkpoint_call", "AllowanceSpent", "early_cheat_check",
                # Gate-checkpoint receipts only skip finished work; the verdict still comes from the saved runs.
                # _saved_checkpoint is hashed: it decides which saved samples stand in for a fresh run.
                "_save_checkpoint", "_checkpoint_receipt_dir", "under_engine"}


def source_inputs(*roots, path=None):
    """Hash the gate's source and its transitive same-module names, including constants.

    Follow references rather than line ranges: inserting an unrelated function does
    not change the binding. External code/data is explicitly listed above.
    """
    source = (path or RUNNER).read_text()
    nodes = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.asname or a.name.split(".")[0] for a in node.names]
            else:
                names = [n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)]
            for name in names: nodes[name] = node
    pending = list(roots)
    found = {}
    while pending:
        name = pending.pop()
        if name in found or name not in nodes or name in SIDE_EFFECTS: continue
        node = nodes[name]
        text = ast.get_source_segment(source, node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            text += "".join(ast.dump(d) for d in node.decorator_list)
        found[name] = hashlib.sha256(text.encode()).hexdigest()
        pending.extend(n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load))
    if any(root not in found for root in roots): raise ValueError("missing judge source")
    return found


def runner_inputs(gate):
    return source_inputs(gate.lower(), *EXTRA_ROOTS.get(gate, ()))


def source_paths(root, pattern):
    # Prune installed/generated trees before traversal. Filtering after rglob
    # walked every node_modules entry on every review binding (minutes per test).
    if pattern.endswith("/**"):
        for anchor in sorted(root.glob(pattern[:-3])):
            for directory, directories, names in os.walk(anchor):
                directories[:] = sorted(d for d in directories if d not in {"node_modules", ".medusa", "__pycache__", ".git"})
                yield from (pathlib.Path(directory) / name for name in sorted(names))
    else:
        yield from sorted(root.glob(pattern))


def release_pins():
    """Source files whose release edit is proven not to change any verdict: {name: {"from", "to"}}.
    A stored identity or gate cache made under the "from" hash stays valid under the "to" hash; any
    other edit of the file (a stale pin included) changes the hash and invalidates as before."""
    try: return json.loads(pathlib.Path(__file__).with_name("invalid-runs-compat.json").read_text()).get("release_pins", {})
    except (OSError, ValueError): return {}


def pinned(name, value):
    pin = release_pins().get(name)
    return pin["from"] if isinstance(pin, dict) and value == pin.get("to") else value


def dependency_files(c, patterns, bench, *, include_pool=False):
    dependencies = {}
    for pattern in patterns:
        # Bench imports its own copy; the runner/launcher use the sibling factory copy.
        if pattern == "factory/case_permissions.py":
            path = bench / pattern
            dependencies["bench/" + pattern] = digest(path) if path.is_file() else None
        if pattern == "bin/factory_pool.py" and not include_pool and getattr(c.args, "bench_workers", 1) == 1:
            continue
        factory = pattern.startswith("factory/")
        root, relative = (RUNNER.parent, pattern[8:]) if factory else (bench, pattern)
        found = False
        for p in source_paths(root, relative):
            rel = p.relative_to(root).as_posix()
            if not p.is_file() or any(part in {"node_modules", ".medusa", "__pycache__", ".git"} for part in p.relative_to(root).parts): continue
            if rel == "projects/medusa/seed-ids.json": continue
            key = "factory/" + rel if factory else rel
            dependencies[key] = pinned(key, digest(p))
            found = True
        if not found: dependencies[pattern] = None  # additions/removals are inputs too
    return dependencies


def judge_dependencies(c, bench, *, calibration=False):
    """Exact portable stress/calibration dependency inventory; no whole manifest."""
    patterns = MEASURE + STRATEGY + MODEL + ("bin/run_validity.py", "*.md", "harbor/**", "factory/case_contract.py", "factory/attack_findings.py")
    roots = ("calibrate", "make_pilots", "calibration_identity") if calibration else (
        "attack_report", "stress_request", "g1")
    result = {"version": VERSION, "runner": source_inputs(*roots),
              "files": dependency_files(c, patterns, bench, include_pool=True),
              "model_science": model_science()}
    if not calibration:
        result.update(settings={key: getattr(c.args, key, default) for key, default in (
                ("runs", 10), ("scenario_runs", 3), ("bench_workers", 1), ("source", None),
                ("agent_timeout", 14400), ("max_role_calls", 400), ("max_total_calls", 1000),
                ("max_cost", 5), ("no_progress_minutes", 45), ("max_zero_tokens", 3),
                ("concurrent_roles", True))}, seed=getattr(c, "seed", None))
    return result


def inputs(c, gate, bench):
    # A lane context (gate_pipeline.early_parallel) runs on its own reserved bench instance with one
    # worker and is fingerprinted as its owner, so GATES reuses what it earned. Instance and worker
    # count never decide a verdict: scientific_version drops both, run numbers keep their seeds, and
    # G5's key checks already run on whichever pool instance is free under one identity.
    c = getattr(c, "reuse_as", c)
    files = []
    for p in sorted(c.case.rglob("*")):
        if not p.is_file(): continue
        rel = p.relative_to(c.case).as_posix()
        if gate not in {"G8", "G9"} and rel in {"BUILD-NOTES.md", "freshness.jsonl"}: continue
        if gate == "G4" and not (rel.startswith("base/") or rel in {"case.json", "promise.md"}): continue
        files.append((rel, digest(p)))
    dependencies = dependency_files(c, (*STAGE_DEPENDENCIES[gate], "factory/case_contract.py"), bench)
    settings = {"runs": 10, "scenario_runs": 3, "bench_workers": 1, "dry_run": False, "rehearse_only": False}
    if gate == "G1": settings["source"] = None
    if gate in MODEL_STAGES:
        settings.update(pilot_runs=5, pilot_tries=3, calibrator_minutes=30, max_role_calls=400,
            max_total_calls=1000, max_cost=5, no_progress_minutes=45, max_zero_tokens=3,
            agent_timeout=14400, concurrent_roles=True, source=None)
    identity = {
        "version": VERSION, "gate": gate, "case": files, "bench": dependencies,
        "runner": runner_inputs(gate),
        "seed": c.seed, "slot": getattr(c, "factory_slot", 0),
        "args": {key: getattr(c.args, key, default) for key, default in settings.items()},
        "environment": environment("UNBUG_JUDGE", "UNBUG_FACTORY_SLOT", "MEDUSA_DEPS_IMAGE"),
    }
    if "agent_timeout" in settings and hasattr(getattr(c, "engine", None), "deadline_s"):
        # Under the engine args.agent_timeout is the attempt's remaining time (run.context_for_step), new
        # on every attempt; the step's own deadline is the setting. A CLI run keeps its real value.
        identity["args"]["agent_timeout"] = c.engine.deadline_s
    if gate in MODEL_STAGES:
        import run
        prompt_roles = ("pilot", "reviewer") if gate in {"G10", "G16", "G17"} else ("reviewer",)
        identity["prompts"] = {role: hashlib.sha256(run.prompt(role, "").encode()).hexdigest() for role in prompt_roles}
        if gate in {"G8", "G9"}:  # the key cross-check text is part of the panel's instruction
            identity["prompts"]["reviewer-keys"] = hashlib.sha256((run.PROMPTS / "reviewer-keys.md").read_bytes()).hexdigest()
        names = (("builder", "strong_calibrator", "easy_calibrator", "reviewers") if gate == "G10" else
                 ("builder", "strong_calibrator", "reviewers") if gate in {"G16", "G17", "G11"} else
                 ("builder", "attacker", "reviewers") if gate == "G2" else ("reviewers",))
        identity["models"] = {key: getattr(c, "models", {}).get(key) for key in names}
        if gate not in SECOND_REVIEWER_GATES and identity["models"].get("reviewers"):
            # Only these gates let the second reviewer decide (founder 2026-11-12); the others keep their
            # one-reviewer identity, so adopting it does not rerun them.
            identity["models"]["reviewers"] = identity["models"]["reviewers"][:1]
        role_names = {"builder": ("writer",), "attacker": ("stress_tester",),
                      "reviewers": ("reviewer", "reviewer2")}
        identity["roles"] = {key: c.card.get("roles", {}).get(key)
                             for name in names for key in role_names.get(name, (name,))}
        if gate not in SECOND_REVIEWER_GATES and "reviewer2" in identity["roles"]:
            identity["roles"]["reviewer2"] = None
        identity["model_science"] = model_science()
        if gate == "G2" and (n := stress_swaps(c.card)):
            identity["stress_swaps"] = n   # A->B->A names the same models, yet the old tester's G2 never counts
    return identity


def stress_swaps(card):
    return sum(s.get("role") == "stress_tester" for s in (card or {}).get("role_swaps") or ())


def model_science():
    """Family independence/default effort are science; router execution is not."""
    result = {}
    for module, name in (("model_router.py", "family"), ("model_runtime.py", "model_effort")):
        path = RUNNER.with_name(module)
        result[module] = source_inputs(name, path=path) if path.is_file() else None
    return result


def scientific_version(c, gate, bench):
    """Content-derived stage version, separate from case/execution binding.

    Mixed scientific executors stay conservatively bound. No source release,
    receipt-writer hash or pure transport implementation is a gate version.
    """
    if gate == "stress":
        import run
        identity = {"gate": gate, "bench": judge_dependencies(c, bench),
                    "prompt": hashlib.sha256(run.prompt("attacker", "").encode()).hexdigest(),
                    "model": c.models.get("attacker"), "role": c.card.get("roles", {}).get("stress_tester"),
                    "environment": environment("UNBUG_JUDGE", "MEDUSA_DEPS_IMAGE")}
        identity["bench"].pop("seed", None)
        settings = identity["bench"].get("settings", {})
    else:
        identity = inputs(c, gate, bench)
        for key in ("case", "seed", "slot", "version"): identity.pop(key, None)
        identity["environment"].pop("UNBUG_FACTORY_SLOT", None)
        settings = identity["args"]
    for key in ("bench_workers", "concurrent_roles"): settings.pop(key, None)
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def calibration_binding(c, bench=None):
    # G16 also feeds portable delivery receipts; sealing still checks this identity.
    import run
    return run.calibration_identity(c, "strong_calibrator", "statement", runs=c.args.runs, bench=bench)


def fingerprint(c, gate, bench):
    return hashlib.sha256(json.dumps(inputs(c, gate, bench), sort_keys=True).encode()).hexdigest()


def inventory(c, bench):
    """Files a gate may cite as evidence. Bench state (slot_state.is_state: progress, overrides,
    receipts, seed IDs, temporaries) is never evidence; the evidence gather (run_artifacts) uses the same rule.
    While two lanes run, `evidence_scope(kind, relative)` keeps each gate to its own files."""
    import slot_state
    paths = {}
    scope = getattr(c, "evidence_scope", None)
    # A mid-gate snapshot moves bench results into c.work/bench-results; load looks in both.
    roots = [("bench", bench / "results"), ("bench", c.work / "bench-results"), ("work", c.work / "gate-details"),
             ("work", c.work / "judge_breadth")]
    roots += [("work", p) for p in c.work.glob("review-*") if p.is_dir()]
    for kind, root in roots:
        for p in root.rglob("*") if root.exists() else []:
            if p.is_file() and not slot_state.is_state(p.relative_to(root).as_posix()):
                base = c.work if kind == "work" else (c.work / "bench-results" if root == c.work / "bench-results" else bench / "results")
                relative = p.relative_to(base).as_posix()
                if scope is None or scope(kind, relative): paths[(kind, relative)] = p
    return paths


def digests(c, bench):
    """inventory's files by digest. The G8/G9 lane runs beside G5/G16 and renames review-N while they
    list it (cae763, 14 November: G16 crashed FileNotFoundError on review-1/verdict.json): a file gone
    before it is read is not there."""
    found = {}
    for key, path in inventory(c, bench).items():
        try: found[key] = digest(path)
        except FileNotFoundError: pass
    return found


def owned(gate, kind, rel):
    """Another gate's work files written beside this one by a concurrent lane are not its evidence: the
    reviewers' copies (the next review() renames review-N) and another gate's details (gate-details/G8.json)."""
    if kind != "work": return True
    parts = rel.split("/")
    if parts[0].startswith("review-"): return gate in {"G8", "G9"}
    head = parts[1].split(".")[0] if parts[0] == "gate-details" and len(parts) > 1 else ""
    return not re.fullmatch(r"G\d+", head) or head == gate


def save(c, gate, info, signature, before, bench):
    """True when the pass record was written."""
    if gate not in REUSABLE:
        return False
    evidence = [{"kind": kind, "path": rel, "sha256": sha256}
                for (kind, rel), sha256 in digests(c, bench).items()
                if before.get((kind, rel)) != sha256 and owned(gate, kind, rel)]
    seen = {e["path"] for e in evidence if e["kind"] == "work"}
    for label, directories in sorted(RECEIPTS.get(str(c.work), {}).items()):
        if not label.startswith(gate.lower() + "-"): continue
        for directory in sorted(directories):
            for p in sorted(directory.glob("*.json")):
                rel = p.relative_to(c.work).as_posix()
                if rel not in seen: seen.add(rel); evidence.append({"kind": "work", "path": rel, "sha256": digest(p)})
    if not evidence and gate in {"G8", "G9"}:
        evidence = [{"kind": "work", "path": p.relative_to(c.work).as_posix(), "sha256": digest(p)}
                    for p in c.work.glob("review-[0-9]/verdict.json") if p.is_file()]
    if not evidence:
        return False  # A summary without supporting evidence cannot authorize later reuse.
    directory = c.work / "gate-cache"
    directory.mkdir(exist_ok=True)
    record = {"fingerprint_version": VERSION, "inputs": inputs(c, gate, bench),
              "signature": signature, "info": info, "evidence": evidence,
              "scientific_version": scientific_version(c, gate, bench)}
    if gate == "G16": record["calibration_identity"] = calibration_binding(c)
    atomic_json(directory / f"{gate}.json", record)
    return True


def record_files(c, gate, bench):
    """The saved record and its evidence as snapshot members {name: path}, or {} when a file is missing
    or changed (load would refuse it). Bench evidence goes where gather_bench_results puts it."""
    try:
        path = c.work / "gate-cache" / f"{gate}.json"
        files = {f"gate-cache/{gate}.json": path}
        for e in json.loads(path.read_text())["evidence"]:
            relative = pathlib.PurePosixPath(e["path"])
            if relative.is_absolute() or ".." in relative.parts: return {}
            places = ([bench / "results" / relative, c.work / "bench-results" / relative]
                      if e["kind"] == "bench" else [c.work / relative])
            found = next((p for p in places if p.is_file() and digest(p) == e["sha256"]), None)
            if found is None: return {}
            files[("bench-results/" if e["kind"] == "bench" else "") + relative.as_posix()] = found
        return files
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def changed_fields(saved, current):
    """Names (never values, never case file names) of the identity fields that differ."""
    names = []
    for key in sorted(saved.keys() | current.keys()):
        old, new = saved.get(key), current.get(key)
        if old == new: continue
        if key != "case" and isinstance(old, dict) and isinstance(new, dict):
            names += [f"{key}.{sub}" for sub in sorted(old.keys() | new.keys()) if old.get(sub) != new.get(sub)]
        else:
            names.append(key)
    return names


def miss(c, gate, reason, saved=None, current=None):
    """Record why a gate cache entry was not reused; key names only. Always returns None."""
    if saved is not None and current is not None:
        names = changed_fields(saved, current)
        reason += ": " + ", ".join(names[:12]) + (f" (+{len(names) - 12} more)" if len(names) > 12 else "")
    try:
        import run
        run.log(c, f"gate cache miss {gate}: {reason}")
    except (OSError, ImportError, AttributeError):
        pass
    return None


def load(c, gate, bench):
    if gate not in REUSABLE:
        return None
    try:
        path = c.work / "gate-cache" / f"{gate}.json"
        if not path.is_file(): return miss(c, gate, "no saved record")
        record = json.loads(path.read_text())
        # V1 contains only an opaque hash, not the old per-input digests.
        # It cannot prove scoped equivalence after a source change.
        if not isinstance(record, dict) or record.get("fingerprint_version") != VERSION:
            return miss(c, gate, "fingerprint_version")
        current = inputs(c, gate, bench)
        expected = json.loads(json.dumps(current))
        if ("scientific_version" in record and
                record["scientific_version"] != scientific_version(c, gate, bench)):
            return miss(c, gate, "scientific_version; inputs changed", record['inputs'], expected)
        if gate == "G16" and record.get("calibration_identity") != calibration_binding(c):
            return miss(c, gate, "calibration_identity")
        from calibration import compatible_panel
        matching = record['inputs'] == expected
        if gate in ('G8', 'G9') and not matching:
            matching = compatible_panel(record['inputs'], expected)
        if not matching:
            return miss(c, gate, "inputs changed", record['inputs'], expected)
        if record["signature"] != hashlib.sha256(json.dumps(record['inputs'], sort_keys=True).encode()).hexdigest():
            return miss(c, gate, "signature")
        if not record["evidence"]:
            return miss(c, gate, "no evidence")
        for e in record["evidence"]:
            relative = pathlib.PurePosixPath(e["path"])
            if relative.is_absolute() or ".." in relative.parts:
                return miss(c, gate, "evidence path")
            paths = ([bench / "results" / relative, c.work / "bench-results" / relative]
                     if e["kind"] == "bench" else [c.work / relative])
            if not any(p.is_file() and digest(p) == e["sha256"] for p in paths):
                return miss(c, gate, "evidence file missing or changed")
        if not hasattr(c, "gate_fingerprint_versions"): c.gate_fingerprint_versions = {}
        c.gate_fingerprint_versions[gate] = VERSION
        return record["info"]
    except (OSError, ValueError, KeyError, TypeError):
        return miss(c, gate, "unreadable record")
