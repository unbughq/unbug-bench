"""Observe OpenCode, Codex or Claude Code JSON usage and stop the process group at cumulative ceilings.

Ceilings are checked after each response; in-flight requests can overshoot.
Only the exclusive local OpenCode process is supported (never --attach).
Schemas: anomalyco/opencode v2.0.26 packages/cli/src/run/noninteractive.ts;
codex-cli 0.162.1 `exec --json`; Claude Code 2.1.299 `-p --output-format stream-json --verbose`.
"""
from contextlib import contextmanager, nullcontext
import fcntl
import json
import math
import os
import re
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_CEILING
from token_prices import CODEX_PRICES, codex_cost, claude_cost


class BudgetError(RuntimeError):
    def __init__(self, message, *, provider_failure=None):
        super().__init__(message)
        self.provider_failure = provider_failure


def classify_provider_failure(text, model, *, reset_at=None, retry_after=None, now=None,
                              status_code=None, error_type=None, allow_outage=True):
    """Sanitized metadata from trusted provider diagnostics, never tool output."""
    text = text.lower()
    reason, scope = None, 'account'
    if status_code == 402 or re.search(r'insufficient[_ ]?credits|\b402\b', text):
        reason, scope = 'credit', 'wallet'
    elif status_code == 429 or 'rate limit' in text or re.search(r'\b429\b', text): reason = 'rate'
    elif ('gousagelimiterror' in text or 'usage limit' in text or 'limit reached' in text
          or re.search(r'\b(?:hit|reached|exceeded) (?:your |the )?(?:usage |rate )?limit\b', text)
          or ('weekly' in text and ('limit' in text or 'quota' in text))): reason = 'quota'
    elif allow_outage and ((type(status_code) is int and (status_code == 404 or 500 <= status_code <= 599))
          or re.sub(r'[^a-z]', '', str(error_type).lower()) in
          ('providermodelnotfounderror', 'modelnotfounderror', 'modelunavailableerror',
           'serviceunavailableerror', 'servererror', 'overloadederror')):
        reason, scope = 'outage', 'route'
    if reason is None: return None
    observation = {'reason': reason, 'scope': scope, 'model': model}
    if type(reset_at) in (int, float) and math.isfinite(reset_at) and reset_at > 0:
        observation['reset_at'] = reset_at
    elif type(retry_after) in (int, float) and math.isfinite(retry_after) and retry_after > 0:
        observation['reset_at'] = (time.time() if now is None else now) + retry_after
    return observation


def provider_diagnostic(event):
    """Extract provider fields, excluding retry counters and ordinary response prose."""
    error = event.get('error')
    rows = [event] + ([error] if isinstance(error, dict) else [])
    if isinstance(error, dict) and isinstance(error.get('data'), dict): rows.append(error['data'])
    def first(keys, predicate):
        return next((row[key] for row in rows for key in keys if key in row and predicate(row[key])), None)
    text = (first(('message', 'result'), lambda v: isinstance(v, str)) or
            (error if isinstance(error, str) else '') or first(('name',), lambda v: isinstance(v, str)) or '')
    return dict(text=text, status_code=first(('statusCode', 'status_code', 'http_status', 'error_status'), lambda v: type(v) is int),
                error_type=first(('name', 'error_type'), lambda v: isinstance(v, str)),
                reset_at=first(('resetsAt', 'reset_at', 'resetAt'), lambda v: type(v) in (int, float)),
                retry_after=first(('retry_after', 'retryAfter'), lambda v: type(v) in (int, float)))


# Codex items that end a model response (reasoning items accompany one of these).
CODEX_STEPS = ('agent_message', 'command_execution', 'file_change', 'mcp_tool_call', 'web_search', 'collab_tool_call')


def _save(path, ledger):
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(ledger, file, indent=2, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def usd(value):
    """Use the batch channel's nine-place, nonnegative decimal money unit."""
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError
        return (result if result else abs(result)).quantize(Decimal('.000000001'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise BudgetError('invalid_money') from None


@contextmanager
def ledger_transaction(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = json.loads(path.read_text()) if path.exists() else {'cost': 0, 'calls': 0, 'events': []}
        before = json.dumps(ledger, sort_keys=True)
        yield ledger
        if json.dumps(ledger, sort_keys=True) != before: _save(path, ledger)


def event_charge(event):
    values = [event.get(k, 0) for k in ('cost', 'list_cost_usd', 'estimated_subscription_cost_usd')]
    for value in values: usd(value)  # Validate, preserving receipt precision until the cumulative sum.
    return sum((Decimal(str(value)) for value in values), Decimal(0))


def _waste_amount(events, identities):
    # Same round-once arithmetic for initial attribution, validation and late
    # receipt extension. Legacy receipts can carry sub-nanodollar precision.
    return float(usd(math.fsum(float(event_charge(events[i])) for i in identities)))


def reserve_invocation(path, lease, maximum_usd, authority, *, operation_id, call_name, parent_call_name=None):
    """Reserve only an admitted lease; the caller and wrapper can safely repeat it."""
    from job_authority import JobAuthority
    if not isinstance(authority, JobAuthority): raise BudgetError('money_wait')
    usd(maximum_usd)
    maximum = Decimal(str(maximum_usd)).quantize(Decimal('.000000001'), rounding=ROUND_CEILING)
    maximum = abs(maximum) if not maximum else maximum
    limit = authority.committed_total_usd
    try:
        identity = uuid.UUID(operation_id)
        if str(identity) != operation_id or identity.version != 4: raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise BudgetError('invalid_operation') from None
    with ledger_transaction(path) as ledger:
        reservations = ledger.setdefault('invocation_reservations', {})
        prior = reservations.get(lease.lease_id)
        if prior is not None:
            if (prior['operation_id'], prior['call_name'], usd(prior['maximum_usd']), prior['parent_call_name']) != (operation_id, call_name, maximum, parent_call_name):
                raise BudgetError('reservation_mismatch')
            return dict(prior)
        total = case_spending(ledger)['total_spent_usd']
        pending = outstanding_reservations(ledger)
        if total is None or usd(total) + pending + maximum > limit:
            raise BudgetError('money_wait')
        row = {'schema_version': 1, 'invocation_id': str(uuid.uuid4()), 'operation_id': operation_id,
               'lease_id': lease.lease_id, 'route': lease.route, 'account': lease.account,
               'billing': lease.billing, 'pool': lease.pool, 'family': lease.family,
               'call_name': call_name, 'parent_call_name': parent_call_name,
               'maximum_usd': format(maximum, '.9f'), 'state': 'pending', 'event_ids': []}
        reservations[lease.lease_id] = row
        return dict(row)


def outstanding_reservations(ledger, exclude_lease=None):
    events = {e['id']: e for e in ledger.get('events', []) if e.get('id')}
    total = Decimal(0)
    for lease_id, row in ledger.get('invocation_reservations', {}).items():
        if row['state'] != 'pending' or lease_id == exclude_lease: continue
        booked = sum((event_charge(events[i]) for i in row['event_ids'] if i in events), Decimal(0))
        total += max(Decimal(0), usd(row['maximum_usd']) - booked)
    return total


def _usage_leaves(work, relative, seen=None, depth=0):
    """Expand A's aggregates, validating every path and never booking aggregate deltas."""
    seen = set() if seen is None else seen
    if not isinstance(relative, str) or depth > 64: raise BudgetError('invalid_usage_receipt')
    path = Path(relative)
    if (path.is_absolute() or not path.parts or path.parts[0] != 'usage-receipts'
            or '..' in path.parts or any((work / Path(*path.parts[:i])).is_symlink() for i in range(1, len(path.parts) + 1))):
        raise BudgetError('invalid_usage_receipt')
    key = path.as_posix()
    if key in seen: return []
    seen.add(key)
    try:
        value = json.loads((work / path).read_text())
        if not isinstance(value, dict): raise ValueError
        if 'receipts' in value:
            if not isinstance(value['receipts'], list) or not value['receipts']: raise ValueError
            return [leaf for child in value['receipts'] for leaf in _usage_leaves(work, child, seen, depth + 1)]
        if (not isinstance(value['lease_id'], str) or type(value['final_usage_known']) is not bool
                or not isinstance(value['events'], list) or not isinstance(value['booked_event_ids'], list)
                or any(not isinstance(i, str) or not i for i in value['booked_event_ids'])): raise ValueError
        return [value]
    except (OSError, ValueError, TypeError, KeyError):
        raise BudgetError('invalid_usage_receipt') from None


def _settle_leaf(ledger, receipt):
    lease_id = receipt['lease_id']
    row = ledger.get('invocation_reservations', {}).get(lease_id)
    if row is None: raise BudgetError('usage_reservation_missing')
    if row['state'] == 'settled' and not receipt['final_usage_known']:
        raise BudgetError('usage_receipt_regressed')
    events = {e['id']: e for e in ledger.get('events', []) if e.get('id')}
    ids = set(row['event_ids']) | set(receipt['booked_event_ids'])
    for event in receipt['events']:
        if not isinstance(event, dict): raise BudgetError('invalid_usage_event')
        identity = event.get('id')
        if not isinstance(identity, str) or not identity: raise BudgetError('invalid_usage_event')
        event_charge(event)
        ids.add(identity)
        if identity in events:
            if event_charge(events[identity]) != event_charge(event): raise BudgetError('usage_event_conflict')
            continue
        ledger['events'].append(event)
        events[identity] = event
        for key in ('cost', 'list_cost_usd', 'estimated_subscription_cost_usd'):
            ledger[key] = float(usd(ledger.get(key, 0)) + usd(event.get(key, 0)))
        ledger['calls'] = ledger.get('calls', 0) + event.get('calls', 1)
    if not ids <= events.keys(): raise BudgetError('usage_event_missing')
    booked = sum((event_charge(events[i]) for i in ids), Decimal(0))
    estimate = (max(Decimal(0), usd(row['maximum_usd']) - booked).quantize(Decimal('.000000001'), rounding=ROUND_CEILING)
                if not receipt['final_usage_known'] else Decimal(0))
    row.update(event_ids=sorted(ids), estimated_gap_usd=format(estimate, '.9f'),
               state='settled' if receipt['final_usage_known'] else 'estimated')
    # A later final receipt can extend a previously classified operation. Keep
    # the same attribution/record ID and recompute only its settled event sum.
    waste_records = ledger.get('infrastructure_waste', [])
    if not isinstance(waste_records, list): raise BudgetError('invalid_waste_attribution')
    for waste in waste_records:
        if not isinstance(waste, dict): raise BudgetError('invalid_waste_attribution')
        if waste.get('kind') == 'factory_bug' and (not isinstance(waste.get('operation_ids'), list)
                or not isinstance(waste.get('event_ids'), list)):
            raise BudgetError('invalid_waste_attribution')
        if waste.get('kind') == 'factory_bug' and row['operation_id'] in waste.get('operation_ids', []):
            rows = [r for r in ledger['invocation_reservations'].values() if r['operation_id'] in waste['operation_ids']]
            if all(r['state'] == 'settled' for r in rows):
                waste['event_ids'] = sorted({i for r in rows for i in r['event_ids']})
                waste['infrastructure_waste_usd'] = _waste_amount(events, waste['event_ids'])
    # Unknown invocations written by the streaming accountant are now covered by
    # this reservation. Historical entries without an invocation_id stay unknown.
    ledger['unpriced_invocations'] = [e for e in ledger.get('unpriced_invocations', [])
        if e.get('invocation_id') != row['invocation_id']]


def settle(record, *, work, ledger_path):
    """Settle a provider wait before admission; replay repairs the flag, never rebooks.

    The caller checkpoints this ledger and record together. The ledger transaction
    is first, so a kill between local writes is repaired by the wait_id marker.
    """
    work = Path(work)
    try:
        identity = str(uuid.UUID(record['wait_id']))
        if identity != record['wait_id'] or uuid.UUID(identity).version != 4: raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise BudgetError('invalid_provider_wait') from None
    leaves = _usage_leaves(work, record['call_id']) if record.get('call_id') is not None else []
    if record.get('lease_id') and not any(r['lease_id'] == record['lease_id'] for r in leaves):
        raise BudgetError('wait_receipt_mismatch')
    with ledger_transaction(ledger_path) as ledger:
        summary = case_spending(ledger)
        before = summary.get('known_total_spent_usd', summary['total_spent_usd'])
        # An owner denial may carry no call_id. The cancelled tester still has a
        # retained per-lease receipt. Include every unsettled authenticated leaf.
        included = {r['lease_id'] for r in leaves}
        for lease_id, row in ledger.get('invocation_reservations', {}).items():
            path = work / 'usage-receipts' / (lease_id + '.json')
            if row['state'] in ('pending', 'estimated') and lease_id not in included and path.is_file():
                leaves.extend(_usage_leaves(work, path.relative_to(work).as_posix()))
        for receipt in leaves: _settle_leaf(ledger, receipt)
        summary = case_spending(ledger)
        after = summary.get('known_total_spent_usd', summary['total_spent_usd'])
        ledger.setdefault('wait_settlements', {}).setdefault(identity, {'lease_ids': sorted({r['lease_id'] for r in leaves})})
    record['settled'] = True
    live = work / 'provider_wait.json'
    if live.exists(): _save(live, record)
    return round(after - before, 9)


def reclassify_factory_bug(path, record):
    """Only the diagnosis/fix-evidence validator may supply this attribution.

    This accounting layer checks shape and settled sums, not the reviewed fix's
    provenance. The coordinator must authenticate that evidence before calling.
    """
    if (not isinstance(record, dict) or not isinstance(record.get('operation_ids'), list)
            or not record['operation_ids'] or any(not isinstance(i, str) for i in record['operation_ids'])
            or not isinstance(record.get('event_ids'), list) or any(not isinstance(i, str) for i in record['event_ids'])):
        raise BudgetError('invalid_waste_attribution')
    with ledger_transaction(path) as ledger:
        if not isinstance(ledger.get('infrastructure_waste', []), list) or any(
                not isinstance(r, dict) for r in ledger.get('infrastructure_waste', [])):
            raise BudgetError('invalid_waste_attribution')
        operations = record.get('operation_ids', [])
        rows = [row for row in ledger.get('invocation_reservations', {}).values() if row['operation_id'] in operations]
        if not rows or {row['operation_id'] for row in rows} != set(operations) or any(row['state'] != 'settled' for row in rows):
            raise BudgetError('waste_operations_pending')
        existing = next((r for r in ledger.get('infrastructure_waste', []) if r.get('id') == record.get('id')), None)
        if existing is not None:
            identity = ('kind', 'schema_version', 'id', 'diagnosis_sha256', 'fix_commit', 'fix_attribution_sha256', 'operation_ids')
            if any(existing.get(k) != record.get(k) for k in identity): raise BudgetError('waste_attribution_mismatch')
            return
        ledger.setdefault('infrastructure_waste', []).append(record)
        if case_spending(ledger)['total_spent_usd'] is None: raise BudgetError('invalid_waste_attribution')


def case_spending(ledger, models_used=None):
    """Whole-case list price, including legacy events; never read transcripts.

    Totals remain authoritative for historical usage not represented by events.
    Legacy roles are attributed only when the recorded model identifies one role.
    """
    ledger = ledger or {}
    roles = {}
    for name, model in (models_used or {}).items():
        roles.setdefault(model, set()).add(invocation_role(name))
    breakdown, estimated, unpriced = {}, 0.0, len(ledger.get('unpriced_invocations', []))
    event_roles, event_costs, indexed_events = {}, {}, {}
    listed, priced = 0.0, 0.0
    for event in ledger.get('events', []):
        cost = event.get('cost', 0)
        listed_cost = event.get('list_cost_usd', 0)
        estimate = event.get('estimated_subscription_cost_usd', 0)
        model = event.get('configured_model')
        if event.get('priced') == 'subscription' and 'list_cost_usd' not in event and 'estimated_subscription_cost_usd' not in event:
            estimate = codex_cost(model, event.get('tokens', {})) if str(model).startswith('codex/') else None
            if estimate is None: unpriced += 1; estimate = 0
        if not all(_number(v) for v in (cost, listed_cost, estimate)):
            unpriced += 1; continue
        listed += listed_cost; priced += cost; estimated += estimate
        matches = roles.get(model, set())
        role = event.get('role') or (next(iter(matches)) if len(matches) == 1 else 'legacy_unattributed')
        breakdown[role] = breakdown.get(role, 0) + cost + listed_cost + estimate
        if event.get('id'):
            event_roles[event['id']] = role
            event_costs[event['id']] = cost + listed_cost + estimate
            indexed_events[event['id']] = {**event, 'estimated_subscription_cost_usd': estimate}
    for key, observed in (('cost', priced), ('list_cost_usd', listed), ('estimated_subscription_cost_usd', estimated)):
        total = ledger.get(key, observed)
        if not _number(total): unpriced += 1; continue
        if total > observed: breakdown['legacy_unattributed'] = breakdown.get('legacy_unattributed', 0) + total - observed
    # Reservation estimates are ledger entries, not fabricated provider events.
    for row in ledger.get('invocation_reservations', {}).values():
        gap = row.get('estimated_gap_usd', 0)
        try: amount = float(usd(gap))
        except BudgetError: unpriced += 1; continue
        role = invocation_role(row['call_name'])
        breakdown[role] = breakdown.get(role, 0) + amount
    breakdown = {role: round(cost, 9) for role, cost in breakdown.items()}
    known = round(sum(breakdown.values()), 9)
    waste = 0.0
    records = ledger.get('infrastructure_waste', [])
    if not isinstance(records, list):
        records = []; unpriced += 1
    classified_events, classified_operations, waste_ids = set(), set(), set()
    for record in records:
        if isinstance(record, dict) and record.get('kind') == 'factory_bug':
            try:
                ids, operations = record['event_ids'], record['operation_ids']
                related = [row for row in ledger.get('invocation_reservations', {}).values()
                           if row['operation_id'] in operations]
                valid = (record.get('schema_version') == 1 and bool(record['id']) and record['id'] not in waste_ids
                    and isinstance(ids, list) and bool(ids) and len(set(ids)) == len(ids)
                    and isinstance(operations, list) and bool(operations) and len(set(operations)) == len(operations)
                    and not set(ids) & classified_events and not set(operations) & classified_operations
                    and set(ids) <= event_costs.keys()
                    and all(re.fullmatch(r'[0-9a-f]{64}', record[k]) for k in ('diagnosis_sha256', 'fix_attribution_sha256'))
                    and re.fullmatch(r'[0-9a-f]{40}', record['fix_commit']) is not None
                    and usd(record['infrastructure_waste_usd']) == usd(_waste_amount(indexed_events, ids))
                    and {row['operation_id'] for row in related} == set(operations)
                    and set(ids) == {i for row in ledger.get('invocation_reservations', {}).values()
                        if row['operation_id'] in operations and row['state'] == 'settled' for i in row['event_ids']})
                if valid:
                    for identity in ids:
                        role = event_roles[identity]
                        breakdown[role] -= event_costs[identity]
                    amount = _waste_amount(indexed_events, ids)
                    known = round(known - amount, 9) + 0.0
                    waste += amount
                    classified_events.update(ids); classified_operations.update(operations); waste_ids.add(record['id'])
                else: unpriced += 1
            except (KeyError, TypeError, ValueError, BudgetError):
                unpriced += 1
            continue
        # Only an explicit, evidenced kill correction belongs here. Unknown
        # invocations still fail closed; this never removes them implicitly.
        try:
            evidence = record['derivation']
            maximum = evidence['maximum_observed_writer_list_cost_usd']
            elapsed = evidence['completed_writer_elapsed_seconds']
            killed = evidence['interrupted_seconds']
            amount = record['infrastructure_waste_usd']
            valid = (record['kind'] == 'infrastructure_kill' and bool(record['reason']) and
                     all(_number(v) and v > 0 for v in (maximum, elapsed, killed, amount)) and
                     amount == math.ceil(max(maximum, maximum / elapsed * killed)) and
                     evidence['ledger_events_before'] == evidence['ledger_events_after'] and
                     all(re.fullmatch(r'[0-9a-f]{64}', evidence[k]) for k in ('card_sha256', 'checkpoint_sha256')))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            valid = False
        if not valid: unpriced += 1
        # Retain even a malformed record's numeric amount in the visible total.
        if isinstance(record, dict) and _number(record.get('infrastructure_waste_usd')):
            waste += record['infrastructure_waste_usd']
    waste = round(waste, 9)
    breakdown = {role: round(cost, 9) + 0.0 for role, cost in breakdown.items()}
    return {'spent_usd': None if unpriced else known, 'breakdown_by_role': breakdown,
            'infrastructure_waste_usd': waste, 'infrastructure_waste': records,
            'total_spent_usd': None if unpriced else round(known + waste, 9),
            **({'unpriced_events': unpriced, 'known_spent_usd': known,
                'known_total_spent_usd': round(known + waste, 9)} if unpriced else {})}


def invocation_role(name):
    return ('writer' if name.startswith('builder') else 'stress_tester' if name.startswith('attacker') else
            'strong_calibrator' if name.startswith('strong-calibrator') else 'easy_calibrator' if name.startswith('easy-calibrator') else
            'reviewer2' if name.startswith('reviewer-2') else 'reviewer')


def require_case_budget(ledger, limit, configured_model=None):
    spent = case_spending(ledger)['spent_usd']
    if spent is None or spent >= limit or (str(configured_model).startswith('codex/') and configured_model not in CODEX_PRICES):
        raise BudgetError('budget_exhausted')


def tool_cpu_ticks(sid):
    """CPU ticks used by the processes in session `sid` other than its leader (the model CLI): the tool
    commands it runs. None where /proc is unavailable (then silence alone decides)."""
    if not os.path.isdir('/proc/self'): return None
    total = 0
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == sid: continue
        try: fields = open(f'/proc/{pid}/stat').read().rsplit(')', 1)[1].split()
        except OSError: continue
        if int(fields[3]) == sid: total += int(fields[11]) + int(fields[12]) + int(fields[13]) + int(fields[14])
    return total


@contextmanager
def _activity(path, resume=False):
    """Protect admission and non-atomic EX→SH conversion separately from execution."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".admission.lock", "a") as admission, open(str(path) + ".activity.lock", "a") as lock:
        deadline = time.monotonic() + 10
        while True:
            fcntl.flock(admission, fcntl.LOCK_EX)
            if not resume:
                fcntl.flock(lock, fcntl.LOCK_SH)
                break
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                # Another caller may already have resumed the stopped generation.
                # Join it without erasing its registrations or resetting its limits.
                fcntl.flock(lock, fcntl.LOCK_SH)
                with open(str(path) + '.lock', 'a') as ledger_lock:
                    fcntl.flock(ledger_lock, fcntl.LOCK_EX)
                    ledger = json.loads(path.read_text()) if path.exists() else {}
                    if ledger.get('terminal_stop') in (None, 'running', 'complete'):
                        resume = False
                        break
                fcntl.flock(lock, fcntl.LOCK_UN)
                fcntl.flock(admission, fcntl.LOCK_UN)
                if time.monotonic() >= deadline:
                    raise BudgetError('resume_while_active') from None
                time.sleep(.01)
        # The caller releases admission only after registration and the shared
        # lease are established. flock conversion can momentarily drop EX on Linux.
        yield lock, resume, admission


def resume_ledger(ledger_path):
    """The resume handshake alone, no process: record the previous run's stop and clear it, so the first model calls of a
    resumed run may start in parallel (2026-10-20: a resume whose first calls were G10 ran both testers serially)."""
    path = Path(ledger_path)
    if not path.exists(): return
    with _activity(path, resume=True) as (_, reset, _), open(str(path) + '.lock', 'a') as lock:
        if not reset: return
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = json.loads(path.read_text())
        previous = ledger.get('terminal_stop')
        if previous not in (None, 'complete'): ledger.setdefault('previous_stops', []).append(previous)
        ledger['terminal_stop'], ledger['zero_token_streak'] = None, 0
        ledger.pop('active', None)
        _save(path, ledger)


def run_budgeted(cmd, cwd, env, transcript_path, ledger_path, timeout,
                 max_cost=3.0, max_calls=100, max_total_calls=300, driver='opencode',
                 progress_timeout=15 * 60, max_zero_tokens=3, configured_model=None, resume=False, concurrent=False, cancel=None, case_budget=50.0, role=None, invocation_name=None):
    # Preserve the original whole-session lock unless concurrency is explicitly enabled.
    settings = locals()
    path = Path(ledger_path)
    with _activity(path, resume=resume) as (activity, reset, admission):
        settings["resume"] = reset
        if concurrent: return _run_budgeted(**settings, _activity_lock=activity, _admission_lock=admission)
        with open(str(path) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _run_budgeted(**settings, _serial_lock=lock, _activity_lock=activity, _admission_lock=admission)


def _run_budgeted(cmd, cwd, env, transcript_path, ledger_path, timeout,
                 max_cost=3.0, max_calls=100, max_total_calls=300, driver='opencode',
                 progress_timeout=15 * 60, max_zero_tokens=3, configured_model=None, resume=False, concurrent=False, cancel=None, case_budget=50.0, role=None, invocation_name=None, _serial_lock=None, _activity_lock=None, _admission_lock=None):
    """Return CompletedProcess, or raise BudgetError without exposing transcript text.

    max_calls limits this invocation; max_total_calls and max_cost span roles.
    max_cost counts priced (opencode) events only: codex/claude are subscriptions
    (Claude list-price totals and estimated Codex token costs recorded separately).
    case_budget is checked only before a role starts; an in-flight role finishes.
    Ledger contains usage metadata only. A terminal failure is sticky unless explicitly
    resumed; resuming preserves all costs/calls and archives the previous stop.
    """
    if driver not in ('opencode', 'codex', 'claude'):
        raise ValueError('Unknown driver')
    if not all(_number(v) for v in (max_cost, max_calls, timeout, max_total_calls, progress_timeout, case_budget)) or not isinstance(max_zero_tokens, int) or max_zero_tokens < 1:
        raise ValueError('Budget ceilings and timeout must be finite and nonnegative')
    if '--attach' in cmd or any(str(arg).startswith('--attach=') for arg in cmd):
        raise ValueError('Budget enforcement requires an exclusive local process')
    if configured_model is None:
        for index, arg in enumerate(cmd[:-1]):
            if arg in ('-m', '--model'): configured_model = cmd[index + 1]
        if driver == 'codex' and not str(configured_model).startswith('codex/'):
            configured_model = 'codex/' + (configured_model or 'unknown')
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger = None
    invocation = uuid.uuid4().hex

    @contextmanager
    def transaction():
        nonlocal ledger
        with (nullcontext(_serial_lock) if _serial_lock is not None else open(str(path) + '.lock', 'a')) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ledger = json.loads(path.read_text()) if path.exists() else {
                'cost': 0.0, 'calls': 0, 'events': [], 'terminal_stop': None,
            }
            before = json.dumps(ledger, sort_keys=True)
            try:
                yield
            finally:
                if json.dumps(ledger, sort_keys=True) != before: _save(path, ledger)

    def shared_stop():
        previous = ledger.get('terminal_stop')
        if previous not in (None, 'running', 'complete'):
            raise BudgetError(previous)
        if cancel is not None and cancel.is_set(): raise BudgetError('cancelled')

    with transaction():
        if (not _number(ledger.get('cost')) or not _number(ledger.get('calls'))
                or not isinstance(ledger.get('events'), list)):
            raise BudgetError('Invalid budget ledger; no process started')
        require_case_budget(ledger, case_budget, configured_model)
        previous = ledger.get('terminal_stop')
        if previous not in (None, 'complete') and not (concurrent and previous == 'running' and not resume):
            if not resume: raise BudgetError('Budget ledger stopped: ' + str(previous))
            ledger.setdefault('previous_stops', []).append(previous)
        if resume:
            ledger['zero_token_streak'] = 0
            ledger.pop('active', None)
        cause = ('cost_limit' if ledger['cost'] >= max_cost else
                 'total_call_limit' if ledger['calls'] >= max_total_calls else
                 'call_limit' if max_calls == 0 else
                 'timeout' if timeout == 0 else
                 'stalled' if progress_timeout == 0 else None)
        if cause:
            ledger['terminal_stop'] = cause
            raise BudgetError('Budget stopped: ' + cause)
        ledger['terminal_stop'] = 'running'
        if concurrent: ledger.setdefault('active', []).append(invocation)
    if _activity_lock is not None:
        fcntl.flock(_activity_lock, fcntl.LOCK_SH)
    if _admission_lock is not None:
        fcntl.flock(_admission_lock, fcntl.LOCK_UN)
    seen = {item['id'] for item in ledger['events']}
    provider_model = configured_model or driver + '/unknown'
    with transaction():
        ledger.update(driver=driver, configured_model=configured_model)
        ledger.pop('provider_failure', None)
    rate_limits = 0
    starts, finishes, responses = set(), set(), set()
    partial_usage = {}
    count = usages = 0
    session = {'id': '', 'turns': 0}
    process = None
    stopped = False
    collecting_usage = False
    pending = b''
    selector = selectors.DefaultSelector()
    last_output = time.monotonic()
    deadline = last_output + timeout
    started_utc, log_checked = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()), last_output

    def silent_limit():
        # OpenCode 1.19 prints nothing and retries forever on a Go usage limit; only its log says so (2026-10-19).
        try: logs = list(Path(env.get('XDG_DATA_HOME') or Path.home() / '.local/share', 'opencode/log').glob('*.log'))
        except OSError: return  # an isolated tester's private log dir: silence alone decides, as before
        for log in logs:
            try: lines = log.read_text(errors='replace').splitlines()[-2000:]
            except OSError: continue
            if any('usage limit exceeded' in l.lower() and l[10:29] >= started_utc for l in lines if l.startswith('timestamp=')):
                raise BudgetError('provider_limit:' + provider_model, provider_failure=classify_provider_failure('usage limit', provider_model))

    def check_limits():
        if collecting_usage: return  # accounting buffered output after the process was stopped
        if ledger['cost'] >= max_cost:
            raise BudgetError('cost_limit')
        if ledger['calls'] >= max_total_calls:
            raise BudgetError('total_call_limit')
        if count >= max_calls:
            raise BudgetError('call_limit')

    def tokens_seen(tokens):
        nonlocal rate_limits
        ledger['zero_token_streak'] = 0 if any(tokens) else ledger.get('zero_token_streak', 0) + 1
        if any(tokens): rate_limits = 0
        _save(path, ledger)
        if not collecting_usage and ledger['zero_token_streak'] >= max_zero_tokens: raise BudgetError('zero_tokens')

    def diagnostic(text, response=False, partial=False, reset_at=None, retry_after=None, status_code=None, error_type=None, allow_outage=True, shared=False):
        nonlocal rate_limits
        text = text.lower()
        if driver == 'codex' and not response and (('refresh token' in text and any(s in text for s in (
                'already used', 'expired', 'revoked', 'invalidated', 'could not be refreshed')))
                or 'refresh_token_reused' in text or 'refresh_token_expired' in text
                or 'refresh_token_invalidated' in text
                or 'access token could not be refreshed' in text
                or 'workspace routing discovery unauthorized' in text
                or 'authentication token has expired' in text
                or ('401' in text and ('unauthorized' in text or 'authentication' in text))):
            raise BudgetError('codex_login_expired', provider_failure={'reason': 'credential_expiring', 'scope': 'account',
                'model': provider_model})  # The CLI's exact login-expiry diagnostic is trusted metadata.
        if driver == 'codex' and 'cybersecurity' in text and any(w in text for w in ('flagged', 'refus', "can't", 'cannot')):
            raise BudgetError('refusal:' + provider_model)
        if response: return False  # Assistant prose cannot establish provider health.
        observation = classify_provider_failure(text, provider_model, reset_at=reset_at, retry_after=retry_after,
            status_code=status_code, error_type=error_type, allow_outage=allow_outage and not response)
        if observation:
            if not shared: observation['per_call'] = True
            if observation['reason'] == 'rate':
                if partial: return False
                rate_limits += 1
                if rate_limits < 2 and not provider_model.startswith('openrouter/'): return True
            label = 'process_error' if observation['reason'] == 'outage' else 'provider_limit:' + provider_model
            raise BudgetError(label, provider_failure=observation)
        return False

    def call():
        """A subscription CLI's model response: counted live, usage arrives per turn/run."""
        nonlocal count
        count += 1
        ledger['calls'] += 1
        _save(path, ledger)
        check_limits()

    def subscription_usage(identity, usage, required, list_cost=None, partial=False):
        """Tokens recorded at cost 0, priced 'subscription' (exempt from unpriced_usage)."""
        nonlocal usages
        if not isinstance(usage, dict) or not all(_number(usage.get(k)) for k in required):
            raise BudgetError('missing_usage')
        estimate = (codex_cost(configured_model, usage) if driver == 'codex' else
                    claude_cost(configured_model, usage) if partial else None)
        if (driver == 'codex' or partial) and estimate is None: raise BudgetError('missing_usage')
        finishes.add(identity)
        if identity in seen:
            return
        seen.add(identity)
        usages += 1
        record = {'id': identity, 'cost': 0, 'priced': 'subscription', 'tokens': usage,
                  'configured_model': configured_model, 'calls': count}
        record.update(role=role or 'legacy_unattributed', invocation=invocation_name)
        if partial: record['estimated_from_partial_usage'] = True
        if estimate is not None:
            record['estimated_subscription_cost_usd'] = estimate
            ledger['estimated_subscription_cost_usd'] = ledger.get('estimated_subscription_cost_usd', 0) + estimate
        if list_cost is not None:
            record['list_cost_usd'] = list_cost
            ledger['list_cost_usd'] = ledger.get('list_cost_usd', 0) + list_cost
        ledger['events'].append(record)
        if driver == 'codex': tokens_seen([v for k, v in usage.items() if k.endswith('_tokens') and _number(v)])
        else: _save(path, ledger)
        check_limits()

    def consume_codex(event):
        # 'error' events are retry notices ("Reconnecting..."); turn.failed is terminal.
        kind = event.get('type')
        usage = event.get('usage') or (event.get('item') or {}).get('usage')
        if isinstance(usage, dict):
            partial_usage[session['id'] + ':turn-' + str(session['turns'])] = usage
        if kind == 'thread.started':
            session['id'] = str(event.get('thread_id', ''))
        elif kind == 'turn.started':
            session['turns'] += 1
            starts.add(session['id'] + ':turn-' + str(session['turns']))
        elif kind == 'turn.failed':
            raise BudgetError('codex_error')
        elif kind == 'item.completed' and (event.get('item') or {}).get('type') in CODEX_STEPS:
            # ponytail: exec --json has no per-response usage; parallel tool calls overcount, so limits stop early, never late.
            call()
        elif kind == 'turn.completed':
            subscription_usage(session['id'] + ':turn-' + str(session['turns']), event.get('usage'),
                               ('input_tokens', 'cached_input_tokens', 'output_tokens'))

    def consume_claude(event):
        kind = event.get('type')
        if kind == 'system' and event.get('subtype') == 'init':
            session['id'] = str(event.get('session_id', ''))
            starts.add(session['id'] + ':result')
        elif kind == 'assistant':
            message = event.get('message')
            if not isinstance(message, dict) or not message.get('id') or not isinstance(message.get('usage'), dict):
                starts.add('unverified-stream-usage:' + invocation)
                raise BudgetError('missing_usage')
            key = session['id'] + ':' + str(message['id'])
            usage = message['usage']
            required = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
            if not all(_number(usage.get(k)) for k in required):
                starts.add('unverified-stream-usage:' + invocation)
                raise BudgetError('missing_usage')
            # A message can have several content blocks with growing usage.
            prior = partial_usage.setdefault(key, {})
            for k in required: prior[k] = max(prior.get(k, 0), usage[k])
            if key not in responses:  # one response streams as one event per content block
                responses.add(key)
                call()
                tokens_seen([usage[k] for k in required])
        elif kind == 'result':
            if event.get('is_error'):  # API errors arrive as subtype 'success' with is_error
                raise BudgetError('claude_error')
            if not _number(event.get('total_cost_usd')):
                starts.add('unverified-stream-usage:' + invocation)
                raise BudgetError('missing_usage')
            usage = event.get('usage')
            if not isinstance(usage, dict) or not all(_number(usage.get(k)) for k in
                    ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')):
                starts.add('unverified-stream-usage:' + invocation)
                raise BudgetError('missing_usage')
            subscription_usage(str(event.get('session_id') or session['id']) + ':result', event.get('usage'),
                               ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
                                'cache_creation_input_tokens'), list_cost=event['total_cost_usd'])

    def consume(line):
        nonlocal count, usages
        try:
            event = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            diagnostic(line.decode(errors='replace') if isinstance(line, bytes) else line)
            return  # Non-JSON diagnostics stay in the sealed transcript.
        if not isinstance(event, dict):
            return
        kind = event.get('type')
        if driver == 'claude' and kind == 'rate_limit_event':
            # Claude names its window reset; a limited case resumes then instead of guessing (2026-10-19).
            info = event.get('rate_limit_info') or {}
            if _number(info.get('resetsAt')): ledger['claude_resets_at'] = info['resetsAt']
            if info.get('status') == 'rejected':
                raise BudgetError('provider_limit:' + provider_model, provider_failure=classify_provider_failure('usage limit', provider_model, reset_at=info.get('resetsAt')))
        if driver == 'claude' and event.get('error') in ('rate_limit', 'usage_limit'):
            raise BudgetError('provider_limit:' + provider_model, provider_failure=classify_provider_failure('usage limit', provider_model))
        # Never scan tool output or echoed command/prompt text for provider errors.
        if kind == 'error' or (kind == 'system' and event.get('subtype') in ('error', 'api_retry', 'retry')) or (kind == 'result' and event.get('is_error')) or (driver == 'claude' and kind == 'assistant' and event.get('error')):
            info = provider_diagnostic(event)
            if diagnostic(**info, allow_outage=kind != 'system', shared=True): return
        elif driver == 'claude' and kind == 'result':
            diagnostic(str(event.get('result', '')), response=True)
        elif driver == 'codex' and kind == 'turn.failed':
            diagnostic(**provider_diagnostic(event), shared=True)
        elif driver == 'codex' and kind == 'item.completed' and (event.get('item') or {}).get('type') == 'agent_message':
            diagnostic(str(event['item'].get('text', '')), response=True)
        elif driver == 'opencode' and kind == 'text':
            diagnostic(str((event.get('part') or {}).get('text', '')), response=True)
        if driver == 'codex':
            return consume_codex(event)
        if driver == 'claude':
            return consume_claude(event)
        kind, part = event.get('type'), event.get('part', {})
        if kind == 'error':
            raise BudgetError('opencode_error')
        if kind not in ('step_start', 'step_finish'):
            return
        if not isinstance(part, dict) or not part.get('messageID'):
            raise BudgetError('invalid_usage')
        key = str(event.get('sessionID', part.get('sessionID', ''))) + ':' + part['messageID']
        if kind == 'step_start':
            starts.add(key)
            return
        identity = key + ':' + str(part.get('id', ''))
        if identity in seen:
            finishes.add(key)
            return
        tokens = part.get('tokens')
        if (not part.get('id') or not _number(part.get('cost'))
                or not isinstance(tokens, dict) or not isinstance(tokens.get('cache'), dict)
                or not all(_number(tokens.get(k)) for k in ('input', 'output', 'reasoning'))
                or not all(_number(tokens['cache'].get(k)) for k in ('read', 'write'))):
            raise BudgetError('missing_usage')
        seen.add(identity)
        finishes.add(key)
        count += 1
        usages += 1
        ledger['cost'] += part['cost']
        ledger['calls'] += 1
        ledger['events'].append({
            'id': identity, 'cost': part['cost'], 'tokens': tokens,
            'role': role or 'legacy_unattributed', 'invocation': invocation_name,
            'configured_model': configured_model,
            'model': part.get('model', event.get('model')),
            'modelID': part.get('modelID', event.get('modelID')),
            'providerID': part.get('providerID', event.get('providerID')),
        })
        tokens_seen([tokens[k] for k in ('input', 'output', 'reasoning')] + list(tokens['cache'].values()))
        if (part['cost'] == 0 and any([tokens[k] for k in ('input', 'output', 'reasoning')]
                                           + list(tokens['cache'].values()))
                and not str(configured_model).endswith((':free', '-free'))):
            raise BudgetError('unpriced_usage')
        check_limits()

    def stop_process():
        nonlocal stopped
        if process is not None and not stopped:
            # Kill descendants even if their immediate parent already exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                # Darwin can report EPERM after the group has already exited.
                # A live sudo/pilot child may instead require privileged cancellation.
                if process.poll() is None:
                    try:
                        cancellation = subprocess.run(
                            ['sudo', '-n', '/bin/kill', '-KILL', '--', f'-{process.pid}'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                        if cancellation.returncode and process.poll() is None:
                            raise BudgetError('cancellation_failed')
                    except (OSError, subprocess.TimeoutExpired) as error:
                        raise BudgetError('cancellation_failed') from error
            finally:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    raise BudgetError('cancellation_failed') from None
            stopped = True

    try:
        with open(transcript_path, 'wb') as transcript:
            process = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       start_new_session=True)  # codex exec waits on an open stdin
            selector.register(process.stdout, selectors.EVENT_READ)
            pending = b''
            tool_cpu = tool_cpu_ticks(process.pid)
            while selector.get_map() or process.poll() is None:
                with transaction():
                    shared_stop()
                    check_limits()
                now = time.monotonic()
                if driver == 'opencode' and min(now - last_output, now - log_checked) >= min(60, progress_timeout / 2):
                    log_checked = now; silent_limit()
                if now - last_output >= progress_timeout:
                    # A long tool call (e.g. five strategy runs in one shell command) prints nothing until it
                    # ends; CPU used by the CLI's child processes counts as progress. --agent-timeout still caps.
                    cpu = tool_cpu_ticks(process.pid)
                    if cpu is None or cpu == tool_cpu: raise BudgetError("stalled")  # a child that ended also changes it
                    tool_cpu, last_output = cpu, now
                remaining = deadline - now
                if remaining <= 0:
                    raise BudgetError('timeout')
                for key, _ in selector.select(min(remaining, progress_timeout - (now - last_output), 0.1)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    last_output = time.monotonic()
                    transcript.write(chunk)
                    transcript.flush()
                    pending += chunk
                    while b'\n' in pending:
                        with transaction():
                            shared_stop()
                            seen.update(item["id"] for item in ledger["events"])
                            line, pending = pending.split(b'\n', 1)
                            consume(line)
                    if pending and not pending.lstrip().startswith(b'{'):
                        diagnostic(pending.decode(errors='replace'), partial=True)
            if pending:
                with transaction():
                    shared_stop()
                    seen.update(item["id"] for item in ledger["events"])
                    line, pending = pending, b''
                    consume(line)
            try:
                returncode = process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise BudgetError('timeout') from None
            if returncode:
                raise BudgetError('process_error')
            if not usages or starts - finishes:
                raise BudgetError('missing_usage')
            with transaction():
                shared_stop()
                if concurrent: ledger['active'].remove(invocation)
                ledger['terminal_stop'] = 'running' if ledger.get('active') else 'complete'
                if not ledger.get('active'): ledger.pop('active', None)
            return subprocess.CompletedProcess(cmd, returncode)
    except BaseException as error:
        if (process is not None and driver in ('codex', 'claude')
                and isinstance(error, BudgetError)
                and str(error) in ('call_limit', 'total_call_limit', 'cost_limit', 'timeout')):
            # Stop first: collecting usage must never grant another model response.
            # Only drain bytes already emitted; no grace period for a missing receipt.
            try:
                stop_process()
            except BaseException as cleanup_error:
                # Cancellation is part of the accounting boundary. A failed stop
                # cannot bypass the durable unknown-usage record below, even if
                # this invocation already recorded an earlier complete turn.
                starts.add('cancellation-failed:' + invocation)
                with transaction():
                    ledger.setdefault('cleanup_errors', []).append({
                        'stage':'process_cancellation', 'error':type(cleanup_error).__name__})
                if isinstance(cleanup_error, Exception):
                    pass  # Keep the first stop; unknown usage still blocks recovery.
                else:
                    error = cleanup_error
            else:
                collecting_usage = True
                complete = True
                try:
                    os.set_blocking(process.stdout.fileno(), False)
                    buffered = 0
                    while True:
                        try: chunk = os.read(process.stdout.fileno(), 65536)
                        except BlockingIOError:
                            complete = False
                            break
                        if not chunk: break
                        with open(transcript_path, 'ab') as transcript: transcript.write(chunk)
                        pending += chunk
                        buffered += len(chunk)
                        if buffered >= 4 * 1024 * 1024:
                            complete = False
                            break
                    for line in pending.splitlines():
                        try:
                            # A killed writer may leave half of a new event after a
                            # valid receipt; do not silently price that tail as zero.
                            if line.lstrip().startswith((b'{', b'[')):
                                if not isinstance(json.loads(line), dict):
                                    raise ValueError('invalid buffered event')
                            with transaction():
                                seen.update(item['id'] for item in ledger['events'])
                                consume(line)
                        except Exception:
                            # Unexpected JSON shapes and oversized numbers must
                            # still reach durable unknown-usage bookkeeping.
                            complete = False
                    pending = b''
                except (OSError, ValueError, TypeError):
                    complete = False
                finally:
                    collecting_usage = False
                if not complete:
                    # An unread/malformed tail could contain another unpriced turn.
                    starts.add('unverified-buffered-usage:' + invocation)
        with transaction():
            collecting_usage = True
            try:
                if driver == 'claude':
                    required = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
                    sessions = {key.rsplit(':', 1)[0] for key in partial_usage}
                    for sid in sessions:
                        identity = sid + ':result'
                        if identity in finishes: continue
                        values = [v for key, v in partial_usage.items() if key.rsplit(':', 1)[0] == sid]
                        usage = {k: sum(v[k] for v in values) for k in required}
                        subscription_usage(identity, usage, required, partial=True)
                elif driver == 'codex':
                    for identity, usage in partial_usage.items():
                        if identity not in finishes:
                            subscription_usage(identity, usage, ('input_tokens', 'cached_input_tokens', 'output_tokens'), partial=True)
            except BudgetError:
                pass  # Unknown model or invalid partial usage remains fail-closed below.
            finally:
                collecting_usage = False
            if driver in ('codex', 'claude') and (starts - finishes or (process is not None and not usages)):
                ledger.setdefault('unpriced_invocations', []).append({'role': role, 'model': configured_model})
            if invocation in ledger.get('active', []): ledger['active'].remove(invocation)
            if not ledger.get('active'): ledger.pop('active', None)
            if ledger.get('terminal_stop') in (None, 'running', 'complete'):
                ledger['terminal_stop'] = str(error) if isinstance(error, BudgetError) else type(error).__name__
                if getattr(error, 'provider_failure', None): ledger['provider_failure'] = error.provider_failure
                if isinstance(error, BudgetError) and str(error) == 'process_error':
                    # Keep the last natural CLI failure diagnosable without exposing transcript text.
                    ledger['last_process_error'] = {'returncode': process.returncode, 'driver': driver,
                                                    'configured_model': configured_model}
        raise error
    finally:
        original = sys.exc_info()[1]
        selector.close()
        try:
            stop_process()
        except Exception as cleanup_error:
            with transaction():
                ledger.setdefault('cleanup_errors', []).append({
                    'stage':'process_cancellation', 'error':type(cleanup_error).__name__})
                # A failure on the success path is itself a stop; never return success.
                if original is None: ledger['terminal_stop'] = 'cancellation_failed'
            if original is None: raise BudgetError('cancellation_failed') from cleanup_error
        finally:
            if process is not None: process.stdout.close()
