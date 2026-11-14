"""One accounted diagnosis call through the root-owned disposable task boundary."""
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import uuid

from budget import BudgetError
from carry_over import digest
import diagnosis
import diagnosis_task as task

HELPER_LINE = re.compile(r'diagnosis task operation failed: \w+')


def _helper(runner, c, operation, identity):
    # The private result must never pass through runner.sh's stdout logging.
    command = ['sudo', '--', 'python3', '-I', '-B',
               str(Path(runner.__file__).parent / 'diagnosis_task.py'),
               operation, c.case_id, identity]
    # What the helper said becomes the stop's cause, so the sealed diagnostic's traceback shows it.
    # Only diagnosis_task.py's fixed failure line passes, never raw bytes; the return code says the rest.
    detail = ''
    try:
        process = subprocess.run(command, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=120)
        said = [line for line in (process.stderr or b'').decode('utf-8', 'replace').splitlines()
                if HELPER_LINE.fullmatch(line)][-3:]
        detail = f'{operation}: returncode={process.returncode}; stderr={" | ".join(said)}'
        if process.returncode or len(process.stdout) > task.MAX_RESPONSE:
            raise ValueError()
        value = json.loads(process.stdout)
        if (not isinstance(value, dict) or set(value) != {
                'schema_version', 'status', 'inputs_sha256', 'raw_sha256', 'raw_base64'} or
                type(value['schema_version']) is not int or value['schema_version'] != 1 or
                not isinstance(value['status'], str) or
                (value['inputs_sha256'] is not None and not diagnosis._sha(value['inputs_sha256'])) or
                not diagnosis._sha(value['raw_sha256']) or
                not isinstance(value['raw_base64'], str)):
            raise ValueError()
        raw = base64.b64decode(value['raw_base64'], validate=True)
        if len(raw) > task.MAX_RESULT or hashlib.sha256(raw).hexdigest() != value['raw_sha256']:
            raise ValueError()
    except Exception as error:
        failed = RuntimeError(f'{detail or operation}; {type(error).__name__}')
    else:
        # A well-formed answer names why there is no result: one reason each, not one for all
        # (f46dac-5 diagnosis attempt 5: a model that wrote nothing read as an invalid result).
        status = value['status']
        if status == 'ok': return value, raw
        failed = RuntimeError(f'{operation}: status={status}')
        if status == 'missing': raise BudgetError('diagnosis_result_missing') from failed
        if status == 'oversized': raise BudgetError('diagnosis_result_oversized') from failed
        if status == 'unsafe': raise BudgetError('diagnosis_result_unsafe') from failed
        if status == 'input_invalid': raise BudgetError('diagnosis_input_invalid') from failed
    raise BudgetError('diagnosis_result_invalid') from failed


def _remove_tree(path):
    """Remove the runner's own copy of the inputs, even where a copied directory is read-only
    (copytree keeps each directory's mode, and a 0o5xx directory refuses to lose its entries)."""
    path.chmod(0o700)
    for root, directories, _ in os.walk(path):   # top-down: each is opened before it is walked
        for name in directories:
            child = Path(root, name)
            if not child.is_symlink(): child.chmod(0o700)
    shutil.rmtree(path)


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
        # The first cleanup stage that failed, and its error's class, name the stop
        # (durable/classify.py CLEANUP_STAGES): 1bb2ad-2 and f46dac-2r2 stopped with only
        # "diagnosis_cleanup_failed" after diagnoses that had succeeded.
        failed = None
        def fail(stage, error):
            nonlocal failed
            name = getattr(error, 'cleanup_stage', None) or stage
            kind = getattr(error, 'cleanup_error', None) or type(error).__name__
            card = getattr(c, 'card', None)
            if isinstance(card, dict):
                card.setdefault('cleanup_errors', []).append({'stage': 'diagnosis_' + name, 'error': kind})
            if failed is None: failed = name + ':' + kind
        try:
            runner.dispose_diagnosis_pilot(c)
        except BaseException as error:
            fail('pilot_stop', error)
        if prepared:
            try:
                response, raw = _helper(runner, c, 'remove', identity)
                if response['inputs_sha256'] is not None or raw:
                    raise ValueError('task not removed')
            except BaseException as error:
                fail('task_remove', error)
        try:
            if source.exists(): _remove_tree(source)
        except BaseException as error:
            fail('source_remove', error)
        if failed is not None:
            if first is None:
                raise BudgetError('diagnosis_cleanup_failed:' + failed) from None
            # Keep the first error as the cause; the step names both (steps/diagnosis.py).
            try: first.diagnosis_cleanup_failed = True
            except AttributeError: pass
