"""One judgment per configured independent family and unchanged private evidence."""
import hashlib
import json
import shutil

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
    for chain in c.models['reviewers']:
        family = r.family(chain[0])
        if family in blocked: continue
        blocked.add(family)
        output = directory / ('verdict-' + str(len(state)) + '.json')
        prior = state.get(family)
        if prior:
            if prior['status'] == 'completed':
                try: result = validate(json.loads((directory / prior['output']).read_text()))
                except (ValueError, TypeError, KeyError, OSError): result = None
                if result is not None: return result
            if prior['status'] != 'running': continue
            # Admission/provider waits and interrupted calls are not reviews.
            output = directory / prior['output']
        output.unlink(missing_ok=True)
        state[family] = {'status': 'running', 'output': output.name, 'model': chain[0]}
        atomic_results(journal, state)
        code = r.model_call(c, chain, instruction + '\nWrite the JSON verdict to ' + str(output) + '.',
                            directory, 'reviewer-' + gate.lower())
        if {name: tree_digest(directory / name) for name in inputs} != copied:
            raise InvalidInfra('reviewer changed input evidence')
        try: result = None if code else validate(json.loads(output.read_text()))
        except (ValueError, TypeError, KeyError, OSError): result = None
        state[family]['status'] = 'completed' if result is not None else 'inconclusive'
        atomic_results(journal, state)
        if result is not None: return result
    raise InfrastructureExhausted('independent review inconclusive; unchanged evidence was not repeated')
