"""ADMIT: choose a case's candidate, admit its statement, hand over a work tree (WP11).

    from durable.steps import admit
    result, outputs = admit.run(worker, step_input, keys)

`worker_step.Worker.execute` calls `run` for `StepKind.ADMIT` and returns its two values.
`worker` is the live harness (home, sealer, runner, open_blob); `keys` holds the case and
batch scope keys. The inputs and the statement registry are batch-scoped; the case
snapshot is case-scoped. Nothing here records plaintext or a key.

Both plaintexts are JSON, version 1.

INPUTS (batch key), reusing the card and case.json schemas:
    {"version": 1, "dry_run": true, "seed": 7, "models": {...}, "recovery_config": {...}}
        The explicit dry run builds `run.build_fixture`'s practice case. It never runs a
        model, never selects a candidate and never changes the registry.
    {"version": 1, "dry_run": false, "seed": 7, "source": "port",
     "app_repo": "owner/name", "app_commit": "<40 hex>", "promise": "...",
     "promise_paths": [...], "promise_checks": [...],
     "models": {...}, "recovery_config": {...},
     "candidate": {"statement": "...", "statement_sha256": "<64 hex>"}}
        `candidate` is optional. Without it the existing selector proposes a statement.
        An initial snapshot that is a legacy checkpoint (still age ciphertext to the statement
        key) is an import: see `_import_legacy`.
        Every real candidate runs the existing semantic dedup, public freshness and
        independent idea-realism checks before it can be handed to WRITER.
        Optional `rotation_slot` overrides the existing cohort table; otherwise engine
        case ordinals cycle that table. Explicit role chains still undergo validation.

REGISTRY (batch key), exactly registry.Registry's state plus its object store:
    {"version": 1, "registry": {"revision": n, "entries": {...}},
     "objects": {"<sha256 of ciphertext>": "<base64 age ciphertext>"},
     "refs": {"<sha256 of ciphertext>": "<artifact digest>"}}
    An empty plaintext is an empty registry. Materialising it into a temporary Registry
    is what lets the adapter reuse registry.Registry.reserve/export unchanged; the
    reserved entry travels in the returned, re-sealed registry so the next ADMIT (the
    engine queue serialises them) dedups against it and a retry is idempotent. `refs`
    lets a later worker open a stored statement with the sealer: the ciphertext alone is
    not enough, AgeSealer.open also checks the artifact digest.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import tarfile
import tempfile

from durable.contract import ArtifactKind, Outcome, Ref, StepKind, StepResult, Usage

_VERSION = 1
_CASE = re.compile(r"case-[A-Za-z0-9-]{1,80}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_STATUS = {"screening", "building", "completed", "known_public", "released"}


class _Conflict(Exception):
    pass


class _Invalid(ValueError):
    """A plaintext did not match the version-1 schema above."""


def _json(plaintext, what):
    try:
        value = json.loads(plaintext)
    except (TypeError, ValueError) as error:
        raise _Invalid(what) from error
    if not isinstance(value, dict) or value.get("version") != _VERSION:
        raise _Invalid(what)
    return value


def _inputs(plaintext):
    value = _json(plaintext, "inputs")
    if type(value.get("dry_run")) is not bool or type(value.get("seed")) is not int:
        raise _Invalid("inputs")
    for name in ("models", "roles", "recovery_config"):
        if value.get(name) is not None and not isinstance(value[name], dict):
            raise _Invalid("inputs")
    if value.get("rotation_slot") is not None and (type(value["rotation_slot"]) is not int or value["rotation_slot"] < 1):
        raise _Invalid("inputs")
    if value["dry_run"]:
        return value
    for name in ("app_repo", "app_commit", "promise", "source"):
        if not isinstance(value.get(name), str):
            raise _Invalid("inputs")
    if (_REPO.fullmatch(value["app_repo"]) is None or _COMMIT.fullmatch(value["app_commit"]) is None
            or not value["promise"].strip() or value["source"] not in ("port", "hunt", "plant")):
        raise _Invalid("inputs")
    for name in ("promise_paths", "promise_checks"):
        paths = value.get(name, [])
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise _Invalid("inputs")
    candidate = value.get("candidate")
    if candidate is None:
        return value
    if (not isinstance(candidate, dict) or not isinstance(candidate.get("statement"), str)
            or not candidate["statement"].strip()
            or hashlib.sha256(candidate["statement"].encode()).hexdigest() != candidate.get("statement_sha256")):
        raise _Invalid("inputs")
    return value


def _entry(case, entry):
    if (not isinstance(entry, dict) or entry.get("version") != _VERSION or entry.get("case_id") != case
            or _CASE.fullmatch(case) is None or entry.get("status") not in _STATUS
            or type(entry.get("complete")) is not bool or not isinstance(entry.get("reservation"), str)
            or not entry["reservation"] or type(entry.get("registry_revision")) is not int
            or entry["registry_revision"] < 0 or not isinstance(entry.get("statements"), dict)
            or not isinstance(entry.get("cipher_sha256"), str) or _DIGEST.fullmatch(entry["cipher_sha256"]) is None
            or (entry.get("statement_sha256") is not None and _DIGEST.fullmatch(str(entry["statement_sha256"])) is None)
            or not all(_CASE.fullmatch(k) and isinstance(v, str) and _DIGEST.fullmatch(v) for k, v in entry["statements"].items())):
        raise _Invalid("registry")


def _load_registry(root, plaintext):
    """Materialise the registry plaintext as a registry.Registry in `root`.
    Returns (registry, revision, refs): refs maps ciphertext sha256 to artifact digest."""
    from registry import Registry
    state, objects, refs = {"revision": 0, "entries": {}}, {}, {}
    if plaintext:
        value = _json(plaintext, "registry")
        state, objects, refs = value.get("registry"), value.get("objects"), value.get("refs", {})
        if (not isinstance(state, dict) or set(state) != {"revision", "entries"}
                or type(state["revision"]) is not int or state["revision"] < 0
                or not isinstance(state["entries"], dict) or not isinstance(objects, dict)
                or not isinstance(refs, dict)):
            raise _Invalid("registry")
        for case, entry in state["entries"].items():
            _entry(case, entry)
        if not all(isinstance(k, str) and _DIGEST.fullmatch(k) and isinstance(v, str) and _DIGEST.fullmatch(v)
                   for k, v in refs.items()) or not set(refs) <= set(objects):
            raise _Invalid("registry")
        referenced = {e["cipher_sha256"] for e in state["entries"].values()}
        referenced |= {e["search_sha256"] for e in state["entries"].values() if e.get("search_sha256")}
        for digest, text in objects.items():
            if not isinstance(text, str) or _DIGEST.fullmatch(digest) is None:
                raise _Invalid("registry")
            try:
                data = base64.b64decode(text, validate=True)
            except (ValueError, TypeError) as error:
                raise _Invalid("registry") from error
            if hashlib.sha256(data).hexdigest() != digest:
                raise _Invalid("registry")
        if not referenced <= set(objects):
            raise _Invalid("registry")
    registry = Registry(root)
    (root / "registry.json").write_text(json.dumps(state, sort_keys=True))
    for digest, text in objects.items():
        (root / "objects" / (digest + ".age")).write_bytes(base64.b64decode(text, validate=True))
    return registry, state["revision"], refs


def _dump_registry(root, refs):
    """The canonical registry plaintext: stable across retries for the same state."""
    state = json.loads((root / "registry.json").read_text())
    objects = {p.stem: base64.b64encode(p.read_bytes()).decode()
               for p in sorted((root / "objects").glob("*.age"))}
    return json.dumps({"version": _VERSION, "registry": state, "objects": objects,
                       "refs": {k: v for k, v in refs.items() if k in objects}},
                      sort_keys=True, separators=(",", ":")).encode()


def _upgrade_registry(plaintext, sealer, batch_key):
    """Rewrap legacy statement ciphertext only in worker RAM; preserve its registry history."""
    if not plaintext:
        return plaintext
    value = _json(plaintext, 'registry')
    if value.get('legacy') is not True:
        return plaintext
    from worker_secrets import SECRETS
    state, objects = value['registry'], value['objects']
    refs, rewritten = {}, {}
    for case, entry in state['entries'].items():
        _entry(case, entry)
        if entry['status'] == 'released':
            continue
        old = entry['cipher_sha256']
        ciphertext = base64.b64decode(objects[old], validate=True)
        if hashlib.sha256(ciphertext).hexdigest() != old:
            raise _Invalid('registry')
        opened = subprocess.run(['age', '-d', '-i', str(SECRETS / 'statements-key')],
                                input=ciphertext, capture_output=True, timeout=30)
        if opened.returncode or (entry['statement_sha256'] is not None
                and hashlib.sha256(opened.stdout).hexdigest() != entry['statement_sha256']):
            raise _Invalid('registry')
        ref, sealed = sealer.seal(batch_key, ArtifactKind.STATEMENT_REGISTRY, opened.stdout)
        digest = hashlib.sha256(sealed).hexdigest()
        objects[digest], refs[digest], rewritten[old] = base64.b64encode(sealed).decode(), ref.digest, digest
        entry['cipher_sha256'] = digest
    for entry in state['entries'].values():
        entry['statements'] = {case: rewritten.get(digest, digest) for case, digest in entry['statements'].items()}
    value.pop('legacy')
    value['refs'] = refs
    return json.dumps(value, sort_keys=True).encode()


AGE = b"age-encryption.org/v1\n"


def _import_legacy(ciphertext, work, inputs, case_id):
    """Turn a rewrapped pre-durable checkpoint into this case's first work tree, in worker RAM.

    Only the old case tree is kept. Its card, ledger, gate caches, reviews and search evidence
    are dropped, so every screen and gate reruns on today's factory; the old card survives only
    as numbers in `imported_from`. Returns that summary.
    """
    from worker_secrets import SECRETS
    from registry import atomic_json
    import io
    opened = subprocess.run(["age", "-d", "-i", str(SECRETS / "statements-key")], input=ciphertext,
                            capture_output=True, timeout=600)
    if opened.returncode:
        raise _Invalid("import")
    staging = pathlib.Path(tempfile.mkdtemp(dir=work.parent, prefix="import-"))
    try:
        with tarfile.open(fileobj=io.BytesIO(opened.stdout), mode="r:gz") as tar:
            # A macOS tar adds AppleDouble "._*" metadata members; they are never case content.
            members = [m for m in tar.getmembers() if not pathlib.PurePosixPath(m.name).name.startswith("._")]
            roots = {pathlib.PurePosixPath(m.name).parts[0] for m in members if m.name not in ("", ".")}
            if len(roots) != 1 or _CASE.fullmatch(next(iter(roots))) is None:
                raise _Invalid("import")
            name = next(iter(roots))
            # Agent state and bench results may hold links; only the case tree and card are read.
            wanted = [m for m in members if m.name == f"{name}/scorecard.json" or m.name == f"{name}/case"
                      or m.name.startswith(f"{name}/case/")]
            tar.extractall(staging, members=wanted, filter="data")
        old, case = staging / name, staging / name / "case"
        card = json.loads((old / "scorecard.json").read_text())
        if not case.is_dir() or not (case / "statement.md").is_file() or card.get("case") != old.name:
            raise _Invalid("import")
        app = json.loads((case / "case.json").read_text()).get("app") or {}
        if (app.get("repo"), app.get("commit")) != (inputs["app_repo"], inputs["app_commit"]):
            raise _Invalid("import")
        gates = card.get("gates") if isinstance(card.get("gates"), dict) else {}
        spent = (card.get("continuation_budget") or {}).get("cost")
        summary = {"case": old.name, "source": card.get("source"), "gates": dict(gates),
                   "failed_gate": card.get("failed_gate"), "spent_usd": spent if type(spent) in (int, float) else None,
                   "written": gates.get("G1") == "pass"}
        if work.exists():
            shutil.rmtree(work)
        work.mkdir()
        case.rename(work / "case")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    atomic_json(work / "continuation-budget.json", {"calls": 0, "events": [], "cost": 0})
    fresh = _card(inputs, case_id, False)
    fresh["imported_from"] = summary
    atomic_json(work / "scorecard.json", fresh)
    return summary


def _card(value, case_id, dry_run):
    card = {"case": case_id, "dry_run": dry_run, "seed": value["seed"], "gates": {}, "failed_gate": None,
            "factory_slots_prepared": 1}
    import model_runtime
    table = model_runtime.PROMPTS.parent / os.environ.get("FACTORY_ROTATION", "rotation-3writers.json")
    slots = len(json.loads(table.read_text())["slots"])
    # Engine case IDs end in their batch ordinal; cycle the existing cohort table.
    ordinal = case_id.rsplit("-", 1)[-1]
    default = (int(ordinal) - 1) % slots + 1 if ordinal.isdigit() and int(ordinal) > 0 else 1
    card["rotation_slot"] = value.get("rotation_slot") or default
    if not 1 <= card["rotation_slot"] <= slots: raise _Invalid("inputs")
    card["source"] = "fixture (dry-run)" if dry_run else value["source"]
    for name in ("models", "roles", "recovery_config"):
        if value.get(name) is not None:
            card[name] = value[name]
    return card


def _write_case(c, value):
    """The initial real case tree: what the existing admission path left as its candidate."""
    from registry import atomic_json
    case = c.case
    case.mkdir(parents=True, exist_ok=True)
    (case / "promise.md").write_text(value["promise"])
    if value.get("candidate"):
        (case / "statement.md").write_text(value["candidate"]["statement"])
    atomic_json(case / "case.json", {
        "source": value["source"],
        "app": {"repo": value["app_repo"], "commit": value["app_commit"]},
        "promise_paths": value.get("promise_paths", []),
        "promise_checks": value.get("promise_checks", []),
        "leak_words": []})


def _pin_models(c, runner, inputs):
    """Validate explicit chains through the existing family/effort selection rules."""
    requested = inputs.get("models")
    if not requested:
        return
    flags = {"builder": "builder", "attacker": "attacker", "strong_calibrator": "strong_calibrator",
             "easy_calibrator": "easy_calibrator"}
    roles = {"builder": "writer", "attacker": "stress_tester", "strong_calibrator": "strong_calibrator",
             "easy_calibrator": "easy_calibrator", "reviewer1": "reviewer", "reviewer2": "reviewer2"}
    if set(requested) != {*flags, "reviewers"}:
        raise _Invalid("models")
    reviewers = requested["reviewers"]
    if not isinstance(reviewers, list) or not 1 <= len(reviewers) <= 2:
        raise _Invalid("models")
    chains = {**{flag: requested[name] for name, flag in flags.items()},
              **{f"reviewer{i}": chain for i, chain in enumerate(reviewers, 1)}}
    for flag, chain in chains.items():
        if not isinstance(chain, list) or len(chain) != 1 or not isinstance(chain[0], str):
            raise _Invalid("models")
        setattr(c.args, flag, chain[0])
        role = inputs.get("roles", {}).get(roles[flag], {})
        if role and (role.get("model") != chain[0] or not isinstance(role.get("effort"), str)):
            raise _Invalid("models")
        if role:
            setattr(c.args, flag + "_effort", role["effort"])
    selected = runner.pick_models(c)
    if selected != requested:
        raise _Invalid("models")
    c.models = c.card["models"] = selected


def _prior_statements(root, refs, sealer, batch_key, case_id, work, imported=None):
    state = json.loads((root / "registry.json").read_text())
    prior = {}
    directory = work / "statements"
    directory.mkdir(exist_ok=True)
    for case, entry in state["entries"].items():
        # An import is its old case's own idea: that entry is not a duplicate of it.
        if case in (case_id, imported) or entry["status"] == "released":
            continue
        digest = entry["cipher_sha256"]
        ref = Ref(refs[digest], ArtifactKind.STATEMENT_REGISTRY)
        raw = sealer.open(batch_key, ref, (root / "objects" / (digest + ".age")).read_bytes())
        if entry["statement_sha256"] is not None and hashlib.sha256(raw).hexdigest() != entry["statement_sha256"]:
            raise _Invalid("registry")
        path = directory / (case + ".md")
        path.write_bytes(raw)
        path.chmod(0o600)
        prior[case] = str(path)
    return state["revision"], prior


def _screen(c, runner, registry, refs, sealer, batch_key, step_input):
    from admission import MAX_CANDIDATES
    from registry import atomic_json
    root = registry.root
    imported = (c.card.get("imported_from") or {}).get("case")
    revision, prior = _prior_statements(root, refs, sealer, batch_key, step_input.case_id, c.work, imported)
    c.engine_prior_statements, c.engine_registry_revision = prior, revision

    def reserve():
        raw = c.statement.encode()
        ref, ciphertext = sealer.seal(batch_key, ArtifactKind.STATEMENT_REGISTRY, raw)
        digest = hashlib.sha256(raw).hexdigest()
        rejected = [r["statement_sha256"] for r in c.card.get("rejected_candidates", [])]
        previous = json.loads((root / "registry.json").read_text())["entries"].get(c.case_id)
        if previous and previous["status"] != "released" and previous["statement_sha256"] != digest and previous["statement_sha256"] not in rejected:
            raise _Conflict()
        entry = registry.replace_rejected(c.case_id, digest, ciphertext, rejected)
        # A replay can retain the earlier randomized ciphertext for the same statement.
        if entry["cipher_sha256"] == hashlib.sha256(ciphertext).hexdigest():
            refs[entry["cipher_sha256"]] = ref.digest
        c.admission_binding = c.card["admission_binding"] = {k: entry[k] for k in ("reservation", "registry_revision")}
        return prior

    c.engine_reserve_candidate = reserve
    rejected = c.card.setdefault("rejected_candidates", [])
    # An import has exactly one candidate, its own; a rejection never replaces its case tree.
    limit = 1 if imported else MAX_CANDIDATES
    while len(rejected) < limit:
        c.card["candidate_attempts"] = len(rejected) + 1
        if runner.statement_precheck(c):
            return True
        digest = c.card.get("statement_sha256")
        if digest and not any(r["statement_sha256"] == digest for r in rejected):
            rejected.append({"statement_sha256": digest,
                             "screen": c.card.get("admission", {}).get("screen", "selection"),
                             "problems": getattr(c, "precheck_problems", [])})
        else:
            # A failed selection or repeated rejection still consumes a bounded candidate try.
            rejected.append({"statement_sha256": digest, "screen": "selection_failed"})
        old = c.work / "statements" / f"rejected-{len(rejected)}"
        c.case.rename(old)
        c.case.mkdir()
        for name in ("promise.md", "case.json"):
            if (old / name).is_file(): shutil.copyfile(old / name, c.case / name)
        atomic_json(c.work / "selection-rejections.json", rejected)
        c.__dict__.pop("precheck_problems", None)
        if len(rejected) < limit:
            request = runner.prompt("selection", runner.selection_context(c, prior, round="reselection",
                rejected_candidate_dir=str(old), rejection_feedback_path=str(c.work / "selection-rejections.json"),
                rejected_statement_hashes=[r["statement_sha256"] for r in rejected]))
            if runner.opencode(c, c.models["builder"], request, c.case, f"builder-selection-{len(rejected) + 1}"):
                return False
    c.card["admission"] = {"status": "exhausted", "candidates": len(rejected)}
    return False


def run(worker, step_input, keys):
    """Run the existing admission screens with durable artifacts and accounting."""
    from budget import BudgetError
    from durable import worker_step
    from registry import atomic_json
    fail = lambda reason: (StepResult(Outcome.INFRA_ERROR, reason), {})
    if step_input.step.kind is not StepKind.ADMIT or step_input.batch_id not in keys or step_input.case_id not in keys:
        return fail("admit:inputs_invalid")
    sealer = worker.sealer()
    case_key, batch_key = keys[step_input.case_id], keys[step_input.batch_id]
    try:
        inputs = _inputs(worker.open_blob(sealer, batch_key, step_input.inputs))
        registry_plaintext = worker.open_blob(sealer, batch_key, step_input.registry)
    except _Invalid:
        return fail("admit:inputs_invalid")
    except Exception:
        return fail("infra:blob_unavailable")
    runner, c, before, outputs = worker.runner(), None, None, {}
    base = pathlib.Path(worker.home) / "work"
    base.mkdir(parents=True, exist_ok=True)
    root = pathlib.Path(tempfile.mkdtemp(dir=base, prefix="admit-"))

    def seal(kind, key, raw):
        ref, ciphertext = sealer.seal(key, kind, raw)
        outputs[worker_step.blob_name(ref)] = ciphertext
        return ref

    def account():
        return worker_step.usage_since(before, c.ledger, step_input.money_ceiling_usd_micros) if before is not None else Usage()

    def snapshot():
        atomic_json(c.work / "scorecard.json", c.card)
        return seal(ArtifactKind.CASE_SNAPSHOT, case_key, worker_step.snapshot_bytes(c, runner))

    try:
        try:
            registry_plaintext = _upgrade_registry(registry_plaintext, sealer, batch_key)
            registry, _, refs = _load_registry(root / "registry", registry_plaintext)
        except _Invalid:
            return fail("admit:registry_invalid")
        # Keep the ledger at its stable path: the supervisor can account a killed/failed attempt.
        work = base / step_input.case_id
        if step_input.snapshot is not None:
            restored = worker.open_blob(sealer, case_key, step_input.snapshot)
            if restored.startswith(AGE):
                if inputs["dry_run"]:
                    return fail("admit:inputs_invalid")
                try:
                    _import_legacy(restored, work, inputs, step_input.case_id)
                except (_Invalid, OSError, ValueError, KeyError, AttributeError, tarfile.TarError):
                    return fail("admit:import_invalid")
            else:
                worker_step.restore(restored, work)
        else:
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir()
            atomic_json(work / "continuation-budget.json", {"calls": 0, "events": [], "cost": 0})
            atomic_json(work / "scorecard.json", _card(inputs, step_input.case_id, inputs["dry_run"]))
        c = runner.context_for_step(step_input, work)
        _pin_models(c, runner, inputs)
        before = worker_step.ledger_totals(c.ledger)
        worker._save_baseline(step_input, c.ledger, before)
        worker.bind_checkpoint(step_input, c, sealer, case_key, runner)
        if inputs["dry_run"]:
            if not c.case.exists(): runner.build_fixture(c)
            c.card["admission"] = {"status": "practice_dry_run"}
            reason, accepted = "admit:practice", True
        else:
            from model_runtime import require_bounded_models
            require_bounded_models(c)
            if not c.case.exists(): _write_case(c, inputs)
            runner.provider_preflight(c)
            accepted = _screen(c, runner, registry, refs, sealer, batch_key, step_input)
            reason = "admit:selected" if accepted else "admit:exhausted"
            if accepted and (c.card.get("imported_from") or {}).get("written"):
                reason = "admit:imported_written"  # the engine resumes a written case at STRESS
        snap = snapshot()
        usage = account()
        if not accepted:
            return StepResult(Outcome.EXHAUSTED, reason, usage=usage, snapshot=snap), outputs
        reg = seal(ArtifactKind.STATEMENT_REGISTRY, batch_key, _dump_registry(root / "registry", refs))
        return StepResult(Outcome.OK, reason, usage=usage, snapshot=snap, registry=reg), outputs
    except Exception as error:
        usage = account()  # Unknown usage deliberately propagates to the supervisor's loss handling.
        fields = {"outcome": Outcome.INFRA_ERROR, "reason": "admit:processing_failed"}
        if isinstance(error, _Conflict):
            fields = {"outcome": Outcome.EXHAUSTED, "reason": "admit:conflict"}
        elif isinstance(error, BudgetError):
            from model_router import ProviderWait
            translated = (runner.engine_provider_wait(c, error, now=worker.clock())
                          if c is not None and isinstance(error, ProviderWait)
                          else runner.engine_stop(c, str(error)) if c is not None else None)
            if translated is not None:
                fields = translated
            else:
                classified = worker.classifier()(str(error), step=StepKind.ADMIT, now=worker.clock())
                fields = {"outcome": classified.outcome, "reason": classified.reason, "retry_at": classified.retry_at}
                if getattr(error, "provider_failure", None):
                    fields["retry_at"] = error.provider_failure.get("reset_at") or fields["retry_at"]
        if c is not None and before is not None:
            import traceback
            fields['diagnostic'] = seal(ArtifactKind.DIAGNOSTIC, case_key,
                worker_step.diagnostic(c, {**fields, 'stop': str(error), 'traceback': traceback.format_exc()}))
            try: fields["snapshot"] = snapshot()
            except Exception: pass  # Usage is retained even if artifact publication failed.
        return StepResult(**fields, usage=usage), outputs
    finally:
        shutil.rmtree(root, ignore_errors=True)
