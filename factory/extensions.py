"""One-round extension histories, immutable case snapshots and versioned progress.

Admission consumes an already reserved writer lease, never a model's permission
or a round allowance. All private state lives outside current gate results.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from budget import BudgetError
from diagnosis import _sha, _uuid4, _state, extension_history
from registry import atomic_json

LIMIT = 5


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def tree(path):
    path = Path(path)
    if path.is_symlink(): raise BudgetError('extension_snapshot_invalid')
    result = {}
    for item in sorted(path.rglob('*')):
        if item.is_symlink(): raise BudgetError('extension_snapshot_invalid')
        if item.is_file(): result[item.relative_to(path).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
        elif not item.is_dir(): raise BudgetError('extension_snapshot_invalid')
    return result


def stages():
    # Use the runner order, not gate-number sorting. Import lazily to avoid cycles.
    from run import GATES
    return ('stress', *(gate for gate in GATES if gate != 'G12'))


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {
            'source_generation', 'case_sha256', 'stages', 'frontier', 'evidence'}:
        raise BudgetError('extension_snapshot_invalid')
    if not _sha(snapshot['source_generation']) or not _sha(snapshot['case_sha256']):
        raise BudgetError('extension_snapshot_invalid')
    evidence = snapshot['evidence']
    if not isinstance(evidence, dict): raise BudgetError('extension_snapshot_invalid')
    for name, value in evidence.items():
        if (not isinstance(name, str) or not name or Path(name).is_absolute() or
                Path(name).as_posix() != name or '..' in Path(name).parts or
                name.startswith(('case/', 'extension-snapshots/')) or not _sha(value)):
            raise BudgetError('extension_snapshot_invalid')
    rows = snapshot['stages']
    if (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
            or [row.get('stage') for row in rows] != list(stages())):
        raise BudgetError('extension_snapshot_invalid')
    for row in rows:
        if (set(row) != {'stage', 'version', 'status', 'binding_sha256', 'evidence_sha256'}
                or not _sha(row['version']) or row['status'] not in ('pass', 'fail', 'pending', 'unreached')
                or (row['status'] in ('pass', 'fail') and
                    (not _sha(row['binding_sha256']) or row['evidence_sha256'] not in evidence.values()))
                or (row['status'] in ('pending', 'unreached') and
                    (row['binding_sha256'] is not None or row['evidence_sha256'] is not None))):
            raise BudgetError('extension_snapshot_invalid')
    frontier = next((i for i, row in enumerate(rows) if row['status'] != 'pass'), len(rows))
    if type(snapshot['frontier']) is not int or snapshot['frontier'] != frontier:
        raise BudgetError('extension_snapshot_invalid')
    return snapshot


def progress(entry, outcome):
    """Compare only identical ordered stage versions and complete execution."""
    validate_snapshot(entry); validate_snapshot(outcome)
    if [r['version'] for r in entry['stages']] != [r['version'] for r in outcome['stages']]:
        return 'pending'
    if any(r['status'] == 'pending' for r in (*entry['stages'], *outcome['stages'])):
        return 'pending'
    for before, after in zip(entry['stages'], outcome['stages']):
        if before['status'] == 'pass':
            if after['status'] == 'fail': return 'regression'
            if after['status'] != 'pass': return 'pending'
    return 'progress' if outcome['frontier'] > entry['frontier'] else 'no_progress'


def public(history):
    return [{'schema_version': 1, 'extension_id': row['extension_id'],
             'writer_operation_id': row['writer_operation_id'], 'entry_sha256': digest(row['entry']),
             'outcome_sha256': digest(row['outcome']) if row['outcome'] is not None else None}
            for row in history]


def read(c):
    path = c.work / 'extension-history.json'
    if path.is_symlink(): raise BudgetError('extension_history_invalid')
    try: history = json.loads(path.read_text()) if path.exists() else []
    except (ValueError, OSError): raise BudgetError('extension_history_invalid') from None
    if not isinstance(history, list) or len(history) > LIMIT: raise BudgetError('extension_history_invalid')
    for number, row in enumerate(history, 1):
        if (not isinstance(row, dict) or set(row) != {'schema_version', 'extension_id',
                'writer_operation_id', 'round', 'entry', 'outcome', 'comparisons'} or
                type(row['schema_version']) is not int or row['schema_version'] != 1 or
                type(row['extension_id']) is not int or row['extension_id'] != number or
                not _uuid4(row['writer_operation_id']) or type(row['round']) is not int or row['round'] < 1 or
                not isinstance(row['comparisons'], list) or (number < len(history) and row['outcome'] is None)):
            raise BudgetError('extension_history_invalid')
        validate_snapshot(row['entry'])
        _verify_case(c, number, 'entry', row['entry'])
        if row['outcome'] is not None:
            validate_snapshot(row['outcome']); _verify_case(c, number, 'outcome', row['outcome'])
        for pair in row['comparisons']:
            if not isinstance(pair, dict) or set(pair) != {'entry', 'outcome'}: raise BudgetError('extension_history_invalid')
            validate_snapshot(pair['entry']); validate_snapshot(pair['outcome'])
            if (pair['entry']['case_sha256'] != row['entry']['case_sha256'] or row['outcome'] is None or
                    pair['outcome']['case_sha256'] != row['outcome']['case_sha256']):
                raise BudgetError('extension_history_invalid')
            root = c.work / 'extension-snapshots' / str(number) / ('comparison-' + digest(pair))
            for phase in ('entry', 'outcome'):
                if tree(root / phase) != pair[phase]['evidence']:
                    raise BudgetError('extension_snapshot_changed')
    projected = public(history)
    if extension_history({'extension_history': projected}) is None: raise BudgetError('extension_history_invalid')
    if c.card.get('extension_history', projected) != projected: raise BudgetError('extension_history_invalid')
    c.card['extension_history'] = projected
    return history


def _verify_case(c, number, phase, snapshot):
    path = c.work / 'extension-snapshots' / str(number) / phase / 'case'
    if not path.is_dir() or path.is_symlink() or digest(tree(path)) != snapshot['case_sha256']:
        raise BudgetError('extension_snapshot_changed')
    retained = path.parent / 'evidence'
    if tree(retained) != snapshot['evidence']: raise BudgetError('extension_snapshot_changed')


def _save_case(c, number, phase, snapshot):
    if digest(tree(c.case)) != snapshot['case_sha256']: raise BudgetError('extension_snapshot_changed')
    parent = c.work / 'extension-snapshots' / str(number)
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / phase
    if target.exists():
        _verify_case(c, number, phase, snapshot)
        return
    staged = Path(tempfile.mkdtemp(prefix='.snapshot-', dir=parent))
    try:
        shutil.copytree(c.case, staged / 'case')
        if digest(tree(staged / 'case')) != snapshot['case_sha256']: raise BudgetError('extension_snapshot_changed')
        _save_evidence(c, staged / 'evidence', snapshot)
        _sync_tree(staged)
        os.replace(staged, target)
        _sync_directory(parent)
    finally:
        if staged.exists(): shutil.rmtree(staged)


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _sync_tree(root):
    for path in root.rglob('*'):
        if path.is_file():
            with path.open('rb') as file: os.fsync(file.fileno())
    for path in sorted((p for p in root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        _sync_directory(path)
    _sync_directory(root)
    # New intermediate snapshot directories must also survive before history.
    _sync_directory(root.parent)
    _sync_directory(root.parent.parent)
    _sync_directory(root.parent.parent.parent)


def _save_evidence(c, destination, snapshot):
    for name, expected in snapshot['evidence'].items():
        source = c.work / name
        if any(p.is_symlink() for p in (source, *source.parents) if p.is_relative_to(c.work)):
            raise BudgetError('extension_snapshot_changed')
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected: raise BudgetError('extension_snapshot_changed')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('wb') as output:
            output.write(data); output.flush(); os.fsync(output.fileno())


def _write(c, history):
    atomic_json(c.work / 'extension-history.json', history)
    c.card['extension_history'] = public(history)


def active(c):
    history = read(c)
    return history[-1] if history and history[-1]['outcome'] is None else None


def propose(c, snapshot):
    """Check eligibility before admission without consuming an extension ID."""
    import job_authority
    job_authority.for_case(c)
    validate_snapshot(snapshot)
    history = read(c)
    state = _state(c.card, public(history))
    if not state or state['status'] != 'completed' or state['outcome'] != 'close_to_passing':
        raise BudgetError('extension_diagnosis_required')
    if history and history[-1]['outcome'] is None: raise BudgetError('extension_already_active')
    if len(history) >= LIMIT: raise BudgetError('retired_extension_limit')
    if snapshot['stages'][0]['status'] != 'pass': raise BudgetError('retired_no_progress')
    if history:
        prior = history[-1]
        versions = [r['version'] for r in snapshot['stages']]
        candidates = [{'entry': prior['entry'], 'outcome': prior['outcome']}, *prior['comparisons']]
        pair = next((p for p in reversed(candidates) if
                     [r['version'] for r in p['entry']['stages']] == versions and
                     [r['version'] for r in p['outcome']['stages']] == versions), None)
        result = progress(pair['entry'], pair['outcome']) if pair else 'pending'
        if result == 'pending': raise BudgetError('extension_comparison_pending')
        if result != 'progress': raise BudgetError('retired_no_progress')
    return {'extension_id': len(history) + 1, 'round': c.card.get('builder_rounds', 0) + 1,
            'entry': copy.deepcopy(snapshot), 'exhaustion_id': state['exhaustion_id']}


def admit(c, proposal, lease, operation_id):
    """Append entry only after the writer lease AND its money reservation exist."""
    import job_authority
    job_authority.for_case(c)
    history = read(c)
    if history and history[-1]['outcome'] is None:
        row = history[-1]
        if (row['extension_id'], row['writer_operation_id'], row['round'], row['entry']) != (
                proposal['extension_id'], operation_id, proposal['round'], proposal['entry']):
            raise BudgetError('extension_reservation_mismatch')
        return row
    if propose(c, proposal['entry']) != proposal: raise BudgetError('extension_reservation_mismatch')
    ledger = json.loads(c.ledger.read_text())
    reserved = ledger.get('invocation_reservations', {}).get(lease.lease_id, {})
    if (not _uuid4(operation_id) or reserved.get('state') != 'pending' or
            reserved.get('operation_id') != operation_id or
            reserved.get('call_name') != 'builder-' + str(proposal['round'])):
        raise BudgetError('extension_reservation_missing')
    _save_case(c, proposal['extension_id'], 'entry', proposal['entry'])
    row = dict(schema_version=1, extension_id=proposal['extension_id'], writer_operation_id=operation_id,
               round=proposal['round'], entry=proposal['entry'], outcome=None, comparisons=[])
    history.append(row); _write(c, history)
    return row


def complete(c, snapshot):
    validate_snapshot(snapshot)
    if any(row['status'] == 'pending' for row in snapshot['stages']):
        raise BudgetError('extension_execution_pending')
    history = read(c)
    if not history: raise BudgetError('extension_history_invalid')
    row = history[-1]
    if row['outcome'] is not None:
        if row['outcome'] != snapshot: raise BudgetError('extension_outcome_changed')
        return
    _save_case(c, row['extension_id'], 'outcome', snapshot)
    row['outcome'] = copy.deepcopy(snapshot)
    _write(c, history)


def retain_comparison(c, number, entry, outcome):
    """Runner supplies re-evaluations on both saved revisions at one version."""
    validate_snapshot(entry); validate_snapshot(outcome)
    history = read(c)
    if type(number) is not int or not 1 <= number <= len(history): raise BudgetError('extension_history_invalid')
    row = history[number - 1]
    if (row['outcome'] is None or entry['case_sha256'] != row['entry']['case_sha256'] or
            outcome['case_sha256'] != row['outcome']['case_sha256'] or
            [r['version'] for r in entry['stages']] != [r['version'] for r in outcome['stages']]):
        raise BudgetError('extension_comparison_pending')
    pair = {'entry': copy.deepcopy(entry), 'outcome': copy.deepcopy(outcome)}
    if pair not in row['comparisons']:
        parent = c.work / 'extension-snapshots' / str(number)
        target = parent / ('comparison-' + digest(pair))
        if not target.exists():
            staged = Path(tempfile.mkdtemp(prefix='.comparison-', dir=parent))
            try:
                for phase in ('entry', 'outcome'): _save_evidence(c, staged / phase, pair[phase])
                _sync_tree(staged)
                os.replace(staged, target)
                _sync_directory(parent)
            finally:
                if staged.exists(): shutil.rmtree(staged)
        for phase in ('entry', 'outcome'):
            if tree(target / phase) != pair[phase]['evidence']: raise BudgetError('extension_snapshot_changed')
        row['comparisons'].append(pair); _write(c, history)
