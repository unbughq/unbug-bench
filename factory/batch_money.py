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


def check_manifest(record):
    try:
        if record['schema'] != 1 or type(record['schema']) is not int: raise ValueError()
        if not re.fullmatch('[a-z0-9-]+', record['id']): raise ValueError()
        if amount(record['money_limit_usd']) <= 0: raise ValueError()
        deadline(record['batch_deadline'])
        jobs = record['jobs']
        if not isinstance(jobs, dict) or not jobs: raise ValueError()
        for key in ('max_concurrency', 'target_slots'):
            if type(record[key]) is not int or not 1 <= record[key] <= len(jobs): raise ValueError()
        if not re.fullmatch('age1[0-9a-z]{58}', record['restore_recipient']): raise ValueError()
        if 'replacement_policy' in record:
            replacement = record['replacement_policy']
            if (not isinstance(replacement, dict) or set(replacement) != {'schema', 'enabled'} or
                    type(replacement['schema']) is not int or replacement['schema'] != 1 or
                    type(replacement['enabled']) is not bool): raise ValueError()
        for name, job in jobs.items():
            if (not re.fullmatch('[a-z0-9-]+', name) or re.search(r'-r[0-9]+$', name) or job['mode'] != 'batch' or
                    job['case'] != 'case-' + record['id'] + '-' + name or
                    type(job['max_calls']) is not int or job['max_calls'] <= 0 or
                    amount(job['requested_total_usd']) <= 0 or 'max_cost' in job):
                raise ValueError()
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
                record['id'], name, record['jobs'][name]['case'], record['batch_deadline']):
            raise ValueError()
        if amount(value['committed_total_usd']) > amount(record['money_limit_usd']): raise ValueError()
        return value
    except (KeyError, TypeError, ValueError, AttributeError):
        raise MoneyWait('money_wait') from None


@contextmanager
def locked(home, batch):
    directory = home / 'batches' / batch
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink(): raise MoneyWait('money_wait')
    with (directory / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield directory


def authorize(policy, name, source_generation, root, home, *, now=None):
    """Issue once for a fresh job, or return an identical already-issued channel.

    Source changes deliberately refuse until the generation/retirement verifier
    exists. A persisted grant is retained even if projection/delivery later fails.
    """
    record = manifest(policy, root)
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
