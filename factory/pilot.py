"""Offline pilot admission policy. No activation pin or deployment is supplied."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import os

import batch_money as money
import practice


def managed(policy):
    return str(policy.get('batch', {}).get('id', '')).startswith('b-pilot-')


def pin(policy):
    batch = policy['batch']
    return ':'.join(batch[k] for k in ('id', 'manifest_sha256', 'sha256'))


def validate(record):
    try:
        money.check_manifest(record)
        bounds = record['pilot_admission']
        if (not record['id'].startswith('b-pilot-') or
                set(bounds) != {'schema', 'starts_at', 'max_lifecycles', 'max_lifecycles_per_case', 'infrastructure_limit_usd'} or
                any(type(bounds[k]) is not int or bounds[k] != v for k, v in
                    (('schema', 1), ('max_lifecycles', 6), ('max_lifecycles_per_case', 2))) or
                record['max_concurrency'] != 1 or record['target_slots'] != 3 or
                record.get('replacement_policy') != {'schema': 1, 'enabled': False} or
                'practice_admission' in record or 'carry_from' in record or len(record['jobs']) != 3):
            raise ValueError()
        cap = money.amount(bounds['infrastructure_limit_usd'])
        duration = money.deadline(record['batch_deadline']) - money.deadline(bounds['starts_at'])
        if cap <= 0 or not 0 < duration <= 6 * 3600: raise ValueError()
        if sum(money.amount(j['requested_total_usd']) for j in record['jobs'].values()) > money.amount(record['money_limit_usd']):
            raise ValueError()
        forbidden = {'--dry-run', '--restore', '--restore-review', '--resume', '--reuse-review-worker',
                     '--ttl-continuation', '--continue-g11-review', '--probe', '--skip-build', '--statement-only'}
        for job in record['jobs'].values():
            args = job['args']
            if not isinstance(args, list) or any(not isinstance(a, str) for a in args): raise ValueError()
            if args[:1] != ['1'] or any(a.split('=', 1)[0] in forbidden for a in args): raise ValueError()
            for flag, expected in (('--ttl-hours', Decimal(1)), ('--max-spend', Decimal(cap) / 10**9)):
                positions = [i for i, a in enumerate(args) if a.split('=', 1)[0] == flag]
                if len(positions) != 1: raise ValueError()
                i = positions[0]
                if args[i] != flag or i + 1 >= len(args) or Decimal(args[i + 1]) != expected: raise ValueError()
        practice.deadlines(0)
        return record
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise ValueError('request_refused') from None


def active(policy, root):
    if not managed(policy) or os.environ.get('UNBUG_PILOT_PIN') != pin(policy): return False
    validate(money.manifest(policy, root))
    return True


def admission(record, now=None):
    validate(record)
    now = now or datetime.now(timezone.utc)
    if now.timestamp() < money.deadline(record['pilot_admission']['starts_at']):
        raise money.MoneyWait('pilot_window_closed')
    try: practice.admission(record, now)
    except money.MoneyWait: raise money.MoneyWait('pilot_window_closed') from None


def history(record, ops, identity=None, name=None):
    bounds = record['pilot_admission']
    counts = {job: sum(o['job'] == job for o in ops.values()) for job in record['jobs']}
    if len(ops) > bounds['max_lifecycles'] or any(n > bounds['max_lifecycles_per_case'] for n in counts.values()):
        raise ValueError('request_refused')
    if identity is not None and identity not in ops and (len(ops) >= bounds['max_lifecycles'] or
            counts[name] >= bounds['max_lifecycles_per_case']):
        raise money.MoneyWait('pilot_lifecycle_limit')
