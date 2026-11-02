"""Compare retained revisions without running gates against the live candidate.

The owning worker supplies a trusted, non-mutating evaluator. There is no default
run.gN adapter: runner globals point at live results. Dispatch and money admission
belong to the caller, as do bounded retries. This module never retries a stage.
"""
import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile

from budget import BudgetError
from case_contract import CaseProblem
import extensions
import gate_state
from registry import atomic_json
from run_validity import InvalidInfra


@dataclass(frozen=True)
class Workspace:
    case: Path
    work: Path
    bench: Path
    args: object
    models: dict
    card: dict
    seed: int
    factory_slot: int
    case_id: str
    execution: dict | None = None


class _Changed(RuntimeError):
    """An evaluator changed its inputs; no pair may be published."""


def _versions(w):
    return {stage: gate_state.scientific_version(w, stage, w.bench)
            for stage in extensions.stages()}


def _case(w):
    return extensions.digest(extensions.tree(w.case))


def _configuration(w):
    return copy.deepcopy((vars(w.args), w.models, w.card.get('roles', {}), getattr(w, 'execution', None)))


def _binding(w, stage, version):
    # Scientific identity is portable. Full execution provenance is retained in
    # the hashed receipt, but a slot/worker change cannot reroll its verdict.
    return extensions.digest(dict(stage=stage, scientific_version=version, case_sha256=_case(w)))


def _calibration(w, stage):
    if stage != 'G16':
        return None
    identity = copy.deepcopy(gate_state.calibration_binding(w, w.bench))
    # The receipt records the actual seed/slot separately. Both are execution
    # provenance, not reasons to re-judge a fixed case at the same gate version.
    identity.pop('seed', None)
    identity.pop('slot', None)
    return identity


def _execution(w):
    override = getattr(w, 'execution', None)
    if override is not None and (not isinstance(override, dict) or
            set(override) != {'bench_workers', 'concurrent_roles'} or
            type(override['bench_workers']) is not int or override['bench_workers'] < 1 or
            type(override['concurrent_roles']) is not bool):
        raise ValueError('invalid comparison execution')
    result = dict(seed=w.seed, slot=w.factory_slot, bench_workers=getattr(w.args, 'bench_workers', 1),
                concurrent_roles=getattr(w.args, 'concurrent_roles', True),
                slot_environment=os.environ.get('UNBUG_FACTORY_SLOT'))
    result.update(override or {})
    return result


def _path(root, name):
    if (not isinstance(name, str) or not name or Path(name).is_absolute() or
            Path(name).as_posix() != name or '..' in Path(name).parts or
            name.startswith(('case/', 'extension-snapshots/'))):
        raise ValueError('invalid evidence path')
    path = root / name
    if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)):
        raise ValueError('symlink evidence')
    if not path.is_file():
        raise ValueError('missing evidence')
    return path


def _pending(ok, detail):
    return (type(ok) is not bool or not isinstance(detail, dict) or
            'error' in detail or detail.get('classification') == 'invalid-infra' or
            detail.get('invalid_infra') is True or detail.get('execution_valid') is False or
            (ok and (detail.get('review_inconclusive') is True or detail.get('verdict_valid') is False)))


def _receipt_name(stage):
    return f'comparison-receipts/{stage}.json'


def _load(w, row, evidence):
    """Verify terminal proof; reuse policy is separate from proof validity."""
    try:
        stage = row['stage']
        name = _receipt_name(stage)
        path = _path(w.work, name)
        if row['status'] not in ('pass', 'fail') or evidence.get(name) != gate_state.digest(path):
            return None
        receipt = json.loads(path.read_text())
        if not isinstance(receipt, dict) or set(receipt) != {
                'schema_version', 'stage', 'scientific_version', 'binding_sha256',
                'case_sha256', 'status', 'detail', 'support', 'calibration_identity', 'execution'}:
            return None
        if (type(receipt['schema_version']) is not int or receipt['schema_version'] != 2 or
                receipt['stage'] != stage or receipt['scientific_version'] != row['version'] or
                receipt['case_sha256'] != _case(w) or receipt['status'] != row['status'] or
                receipt['binding_sha256'] != row['binding_sha256'] or
                row['binding_sha256'] != _binding(w, stage, row['version']) or
                row['evidence_sha256'] != evidence[name] or
                _pending(row['status'] == 'pass', receipt['detail'])):
            return None
        json.dumps(receipt, allow_nan=False)
        if not isinstance(receipt['execution'], dict) or set(receipt['execution']) != {
                'seed', 'slot', 'bench_workers', 'concurrent_roles', 'slot_environment'}:
            return None
        expected_calibration = _calibration(w, stage)
        if receipt['calibration_identity'] != expected_calibration:
            return None
        support = receipt['support']
        if not isinstance(support, dict) or not support:
            return None
        for name, sha in support.items():
            if (not name.startswith(f'comparison-support/{stage}/') or
                    evidence.get(name) != sha or gate_state.digest(_path(w.work, name)) != sha):
                return None
        return {_receipt_name(stage): row['evidence_sha256'], **support}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save(w, stage, version, ok, detail, paths):
    # Normalize first: neither non-JSON results nor mutable callback references
    # can enter a receipt. Each stage owns copies of its supporting evidence.
    detail = json.loads(json.dumps(detail, allow_nan=False))
    if _pending(ok, detail) or not isinstance(paths, (list, tuple)) or not paths:
        raise ValueError('incomplete execution')
    support = {}
    for name in paths:
        source = _path(w.work, name)
        if name.startswith(('comparison-receipts/', 'comparison-support/')):
            raise ValueError('reserved evidence path')
        target_name = f'comparison-support/{stage}/{name}'
        target = w.work / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        support[target_name] = gate_state.digest(target)
    binding = _binding(w, stage, version)
    record = dict(schema_version=2, stage=stage, scientific_version=version,
        binding_sha256=binding, case_sha256=_case(w), status='pass' if ok else 'fail',
        detail=detail, support=support,
        calibration_identity=_calibration(w, stage), execution=_execution(w))
    name = _receipt_name(stage)
    (w.work / name).parent.mkdir(parents=True, exist_ok=True)
    atomic_json(w.work / name, record)
    sha = gate_state.digest(w.work / name)
    return dict(stage=stage, version=version, status=record['status'],
                binding_sha256=binding, evidence_sha256=sha), {name: sha, **support}


def snapshot(w, source_generation, evaluate, previous=None, versions=None):
    """Shared producer for original and rebased snapshots; no history mutation.

    evaluate(workspace, stage) returns (bool, detail object, relative proof paths).
    It must enumerate all supporting files and leave case/configuration unchanged.
    InvalidInfra is pending. CaseProblem is a bound scientific failure.
    """
    versions = _versions(w) if versions is None else dict(versions)
    if list(versions) != list(extensions.stages()):
        raise ValueError('invalid comparison version vector')
    case, configuration = _case(w), _configuration(w)
    rows, evidence, stopped = [], {}, False
    for stage, version in versions.items():
        row = dict(stage=stage, version=version, status='unreached',
                   binding_sha256=None, evidence_sha256=None)
        if not stopped:
            old = next((r for r in previous['stages'] if r['stage'] == stage), None) if previous else None
            retained = (_load(w, old, previous['evidence']) if old and
                        old['version'] == version and old['status'] == 'pass' and
                        stage in gate_state.REUSABLE else None)
            if retained:
                row = copy.deepcopy(old)
                evidence.update(retained)
            else:
                try:
                    result = evaluate(w, stage)
                except CaseProblem as error:
                    detail = {'problems': [str(error)]}
                    name = f'comparison-errors/{stage}.json'
                    (w.work / name).parent.mkdir(parents=True, exist_ok=True)
                    atomic_json(w.work / name, detail)
                    result = False, detail, [name]
                except BudgetError as error:
                    if stage != 'stress' or str(error) != 'freshness_unresolved':
                        raise
                    result = None
                except InvalidInfra:
                    result = None
                # Only malformed returned evidence is pending. Programming errors
                # raised inside an adapter propagate without publishing a pair.
                try:
                    if not isinstance(result, (tuple, list)) or len(result) != 3:
                        raise ValueError('malformed evaluator result')
                    row, proof = _save(w, stage, version, *result)
                    evidence.update(proof)
                except (ValueError, TypeError, FileNotFoundError):
                    row.update(status='pending', binding_sha256=None, evidence_sha256=None)
            if _case(w) != case or _configuration(w) != configuration:
                raise _Changed('comparison evaluator changed its input')
            stopped = row['status'] != 'pass'
        rows.append(row)
    if _versions(w) != versions:
        raise _Changed('comparison version changed')
    result = dict(source_generation=source_generation, case_sha256=case, stages=rows,
        frontier=next((i for i, r in enumerate(rows) if r['status'] != 'pass'), len(rows)), evidence=evidence)
    extensions.validate_snapshot(result)
    # A later callback cannot overwrite the earlier stages' copied proofs.
    for row in rows:
        if row['status'] in ('pass', 'fail') and _load(w, row, evidence) is None:
            raise _Changed('comparison evidence changed')
    return result


def _workspace(c, root, bench, execution=None):
    return Workspace(root / 'case', root / 'work', Path(bench), copy.deepcopy(c.args),
        copy.deepcopy(c.models), {'roles': copy.deepcopy(c.card.get('roles', {}))},
        c.seed, getattr(c, 'factory_slot', 0), c.case_id, copy.deepcopy(execution))


def _source(c, number, phase, pair=None):
    parent = c.work / 'extension-snapshots' / str(number)
    return (parent / ('comparison-' + extensions.digest(pair)) / phase if pair else
            parent / phase / 'evidence')


def current_pair(c, number, bench, *, execution=None):
    """Verify the selected terminal pair before any retry/setup boundary.

    Return (pair, valid, retained). Invalid original opaque proof may be
    reconstructed; invalid retained scored proof may never be rerolled.
    """
    owner = copy.copy(c)
    owner.card = copy.deepcopy(c.card)
    history = extensions.read(owner)
    if type(number) is not int or not 1 <= number <= len(history):
        raise BudgetError('extension_history_invalid')
    original = history[number - 1]
    if original['outcome'] is None: return None, False, False
    configuration = _configuration(c)
    with tempfile.TemporaryDirectory(prefix='unbug-verify-') as directory:
        workspaces = {}
        for phase in ('entry', 'outcome'):
            w = _workspace(c, Path(directory) / phase, bench, execution)
            w.work.mkdir(parents=True)
            shutil.copytree(c.work / 'extension-snapshots' / str(number) / phase / 'case', w.case)
            if _case(w) != original[phase]['case_sha256']:
                raise BudgetError('extension_snapshot_changed')
            workspaces[phase] = w
        versions = _versions(workspaces['entry'])
        if versions != _versions(workspaces['outcome']): return None, False, False
        selected = extensions.comparison_pair(original, list(versions.values()))
        retained = selected if any(selected is p for p in original['comparisons']) else None
        if not selected or extensions.progress(selected['entry'], selected['outcome']) == 'pending':
            return None, False, False
        valid = True
        for phase, w in workspaces.items():
            extensions._save_evidence(_source(c, number, phase, retained), w.work, selected[phase])
            valid &= all(_load(w, row, selected[phase]['evidence']) is not None
                         for row in selected[phase]['stages'] if row['status'] in ('pass', 'fail'))
        valid &= (_configuration(c) == configuration and
                  all(_versions(w) == versions for w in workspaces.values()))
        return copy.deepcopy(selected), bool(valid), retained is not None


def compare(c, number, bench, evaluate, *, execution=None):
    """Return progress/no_progress/regression/pending. Single owning worker only.

    Live mutations are limited to append-only comparison history and proofs.
    A completed current pair is authoritative: no stochastic re-rolls.
    """
    terminal, valid, was_retained = current_pair(c, number, bench, execution=execution)
    if terminal is not None:
        if valid: return extensions.progress(terminal['entry'], terminal['outcome'])
        if was_retained: return 'pending'
    owner = copy.copy(c)
    owner.card = copy.deepcopy(c.card)
    history = extensions.read(owner)
    if type(number) is not int or not 1 <= number <= len(history):
        raise BudgetError('extension_history_invalid')
    original = history[number - 1]
    if original['outcome'] is None:
        return 'pending'
    configuration = _configuration(c)
    with tempfile.TemporaryDirectory(prefix='unbug-compare-') as directory:
        root = Path(directory)
        workspaces = {}
        for phase in ('entry', 'outcome'):
            w = _workspace(c, root / phase, bench, execution)
            w.work.mkdir(parents=True)
            shutil.copytree(c.work / 'extension-snapshots' / str(number) / phase / 'case', w.case)
            if _case(w) != original[phase]['case_sha256']:
                raise BudgetError('extension_snapshot_changed')
            workspaces[phase] = w
        versions = _versions(workspaces['entry'])
        if versions != _versions(workspaces['outcome']):
            return 'pending'
        selected = extensions.comparison_pair(original, list(versions.values()))
        retained = selected if any(selected is p for p in original['comparisons']) else None
        if selected:
            previous = selected
        elif original['comparisons']:
            previous = retained = original['comparisons'][-1]
        else:
            previous = dict(entry=original['entry'], outcome=original['outcome'])
        pair = {}
        try:
            for phase, w in workspaces.items():
                # Do not leave evidence from older candidate checks in scratch.
                shutil.rmtree(w.work); w.work.mkdir()
                extensions._save_evidence(_source(c, number, phase, retained), w.work, previous[phase])
                pair[phase] = snapshot(w, original[phase]['source_generation'], evaluate,
                                       previous[phase], versions)
            if (_configuration(c) != configuration or
                    any(_versions(w) != versions or _case(w) != original[p]['case_sha256']
                        for p, w in workspaces.items())):
                return 'pending'
        except _Changed:
            return 'pending'
        extensions.retain_comparison(owner, number, pair['entry'], pair['outcome'],
                                     roots={p: w.work for p, w in workspaces.items()})
        return extensions.progress(pair['entry'], pair['outcome'])
