"""One accounted diagnosis call through the root-owned disposable task boundary."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

from budget import BudgetError
from carry_over import digest
import diagnosis
import diagnosis_task as task


def _helper(runner, c, operation, identity):
    # The private result must never pass through runner.sh's stdout logging.
    command = ['sudo', '--', 'python3', '-I', '-B',
               str(Path(runner.__file__).parent / 'diagnosis_task.py'),
               operation, c.case_id, identity]
    try:
        process = subprocess.run(command, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, timeout=120)
        if process.returncode or len(process.stdout) > task.MAX_RESPONSE:
            raise ValueError()
        value = json.loads(process.stdout)
        if (not isinstance(value, dict) or set(value) != {
                'schema_version', 'status', 'inputs_sha256', 'raw_sha256', 'raw_base64'} or
                type(value['schema_version']) is not int or value['schema_version'] != 1 or
                value['status'] != 'ok' or
                (value['inputs_sha256'] is not None and not diagnosis._sha(value['inputs_sha256'])) or
                not diagnosis._sha(value['raw_sha256']) or
                not isinstance(value['raw_base64'], str)):
            raise ValueError()
        raw = base64.b64decode(value['raw_base64'], validate=True)
        if len(raw) > task.MAX_RESULT or hashlib.sha256(raw).hexdigest() != value['raw_sha256']:
            raise ValueError()
        return value, raw
    except Exception:
        raise BudgetError('diagnosis_result_invalid') from None


def invoke(runner, c, *, model, prompt, inputs, output):
    """Transport immutable inputs and return bytes; the engine validates the verdict."""
    identity = str(uuid.uuid4())
    source = c.work / 'diagnosis' / identity
    exposed = task.ROOT / c.case_id / identity
    prepared = False
    first = None  # the error that ended the call; a cleanup failure never replaces it
    try:
        inventory = diagnosis._input_inventory(Path(inputs))
        source.mkdir(parents=True, mode=0o700)
        shutil.copytree(inputs, source / 'inputs')
        if diagnosis._input_inventory(source / 'inputs') != inventory:
            raise BudgetError('diagnosis_input_invalid')
        (source / 'input.json').write_text(json.dumps(dict(
            case_id=c.case_id, exhaustion_id=identity, files=inventory), sort_keys=True))
        (source / 'attempts.json').write_text(json.dumps(
            {'attempts': [{'kind': 'judgment', 'status': 'pending'}]}))
        runner.make_pilots(c, [('pilot', None)], True, diagnosis=True)
        prepared = True  # Even a partial helper preparation must be removed.
        response, raw = _helper(runner, c, 'prepare', identity)
        expected = digest(inventory)
        if response['inputs_sha256'] != expected or raw:
            raise BudgetError('diagnosis_input_invalid')

        def reset():
            response, raw = _helper(runner, c, 'reset', identity)
            if response['inputs_sha256'] is not None or raw:
                raise BudgetError('diagnosis_result_invalid')

        # These prefixes come from the trusted caller's run context.
        mapping = {str(inputs): str(exposed / 'inputs'), str(output): str(exposed / 'output')}
        for old in sorted(mapping, key=len, reverse=True):
            prompt = prompt.replace(old, mapping[old])
        runner.opencode(c, [model], prompt, exposed / 'output', 'diagnosis-' + identity,
                        user='pilot', before_attempt=reset)
        response, raw = _helper(runner, c, 'collect', identity)
        if response['inputs_sha256'] != expected:
            raise BudgetError('diagnosis_input_invalid')
        return raw
    except BaseException as error:
        first = error
        raise
    finally:
        failed = False
        try:
            runner.dispose_diagnosis_pilot(c)
        except BaseException:
            failed = True
        if prepared:
            try:
                response, raw = _helper(runner, c, 'remove', identity)
                if response['inputs_sha256'] is not None or raw:
                    failed = True
            except BaseException:
                failed = True
        try:
            if source.exists(): shutil.rmtree(source)
        except BaseException:
            failed = True
        if failed:
            if first is None:
                raise BudgetError('diagnosis_cleanup_failed') from None
            # Keep the first error as the cause; the step names both (steps/diagnosis.py).
            try: first.diagnosis_cleanup_failed = True
            except AttributeError: pass
