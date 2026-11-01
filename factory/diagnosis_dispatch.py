"""Same-owner worker diagnosis. No writer path and no independent money authority."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

import batch_service
from batch_accounting import card_total
from budget import BudgetError, reconcile_reservations
from carry_over import digest
import diagnosis as d
import diagnosis_task as task
import job_authority
import job_config
import model_router
import model_runtime
from registry import atomic_json

CARRY = ('source', 'seed', 'rotation_slot', 'roles', 'models', 'models_used', 'gates',
    'gate_results', 'gate_minutes', 'early_gates', 'failed_gate', 'failed_detail',
    'infrastructure_gate', 'late_defect', 'stress_review', 'loop_freshness', 'statement_sha256',
    'admission', 'dedup', 'dedup_skipped', 'idea_realism', 'candidate_attempts',
    'rejected_candidates', 'builder_rounds', 'recovery_config', 'factory_slots_prepared',
    'diagnosis_state', 'extension_history', 'factory_bug', 'factory_bug_resume_count')
INVALID = ('diagnosis_input_invalid', 'factory_bug_history_invalid')
STOPS = {'factory_bug': 'factory_bug_held', 'close_to_passing': 'extension_comparison_pending',
         'not_converging': 'retired_not_converging'}


class DiagnosisTaskCleanupError(RuntimeError): pass
class InputVerificationError(ValueError): pass


def verify(action, *args, **kwargs):
    """Only read/validation operations belong here, never publication or runtime."""
    try: return action(*args, **kwargs)
    except (FileNotFoundError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        raise InputVerificationError('invalid retained diagnosis input') from None


def stop(c, label):
    c.card.update(status='stopped', terminal_stop=label)
    c.stopped = True
    raise BudgetError(label)


def invalid(c):
    stop(c, 'diagnosis_input_invalid')


def read(path, base):
    return json.loads(d._input_bytes(path, base))


def retain(path, raw):
    """Immutable private bytes, synced before a journal can reference them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if verify(d._input_bytes, path, path.parent) != raw: raise InputVerificationError('changed retained bytes')
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def helper(c, operation, identity):
    # sh(c, capture=True) logs stdout, which must never contain this private wire.
    command = ['sudo', '--', 'python3', '-I', '-B', str(job_config.FACTORY / 'diagnosis_task.py'),
               operation, c.case_id, identity]
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
    if process.returncode or len(process.stdout) > task.MAX_RESPONSE: raise ValueError('task helper failed')
    value = json.loads(process.stdout)
    if (not isinstance(value, dict) or set(value) != {
            'schema_version', 'status', 'inputs_sha256', 'raw_sha256', 'raw_base64'} or
            type(value['schema_version']) is not int or value['schema_version'] != 1 or
            value['status'] not in ('ok', 'missing', 'unsafe', 'oversized', 'input_invalid') or
            (value['inputs_sha256'] is not None and not d._sha(value['inputs_sha256']))):
        raise ValueError('invalid task response')
    raw = base64.b64decode(value['raw_base64'], validate=True)
    if len(raw) > task.MAX_RESULT or hashlib.sha256(raw).hexdigest() != value['raw_sha256']:
        raise ValueError('invalid task bytes')
    return value, raw


def audit(c, identity, response, raw):
    if response['status'] == 'missing' and not raw: return
    parent = d._finding_path(c, identity).parent
    retain(parent / ('audit-bytes-' + response['raw_sha256']), raw)
    record = {key: response[key] for key in ('schema_version', 'status', 'inputs_sha256', 'raw_sha256')}
    atomic_json(parent / ('audit-' + digest(record) + '.json'), record)


def remove_task(c, identity):
    try:
        response, _ = helper(c, 'remove', identity)
        if response['status'] != 'ok': raise ValueError()
    except Exception:
        raise DiagnosisTaskCleanupError('task removal failed') from None


def cleanup_tasks(c):
    """Old pilots are already killed/joined; audit is never a verdict."""
    root = task.ROOT / c.case_id
    if task.ROOT.is_symlink() or root.is_symlink(): raise DiagnosisTaskCleanupError('linked task root')
    if not root.exists(): return
    for path in sorted(root.iterdir()):
        if path.name == '.lock': continue  # Root-owned helper lock, not a task.
        if not d._uuid4(path.name): raise DiagnosisTaskCleanupError('unknown task name')
        try:
            response, raw = helper(c, 'collect', path.name)
            audit(c, path.name, response, raw)
        except Exception:
            raise DiagnosisTaskCleanupError('task audit failed') from None
        remove_task(c, path.name)


def contract(root):
    try:
        templates = [d._input_bytes(root / 'source/factory/prompts' / name, root).decode()
                     for name in ('diagnosis.md', 'diagnosis-repair.md')]
    except (FileNotFoundError, ValueError): raise BudgetError('diagnosis_schema_wait') from None
    return templates, digest(dict(schema=d.RESULT_SCHEMA, judgment_template=templates[0], repair_template=templates[1]))


def reviewer(c):
    roles = c.card['roles']
    names = ('writer', 'stress_tester', 'strong_calibrator', 'reviewer')
    families = []
    for name in names:
        model = roles[name]['model']
        family = model_router.family(model)
        if not family or roles[name].get('family', family) != family: raise ValueError('contradictory role')
        families.append(family)
    if len(set(families)) != len(families): raise ValueError('dependent reviewer')
    return roles['reviewer']['model'], families[-1]


def journal(c, parent, manifest, schema_sha, family):
    expected = dict(schema_version=1, exhaustion_id=manifest['exhaustion_id'],
                    input_sha256=digest(manifest), schema_sha256=schema_sha, family=family)
    path = parent / 'attempts.json'
    reservations = read(c.ledger, c.ledger.parent).get('invocation_reservations', {})
    if not path.exists() and not path.is_symlink():
        prefix = 'diagnosis-' + manifest['exhaustion_id']
        if any(r.get('call_name', '').startswith(prefix) for r in reservations.values()):
            raise ValueError('bound diagnosis lacks journal')
        return {**expected, 'attempts': []}
    value = read(path, c.work)
    if not isinstance(value, dict) or set(value) != {*expected, 'attempts'}: raise ValueError('invalid journal')
    if value['schema_sha256'] != schema_sha: raise BudgetError('diagnosis_schema_wait')
    if any(value[k] != v for k, v in expected.items()) or type(value['schema_version']) is not int:
        raise ValueError('changed journal binding')
    rows = value['attempts']
    if not isinstance(rows, list): raise ValueError('invalid attempts')
    operations, leases, closed = set(), set(), set()
    for n, row in enumerate(rows):
        name = 'diagnosis-' + manifest['exhaustion_id'] + (('-repair-' + str(n)) if n else '')
        if (not isinstance(row, dict) or set(row) != {'ordinal', 'kind', 'call_name', 'operation_id',
                'status', 'repair_of', 'invocations', 'raw_sha256', 'error'} or
                type(row['ordinal']) is not int or row['ordinal'] != n or row['call_name'] != name or
                not d._uuid4(row['operation_id']) or row['operation_id'] in operations or
                row['kind'] not in ('judgment', 'repair') or row['status'] not in ('pending', 'valid', 'malformed') or
                (row['status'] in ('pending', 'valid') and n != len(rows) - 1) or
                not isinstance(row['invocations'], list)):
            raise ValueError('invalid attempt')
        previous = rows[n - 1] if n else None
        if row['kind'] == 'repair':
            if (previous is None or previous['kind'] != 'judgment' or previous['status'] != 'malformed'
                    or type(row['repair_of']) is not int or row['repair_of'] != n - 1):
                raise ValueError('invalid repair')
        elif row['repair_of'] is not None or (previous and previous['kind'] != 'repair'):
            raise ValueError('skipped repair')
        operations.add(row['operation_id'])
        for invocation in row['invocations']:
            if not isinstance(invocation, dict) or set(invocation) != {'lease_id', 'invocation_id', 'route', 'pool'}:
                raise ValueError('invalid invocation')
            retained = reservations[invocation['lease_id']]
            if (invocation['lease_id'] in leases or any(retained[k] != v for k, v in invocation.items()) or
                    retained['operation_id'] != row['operation_id'] or retained['call_name'] != name or
                    model_router.family(invocation['route']) != family): raise ValueError('unbound invocation')
            leases.add(invocation['lease_id'])
            if invocation['route'] in closed: raise ValueError('reused malformed route')
        if row['status'] == 'pending':
            if row['raw_sha256'] is not None or row['error'] is not None: raise ValueError('pending answer')
        elif (not row['invocations'] or not d._sha(row['raw_sha256']) or
                (row['status'] == 'valid' and row['error'] is not None) or
                (row['status'] == 'malformed' and row['error'] not in ('schema', 'missing', 'unsafe', 'oversized'))):
            raise ValueError('invalid completed answer')
        else:
            raw_answer(parent, row)  # A referenced answer cannot disappear or change.
        if row['kind'] == 'repair' and any(i['route'] != previous['invocations'][-1]['route'] for i in row['invocations']):
            raise ValueError('repair changed route')
        if row['kind'] == 'repair' and row['status'] == 'malformed': closed.add(row['invocations'][-1]['route'])
    return value


def raw_answer(parent, row):
    raw = d._input_bytes(parent / ('raw-bytes-' + row['raw_sha256']), parent)
    if len(raw) > task.MAX_RESULT or hashlib.sha256(raw).hexdigest() != row['raw_sha256']:
        raise ValueError('changed answer')
    return raw


def validate(c, manifest, root, raw):
    return d.validate_result(json.loads(raw), case=c.case_id, generation=manifest['generation'], evidence_root=root)


def decision(c, parent, manifest, result):
    value = dict(schema_version=1, exhaustion_id=manifest['exhaustion_id'], input_sha256=digest(manifest), diagnosis=result)
    path = parent / 'decision.json'
    if path.exists():
        if verify(read, path, c.work) != value: raise InputVerificationError('changed decision')
    else: atomic_json(path, value)
    return result


def apply(c, parent, manifest, result, *, resume=False):
    root = parent / 'inputs'
    if result['outcome'] == 'factory_bug':
        d.persist_factory_bug(c, result, generation=manifest['generation'], evidence_root=root)
    else:
        state = c.card['diagnosis_state']
        if state['status'] == 'completed' and state['outcome'] != result['outcome']: raise InputVerificationError('changed outcome')
        state.update(status='completed', outcome=result['outcome'])
        c.card.update(status='stopped', terminal_stop=STOPS[result['outcome']])
        if result['outcome'] == 'close_to_passing':
            import extensions
            row = extensions.active(c)
            if row is None:
                history = extensions.read(c)
                if history and history[-1]['exhaustion_id'] != manifest['exhaustion_id']:
                    prior = history[-1]
                    versions = [stage['version'] for stage in prior['outcome']['stages']]
                    pair = extensions.comparison_pair(prior, versions)
                    if pair is None or extensions.progress(pair['entry'], pair['outcome']) == 'pending':
                        stop(c, 'extension_comparison_pending')
                row = (history[-1] if history and
                       history[-1]['exhaustion_id'] == manifest['exhaustion_id'] else None)
            if row is not None:
                if row['exhaustion_id'] != manifest['exhaustion_id']:
                    raise InputVerificationError('extension differs from diagnosis')
                if row['outcome'] is None:
                    extensions.writer_receipt(c)
                else:
                    from extension_package import completed_route
                    completed_route(c, row)
            if batch_service.DIAGNOSIS_ENABLED is True:
                atomic_json(c.work / 'scorecard.json', c.card)
                return row['extension_id'] if row is not None else 0
        atomic_json(c.work / 'scorecard.json', c.card)
    stop(c, STOPS[result['outcome']])


def replay(c, parent, manifest, journal_value=None):
    result = None
    path = parent / 'decision.json'
    if path.exists() or path.is_symlink():
        if (not journal_value or not journal_value['attempts'] or
                journal_value['attempts'][-1]['status'] != 'valid'):
            raise InputVerificationError('decision lacks completed journal')
        value = verify(read, path, c.work)
        if (not isinstance(value, dict) or set(value) != {'schema_version', 'exhaustion_id', 'input_sha256', 'diagnosis'} or
                type(value['schema_version']) is not int or value['schema_version'] != 1 or
                value['exhaustion_id'] != manifest['exhaustion_id'] or value['input_sha256'] != digest(manifest)):
            raise InputVerificationError('invalid decision')
        result = d.validate_result(value['diagnosis'], case=c.case_id, generation=manifest['generation'],
                                   evidence_root=parent / 'inputs')
        if result != value['diagnosis']: raise InputVerificationError('unnormalized decision')
        retained = verify(validate, c, manifest, parent / 'inputs', verify(raw_answer, parent, journal_value['attempts'][-1]))
        if result != retained: raise InputVerificationError('decision differs from retained answer')
    finding = parent / 'finding.json'
    if finding.exists() or finding.is_symlink():
        if result is not None:
            previous = verify(read, finding, c.work)
            if not isinstance(previous, dict) or previous.get('diagnosis') != result:
                raise InputVerificationError('conflicting finding')
        d.restore_factory_bug(c, generation=manifest['generation'], evidence_root=parent / 'inputs')
        stop(c, 'factory_bug_held')
    if result is not None: return apply(c, parent, manifest, result, resume=True)


def closed_routes(value):
    return {row['invocations'][-1]['route'] for row in value['attempts']
            if row['kind'] == 'repair' and row['status'] == 'malformed'}


def carry_context(c):
    """Carry before cleanup too: its infrastructure failure must not erase roles."""
    previous = c.checkpoint_card
    if (previous.get('diagnosis_state') is None and not previous.get('extension_history') and
            not (c.work / 'extension-history.json').exists()): return False
    for key in CARRY:
        if key in previous: c.card[key] = copy.deepcopy(previous[key])
    return True


def _dispatch(c, r):
    previous = c.checkpoint_card
    if not carry_context(c): return False
    state = previous.get('diagnosis_state')
    if previous.get('terminal_stop') in INVALID: stop(c, previous['terminal_stop'])
    job_authority.for_case(c)
    if d._state(c.card, d.extension_history(c.card)) is None: invalid(c)
    if d.resume_factory_bug(c, r): return False
    model_runtime.prepare_dispatch(c)
    with c.model_dispatch_lock:
        if c.active_model_calls: raise BudgetError('usage_reconciliation_while_active')
        unknown = verify(card_total, previous) is None
        r.resume_provider_wait(c)
        reconcile_reservations(c.work, c.ledger)
        ledger = verify(read, c.ledger, c.ledger.parent)
        if ledger.get('active') or any(row['state'] == 'pending' for row in ledger.get('invocation_reservations', {}).values()):
            raise BudgetError('usage_reconciliation_pending')
        if unknown and state['status'] == 'pending': stop(c, 'diagnosis_pending')
        import extensions
        if c.card.get('extension_history') or (c.work / 'extension-history.json').exists(): extensions.read(c)
        manifest = d.queued_inputs(c, r.BENCH, quiescent=True)
        parent = d._finding_path(c, manifest['exhaustion_id']).parent
        value = None
        if (parent / 'attempts.json').exists() or (parent / 'attempts.json').is_symlink():
            templates, schema_sha = contract(parent / 'inputs')
            model, family = verify(reviewer, c)
            value = verify(journal, c, parent, manifest, schema_sha, family)
        extension_id = replay(c, parent, manifest, value)
        if type(extension_id) is int: return extension_id
        if value is None:
            templates, schema_sha = contract(parent / 'inputs')
            model, family = verify(reviewer, c)
            value = verify(journal, c, parent, manifest, schema_sha, family)
        if value['attempts'] and value['attempts'][-1]['status'] == 'valid':
            try: result = verify(validate, c, manifest, parent / 'inputs', verify(raw_answer, parent, value['attempts'][-1]))
            except (ValueError, BudgetError): invalid(c)
            return apply(c, parent, manifest, decision(c, parent, manifest, result))
        if state['status'] == 'completed': invalid(c)
        routes = model_router.routes(model, getattr(c, 'router_accounts', model_router.ACCOUNTS))
        if routes and all(row['route'] in closed_routes(value) for row in routes): stop(c, 'retired_diagnosis_malformed')
        if batch_service.DIAGNOSIS_ENABLED is not True: stop(c, 'diagnosis_pending')
        from worker_release import verify_selected_drivers
        c.diagnosis_driver_qualification = verify_selected_drivers({'reviewer': [model]},
            lambda driver: r.pinned_cli(driver) if driver in ('codex', 'claude') else r.OPENCODE_BIN)
        return invoke(c, r, parent, manifest, model, routes, templates, value)


def dispatch(c, r):
    """Called immediately after verified job installation; all handled paths stop."""
    try:
        return _dispatch(c, r)
    except InputVerificationError:
        invalid(c)
    except BudgetError as error:
        if str(error) in ('diagnosis_result_invalid', 'diagnosis_finding_invalid'):
            invalid(c)
        if str(error) == 'diagnosis_schema_wait': stop(c, str(error))
        raise


def invoke(c, r, parent, manifest, model, routes, templates, value):
    identity = manifest['exhaustion_id']
    old_operation = getattr(c, 'model_operation_id', None)
    old_exclusions = getattr(c, 'router_excluded', None)
    prepared = False
    preserve_task = False
    try:
        r.make_pilots(c, [('pilot', None)], True, diagnosis=True)
        while True:
            rows = value['attempts']
            closed = closed_routes(value)
            if routes and all(route['route'] in closed for route in routes): stop(c, 'retired_diagnosis_malformed')
            if not rows or rows[-1]['status'] != 'pending':
                n = len(rows)
                repair = bool(rows and rows[-1]['kind'] == 'judgment')
                rows.append(dict(ordinal=n, kind='repair' if repair else 'judgment',
                    call_name='diagnosis-' + identity + (('-repair-' + str(n)) if n else ''),
                    operation_id=str(uuid.uuid4()), status='pending', repair_of=n - 1 if repair else None,
                    invocations=[], raw_sha256=None, error=None))
                atomic_json(parent / 'attempts.json', value)
            row = rows[-1]
            pinned = rows[row['repair_of']]['invocations'][-1]['route'] if row['kind'] == 'repair' else None
            c.router_excluded = tuple(set(old_exclusions or ()) | {
                route['pool'] + '/' + route['route'] for route in routes
                if route['route'] in closed or (pinned is not None and route['route'] != pinned)})
            c.model_operation_id = row['operation_id']
            prepared = True  # A partial prepare must also be removed.
            response, _ = helper(c, 'prepare', identity)
            expected = digest(manifest['files']) if row['kind'] == 'judgment' else None
            if response['status'] != 'ok' or response['inputs_sha256'] != expected:
                raise RuntimeError('task preparation failed')
            exposed = task.ROOT / c.case_id / identity
            context = dict(case_id=c.case_id, checkpoint_sha256=manifest['generation'],
                           output=str(exposed / 'output/result.json'), schema=d.RESULT_SCHEMA)
            if pinned is None: context['inputs'] = str(exposed / 'inputs')
            else:
                previous = rows[row['repair_of']]
                context.update(retained_answer=verify(raw_answer, parent, previous).decode('utf-8', errors='replace'),
                               error=previous['error'])
            text = templates[1 if pinned else 0] + '\nRun context (data):\n' + json.dumps(context, sort_keys=True)

            def admitted():
                reservation = c.invocation_reservation
                if reservation['operation_id'] != row['operation_id'] or reservation['call_name'] != row['call_name']:
                    raise ValueError('invocation differs')
                invocation = {key: reservation[key] for key in ('lease_id', 'invocation_id', 'route', 'pool')}
                if invocation not in row['invocations']: row['invocations'].append(invocation)
                atomic_json(parent / 'attempts.json', value)
                try:
                    response, raw = helper(c, 'collect', identity)
                    audit(c, identity, response, raw)
                except Exception:
                    raise DiagnosisTaskCleanupError('predecessor task audit failed') from None
                response, _ = helper(c, 'reset', identity)
                if response['status'] != 'ok': raise RuntimeError('task reset failed')

            try:
                r.opencode(c, [model], text, exposed / 'output', row['call_name'], user='pilot', before_attempt=admitted)
                response, raw = helper(c, 'collect', identity)
                if response['status'] == 'input_invalid' or response['inputs_sha256'] != expected: invalid(c)
                retain(parent / ('raw-bytes-' + response['raw_sha256']), raw)
                result, error = None, response['status'] if response['status'] != 'ok' else None
                if error is None:
                    try: result = validate(c, manifest, parent / 'inputs', raw)
                    except (ValueError, BudgetError): error = 'schema'
                row.update(status='malformed' if error else 'valid', raw_sha256=response['raw_sha256'], error=error)
                atomic_json(parent / 'attempts.json', value)
            except BaseException:
                # _invoke has already killed its pilot process; partial bytes are audit only.
                try:
                    response, raw = helper(c, 'collect', identity)
                    audit(c, identity, response, raw)
                except Exception:
                    preserve_task = True
                    raise DiagnosisTaskCleanupError('interrupted task audit failed') from None
                raise
            finally:
                if not preserve_task:
                    remove_task(c, identity); prepared = False
            if result is not None: return apply(c, parent, manifest, decision(c, parent, manifest, result))
    finally:
        if old_operation is None: c.__dict__.pop('model_operation_id', None)
        else: c.model_operation_id = old_operation
        if old_exclusions is None: c.__dict__.pop('router_excluded', None)
        else: c.router_excluded = old_exclusions
        try:
            r.dispose_diagnosis_pilot(c)
        finally:
            if prepared and not preserve_task: remove_task(c, identity)


def admit_extension(c, r, previous):
    """Convert a validated diagnosis into one reserved writer, outside dispatch."""
    import extension_package
    import extensions
    from late_recovery import invalidate

    job_authority.for_case(c)
    history = extensions.read(c)
    state = d._state(c.card, extensions.public(history))
    if not state or state['status'] != 'completed' or state['outcome'] != 'close_to_passing':
        raise BudgetError('extension_diagnosis_required')
    if history and history[-1]['outcome'] is None:
        raise BudgetError('extension_already_active')
    if len(history) >= extensions.LIMIT:
        raise BudgetError('retired_extension_limit')
    entry = getattr(extension_package, 'entry', None)
    if entry is None:
        raise BudgetError('extension_comparison_pending')
    proposal = extensions.propose(c, entry(c, r))
    number = proposal['round']
    problems = r.writer_feedback(c, previous)
    receipt, prompt = r.writer_request(c, number, number, None, problems, [], [],
                                       r.case_hash(c), bool(problems))
    r.pending_call(c, c.models['builder'], prompt, c.case, f'builder-{number}', receipt,
        role='writer', extension_proposal=proposal, on_admitted=lambda: invalidate(c),
        on_complete=lambda: r.complete_writer(c, receipt, c.work / 'attack-state.json'))
    row = extensions.active(c)
    if row is None or row['extension_id'] != proposal['extension_id']:
        raise BudgetError('extension_reservation_mismatch')
    return row['extension_id']
