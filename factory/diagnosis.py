"""Content-free projections and worker-owned diagnosis lifecycle.

The three projection APIs read only their input card and never grant authority.
Lifecycle producers retain private findings before publishing completed state.
"""
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import uuid
from recovery import infrastructure_exhausted
from budget import BudgetError
from registry import atomic_json


class FactoryBugHeldWait(BudgetError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _uuid4(value):
    try:
        parsed = uuid.UUID(value)
        return str(parsed) == value and parsed.version == 4
    except (ValueError, TypeError, AttributeError):
        return False


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def extension_history(card):
    """Validate exact public history; None means malformed, [] means absent."""
    history = card.get('extension_history', [])
    if not isinstance(history, list) or len(history) > 5: return None
    keys = {'schema_version', 'extension_id', 'writer_operation_id', 'entry_sha256', 'outcome_sha256'}
    for ordinal, row in enumerate(history, 1):
        if (not isinstance(row, dict) or set(row) != keys or type(row['schema_version']) is not int
                or row['schema_version'] != 1 or type(row['extension_id']) is not int
                or row['extension_id'] != ordinal or not _uuid4(row['writer_operation_id'])
                or not _sha(row['entry_sha256']) or
                (row['outcome_sha256'] is None and ordinal != len(history)) or
                (row['outcome_sha256'] is not None and not _sha(row['outcome_sha256']))): return None
    return history


def _trigger(card, stop, history):
    if stop in ('budget_exhausted', 'stress_review_unresolved:rounds_exhausted', 'infrastructure_exhausted',
                'malformed_output_exhausted', 'freshness_evidence_unavailable', 'stress_validation_exhausted'):
        return True
    if stop == 'extension_incomplete':
        return bool(history and history[-1]['outcome_sha256'] is not None)
    if isinstance(stop, str) and re.fullmatch(r'late_defect_needs_ruling:G(?:[1-9]|1[013-7])', stop):
        config = card.get('recovery_config')
        rounds = config.get('rounds') if isinstance(config, dict) else None
        count = card.get('builder_rounds')
        return (type(rounds) is int and rounds > 0 and type(count) is int and count >= rounds
                and not (history and history[-1]['outcome_sha256'] is None))
    return False


def _state(card, history):
    state = card.get('diagnosis_state')
    if (not isinstance(state, dict) or set(state) !=
            {'schema_version', 'exhaustion_id', 'stop', 'status', 'outcome'} or
            type(state['schema_version']) is not int or state['schema_version'] != 1 or
            not _uuid4(state['exhaustion_id'])): return None
    # Validate the retained decision against the history before its admission.
    origin = history
    if (state['status'] == 'completed' and state['outcome'] == 'close_to_passing'
            and history and history[-1]['outcome_sha256'] is None):
        origin = history[:-1]
    if not _trigger(card, state['stop'], origin): return None
    if state['status'] == 'pending' and state['outcome'] is None: return state
    if state['status'] == 'completed' and state['outcome'] in ('factory_bug', 'close_to_passing', 'not_converging'):
        return state
    return None


def exhaustion(card):
    if not isinstance(card, dict): return False
    stop, gates = card.get('terminal_stop'), card.get('gates', {})
    if (not isinstance(gates, dict) or gates.get('G12') == 'pass' or
            card.get('status') in ('sealed', 'retired') or
            stop in ('provider_wait', 'paused', 'ttl_retired', 'factory_bug_history_invalid', 'diagnosis_input_invalid') or
            (isinstance(stop, str) and stop.startswith('retired'))): return False
    history = extension_history(card)
    if history is None or (history and history[-1]['outcome_sha256'] is None): return False
    if 'diagnosis_state' in card and _state(card, history) is None: return False
    if stop == 'diagnosis_pending':
        state = _state(card, history)
        return bool(state and state['status'] == 'pending')
    return infrastructure_exhausted(card) or _trigger(card, stop, history)


def actual_model_work(card):
    """Reservations and conservative gaps alone are not process-start evidence.

    A started call leaves an event, an unknown marker, or a route receipt whose
    outcome is done/interrupted (the runtime resets an unstarted one to denied).
    """
    if not isinstance(card, dict) or not isinstance(card.get('continuation_budget'), dict): return False
    ledger = card['continuation_budget']
    events, unknown = ledger.get('events', []), ledger.get('unpriced_invocations', [])
    receipts = card.get('route_receipts', [])
    if (not isinstance(events, list) or not isinstance(unknown, list) or not isinstance(receipts, list) or
            any(not isinstance(row, dict) for row in events + unknown + receipts)): return False
    return bool(events or unknown or any(r.get('outcome') in ('done', 'interrupted') for r in receipts))


def pending_projection(card):
    if not exhaustion(card): return None
    history = extension_history(card)
    if history and history[-1]['outcome_sha256'] is None: return None
    state = _state(card, history)
    if state and state['status'] != 'pending': return None
    infrastructure = (state['stop'] == 'infrastructure_exhausted' if state
                      else infrastructure_exhausted(card))
    return {'schema_version': 1, 'status': 'pending',
            'replacement_eligible': actual_model_work(card) and not infrastructure}


def record_exhaustion(card, *, new_exhaustion=False):
    """Runner-only checkpoint producer; never starts diagnosis or names its seal.

    Call after accounting on the run that stops. A pending diagnosis keeps its
    ID through retries. Only a new literal exhaustion can replace a completed
    state; a retained infrastructure marker alone is not a new exhaustion.
    """
    history = extension_history(card)
    if history is None: raise BudgetError('diagnosis_state_invalid')
    state = _state(card, history)
    if 'diagnosis_state' in card and state is None: raise BudgetError('diagnosis_state_invalid')
    if state and state['status'] == 'pending': return
    if state and not new_exhaustion: return
    if card.get('terminal_stop') == 'factory_bug_held': return
    stop = card.get('terminal_stop')
    if state:
        # A retained infrastructure marker is evidence, not another exhaustion.
        if not _trigger(card, stop, history): return
    elif infrastructure_exhausted(card):
        stop = 'infrastructure_exhausted'
    if (not exhaustion(card) or not _trigger(card, stop, history) or
            (history and history[-1]['outcome_sha256'] is None)): return
    card['diagnosis_state'] = dict(schema_version=1, exhaustion_id=str(uuid.uuid4()),
        stop=stop, status='pending', outcome=None)


RESULT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['schema_version', 'case_id', 'checkpoint_sha256', 'outcome', 'reason', 'evidence', 'factory_bug'],
    'properties': {
        'schema_version': {'type': 'integer', 'const': 1},
        'case_id': {'type': 'string'},
        'checkpoint_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
        'outcome': {'enum': ['factory_bug', 'close_to_passing', 'not_converging']},
        'reason': {'type': 'string', 'minLength': 1},
        'evidence': {'type': 'array', 'minItems': 1, 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['path', 'sha256', 'finding'],
            'properties': {'path': {'type': 'string', 'minLength': 1},
                           'sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                           'finding': {'type': 'string', 'minLength': 1}}}},
        'factory_bug': {'anyOf': [{'type': 'null'}, {
            'type': 'object', 'additionalProperties': False,
            'required': ['component', 'reproducer', 'affected_operations', 'fix_required'],
            'properties': {**{key: {'type': 'string', 'minLength': 1}
                              for key in ('component', 'reproducer', 'fix_required')},
                           'affected_operations': {'type': 'array', 'uniqueItems': True,
                                                   'items': {'type': 'string', 'format': 'uuid'}}}}]},
    },
    'allOf': [{'if': {'properties': {'outcome': {'const': 'factory_bug'}}},
               'then': {'properties': {'factory_bug': {'type': 'object'}}},
               'else': {'properties': {'factory_bug': {'type': 'null'}}}}],
}


def validate_result(value, *, case, generation, evidence_root):
    """Validate against immutable queued inputs, never the worker's live ledger."""
    try:
        if (not _sha(generation) or not isinstance(value, dict) or set(value) != {'schema_version', 'case_id',
                'checkpoint_sha256', 'outcome', 'reason', 'evidence', 'factory_bug'} or
                type(value['schema_version']) is not int or value['schema_version'] != 1 or
                value['case_id'] != case or value['checkpoint_sha256'] != generation or
                value['outcome'] not in ('factory_bug', 'close_to_passing', 'not_converging') or
                not isinstance(value['reason'], str) or not value['reason'].strip() or
                not isinstance(value['evidence'], list) or not value['evidence']):
            raise ValueError()
        seen = set()
        root = Path(evidence_root)
        for item in value['evidence']:
            if not isinstance(item, dict) or set(item) != {'path', 'sha256', 'finding'}:
                raise ValueError()
            name = item['path']
            if not isinstance(name, str) or not name or name in seen: raise ValueError()
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or path.as_posix() != name: raise ValueError()
            target = root / name
            # Model-authored names must not turn ENAMETOOLONG into a paid retry.
            # Use conservative Unix limits before any filesystem probe.
            if ('\x00' in name or any(len(os.fsencode(part)) > 255 for part in path.parts) or
                    len(os.fsencode(target)) > 1023): raise ValueError()
            if any((root.joinpath(*path.parts[:i])).is_symlink() for i in range(len(path.parts) + 1)):
                raise ValueError()
            if (not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != item['sha256'] or
                    not isinstance(item['finding'], str) or not item['finding'].strip()): raise ValueError()
            seen.add(name)
        bug = value['factory_bug']
        if value['outcome'] == 'factory_bug':
            if not isinstance(bug, dict) or set(bug) != {
                    'component', 'reproducer', 'affected_operations', 'fix_required'}: raise ValueError()
            if any(not isinstance(bug[k], str) or not bug[k].strip()
                   for k in ('component', 'reproducer', 'fix_required')): raise ValueError()
            operations = bug['affected_operations']
            if (not isinstance(operations, list) or
                    any(not _uuid4(v) for v in operations) or len(set(operations)) != len(operations)): raise ValueError()
        elif bug is not None: raise ValueError()
    except (FileNotFoundError, ValueError, KeyError, TypeError, AttributeError):
        raise BudgetError('diagnosis_result_invalid') from None
    result = copy.deepcopy(value)
    if result['outcome'] == 'factory_bug':
        from factory_waste import eligible
        root = Path(evidence_root)
        identity = None
        if (root / 'work/factory-failures').exists():
            identity = json.loads(_input_bytes(root / 'card.json', root))['diagnosis_state']['exhaustion_id']
        operations, _ = eligible(root, case, identity)
        result['factory_bug']['affected_operations'] = sorted(set(result['factory_bug']['affected_operations']) & set(operations))
    return result


def _held_stage(card, stop):
    from run import GATES
    if stop == 'infrastructure_exhausted':
        marker = card.get('infrastructure_gate')
        value = marker.get('gate') if isinstance(marker, dict) else None
    elif stop.startswith('late_defect_needs_ruling:'):
        value = stop.split(':', 1)[1]
    elif stop.startswith('stress_review_unresolved:'):
        return 'stress'
    elif stop == 'extension_incomplete':
        value = card.get('failed_gate')
    else:
        value = None
    return value if value in GATES else 'unknown'


def _factory_bug_history(c, *, admitted_replay=None):
    path = Path(c.work) / 'factory-bug-resumes.json'
    try:
        if path.is_symlink(): raise ValueError()
        create = not path.exists()
        if create:
            cards = (c.card, getattr(c, 'checkpoint_card', {}))
            if any('factory_bug' in card or 'factory_bug_resume_count' in card for card in cards):
                raise ValueError()
            root = Path(c.work) / 'diagnosis'
            if root.is_symlink() or any(root.glob('*/finding.json')): raise ValueError()
            ledger_path = Path(c.ledger)
            ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
            for ledger in (ledger, *(card.get('continuation_budget', {}) for card in cards)):
                if not isinstance(ledger, dict): raise ValueError()
                waste = ledger.get('infrastructure_waste', [])
                if not isinstance(waste, list) or any(
                        not isinstance(row, dict) or row.get('kind') == 'factory_bug' for row in waste):
                    raise ValueError()
        history = [] if create else json.loads(path.read_text())
        if not isinstance(history, list) or len(history) > 3: raise ValueError()
        keys = {'schema_version', 'resume_id', 'finding_id', 'case', 'held_batch_id',
                'batch_id', 'job_id', 'reservation_id', 'source_generation', 'batch_release_sha256'}
        for row in history:
            if (not isinstance(row, dict) or set(row) != keys or type(row['schema_version']) is not int or
                    row['schema_version'] != 1 or row['case'] != c.case_id or
                    any(not _uuid4(row[k]) for k in ('resume_id', 'finding_id', 'reservation_id')) or
                    any(not _sha(row[k]) for k in ('source_generation', 'batch_release_sha256')) or
                    any(not isinstance(row[k], str) or not re.fullmatch('[a-z0-9-]+', row[k])
                        for k in ('held_batch_id', 'batch_id', 'job_id')) or
                    row['held_batch_id'] == row['batch_id']): raise ValueError()
        if any(len({row[k] for row in history}) != len(history) for k in ('finding_id', 'resume_id')):
            raise ValueError()
        for card in (c.card, getattr(c, 'checkpoint_card', {})):
            count = card.get('factory_bug_resume_count', len(history))
            if type(count) is not int: raise ValueError()
            if count != len(history) and not (admitted_replay is not None and history and
                    history[-1] == admitted_replay and count == len(history) - 1): raise ValueError()
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        c.card.pop('factory_bug_resume_count', None)
        c.card.update(status='stopped', terminal_stop='factory_bug_history_invalid')
        c.stopped = True
        raise BudgetError('factory_bug_history_invalid') from None
    if create: atomic_json(path, [])
    return history


def _held_context(c):
    from job_authority import for_case
    authority = for_case(c)
    release = c.authenticated_job_config.get('batch_release_sha256')
    if not _sha(release) or release != c.args.batch_release_sha256:
        raise BudgetError('money_wait')
    history = extension_history(c.card)
    state = _state(c.card, history) if history is not None else None
    if state is None or (state['status'] == 'completed' and state['outcome'] != 'factory_bug'):
        raise BudgetError('diagnosis_state_invalid')
    return authority, release, state


def _finding_path(c, identity):
    root = Path(c.work) / 'diagnosis'
    target = root / identity / 'finding.json'
    if root.is_symlink() or target.parent.is_symlink() or target.is_symlink():
        raise BudgetError('diagnosis_finding_invalid')
    return target


def _complete_factory_bug(c, finding, history, state):
    # The finding and history are already durable. Publish completion last.
    card = copy.deepcopy(c.card)
    recorded = getattr(c, 'checkpoint_card', {})
    prior_state = recorded.get('diagnosis_state') if isinstance(recorded, dict) else None
    if not isinstance(prior_state, dict) or prior_state.get('exhaustion_id') != state['exhaustion_id']:
        recorded = card
    card['diagnosis_state'].update(status='completed', outcome='factory_bug')
    card.update(status='stopped', terminal_stop='factory_bug_held',
                factory_bug_resume_count=len(history), factory_bug={
                    'finding_id': finding['finding_id'], 'gate_or_stage': _held_stage(recorded, state['stop']),
                    'summary_class': 'factory_bug'})
    atomic_json(Path(c.work) / 'scorecard.json', card)
    c.card = card
    c.stopped = True


def _read_factory_bug_finding(c, path, authority, release, state, generation, evidence_root):
    try:
        finding = json.loads(path.read_text())
        if (not isinstance(finding, dict) or set(finding) != {'schema_version', 'finding_id',
                'held_batch_id', 'held_release_sha256', 'diagnosis', 'eligible_operation_ids', 'failure_receipts'} or
                type(finding['schema_version']) is not int or finding['schema_version'] != 1 or
                finding['finding_id'] != state['exhaustion_id'] or finding['held_batch_id'] != authority.batch or
                finding['held_release_sha256'] != release): raise ValueError()
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        raise BudgetError('diagnosis_finding_invalid') from None
    from factory_waste import eligible
    operations, proofs = eligible(evidence_root, c.case_id, finding['finding_id'])
    if (finding['eligible_operation_ids'], finding['failure_receipts']) != (operations, proofs):
        raise BudgetError('diagnosis_finding_invalid')
    result = validate_result(finding['diagnosis'], case=c.case_id, generation=generation,
                             evidence_root=evidence_root)
    if result != finding['diagnosis'] or result['outcome'] != 'factory_bug':
        raise BudgetError('diagnosis_finding_invalid')
    return finding


def persist_factory_bug(c, result, *, generation, evidence_root):
    authority, release, state = _held_context(c)
    raw_result = copy.deepcopy(result)
    result = validate_result(result, case=c.case_id, generation=generation,
                             evidence_root=evidence_root)
    if result['outcome'] != 'factory_bug': raise BudgetError('diagnosis_outcome_not_factory_bug')
    from factory_waste import eligible, classify
    operations, proofs = eligible(evidence_root, c.case_id, state['exhaustion_id'])
    finding = dict(schema_version=1, finding_id=state['exhaustion_id'], held_batch_id=authority.batch,
                   held_release_sha256=release, diagnosis=result, eligible_operation_ids=operations, failure_receipts=proofs)
    path = _finding_path(c, state['exhaustion_id'])
    if state['status'] == 'completed' and not path.exists():
        raise BudgetError('diagnosis_finding_invalid')
    history = _factory_bug_history(c)
    if path.exists():
        previous = _read_factory_bug_finding(c, path, authority, release, state, generation, evidence_root)
        if previous != finding: raise BudgetError('diagnosis_finding_invalid')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        # The accepted finding has no attribution; retain the original model
        # judgment separately inside the encrypted checkpoint.
        raw_hash = hashlib.sha256(json.dumps(raw_result, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        atomic_json(path.parent / ('raw-result-' + raw_hash + '.json'), raw_result)
        atomic_json(path, finding)
        # atomic_json syncs the finding directory; persist its newly-created
        # ancestors before the card can advertise completed diagnosis.
        for directory in (path.parent.parent, path.parent.parent.parent):
            fd = os.open(directory, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
    from factory_waste import classify
    classify(c, finding)
    _complete_factory_bug(c, finding, history, state)


def restore_factory_bug(c, *, generation, evidence_root):
    """Call before dispatching a diagnosis model, including after a crash."""
    authority, release, state = _held_context(c)
    path = _finding_path(c, state['exhaustion_id'])
    if not path.exists():
        if state['status'] == 'completed': raise BudgetError('diagnosis_finding_invalid')
        return False
    finding = _read_factory_bug_finding(c, path, authority, release, state, generation, evidence_root)
    history = _factory_bug_history(c)
    from factory_waste import classify
    classify(c, finding)
    _complete_factory_bug(c, finding, history, state)
    return True


def _resume_bindings(c):
    """Authenticated current channel plus an unbranched encrypted transition chain."""
    from job_authority import for_case, read
    from batch_transfer import predecessor
    from batch_money import channel
    for_case(c)
    current = dict(c.authenticated_job_config['job_money'])
    records = {}
    record = c.authenticated_batch_manifest
    release = c.authenticated_job_config['batch_release_sha256']
    while True:
        if record['id'] in records: raise ValueError('cyclic release history')
        records[record['id']] = (record, release)
        if 'carry_from' not in record: break
        policy, record = predecessor(record)
        release = policy['batch']['sha256']
    path = Path(c.work) / 'job-money-history.json'
    transitions = json.loads(_input_bytes(path, c.work)) if path.exists() else {}
    if not isinstance(transitions, dict): raise ValueError('invalid money history')
    bindings, seen = [], set()
    cursor = current
    while True:
        read(cursor, cursor)
        record, release = records[cursor['batch']]
        channel(cursor, record, cursor['job'])
        key = (cursor['reservation_id'], cursor['revision'], cursor['source_generation'])
        if key in seen: raise ValueError('cyclic money history')
        seen.add(key); bindings.append((cursor, release))
        matches = [item for item in transitions.values() if item.get('new') == cursor]
        if not matches: break
        if len(matches) != 1: raise ValueError('branched money history')
        item = matches[0]
        if (set(item) != {'old', 'new', 'config_sha256', 'source_generation'} or
                not _sha(item['config_sha256']) or item['source_generation'] != cursor['source_generation']):
            raise ValueError('invalid money transition')
        previous = item['old']
        if (previous['case'] != cursor['case'] or previous['job'] != cursor['job'] or
                previous['committed_total_usd'] != cursor['committed_total_usd']):
            raise ValueError('changed owner allocation')
        if previous['batch'] == cursor['batch']:
            if (previous['reservation_id'] != cursor['reservation_id'] or
                    cursor['revision'] not in (previous['revision'], previous['revision'] + 1)):
                raise ValueError('invalid same owner transition')
        else:
            policy, _ = predecessor(record)
            spec = record['carry_from']['jobs'][cursor['job']]
            if (policy['batch']['id'] != previous['batch'] or cursor['revision'] != 1 or
                    previous['reservation_id'] == cursor['reservation_id'] or
                    spec['generation'] != cursor['source_generation']):
                raise ValueError('invalid imported transition')
        cursor = previous
    return bindings


def resume_factory_bug(c, r=None):
    """One lifetime admission after verified installation, before diagnosis replay."""
    state = c.card.get('diagnosis_state')
    if not isinstance(state, dict) or state.get('outcome') != 'factory_bug': return False
    from job_authority import for_case, read
    authority = for_case(c)
    path = _finding_path(c, state['exhaustion_id'])
    admission_validated = False
    try:
        finding = json.loads(_input_bytes(path, c.work))
        # Same-batch holds keep the existing strict replay path and never admit.
        if finding['held_batch_id'] == authority.batch: return False
        bindings = _resume_bindings(c)
        held = [(value, release) for value, release in bindings if
                value['batch'] == finding['held_batch_id'] and release == finding['held_release_sha256']]
        if not held: raise ValueError('missing held binding')
        old, old_release = held[0]
        if old_release == c.authenticated_job_config['batch_release_sha256']: raise ValueError('unchanged release')
        manifest = queued_inputs(c, c.work, quiescent=True)
        finding = _read_factory_bug_finding(c, path, read(old, old), old_release, state,
                                           manifest['generation'], path.parent / 'inputs')
        try:
            raw = json.loads(_input_bytes(Path(c.work) / 'factory-bug-resumes.json', c.work))
            if not isinstance(raw, list): raise ValueError('invalid history')
        except (OSError, ValueError, TypeError):
            # Preserve D's public history-invalid stop, including a missing file
            # after a retained finding. Never initialize or relabel this as zero.
            _factory_bug_history(c)
            raise BudgetError('factory_bug_history_invalid') from None
        prior = [row for row in raw if isinstance(row, dict) and row.get('finding_id') == finding['finding_id']]
        admission = prior[0] if len(prior) == 1 else None
        if admission is not None:
            if not any(all(admission.get(k) == value[v] for k, v in (
                    ('case', 'case'), ('batch_id', 'batch'), ('job_id', 'job'),
                    ('reservation_id', 'reservation_id'), ('source_generation', 'source_generation'))) and
                    admission.get('batch_release_sha256') == release and
                    admission.get('held_batch_id') == finding['held_batch_id'] for value, release in bindings):
                raise ValueError('unbound admission replay')
        history = _factory_bug_history(c, admitted_replay=admission)
        admission_validated = True
        if admission is None:
            if len(history) == 3:
                c.card.pop('failed_gate', None)
                c.card.update(status='stopped', terminal_stop='retired_factory_bug_limit', factory_bug_resume_count=3)
                c.stopped = True
                atomic_json(Path(c.work) / 'scorecard.json', c.card)
                raise BudgetError('retired_factory_bug_limit')
            admission = dict(schema_version=1, resume_id=str(uuid.uuid4()), finding_id=finding['finding_id'],
                case=c.case_id, held_batch_id=finding['held_batch_id'], batch_id=authority.batch,
                job_id=authority.job, reservation_id=authority.reservation_id,
                source_generation=authority.source_generation,
                batch_release_sha256=c.authenticated_job_config['batch_release_sha256'])
            history.append(admission)
            atomic_json(Path(c.work) / 'factory-bug-resumes.json', history)
        try:
            if r is None:
                import run as r
            import model_runtime
            from budget import reconcile_reservations
            from factory_waste import classify, refresh_replays
            model_runtime.prepare_dispatch(c)
            with c.model_dispatch_lock:
                if c.active_model_calls: raise BudgetError('usage_reconciliation_while_active')
                ledger = json.loads(_input_bytes(c.ledger, c.ledger.parent))
                if ledger.get('active'): raise BudgetError('usage_reconciliation_pending')
                r.resume_provider_wait(c)
                reconcile_reservations(c.work, c.ledger)
                ledger = json.loads(_input_bytes(c.ledger, c.ledger.parent))
                if ledger.get('active') or any(row['state'] == 'pending' for row in ledger.get('invocation_reservations', {}).values()):
                    raise BudgetError('usage_reconciliation_pending')
                classify(c, finding, admission)
                refresh_replays(c)
        except BudgetError as error:
            if str(error) in {'money_wait', 'invalid_provider_wait', 'usage_reconciliation_while_active',
                    'usage_reconciliation_pending', 'invalid_waste_attribution', 'waste_attribution_mismatch'}:
                raise FactoryBugHeldWait(str(error)) from error
            raise
        admitted_card = dict(c.card)
        for key in ('factory_bug', 'diagnosis_state', 'infrastructure_gate', 'terminal_stop', 'failed_gate', 'factory_bug_wait_reason'):
            admitted_card.pop(key, None)
        admitted_card.update(status='running', factory_bug_resume_count=len(history))
        atomic_json(Path(c.work) / 'scorecard.json', admitted_card)
        c.card.clear(); c.card.update(admitted_card)
        c.stopped = False
        return True
    except OSError:
        if admission_validated:
            raise FactoryBugHeldWait('factory_bug_resume_io_wait') from None
        raise BudgetError('diagnosis_finding_invalid') from None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise BudgetError('diagnosis_finding_invalid') from None


def require_model_work(card):
    """A held case cannot acquire another model lease in this batch."""
    state = card.get('diagnosis_state')
    if (card.get('terminal_stop') == 'factory_bug_held' or 'factory_bug' in card or
            isinstance(state, dict) and state.get('status') == 'completed' and
            state.get('outcome') == 'factory_bug'):
        raise BudgetError('factory_bug_held')


def _input_bytes(path, base):
    """Read selected regular files without following any selected parent link."""
    import stat
    path, base = Path(path), Path(base)
    relative = path.relative_to(base)
    if '..' in relative.parts: raise ValueError('unsafe input path')
    if any(base.joinpath(*relative.parts[:i]).is_symlink() for i in range(len(relative.parts) + 1)):
        raise ValueError('unsafe input path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ValueError('nonregular input')
        return stream.read()


def _input_inventory(root):
    if root.is_symlink() or not root.is_dir(): raise ValueError('missing input directory')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): raise ValueError('unsafe input path')
        if path.is_dir(): continue
        result[path.relative_to(root).as_posix()] = hashlib.sha256(_input_bytes(path, root)).hexdigest()
    return result


def _input_restore_receipt(raw, card, case, generation):
    from carry_over import digest
    receipt = json.loads(raw)
    if (not isinstance(receipt, dict) or type(receipt.get('version')) is not int or
            receipt['version'] != 1 or receipt.get('case') != case or
            receipt.get('accounting_authenticated') is not True or not _sha(generation) or
            receipt.get('generation') != generation or
            not _sha(receipt.get('ledger_sha256')) or not _sha(receipt.get('public_card_sha256'))):
        raise ValueError('invalid restore receipt')
    retained = receipt.get('retained_ledger_sha256', receipt['ledger_sha256'])
    if (not _sha(retained) or not isinstance(card.get('continuation_budget'), dict) or
            digest(card['continuation_budget']) != retained):
        raise ValueError('restore ledger binding')


def _input_cache_resolves(record, files):
    """A cache is a historical hint; missing current evidence makes it unusable."""
    try:
        evidence = record['evidence']
        if not isinstance(evidence, list) or not evidence: return False
        for item in evidence:
            name = item['path']
            path = PurePosixPath(name)
            if (not isinstance(name, str) or not name or path.is_absolute() or
                    '..' in path.parts or path.as_posix() != name or
                    item['kind'] not in ('bench', 'work') or not _sha(item['sha256'])):
                return False
            prefix = 'work/bench-results/' if item['kind'] == 'bench' else 'work/'
            target = prefix + name
            if target.startswith('work/gate-cache/') or files.get(target) != item['sha256']:
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _input_stop_evidence(c, card, state):
    stop = state['stop']
    if stop.startswith('late_defect_needs_ruling:'):
        from late_recovery import digest
        record = json.loads(_input_bytes(c.work / 'late-defect.json', c.work))
        marker = card.get('late_defect', {})
        gate = stop.split(':', 1)[1]
        if record['gate'] != gate or marker['gate'] != gate or marker['record_sha256'] != digest(record):
            raise ValueError('late-defect binding')
    elif stop == 'extension_incomplete':
        import extensions
        from types import SimpleNamespace
        restored = SimpleNamespace(work=c.work, ledger=c.ledger, card=copy.deepcopy(card))
        history = extensions.read(restored)
        if (not history or history[-1]['outcome'] is None or
                restored.card['extension_history'] != card.get('extension_history')):
            raise ValueError('extension outcome binding')
    elif stop == 'infrastructure_exhausted':
        from run import GATES
        marker = card['infrastructure_gate']
        if marker['exhausted'] is not True or marker.get('gate') not in GATES:
            raise ValueError('infrastructure marker')


def _write_input_tree(c, bench, root, card, state):
    """Select existing evidence and verified shipped source; never copy all work."""
    import gate_state
    import job_config
    from launch_manifest import WORKER_BENCH
    files = {}

    def add(name, data, expected=None):
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name:
            raise ValueError('unsafe input name')
        actual = hashlib.sha256(data).hexdigest()
        if (expected is not None and actual != expected) or (name in files and files[name] != actual):
            raise ValueError('different input copies')
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('wb') as output:
            output.write(data); output.flush(); os.fsync(output.fileno())
        files[name] = actual

    def add_tree(source, prefix, base, *, restored_bench=False):
        if source.is_symlink(): raise ValueError('unsafe input tree')
        if source.is_dir():
            for path in sorted(source.rglob('*')):
                if path.is_symlink(): raise ValueError('unsafe input tree')
                if not path.is_dir():
                    name = prefix + '/' + path.relative_to(source).as_posix()
                    data = _input_bytes(path, base)
                    # Current inventory wins, as current gates read it.
                    if not restored_bench or name not in files: add(name, data)
        elif source.exists():
            add(prefix, _input_bytes(source, base))

    add_tree(c.case, 'case', c.case)
    if not any(name.startswith('case/') for name in files): raise ValueError('missing case')
    ledger = _input_bytes(c.ledger, c.ledger.parent)
    value = json.loads(ledger)
    if not isinstance(value, dict) or value.get('active'): raise ValueError('unsettled active input')
    add('ledger.json', ledger)
    add('card.json', json.dumps(card, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    receipt = c.ledger.parent / (c.case_id + '.restore-accounting.json')
    add('restore-accounting.json', _input_bytes(receipt, c.ledger.parent))
    for (kind, name), path in gate_state.inventory(c, bench).items():
        prefix, base = ('work/bench-results/', bench / 'results') if kind == 'bench' else ('work/', c.work)
        add(prefix + name, _input_bytes(path, base))
    names = ('bench-results', 'attack-state.json', 'attacks', 'gate-continuation.json',
             'late-defect.json', 'extension-history.json', 'extension-snapshots', 'comparison-diagnostics', 'transcripts',
             'usage-receipts', 'factory-failures', 'factory-replays', 'job-money.json', 'job-money-history.json', 'infra-attempts.json', 'strong_calibrator', 'easy_calibrator',
             'early_probe', 'fixes', 'evidence', 'history', 'verdict.json', 'prototype.json',
             'public-search.json', 'idea-realism.json', 'audit-baseline.json', 'delivery-provenance.json')
    paths = [c.work / name for name in names] + list(c.work.glob('independent-*'))
    for path in paths:
        add_tree(path, 'work/' + path.name, c.work, restored_bench=path.name == 'bench-results')
    cache = c.work / 'gate-cache'
    if cache.is_symlink() or (cache.exists() and not cache.is_dir()):
        raise ValueError('unsafe cache directory')
    for path in sorted(cache.glob('*.json')):
        raw = _input_bytes(path, c.work)  # Unsafe files refuse even if the hint is stale.
        try: record = json.loads(raw)
        except (ValueError, UnicodeError): continue
        if _input_cache_resolves(record, files): add('work/gate-cache/' + path.name, raw)
    release_sha = c.authenticated_job_config['batch_release_sha256']
    if release_sha != c.args.batch_release_sha256: raise ValueError('release mismatch')
    release = job_config.read_file(job_config.FACTORY.parent / 'batch-release.json', release_sha)
    worker = job_config.read_file(job_config.FACTORY.parent / 'worker-release-manifest.json',
                                  release['files']['worker-release-manifest.json'])
    selected = {name: sha for name, sha in worker['files'].items()
                if (PurePosixPath(name).parent == PurePosixPath('factory') and name.endswith('.py')) or
                (PurePosixPath(name).parent == PurePosixPath('factory/prompts') and name.endswith('.md')) or
                (name in WORKER_BENCH and name.startswith('bin/'))}
    if not selected: raise ValueError('missing release source')
    for name, expected in selected.items():
        relative = PurePosixPath(name)
        base = job_config.FACTORY if relative.parts[0] == 'factory' else bench
        path = base.joinpath(*relative.parts[1:]) if relative.parts[0] == 'factory' else base / name
        add('source/' + name, _input_bytes(path, base), expected)
    return dict(sorted(files.items()))


def _verify_input_records(c, root, manifest):
    from types import SimpleNamespace
    files = manifest['files']
    if not any(name.startswith('case/') for name in files) or not any(name.startswith('source/') for name in files):
        raise ValueError('missing required input set')
    card = json.loads(_input_bytes(root / 'card.json', root))
    ledger = json.loads(_input_bytes(root / 'ledger.json', root))
    state = _state(card, extension_history(card))
    if (card.get('case') != c.case_id or
            state is None or state['status'] != 'pending' or state['exhaustion_id'] != manifest['exhaustion_id'] or
            not isinstance(ledger, dict) or ledger.get('active')):
        raise ValueError('invalid frozen source binding')
    _input_restore_receipt(_input_bytes(root / 'restore-accounting.json', root),
                           card, c.case_id, manifest['generation'])
    frozen = SimpleNamespace(work=root / 'work', ledger=root / 'ledger.json', card=card)
    _input_stop_evidence(frozen, card, state)
    for path in (root / 'work/gate-cache').glob('*.json'):
        record = json.loads(_input_bytes(path, root))
        if not _input_cache_resolves(record, files): raise ValueError('missing gate evidence')


def queued_inputs(c, bench, *, quiescent):
    """Retain/verify private inputs before diagnosis; grants no invocation authority.

    Return the immutable manifest. Callers use its generation and the fixed
    diagnosis/<exhaustion_id>/inputs directory for result and finding validation.
    """
    import job_authority
    import shutil
    authority = job_authority.for_case(c)
    if c.card.get('terminal_stop') == 'factory_bug_history_invalid':
        raise BudgetError('factory_bug_history_invalid')
    try:
        if quiescent is not True or c.card.get('terminal_stop') == 'diagnosis_input_invalid':
            raise ValueError('not an input boundary')
        state = _state(c.card, extension_history(c.card))
        if state is None: raise ValueError('missing diagnosis state')
        parent = _finding_path(c, state['exhaustion_id']).parent
        manifest_path, root, staged = parent / 'input.json', parent / 'inputs', parent / '.inputs-staging'
        if any(path.is_symlink() for path in (manifest_path, root, staged)):
            raise ValueError('unsafe input path')
        if manifest_path.exists():
            manifest = json.loads(_input_bytes(manifest_path, c.work))
            if (not isinstance(manifest, dict) or set(manifest) !=
                    {'schema_version', 'case_id', 'exhaustion_id', 'generation', 'files'} or
                    type(manifest['schema_version']) is not int or manifest['schema_version'] != 1 or
                    manifest['case_id'] != c.case_id or manifest['exhaustion_id'] != state['exhaustion_id'] or
                    not _sha(manifest['generation']) or not isinstance(manifest['files'], dict) or
                    not manifest['files'] or manifest['files'] != _input_inventory(root)):
                raise ValueError('changed input manifest')
            _verify_input_records(c, root, manifest)
            return manifest
        # Missing publication is recoverable only before any consumer bound it.
        ledger = json.loads(_input_bytes(c.ledger, c.ledger.parent))
        call = 'diagnosis-' + state['exhaustion_id']
        bound = any(row.get('call_name') == call or
                    re.fullmatch(re.escape(call) + r'-repair-[0-9]+', str(row.get('call_name', '')))
                    for row in ledger.get('invocation_reservations', {}).values())
        if (state['status'] != 'pending' or any((parent / name).exists()
                for name in ('finding.json', 'attempts.json', 'decision.json')) or
                any(any(parent.glob(pattern)) for pattern in
                    ('raw-result-*.json', 'raw-bytes-*', 'audit-bytes-*', 'audit-*.json')) or bound):
            raise ValueError('bound diagnosis lacks manifest')
        card = getattr(c, 'checkpoint_card', None)
        if (not _sha(authority.source_generation) or not isinstance(card, dict) or
                card.get('case') != c.case_id or
                card.get('diagnosis_state') != state):
            raise ValueError('initial input binding')
        parent.mkdir(parents=True, exist_ok=True)
        for path in (root, staged):
            if path.exists(): shutil.rmtree(path)
        staged.mkdir()
        files = _write_input_tree(c, Path(bench), staged, card, state)
        # File contents were synced by the writer. Persist names before manifest.
        directories = [p for p in staged.rglob('*') if p.is_dir()]
        for path in sorted(directories, key=lambda p: len(p.parts), reverse=True) + [staged]:
            fd = os.open(path, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        os.replace(staged, root)
        for path in (parent, parent.parent, c.work):
            fd = os.open(path, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        manifest = dict(schema_version=1, case_id=c.case_id, exhaustion_id=state['exhaustion_id'],
                        generation=authority.source_generation, files=files)
        _verify_input_records(c, root, manifest)
        atomic_json(manifest_path, manifest)
        return manifest
    except (FileNotFoundError, ValueError, KeyError, TypeError, AttributeError, BudgetError):
        c.card.update(status='stopped', terminal_stop='diagnosis_input_invalid')
        c.stopped = True
        raise BudgetError('diagnosis_input_invalid') from None
