"""Gated host operation/collection composition. No diagnosis or live activation."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.request
import uuid

import batch_money as money
import batch_service as service
from batch_accounting import collection_facts
from job_config import read_file
from registry import atomic_json
from transfer import digest

HOLDER_ENABLED = False
TEMPFAIL = 75  # Dispatch exit: transient wait, the operation stays pending.
RETRY_LIMIT = 5  # Resume/publish respawns before a terminal incident.
FIELDS = {'operation_id', 'launch_id', 'job', 'case', 'source_generation',
          'release_sha256', 'config_sha256', 'authority', 'state', 'pending_since',
          'worker_id', 'dispatch_started', 'dispatch_exit', 'output_generation',
          'retirement', 'launch', 'incident', 'failures'}
INCIDENTS = (None, 'creation_unknown', 'accounting_refused', 'legacy_retire',
             'preflight_refused', 'resume_failed', 'publication_failed')


def active(policy, root):
    import practice
    return HOLDER_ENABLED or practice.active(policy, root)


def enabled(policy, root):
    if not active(policy, root): raise ValueError('request_refused')


def operation_id(policy, job, source):
    name = json.dumps([policy['batch']['id'], job, source, policy['batch']['sha256']], separators=(',', ':'))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def validate_operations(operations, record):
    """Shared journal grammar; no filesystem observation or lifecycle inference."""
    try:
        if not isinstance(operations, dict): raise ValueError()
        live = set()
        for identity, op in operations.items():
            parsed = uuid.UUID(identity)
            if parsed.version != 5 or str(parsed) != identity or set(op) != FIELDS: raise ValueError()
            if (op['operation_id'] != identity or op['case'] != service.resolve_job(record, op['job'])['case'] or
                    not re.fullmatch('[0-9a-f]{32}', op['launch_id']) or
                    not money._sha(op['release_sha256']) or not money._sha(op['config_sha256'])): raise ValueError()
            source = op['source_generation']
            if source is not None and not money._sha(source): raise ValueError()
            if op['output_generation'] is not None and not money._sha(op['output_generation']): raise ValueError()
            name = json.dumps([record['id'], op['job'], source, op['release_sha256']], separators=(',', ':'))
            if str(uuid.uuid5(uuid.NAMESPACE_URL, name)) != identity: raise ValueError()
            auth = money.channel(op['authority'], record, op['job'])
            if auth['source_generation'] != source: raise ValueError()
            money.deadline(op['pending_since'])
            if (type(op['dispatch_started']) is not bool or
                    (op['dispatch_exit'] is not None and type(op['dispatch_exit']) is not int) or
                    type(op['failures']) is not int or op['failures'] < 0 or
                    op['state'] not in ('pending', 'launched', 'failed') or
                    op['incident'] not in INCIDENTS):
                raise ValueError()
            worker = op['worker_id']
            if worker is not None and (not isinstance(worker, str) or not re.fullmatch('[A-Za-z0-9_-]+', worker)):
                raise ValueError()
            money.retirement_check(op['retirement'])
            if op['retirement'] is not None and op['retirement']['worker_id'] != worker: raise ValueError()
            if op['state'] == 'launched':
                if worker is None: raise ValueError()
            elif worker is not None or op['output_generation'] is not None or op['retirement'] is not None:
                raise ValueError()
            launch = op['launch']
            if launch is not None:
                from control_resume import ENVIRONMENT
                if (set(launch) != {'argv', 'environment'} or not isinstance(launch['argv'], list) or
                        any(not isinstance(a, str) for a in launch['argv']) or
                        not isinstance(launch['environment'], dict) or
                        not set(launch['environment']) <= set(ENVIRONMENT) or
                        any(not isinstance(v, str) for v in launch['environment'].values()) or
                        launch['environment'].get('UNBUG_BATCH_OPERATION') != identity): raise ValueError()
            if op['dispatch_started'] and launch is None: raise ValueError()
            if op['state'] in ('pending', 'launched') and op['retirement'] is None:
                if op['case'] in live: raise ValueError()
                live.add(op['case'])
        return operations
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError('invalid batch operations') from None


def _operations(directory, record, policy):
    path = directory / 'reservations.json'
    if not path.exists() and not path.is_symlink(): return {}
    state = service._json(path)
    if (set(state) != {'schema', 'batch', 'manifest_sha256', 'operations'} or
            type(state['schema']) is not int or state['schema'] != 1 or
            state['batch'] != record['id'] or state['manifest_sha256'] != policy['batch']['manifest_sha256']):
        raise ValueError('request_refused')
    ops = validate_operations(state['operations'], record)
    if any(op['release_sha256'] != policy['batch']['sha256'] for op in ops.values()):
        raise ValueError('request_refused')
    return ops


def _save(directory, record, policy, operations):
    validate_operations(operations, record)
    atomic_json(directory / 'reservations.json', dict(schema=1, batch=record['id'],
                manifest_sha256=policy['batch']['manifest_sha256'], operations=operations))
    state = service._load(directory, record, policy['batch']['manifest_sha256'])
    state['operations'] = deepcopy(operations)
    atomic_json(directory / 'journal.json', state)


def _config(policy, home, op):
    path = home / 'batches' / policy['batch']['id'] / 'configs' / (op['config_sha256'] + '.json')
    value = read_file(path, op['config_sha256'], private=True)
    expected = dict(schema=1, batch_id=policy['batch']['id'], job_id=op['job'], case_id=op['case'],
                    batch_deadline=op['authority']['batch_deadline'], source_generation=op['source_generation'],
                    batch_release_sha256=op['release_sha256'], manifest_sha256=policy['batch']['manifest_sha256'],
                    job_money=op['authority'])
    if value != expected: raise ValueError('request_refused')
    return path


def _entry(directory, record, policy, case, generation):
    state = service._load(directory, record, policy['batch']['manifest_sha256'])
    entry = state['entries'][case + '/' + generation]
    card = service._snapshot(directory, entry, record, policy['batch']['sha256'])
    return entry, card


def _source(directory, record, policy, operations, state, name, generation):
    """Read-only predecessor proof common to pre- and post-advance checks."""
    row = state['jobs'][name]
    if row.get('imported', {}).get('generation') == generation:
        from batch_transfer import source
        ack, entry, card, _ = source(directory.parent.parent, record, name, generation)
        return ack, entry, card
    ack = row['acks'][generation]
    predecessor = operations[ack['operation_id']]
    if (predecessor['job'] != name or predecessor['output_generation'] != generation or
            predecessor['authority'] != ack['authority'] or predecessor['retirement'] is None or
            predecessor['retirement'] != ack['retirement']): raise ValueError('request_refused')
    pointer = service._json(directory / 'current' / (predecessor['case'] + '.json'))
    if pointer != dict(generation=generation, manifest_sha256=ack['manifest_sha256']):
        raise ValueError('request_refused')
    outbox = service._json(directory / 'outbox' / (predecessor['operation_id'] + '.json'))
    if outbox != dict(schema=1, operation_id=predecessor['operation_id'], generation=generation,
                      manifest_sha256=ack['manifest_sha256'], state='acknowledged'):
        raise ValueError('request_refused')
    entry, card = _entry(directory, record, policy, predecessor['case'], generation)
    if entry['manifest_sha256'] != ack['manifest_sha256'] or card.get('job_money') != ack['authority']:
        raise ValueError('request_refused')
    return ack, entry, card


def _post(directory, record, policy, home, operations, state, identity):
    if (directory / 'export.json').exists() or (directory / 'export.json').is_symlink():
        raise ValueError('batch_exported')
    op = operations[identity]
    if (state['incidents'] or money.aggregate(state) > money.amount(record['money_limit_usd']) or
            money.deadline(record['batch_deadline']) <= datetime.now(timezone.utc).timestamp()):
        raise money.MoneyWait('money_wait')
    row = state['jobs'][op['job']]
    if row['overrun'] or row['authority'] != op['authority'] or row['sources'][-1] != op['source_generation']:
        raise money.MoneyWait('money_wait')
    _config(policy, home, op)
    if op['source_generation'] is not None:
        ack, _, _ = _source(directory, record, policy, operations, state, op['job'], op['source_generation'])
        if row.get('imported', {}).get('generation') == op['source_generation']:
            if row['authority'] != row['imported']['authority'] or len(row['sources']) != 1: raise ValueError('request_refused')
        elif ack['authority']['source_generation'] != row['sources'][-2]: raise ValueError('request_refused')
    elif row['sources'] != [None]: raise ValueError('request_refused')
    return op


def empty_input(root, directory, case):
    """Empty progress must not reuse any saved case evidence."""
    from batch import sealed_directories
    from launch_manifest import collection_files
    paths = [directory / 'generations' / case, directory / 'current' / (case + '.json')]
    try: directories = sealed_directories(root)
    except (subprocess.SubprocessError, OSError): raise ValueError('request_refused') from None
    for sealed in directories:
        paths.extend(sealed / name for name in collection_files(case))
        paths.append(sealed / 'generations' / case)
    for path in paths:
        try: path.lstat()
        except FileNotFoundError: continue
        except OSError: raise ValueError('request_refused') from None
        raise ValueError('request_refused')


def _admit(directory, record, policy, root, ops, state, name, source_generation, provider_wait=False):
    """Shared decision; only supplied in-memory state changes. Caller owns lock."""
    import practice
    if record['id'] == practice.BATCH:
        if not practice.matches(record): raise ValueError('request_refused')
        practice.admission(record)
    resolved = service.resolve_job(record, name)
    carried = record.get('carry_from', {}).get('jobs', {})
    if name not in carried and any(re.fullmatch(re.escape(name) + r'-r[1-9][0-9]*', child) for child in carried):
        raise ValueError('template-only imported root')
    service._lineage(service._load(directory, record, policy['batch']['manifest_sha256']), record, name)
    if source_generation is not None and not money._sha(source_generation):
        raise ValueError('request_refused')
    if money.deadline(record['batch_deadline']) <= datetime.now(timezone.utc).timestamp():
        raise money.MoneyWait('retired_batch_bound')
    if provider_wait and source_generation is None: raise ValueError('request_refused')
    identity = operation_id(policy, name, source_generation)
    row = state['jobs'].get(name)
    if state['incidents'] or money.aggregate(state) > money.amount(record['money_limit_usd']):
        raise money.MoneyWait('money_wait')
    if 'practice_admission' in record:
        money.allocation_cap(record, name)  # Also refuses unlisted replacement generations.
        if source_generation is None:
            if money.amount(record['practice_admission']['jobs'][name]['baseline_usd']):
                raise money.MoneyWait('money_wait')
            if 'carry_from' in record and name not in carried:
                from batch_transfer import read_import
                receipt = read_import(directory, record)
                while receipt is not None:
                    if name in receipt['snapshot']['money']['jobs']: raise money.MoneyWait('money_wait')
                    receipt = receipt['snapshot']['prior_import']
    if identity in ops:
        if provider_wait: raise ValueError('request_refused')
        if row is None or row['authority']['source_generation'] != source_generation:
            raise ValueError('request_refused')
        return deepcopy(ops[identity]['authority'])
    if (sum(o['state'] in ('pending', 'launched') and o['retirement'] is None
            for o in ops.values()) >= record['max_concurrency'] or
            any(o['job'] == name and o['state'] in ('pending', 'launched') and o['retirement'] is None
                for o in ops.values())): raise money.MoneyWait('money_wait')
    if source_generation is not None:
        ack, _, card = _source(directory, record, policy, ops, state, name, source_generation)
        if provider_wait:
            if ops[ack['operation_id']]['incident'] is not None: raise ValueError('request_refused')
            _wait_due(card, record)
        if row['authority']['source_generation'] != source_generation:
            money.advance_locked(state, record, name, source_generation, ack)
        elif row.get('imported', {}).get('generation') == source_generation:
            if row['authority'] != row['imported']['authority'] or len(row['sources']) != 1:
                raise ValueError('request_refused')
        elif row['sources'][-2] != ack['authority']['source_generation']:
            raise ValueError('request_refused')
    else:
        empty_input(root, directory, resolved['case'])
    return money.authorize_locked(state, record, name, source_generation)


def reserve(policy, root, home, name, source_generation, *, provider_wait=False):
    enabled(policy, root)
    from batch_transfer import prepare
    prepare(policy, root, home)
    record = money.manifest(policy, root)
    identity = operation_id(policy, name, source_generation)
    with money.locked(home, record['id']) as directory:
        ops = _operations(directory, record, policy)
        state = money.load_locked(directory, record, policy['batch']['manifest_sha256'])
        authority = _admit(directory, record, policy, root, ops, state, name, source_generation, provider_wait)
        if identity in ops:
            _save(directory, record, policy, ops)  # repair journal after lost reply
            return deepcopy(ops[identity])
        atomic_json(directory / 'money.json', state)
        money.project(home, record, state)
        _, config_sha = money.configuration(policy, name, authority, home)
        op = dict(operation_id=identity, launch_id=uuid.uuid4().hex, job=name, case=authority['case'],
                  source_generation=source_generation, release_sha256=policy['batch']['sha256'],
                  config_sha256=config_sha, authority=authority, state='pending',
                  pending_since=datetime.now(timezone.utc).isoformat(), worker_id=None,
                  dispatch_started=False, dispatch_exit=None, output_generation=None,
                  retirement=None, launch=None, incident=None, failures=0)
        ops[identity] = op
        _save(directory, record, policy, ops)
        return deepcopy(op)


def reply(op):
    return {k: op[k] for k in ('operation_id', 'launch_id', 'state', 'worker_id')}


def lookup(policy, root, home, identity):
    enabled(policy, root); record = money.manifest(policy, root)
    directory = home / 'batches' / record['id']
    with service._regular(directory / 'lock') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        ops = _operations(directory, record, policy)
        if identity not in ops: raise ValueError('operation_unknown')
        return reply(ops[identity])


@contextmanager
def operation_lock(directory, identity):
    parsed = uuid.UUID(identity)
    if parsed.version != 5 or str(parsed) != identity: raise ValueError('request_refused')
    locks = directory / 'operations'; locks.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(locks / (identity + '.lock'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def record_exit(policy, root, home, identity, code):
    enabled(policy, root); record = money.manifest(policy, root)
    directory = home / 'batches' / record['id']
    try:
        with operation_lock(directory, identity), money.locked(home, record['id']):
            ops = _operations(directory, record, policy); op = ops[identity]
            if code == TEMPFAIL and not op['dispatch_started']: return
            op['dispatch_exit'] = code
            if op['state'] == 'pending' and not op['dispatch_started']:
                op.update(state='failed', incident='preflight_refused')
            _save(directory, record, policy, ops)
    except BlockingIOError:
        pass  # Another preflight owner is alive; this child's exit says nothing.


def record_child(policy, root, home, identity, action, code):
    """Count a reaped resume/publish child. Returns the wait multiplier (0 = none).

    Bounds the respawn: a child that did not finish its job increments a durable
    `failures`, and the holder waits 60 * 2**(failures-1) seconds before the next
    spawn. At RETRY_LIMIT it becomes a terminal incident that the scans skip.
    """
    enabled(policy, root); record = money.manifest(policy, root)
    directory = home / 'batches' / record['id']
    try:
        with operation_lock(directory, identity), money.locked(home, record['id']):
            ops = _operations(directory, record, policy); op = ops[identity]
            done = (home / 'launches' / op['launch_id'] / 'complete').exists() if action == 'resume' else code == 0
            if done:
                op['failures'] = 0; result = 0
            else:
                op['failures'] += 1
                if op['failures'] >= RETRY_LIMIT:
                    op['incident'] = 'resume_failed' if action == 'resume' else 'publication_failed'
                    result = 0
                else: result = op['failures']
            _save(directory, record, policy, ops)
            return result
    except BlockingIOError:
        return 1  # A live owner holds the operation; retry after the base wait, do not count this exit.


def _created(path, op):
    if service._json(path / 'launch.json') != op['launch']: raise ValueError('request_refused')
    workers = []
    for file in sorted(path.glob('new.*')):
        if not re.fullmatch(r'new\.[0-9]+', file.name): continue
        with service._regular(file) as stream:
            for line in stream:
                try: event = json.loads(line)
                except ValueError: continue
                if event.get('event') == 'created': workers.append(event.get('id'))
    with service._regular(path / 'ids') as stream: ids = stream.read().decode().split()
    if (len(workers) != 1 or not isinstance(workers[0], str) or
            not re.fullmatch('[A-Za-z0-9_-]+', workers[0]) or ids != workers):
        raise ValueError('creation_unknown')
    return workers[0]


def _retirement(root, path, worker):
    with service._regular(path / 'monitor.sh') as stream: lines = stream.read().decode().splitlines()
    values = [shlex.split(line.split('=', 1)[1]) for line in lines if line.startswith('spend_file=')]
    if len(values) != 1 or len(values[0]) != 1: raise ValueError('request_refused')
    spend = Path(values[0][0])
    if not spend.is_absolute() or not spend.resolve().is_relative_to((root / 'results/spend').resolve()):
        raise ValueError('request_refused')
    directory = spend.with_suffix('.deletions') / worker
    request, done = (service._json(directory / name) for name in ('deletion-request.json', 'deletion-completion.json'))
    # The real deletion guard saves all six keys on both receipts; keep the full check.
    keys = {'id', 'targetId', 'kind', 'status', 'stage', 'completedAt'}
    if (set(request) != keys or set(done) != keys or not isinstance(done['id'], str) or not done['id'] or
            request['id'] != done['id'] or request['targetId'] != worker or done['targetId'] != worker or
            request['kind'] != 'sandbox' or done['kind'] != 'sandbox' or
            done['status'] != 'completed' or done['stage'] != 'completed' or
            datetime.fromisoformat(done['completedAt'].replace('Z', '+00:00')).tzinfo is None):
        raise ValueError('request_refused')
    return dict(worker_id=worker, request_sha256=digest(directory / 'deletion-request.json'),
                completion_sha256=digest(directory / 'deletion-completion.json'))


def _reconcile_one(directory, root, home, op, state):
    path = home / 'launches' / op['launch_id']
    try: worker = _created(path, op)
    except (OSError, ValueError, KeyError, TypeError):
        if op['worker_id'] is not None: return  # Never forget ownership.
        if op['incident'] not in ('resume_failed', 'publication_failed'):
            op['incident'] = 'creation_unknown'
        # A free operation lock proves the dispatch child (which holds it until
        # launch.sh exits) is gone; no recorded exit is needed after a restart.
        # A busy operation or controller lock means a live owner: stay pending.
        try:
            with operation_lock(directory, op['operation_id']):
                if not path.exists():
                    path.mkdir(mode=0o700)  # Fence any late control_resume for this launch id.
                    op.update(state='failed', incident='preflight_refused'); return
                if service._json(path / 'launch.json') != op['launch']: return
                with service._regular(path / 'controller.lock') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # guard_new opens new.$serial before the creator. With both
                    # locks free and no creation record, guard_init may never have
                    # run, so a missing ids file is as safe as an empty one.
                    if list(path.glob('new.*')): return
                    try:
                        with service._regular(path / 'ids') as stream: ids = stream.read().strip()
                    except FileNotFoundError: ids = b''
                    if not ids:
                        op.update(state='failed', incident='preflight_refused')
        except (OSError, ValueError, KeyError): pass
        return
    if op['worker_id'] not in (None, worker): raise ValueError('request_refused')
    op.update(worker_id=worker, state='launched')
    if op['incident'] == 'creation_unknown': op['incident'] = None
    try: proof = _retirement(root, path, worker)
    except (OSError, ValueError, KeyError, TypeError, AttributeError): return
    if op['retirement'] not in (None, proof): raise ValueError('request_refused')
    for ack in state['jobs'][op['job']]['acks'].values():
        if ack['operation_id'] != op['operation_id']: continue
        if ack['retirement'] not in (None, proof): raise ValueError('request_refused')
        ack['retirement'] = proof
    atomic_json(directory / 'money.json', state)
    op['retirement'] = proof


def reconcile(policy, root, home):
    enabled(policy, root); record = money.manifest(policy, root)
    with money.locked(home, record['id']) as directory:
        ops = _operations(directory, record, policy)
        state = money.load_locked(directory, record, policy['batch']['manifest_sha256'])
        for identity in list(ops):
            if not ops[identity]['dispatch_started'] or ops[identity]['state'] == 'failed': continue
            # One refused operation never stops the scan or keeps its partial writes.
            before, saved = deepcopy(ops[identity]), deepcopy(state)
            try: _reconcile_one(directory, root, home, ops[identity], state)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                ops[identity], state = before, saved
        _save(directory, record, policy, ops)
    ready = []
    for op in ops.values():
        if op['state'] != 'pending' or op['dispatch_started'] or op['dispatch_exit'] is not None or op['incident'] is not None:
            continue
        try:
            with operation_lock(directory, op['operation_id']): ready.append(op['operation_id'])
        except BlockingIOError: pass
    return ready


def _wait_due(card, record):
    """Scheduling predicate only; caller must authenticate the card before reserving."""
    from model_router import REASONS
    wait = card.get('provider_wait')
    if card.get('terminal_stop') != 'provider_wait' or not isinstance(wait, dict):
        raise ValueError('request_refused')
    identity = uuid.UUID(wait['wait_id'])
    end = money.deadline(record['batch_deadline'])
    retry = money.deadline(wait['retry_after'])
    if (identity.version != 4 or str(identity) != wait['wait_id'] or
            wait['reason'] not in REASONS - {'unbounded_route'} or
            wait['evidence'] not in ('denied_before_work', 'interrupted') or
            money.deadline(wait['batch_deadline']) != end or
            not retry <= datetime.now(timezone.utc).timestamp() < end or retry >= end):
        raise ValueError('request_refused')


def schedule_waits(policy, root, home):
    """Reserve due, published, retired waits; ordinary reconcile dispatches next tick."""
    enabled(policy, root); record = money.manifest(policy, root)
    with money.locked(home, record['id']) as directory:
        ops = _operations(directory, record, policy)
    for op in ops.values():
        source = op['output_generation']
        if (op['state'] != 'launched' or op['incident'] is not None or
                op['retirement'] is None or source is None or
                operation_id(policy, op['job'], source) in ops): continue
        try:
            # Cheap skip-only filter: never hash a future wait's archives each tick.
            card = service._json(directory / 'generations' / op['case'] / source /
                                 (op['case'] + '.scorecard.json'))
            _wait_due(card, record)
            # Re-read and authenticate all evidence under reserve's lock.
            reserve(policy, root, home, op['job'], source, provider_wait=True)
        except (OSError, ValueError, KeyError, TypeError, AttributeError): continue
    return []  # This scan reserves work; it does not return children to spawn.


def orphaned(policy, root, home):
    """Discover only initialized controllers; the existing controller lock wins."""
    enabled(policy, root); record = money.manifest(policy, root)
    ready = []
    with money.locked(home, record['id']) as directory:
        for identity, op in _operations(directory, record, policy).items():
            if (not op['dispatch_started'] or op['retirement'] is not None or op['state'] == 'failed' or
                    op['incident'] in ('resume_failed', 'publication_failed')): continue
            path = home / 'launches' / op['launch_id']
            if (path / 'complete').exists() or not (path / 'monitor.sh').is_file(): continue
            try:
                with operation_lock(directory, identity), service._regular(path / 'controller.lock') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if service._json(path / 'launch.json') == op['launch']: ready.append(identity)
            except (OSError, ValueError, KeyError, TypeError): pass
    return ready


def unpublished(policy, root, home):
    """Launches whose output is collected and complete but never published/ACKed."""
    enabled(policy, root); record = money.manifest(policy, root)
    ready = []
    with money.locked(home, record['id']) as directory:
        for identity, op in _operations(directory, record, policy).items():
            if (op['state'] != 'launched' or op['output_generation'] is not None or
                    op['incident'] in ('accounting_refused', 'legacy_retire', 'publication_failed')): continue
            path = home / 'launches' / op['launch_id']
            # complete means the controller finished and deleted its workers, so collection is not racing.
            if not (path / 'complete').exists(): continue
            if not (path / 'collected' / (op['case'] + '.scorecard.json')).exists(): continue
            try:
                with operation_lock(directory, identity): ready.append(identity)
            except BlockingIOError: pass
    return ready


def _r2_env(identity_bytes, secrets):
    """Decrypt only the four R2_* publication credentials from the r2-env bundle member."""
    keys = {'R2_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET'}
    age = subprocess.Popen(['age', '-d', '-i', '/dev/stdin', str(secrets)], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    tar = subprocess.Popen(['tar', '-xOf', '-', 'r2-env'], stdin=age.stdout,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    age.stdout.close()
    try:
        age.stdin.write(identity_bytes); age.stdin.close()
        out, _ = tar.communicate(timeout=10)
        if age.wait(timeout=5) != 0 or tar.returncode != 0: raise ValueError('request_refused')
    except BaseException:
        for child in (age, tar):
            if child.poll() is None: child.kill()
            child.wait()
        raise
    env = {}
    for line in out.decode('utf-8').splitlines():
        tokens = shlex.split(line)  # r2-env is set -a shell assignments; shlex honours its quoting.
        key, _, value = (tokens[-1] if tokens else '').partition('=')
        if key in keys: env[key] = value
    if set(env) != keys: raise ValueError('request_refused')
    return env


def publish_replay(policy, root, home, identity, identity_bytes):
    """Holder-driven publication replay: the same idempotent collect command, with R2 in memory."""
    enabled(policy, root); record = money.manifest(policy, root)
    directory = home / 'batches' / record['id']
    with operation_lock(directory, identity):  # Held for the whole run; a second child refuses.
        with money.locked(home, record['id']):
            op = _operations(directory, record, policy)[identity]
        secrets = Path(os.environ.get('UNBUG_SECRETS_FILE', str(Path.home() / '.config/unbug-bench/secrets.age')))
        os.environ.update(_r2_env(identity_bytes, secrets))
        os.environ['UNBUG_LAUNCH_STATE'] = str(home / 'launches' / op['launch_id'])
        reconcile(policy, root, home)
        collect(policy, root, home, identity)


def resume_controller(policy, root, home, identity, identity_bytes):
    enabled(policy, root); record = money.manifest(policy, root)
    directory = home / 'batches' / record['id']
    with operation_lock(directory, identity):
        with money.locked(home, record['id']):
            op = _operations(directory, record, policy)[identity]
            path = home / 'launches' / op['launch_id']
            if (not op['dispatch_started'] or op['retirement'] is not None or op['state'] == 'failed' or
                    op['incident'] in ('resume_failed', 'publication_failed') or
                    (path / 'complete').exists() or not (path / 'monitor.sh').is_file() or
                    service._json(path / 'launch.json') != op['launch']): raise ValueError('request_refused')
            with service._regular(path / 'controller.lock') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        child = subprocess.Popen(['/bin/sh', str(root / 'factory/launch.sh'), '--resume-launch', op['launch_id']],
                                 cwd=root, env={'PATH': policy['path'], 'HOME': str(Path.home()),
                                                'USER': os.environ.get('USER', ''), 'UNBUG_CONTROL_HOME': str(home)},
                                 stdin=subprocess.PIPE)
        try: child.stdin.write(identity_bytes); child.stdin.close()
        except BrokenPipeError: pass
        return child.wait()


def source_directory(policy, root, home, identity):
    """Pure POST resolver used by both bind and the shell before restore."""
    enabled(policy, root); record = money.manifest(policy, root)
    directory = home / 'batches' / record['id']
    with service._regular(directory / 'lock') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        ops = _operations(directory, record, policy)
        state = money.load_locked(directory, record, policy['batch']['manifest_sha256'])
        op = _post(directory, record, policy, home, ops, state, identity)
        if op['source_generation'] is None: return None
        row = state['jobs'][op['job']]
        if row.get('imported', {}).get('generation') == op['source_generation']:
            from batch_transfer import source
            return source(home, record, op['job'], op['source_generation'])[3]
        return directory / 'generations' / op['case'] / op['source_generation']


def _charge(ledger, row):
    """A reservation's current charge: every event bound to it plus its open estimate."""
    import budget
    ids = set(row['event_ids']) | {e['id'] for e in ledger['events'] if e.get('id')
        and (e.get('lease_id'), e.get('invocation_id')) == (row['lease_id'], row['invocation_id'])}
    events = {e['id']: e for e in ledger['events'] if e.get('id') in ids}
    if ids - events.keys(): raise ValueError('invalid_accounting_input')
    try: return sum((budget.event_charge(e) for e in events.values()), budget.usd(row.get('estimated_gap_usd', 0)))
    except budget.BudgetError: raise ValueError('invalid_accounting_input') from None


def _extends(old, new):
    """Conservative cumulative evidence retention; ambiguous old markers freeze."""
    before, after = old['continuation_budget'], new['continuation_budget']
    events = before['events']
    if after['events'][:len(events)] != events: return False
    immutable = {'schema_version', 'invocation_id', 'operation_id', 'lease_id', 'route', 'account',
                 'billing', 'pool', 'family', 'call_name', 'parent_call_name', 'maximum_usd'}
    later = after.get('invocation_reservations', {})
    records = {r['invocation_id']: r for r in after.get('reconciled_decreases', [])}
    for lease, row in before.get('invocation_reservations', {}).items():
        target = later.get(lease, {})
        if any(row.get(k) != target.get(k) for k in immutable): return False
        if row['state'] == 'settled' and target.get('state') != 'settled': return False
        if row['state'] == 'estimated' and target.get('state') != 'estimated':
            # A final receipt lowers a charge only with its reconciled-decrease record.
            if target.get('state') != 'settled': return False
            if row['invocation_id'] not in records and _charge(after, target) < _charge(before, row): return False
    for marker in before.get('unpriced_invocations', []):
        if not isinstance(marker, dict) or not marker.get('invocation_id') or not marker.get('lease_id'): return False
        target = later.get(marker['lease_id'], {})
        if marker not in after.get('unpriced_invocations', []) and not (
                target.get('invocation_id') == marker['invocation_id'] and target.get('state') == 'settled'):
            return False
    return True


def r2_publish(root, key, path):
    """Signed URLs never leave memory or enter errors. PUT then streamed GET/hash."""
    try:
        def url(verb):
            return subprocess.check_output([str(root / 'bin/r2-presign'), verb, key, '3600'],
                                           stderr=subprocess.DEVNULL, timeout=30, text=True).strip()
        with path.open('rb') as stream:
            request = urllib.request.Request(url('PUT'), data=stream, method='PUT',
                                             headers={'Content-Length': str(path.stat().st_size)})
            with urllib.request.urlopen(request, timeout=120) as response: response.read(4096)
        h = hashlib.sha256(); size = 0; end = time.monotonic() + 1800
        with urllib.request.urlopen(url('GET'), timeout=120) as response:
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > path.stat().st_size or time.monotonic() > end: raise ValueError()
                h.update(block)
        if h.hexdigest() != digest(path): raise ValueError()
    except Exception:
        raise ValueError('publication_failed') from None


def collect(policy, root, home, identity, transport=None):
    enabled(policy, root); record = money.manifest(policy, root)
    with money.locked(home, record['id']) as directory:
        ops = _operations(directory, record, policy); op = deepcopy(ops[identity])
        _config(policy, home, op)
        worker = _created(home / 'launches' / op['launch_id'], op)
        if worker != op['worker_id'] or op['state'] != 'launched': raise ValueError('request_refused')
    incoming = home / 'launches' / op['launch_id'] / 'collected'
    # Freeze bytes through the existing verifier before any outbox or ACK writes.
    entry = service.collect(policy, root, home, op['job'], incoming)
    generation = entry['generation']
    with money.locked(home, record['id']) as directory:
        ops = _operations(directory, record, policy); current = ops[identity]
        state = money.load_locked(directory, record, policy['batch']['manifest_sha256'])
        row = state['jobs'][op['job']]
        if row['authority'] != op['authority'] or current['authority'] != op['authority']:
            raise ValueError('request_refused')
        card = service._snapshot(directory, entry, record, policy['batch']['sha256'])
        if card.get('job_money') != op['authority']: raise ValueError('legacy_retire')
        old = row['acks'].get(generation)
        if old is not None:
            if old['operation_id'] != identity or old['manifest_sha256'] != entry['manifest_sha256']:
                raise ValueError('request_refused')
            if current['output_generation'] not in (None, generation):
                recovery = directory / 'outbox' / (identity + '.json')
                saved = service._json(recovery) if recovery.exists() else {}
                if saved.get('generation') != generation: return deepcopy(old)
        outbox_dir = directory / 'outbox'; outbox_dir.mkdir(mode=0o700, exist_ok=True)
        outbox_path = outbox_dir / (identity + '.json')
        if outbox_path.exists():
            prior = service._json(outbox_path)
            if prior['generation'] != generation and prior['state'] != 'acknowledged':
                incident = state['incidents'].get(identity + '/' + prior['generation'])
                if incident is None: raise ValueError('request_refused')
                _, refused = _entry(directory, record, policy, op['case'], prior['generation'])
                if not _extends(refused, card): raise ValueError('request_refused')
        candidate = dict(schema=1, operation_id=identity, generation=generation,
                         manifest_sha256=entry['manifest_sha256'], state='pending')
        atomic_json(outbox_path, candidate)
        import practice
        practice.fault(policy, root, home, identity)
    snapshot = directory / 'generations' / op['case'] / generation
    manifest = service._json(snapshot / 'manifest.json')
    transport = transport or (lambda key, path: r2_publish(root, key, path))
    for name in sorted(set(manifest['files']) | {'manifest.json'}):
        transport('generations/' + op['case'] + '/' + generation + '/' + name, snapshot / name)
    with money.locked(home, record['id']) as directory:
        if service._json(outbox_path) != candidate: raise ValueError('request_refused')
        ops = _operations(directory, record, policy); current = ops[identity]
        state = money.load_locked(directory, record, policy['batch']['manifest_sha256']); row = state['jobs'][op['job']]
        if row['authority'] != op['authority']: raise ValueError('request_refused')
        card = service._snapshot(directory, entry, record, policy['batch']['sha256'])
        ack = row['acks'].get(generation)
        if ack is None:
            import budget
            try:
                facts = collection_facts(card, row['previous'], row['held_usd'], budget)
                clear = []
                for key, incident in state['incidents'].items():
                    if incident['operation_id'] != identity: continue
                    _, refused = _entry(directory, record, policy, op['case'], incident['generation'])
                    if incident['generation'] == generation or not _extends(refused, card):
                        raise ValueError('invalid_accounting_input')
                    clear.append(key)
            except (ValueError, KeyError, TypeError) as error:
                reason = str(error) if str(error) in money.ACCOUNTING_ERRORS else 'invalid_accounting_input'
                state['incidents'].setdefault(identity + '/' + generation, dict(operation_id=identity,
                    generation=generation, manifest_sha256=entry['manifest_sha256'], reason=reason))
                atomic_json(directory / 'money.json', state)
                current['incident'] = 'accounting_refused'; _save(directory, record, policy, ops)
                raise ValueError(reason) from None
            ack = dict(operation_id=identity, generation=generation, manifest_sha256=entry['manifest_sha256'],
                       authority=deepcopy(op['authority']), previous=deepcopy(row['previous']), facts=facts, retirement=None)
            row['acks'][generation] = ack
            row['previous'] = {k: deepcopy(facts[k]) for k in ('total_usd', 'estimated')}
            if facts['total_usd'] is not None and money.amount(facts['total_usd']) > money.amount(row['known_floor_usd']):
                row['known_floor_usd'] = facts['total_usd']
            row['overrun'] = money.amount(row['known_floor_usd']) > money.amount(row['held_usd'])
            for key in clear: del state['incidents'][key]
        pointers = directory / 'current'; pointers.mkdir(mode=0o700, exist_ok=True)
        pointer = dict(generation=generation, manifest_sha256=entry['manifest_sha256'])
        atomic_json(pointers / (op['case'] + '.json'), pointer)
        if service._json(pointers / (op['case'] + '.json')) != pointer: raise ValueError('request_refused')
        atomic_json(directory / 'money.json', state)
        atomic_json(outbox_path, {**candidate, 'state': 'acknowledged'})
        current.update(output_generation=generation, incident=None)
        _save(directory, record, policy, ops)
        return deepcopy(ack)


def dispatch(policy, root, home, identity, identity_bytes):
    """One preflight owner, then the existing shell controller. No new launcher."""
    enabled(policy, root); record = money.manifest(policy, root)
    directory = home / 'batches' / record['id']
    with operation_lock(directory, identity):
        try:
            from key_holder import fingerprint, secret_labels, OPENCODE_ACCOUNTS, CLAUDE_ACCOUNTS
            from account_handoff import launch_accounts
            from control_resume import ENVIRONMENT
            from batch import bind
            if fingerprint(root) != policy['code_sha256']: raise ValueError('request_refused')
            with money.locked(home, record['id']):
                ops = _operations(directory, record, policy)
                state = money.load_locked(directory, record, policy['batch']['manifest_sha256'])
                op = deepcopy(_post(directory, record, policy, home, ops, state, identity))
                if op['state'] != 'pending' or op['dispatch_started'] or op['incident'] is not None: return
                if op['source_generation'] is None: empty_input(root, directory, op['case'])
            recipient = subprocess.run(['age-keygen', '-y'], input=identity_bytes,
                                       capture_output=True, check=True, timeout=10).stdout.decode().strip()
            if recipient not in (record['restore_recipient'], policy['recipient']): raise ValueError('request_refused')
            secrets = Path(os.environ.get('UNBUG_SECRETS_FILE', str(Path.home() / '.config/unbug-bench/secrets.age')))
            labels = secret_labels(identity_bytes, secrets)
            source = source_directory(policy, root, home, identity)
            card = {} if source is None else service._json(source / (op['case'] + '.scorecard.json'))
            job = bind(policy, op['job'], op['source_generation'], root, home=home, operation=identity)
            account, claude, accounts = launch_accounts(card, job, {}, labels)
            if ((account is not None and OPENCODE_ACCOUNTS[account] not in labels) or
                    CLAUDE_ACCOUNTS[claude] not in labels): raise ValueError('request_refused')
            import practice_cleanup
            practice_cleanup.armed(policy, root, home, op)
            fleet = subprocess.run([str(root / 'bin/boat-call'), 'list', '--json'],
                                   capture_output=True, check=True,
                                   env={**os.environ, 'BOAT_CAPTURE_OUTPUT': '1', 'BOAT_COMMAND_TIMEOUT_SECONDS': '25'})
            inventory = json.loads(fleet.stdout)
            ids = [r['id'] for r in inventory['sandboxes']]
            if (inventory['pageInfo']['hasMore'] is not False or len(ids) != len(set(ids)) or
                    any(not isinstance(v, str) for v in ids)): raise ValueError('request_refused')
            known = set(job.get('known_worker_ids', [])) | {o['worker_id'] for o in ops.values() if o['case'] == op['case']}
            if known.intersection(ids): raise ValueError('request_refused')
            config = _config(policy, home, op)
            argv = [*job['args'], '--factory-job-config', str(config), '--factory-job-config-sha256', op['config_sha256']]
            env = dict(PATH=policy['path'], HOME=str(Path.home()), USER=os.environ.get('USER', ''), LANG='en_US.UTF-8',
                       BOAT_COMMAND_TIMEOUT_SECONDS='120', UNBUG_CLOUD='boat', BOAT_TYPE='default',
                       UNBUG_SECRETS_FILE=str(secrets), UNBUG_CONTROL_HOME=str(home), UNBUG_LAUNCH_ID=op['launch_id'],
                       UNBUG_BATCH_OPERATION=identity, CLAUDE_SECRET_NAME=CLAUDE_ACCOUNTS[claude],
                       FACTORY_ACCOUNT_POLICY=json.dumps({p + '_accounts': job.get(p + '_accounts', []) for p in ('opencode', 'claude')}),
                       FACTORY_ACCOUNT_STATE=json.dumps(accounts))
            import practice
            if practice.active(policy, root): env['UNBUG_PRACTICE_BATCH'] = practice.BATCH
            if account is not None: env['OPENCODE_SECRET_NAME'] = OPENCODE_ACCOUNTS[account]
            with money.locked(home, record['id']):
                ops = _operations(directory, record, policy)
                state = money.load_locked(directory, record, policy['batch']['manifest_sha256'])
                current = _post(directory, record, policy, home, ops, state, identity)
                if current['state'] != 'pending' or current['dispatch_started'] or current['incident'] is not None: return
                if current['source_generation'] is None: empty_input(root, directory, current['case'])
                practice_cleanup.armed(policy, root, home, current)
                current['launch'] = dict(argv=argv, environment={k: env[k] for k in ENVIRONMENT if k in env})
                current['dispatch_started'] = True
                _save(directory, record, policy, ops)
            # Popen uncertainty retains the durable started reservation, never retries.
            child = subprocess.Popen(['/bin/sh', str(root / 'factory/launch.sh'), *argv],
                                     cwd=root, env=env, stdin=subprocess.PIPE)
            try: child.stdin.write(identity_bytes); child.stdin.close()
            except BrokenPipeError: pass
            return child.wait()
        except (money.MoneyWait, subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
            return TEMPFAIL  # A batch freeze or transient I/O is not a refusal of this operation.
        except Exception:
            with money.locked(home, record['id']):
                ops = _operations(directory, record, policy); op = ops[identity]
                if not op['dispatch_started'] and op['state'] == 'pending':
                    op.update(state='failed', incident='preflight_refused')
                    _save(directory, record, policy, ops)
            raise ValueError('request_refused') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('dispatch', 'resume', 'publish', 'collect', 'source', 'restore-check'))
    parser.add_argument('--operation', required=True)
    parser.add_argument('--policy', type=Path, default=Path(os.environ.get('UNBUG_CONTROL_HOME',
                        str(Path.home() / '.unbug-control'))) / 'policy.json')
    parser.add_argument('--recipient')
    a = parser.parse_args()
    try:
        from key_holder import policy_load, ROOT, CONTROL_HOME
        policy = policy_load(a.policy)
        enabled(policy, ROOT)
        if a.command in ('dispatch', 'resume', 'publish'):
            key = bytearray(sys.stdin.buffer.read(4097))
            try:
                action = {'dispatch': dispatch, 'resume': resume_controller, 'publish': publish_replay}[a.command]
                return action(policy, ROOT, CONTROL_HOME, a.operation, key) or 0
            finally: key[:] = b'\0' * len(key)
        if a.command == 'collect':
            # collect.sh wrote into its controller's state; it must be this operation's launch directory.
            state = Path(os.environ.get('UNBUG_LAUNCH_STATE', '')).resolve()
            if state != (CONTROL_HOME / 'launches' / lookup(policy, ROOT, CONTROL_HOME, a.operation)['launch_id']).resolve():
                raise ValueError('request_refused')
            reconcile(policy, ROOT, CONTROL_HOME)
            collect(policy, ROOT, CONTROL_HOME, a.operation)
        else:
            source = source_directory(policy, ROOT, CONTROL_HOME, a.operation)
            if a.command == 'restore-check':
                record = money.manifest(policy, ROOT)
                if source is None or a.recipient not in (policy['recipient'], record['restore_recipient']):
                    raise ValueError('request_refused')
            elif source is not None: print(source)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('batch operation refused', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
