"""Read B's frozen job money channel; never create or enlarge authority.

The holder supplies both the channel and its authenticated launch binding. Until
B installs that binding, this consumer refuses admission. Historical argv and
public card limits are evidence, never substitutes for B's channel.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import re
import uuid

from budget import BudgetError, usd


@dataclass(frozen=True)
class JobAuthority:
    batch: str
    job: str
    case: str
    reservation_id: str
    revision: int
    source_generation: str | None
    committed_total_usd: Decimal
    batch_deadline: str


def read(channel, launch_binding, *, now=None):
    """Both arguments come from authenticated worker configuration, not a card."""
    fields = {'schema', 'batch', 'job', 'case', 'reservation_id', 'revision',
              'source_generation', 'committed_total_usd', 'batch_deadline'}
    try:
        if not isinstance(channel, dict) or set(channel) != fields or channel != launch_binding: raise ValueError
        if channel['schema'] != 1 or type(channel['schema']) is not int: raise ValueError
        if any(not isinstance(channel[k], str) or not re.fullmatch(r'[A-Za-z0-9_-]+', channel[k])
               for k in ('batch', 'job', 'case')) or not channel['case'].startswith('case-'): raise ValueError
        identity = uuid.UUID(channel['reservation_id'])
        if identity.version != 4 or str(identity) != channel['reservation_id']: raise ValueError
        if type(channel['revision']) is not int or channel['revision'] < 1: raise ValueError
        generation = channel['source_generation']
        if generation is not None and (not isinstance(generation, str) or not re.fullmatch('[0-9a-f]{64}', generation)): raise ValueError
        amount = channel['committed_total_usd']
        if not isinstance(amount, str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.[0-9]{9}', amount): raise ValueError
        deadline = datetime.fromisoformat(channel['batch_deadline'].replace('Z', '+00:00'))
        if deadline.utcoffset() != timezone.utc.utcoffset(deadline): raise ValueError
        if deadline.timestamp() <= (datetime.now(timezone.utc).timestamp() if now is None else now):
            raise BudgetError('retired_batch_bound')
        return JobAuthority(**{k: channel[k] for k in fields - {'schema', 'committed_total_usd'}},
                            committed_total_usd=usd(amount))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise BudgetError('money_wait') from None


def for_case(c):
    binding = getattr(c, 'authenticated_job_config', {})
    authority = read(getattr(c, 'job_money', None), binding.get('job_money'))
    if (authority.batch, authority.job, authority.case, authority.batch_deadline, authority.source_generation) != (
            getattr(c, 'batch_id', None), getattr(c, 'job_id', None), c.case_id,
            getattr(c, 'batch_deadline', None), getattr(c, 'source_generation', None)):
        raise BudgetError('money_wait')
    if c.card.get('terminal_stop') == 'retired_batch_bound': raise BudgetError('retired_batch_bound')
    return authority
