"""Observe OpenCode, Codex or Claude Code JSON usage and stop the process group at cumulative ceilings.

Legacy observed ceilings can overshoot in flight. Engine calls instead
reserve a gated Lease maximum before launch; receipts settle actual usage.
Only the exclusive local OpenCode process is supported (never --attach).
Schemas: anomalyco/opencode v2.0.26 packages/cli/src/run/noninteractive.ts;
codex-cli 0.162.1 `exec --json`; Claude Code 2.1.299 `-p --output-format stream-json --verbose`.
"""
from contextlib import contextmanager, nullcontext
import fcntl
import hashlib
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
from token_prices import CODEX_PRICES, CODEX_USAGE_FIELDS, codex_cost, codex_request_usages, claude_cost, claude_standard_usage
from token_prices import GO_ROUTES, go_step_cost


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
    if reason == 'outage' and (status_code == 404 or re.sub(r'[^a-z]', '', str(error_type).lower()) in
            ('providermodelnotfounderror', 'modelnotfounderror', 'modelunavailableerror')):
        observation['source_stop'] = 'model_unavailable'
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


# How often a Codex call's own session logs are read for its per-request usage (usage_feed).
CODEX_FEED_SECONDS = 5
CODEX_FEED_FAILURES = 3                         # unreadable polls in a row before the call stops
CODEX_TURN_READS, CODEX_TURN_READ_PAUSE = 3, 0.5  # reads at a turn's end while the log lags its total

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
        if isinstance(value, str) and not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?', value):
            raise ValueError
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
    values = _event_components(event)
    return sum((Decimal(str(value)) for value in values), Decimal(0))


def _event_components(event):
    values = [event.get(k, 0) for k in ('cost', 'list_cost_usd', 'estimated_subscription_cost_usd')]
    if event.get('priced') == 'subscription' and 'list_cost_usd' not in event and 'estimated_subscription_cost_usd' not in event:
        values[2] = codex_cost(event.get('configured_model'), event.get('tokens', {}))
    if not all(_number(value) for value in values): raise BudgetError('invalid_usage_price')
    return values


def _waste_amount(events, identities):
    # Same round-once arithmetic for initial attribution, validation and late
    # receipt extension. Legacy receipts can carry sub-nanodollar precision.
    return sum((event_charge(events[i]) for i in identities), Decimal(0))


def reserve_invocation(path, lease, maximum_usd, *, attempt, operation_id, call_name, parent_call_name=None):
    """Reserve only an admitted lease; the caller and wrapper can safely repeat it."""
    usd(maximum_usd)
    maximum = Decimal(str(maximum_usd)).quantize(Decimal('.000000001'), rounding=ROUND_CEILING)
    maximum = abs(maximum) if not maximum else maximum
    try:
        identity = uuid.UUID(operation_id)
        if str(identity) != operation_id or identity.version != 4: raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise BudgetError('invalid_operation') from None
    with ledger_transaction(path) as ledger:
        limit = attempt_limit(ledger, attempt)
        reservations = ledger.setdefault('invocation_reservations', {})
        prior = reservations.get(lease.lease_id)
        if prior is not None:
            if (prior['operation_id'], prior['call_name'], usd(prior['maximum_usd']), prior['parent_call_name']) != (operation_id, call_name, maximum, parent_call_name):
                raise BudgetError('reservation_mismatch')
            return dict(prior)
        total = case_spending(ledger)['total_spent_usd']
        pending = outstanding_reservations(ledger)
        if total is None or usd(total) + pending + maximum > limit:
            raise BudgetError('budget_exhausted:grant_insufficient')
        row = {'schema_version': 1, 'invocation_id': str(uuid.uuid4()), 'operation_id': operation_id,
               'lease_id': lease.lease_id, 'route': lease.route, 'account': lease.account,
               'billing': lease.billing, 'pool': lease.pool, 'family': lease.family,
               'call_name': call_name, 'parent_call_name': parent_call_name,
               'maximum_usd': format(maximum, '.9f'), 'state': 'pending', 'event_ids': []}
        reservations[lease.lease_id] = row
        return dict(row)


def attempt_limit(ledger, attempt):
    """Persist the cumulative baseline once per attempt, across parallel calls and replay.

    Use worker_step.usage_since's valuation, including infrastructure waste;
    historical spending does not consume a fresh batch-funded grant.
    """
    total = case_spending(ledger)['total_spent_usd']
    if total is None or attempt.baseline_spent_usd is None:
        raise BudgetError('usage_unknown')
    ceiling = usd(attempt.ceiling_usd)
    row = ledger.get('attempt_budget')
    if row is None or row['key'] != attempt.key:
        row = ledger['attempt_budget'] = dict(key=attempt.key, baseline=str(total), ceiling=str(ceiling))
    if usd(row['ceiling']) != ceiling: raise BudgetError('reservation_mismatch')
    return usd(row['baseline']) + ceiling


def reservation_booked(ledger, lease_id, row, events=None):
    """Spend booked against one reservation: its listed events plus those bound to it by lease
    and invocation before settlement lists them (the same join as _settle_leaf)."""
    if events is None: events = {e['id']: e for e in ledger.get('events', []) if e.get('id')}
    ids = set(row['event_ids']) | {i for i, e in events.items()
                                   if e.get('lease_id') == lease_id and e.get('invocation_id') == row['invocation_id']}
    if not ids <= events.keys(): return None   # a listed event is missing: the ledger cannot be trusted
    return sum((event_charge(events[i]) for i in ids), Decimal(0))


def check_reservation(ledger, lease_id):
    """Stop a running reserved call when the case total cannot be priced, an event it listed is
    missing from the ledger, or more is booked to it than it reserved. Each stop has its own label
    (b5521c, 8 November: all three were usage_reservation_exceeded, so the cause was hidden)."""
    if case_spending(ledger)['total_spent_usd'] is None: raise BudgetError('reservation_spend_unknown')
    # Any state: a row settled or estimated while its stream continues is held to the same maximum.
    row = ledger['invocation_reservations'][lease_id]
    booked = reservation_booked(ledger, lease_id, row)
    if booked is None: raise BudgetError('reservation_event_missing')
    if booked > usd(row['maximum_usd']): raise BudgetError('usage_reservation_exceeded')


def outstanding_reservations(ledger, exclude_lease=None):
    events = {e['id']: e for e in ledger.get('events', []) if e.get('id')}
    total = Decimal(0)
    for lease_id, row in ledger.get('invocation_reservations', {}).items():
        if row['state'] != 'pending' or lease_id == exclude_lease: continue
        # Missing the bound events counted a running call's spend twice (7 November).
        booked = reservation_booked(ledger, lease_id, row, events)
        if booked is None: raise BudgetError('usage_event_missing')
        total += max(Decimal(0), usd(row['maximum_usd']) - booked)
    return total


def available_invocation_funding(path, attempt):
    """Uncommitted funding only; reserve_invocation arbitrates concurrent callers."""
    with ledger_transaction(path) as ledger:
        limit = attempt_limit(ledger, attempt)
        total = case_spending(ledger)['total_spent_usd']
        if total is None: raise BudgetError('usage_unknown')
        available = limit - usd(total) - outstanding_reservations(ledger)
        if available <= 0: raise BudgetError('budget_exhausted:grant_insufficient')
        return format(available, '.9f')


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


def _retain_final_receipts(work, leaves):
    """Persist evidence before its digest enters the atomic ledger transaction."""
    for receipt in leaves:
        if not receipt['final_usage_known']: continue
        data = json.dumps(receipt, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        directory = Path(work) / 'usage-receipts' / 'final'
        if directory.is_symlink(): raise BudgetError('invalid_usage_receipt')
        directory.mkdir(exist_ok=True)
        path = directory / (hashlib.sha256(data).hexdigest() + '.json')
        if path.is_symlink(): raise BudgetError('invalid_usage_receipt')
        if path.exists():
            if path.read_bytes() != data: raise BudgetError('invalid_usage_receipt')
        else:
            fd, temporary = tempfile.mkstemp(dir=directory)
            try:
                with os.fdopen(fd, 'wb') as file:
                    file.write(data); file.flush(); os.fsync(file.fileno())
                os.replace(temporary, path)
                parent = os.open(directory, os.O_RDONLY)
                try: os.fsync(parent)
                finally: os.close(parent)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)


def _gate_bound(receipt):
    """The closed call gate's ceiling: validated spend plus each unvalidated request's hold.

    A closed gate refuses further requests, so this bounds the call even if its
    process outlived the stop. Receipts without a closed gate snapshot get None.
    """
    cap = receipt.get('cap_used')
    # No forwarded request is an unstarted gate's default snapshot (keep the maximum), unless
    # the gate itself refused: only a running gate sets exhausted, and it forwarded nothing, so
    # the call cost nothing. (b5521c, 7 November: refused Claude preflights booked their holds.)
    if (not isinstance(cap, dict) or cap.get('closed') is not True or type(cap.get('forwarded_requests')) is not int
            or (cap['forwarded_requests'] < 1 and cap.get('exhausted') is not True)): return None
    try: values = [Decimal(str(cap[k])) for k in ('settled_usd', 'held_usd')]
    except (KeyError, InvalidOperation, TypeError): return None
    if not all(v.is_finite() and v >= 0 for v in values): return None
    return sum(values, Decimal(0)).quantize(Decimal('.000000001'), rounding=ROUND_CEILING)


def _settle_leaf(ledger, receipt, wait_id=None):
    lease_id = receipt['lease_id']
    row = ledger.get('invocation_reservations', {}).get(lease_id)
    if row is None:
        if (receipt.get('outcome') == 'denied' and receipt['final_usage_known']
                and receipt['events'] == [] and receipt['booked_event_ids'] == []
                and receipt.get('unidentified_events', 0) == 0
                and isinstance(receipt.get('usage_delta', {}), dict)
                and all(usd(v) == 0 for v in receipt.get('usage_delta', {}).values())): return
        raise BudgetError('usage_reservation_missing')
    if row['state'] == 'settled' and not receipt['final_usage_known']:
        raise BudgetError('usage_receipt_regressed')
    # Capture this row's estimate, independent of unrelated unknown usage.
    previous_gap = usd(row.get('estimated_gap_usd', 0)) if row['state'] == 'estimated' else Decimal(0)
    events = {e['id']: e for e in ledger.get('events', []) if e.get('id')}
    before_ids = set(row['event_ids']) | {i for i, e in events.items()
        if e.get('invocation_id') == row['invocation_id'] and e.get('lease_id') == lease_id}
    # Late-booked events already bound to this row are part of its current charge.
    booked_before = sum((event_charge(events[i]) for i in before_ids if i in events), Decimal(0))
    ids = before_ids | set(receipt['booked_event_ids'])
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
            ledger[key] = ledger.get(key, 0) + event.get(key, 0)
        ledger['calls'] = ledger.get('calls', 0) + event.get('calls', 1)
    if not ids <= events.keys(): raise BudgetError('usage_event_missing')
    # A receipt cannot assign another invocation's events to this row.
    for other_lease, other in ledger.get('invocation_reservations', {}).items():
        if other_lease != lease_id and ids.intersection(other['event_ids']):
            raise BudgetError('usage_event_shared')
    for identity in ids:
        event = events[identity]
        if ((event.get('lease_id') is not None or event.get('invocation_id') is not None) and
                (event.get('lease_id'), event.get('invocation_id')) != (lease_id, row['invocation_id'])):
            raise BudgetError('invalid_usage_binding')
    booked = sum((event_charge(events[i]) for i in ids), Decimal(0))
    bound, gate = usd(row['maximum_usd']), _gate_bound(receipt)
    if gate is not None: bound = min(bound, gate)
    estimate = (max(Decimal(0), bound - booked).quantize(Decimal('.000000001'), rounding=ROUND_CEILING)
                if not receipt['final_usage_known'] else Decimal(0))
    if row['state'] == 'estimated' and not receipt['final_usage_known']:
        # An estimate is already a ceiling (closed gate or maximum). Non-final
        # evidence never moves it, so it cannot grow between collections; only
        # booked usage above it, or a final receipt with its decrease record, does.
        estimate = max(Decimal(0), booked_before + previous_gap - booked).quantize(
            Decimal('.000000001'), rounding=ROUND_CEILING)
    row.update(event_ids=sorted(ids), estimated_gap_usd=format(estimate, '.9f'),
               state='settled' if receipt['final_usage_known'] else 'estimated')
    if previous_gap > 0 and receipt['final_usage_known']:
        before_money, actual_money = usd(booked_before), usd(booked)
        released = before_money + previous_gap - actual_money
        if released > 0:
            records = ledger.setdefault('reconciled_decreases', [])
            if any(r['invocation_id'] == row['invocation_id'] for r in records):
                raise BudgetError('usage_receipt_regressed')
            records.append({'schema_version': 1, 'kind': 'reconciled_decrease',
                'invocation_id': row['invocation_id'], 'wait_id': wait_id,
                'receipt_sha256': hashlib.sha256(json.dumps(receipt, sort_keys=True,
                    separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
                'booked_before_usd': format(before_money, '.9f'),
                'previous_estimate_usd': format(previous_gap, '.9f'),
                'actual_charge_usd': format(actual_money, '.9f'), 'released_usd': format(released, '.9f')})
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
            rows = [r for r in ledger['invocation_reservations'].values()
                    if r['operation_id'] in waste['operation_ids'] and r['state'] == 'settled']
            waste['event_ids'] = sorted({i for r in rows for i in r['event_ids']})
            amount = usd(_waste_amount(events, waste['event_ids']))
            if waste.get('schema_version') == 2:
                waste['infrastructure_waste_usd'] = format(amount, '.9f')
                _factory_bug_v2(ledger, waste, events)
            elif waste.get('schema_version') == 1:
                waste['infrastructure_waste_usd'] = float(amount)
            else: raise BudgetError('invalid_waste_attribution')
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
        _retain_final_receipts(work, leaves)
        for receipt in leaves: _settle_leaf(ledger, receipt, identity)
        summary = case_spending(ledger)
        after = summary.get('known_total_spent_usd', summary['total_spent_usd'])
        wait = ledger.setdefault('wait_settlements', {}).setdefault(identity, {'lease_ids': []})
        # Replays can discover later receipts. Retain their provenance too;
        # denied zero-usage leaves without a reservation carry no work.
        wait['lease_ids'] = sorted(set(wait['lease_ids']) | {r['lease_id'] for r in leaves
            if r['lease_id'] in ledger.get('invocation_reservations', {})})
    record['settled'] = True
    live = work / 'provider_wait.json'
    if live.exists(): _save(live, record)
    return round(after - before, 9)


def complete_invocation(work, ledger_path, lease_id):
    """Settle the finished call now; missing final usage charges its remaining maximum."""
    relative = 'usage-receipts/' + lease_id + '.json'
    leaves = _usage_leaves(Path(work), relative)
    _retain_final_receipts(work, leaves)
    with ledger_transaction(ledger_path) as ledger:
        for receipt in leaves:
            if receipt['lease_id'] != lease_id: raise BudgetError('wait_receipt_mismatch')
            _settle_leaf(ledger, receipt)


def release_uninvoked(ledger_path, lease_id):
    with ledger_transaction(ledger_path) as ledger:
        row = ledger.get('invocation_reservations', {}).get(lease_id)
        if row is None: return
        if row['state'] == 'settled' and not row['event_ids'] and usd(row.get('estimated_gap_usd', 0)) == 0:
            return  # Both wrapper and caller may unwind the same unstarted lease.
        if row['state'] != 'pending' or row['event_ids']: raise BudgetError('reservation_already_invoked')
        row.update(state='settled', estimated_gap_usd='0.000000000')


def reconcile_reservations(work, ledger_path, *, exclude_leases=(), exclude_calls=()):
    """Ordinary crash reconciliation, called only after exclusive case ownership.

    Missing receipts do not prove a free call: charge the remaining reservation
    explicitly. Late receipts replace that estimate through the same settler.
    """
    work = Path(work)
    with ledger_transaction(ledger_path) as ledger:
        for lease_id, row in ledger.get('invocation_reservations', {}).items():
            if lease_id in exclude_leases or row['call_name'] in exclude_calls: continue
            if row['state'] == 'settled': continue
            relative = 'usage-receipts/' + lease_id + '.json'
            if (work / relative).is_file(): leaves = _usage_leaves(work, relative)
            else:
                leaves = [{'lease_id': lease_id, 'events': [], 'booked_event_ids': row['event_ids'],
                           'final_usage_known': False}]
            _retain_final_receipts(work, leaves)
            for receipt in leaves: _settle_leaf(ledger, receipt)


def _factory_bug_v2(ledger, record, events):
    """The shared exact validator for current factory-bug monetary records."""
    try:
        keys = {'schema_version', 'kind', 'id', 'finding_id', 'diagnosis_sha256',
                'resume_id', 'resume_binding_sha256', 'operation_ids', 'event_ids', 'infrastructure_waste_usd'}
        if set(record) != keys or type(record['schema_version']) is not int or record['schema_version'] != 2:
            raise ValueError()
        def identity(value):
            parsed = uuid.UUID(value)
            return str(parsed) == value and parsed.version == 4
        if (record['kind'] != 'factory_bug' or not identity(record['finding_id']) or
                record['id'] != 'factory-bug:' + record['finding_id'] or
                re.fullmatch('[0-9a-f]{64}', record['diagnosis_sha256']) is None): raise ValueError()
        pair = (record['resume_id'], record['resume_binding_sha256'])
        if pair != (None, None) and (not identity(pair[0]) or
                re.fullmatch('[0-9a-f]{64}', pair[1]) is None): raise ValueError()
        operations, ids = record['operation_ids'], record['event_ids']
        if (not isinstance(operations, list) or not operations or operations != sorted(set(operations)) or
                not all(identity(op) for op in operations) or not isinstance(ids, list) or
                ids != sorted(set(ids)) or any(not isinstance(i, str) for i in ids)): raise ValueError()
        rows = [row for row in ledger.get('invocation_reservations', {}).values() if row['operation_id'] in operations]
        if ({row['operation_id'] for row in rows} != set(operations) or
                any(row['state'] != 'settled' or usd(row['estimated_gap_usd']) != 0 for row in rows)):
            raise BudgetError('waste_operations_pending')
        if set(ids) != {i for row in rows for i in row['event_ids']} or not set(ids) <= events.keys(): raise ValueError()
        amount = record['infrastructure_waste_usd']
        if (not isinstance(amount, str) or re.fullmatch(r'(?:0|[1-9][0-9]*)\.[0-9]{9}', amount) is None or
                amount != format(usd(_waste_amount(events, ids)), '.9f')): raise ValueError()
        return ids, operations
    except (KeyError, TypeError, ValueError, AttributeError):
        raise BudgetError('invalid_waste_attribution') from None


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
        existing = next((r for r in ledger.get('infrastructure_waste', []) if r.get('id') == record.get('id')), None)
        if record.get('schema_version') == 2:
            events = {event['id']: event for event in ledger.get('events', [])}
            _factory_bug_v2(ledger, record, events)
            if existing is not None:
                identity = ('schema_version', 'kind', 'id', 'finding_id', 'diagnosis_sha256')
                if (any(existing.get(k) != record[k] for k in identity) or
                        not set(existing['operation_ids']) <= set(record['operation_ids']) or
                        (existing['resume_id'] is not None and
                         (existing['resume_id'], existing['resume_binding_sha256']) !=
                         (record['resume_id'], record['resume_binding_sha256']))):
                    raise BudgetError('waste_attribution_mismatch')
                existing.clear(); existing.update(record)
            else:
                ledger.setdefault('infrastructure_waste', []).append(record)
            if case_spending(ledger)['total_spent_usd'] is None: raise BudgetError('invalid_waste_attribution')
            return
        if record.get('schema_version') != 1: raise BudgetError('invalid_waste_attribution')
        if existing is not None:
            identity = ('kind', 'schema_version', 'id', 'diagnosis_sha256', 'fix_commit', 'fix_attribution_sha256', 'operation_ids')
            if any(existing.get(k) != record.get(k) for k in identity): raise BudgetError('waste_attribution_mismatch')
            return
        rows = [row for row in ledger.get('invocation_reservations', {}).values() if row['operation_id'] in operations]
        if not rows or {row['operation_id'] for row in rows} != set(operations) or any(row['state'] != 'settled' for row in rows):
            raise BudgetError('waste_operations_pending')
        ledger.setdefault('infrastructure_waste', []).append(record)
        if case_spending(ledger)['total_spent_usd'] is None: raise BudgetError('invalid_waste_attribution')


def _spending(ledger, models_used=None):
    """One valuation for usage, classification and batch totals.

    Preserve provider precision internally. Public totals use the nine-place
    batch unit; role rounding never feeds back into the cumulative total.
    """
    ledger = ledger or {}
    roles = {}
    for name, model in (models_used or {}).items():
        roles.setdefault(model, set()).add(invocation_role(name))
    breakdown, events, event_roles = {}, {}, {}
    observed = [Decimal(0), Decimal(0), Decimal(0)]
    unpriced = len(ledger.get('unpriced_invocations', []))
    for event in ledger.get('events', []):
        try: values = [Decimal(str(v)) for v in _event_components(event)]
        except BudgetError:
            unpriced += 1
            continue
        observed = [a + b for a, b in zip(observed, values)]
        model = event.get('configured_model')
        matches = roles.get(model, set())
        role = event.get('role') or (next(iter(matches)) if len(matches) == 1 else 'legacy_unattributed')
        breakdown[role] = breakdown.get(role, Decimal(0)) + sum(values)
        if event.get('id'):
            events[event['id']], event_roles[event['id']] = event, role
    for key, amount in zip(('cost', 'list_cost_usd', 'estimated_subscription_cost_usd'), observed):
        total = ledger.get(key, float(amount))
        if not _number(total):
            unpriced += 1
            continue
        remainder = max(Decimal(0), Decimal(str(total)) - amount)
        # Floating streaming aggregates may differ from their exact decimal
        # events below the public money unit. They prove no legacy charge.
        if usd(remainder):
            breakdown['legacy_unattributed'] = breakdown.get('legacy_unattributed', Decimal(0)) + remainder
    for row in ledger.get('invocation_reservations', {}).values():
        try: gap = usd(row.get('estimated_gap_usd', 0))
        except BudgetError:
            unpriced += 1
            continue
        role = invocation_role(row['call_name'])
        breakdown[role] = breakdown.get(role, Decimal(0)) + gap
    model_total = sum(breakdown.values(), Decimal(0))
    waste, additive_waste = Decimal(0), Decimal(0)
    records = ledger.get('infrastructure_waste', [])
    if not isinstance(records, list):
        records = []
        unpriced += 1
    classified_events, classified_operations, waste_ids = set(), set(), set()
    for record in records:
        if isinstance(record, dict) and record.get('kind') == 'factory_bug':
            if record.get('schema_version') != 1:
                ids, operations = _factory_bug_v2(ledger, record, events)
                if (record['id'] in waste_ids or set(ids) & classified_events or
                        set(operations) & classified_operations): raise BudgetError('invalid_waste_attribution')
                for identity in ids: breakdown[event_roles[identity]] -= event_charge(events[identity])
                waste += _waste_amount(events, ids)
                classified_events.update(ids); classified_operations.update(operations); waste_ids.add(record['id'])
                continue
            try:
                ids, operations = record['event_ids'], record['operation_ids']
                related = [row for row in ledger.get('invocation_reservations', {}).values()
                           if row['operation_id'] in operations]
                valid = (record.get('schema_version') == 1 and bool(record['id']) and record['id'] not in waste_ids
                    and isinstance(ids, list) and bool(ids) and len(set(ids)) == len(ids)
                    and isinstance(operations, list) and bool(operations) and len(set(operations)) == len(operations)
                    and not set(ids) & classified_events and not set(operations) & classified_operations
                    and set(ids) <= events.keys()
                    and all(re.fullmatch(r'[0-9a-f]{64}', record[k]) for k in ('diagnosis_sha256', 'fix_attribution_sha256'))
                    and re.fullmatch(r'[0-9a-f]{40}', record['fix_commit']) is not None
                    and usd(record['infrastructure_waste_usd']) == usd(_waste_amount(events, ids))
                    and {row['operation_id'] for row in related} == set(operations)
                    and set(ids) == {i for row in related if row['state'] == 'settled' for i in row['event_ids']})
                if valid:
                    for identity in ids:
                        breakdown[event_roles[identity]] -= event_charge(events[identity])
                    waste += _waste_amount(events, ids)
                    classified_events.update(ids); classified_operations.update(operations); waste_ids.add(record['id'])
                else: unpriced += 1
            except (KeyError, TypeError, ValueError, BudgetError):
                unpriced += 1
            continue
        # Additive legacy kill charges have no already-booked event IDs.
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
        if isinstance(record, dict) and _number(record.get('infrastructure_waste_usd')):
            additive_waste += Decimal(str(record['infrastructure_waste_usd']))
    total = usd(model_total + additive_waste)
    waste = usd(waste + additive_waste)
    # Derive the ordinary line from the one cumulative total, so reclassifying
    # receipts cannot move that total or create a negative nanodollar residue.
    known = total - waste
    breakdown = {role: float(usd(value)) for role, value in breakdown.items()
                 if role != 'legacy_unattributed' or usd(value)}
    return model_total + additive_waste, {'spent_usd': None if unpriced else float(known), 'breakdown_by_role': breakdown,
            'infrastructure_waste_usd': float(waste), 'infrastructure_waste': records,
            'total_spent_usd': None if unpriced else float(total),
            **({'unpriced_events': unpriced, 'known_spent_usd': float(known),
                'known_total_spent_usd': float(total)} if unpriced else {})}


def case_spending(ledger, models_used=None):
    return _spending(ledger, models_used)[1]


def _bound_events(ledger):
    """One event-to-reservation join for coverage and settlement, legacy included."""
    rows, events = ledger.get('invocation_reservations', {}), ledger.get('events', [])
    if not isinstance(rows, dict) or not isinstance(events, list): raise BudgetError('invalid_usage_binding')
    by_id, owners, claims = {}, {}, {}
    for lease, row in rows.items():
        if not isinstance(row, dict) or row.get('lease_id') != lease: raise BudgetError('invalid_usage_binding')
        identity = row.get('invocation_id')
        if identity in by_id or not isinstance(identity, str): raise BudgetError('invalid_usage_binding')
        by_id[identity] = lease
        ids = row.get('event_ids')
        if not isinstance(ids, list) or len(set(ids)) != len(ids): raise BudgetError('invalid_usage_binding')
        for event_id in ids:
            if event_id in claims: raise BudgetError('usage_event_shared')
            claims[event_id] = lease
    indexed = {}
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get('id'), str) or not event['id']:
            raise BudgetError('invalid_usage_event')
        identity = event['id']
        if identity in indexed: raise BudgetError('usage_event_shared')
        event_charge(event)
        indexed[identity] = event
        lease, invocation, bound = event.get('lease_id'), event.get('invocation_id'), claims.get(identity)
        if lease is not None or invocation is not None:
            if lease not in rows or by_id.get(invocation) != lease or bound not in (None, lease):
                raise BudgetError('invalid_usage_binding')
            bound = lease
        if bound is not None: owners[identity] = bound
    if not claims.keys() <= indexed.keys(): raise BudgetError('usage_event_missing')
    return indexed, owners


def usage_coverage(ledger):
    """Pure conservative coverage using case_spending's raw Decimal valuation."""
    try:
        if not isinstance(ledger, dict): return None
        rows = ledger.get('invocation_reservations', {})
        unknown, waits = ledger.get('unpriced_invocations', []), ledger.get('wait_settlements', {})
        if not isinstance(unknown, list) or not isinstance(waits, dict): return None
        indexed, owners = _bound_events(ledger)
        raw_total, summary = _spending(ledger)
        if summary.get('unpriced_events', 0) != len(unknown): return None
        from diagnosis import _uuid4
        keys = {'schema_version', 'invocation_id', 'operation_id', 'lease_id', 'route', 'account',
                'billing', 'pool', 'family', 'call_name', 'parent_call_name', 'maximum_usd', 'state', 'event_ids'}
        for lease, row in rows.items():
            if (not keys <= row.keys() or row.keys() - keys - {'estimated_gap_usd'} or
                    type(row['schema_version']) is not int or row['schema_version'] != 1 or
                    not isinstance(lease, str) or not lease or not _uuid4(row['invocation_id']) or
                    not _uuid4(row['operation_id']) or row['state'] not in ('pending', 'estimated', 'settled') or
                    not isinstance(row['maximum_usd'], str) or
                    not re.fullmatch(r'(?:0|[1-9][0-9]*)\.[0-9]{9}', row['maximum_usd'])): return None
            gap = row.get('estimated_gap_usd', '0.000000000')
            if (not isinstance(gap, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.[0-9]{9}', gap)
                    or (row['state'] != 'estimated' and usd(gap) != 0)): return None
        for marker in unknown:
            if not isinstance(marker, dict): return None
            row = rows.get(marker.get('lease_id'))
            if row is None or row['state'] == 'settled' or row['invocation_id'] != marker.get('invocation_id'):
                return None
        for identity, wait in waits.items():
            if (not _uuid4(identity) or not isinstance(wait, dict) or set(wait) != {'lease_ids'}
                    or not isinstance(wait['lease_ids'], list) or
                    any(lease not in rows for lease in wait['lease_ids'])): return None
        booked = raw_total - sum((usd(row.get('estimated_gap_usd', 0)) for row in rows.values()), Decimal(0))
        covered, result = booked, []
        for lease, row in rows.items():
            if row['state'] == 'settled': continue
            charge = sum((event_charge(indexed[i]) for i, owner in owners.items() if owner == lease), Decimal(0))
            remaining = max(Decimal(0), usd(row['maximum_usd']) - charge)
            covered += remaining
            result.append({'invocation_id': row['invocation_id'], 'lease_id': lease,
                'wait_ids': sorted(i for i, wait in waits.items() if lease in wait['lease_ids']),
                'maximum_usd': row['maximum_usd'], 'booked_usd': format(usd(charge), '.9f'),
                'remaining_usd': format(remaining.quantize(Decimal('.000000001'), rounding=ROUND_CEILING), '.9f')})
        return {'schema_version': 1, 'booked_total_usd': format(usd(booked), '.9f'),
                'covered_total_usd': format(covered.quantize(Decimal('.000000001'), rounding=ROUND_CEILING), '.9f'),
                'invocations': sorted(result, key=lambda row: row['invocation_id'])}
    except (BudgetError, ValueError, TypeError, KeyError, AttributeError, InvalidOperation): return None


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
    _check_containment(ledger_path)
    path = Path(ledger_path)
    if not path.exists(): return
    with _activity(path, resume=True) as (_, reset, _), open(str(path) + '.lock', 'a') as lock:
        if not reset: return
        fcntl.flock(lock, fcntl.LOCK_EX)
        _check_containment(ledger_path)  # an owner may have died while we waited
        ledger = json.loads(path.read_text())
        previous = ledger.get('terminal_stop')
        if previous not in (None, 'complete'): ledger.setdefault('previous_stops', []).append(previous)
        ledger['terminal_stop'], ledger['zero_token_streak'] = None, 0
        ledger.pop('active', None)
        _save(path, ledger)


def _check_containment(ledger):
    if not os.environ.get('UNBUG_MODEL_CGROUP_ROOT'): return
    import processes
    try: processes.check_containment(ledger)
    except processes.ContainmentError as error: raise BudgetError(str(error)) from None


def run_budgeted(cmd, cwd, env, transcript_path, ledger_path, timeout,
                 max_cost=3.0, max_calls=100, max_total_calls=300, driver='opencode',
                 progress_timeout=15 * 60, max_zero_tokens=3, configured_model=None, resume=False, concurrent=False, cancel=None, case_budget=50.0, role=None, invocation_name=None,
                 invocation_id=None, lease_id=None, on_started=None, attempt=None, containment=True, usage_feed=None, call_cap_usd=None):
    # Preserve the original whole-session lock unless concurrency is explicitly enabled.
    settings = locals()
    _check_containment(ledger_path)
    path = Path(ledger_path)
    with _activity(path, resume=resume) as (activity, reset, admission):
        settings["resume"] = reset
        if concurrent: return _run_budgeted(**settings, _activity_lock=activity, _admission_lock=admission)
        with open(str(path) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return _run_budgeted(**settings, _serial_lock=lock, _activity_lock=activity, _admission_lock=admission)


def _run_budgeted(cmd, cwd, env, transcript_path, ledger_path, timeout,
                 max_cost=3.0, max_calls=100, max_total_calls=300, driver='opencode',
                 progress_timeout=15 * 60, max_zero_tokens=3, configured_model=None, resume=False, concurrent=False, cancel=None, case_budget=50.0, role=None, invocation_name=None,
                 invocation_id=None, lease_id=None, on_started=None, attempt=None, containment=True, usage_feed=None, call_cap_usd=None, _serial_lock=None, _activity_lock=None, _admission_lock=None):
    """Return CompletedProcess, or raise BudgetError without exposing transcript text.

    max_calls limits this invocation; max_total_calls and max_cost span roles.
    max_cost counts priced (opencode) events only: codex/claude are subscriptions
    (Claude list-price totals and estimated Codex token costs recorded separately).
    case_budget is the legacy role boundary. An engine attempt uses its admitted
    reservation instead, with no cumulative case ceiling.
    Ledger contains usage metadata only. A terminal failure is sticky unless explicitly
    resumed; resuming preserves all costs/calls and archives the previous stop.
    usage_feed (Codex only) returns the text of Codex's own session logs, or None when it cannot
    be read: each request is booked as it lands, so a reserved call stops mid-turn at its maximum.
    call_cap_usd holds an unreserved call's own booked list value to that maximum the same way.
    """
    import processes
    if driver not in ('opencode', 'codex', 'claude'):
        raise ValueError('Unknown driver')
    if usage_feed is not None and driver != 'codex': raise ValueError('usage_feed is for Codex only')
    reserved = attempt is not None
    # Live Codex usage holds a call to its reservation (check_reservation) or, outside one, to call_cap_usd.
    if usage_feed is not None and not reserved and call_cap_usd is None: raise BudgetError('unbounded_route')
    if call_cap_usd is not None and (reserved or not _number(call_cap_usd)): raise ValueError('call_cap_usd is for an unreserved call')
    if ((max_cost is None and not reserved)
            or (reserved and (max_cost is not None or not invocation_id or not lease_id))):
        raise ValueError('attempt budget requires admitted invocation')
    if not all(_number(v) for v in ((() if reserved else (max_cost,)) + (max_calls, timeout, max_total_calls, progress_timeout, case_budget))) or not isinstance(max_zero_tokens, int) or max_zero_tokens < 1:
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
    invocation = invocation_id or uuid.uuid4().hex

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
        if attempt is None:
            require_case_budget(ledger, case_budget, configured_model)
        else:
            attempt_limit(ledger, attempt)
        if reserved:
            reservation = ledger.get('invocation_reservations', {}).get(lease_id, {})
            if (reservation.get('invocation_id') != invocation or reservation.get('state') != 'pending'
                    or reservation.get('route') != configured_model): raise BudgetError('reservation_mismatch')
        previous = ledger.get('terminal_stop')
        if previous not in (None, 'complete') and not (concurrent and previous == 'running' and not resume):
            if not resume: raise BudgetError('Budget ledger stopped: ' + str(previous))
            ledger.setdefault('previous_stops', []).append(previous)
        if resume:
            ledger['zero_token_streak'] = 0
            ledger.pop('active', None)
        cause = ('cost_limit' if not reserved and ledger['cost'] >= max_cost else
                 'total_call_limit' if not reserved and ledger['calls'] >= max_total_calls else
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
    seen = {item['id'] for item in ledger['events'] if item.get('id')}
    provider_model = configured_model or driver + '/unknown'
    with transaction():
        ledger.update(driver=driver, configured_model=configured_model)
        ledger.pop('provider_failure', None)
    rate_limits = 0
    starts, finishes, responses = set(), set(), set()
    partial_usage = {}
    count = usages = 0
    session = {'id': '', 'turns': 0}
    live = {'polled': float('-inf'), 'booked': 0, 'failures': 0, 'value': Decimal(0), 'unattributed': {k: 0 for k in CODEX_USAGE_FIELDS}}
    process = None
    contained = None
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
        if not reserved and ledger['cost'] >= max_cost:
            raise BudgetError('cost_limit')
        if reserved:
            # reserve_invocation admitted this call's maximum against the attempt's limit, with
            # every other pending maximum. So the call is held to its own reservation only: the
            # whole-attempt re-test let other calls' late bookings stop a call within its own
            # (b5521c, 7 November: attempts 2 and 4 stopped mid-admission at real cents).
            check_reservation(ledger, lease_id)
        if call_cap_usd is not None and live['value'] > usd(call_cap_usd):
            raise BudgetError('usage_reservation_exceeded')
        if not reserved and ledger['calls'] >= max_total_calls:
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

    def subscription_usage(identity, usage, required, list_cost=None, partial=False, long_context=None, extra=None):
        """Tokens recorded at cost 0, priced 'subscription' (exempt from unpriced_usage)."""
        nonlocal usages
        if not isinstance(usage, dict) or not all(_number(usage.get(k)) for k in required):
            raise BudgetError('missing_usage')
        estimate = (codex_cost(configured_model, usage, long_context) if driver == 'codex' else
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
        if reserved:
            record.update(invocation_id=invocation, lease_id=lease_id)
            ledger['invocation_reservations'][lease_id]['event_ids'].append(identity)
        if partial: record['estimated_from_partial_usage'] = True
        if extra: record.update(extra)
        if estimate is not None:
            live['value'] += usd(estimate)
            record['estimated_subscription_cost_usd'] = estimate
            ledger['estimated_subscription_cost_usd'] = ledger.get('estimated_subscription_cost_usd', 0) + estimate
        if list_cost is not None:
            record['list_cost_usd'] = list_cost
            ledger['list_cost_usd'] = ledger.get('list_cost_usd', 0) + list_cost
        ledger['events'].append(record)
        if driver == 'codex':  # what Codex reported counts, not what is left to book after live requests
            reported = record.get('turn_usage') or record.get('reported_usage') or usage
            tokens_seen([v for k, v in reported.items() if k.endswith('_tokens') and _number(v)])
        else: _save(path, ledger)
        check_limits()

    def read_feed(force=False):
        """Codex's session logs, at most every CODEX_FEED_SECONDS unless forced; None when not due or
        unreadable. Called outside the ledger lock (the feed may run sudo). CODEX_FEED_FAILURES
        unreadable polls in a row stop the call: its usage would no longer be capped."""
        if usage_feed is None: return None
        now = time.monotonic()
        if not force and now - live['polled'] < CODEX_FEED_SECONDS: return None
        live['polled'] = now
        text = usage_feed()
        if isinstance(text, str):
            live['failures'] = 0
            return text
        live['failures'] += 1
        if not force and live['failures'] >= CODEX_FEED_FAILURES: raise BudgetError('missing_usage')
        return None

    def covers(text, usage):
        """Whether the log already shows every token the turn reports."""
        if text is None or not isinstance(usage, dict): return False
        new = codex_request_usages(text)[live['booked']:]
        return all(_number(usage.get(k)) and max(0, live['unattributed'][k])
                   + sum(u.get(k, 0) for u in new if _number(u.get(k, 0))) >= usage[k] for k in CODEX_USAGE_FIELDS)

    def prefetch(line):
        """Before a turn's end is booked under the ledger lock, read the log outside it, a few times
        while Codex's log writer lags behind the turn total."""
        live.pop('prefetched', None)
        if usage_feed is None or b'turn.completed' not in line: return
        try: usage = json.loads(line).get('usage')
        except (ValueError, UnicodeDecodeError, AttributeError): return
        text = None
        for attempt_number in range(CODEX_TURN_READS):
            if attempt_number: time.sleep(CODEX_TURN_READ_PAUSE)
            text = read_feed(force=True) or text
            if covers(text, usage): break
        live['prefetched'] = text

    def book_live(text):
        """Book each new request from Codex's own report at list price, as it lands. Tokens a turn's
        end already booked as residual (negative 'unattributed') are not booked again."""
        if text is None: return
        for usage in codex_request_usages(text)[live['booked']:]:
            identity = invocation + ':request-' + str(live['booked'])
            live['booked'] += 1
            if not all(type(usage.get(k, 0)) is int and usage.get(k, 0) >= 0 for k in CODEX_USAGE_FIELDS):
                raise BudgetError('missing_usage')
            booked = {}
            for k in CODEX_USAGE_FIELDS:
                value = usage.get(k, 0)
                booked[k] = max(0, value + min(0, live['unattributed'][k]))
                live['unattributed'][k] += value
            booked['cached_input_tokens'] = min(booked['cached_input_tokens'], booked['input_tokens'])
            subscription_usage(identity, booked, CODEX_USAGE_FIELDS,
                               extra={'codex_request': True, 'reported_usage': {k: usage.get(k, 0) for k in CODEX_USAGE_FIELDS}})

    def book_turn(identity, usage):
        """A turn's end: book only what its live requests did not, at the long-context tariff
        (those tokens' request sizes are unknown)."""
        if not isinstance(usage, dict) or not all(type(usage.get(k)) is int and usage[k] >= 0 for k in CODEX_USAGE_FIELDS):
            raise BudgetError('missing_usage')
        finishes.add(identity)   # a stop below must not book the whole turn again (book_residual books it)
        try: book_live(live.pop('prefetched', None))
        finally: book_residual(identity, usage)

    def book_residual(identity, usage):
        residual = {}
        for k in CODEX_USAGE_FIELDS:
            residual[k] = max(0, usage[k] - max(0, live['unattributed'][k]))
            live['unattributed'][k] -= usage[k]
        residual['cached_input_tokens'] = min(residual['cached_input_tokens'], residual['input_tokens'])
        subscription_usage(identity, residual, CODEX_USAGE_FIELDS, long_context=True,
                           extra={'turn_usage': {k: usage[k] for k in CODEX_USAGE_FIELDS}})

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
            identity = session['id'] + ':turn-' + str(session['turns'])
            if usage_feed is not None: book_turn(identity, event.get('usage'))
            else: subscription_usage(identity, event.get('usage'), CODEX_USAGE_FIELDS)

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
            if not claude_standard_usage(usage): prior['speed'] = 'unknown'
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
        if configured_model in GO_ROUTES:
            # A Go plan step is booked at its OpenRouter twin's list price whatever OpenCode reports
            # (founder 2026-11-09): a $0 or low report must neither stop the call with an unknown final
            # usage, which books the whole reservation, nor under-count the case budget.
            part = dict(part, cost=max(float(part['cost']), go_step_cost(configured_model, tokens)))
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
            **({'invocation_id': invocation, 'lease_id': lease_id} if reserved else {}),
        })
        if reserved: ledger['invocation_reservations'][lease_id]['event_ids'].append(identity)
        tokens_seen([tokens[k] for k in ('input', 'output', 'reasoning')] + list(tokens['cache'].values()))
        # A free route is checked only against OpenCode's own report (founder 2026-11-08), so a step from
        # any other provider or model stops it, once its cost is booked: that step could be billed somewhere.
        if str(configured_model).endswith('-free') and str(configured_model).startswith('opencode/'):
            reported = (part.get('providerID', event.get('providerID')), part.get('modelID', event.get('modelID')))
            if any(v is not None for v in reported) and reported != tuple(str(configured_model).split('/', 1)):
                raise BudgetError('free_route_mismatch')
        if (part['cost'] == 0 and any([tokens[k] for k in ('input', 'output', 'reasoning')]
                                           + list(tokens['cache'].values()))
                and not str(configured_model).endswith((':free', '-free'))):
            raise BudgetError('unpriced_usage')
        check_limits()

    def stop_process():
        nonlocal stopped
        if contained is not None:
            try:
                contained.stop()
                if process is not None: process.wait(timeout=5)
            except (processes.ContainmentError, subprocess.TimeoutExpired):
                raise BudgetError('cancellation_failed') from None
            stopped = True
            return
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
            _check_containment(ledger_path)  # include isolated calls after admission-lock waits
            if containment: contained = processes.ContainedCall(ledger_path)
            launch = contained.launch if contained is not None else subprocess.Popen
            process = launch(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             **({} if containment else {'start_new_session': True}))
            if on_started is not None: on_started()
            selector.register(process.stdout, selectors.EVENT_READ)
            pending = b''
            tool_cpu = tool_cpu_ticks(process.pid)
            while selector.get_map() or process.poll() is None:
                feed = read_feed()
                with transaction():
                    shared_stop()
                    book_live(feed)
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
                        prefetch(pending.split(b'\n', 1)[0])
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
            if contained is not None: stop_process()
            with transaction():
                shared_stop()
                if concurrent: ledger['active'].remove(invocation)
                ledger['terminal_stop'] = 'running' if ledger.get('active') else 'complete'
                if not ledger.get('active'): ledger.pop('active', None)
            return subprocess.CompletedProcess(cmd, returncode)
    except BaseException as error:
        if isinstance(error, processes.ContainmentError): error = BudgetError(str(error))
        if contained is not None:
            try: stop_process()
            except BudgetError as cleanup_error:
                starts.add('cancellation-failed:' + invocation)
                with transaction():
                    ledger.setdefault('cleanup_errors', []).append({
                        'stage': 'process_cancellation', 'error': 'cancellation_failed'})
                error = cleanup_error
        if (process is not None and driver in ('codex', 'claude')
                and isinstance(error, BudgetError)
                and str(error) in ('call_limit', 'total_call_limit', 'cost_limit', 'timeout')):
            # Stop first: collecting usage must never grant another model response.
            # Only drain bytes already emitted; no grace period for a missing receipt.
            try:
                stop_process()
            except BaseException as cleanup_error:
                # Cancellation is part of the accounting boundary. A failed stop
                # cannot make this invocation's usage known, even if it already
                # recorded an earlier complete turn (factory: reservation estimate).
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
        final_feed = None
        if usage_feed is not None:
            try: final_feed = read_feed(force=True)   # outside the ledger lock
            except Exception: final_feed = None
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
                        if not all(claude_standard_usage(v) for v in values): usage['speed'] = 'unknown'
                        subscription_usage(identity, usage, required, partial=True)
                elif driver == 'codex':
                    # A stopped call keeps what Codex reported for it, up to its stop.
                    if usage_feed is not None:
                        try: book_live(final_feed)
                        except Exception: starts.add('unverified-live-usage:' + invocation)
                    for identity, usage in partial_usage.items():
                        if identity in finishes: continue
                        if usage_feed is not None:   # only what the live requests did not book
                            finishes.add(identity); book_residual(identity, usage)
                        else: subscription_usage(identity, usage, CODEX_USAGE_FIELDS, partial=True)
            except BudgetError:
                pass  # Unknown model or invalid partial usage remains fail-closed below.
            finally:
                collecting_usage = False
            # A factory call's reservation bounds its unknown usage, and its closed
            # call gate refuses requests from a process that outlived the stop; a
            # marker would only make the whole case total unknown.
            if not reserved and driver in ('codex', 'claude') and (starts - finishes or (process is not None and not usages)):
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
