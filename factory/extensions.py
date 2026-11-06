"""Immutable extension snapshots and scientific progress comparison."""
import hashlib
import json
from pathlib import Path
from budget import BudgetError
from diagnosis import _sha

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
