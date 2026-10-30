"""Pure D collection proof checks. No durable ACK, source grant or usage booking."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
import json
import re
import uuid

from batch_money import amount


RESERVATION_KEYS = {'schema_version', 'invocation_id', 'operation_id', 'lease_id',
                    'route', 'account', 'billing', 'pool', 'family', 'call_name',
                    'parent_call_name', 'maximum_usd', 'state', 'event_ids'}
RECEIPT_KEYS = {'schema_version', 'kind', 'invocation_id', 'wait_id', 'receipt_sha256',
                'booked_before_usd', 'previous_estimate_usd', 'actual_charge_usd', 'released_usd'}


def _uuid(value):
    parsed = uuid.UUID(value)
    if parsed.version != 4 or str(parsed) != value: raise ValueError()


def _normalize(value):
    if value is None: return None
    if type(value) not in (str, int, float): raise ValueError()
    number = Decimal(str(value))
    if not number.is_finite() or number < 0: raise ValueError()
    with localcontext() as context:
        context.prec = max(28, len(number.as_tuple().digits), number.adjusted() + 1) + 10
        result = format(abs(number.quantize(Decimal('.000000001'), rounding=ROUND_CEILING)), '.9f')
    amount(result)
    return result


def card_total(card):
    """Normalize only the reported cumulative total, including old absent/null blocks."""
    try:
        if not isinstance(card, dict): raise ValueError()
        block = card.get('case_budget')
        if block is None: return None
        if not isinstance(block, dict): raise ValueError()
        return _normalize(block.get('total_spent_usd'))
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise ValueError('invalid_accounting_input') from None


def _call(accountant, name, ledger):
    """Keep the caller's ledger separate and refuse an API that changes its input."""
    value = deepcopy(ledger)
    try:
        before = json.dumps(value, sort_keys=True, allow_nan=False)
        result = deepcopy(getattr(accountant, name)(value))
        if json.dumps(value, sort_keys=True, allow_nan=False) != before: raise ValueError()
        if not isinstance(result, dict): raise ValueError()
        return result
    except Exception:
        raise ValueError('accounting_api_refused') from None


def _coverage(value):
    try:
        if (set(value) != {'schema_version', 'booked_total_usd', 'covered_total_usd', 'invocations'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1): raise ValueError()
        amount(value['booked_total_usd']); covered = amount(value['covered_total_usd'])
        if not isinstance(value['invocations'], list): raise ValueError()
        identities, leases = [], set()
        for row in value['invocations']:
            if (not isinstance(row, dict) or set(row) != {'invocation_id', 'lease_id', 'wait_ids',
                    'maximum_usd', 'booked_usd', 'remaining_usd'}): raise ValueError()
            _uuid(row['invocation_id']); identities.append(row['invocation_id'])
            lease = row['lease_id']
            if not isinstance(lease, str) or not lease or lease in leases: raise ValueError()
            leases.add(lease)
            waits = row['wait_ids']
            if not isinstance(waits, list): raise ValueError()
            for identity in waits: _uuid(identity)
            if waits != sorted(set(waits)): raise ValueError()
            for key in ('maximum_usd', 'booked_usd', 'remaining_usd'): amount(row[key])
        if identities != sorted(set(identities)): raise ValueError()
        return covered
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('accounting_api_refused') from None


def _inputs(card, previous, held):
    try:
        limit = amount(held)
        if not isinstance(previous, dict) or set(previous) != {'total_usd', 'estimated'}: raise ValueError()
        prior = previous['total_usd']
        if prior is not None: amount(prior)
        estimates = previous['estimated']
        if not isinstance(estimates, dict): raise ValueError()
        for identity, gap in estimates.items(): _uuid(identity); amount(gap)
        total = card_total(card)
        ledger = card.get('continuation_budget')
        if not isinstance(ledger, dict): raise ValueError()
        rows = ledger.get('invocation_reservations', {})
        if not isinstance(rows, dict): raise ValueError()
        indexed, next_estimates = {}, {}
        for lease, row in rows.items():
            if (not isinstance(row, dict) or not RESERVATION_KEYS <= row.keys() or
                    row.keys() - RESERVATION_KEYS - {'estimated_gap_usd'} or
                    type(row['schema_version']) is not int or row['schema_version'] != 1 or
                    not isinstance(lease, str) or not lease or row['lease_id'] != lease or
                    row['state'] not in ('pending', 'estimated', 'settled')): raise ValueError()
            identity = row['invocation_id']; _uuid(identity)
            if identity in indexed: raise ValueError()
            indexed[identity] = row
            if row['state'] == 'estimated':
                amount(row['estimated_gap_usd'])
                next_estimates[identity] = row['estimated_gap_usd']
        return total, prior, limit, ledger, indexed, next_estimates
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('invalid_accounting_input') from None


def _releases(ledger, indexed, previous):
    """Validate all public records, then qualify only the immediately prior estimates."""
    try:
        records = ledger.get('reconciled_decreases', [])
        if not isinstance(records, list): raise ValueError()
        unique = {}
        for row in records:
            if (not isinstance(row, dict) or set(row) != RECEIPT_KEYS or
                    type(row['schema_version']) is not int or row['schema_version'] != 1 or
                    row['kind'] != 'reconciled_decrease'): raise ValueError()
            identity = row['invocation_id']; _uuid(identity)
            if row['wait_id'] is not None: _uuid(row['wait_id'])
            if not isinstance(row['receipt_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['receipt_sha256']):
                raise ValueError()
            before, estimate, actual, released = (amount(row[k]) for k in (
                'booked_before_usd', 'previous_estimate_usd', 'actual_charge_usd', 'released_usd'))
            if released <= 0 or released != before + estimate - actual: raise ValueError()
            if identity not in indexed or indexed[identity]['state'] != 'settled': raise ValueError()
            if identity in unique and unique[identity] != row: raise ValueError()
            unique[identity] = row
        return [deepcopy(row) for identity, row in sorted(unique.items())
                if identity in previous and amount(row['released_usd']) <= amount(previous[identity])]
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError('malformed_reconciliation') from None


def collection_facts(card, previous, held, accountant):
    """Compare an immutable card to prior host facts; caller must authenticate both.

    Returned totals/maps are replacements, not charges. This offline consumer is
    deliberately not wired into authorize or any launch/ACK path.
    """
    total, prior, limit, ledger, indexed, estimates = _inputs(card, previous, held)
    summary = _call(accountant, 'case_spending', ledger)
    try:
        if 'total_spent_usd' not in summary: raise ValueError()
        reported = _normalize(summary['total_spent_usd'])
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise ValueError('accounting_api_refused') from None
    if total != reported: raise ValueError('invalid_accounting_input')
    records = _releases(ledger, indexed, previous['estimated'])
    if total is None:
        if _coverage(_call(accountant, 'usage_coverage', ledger)) > limit:
            raise ValueError('uncovered_total')
    elif prior is None:
        if amount(total) > limit: raise ValueError('uncovered_total')
    else:
        released = sum(amount(row['released_usd']) for row in records)
        epsilon = 2 * len(previous['estimated']) + 1
        if amount(total) < amount(prior) - released - epsilon: raise ValueError('unsupported_decrease')
    return dict(total_usd=total, estimated=dict(sorted(estimates.items())), reconciled_decreases=records)
