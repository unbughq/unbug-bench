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
    if stop in ('budget_exhausted', 'stress_review_unresolved:rounds_exhausted', 'infrastructure_exhausted'):
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
            not _uuid4(state['exhaustion_id']) or not _trigger(card, state['stop'], history)): return None
    if state['status'] == 'pending' and state['outcome'] is None: return state
    if state['status'] == 'completed' and state['outcome'] in ('factory_bug', 'close_to_passing', 'not_converging'):
        return state
    return None


def exhaustion(card):
    if not isinstance(card, dict): return False
    stop, gates = card.get('terminal_stop'), card.get('gates', {})
    if (not isinstance(gates, dict) or gates.get('G12') == 'pass' or
            card.get('status') in ('sealed', 'retired') or
            stop in ('provider_wait', 'paused', 'ttl_retired', 'factory_bug_history_invalid') or
            (isinstance(stop, str) and stop.startswith('retired'))): return False
    history = extension_history(card)
    if history is None: return False
    if 'diagnosis_state' in card and _state(card, history) is None: return False
    if stop == 'diagnosis_pending':
        state = _state(card, history)
        return bool(state and state['status'] == 'pending')
    return infrastructure_exhausted(card) or _trigger(card, stop, history)


def actual_model_work(card):
    """Reservations and conservative gaps alone are not process-start evidence."""
    if not isinstance(card, dict) or not isinstance(card.get('continuation_budget'), dict): return False
    ledger = card['continuation_budget']
    events, unknown = ledger.get('events', []), ledger.get('unpriced_invocations', [])
    if (not isinstance(events, list) or not isinstance(unknown, list) or
            any(not isinstance(row, dict) for row in events + unknown)): return False
    return bool(events or unknown)


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
    stop = 'infrastructure_exhausted' if infrastructure_exhausted(card) else card.get('terminal_stop')
    if (not exhaustion(card) or not _trigger(card, stop, history) or
            (history and history[-1]['outcome_sha256'] is None)): return
    card['diagnosis_state'] = dict(schema_version=1, exhaustion_id=str(uuid.uuid4()),
        stop=stop, status='pending', outcome=None)


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
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise BudgetError('diagnosis_result_invalid') from None
    result = copy.deepcopy(value)
    if result['outcome'] == 'factory_bug':
        result['factory_bug']['affected_operations'] = []
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


def _factory_bug_history(c):
    path = Path(c.work) / 'factory-bug-resumes.json'
    try:
        if path.is_symlink(): raise ValueError()
        if not path.exists():
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
            atomic_json(path, [])
        history = json.loads(path.read_text())
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
            if type(count) is not int or count != len(history): raise ValueError()
        return history
    except (OSError, ValueError, KeyError, TypeError):
        c.card.pop('factory_bug_resume_count', None)
        c.card.update(status='stopped', terminal_stop='factory_bug_history_invalid')
        c.stopped = True
        raise BudgetError('factory_bug_history_invalid') from None


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
                finding['held_release_sha256'] != release or finding['eligible_operation_ids'] != [] or
                finding['failure_receipts'] != []): raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise BudgetError('diagnosis_finding_invalid') from None
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
    finding = dict(schema_version=1, finding_id=state['exhaustion_id'], held_batch_id=authority.batch,
                   held_release_sha256=release, diagnosis=result, eligible_operation_ids=[], failure_receipts=[])
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
    _complete_factory_bug(c, finding, history, state)
    return True


def require_model_work(card):
    """A held case cannot acquire another model lease in this batch."""
    state = card.get('diagnosis_state')
    if (card.get('terminal_stop') == 'factory_bug_held' or 'factory_bug' in card or
            isinstance(state, dict) and state.get('status') == 'completed' and
            state.get('outcome') == 'factory_bug'):
        raise BudgetError('factory_bug_held')
