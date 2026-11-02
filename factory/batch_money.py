"""Manifest-bound cumulative job authority. No usage booking or source advancement."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from registry import atomic_json


class MoneyWait(ValueError):
    """No authenticated authority; caller queues without starting a worker."""


def amount(value):
    """Exact integer nanodollars; channel encoding remains decimal USD to 9 places."""
    if not isinstance(value, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.[0-9]{9}', value):
        raise MoneyWait('money_wait')
    return int(value.replace('.', ''))


def deadline(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.utcoffset() != timedelta(0): raise ValueError()
        return stamp.timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise MoneyWait('money_wait') from None


def check_manifest(record, *, _ancestors=True):
    try:
        if record['schema'] != 1 or type(record['schema']) is not int: raise ValueError()
        if not re.fullmatch('[a-z0-9-]+', record['id']): raise ValueError()
        if amount(record['money_limit_usd']) <= 0: raise ValueError()
        deadline(record['batch_deadline'])
        jobs = record['jobs']
        if not isinstance(jobs, dict) or not jobs: raise ValueError()
        for key in ('max_concurrency', 'target_slots'):
            if type(record[key]) is not int or record[key] < 1: raise ValueError()
        if not re.fullmatch('age1[0-9a-z]{58}', record['restore_recipient']): raise ValueError()
        if 'replacement_policy' in record:
            replacement = record['replacement_policy']
            if (not isinstance(replacement, dict) or set(replacement) != {'schema', 'enabled'} or
                    type(replacement['schema']) is not int or replacement['schema'] != 1 or
                    type(replacement['enabled']) is not bool): raise ValueError()
        for name, job in jobs.items():
            if (not re.fullmatch('[a-z0-9-]+', name) or re.search(r'-r[0-9]+$', name) or job['mode'] != 'batch' or
                    job['case'] != record.get('carry_from', {}).get('jobs', {}).get(name, {}).get('case', 'case-' + record['id'] + '-' + name) or
                    ('max_calls' in job and (type(job['max_calls']) is not int or job['max_calls'] <= 0)) or
                    amount(job['requested_total_usd']) <= 0 or 'max_cost' in job):
                raise ValueError()
        if 'practice_admission' in record:
            practice = record['practice_admission']
            if (not isinstance(practice, dict) or set(practice) != {'schema', 'jobs'} or
                    type(practice['schema']) is not int or practice['schema'] != 1 or
                    not isinstance(practice['jobs'], dict) or not jobs.keys() <= practice['jobs'].keys()):
                raise ValueError()
            total = 0
            for name, allocation in practice['jobs'].items():
                if name not in jobs and not (isinstance(name, str) and name.endswith('-r1') and
                        name[:-3] in jobs and record.get('replacement_policy', {}).get('enabled')):
                    raise ValueError()
                if not isinstance(allocation, dict) or set(allocation) != {'baseline_usd', 'incremental_usd'}:
                    raise ValueError()
                baseline = amount(allocation['baseline_usd'])
                incremental = amount(allocation['incremental_usd'])
                if incremental <= 0 or ('carry_from' not in record and baseline): raise ValueError()
                total += baseline + incremental
            if total > amount(record['money_limit_usd']): raise ValueError()
        if 'carry_from' in record and _ancestors:
            from batch_transfer import check
            check(record)
        return record
    except (KeyError, TypeError, ValueError):
        raise MoneyWait('money_wait') from None


def manifest(policy, root):
    """The release authenticates both the host code and the tracked manifest bytes."""
    from batch import verify
    try:
        batch = policy['batch']
        directory = Path(batch['release'])
        verify(directory, batch['sha256'], root)
        relative = 'factory/batches/' + batch['id'] + '.json'
        if batch['manifest_path'] != relative: raise ValueError()
        path = root / relative
        raw = path.read_bytes()
        if path.is_symlink() or hashlib.sha256(raw).hexdigest() != batch['manifest_sha256']:
            raise ValueError()
        source = json.loads((directory / 'source-manifest.json').read_text())
        if source['files'][relative] != batch['manifest_sha256']: raise ValueError()
        record = check_manifest(json.loads(raw))
        if (record['id'] != batch['id'] or record['jobs'] != policy['jobs'] or
                record['max_concurrency'] != batch['max_concurrency'] or
                record['restore_recipient'] != (root / 'factory/control-recipient.txt').read_text().strip()):
            raise ValueError()
        return record
    except (OSError, KeyError, TypeError, ValueError):
        raise MoneyWait('money_wait') from None


def channel(value, record, name):
    fields = {'schema', 'batch', 'job', 'case', 'reservation_id', 'revision',
              'source_generation', 'committed_total_usd', 'batch_deadline'}
    try:
        if set(value) != fields or type(value['schema']) is not int or value['schema'] != 1:
            raise ValueError()
        identity = uuid.UUID(value['reservation_id'])
        if identity.version != 4 or str(identity) != value['reservation_id']: raise ValueError()
        if type(value['revision']) is not int or value['revision'] < 1: raise ValueError()
        source = value['source_generation']
        if source is not None and not re.fullmatch('[0-9a-f]{64}', source): raise ValueError()
        if (value['batch'], value['job'], value['case'], value['batch_deadline']) != (
                record['id'], name, resolved(record, name)['case'], record['batch_deadline']):
            raise ValueError()
        if amount(value['committed_total_usd']) > allocation_cap(record, name): raise ValueError()
        return value
    except (KeyError, TypeError, ValueError, AttributeError):
        raise MoneyWait('money_wait') from None


def allocation_cap(record, name):
    """Manifest-authenticated lifetime ceiling; no allowance is inferred from a parent."""
    if 'practice_admission' not in record: return amount(record['money_limit_usd'])
    allocation = record['practice_admission']['jobs'].get(name)
    if allocation is None: raise MoneyWait('money_wait')
    return amount(allocation['baseline_usd']) + amount(allocation['incremental_usd'])


def resolved(record, name):
    from batch_service import resolve_job
    return resolve_job(record, name)


@contextmanager
def locked(home, batch, *, read_export=False):
    directory = home / 'batches' / batch
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink(): raise MoneyWait('money_wait')
    with (directory / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not read_export and ((directory / 'export.json').exists() or (directory / 'export.json').is_symlink()):
            raise MoneyWait('batch_exported')
        yield directory


def authorize(policy, name, source_generation, root, home, *, now=None):
    """Issue once for a fresh job, or return an identical already-issued channel.

    Source changes deliberately refuse until the generation/retirement verifier
    exists. A persisted grant is retained even if projection/delivery later fails.
    """
    record = manifest(policy, root)
    if 'practice_admission' in record or 'carry_from' in record or re.search(r'-r[0-9]+$', name):
        raise MoneyWait('money_wait')
    if deadline(record['batch_deadline']) <= (time.time() if now is None else now):
        raise MoneyWait('retired_batch_bound')
    if name not in record['jobs']: raise MoneyWait('money_wait')
    with locked(home, record['id']) as directory:
        path = directory / 'money.json'
        state = json.loads(path.read_text()) if path.exists() else {
            'schema': 1, 'batch': record['id'], 'manifest_sha256': policy['batch']['manifest_sha256'],
            'money_limit_usd': record['money_limit_usd'], 'batch_deadline': record['batch_deadline'], 'jobs': {}}
        if (state['schema'] != 1 or state['batch'] != record['id'] or
                state['manifest_sha256'] != policy['batch']['manifest_sha256'] or
                state['money_limit_usd'] != record['money_limit_usd'] or
                state['batch_deadline'] != record['batch_deadline']):
            raise MoneyWait('money_wait')
        total = 0
        for job, row in state['jobs'].items():
            authority = channel(row['authority'], record, job)
            total += max(amount(authority['committed_total_usd']), amount(row['collected_total_usd']))
        if total > amount(record['money_limit_usd']): raise MoneyWait('money_wait')
        if name in state['jobs']:
            result = state['jobs'][name]['authority']
            if result['source_generation'] != source_generation: raise MoneyWait('money_wait')
        else:
            if source_generation is not None: raise MoneyWait('money_wait')
            wanted = record['jobs'][name]['requested_total_usd']
            if total + amount(wanted) > amount(record['money_limit_usd']): raise MoneyWait('money_wait')
            result = dict(schema=1, batch=record['id'], job=name, case=record['jobs'][name]['case'],
                          reservation_id=str(uuid.uuid4()), revision=1, source_generation=None,
                          committed_total_usd=wanted, batch_deadline=record['batch_deadline'])
            state['jobs'][name] = dict(authority=result, collected_total_usd='0.000000000')
        atomic_json(path, state)  # Authoritative first; replay repairs every projection.
        projections = home / 'batch-money' / record['id'] / 'jobs'
        projections.mkdir(mode=0o700, parents=True, exist_ok=True)
        for job, row in state['jobs'].items():
            atomic_json(projections / (job + '.json'), row['authority'])
        return dict(result)


def configuration(policy, name, authority, home):
    """Freeze public launch data. Caller has already validated manifest/authority."""
    batch = policy['batch']
    value = dict(schema=1, batch_id=authority['batch'], job_id=name, case_id=authority['case'],
                 batch_deadline=authority['batch_deadline'], source_generation=authority['source_generation'],
                 batch_release_sha256=batch['sha256'], manifest_sha256=batch['manifest_sha256'],
                 job_money=dict(authority))
    raw = json.dumps(value, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    directory = home / 'batches' / authority['batch'] / 'configs'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / (digest + '.json')
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw: raise MoneyWait('money_wait')
    else:
        atomic_json(path, value)
    return path, digest


# Schema2 is used only by the gated holder integration. Legacy authorize above
# deliberately retains its schema1 behavior; no implicit migration is allowed.
ACCOUNTING_ERRORS = {'invalid_accounting_input', 'accounting_api_refused',
                     'malformed_reconciliation', 'unsupported_decrease', 'uncovered_total'}


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def previous_check(value):
    if not isinstance(value, dict) or set(value) != {'total_usd', 'estimated'}:
        raise MoneyWait('money_wait')
    if value['total_usd'] is not None: amount(value['total_usd'])
    if not isinstance(value['estimated'], dict): raise MoneyWait('money_wait')
    for identity, gap in value['estimated'].items():
        parsed = uuid.UUID(identity)
        if parsed.version != 4 or str(parsed) != identity: raise MoneyWait('money_wait')
        amount(gap)


def retirement_check(value):
    if value is None: return
    if (not isinstance(value, dict) or set(value) != {'worker_id', 'request_sha256', 'completion_sha256'}
            or not isinstance(value['worker_id'], str)
            or not re.fullmatch('[A-Za-z0-9_-]+', value['worker_id'])
            or not _sha(value['request_sha256']) or not _sha(value['completion_sha256'])):
        raise MoneyWait('money_wait')


def load_locked(directory, record, manifest_sha):
    from batch_service import _json
    path = directory / 'money.json'
    header = dict(schema=2, batch=record['id'], manifest_sha256=manifest_sha,
                  money_limit_usd=record['money_limit_usd'], batch_deadline=record['batch_deadline'])
    if not path.exists() and not path.is_symlink(): return dict(**header, jobs={}, incidents={})
    try:
        state = _json(path)
        if (set(state) - {'carried_debit_usd'} != set(header) | {'jobs', 'incidents'} or
                any(state[k] != v for k, v in header.items()) or type(state['schema']) is not int or
                not isinstance(state['jobs'], dict) or not isinstance(state['incidents'], dict)):
            raise ValueError()
        if 'carry_from' in record:
            from batch_transfer import read_import
            receipt = read_import(directory, record)
            if (state.get('carried_debit_usd') != receipt['carried_debit_usd'] or
                    receipt['target_manifest_sha256'] != manifest_sha): raise ValueError()
        elif 'carried_debit_usd' in state: raise ValueError()
        for name, row in state['jobs'].items():
            if set(row) - {'imported'} != {'authority', 'held_usd', 'known_floor_usd', 'previous', 'acks', 'sources', 'overrun'}:
                raise ValueError()
            base = None
            if 'imported' in row:
                from batch_transfer import imported_row
                base = imported_row(directory, record, name, row)
            elif name in record.get('carry_from', {}).get('jobs', {}): raise ValueError()
            auth = channel(row['authority'], record, name)
            if base and (auth['reservation_id'] != base['authority']['reservation_id'] or
                         auth['committed_total_usd'] != base['authority']['committed_total_usd']): raise ValueError()
            if amount(row['held_usd']) != amount(auth['committed_total_usd']): raise ValueError()
            floor = amount(row['known_floor_usd']); previous_check(row['previous'])
            sources = row['sources']
            if (not isinstance(sources, list) or not sources or sources[0] != (base['generation'] if base else None) or
                    any(not _sha(v) for v in sources[1:]) or len(set(sources)) != len(sources) or
                    sources[-1] != auth['source_generation'] or not isinstance(row['acks'], dict) or
                    type(row['overrun']) is not bool or row['overrun'] != (floor > amount(row['held_usd']))):
                raise ValueError()
            known = [amount(base['known_floor_usd']) if base else 0]
            for generation, ack in row['acks'].items():
                if (not _sha(generation) or set(ack) != {'operation_id', 'generation', 'manifest_sha256',
                        'authority', 'previous', 'facts', 'retirement'} or ack['generation'] != generation or
                        not _sha(ack['manifest_sha256'])): raise ValueError()
                operation = uuid.UUID(ack['operation_id'])
                if operation.version != 5 or str(operation) != ack['operation_id']: raise ValueError()
                prior_auth = channel(ack['authority'], record, name)
                if (prior_auth['reservation_id'] != auth['reservation_id'] or
                        prior_auth['source_generation'] not in sources or
                        prior_auth['revision'] > auth['revision']): raise ValueError()
                previous_check(ack['previous'])
                facts = ack['facts']
                if set(facts) != {'total_usd', 'estimated', 'reconciled_decreases'}: raise ValueError()
                previous_check({k: facts[k] for k in ('total_usd', 'estimated')})
                if not isinstance(facts['reconciled_decreases'], list): raise ValueError()
                if facts['total_usd'] is not None: known.append(amount(facts['total_usd']))
                retirement_check(ack['retirement'])
            if floor != max(known): raise ValueError()
            for source in sources[1:]:
                if source not in row['acks']: raise ValueError()
        for key, incident in state['incidents'].items():
            if (set(incident) != {'operation_id', 'generation', 'manifest_sha256', 'reason'} or
                    key != incident['operation_id'] + '/' + incident['generation'] or
                    not _sha(incident['generation']) or not _sha(incident['manifest_sha256']) or
                    incident['reason'] not in ACCOUNTING_ERRORS): raise ValueError()
            operation = uuid.UUID(incident['operation_id'])
            if operation.version != 5 or str(operation) != incident['operation_id']: raise ValueError()
        return state
    except (KeyError, ValueError, TypeError, AttributeError):
        raise MoneyWait('money_wait') from None


def aggregate(state):
    return amount(state.get('carried_debit_usd', '0.000000000')) + sum(
        max(amount(r['held_usd']), amount(r['known_floor_usd'])) for r in state['jobs'].values())


def authorize_locked(state, record, name, source_generation):
    """Caller owns batch lock and persists the returned mutation before config."""
    if state['incidents'] or aggregate(state) > amount(record['money_limit_usd']): raise MoneyWait('money_wait')
    job = resolved(record, name)
    if name in state['jobs']:
        row = state['jobs'][name]
        if row['overrun'] or row['authority']['source_generation'] != source_generation:
            raise MoneyWait('money_wait')
        return dict(row['authority'])
    if source_generation is not None: raise MoneyWait('money_wait')
    if name in record.get('carry_from', {}).get('jobs', {}): raise MoneyWait('money_wait')
    wanted = job['template']['requested_total_usd']
    if 'practice_admission' in record:
        cap = allocation_cap(record, name)
        if amount(wanted) > cap: wanted = f'{cap // 10**9}.{cap % 10**9:09d}'
    if aggregate(state) + amount(wanted) > amount(record['money_limit_usd']): raise MoneyWait('money_wait')
    auth = dict(schema=1, batch=record['id'], job=name, case=job['case'],
                reservation_id=str(uuid.uuid4()), revision=1, source_generation=None,
                committed_total_usd=wanted, batch_deadline=record['batch_deadline'])
    state['jobs'][name] = dict(authority=auth, held_usd=wanted, known_floor_usd='0.000000000',
                              previous=dict(total_usd='0.000000000', estimated={}),
                              acks={}, sources=[None], overrun=False)
    return dict(auth)


def advance_locked(state, record, name, source_generation, ack):
    """Single source writer; holder already checked publication and retirement."""
    row = state['jobs'][name]
    if (state['incidents'] or row['overrun'] or aggregate(state) > amount(record['money_limit_usd']) or
            source_generation in row['sources'] or row['acks'].get(source_generation) != ack or
            ack['retirement'] is None or ack['authority'] != row['authority']):
        raise MoneyWait('money_wait')
    row['authority'] = {**row['authority'], 'source_generation': source_generation,
                        'revision': row['authority']['revision'] + (ack['facts']['total_usd'] is not None)}
    row['sources'].append(source_generation)
    return dict(row['authority'])


def project(home, record, state):
    directory = home / 'batch-money' / record['id'] / 'jobs'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, row in state['jobs'].items(): atomic_json(directory / (name + '.json'), row['authority'])
