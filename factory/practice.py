"""Explicit opt-in for the one disposable, hash-authenticated plumbing practice."""
import os
from datetime import datetime, timezone
from pathlib import Path
import batch_money as money
from registry import atomic_json

BATCH = 'b-plumbing-practice-3'
TIMING = dict(run_seconds=1800, grace_seconds=900, ttl_seconds=3600)
EXPECTED = {'schema': 1,
 'id': 'b-plumbing-practice-3',
 'batch_deadline': '2026-11-07T00:00:00Z',
 'money_limit_usd': '19.990000000',
 'max_concurrency': 1,
 'target_slots': 1,
 'restore_recipient': 'age1ae6f86fkvfnlv525ne9n4rj49texw9r9sh5h5udj23da0ptnnuksuxm6ch',
 'replacement_policy': {'schema': 1, 'enabled': False},
 'practice_admission': {'schema': 1,
                        'jobs': {'smoke': {'baseline_usd': '0.000000000', 'incremental_usd': '0.010000000'},
                                 'practice': {'baseline_usd': '0.000000000',
                                              'incremental_usd': '19.980000000'}}},
 'jobs': {'smoke': {'mode': 'batch',
                    'case': 'case-b-plumbing-practice-3-smoke',
                    'requested_total_usd': '0.010000000',
                    'claude_accounts': [2, 1],
                    'initial_accounts': {'claude': 2},
                    'opencode_accounts': [],
                    'args': ['1',
                             '--source',
                             'port',
                             '--rotation-slot',
                             '1',
                             '--builder',
                             'openrouter/minimax/minimax-m3.1-flash',
                             '--attacker',
                             'openrouter/deepseek/deepseek-v4.1-flash',
                             '--reviewer1',
                             'openrouter/xiaomi/mimo-v2.6-pro',
                             '--strong-calibrator',
                             'claude/claude-opus-4-5-20251101:compact',
                             '--easy-calibrator',
                             'openrouter/minimax/minimax-m3.1-flash',
                             '--ttl-hours',
                             '1',
                             '--max-spend',
                             '5',
                             '--dry-run']},
          'practice': {'mode': 'batch',
                       'case': 'case-b-plumbing-practice-3-practice',
                       'requested_total_usd': '19.980000000',
                       'claude_accounts': [2, 1],
                       'initial_accounts': {'claude': 2},
                       'opencode_accounts': [],
                       'args': ['1',
                                '--source',
                                'port',
                                '--rotation-slot',
                                '1',
                                '--builder',
                                'openrouter/minimax/minimax-m3.1-flash',
                                '--attacker',
                                'openrouter/deepseek/deepseek-v4.1-flash',
                                '--reviewer1',
                                'openrouter/xiaomi/mimo-v2.6-pro',
                                '--strong-calibrator',
                                'claude/claude-opus-4-5-20251101:compact',
                                '--easy-calibrator',
                                'openrouter/minimax/minimax-m3.1-flash',
                                '--ttl-hours',
                                '1',
                                '--max-spend',
                                '5']}}}


def matches(record):
    return record == EXPECTED


def active(policy, root):
    if policy.get('batch', {}).get('id') != BATCH or os.environ.get('UNBUG_PRACTICE_BATCH') != BATCH:
        return False
    if not matches(money.manifest(policy, root)): raise ValueError('request_refused')
    return True


def deadlines(start, timing=None):
    t = TIMING if timing is None else timing
    if set(t) != set(TIMING) or any(type(v) is not int or v <= 0 for v in t.values()):
        raise ValueError('invalid cleanup timing')
    collect = start + t['run_seconds']
    delete = collect + t['grace_seconds']
    ttl = start + t['ttl_seconds']
    if not start < collect < delete < ttl: raise ValueError('invalid cleanup timing')
    return collect, delete, ttl


def admission(record, now=None):
    deadlines(0)
    now = now or datetime.now(timezone.utc)
    if money.deadline(record['batch_deadline']) - now.timestamp() <= TIMING['ttl_seconds']:
        raise money.MoneyWait('cleanup window unavailable')


def fault(policy, root, home, identity, *, arm=False):
    import batch_holder as holder
    import batch_service as service
    if not active(policy, root):
        if arm: raise ValueError('request_refused')
        return
    record = money.manifest(policy, root)
    # Caller holds batch_money.locked for both arming and collection.
    directory = home / 'batches' / record['id']
    op = holder._operations(directory, record, policy)[identity]
    path = home / 'launches' / op['launch_id'] / 'publication-fault.json'
    if arm:
        if path.exists() or path.is_symlink() or op['output_generation'] is not None or not op['dispatch_started']:
            raise ValueError('request_refused')
        atomic_json(path, dict(schema=1, operation_id=identity, state='armed'))
    elif path.exists() or path.is_symlink():
        marker = service._json(path)
        if marker not in [dict(schema=1, operation_id=identity, state=s) for s in ('armed', 'consumed')]:
            raise ValueError('request_refused')
        if marker['state'] == 'armed':
            atomic_json(path, dict(marker, state='consumed'))
            raise ValueError('publication_failed')
