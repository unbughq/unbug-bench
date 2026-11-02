"""Finish a public-match extension from completed independent HTTP/review proof."""
import contextlib
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace

from budget import BudgetError
import extension_compare as comparison
import extensions
import job_authority
from registry import atomic_json

_FIELDS = {'schema_version', 'kind', 'extension_id', 'writer_operation_id', 'round',
           'entry_sha256', 'source_generation', 'case_sha256', 'case_tree_sha256',
           'receipt', 'source_sha256', 'rows', 'versions', 'execution', 'models'}


def refuse():
    raise BudgetError('extension_snapshot_changed')


def raw(path, root):
    from diagnosis import _input_bytes
    return _input_bytes(path, root)


def read(path, root):
    return json.loads(raw(path, root))


def sha(path, root):
    return hashlib.sha256(raw(path, root)).hexdigest()


def marker(row):
    return f"extension-terminal/{row['extension_id']}-public-match.json"


def _report(c, row):
    return c.work / 'attacks' / f"round-{row['round']}.json"


def _receipt(c, r, row, receipt, report):
    completed = receipt.get('review_completed') or {}
    return (receipt.get('actor') == 'stress_tester' and receipt.get('phase') in ('completed', 'validated')
        and receipt.get('review_pending') is False and type(receipt.get('round')) is int
        and receipt['round'] == row['round'] and type(receipt.get('round_limit')) is int
        and receipt['round_limit'] == row['round'] and receipt.get('report') == report.name
        and receipt['binding']['case'] == r.case_hash(c) and receipt['binding']['case_id'] == c.case_id
        and completed.get('attempt') == receipt.get('review_attempt')
        and completed.get('binding') == hashlib.sha256(json.dumps(receipt['binding'], sort_keys=True).encode()).hexdigest()
        and completed.get('report_sha256') == sha(report, c.work) and r.attack_report(report) is not None)


def _intent(c, r, row, report):
    path = report.with_suffix('.public-match.json')
    if not path.exists() and not path.is_symlink(): return None
    envelope = read(path, c.work)
    value = envelope['record']
    if (set(envelope) != {'record', 'sha256'} or envelope['sha256'] != extensions.digest(value)
            or set(value) != _FIELDS or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['kind'] != 'public_match_request' or type(value['extension_id']) is not int
            or type(value['round']) is not int or any(value[key] != row[key] for key in
                ('extension_id', 'writer_operation_id', 'round'))
            or value['entry_sha256'] != extensions.digest(row['entry'])): refuse()
    if value['source_sha256'] != sha(report, c.work):
        if any(sha(old, c.work) == value['source_sha256']
               for old in report.parent.glob(report.stem + '-superseded-*.json')): return None
        refuse()
    receipt = read(c.work / 'attack-state.json', c.work)
    if (value['receipt'] != receipt or not _receipt(c, r, row, receipt, report)
            or value['case_sha256'] != r.case_hash(c)
            or value['case_tree_sha256'] != extensions.digest(extensions.tree(c.case))
            or not isinstance(value['rows'], list) or not value['rows']
            or set(value['versions']) != set(extensions.stages())
            or any(not re.fullmatch('[0-9a-f]{64}', version) for version in value['versions'].values())
            or not re.fullmatch('[0-9a-f]{64}', value['source_generation'])): refuse()
    return value


@contextlib.contextmanager
def capture(c, r, row):
    absent = object()
    previous = getattr(c, 'extension_public_match_recorder', absent)
    def record(owner, rows, report):
        try:
            if owner is not c or report != _report(c, row): return
            receipt = read(c.work / 'attack-state.json', c.work)
            if not _receipt(c, r, row, receipt, report): return
            old = _intent(c, r, row, report)
            if old is not None:
                if old['rows'] != rows: refuse()
                return
            from extension_package import workspace
            w = workspace(c, r)
            value = dict(schema_version=1, kind='public_match_request', extension_id=row['extension_id'],
                writer_operation_id=row['writer_operation_id'], round=row['round'], entry_sha256=extensions.digest(row['entry']),
                source_generation=job_authority.for_case(c).source_generation, case_sha256=r.case_hash(c),
                case_tree_sha256=extensions.digest(extensions.tree(c.case)), receipt=receipt,
                source_sha256=sha(report, c.work), rows=copy.deepcopy(rows), versions=comparison._versions(w),
                execution=comparison._execution(w), models=copy.deepcopy(c.models))
            atomic_json(report.with_suffix('.public-match.json'), {'record': value, 'sha256': extensions.digest(value)})
        except (OSError, ValueError, KeyError, TypeError, AttributeError, BudgetError):
            refuse()
    c.extension_public_match_recorder = record
    try: yield
    finally:
        if previous is absent: c.__dict__.pop('extension_public_match_recorder', None)
        else: c.extension_public_match_recorder = previous


def _confirmed(c, r, row, intent, report):
    from admission import search_binding
    from late_recovery import freshness_proof
    path = c.work / 'freshness-verdict.json'
    if not path.exists() and not path.is_symlink(): return None
    confirmation = read(path, c.work)
    # A stale cache is not a completed verdict for this request.
    binding = confirmation.get('binding')
    bound = SimpleNamespace(case=c.case, case_id=c.case_id, models=intent['models'],
                            admission_binding=binding.get('reservation') if isinstance(binding, dict) else None)
    if binding != {**search_binding(bound, intent['rows']), 'confirmation_contract': 2}: return None
    models = intent['models']
    if r.family(models['reviewers'][0][0]) in {r.family(models[key][0]) for key in ('builder', 'attacker')}: refuse()
    proof = dict(source_sha256=intent['source_sha256'], case_sha256=intent['case_sha256'],
                 rows=intent['rows'], verdict_path=confirmation['verdict_path'], confirmation=confirmation)
    snapshot, blocked = freshness_proof(c, intent['receipt'], report, proof, retained=True)
    if not snapshot.freshness_confirmed_hits: return None
    if len(blocked) != snapshot.freshness_confirmed_hits: return None
    result = r.attack_report(report)
    freshness = dict(rows=len(intent['rows']), requested=len(dict.fromkeys(result.get('freshness_review', []))),
        verdict_path=confirmation['verdict_path'], outcome='public_match', reason='same_bug')
    return {'confirmed_public_match': True, 'freshness': freshness}


def _metadata(row, intent):
    return dict(schema_version=1, kind='public_match', extension_id=row['extension_id'],
        writer_operation_id=row['writer_operation_id'], round=row['round'], entry_sha256=extensions.digest(row['entry']),
        case_tree_sha256=intent['case_tree_sha256'], request_sha256=extensions.digest(intent))


def _build(c, r, row, root, intent, detail):
    """Copy only the named proof; every resulting byte comes from retained inputs."""
    case, work = root / 'case', root / 'work'
    shutil.copytree(c.case, case)
    if extensions.digest(extensions.tree(case)) != intent['case_tree_sha256']: refuse()
    relative_report = 'attacks/' + _report(c, row).name
    confirmation = read(c.work / 'freshness-verdict.json', c.work)
    relative = confirmation['verdict_path']
    if not isinstance(relative, str) or not re.fullmatch(r'g2-confirm-[0-9]+/verdict.json', relative): refuse()
    directory = Path(relative).parent
    paths = ['attack-state.json', relative_report, str(Path(relative_report).with_suffix('.public-match.json')),
             'freshness-verdict.json', relative, str(directory / 'review-completed.json')]
    retrieval = c.work / directory / 'retrieval'
    paths.extend((directory / 'retrieval' / name).as_posix() for name in extensions.tree(retrieval))
    for name in sorted(paths):
        target = work / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw(c.work / name, c.work))
    owner = SimpleNamespace(work=work, case=case, case_id=c.case_id)
    copied = _intent(owner, r, row, work / relative_report)
    if copied != intent or _confirmed(owner, r, row, intent, work / relative_report) != detail: refuse()
    name = marker(row)
    (work / name).parent.mkdir(parents=True, exist_ok=True)
    atomic_json(work / name, _metadata(row, intent)); paths.append(name)
    w = comparison.Workspace(case, work, r.BENCH, c.args if hasattr(c, 'args') else SimpleNamespace(),
        intent['models'], {}, intent['execution']['seed'], intent['execution']['slot'], c.case_id)
    observed, evidence = comparison._save(w, 'stress', intent['versions']['stress'], False, detail,
                                          sorted(paths), execution=intent['execution'])
    stages = [observed] + [dict(stage=stage, version=intent['versions'][stage], status='unreached',
        binding_sha256=None, evidence_sha256=None) for stage in extensions.stages() if stage != 'stress']
    snapshot = dict(source_generation=intent['source_generation'], case_sha256=intent['case_tree_sha256'],
                    stages=stages, frontier=0, evidence=evidence)
    extensions.validate_snapshot(snapshot)
    if extensions.digest(extensions.tree(c.case)) != intent['case_tree_sha256']: refuse()
    return snapshot, work


def complete(c, r, row):
    job_authority.for_case(c)
    try:
        report = _report(c, row)
        intent = _intent(c, r, row, report)
        if intent is None: return False
        detail = _confirmed(c, r, row, intent, report)
        if detail is None: return False
        extensions._verify_case(c, row['extension_id'], 'entry', row['entry'])
        with tempfile.TemporaryDirectory(prefix='unbug-public-match-') as directory:
            snapshot, work = _build(c, r, row, Path(directory), intent, detail)
            extensions.complete(c, snapshot, evidence_root=work)
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, BudgetError):
        refuse()


def verified(c, r, row):
    outcome = row['outcome']
    name = 'comparison-support/stress/' + marker(row)
    if outcome is None or name not in outcome['evidence']: return False
    try:
        for phase in ('entry', 'outcome'):
            extensions._verify_case(c, row['extension_id'], phase, row[phase])
        base = c.work / 'extension-snapshots' / str(row['extension_id']) / 'outcome'
        support = base / 'evidence' / 'comparison-support/stress'
        owner = SimpleNamespace(work=support, case=base / 'case', case_id=c.case_id)
        report = _report(owner, row)
        intent = _intent(owner, r, row, report)
        if intent is None or read(support / marker(row), support) != _metadata(row, intent): refuse()
        detail = _confirmed(owner, r, row, intent, report)
        if detail is None: refuse()
        w = comparison.Workspace(base / 'case', base / 'evidence', r.BENCH, SimpleNamespace(),
            intent['models'], {}, intent['execution']['seed'], intent['execution']['slot'], c.case_id)
        if comparison._load(w, outcome['stages'][0], outcome['evidence']) is None: refuse()
        with tempfile.TemporaryDirectory(prefix='unbug-verify-public-') as directory:
            snapshot, _ = _build(owner, r, row, Path(directory), intent, detail)
            if snapshot != outcome: refuse()
    except (OSError, ValueError, KeyError, TypeError, AttributeError, BudgetError):
        refuse()
    return True


def stop(c, row):
    root = c.work / 'extension-snapshots' / str(row['extension_id']) / 'outcome/evidence'
    detail = read(root / 'comparison-receipts/stress.json', root)['detail']['freshness']
    from late_recovery import invalidate
    invalidate(c)
    c.card.pop('infrastructure_gate', None)
    c.card.update(gates={'G2': 'fail'}, gate_results={'G2': copy.deepcopy(detail)}, failed_gate='G2',
        failed_detail=copy.deepcopy(detail), loop_freshness=copy.deepcopy(detail),
        stress_review={'status': 'completed', 'round': row['round'], 'reason': 'confirmed_public_match'})
    raise BudgetError('extension_incomplete')
