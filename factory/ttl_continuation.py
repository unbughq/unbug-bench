"""Attest, collect and admit bounded TTL continuations through the existing holder.

Legacy ``paused`` cards are deliberately ineligible. A host retirement request
must first be echoed into a distinct TTL scorecard by the runner. Prepared jobs
still need an explicit reviewed fixed-case policy and the existing holder's
inventory/concurrency checks; this module does not grant that authorization.
"""
import argparse
import hashlib
import json
import os
import math
import pathlib
import re
import time
import secrets
import shlex
import subprocess

import coordinator
import key_holder
from registry import atomic_json, identifier

BOUND_FIELDS = {'started_at', 'deadline', 'max_attempts', 'max_spend', 'launch_spend', 'initial_spend', 'ttl_hours'}


def identity_digest(card):
    identity = {key: card.get(key) for key in ('case', 'source', 'rotation_slot', 'seed', 'roles', 'recovery_config')}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()


def proposal(card, bounds):
    case, config = card['case'], card['recovery_config']
    job = {'mode': 'case', 'case': case, 'card': case + '.scorecard.json', 'archive_prefix': case,
           'roles': card['roles'], 'max_calls': config['max_total_calls'], 'max_cost': config['max_cost'],
           'args': ['1', '--restore', case, '--seed', str(card['seed']), '--ttl-hours', str(bounds['ttl_hours']),
                    '--max-spend', str(bounds['launch_spend'])]}
    job['args'] = coordinator.configuration_args(card, job)
    return job


def policy_check(job):
    bounds = job.get('ttl_continuation')
    if (job.get('mode') != 'case' or not isinstance(bounds, dict) or set(bounds) != BOUND_FIELDS or
            job.get('card') != job.get('case', '') + '.scorecard.json' or job.get('archive_prefix') != job.get('case')):
        raise ValueError('fixed-case TTL policy required')
    # Reuse the same bounds checks as preparation, without reading any case data.
    b = bounds
    if (not all(finite(b[k]) for k in BOUND_FIELDS - {'max_attempts'}) or
            not b['started_at'] < b['deadline'] <= b['started_at'] + 86400 or
            type(b['max_attempts']) is not int or not 1 <= b['max_attempts'] <= 3 or
            not 0 <= b['initial_spend'] <= b['max_spend'] or
            not 0 < b['launch_spend'] <= b['max_spend'] or not 0 < b['ttl_hours'] * 3600 <= b['deadline'] - b['started_at']):
        raise ValueError('invalid fixed continuation bounds')
    argv = job['args']
    for flag, expected in (('--ttl-hours', b['ttl_hours']), ('--max-spend', b['launch_spend'])):
        if argv.count(flag) != 1 or float(argv[argv.index(flag) + 1]) != expected:
            raise ValueError('TTL policy launch envelope differs')
    if any(v.startswith(('--ttl-hours=', '--max-spend=')) for v in argv):
        raise ValueError('duplicate TTL launch envelope')
    return bounds


def runner_request(path, pid, case, now=None):
    """A stale marker or a marker for another process is an ordinary manual pause."""
    try:
        request = read_public(path)
        now = time.time() if now is None else now
        if (request.get('version') == 1 and request.get('reason') == 'ttl' and request.get('case') == case and
                type(request.get('runner_pid')) is int and request['runner_pid'] == pid and
                finite(request.get('requested_at')) and 0 <= now - request['requested_at'] <= 120 and
                re.fullmatch(r'[0-9a-f]{32}', request.get('nonce', '')) and
                re.fullmatch(r'[A-Za-z0-9_-]+', request.get('worker', ''))):
            return request
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def request_retirement(root, worker, job, *, remote=None, now=None):
    """Persist the host attestation before installing its public marker on the VM."""
    root = pathlib.Path(root); bounds = policy_check(job)
    now = time.time() if now is None else now
    if not re.fullmatch(r'[A-Za-z0-9_-]+', worker) or not bounds['started_at'] <= now < bounds['deadline']:
        raise ValueError('invalid TTL retirement target or deadline')
    if remote is None:
        def remote(command):
            return subprocess.check_output([str(root / 'bin/boat-call'), 'ssh', worker, command], text=True,
                env={**os.environ, 'BOAT_CAPTURE_OUTPUT': '1', 'BOAT_COMMAND_TIMEOUT_SECONDS': '120'}).strip()
    pid = int(remote("pgrep -f '^python3 .*factory/run.py'"))  # exactly one process; ambiguous output fails closed
    if pid <= 0: raise ValueError('no live runner')
    request = dict(version=1, reason='ttl', case=identifier(job['case']), worker=worker,
                   nonce=secrets.token_hex(16), runner_pid=pid, requested_at=now)
    record = root / 'results/ttl-retirements' / (worker + '.json')
    record.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(record, {'request': request, 'bounds': bounds})
    code = ("import os,pathlib; os.kill(" + str(pid) + ",0); p=pathlib.Path.home()/'sealed/.ttl-retirement.json'; "
            "p.write_text(" + repr(json.dumps(request)) + ")")
    remote('python3 -c ' + shlex.quote(code))
    return request


def collect(root, worker, *, now=None):
    root = pathlib.Path(root)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', worker): raise ValueError('invalid worker')
    record = read_public(root / 'results/ttl-retirements' / (worker + '.json'))
    return prepare(root, record['request'], now=now, **record['bounds'])


def retired(root, worker, *, now=None):
    """The guard calls this only after the provider confirms deletion, never parking."""
    root = pathlib.Path(root)
    row = collect(root, worker, now=now)
    path = root / 'results/ttl-retired' / (worker + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, {'retirement': row['retirement'], 'generation': row['generation'],
                       'deleted_at': time.time() if now is None else now})
    return row


def successor(root, job, generation, receipt):
    """A later verified TTL seal and confirmed deletion reconcile a previous launch."""
    try:
        if receipt.get('case') != job['case'] or receipt.get('generation') == generation: return None
        card = read_public(pathlib.Path(root) / 'sealed' / job['card'])
        row = ready(root, job, card)
        request = row['retirement']
        proof = read_public(pathlib.Path(root) / 'results/ttl-retired' / (request['worker'] + '.json'))
        if (row['generation'] != generation or proof.get('retirement') != request or
                proof.get('generation') != generation or not finite(proof.get('deleted_at')) or
                not finite(receipt.get('at')) or not receipt['at'] <= request['requested_at'] <= proof['deleted_at'] <= time.time() or
                type(receipt.get('budget_calls')) is not int or not finite(receipt.get('budget_cost')) or
                row['budget_calls'] < receipt['budget_calls'] or row['budget_cost'] + 1e-9 < receipt['budget_cost']):
            return None
        return request['worker']
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def ready(root, job, card, *, now=None):
    """Admission requires a verified queue row AND the retained host attestation."""
    root = pathlib.Path(root); bounds = policy_check(job)
    now = time.time() if now is None else now
    request = card.get('retirement') or {}
    worker = request.get('worker', '')
    if not isinstance(worker, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', worker):
        raise ValueError('missing host TTL attestation')
    record = read_public(root / 'results/ttl-retirements' / (worker + '.json'))
    if record != {'request': request, 'bounds': bounds}: raise ValueError('host TTL attestation differs')
    queue = read_public(root / 'results/ttl-continuations' / (job['case'] + '.json'))
    if not any(row.get('generation') == card.get('sha256') and row.get('retirement') == request
               for row in queue.get('preparations', [])):
        raise ValueError('verified TTL collection queue required')
    row = prepare(root, request, now=now, **bounds)
    if job['args'] != row['job_proposal']['args'] or job['roles'] != row['job_proposal']['roles']:
        raise ValueError('TTL policy changes original conditions')
    if job['max_calls'] != card['recovery_config']['max_total_calls'] or job['max_cost'] != card['recovery_config']['max_cost']:
        raise ValueError('TTL policy changes original ceilings')
    return row


def admit(root, job, card, generation, req, receipts, consumed, *, now=None):
    """Called inside the holder's serialized launch reservation, including direct clients."""
    bounds = policy_check(job)
    now = time.time() if now is None else now
    if (not finite(now) or not bounds['started_at'] <= now or now + bounds['ttl_hours'] * 3600 > bounds['deadline']):
        raise ValueError('TTL launch deadline exhausted')
    if card.get('terminal_stop') == 'ttl_retired':
        row = ready(root, job, card, now=now)
    else:
        # Arm an ordinary already-authorized fixed-case recovery. Its next TTL
        # stop enters the attested queue; manual pauses never bootstrap this path.
        if (card.get('terminal_stop') == 'paused' or
                (card.get('continuation_budget') or {}).get('terminal_stop') in ('PauseRequested', 'paused') or
                job['roles'] != card.get('roles') or proposal(card, bounds)['args'] != job['args'] or
                job['args'].count('--seed') != 1 or job['args'][job['args'].index('--seed') + 1] != str(card.get('seed')) or
                job['max_calls'] != card['recovery_config']['max_total_calls'] or job['max_cost'] != card['recovery_config']['max_cost']):
            raise ValueError('TTL bootstrap changes original conditions or resumes a manual pause')
        row = {'launch_expectations': {'expected_generation': generation,
                'expected_recovery_config_sha256': key_holder.recovery_conditions_digest(card)}}
        path = pathlib.Path(root) / 'results/ttl-continuations' / (job['case'] + '.json')
        with coordinator.locked(path):
            state = read_public(path) if path.exists() else {'version': 1, 'case': job['case'],
                'identity': identity_digest(card), 'bounds': bounds, 'preparations': []}
            if (state.get('version') != 1 or state.get('case') != job['case'] or
                    state.get('identity') != identity_digest(card) or state.get('bounds') != bounds):
                raise ValueError('continuation identity or fixed bounds changed')
            atomic_json(path, state)
    stamp = (job['case'], generation)
    if stamp in consumed or any(v['case'] == job['case'] and v['generation'] == generation for v in receipts):
        raise ValueError('TTL generation already admitted')
    attempts = sum(v['case'] == job['case'] for v in receipts)
    if attempts >= bounds['max_attempts']:
        raise ValueError('TTL attempt allowance exhausted')
    if bounds['initial_spend'] + (attempts + 1) * bounds['launch_spend'] > bounds['max_spend'] + 1e-9:
        raise ValueError('TTL infrastructure allowance exhausted')
    if req.get('machine', 'default') != 'default': raise ValueError('TTL infrastructure envelope requires default machine')
    if any(req.get(key) != value for key, value in row['launch_expectations'].items()):
        raise ValueError('TTL admission requires exact expectations')
    return row


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def read_public(path):
    return coordinator.read_public(path)


def prepare(root, request, *, started_at, deadline, max_attempts, max_spend,
            launch_spend, initial_spend, ttl_hours, now=None):
    """Reserve a preparation once per verified generation, inside fixed bounds.

    ``request`` is host-owned metadata retained before a TTL retirement, never a
    caller's reinterpretation of a collected manual pause. No ciphertext opens.
    """
    root = pathlib.Path(root)
    now = time.time() if now is None else now
    if (not all(finite(v) for v in (now, started_at, deadline, max_spend, launch_spend, initial_spend, ttl_hours)) or
            not started_at <= now < deadline <= started_at + 24 * 3600 or
            type(max_attempts) is not int or not 1 <= max_attempts <= 3 or
            not 0 <= initial_spend <= max_spend or not 0 < launch_spend <= max_spend or
            not 0 < ttl_hours * 3600 <= deadline - now):
        raise ValueError('invalid fixed continuation bounds')
    if (not isinstance(request, dict) or set(request) !=
            {'version', 'reason', 'case', 'worker', 'nonce', 'runner_pid', 'requested_at'} or
            request.get('version') != 1 or request.get('reason') != 'ttl' or
            not isinstance(request.get('worker'), str) or not re.fullmatch(r'[A-Za-z0-9_-]+', request['worker']) or
            not isinstance(request.get('nonce'), str) or not re.fullmatch(r'[0-9a-f]{32}', request['nonce']) or
            type(request.get('runner_pid')) is not int or request['runner_pid'] <= 0 or
            not finite(request.get('requested_at')) or not started_at <= request['requested_at'] <= now):
        raise ValueError('missing host TTL retirement request')
    case = identifier(request['case'])
    card = read_public(root / 'sealed' / (case + '.scorecard.json'))
    if (card.get('case') != case or card.get('status') != 'stopped' or card.get('terminal_stop') != 'ttl_retired' or
            card.get('retirement') != request or card.get('failed_gate') or card.get('checkpoint_error')):
        raise ValueError('only an attested TTL retirement can be queued')
    budget, config = card.get('continuation_budget'), card.get('recovery_config')
    if not isinstance(budget, dict) or not isinstance(config, dict):
        raise ValueError('missing original cumulative conditions')
    conditions = key_holder.recovery_conditions_digest(card)
    if (not isinstance(budget.get('events'), list) or budget.get('active') or
            budget.get('terminal_stop') not in (None, 'complete', 'PauseRequested', 'ttl_retired') or
            not finite(config.get('max_cost')) or not finite(config.get('max_total_calls')) or
            budget['calls'] >= config['max_total_calls'] or budget['cost'] >= config['max_cost']):
        raise ValueError('invalid or exhausted original cumulative allowance')
    sealed = root / 'sealed'
    final, checkpoint = (sealed / (case + suffix) for suffix in ('.tar.gz.age', '.checkpoint.tar.gz.age'))
    archive = final if not checkpoint.is_file() or (final.is_file() and final.stat().st_mtime_ns > checkpoint.stat().st_mtime_ns) else checkpoint
    if not archive.is_file() or archive.is_symlink():
        raise ValueError('verified collection required')
    with archive.open('rb') as stream:
        if not stream.read(64).startswith((b'age-encryption.org/v1', b'-----BEGIN AGE ENCRYPTED FILE-----')):
            raise ValueError('verified encrypted collection required')
        stream.seek(0)
        generation = hashlib.file_digest(stream, 'sha256').hexdigest()
    if generation != card.get('sha256'):
        raise ValueError('verified collection required')
    identity = identity_digest(card)
    bounds = dict(started_at=started_at, deadline=deadline, max_attempts=max_attempts,
                  max_spend=max_spend, launch_spend=launch_spend, initial_spend=initial_spend, ttl_hours=ttl_hours)
    path = root / 'results/ttl-continuations' / (case + '.json')
    with coordinator.locked(path):
        state = read_public(path) if path.exists() else {
            'version': 1, 'case': case, 'identity': identity, 'bounds': bounds, 'preparations': []}
        if (not isinstance(state, dict) or state.get('version') != 1 or state.get('case') != case or
                state.get('identity') != identity or state.get('bounds') != bounds or
                not isinstance(state.get('preparations'), list) or len(state['preparations']) > max_attempts):
            raise ValueError('continuation identity or fixed bounds changed')
        for row in state['preparations']:
            if (type(row.get('budget_calls')) is not int or not finite(row.get('budget_cost')) or
                    budget['calls'] < row['budget_calls'] or budget['cost'] + 1e-9 < row['budget_cost']):
                raise ValueError('cumulative usage regressed')
            if row.get('generation') == generation:
                if row.get('conditions_sha256') != conditions or row.get('retirement') != request:
                    raise ValueError('collected generation conditions changed')
                return row
            if row.get('retirement', {}).get('nonce') == request['nonce']:
                raise ValueError('TTL retirement request already consumed')
        count = len(state['preparations'])
        if count >= max_attempts or initial_spend + (count + 1) * launch_spend > max_spend + 1e-9:
            raise ValueError('continuation preparation allowance exhausted')
        job = proposal(card, bounds)
        row = {'action': 'queued_policy_required', 'generation': generation, 'conditions_sha256': conditions,
               'launch_expectations': {'expected_generation': generation,
                                       'expected_recovery_config_sha256': conditions},
               'retirement': request, 'at': now, 'budget_calls': budget['calls'], 'budget_cost': budget['cost'],
               'reserved_infrastructure_spend': launch_spend, 'job_proposal': job,
               'prerequisite': 'reviewed fixed-case TTL policy and holder admission; no launch authorized'}
        state['preparations'].append(row)
        atomic_json(path, state)
        return row


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in ('retire', 'collect', 'retired'):
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('operation', choices=('retire', 'collect', 'retired'))
        parser.add_argument('--root', type=pathlib.Path, required=True)
        parser.add_argument('--worker', required=True)
        parser.add_argument('--job-json')
        args = parser.parse_args()
        result = (request_retirement(args.root, args.worker, json.loads(args.job_json)) if args.operation == 'retire'
                  else (retired if args.operation == 'retired' else collect)(args.root, args.worker))
        print(json.dumps(result, sort_keys=True))
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, required=True)
    parser.add_argument('--request', type=pathlib.Path, required=True, help='host-owned pre-retirement public request')
    for flag in ('started-at', 'deadline', 'max-spend', 'launch-spend', 'initial-spend', 'ttl-hours'):
        parser.add_argument('--' + flag, type=float, required=True)
    parser.add_argument('--max-attempts', type=int, required=True)
    args = vars(parser.parse_args())
    args['request'] = read_public(args['request'])
    print(json.dumps(prepare(**args), sort_keys=True))


if __name__ == '__main__':
    main()
