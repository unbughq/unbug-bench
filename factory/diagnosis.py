"""Pure content-free exhaustion eligibility; the caller authenticates collection.

Private findings, local state, clocks and output-generation hashes are not read.
These predicates never grant authority to launch or spend.
"""
import re
import uuid
from recovery import infrastructure_exhausted


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
            stop in ('provider_wait', 'paused', 'ttl_retired') or
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
    from budget import BudgetError
    history = extension_history(card)
    if history is None: raise BudgetError('diagnosis_state_invalid')
    state = _state(card, history)
    if 'diagnosis_state' in card and state is None: raise BudgetError('diagnosis_state_invalid')
    if state and state['status'] == 'pending': return
    if state and not new_exhaustion: return
    if (not exhaustion(card) or not _trigger(card, card.get('terminal_stop'), history) or
            (history and history[-1]['outcome_sha256'] is None)): return
    card['diagnosis_state'] = dict(schema_version=1, exhaustion_id=str(uuid.uuid4()),
        stop=card['terminal_stop'], status='pending', outcome=None)
