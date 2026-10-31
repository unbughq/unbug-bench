"""Private causal attempt proofs; B alone owns resume and money authority."""
import contextlib
import contextvars
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid

import budget
import job_authority
from registry import atomic_json

_attempt = contextvars.ContextVar('factory_waste_attempt', default=None)
_FIELDS = ('lease_id', 'invocation_id', 'operation_id', 'call_name', 'parent_call_name')
_BASE = {'schema_version', 'attempt_id', 'case', 'stage', 'case_sha256', 'batch_id',
         'job_id', 'source_generation', 'batch_release_sha256', 'money_owner', 'reservations'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(path, base):
    from diagnosis import _input_bytes
    return json.loads(_input_bytes(Path(path), Path(base)))


def current_attempt():
    return _attempt.get()


class Attempt:
    def __init__(self, c, stage, case_sha256):
        job_authority.for_case(c)
        from diagnosis import _sha
        release = c.authenticated_job_config.get('batch_release_sha256')
        if not _sha(release) or release != c.args.batch_release_sha256:
            raise budget.BudgetError('money_wait')
        self.c, self.lock = c, threading.Lock()
        self.unpublishable, self.cleanup = False, []
        self.value = dict(schema_version=1, attempt_id=str(uuid.uuid4()), case=c.case_id,
            stage=stage, case_sha256=case_sha256, batch_id=c.batch_id, job_id=c.job_id,
            source_generation=c.source_generation,
            batch_release_sha256=c.authenticated_job_config['batch_release_sha256'],
            money_owner=copy.deepcopy(c.job_money))
        self.reservations = {}
        self.link = resume_scope(c, stage, case_sha256)

    def mark_unpublishable(self, reason):
        with self.lock:
            self.unpublishable = True
            self.cleanup.append(reason)

    def publish(self, error):
        from run_validity import InvalidInfra
        with self.lock:
            if self.unpublishable or (error is not None and not isinstance(error, InvalidInfra)): return
            if error is None and self.link is None: return
            value = {**self.value, 'reservations': [self.reservations[k] for k in sorted(self.reservations)]}
        if self.link:
            value.update(schema_version=2, replay_of=self.link['attempt_ids'],
                         resume_id=self.link['admission']['resume_id'],
                         outcome='invalid-infra' if error is not None else 'completed')
            folder = 'factory-replays'
        else:
            value.update(classification='invalid-infra', error_type=type(error).__name__)
            folder = 'factory-failures'
        path = Path(self.c.work) / folder / (value['attempt_id'] + '.json')
        path.parent.mkdir(exist_ok=True)
        atomic_json(path, value)
        descriptor = os.open(self.c.work, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
        if self.link:
            try: classify(self.c, self.link['finding'], self.link['admission'])
            except budget.BudgetError as pending:
                if str(pending) != 'money_wait': raise



@contextlib.contextmanager
def attempt(c, stage, case_sha256):
    # Non-factory execution has no B channel and cannot produce paid proof.
    from model_runtime import factory_job
    if not factory_job(c):
        yield None
        return
    scope = Attempt(c, stage, case_sha256)
    token = _attempt.set(scope)
    try:
        yield scope
    except BaseException as error:
        scope.publish(error)
        raise
    else:
        scope.publish(None)
    finally:
        _attempt.reset(token)


def record_reservation(c, row):
    scope = current_attempt()
    if scope is None: return
    if Path(c.ledger) != Path(scope.c.ledger) or c.case_id != scope.value['case']:
        raise budget.BudgetError('invalid_waste_attribution')
    value = {k: row.get(k) for k in _FIELDS}
    with scope.lock:
        previous = scope.reservations.get(value['lease_id'])
        if previous is not None and previous != value: raise budget.BudgetError('invalid_waste_attribution')
        scope.reservations[value['lease_id']] = value


def _owners(root):
    current = read(root / 'work/job-money.json', root)
    history_path = root / 'work/job-money-history.json'
    history = read(history_path, root) if history_path.exists() else {}
    if not isinstance(history, dict): raise ValueError('money history')
    owners = [current]
    for item in history.values():
        if not isinstance(item, dict) or set(item) != {'old', 'new', 'config_sha256', 'source_generation'}:
            raise ValueError('money history')
        owners.extend((item['old'], item['new']))
    return owners


def _proof(value, ledger, case, owners, *, replay=False):
    from diagnosis import _sha, _uuid4
    from run import GATES
    extra = {'replay_of', 'resume_id', 'outcome'} if replay else {'classification', 'error_type'}
    if (not isinstance(value, dict) or set(value) != _BASE | extra or
            type(value['schema_version']) is not int or value['schema_version'] != (2 if replay else 1) or
            not _uuid4(value['attempt_id']) or value['case'] != case or
            value['stage'] not in (*GATES, 'stress') or not _sha(value['case_sha256']) or
            not _sha(value['batch_release_sha256'])): raise ValueError('attempt shape')
    owner = value['money_owner']
    job_authority.read(owner, owner)
    if owner not in owners or (owner['case'], owner['batch'], owner['job'], owner['source_generation']) != (
            case, value['batch_id'], value['job_id'], value['source_generation']): raise ValueError('attempt owner')
    if replay:
        if (not _uuid4(value['resume_id']) or value['outcome'] not in ('completed', 'invalid-infra') or
                not isinstance(value['replay_of'], list) or not value['replay_of'] or
                value['replay_of'] != sorted(set(value['replay_of'])) or
                not all(_uuid4(i) for i in value['replay_of'])): raise ValueError('replay shape')
    elif value['classification'] != 'invalid-infra' or not isinstance(value['error_type'], str) or not value['error_type']:
        raise ValueError('failure shape')
    reservations = value['reservations']
    if not isinstance(reservations, list): raise ValueError('reservations')
    leases, operations = [], set()
    for reservation in reservations:
        if not isinstance(reservation, dict) or set(reservation) != set(_FIELDS): raise ValueError('reservation')
        lease = reservation['lease_id']
        if not _uuid4(lease): raise ValueError('lease')
        row = ledger['invocation_reservations'][lease]
        if lease != row['lease_id'] or reservation != {k: row.get(k) for k in _FIELDS}: raise ValueError('reservation identity')
        leases.append(lease); operations.add(row['operation_id'])
    if leases != sorted(set(leases)): raise ValueError('duplicate leases')
    return operations


def eligible(evidence_root, case, finding_id):
    root = Path(evidence_root)
    directory = root / 'work/factory-failures'
    if directory.is_symlink(): raise ValueError('unsafe proof directory')
    if not directory.exists(): return [], []
    if not directory.is_dir(): raise ValueError('proof directory')
    paths = sorted(directory.iterdir())
    if not paths: return [], []
    ledger, owners = read(root / 'ledger.json', root), _owners(root)
    # Validate monetary ownership before using it to exclude another finding.
    if budget.case_spending(ledger)['total_spent_usd'] is None:
        raise ValueError('unvalidated monetary ownership')
    owned = set()
    for record in ledger.get('infrastructure_waste', []):
        if record.get('kind') != 'factory_bug' or record.get('finding_id') != finding_id:
            owned.update(record.get('operation_ids', []))
    operations, receipts = set(), []
    for path in paths:
        if path.is_dir(): raise ValueError('nested proof directory')
        value = read(path, root)
        if path.name != value['attempt_id'] + '.json': raise ValueError('proof filename')
        selected = _proof(value, ledger, case, owners) - owned
        if value['money_owner'] == owners[0] and value['batch_release_sha256'] != read(root / 'card.json', root).get('batch_release_sha256'):
            raise ValueError('attempt release')
        if selected:
            operations.update(selected)
            from diagnosis import _input_bytes
            receipts.append(dict(path=path.relative_to(root).as_posix(),
                                 sha256=hashlib.sha256(_input_bytes(path, root)).hexdigest()))
    return sorted(operations), receipts


def _finding(c, admission):
    import diagnosis as d
    from job_authority import read as authority
    path = d._finding_path(c, admission['finding_id'])
    root = path.parent / 'inputs'
    raw = read(path, c.work)
    manifest = read(path.parent / 'input.json', c.work)
    if (manifest['case_id'] != c.case_id or manifest['exhaustion_id'] != admission['finding_id'] or
            manifest['generation'] != raw['diagnosis']['checkpoint_sha256'] or
            manifest['files'] != d._input_inventory(root)):
        raise budget.BudgetError('invalid_waste_attribution')
    card = read(root / 'card.json', root)
    bindings = d._resume_bindings(c)
    matched = [(owner, release) for owner, release in bindings if all(admission.get(k) == owner[v] for k, v in (
        ('case', 'case'), ('batch_id', 'batch'), ('job_id', 'job'), ('reservation_id', 'reservation_id'),
        ('source_generation', 'source_generation'))) and admission['batch_release_sha256'] == release]
    old = [(owner, release) for owner, release in bindings if owner['batch'] == raw['held_batch_id']
           and release == raw['held_release_sha256']]
    if not matched or not old: raise ValueError('resume binding')
    finding = d._read_factory_bug_finding(c, path, authority(old[0][0], old[0][0]), old[0][1],
        card['diagnosis_state'], raw['diagnosis']['checkpoint_sha256'], root)
    return finding, root, bindings


def resume_scope(c, stage, case_sha256):
    path = Path(c.work) / 'factory-bug-resumes.json'
    if not path.exists(): return None
    import diagnosis as d
    retained = read(path, c.work)
    candidate = retained[-1] if isinstance(retained, list) and retained else None
    history = d._factory_bug_history(c, admitted_replay=candidate)
    if not history: return None
    admission = history[-1]
    finding, root, _ = _finding(c, admission)
    attempts = []
    for proof in finding['failure_receipts']:
        value = read(root / proof['path'], root)
        if value['stage'] == stage and value['case_sha256'] == case_sha256:
            attempts.append(value['attempt_id'])
    if not attempts: return None
    return dict(finding=finding, admission=admission, attempt_ids=sorted(attempts))


def classify(c, finding, admission=None):
    try:
        return _classify(c, finding, admission)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise budget.BudgetError('invalid_waste_attribution') from None


def _classify(c, finding, admission=None):
    import diagnosis as d
    path = d._finding_path(c, finding['finding_id'])
    root = path.parent / 'inputs'
    operations, references = eligible(root, c.case_id, finding['finding_id'])
    if operations != finding['eligible_operation_ids'] or references != finding['failure_receipts']:
        raise budget.BudgetError('invalid_waste_attribution')
    if not operations: return
    frozen = read(root / 'ledger.json', root)
    proof_rows = {item['lease_id']: frozen['invocation_reservations'][item['lease_id']]
                  for ref in references for item in read(root / ref['path'], root)['reservations']}
    if admission is not None:
        validated, _, bindings = _finding(c, admission)
        if finding != validated: raise budget.BudgetError('invalid_waste_attribution')
        owners = [owner for owner, _ in bindings]
        replay_dir = Path(c.work) / 'factory-replays'
        if replay_dir.is_symlink(): raise ValueError('unsafe replay directory')
        ledger = read(c.ledger, c.ledger.parent)
        originals = {read(root / ref['path'], root)['attempt_id']: read(root / ref['path'], root)
                     for ref in finding['failure_receipts']}
        for proof in sorted(replay_dir.glob('*.json')):
            value = read(proof, c.work)
            replay_ops = _proof(value, ledger, c.case_id, owners, replay=True)
            if value['money_owner'] == c.job_money and value['batch_release_sha256'] != c.authenticated_job_config['batch_release_sha256']:
                raise budget.BudgetError('invalid_waste_attribution')
            if value['resume_id'] != admission['resume_id']: continue
            if (proof.name != value['attempt_id'] + '.json' or not set(value['replay_of']) <= originals.keys() or
                    any((value['stage'], value['case_sha256']) != (originals[i]['stage'], originals[i]['case_sha256'])
                        for i in value['replay_of'])): raise budget.BudgetError('invalid_waste_attribution')
            operations = sorted(set(operations) | replay_ops)
            for lease, row in ledger['invocation_reservations'].items():
                if row['operation_id'] in replay_ops: proof_rows[lease] = row
    ledger = read(c.ledger, c.ledger.parent)
    rows = ledger.get('invocation_reservations', {})
    if any(row['operation_id'] in operations and lease not in proof_rows for lease, row in rows.items()):
        raise budget.BudgetError('invalid_waste_attribution')
    for lease, row in proof_rows.items():
        if row['operation_id'] not in operations: continue
        live = rows.get(lease)
        if live is None or any(live.get(k) != row.get(k) for k in _FIELDS):
            raise budget.BudgetError('invalid_waste_attribution')
    settled = [op for op in operations if any(row['operation_id'] == op for row in rows.values()) and
               all(row['state'] == 'settled' and budget.usd(row['estimated_gap_usd']) == 0
                   for row in rows.values() if row['operation_id'] == op)]
    if settled:
        ids = sorted({i for row in rows.values() if row['operation_id'] in settled for i in row['event_ids']})
        events = {event['id']: event for event in ledger.get('events', [])}
        record = dict(schema_version=2, kind='factory_bug', id='factory-bug:' + finding['finding_id'],
            finding_id=finding['finding_id'], diagnosis_sha256=digest(finding['diagnosis']),
            resume_id=admission['resume_id'] if admission else None,
            resume_binding_sha256=digest(admission) if admission else None,
            operation_ids=settled, event_ids=ids,
            infrastructure_waste_usd=format(budget.usd(budget._waste_amount(events, ids)), '.9f'))
        budget.reclassify_factory_bug(c.ledger, record)
    if admission is not None and len(settled) != len(operations): raise budget.BudgetError('money_wait')


def refresh_replays(c):
    try:
        return _refresh_replays(c)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise budget.BudgetError('invalid_waste_attribution') from None


def _refresh_replays(c):
    """Before B clears a hold, settle replay proof belonging to prior admissions."""
    import diagnosis as d
    directory = Path(c.work) / 'factory-replays'
    if not directory.exists(): return
    if directory.is_symlink(): raise budget.BudgetError('invalid_waste_attribution')
    resumes = {read(proof, c.work)['resume_id'] for proof in directory.glob('*.json')}
    path = Path(c.work) / 'factory-bug-resumes.json'
    history = read(path, c.work)
    history = d._factory_bug_history(c, admitted_replay=history[-1] if history else None)
    if not resumes <= {row['resume_id'] for row in history}: raise budget.BudgetError('invalid_waste_attribution')
    for admission in history:
        if admission['resume_id'] not in resumes: continue
        finding, _, _ = _finding(c, admission)
        classify(c, finding, admission)
