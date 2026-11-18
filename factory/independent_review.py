"""One judgment per configured independent family and unchanged private evidence."""
import hashlib
import json
import shutil
import contextvars
import copy
import threading
from concurrent.futures import ThreadPoolExecutor

from calibration import atomic_results, tree_digest
from run_validity import InfrastructureExhausted, InvalidInfra


def review(c, r, gate, inputs, instruction, validate):
    if hasattr(r, "engine_review_ruling"):
        instruction += r.engine_review_ruling(c, gate)
    blocked = {r.family(c.models[name][0]) for name in ('builder', 'strong_calibrator')}
    binding = {'inputs': {name: tree_digest(path) for name, path in inputs.items()}, 'instruction': instruction}
    key = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    directory = c.work / ('independent-' + gate.lower() + '-' + key)
    if not directory.exists():
        directory.mkdir()
        for name, path in inputs.items(): shutil.copytree(path, directory / name)
    copied = {name: tree_digest(directory / name) for name in inputs}
    if copied != binding['inputs']: raise InvalidInfra('review inputs changed')
    journal = directory / 'reviews.json'
    state = json.loads(journal.read_text()) if journal.exists() else {}
    # Speed plan 2026-11-18: the reviewers are asked side by side, not one after the other. The verdict
    # is unchanged: the first family's valid answer still wins, the next one's only when it is inconclusive.
    # ponytail: the gate waits for both calls, so a slower second reviewer can delay a first-reviewer verdict.
    asks = []
    for index, chain in enumerate(c.models['reviewers']):
        family = r.family(chain[0])
        if family in blocked: continue
        blocked.add(family)
        prior = state.get(family)
        if prior:
            if prior['status'] == 'completed':
                try: result = validate(json.loads((directory / prior['output']).read_text()))
                except (ValueError, TypeError, KeyError, OSError): result = None
                if result is not None:
                    asks.append((index, chain, family, result))
                    break   # no later family is asked before an answer that already decides
            if prior['status'] != 'running': continue
            # Admission/provider waits and interrupted calls are not reviews.
            output = directory / prior['output']
        else:
            output = directory / ('verdict-' + str(len(state)) + '.json')
        output.unlink(missing_ok=True)
        state[family] = {'status': 'running', 'output': output.name, 'model': chain[0]}
        asks.append((index, chain, family, None))
    atomic_results(journal, state)
    lock = threading.Lock()

    def ask(context, index, chain, family):
        output = directory / state[family]['output']
        code = r.model_call(context, chain, instruction + '\nWrite the JSON verdict to ' + str(output) + '.',
                            directory,
                            ('reviewer-' if index == 0 else f'reviewer-{index + 1}-') + gate.lower())
        if {name: tree_digest(directory / name) for name in inputs} != copied:
            raise InvalidInfra('reviewer changed input evidence')
        try: result = None if code else validate(json.loads(output.read_text()))
        except (ValueError, TypeError, KeyError, OSError): result = None
        with lock:
            state[family]['status'] = 'completed' if result is not None else 'inconclusive'
            atomic_results(journal, state)
        return result

    calls = [a for a in asks if a[3] is None]
    # A budget resume still pending hands the ledger over in the first call (as G10 runs serially then).
    if len(calls) < 2 or (getattr(getattr(c, 'args', None), 'resume', None) and not getattr(c, 'budget_resumed', False)):
        answers = {}
        for index, chain, family, retained in asks:
            answers[family] = retained if retained is not None else ask(c, index, chain, family)
            if answers[family] is not None: return answers[family]
    else:
        # As G10's calibrators: each call gets its own context (the runtime keeps its lease on it).
        if getattr(c, 'role_cancel', None) is None: c.role_cancel = threading.Event()
        from durable.checkpoints import concurrent_section
        with concurrent_section(c), ThreadPoolExecutor(max_workers=len(calls)) as pool:
            children = [copy.copy(c) for _ in calls]
            futures = {family: pool.submit(contextvars.copy_context().run, ask, child, index, chain, family)
                       for child, (index, chain, family, _) in zip(children, calls)}
            try: answers = {family: future.result() for family, future in futures.items()}
            except BaseException:
                c.role_cancel.set()
                raise
        for index, chain, family, retained in asks:
            result = retained if retained is not None else answers[family]
            if result is not None: return result
    raise InfrastructureExhausted('independent review inconclusive; unchanged evidence was not repeated')
