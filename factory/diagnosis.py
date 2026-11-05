"""Scientific diagnosis schema, evidence validation and public projections."""
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import uuid
from budget import BudgetError

def infrastructure_exhausted(card):
    return (card.get("terminal_stop") == "infrastructure_exhausted" or
            isinstance(card.get("infrastructure_gate"), dict) and
            card["infrastructure_gate"].get("exhausted") is True)

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
