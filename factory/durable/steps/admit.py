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
        `candidate` is the selected statement and its digest, produced by the existing
        admission path (run.statement_precheck). A real run without it fails
        `admit:selection_required`: this adapter never invents a candidate or falls back
        to the practice case. It reserves the candidate through registry.Registry, which
        is the existing dedup/conflict rule, and builds the initial case tree.

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
import pathlib
import re
import shutil
import tempfile

from durable.contract import ArtifactKind, Outcome, StepKind, StepResult, Usage

_VERSION = 1
_CASE = re.compile(r"case-[A-Za-z0-9-]{1,80}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_STATUS = {"screening", "building", "completed", "known_public", "released"}


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
    for name in ("models", "recovery_config"):
        if value.get(name) is not None and not isinstance(value[name], dict):
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


def _card(value, case_id, dry_run):
    card = {"case": case_id, "dry_run": dry_run, "seed": value["seed"], "gates": {}, "failed_gate": None,
            "factory_slots_prepared": 1}
    card["source"] = "fixture (dry-run)" if dry_run else value["source"]
    for name in ("models", "recovery_config"):
        if value.get(name) is not None:
            card[name] = value[name]
    return card


def _write_case(c, value):
    """The initial real case tree: what the existing admission path left as its candidate."""
    from registry import atomic_json
    case = c.case
    case.mkdir(parents=True, exist_ok=True)
    (case / "promise.md").write_text(value["promise"])
    (case / "statement.md").write_text(value["candidate"]["statement"])
    atomic_json(case / "case.json", {
        "source": value["source"],
        "app": {"repo": value["app_repo"], "commit": value["app_commit"]},
        "promise_paths": value.get("promise_paths", []),
        "promise_checks": value.get("promise_checks", []),
        "leak_words": []})
    c.card["statement_sha256"] = value["candidate"]["statement_sha256"]
    c.card["admission"] = {"status": "passed"}


def run(worker, step_input, keys):
    """(StepResult, {blob name: ciphertext}) for one ADMIT attempt.

    Every failure below is a fixed reason code; run_attempt still guards unexpected faults."""
    fail = lambda outcome, reason: (StepResult(outcome, reason), {})
    if step_input.step.kind is not StepKind.ADMIT or step_input.batch_id not in keys \
            or step_input.case_id not in keys:
        return fail(Outcome.INFRA_ERROR, "admit:inputs_invalid")
    sealer = worker.sealer()
    case_key, batch_key = keys[step_input.case_id], keys[step_input.batch_id]
    try:
        inputs = _inputs(worker.open_blob(sealer, batch_key, step_input.inputs))
        registry_plaintext = worker.open_blob(sealer, batch_key, step_input.registry)
    except _Invalid as error:
        return fail(Outcome.INFRA_ERROR, "admit:inputs_invalid" if str(error) == "inputs" else "admit:registry_invalid")
    except Exception:
        return fail(Outcome.INFRA_ERROR, "infra:blob_unavailable")
    dry_run = inputs["dry_run"]
    if not dry_run and inputs.get("candidate") is None:
        return fail(Outcome.INFRA_ERROR, "admit:selection_required")

    runner = worker.runner()
    base = pathlib.Path(worker.home) / "work"
    base.mkdir(parents=True, exist_ok=True)
    root = pathlib.Path(tempfile.mkdtemp(dir=base, prefix="admit-"))
    try:
        try:
            registry, revision, refs = _load_registry(root / "registry", registry_plaintext)
        except _Invalid:
            return fail(Outcome.INFRA_ERROR, "admit:registry_invalid")
        work = root / "work"
        work.mkdir()
        (work / "continuation-budget.json").write_text(json.dumps({"calls": 0, "events": [], "cost": 0}))
        (work / "scorecard.json").write_text(json.dumps(_card(inputs, step_input.case_id, dry_run), sort_keys=True))
        try:
            c = runner.context_for_step(step_input, work)
        except Exception:
            return fail(Outcome.INFRA_ERROR, "admit:context_failed")
        if dry_run:
            try:
                runner.build_fixture(c)
            except Exception:
                return fail(Outcome.INFRA_ERROR, "admit:fixture_failed")
            c.card["admission"] = {"status": "practice_dry_run"}
            reason = "admit:practice"
        else:
            value = inputs["candidate"]
            statement = value["statement"].encode()
            try:
                # The registry stores age ciphertext, not a Ref. The batch key lets every
                # later ADMIT open it; registry.Registry.reject/reserve semantics are reused.
                statement_ref, ciphertext = sealer.seal(batch_key, ArtifactKind.STATEMENT_REGISTRY, statement)
                registry.reserve(step_input.case_id, value["statement_sha256"], ciphertext,
                                 expected_revision=revision)
                refs[hashlib.sha256(ciphertext).hexdigest()] = statement_ref.digest
            except ValueError:
                return fail(Outcome.EXHAUSTED, "admit:conflict")
            reason = "admit:selected"
        try:
            from durable import worker_step
            from registry import atomic_json
            if not dry_run:
                _write_case(c, inputs)
            atomic_json(work / "scorecard.json", c.card)
            snapshot = worker_step.snapshot_bytes(c, runner)
            snapshot_ref, snapshot_ciphertext = sealer.seal(case_key, ArtifactKind.CASE_SNAPSHOT, snapshot)
            registry_ref, registry_ciphertext = sealer.seal(
                batch_key, ArtifactKind.STATEMENT_REGISTRY, _dump_registry(root / "registry", refs))
        except Exception:
            return fail(Outcome.INFRA_ERROR, "admit:snapshot_failed")
        outputs = {f"{snapshot_ref.digest}.{snapshot_ref.kind.value}.age": snapshot_ciphertext,
                   f"{registry_ref.digest}.{registry_ref.kind.value}.age": registry_ciphertext}
        return StepResult(Outcome.OK, reason, usage=Usage(), snapshot=snapshot_ref,
                          registry=registry_ref), outputs
    finally:
        shutil.rmtree(root, ignore_errors=True)
