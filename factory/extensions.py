"""One-round extension histories, immutable case snapshots and versioned progress.

Admission consumes an already reserved writer lease, never a model's permission
or a round allowance. All private state lives outside current gate results.
"""
import copy
import errno
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
    except (ValueError, FileNotFoundError): raise BudgetError('extension_history_invalid') from None
    if not isinstance(history, list) or len(history) > LIMIT: raise BudgetError('extension_history_invalid')
    operations, diagnoses = set(), set()
    for number, row in enumerate(history, 1):
        if (not isinstance(row, dict) or set(row) != {'schema_version', 'extension_id',
                'writer_operation_id', 'exhaustion_id', 'round', 'entry', 'outcome', 'comparisons'} or
                type(row['schema_version']) is not int or row['schema_version'] != 1 or
                type(row['extension_id']) is not int or row['extension_id'] != number or
                not _uuid4(row['writer_operation_id']) or type(row['round']) is not int or row['round'] < 1 or
                not _uuid4(row['exhaustion_id']) or row['exhaustion_id'] in diagnoses or
                row['writer_operation_id'] in operations or
                (number > 1 and row['round'] != history[number - 2]['round'] + 1) or
                not isinstance(row['comparisons'], list) or (number < len(history) and row['outcome'] is None)):
            raise BudgetError('extension_history_invalid')
        operations.add(row['writer_operation_id']); diagnoses.add(row['exhaustion_id'])
        # The private round cannot be relabelled without its retained operation.
        try:
            reservations = json.loads(c.ledger.read_text()).get('invocation_reservations', {})
            if not any(r['operation_id'] == row['writer_operation_id'] and
                       r['call_name'] == 'builder-' + str(row['round']) for r in reservations.values()):
                raise ValueError()
        except (FileNotFoundError, ValueError, KeyError, TypeError, AttributeError):
            raise BudgetError('extension_history_invalid') from None
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
    count = c.card.get('builder_rounds', 0)
    if type(count) is not int or count < 0: raise BudgetError('extension_history_invalid')
    if history:
        last = history[-1]
        allowed = (last['round'] - 1, last['round']) if last['outcome'] is None else (last['round'],)
        if count not in allowed: raise BudgetError('extension_history_invalid')
    observed = c.card.get('extension_history', [])
    if extension_history({'extension_history': observed}) is None: raise BudgetError('extension_history_invalid')
    if observed != projected:
        # Only the immediately previous public view can lag a durable write.
        previous = copy.deepcopy(projected)
        if not history: raise BudgetError('extension_history_invalid')
        if history[-1]['outcome'] is None:
            previous.pop()  # Admission was committed before public publication.
        else:
            previous[-1]['outcome_sha256'] = None  # Completed outcome was committed.
        if observed != previous: raise BudgetError('extension_history_invalid')
    if history and history[-1]['outcome'] is None:
        state = _state(c.card, projected)
        if (not state or state['status'] != 'completed' or state['outcome'] != 'close_to_passing'
                or state['exhaustion_id'] != history[-1]['exhaustion_id']):
            raise BudgetError('extension_history_invalid')
    c.card['extension_history'] = projected
    return history


def _verify_case(c, number, phase, snapshot):
    path = c.work / 'extension-snapshots' / str(number) / phase / 'case'
    if not path.is_dir() or path.is_symlink() or digest(tree(path)) != snapshot['case_sha256']:
        raise BudgetError('extension_snapshot_changed')
    retained = path.parent / 'evidence'
    if tree(retained) != snapshot['evidence']: raise BudgetError('extension_snapshot_changed')


def _save_case(c, number, phase, snapshot, *, evidence_root=None):
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
        _save_evidence(evidence_root if evidence_root is not None else c.work, staged / 'evidence', snapshot)
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


def _save_evidence(root, destination, snapshot):
    root = Path(root)
    for name, expected in snapshot['evidence'].items():
        source = root / name
        if any(p.is_symlink() for p in (source, *source.parents) if p.is_relative_to(root)):
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


def writer_continuation(c, receipt, name):
    """Bind a pending writer retry to its admitted extension, never a new round."""
    from run import provider_continuation
    row = active(c)
    if row is None and 'extension_id' not in receipt: return False
    if (row is None or type(receipt.get('schema_version')) is not int or
            receipt['schema_version'] != 2 or receipt.get('phase') != 'pending' or
            receipt.get('actor') != 'writer' or type(receipt.get('extension_id')) is not int or
            receipt['extension_id'] != row['extension_id'] or type(receipt.get('round')) is not int or
            receipt['round'] != row['round'] or receipt.get('operation_id') != row['writer_operation_id'] or
            name != 'builder-' + str(row['round'])):
        raise BudgetError('extension_reservation_mismatch')
    lease, invocation = receipt.get('lease_id'), receipt.get('invocation_id')
    if isinstance(lease, str) and isinstance(invocation, str):
        reservation = json.loads(c.ledger.read_text()).get('invocation_reservations', {}).get(lease, {})
        if (reservation.get('operation_id') == row['writer_operation_id'] and
                reservation.get('call_name') == name and reservation.get('invocation_id') == invocation):
            return True
    elif lease is None and invocation is None and provider_continuation(c, receipt, 'writer'):
        return True
    raise BudgetError('extension_reservation_mismatch')


def comparison_pair(row, versions):
    """One selection rule for comparison and admission; never reroll a score."""
    def matches(pair):
        return pair['outcome'] is not None and all(
            [r['version'] for r in pair[phase]['stages']] == versions
            for phase in ('entry', 'outcome'))
    matching = [pair for pair in row['comparisons'] if matches(pair)]
    original = {'entry': row['entry'], 'outcome': row['outcome']}
    if not matching and matches(original):
        matching = [original]
    return next((pair for pair in matching if progress(pair['entry'], pair['outcome']) != 'pending'),
                matching[-1] if matching else None)


def propose(c, snapshot):
    """Check eligibility before admission without consuming an extension ID.

    The owning runner must compare completed history first. This state helper
    verifies retained bytes, not the scientific validity of opaque old receipts.
    """
    import job_authority
    job_authority.for_case(c)
    validate_snapshot(snapshot)
    history = read(c)
    state = _state(c.card, public(history))
    if not state or state['status'] != 'completed' or state['outcome'] != 'close_to_passing':
        raise BudgetError('extension_diagnosis_required')
    if history and history[-1]['outcome'] is None: raise BudgetError('extension_already_active')
    if len(history) >= LIMIT: raise BudgetError('retired_extension_limit')
    if any(row['exhaustion_id'] == state['exhaustion_id'] for row in history):
        raise BudgetError('extension_diagnosis_already_used')
    if any(row['status'] == 'pending' for row in snapshot['stages']):
        raise BudgetError('extension_execution_pending')
    if snapshot['stages'][0]['status'] != 'pass': raise BudgetError('retired_no_progress')
    if history:
        prior = history[-1]
        versions = [r['version'] for r in snapshot['stages']]
        pair = comparison_pair(prior, versions)
        result = progress(pair['entry'], pair['outcome']) if pair else 'pending'
        if result == 'pending': raise BudgetError('extension_comparison_pending')
        if result != 'progress': raise BudgetError('retired_no_progress')
        # A later checkpoint may change lineage, not the case/evidence compared.
        if any(snapshot[key] != pair['outcome'][key]
               for key in ('case_sha256', 'stages', 'frontier', 'evidence')):
            raise BudgetError('extension_comparison_pending')
    return {'extension_id': len(history) + 1, 'round': c.card.get('builder_rounds', 0) + 1,
            'entry': copy.deepcopy(snapshot), 'exhaustion_id': state['exhaustion_id']}


def _entry_evidence_root(c, history, snapshot):
    """Resolve only verified retained outcomes, never a path from a proposal."""
    if history and history[-1]['outcome'] is not None:
        row = history[-1]
        parent = c.work / 'extension-snapshots' / str(row['extension_id'])
        # This locates byte-identical evidence for the already-selected outcome;
        # reverse location order cannot select a different scientific verdict.
        candidates = [(pair['outcome'], parent / ('comparison-' + digest(pair)) / 'outcome')
                      for pair in reversed(row['comparisons'])]
        candidates.append((row['outcome'], parent / 'outcome' / 'evidence'))
        for outcome, root in candidates:
            if all(snapshot[key] == outcome[key] for key in ('case_sha256', 'stages', 'frontier', 'evidence')):
                return root
    return c.work


def verify_proposal(c, proposal):
    """Verify a fresh proposal and current bytes without publishing admission."""
    import job_authority
    from diagnosis import _input_bytes
    if (not isinstance(proposal, dict) or set(proposal) != {
            'extension_id', 'round', 'entry', 'exhaustion_id'} or
            type(proposal['extension_id']) is not int or type(proposal['round']) is not int or
            proposal['extension_id'] < 1 or proposal['round'] < 1):
        raise BudgetError('extension_reservation_mismatch')
    if propose(c, proposal['entry']) != proposal:
        raise BudgetError('extension_reservation_mismatch')
    entry = proposal['entry']
    if (entry['source_generation'] != job_authority.for_case(c).source_generation or
            entry['case_sha256'] != digest(tree(c.case))):
        raise BudgetError('extension_snapshot_changed')
    root = _entry_evidence_root(c, read(c), entry)
    for name, expected in entry['evidence'].items():
        try:
            data = _input_bytes(root / name, root)
        except (FileNotFoundError, ValueError):
            raise BudgetError('extension_snapshot_changed') from None
        except OSError as error:
            if error.errno in (errno.ELOOP, errno.ENOTDIR, errno.ENXIO, errno.EISDIR):
                raise BudgetError('extension_snapshot_changed') from None
            raise
        if hashlib.sha256(data).hexdigest() != expected:
            raise BudgetError('extension_snapshot_changed')


def admit(c, proposal, lease, operation_id):
    """Append entry only after the writer lease AND its money reservation exist."""
    import job_authority
    job_authority.for_case(c)
    history = read(c)
    if history and history[-1]['outcome'] is None:
        row = history[-1]
        if (row['extension_id'], row['writer_operation_id'], row['round'], row['entry'], row['exhaustion_id']) != (
                proposal['extension_id'], operation_id, proposal['round'], proposal['entry'], proposal['exhaustion_id']):
            raise BudgetError('extension_reservation_mismatch')
        return row
    if propose(c, proposal['entry']) != proposal: raise BudgetError('extension_reservation_mismatch')
    if any(row['writer_operation_id'] == operation_id for row in history):
        raise BudgetError('extension_reservation_mismatch')
    ledger = json.loads(c.ledger.read_text())
    reserved = ledger.get('invocation_reservations', {}).get(lease.lease_id, {})
    if (not _uuid4(operation_id) or reserved.get('state') != 'pending' or
            reserved.get('operation_id') != operation_id or
            reserved.get('call_name') != 'builder-' + str(proposal['round'])):
        raise BudgetError('extension_reservation_missing')
    _save_case(c, proposal['extension_id'], 'entry', proposal['entry'],
               evidence_root=_entry_evidence_root(c, history, proposal['entry']))
    row = dict(schema_version=1, extension_id=proposal['extension_id'], writer_operation_id=operation_id,
               exhaustion_id=proposal['exhaustion_id'], round=proposal['round'],
               entry=proposal['entry'], outcome=None, comparisons=[])
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


def retain_comparison(c, number, entry, outcome, *, roots=None):
    """Retain proofs from isolated roots without staging them in live gate work."""
    roots = roots if roots is not None else {phase: c.work for phase in ("entry", "outcome")}
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
                for phase in ('entry', 'outcome'): _save_evidence(roots[phase], staged / phase, pair[phase])
                _sync_tree(staged)
                os.replace(staged, target)
                _sync_directory(parent)
            finally:
                if staged.exists(): shutil.rmtree(staged)
        for phase in ('entry', 'outcome'):
            if tree(target / phase) != pair[phase]['evidence']: raise BudgetError('extension_snapshot_changed')
        row['comparisons'].append(pair); _write(c, history)
