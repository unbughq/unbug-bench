"""Batch transport waits and retained-answer repair; neither spends writer rounds."""
import copy
import hashlib
import json
from pathlib import Path
import time

from budget import BudgetError
import model_router
import model_runtime
from registry import atomic_json
from run_validity import InvalidInfra


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read(path, default=None):
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError: return default
    except (ValueError, TypeError) as error: raise BudgetError('ordinary_retry_state_invalid') from error


def check(c):
    if time.time() >= model_router.epoch(c.batch_deadline):
        raise BudgetError('provider_wait_deadline')
    cancel = getattr(c, 'role_cancel', None)
    if cancel is not None and cancel.is_set(): raise BudgetError('cancelled')


def backoff(c, failures=1, *, deadline=None):
    end = time.monotonic() + min(60, 5 * 2 ** min(max(failures - 1, 0), 4))
    if deadline is not None: end = min(end, deadline)
    while True:
        check(c)
        remaining = end - time.monotonic()
        if remaining <= 0: return
        cancel = getattr(c, 'role_cancel', None)
        if cancel is not None: cancel.wait(min(1, remaining))
        else: time.sleep(min(1, remaining))


def transport(c, identity, invoke, *, deadline=None):
    """Only declared retrieval/publication errors retry; programming errors escape."""
    path = c.work / 'ordinary-retries' / digest({'transport': identity}) / 'state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    state = read(path, {'version': 1, 'transport_failures': 0})
    failures = 0
    while True:
        check(c)
        if deadline is not None and time.monotonic() >= deadline:
            raise InvalidInfra('transport window expired')
        try: return invoke()
        except InvalidInfra as error:
            state['transport_failures'] += 1
            state['last_error'] = str(error)
            atomic_json(path, state)
            failures += 1
            backoff(c, failures, deadline=deadline)


def decode(raw):
    text = raw.decode('utf-8')
    if text.startswith('```json\n') and text.rstrip().endswith('```'):
        text = text[8:text.rfind('```')]
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def projection(value, kind):
    """Only typed decisions already in an answer may survive schema-only repair."""
    if not isinstance(value, dict): raise ValueError('not an object')
    if kind == 'dedup':
        result = value['duplicate_of']
        if result is not None and not isinstance(result, str): raise ValueError('duplicate_of')
        return result
    if kind == 'idea':
        if type(value['approve']) is not bool: raise ValueError('approve')
        return value['approve']
    if kind == 'panel':
        result = [value[k]['approve'] for k in ('fairness', 'realism')]
        if any(type(v) is not bool for v in result): raise ValueError('approve')
        return result
    if kind == 'freshness':
        rows = value['hits']
        if not isinstance(rows, list): raise ValueError('hits')
        result = []
        for row in rows:
            if type(row['resolved']) is not bool or row['same_bug'] is not None and type(row['same_bug']) is not bool:
                raise ValueError('freshness decision')
            if type(row['retrieved']) is not bool: raise ValueError('retrieved')
            if any(not isinstance(row[k], str) for k in ('url', 'app_version', 'version_scope')):
                raise ValueError('freshness decision strings')
            result.append({k: row.get(k, 'live' if k == 'retrieved_from' else None) for k in
                ('url', 'resolved', 'same_bug', 'retrieved', 'retrieved_from', 'archive_checked',
                 'archive_available', 'archive_snapshot_url', 'live_failure', 'app_version', 'version_scope')})
        return result
    if kind == 'stress':
        result = {k: value[k] for k in ('category', 'category_complete', 'completed_subchecks',
                  'blocking', 'unfinished_validation', 'freshness_review', 'cheats_tried')}
        if type(result['category_complete']) is not bool: raise ValueError('category_complete')
        if any(not isinstance(result[k], list) for k in result if k not in ('category', 'category_complete')):
            raise ValueError('stress lists')
        return result
    raise ValueError('unknown projection')


def answer(c, models, identity, kind, schema, request, invoke, validate):
    """invoke(context, text, output_path, completed) must call completed only on success.

    Request is a function of the immutable attempt output path. The caller owns
    scientific validation; this module owns durability, repair and route bounds.
    """
    binding = {'inputs': identity, 'model': models[0], 'schema': schema, 'kind': kind, 'version': 1}
    directory = c.work / 'ordinary-retries' / digest(binding)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'state.json'
    state = read(path, {'version': 1, 'binding': binding, 'spent_routes': [], 'attempts': []})
    if state.get('binding') != binding or not isinstance(state.get('attempts'), list):
        raise BudgetError('ordinary_retry_state_invalid')
    routes = model_router.routes(models[0], getattr(c, 'router_accounts', model_router.ACCOUNTS))
    approved = {row['route'] for row in routes}
    if not isinstance(state.get('spent_routes'), list) or not set(state['spent_routes']) <= approved:
        raise BudgetError('ordinary_retry_state_invalid')
    def save(): atomic_json(path, state)
    def payload(row):
        output = directory / row['output']
        raw = output.read_bytes() if output.is_file() else b''
        if row.get('sha256') != hashlib.sha256(raw).hexdigest():
            raise BudgetError('ordinary_retry_output_changed')
        return raw
    while True:
        check(c)
        row = state['attempts'][-1] if state['attempts'] else None
        if row and row['phase'] == 'completed':
            raw = payload(row)
            try:
                value = decode(raw)
                if not validate(value): raise ValueError('schema validation failed')
                if row['kind'] == 'repair':
                    original = state['attempts'][row['original']]
                    if projection(value, kind) != projection(decode(payload(original)), kind):
                        raise ValueError('repair changed scientific decision')
            except (ValueError, TypeError, KeyError, UnicodeError) as error:
                row['validation_error'] = str(error)
                try: projection(decode(raw), kind); projectable = True
                except (ValueError, TypeError, KeyError, UnicodeError): projectable = False
                if row['kind'] == 'judgment' and projectable:
                    row['phase'] = 'invalid'
                    state['attempts'].append({'kind': 'repair', 'original': len(state['attempts']) - 1,
                        'route': row['route'], 'phase': 'pending', 'output': f'answer-{len(state["attempts"])}.json'})
                else:
                    row['phase'] = 'invalid'
                    if row['route'] not in state['spent_routes']: state['spent_routes'].append(row['route'])
                save()
                continue
            else:
                # Keep completed as the replayable authenticated state.
                row['validated'] = True
                save()
                return value
        if not row or row['phase'] == 'invalid':
            if approved <= set(state['spent_routes']): raise BudgetError('malformed_output_exhausted')
            row = {'kind': 'judgment', 'phase': 'pending', 'output': f'answer-{len(state["attempts"])}.json'}
            state['attempts'].append(row); save()
        if row['phase'] != 'pending': raise BudgetError('ordinary_retry_state_invalid')
        output = directory / row['output']
        # Preserve a killed call's partial bytes before giving it a fresh file.
        if output.exists():
            partial = directory / (row['output'] + '.partial-' + str(time.time_ns()))
            output.rename(partial)
        model_runtime.prepare_dispatch(c)
        context = copy.copy(c)
        excluded = set(getattr(c, 'router_excluded', ()))
        excluded.update(r['pool'] + '/' + r['route'] for r in routes if r['route'] in state['spent_routes']
                        or row['kind'] == 'repair' and r['route'] != row['route'])
        context.router_excluded = tuple(excluded)
        if row['kind'] == 'repair':
            original = state['attempts'][row['original']]
            text = ('Repair JSON shape only. Do not investigate or invent decisions. Preserve every decision, '
                    'finding and uncertainty. If impossible return {"status":"unresolved","reason":"..."}. '
                    'Write only to ' + str(output) + '. Schema: ' + schema + '\nRetained answer:\n' +
                    payload(original).decode('utf-8', errors='replace') + '\nValidation error: ' + original['validation_error'])
        else: text = request(output)
        def completed():
            raw = output.read_bytes() if output.is_file() else b''
            row.update(phase='completed', route=context.model_lease.route,
                       sha256=hashlib.sha256(raw).hexdigest())
            save()
        try:
            invoke(context, text, output, completed)
        finally:
            for key in ('budget_resumed', 'force_budget_resume'):
                if hasattr(context, key): setattr(c, key, getattr(context, key))
            # Keep newly observed outage exclusions, but discard this helper's
            # temporary deterministic-output route exclusions.
            c.router_excluded = tuple(set(getattr(c, 'router_excluded', ())) |
                                      (set(getattr(context, 'router_excluded', ())) - excluded))
        if row['phase'] != 'completed': raise BudgetError('ordinary_retry_completion_missing')
