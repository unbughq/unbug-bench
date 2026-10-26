#!/usr/bin/env python3
"""Next-run controller finisher: verify an existing deletion, then finish spend once.

Usage: python3 -B tools/public-qualification/finish.py EVIDENCE_DIRECTORY [--timeout 60]
Never creates, resumes, or deletes a worker. Historical run scripts stay unchanged.
"""
import argparse
import datetime
import fcntl
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return json.loads(path.read_text())


def save(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def timestamp(value):
    if not isinstance(value, str) or not value:
        raise ValueError('Missing completion timestamp')
    parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Completion timestamp must include timezone')


def identity(operation, operation_id, worker):
    if (not isinstance(operation, dict) or operation.get('id') != operation_id or
            operation.get('targetId') != worker or operation.get('kind') != 'sandbox'):
        raise ValueError('Deletion operation identity mismatch')


def wait_deletion(evidence, operation_id, worker, timeout):
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Deletion verification deadline exceeded')
        response = subprocess.run([str(ROOT / 'bin/boat-call'), 'deletion', 'status',
                                   operation_id, '--json'], capture_output=True, text=True,
                                  timeout=remaining)
        if response.returncode:
            raise ValueError('Deletion status query failed')
        operation = json.loads(response.stdout)['operation']
        identity(operation, operation_id, worker)
        # Persist only public operation metadata, never arbitrary provider diagnostics.
        operation = {k: operation.get(k) for k in
                     ('id', 'targetId', 'kind', 'status', 'stage', 'completedAt')}
        save(evidence / 'deletion-completion-query.json', operation)
        if time.monotonic() >= deadline:
            raise TimeoutError('Deletion verification deadline exceeded')
        if operation['status'] == 'completed':
            if operation['stage'] != 'completed':
                raise ValueError('Deletion completion stage mismatch')
            timestamp(operation['completedAt'])
            save(evidence / 'deletion-completion.json', operation)
            return operation
        if (operation['status'] not in ('pending', 'processing') or
                operation['stage'] in ('failed', 'cancelled', 'canceled', 'completed') or
                operation['completedAt'] is not None):
            raise ValueError('Deletion failed or has inconsistent state')
        time.sleep(min(2, max(0, deadline - time.monotonic())))


def spend_finalized(spend, worker, code):
    if not spend.get('finished_at'):
        return False
    timestamp(spend['finished_at'])
    amount = spend.get('actual_spend_eur' if spend.get('provider') == 'hetzner' else 'actual_spend_usd')
    if (spend.get('ids') != [worker] or spend.get('exit_code') != code or
            type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0):
        raise ValueError('Existing spend finish is incomplete or mismatched; manual reconciliation required')
    return True


def finish(evidence, *, timeout=60):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Deletion timeout must be positive and finite')
    evidence = Path(evidence)
    # Serialize retries, including the read/check/spend write sequence.
    with (evidence / 'finish.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = load(evidence / 'monitor-status.json')
        if status.get('collection_verified') is not True or status.get('worker_deleted') is not True:
            raise ValueError('Verified collection and existing deletion request required')
        worker = status['worker_id']
        raw = load(evidence / 'deletion.json')
        operation = json.loads(raw['stdout'])['operation']
        operation_id = operation.get('id')
        if raw.get('returncode') != 0 or not isinstance(operation_id, str) or not operation_id:
            raise ValueError('Valid existing deletion operation required')
        identity(operation, operation_id, worker)
        if (evidence / 'worker-ids.txt').read_text().split() != [worker]:
            raise ValueError('Spend worker list mismatch')
        completion = wait_deletion(evidence, operation_id, worker, timeout)
        case = status['case']
        if not isinstance(case, str) or Path(case).name != case:
            raise ValueError('Invalid scorecard identifier')
        card = load(evidence / (case + '.scorecard.json'))
        code = int(bool(card.get('failed_gate') or card.get('terminal_stop') or card['gates'].get('G12') != 'pass'))
        if spend_finalized(load(evidence / 'spend.json'), worker, code):
            return completion
        attempt = evidence / 'spend-finish-attempt.json'
        if attempt.exists():
            raise ValueError('Previous spend attempt unresolved; manual reconciliation required')
        save(attempt, {'operation_id': operation_id, 'worker_id': worker, 'exit_code': code})
        response = subprocess.run([str(ROOT / 'bin/boat-spend'), '--finish', str(evidence / 'spend.json'),
                                   str(code), str(evidence / 'worker-ids.txt')],
                                  capture_output=True, text=True, timeout=130)
        save(evidence / 'spend-finish.json', {'returncode': response.returncode})
        if response.returncode or not spend_finalized(load(evidence / 'spend.json'), worker, code):
            raise ValueError('Spend finish unconfirmed; manual reconciliation required')
        return completion


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args()
    try:
        completion = finish(args.evidence, timeout=args.timeout)
    except Exception:
        parser.exit(1, 'Finish failed closed; inspect public evidence and reconcile before retrying.\n')
    print(json.dumps({'deletion_completed_at': completion['completedAt'], 'spend_finalized': True}))
