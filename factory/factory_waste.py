"""Read-only validation of retained causal financial evidence."""
import hashlib
import json
from pathlib import Path
import budget
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import re
import uuid

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

def _owner(channel, launch_binding, *, now=None):
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
            raise budget.BudgetError('retired_batch_bound')
        return JobAuthority(**{k: channel[k] for k in fields - {'schema', 'committed_total_usd'}},
                            committed_total_usd=budget.usd(amount))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise budget.BudgetError('money_wait') from None

_FIELDS = ('lease_id', 'invocation_id', 'operation_id', 'call_name', 'parent_call_name')



_BASE = {'schema_version', 'attempt_id', 'case', 'stage', 'case_sha256', 'batch_id',
         'job_id', 'source_generation', 'batch_release_sha256', 'money_owner', 'reservations'}



def read(path, base):
    from diagnosis import _input_bytes
    return json.loads(_input_bytes(Path(path), Path(base)))



def _owners(root):
    current = read(root / 'work/job-money.json', root)
    history_path = root / 'work/job-money-history.json'
    history = read(history_path, root) if history_path.exists() else {}
    if not isinstance(history, dict): raise ValueError('money history')
    owners = [current]
    for item in history.values():
        if not isinstance(item, dict) or set(item) != {'old', 'new', 'config_sha256', 'source_generation'}:
            raise ValueError('money history')
        owners.extend((item['old'], item['new']))
    return owners



def _proof(value, ledger, case, owners, *, replay=False):
    from diagnosis import _sha, _uuid4
    from run import GATES
    extra = {'replay_of', 'resume_id', 'outcome'} if replay else {'classification', 'error_type'}
    if (not isinstance(value, dict) or set(value) != _BASE | extra or
            type(value['schema_version']) is not int or value['schema_version'] != (2 if replay else 1) or
            not _uuid4(value['attempt_id']) or value['case'] != case or
            value['stage'] not in (*GATES, 'stress') or not _sha(value['case_sha256']) or
            not _sha(value['batch_release_sha256'])): raise ValueError('attempt shape')
    owner = value['money_owner']
    _owner(owner, owner)
    if owner not in owners or (owner['case'], owner['batch'], owner['job'], owner['source_generation']) != (
            case, value['batch_id'], value['job_id'], value['source_generation']): raise ValueError('attempt owner')
    if replay:
        if (not _uuid4(value['resume_id']) or value['outcome'] not in ('completed', 'invalid-infra') or
                not isinstance(value['replay_of'], list) or not value['replay_of'] or
                value['replay_of'] != sorted(set(value['replay_of'])) or
                not all(_uuid4(i) for i in value['replay_of'])): raise ValueError('replay shape')
    elif value['classification'] != 'invalid-infra' or not isinstance(value['error_type'], str) or not value['error_type']:
        raise ValueError('failure shape')
    reservations = value['reservations']
    if not isinstance(reservations, list): raise ValueError('reservations')
    leases, operations = [], set()
    for reservation in reservations:
        if not isinstance(reservation, dict) or set(reservation) != set(_FIELDS): raise ValueError('reservation')
        lease = reservation['lease_id']
        if not _uuid4(lease): raise ValueError('lease')
        row = ledger['invocation_reservations'][lease]
        if lease != row['lease_id'] or reservation != {k: row.get(k) for k in _FIELDS}: raise ValueError('reservation identity')
        leases.append(lease); operations.add(row['operation_id'])
    if leases != sorted(set(leases)): raise ValueError('duplicate leases')
    return operations



def eligible(evidence_root, case, finding_id):
    root = Path(evidence_root)
    directory = root / 'work/factory-failures'
    if directory.is_symlink(): raise ValueError('unsafe proof directory')
    if not directory.exists(): return [], []
    if not directory.is_dir(): raise ValueError('proof directory')
    paths = sorted(directory.iterdir())
    if not paths: return [], []
    ledger, owners = read(root / 'ledger.json', root), _owners(root)
    # Validate monetary ownership before using it to exclude another finding.
    if budget.case_spending(ledger)['total_spent_usd'] is None:
        raise ValueError('unvalidated monetary ownership')
    owned = set()
    for record in ledger.get('infrastructure_waste', []):
        if record.get('kind') != 'factory_bug' or record.get('finding_id') != finding_id:
            owned.update(record.get('operation_ids', []))
    operations, receipts = set(), []
    for path in paths:
        if path.is_dir(): raise ValueError('nested proof directory')
        value = read(path, root)
        if path.name != value['attempt_id'] + '.json': raise ValueError('proof filename')
        selected = _proof(value, ledger, case, owners) - owned
        if value['money_owner'] == owners[0] and value['batch_release_sha256'] != read(root / 'card.json', root).get('batch_release_sha256'):
            raise ValueError('attempt release')
        if selected:
            operations.update(selected)
            from diagnosis import _input_bytes
            receipts.append(dict(path=path.relative_to(root).as_posix(),
                                 sha256=hashlib.sha256(_input_bytes(path, root)).hexdigest()))
    return sorted(operations), receipts
