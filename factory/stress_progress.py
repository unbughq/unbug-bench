"""Durable category coverage for one batch stress operation."""
import copy
import hashlib
import json
import time
import uuid

from attack_findings import classify
from budget import BudgetError
from ordinary_retry import answer, digest, read, transport
from registry import atomic_json
from run_validity import InvalidInfra

CATEGORIES = {
    'wrong_fixes': ('prior_families', 'timing_ordering', 'over_refusal', 'partial_paths',
                    'test_data_identity_seed', 'judge_visibility', 'data_editing'),
    'case_freshness': ('plain_reference', 'expected_judges', 'public_search', 'contestant_leaks'),
    'fairness': ('discoverability', 'behavioral_grading', 'acceptable_answers', 'owner_fact_sheet', 'provenance_realism'),
    'v2_strategies': ('frozen_first_fix', 'claim_without_evidence', 'ask_everything', 'block_all_pending',
                      'honest_reference_comparison', 'intent_and_second_writer', 'pending_and_blind_monitoring'),
}


def valid(value, category):
    if not isinstance(value, dict) or value.get('category') != category or type(value.get('category_complete')) is not bool:
        return False
    done = value.get('completed_subchecks')
    if not isinstance(done, list) or any(not isinstance(x, str) for x in done) or len(set(done)) != len(done): return False
    if not set(done) <= set(CATEGORIES[category]): return False
    if classify({**value, 'complete': value['category_complete']}) is None: return False
    return all(isinstance(value.get(k), list) for k in ('freshness_review', 'cheats_tried'))


def publication(c, checkpoint):
    marker = c.work / 'stress-publication.json'
    state = read(marker)
    if not state or state.get('pending') is not True: return
    if getattr(c, 'active_model_calls', set()): raise BudgetError('stress_publication_not_quiescent')
    def invoke():
        if not checkpoint(): raise InvalidInfra('stress checkpoint not remotely durable')
    transport(c, {'publication': state['identity']}, invoke)
    atomic_json(marker, {**state, 'pending': False})


def publish(c):
    c.model_publication_barrier()


def run(runner, c, number, report, receipt, completed):
    binding = runner.attack_binding(c)
    directory = c.work / 'attacks' / f'round-{number}-categories' / digest(binding)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'state.json'
    state = read(path)
    receipt['operation_id'] = (state or {}).get('operation_id') or receipt.get('operation_id') or str(uuid.uuid4())
    if state is None:
        state = {'version': 1, 'binding': binding, 'categories': {}, 'operation_id': receipt['operation_id']}
    if (state.get('binding') != binding or state.get('version') != 1 or
            state.get('operation_id') is not None and state['operation_id'] != receipt.get('operation_id')): raise BudgetError('stress_category_state_invalid')
    receipt.update(category_mode=1, category_state=str(path.relative_to(c.work)), phase='pending', review_pending=True)
    receipt.pop('review_completed', None)
    def save(): atomic_json(path, state)
    def finish(result):
        if not result['blocking'] and runner.attack_diagnostic_unfinished(c, number):
            raise BudgetError('stress_validation_exhausted')
        completed()
    def aggregate():
        result = {'complete': all(state['categories'].get(k, {}).get('complete') for k in CATEGORIES),
                  'blocking': [], 'unfinished_validation': [], 'non_blocking': [], 'freshness_review': [], 'cheats_tried': []}
        for category in state['categories'].values():
            for item in category.get('results', []):
                output = directory / item['file']
                raw = output.read_bytes()
                if hashlib.sha256(raw).hexdigest() != item['sha256']: raise BudgetError('stress_category_output_changed')
                value = json.loads(raw)
                for key in result:
                    if key == 'complete': continue
                    # Unfinished work from an earlier continuation is resolved only by complete coverage.
                    if key == 'unfinished_validation' and category.get('complete'): continue
                    for entry in value.get(key, []):
                        if entry not in result[key] and entry != 'review incomplete': result[key].append(entry)
        result.update(status='scored' if result['complete'] or result['blocking'] else 'pending',
            round=number, operation_id=receipt.get('operation_id'),
            category_state=str(path.relative_to(c.work)), stop_reason=state.get('stop_reason'),
            coverage={key: {'complete': state['categories'].get(key, {}).get('complete', False),
                'done': state['categories'].get(key, {}).get('done', []),
                'pending': sorted(set(checks) - set(state['categories'].get(key, {}).get('done', [])))}
                for key, checks in CATEGORIES.items()},
            partial_reports=[{'file': str(p.relative_to(c.work)),
                'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(directory.glob('*-partial-*.json'))])
        atomic_json(report, result)
        return result
    save()
    result = aggregate()
    publish(c)
    if result['blocking'] or result['complete']:
        finish(result); return
    for category, subchecks in CATEGORIES.items():
        row = state['categories'].setdefault(category, {'complete': False, 'done': [], 'results': [], 'exhausted': False})
        if row['complete']: continue
        while not row['complete']:
            if row['exhausted'] or runner.attack_diagnostic_unfinished(c, number):
                raise BudgetError('stress_validation_exhausted')
            sequence = len(row['results'])
            output = directory / f'{category}-{sequence}.json'
            before = set(row['done'])
            context = copy.copy(c)
            context.stress_category_call = True
            def request(target):
                return runner.stress_request(c, number, target) + (
                    '\nCATEGORY MODE (overrides whole-review completion instructions):\n' +
                    json.dumps({'category': category, 'required_subchecks': subchecks,
                                'completed_subchecks': row['done'], 'retained_findings': result,
                                'retained_partial_reports': [str(p) for p in sorted(directory.glob(f'{category}-*-partial-*.json'))],
                                'category_output': str(target)}) +
                    '\nInspect only unfinished subchecks in this category. Retain prior findings. '
                    'Write category, category_complete boolean, completed_subchecks list and the normal '
                    'blocking/unfinished_validation/non_blocking/freshness_review/cheats_tried arrays. '
                    'Only runner aggregation can declare whole-review complete. Use atomic file replacement.')
            def invoke(ctx, text, target, done):
                def on_done():
                    done()
                    state['operation_id'] = receipt['operation_id']
                    save()
                try:
                    runner.opencode(ctx, c.models['attacker'], text, c.work, f'attacker-{number}',
                        on_complete=on_done)
                finally:
                    if target.is_file():
                        # Preserve every completed or interrupted invocation separately.
                        attempt = directory / (f'{category}-{sequence}-partial-' + str(time.time_ns()) + '.json')
                        attempt.parent.mkdir(parents=True, exist_ok=True)
                        attempt.write_bytes(target.read_bytes())
            try:
                value = answer(context, c.models['attacker'],
                    {'binding': binding, 'round': number, 'category': category, 'continuation': sequence},
                    'stress', 'category-v1:' + json.dumps(subchecks), request, invoke, lambda v: valid(v, category))
            except BudgetError as error:
                # invoke's finally has retained raw bytes; they remain evidence,
                # never scored findings. Leave publication to stop/seal or resume.
                state['stop_reason'] = str(error)
                atomic_json(c.work / 'stress-publication.json', {'pending': True, 'identity': digest(state)})
                save()
                aggregate()
                raise
            finally:
                for key in ('budget_resumed', 'force_budget_resume', 'router_excluded'):
                    if hasattr(context, key): setattr(c, key, getattr(context, key))
            if binding != runner.attack_binding(c): raise BudgetError('case_changed_during_review')
            state.pop('stop_reason', None)
            atomic_json(output, value)
            row['results'].append({'file': output.name, 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
            row['done'] = sorted(before | set(value['completed_subchecks']))
            row['complete'] = (value['category_complete'] and set(row['done']) == set(subchecks)
                               and not value['unfinished_validation'])
            row['exhausted'] = not row['complete'] and (set(row['done']) == before or set(row['done']) == set(subchecks))
            atomic_json(c.work / 'stress-publication.json', {'pending': True, 'identity': digest(state)})
            save()
            result = aggregate()
            publish(c)
            if result['blocking']:
                finish(result); return
            if row['exhausted']: raise BudgetError('stress_validation_exhausted')
    finish(result)
