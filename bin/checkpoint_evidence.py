"""Checkpoint completion and evidence, shared by subprocess callers.

This module proves that a requested batch completed and describes operational
validity. It does not decide whether a guard or a case passes a gate, and does
not replace the stronger pending-installation proof.
"""
import json
from pathlib import Path
import re
from run_validity import InvalidInfra, require_valid as valid_execution


RECEIPT_PREFIX = 'UNBUG_CHECKPOINT='


def record_paths(directory):
    """Enumerate every numbered trial in numeric order, including trial 100+.

    Writers use a minimum width of two digits. Reject aliases rather than
    silently accepting two files for one trial or omitting malformed records.
    """
    records = []
    for path in Path(directory).glob('*.json'):
        if not re.fullmatch(r'[0-9]+', path.stem):
            continue
        number = int(path.stem)
        if number < 1 or path.name != f'{number:02}.json':
            raise ValueError('invalid checkpoint record filename: ' + path.name)
        records.append((number, path))
    return [path for _, path in sorted(records)]


def publish(directory, summary, requested_runs):
    """Commit the summary before returning its machine-readable completion receipt."""
    path = Path(directory).resolve() / 'checkpoint.json'
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)
    return RECEIPT_PREFIX + json.dumps({'version': 1, 'path': str(path),
                                       'requested_runs': requested_runs})


def verdict_detail(summary, path):
    return (f'runs={summary.get("runs")}; error_runs={summary.get("error_runs")}; '
            f'invalid_runs={summary.get("invalid_runs")}; evidence={path}; '
            f'errors={json.dumps(summary.get("errors", []))[-12000:]}')


def _read(path):
    value = json.loads(path.read_text())
    json.dumps(value, allow_nan=False)
    if not isinstance(value, dict):
        raise ValueError('evidence must be a JSON object')
    return value


def read_completed(process, requested_runs, label, *, require_valid=False):
    """Return (summary, records, path) only for a complete checkpoint batch.

    A valid scored failure is returned normally. Factory gates may inspect complete
    invalid batches; strategy callers set require_valid because those have no
    strategy verdict. Legacy output is read here only, for older checkpoint CLIs.
    """
    stdout, stderr = process.stdout or '', process.stderr or ''
    detail = (f'{label}; returncode={process.returncode}; '
              f'stderr={stderr[-4000:]}; stdout={stdout[-4000:]}')
    summary, path = {}, None
    try:
        if process.returncode:
            raise ValueError('checkpoint process failed')
        if type(requested_runs) is not int or requested_runs <= 0:
            raise ValueError('requested runs must be positive')
        receipts = [line[len(RECEIPT_PREFIX):] for line in stdout.splitlines()
                    if line.startswith(RECEIPT_PREFIX)]
        if receipts:
            if len(receipts) != 1:
                raise ValueError('ambiguous checkpoint receipts')
            receipt = json.loads(receipts[0])
            if (not isinstance(receipt, dict) or type(receipt.get('version')) is not int
                    or receipt['version'] != 1 or type(receipt.get('requested_runs')) is not int
                    or receipt['requested_runs'] != requested_runs
                    or not isinstance(receipt.get('path'), str) or not receipt['path']):
                raise ValueError('invalid checkpoint receipt')
            path = Path(receipt['path']).resolve()
        else:
            paths = re.findall(r'^Checkpoint: (.+)$', stdout, re.M)
            if len(paths) != 1:
                raise ValueError('missing or ambiguous checkpoint receipt')
            path = Path(paths[0]).resolve()
        summary = _read(path)
        # Check validity before structural details so operational failures keep
        # the run counts and diagnostic evidence that explain the failure.
        if require_valid and (not summary.get('runs') or summary.get('error_runs')
                              or summary.get('invalid_runs')):
            raise ValueError('checkpoint has no valid verdict')
        for key in ('runs', 'pass_runs', 'error_runs', 'invalid_runs'):
            if type(summary.get(key)) is not int or not 0 <= summary[key] <= requested_runs:
                raise ValueError('invalid checkpoint count: ' + key)
        if summary['runs'] != requested_runs:
            raise ValueError('incomplete checkpoint batch')
        files = record_paths(path.parent)
        if len(files) != requested_runs:
            raise ValueError('incomplete checkpoint records')
        records = [_read(record) for record in files]
        for number, record in enumerate(records, 1):
            if type(record.get('run')) is not int or record['run'] != number:
                raise ValueError('checkpoint run order mismatch')
            if not isinstance(record.get('errors'), list):
                raise ValueError('missing checkpoint errors')
            checker, judge = record.get('checker'), record.get('judge')
            if not isinstance(checker, dict) or type(checker.get('valid')) is not bool:
                raise ValueError('missing checkpoint validity')
            if not isinstance(judge, dict) or type(judge.get('pass')) is not bool:
                raise ValueError('missing checkpoint verdict')
            for key in ('paths', 'checks'):
                if not isinstance(judge.get(key), dict) or any(type(v) is not bool for v in judge[key].values()):
                    raise ValueError('invalid checkpoint judge ' + key)
        counts = {'pass_runs': sum(r['judge']['pass'] for r in records),
                  'error_runs': sum(bool(r['errors']) for r in records),
                  'invalid_runs': sum(not r['checker']['valid'] for r in records)}
        if any(summary[key] != count for key, count in counts.items()):
            raise ValueError('checkpoint summary disagrees with records')
        for field, count_key in (('paths', 'violated_runs'), ('checks', 'ok_runs')):
            aggregate = {}
            for record in records:
                for name, value in record['judge'][field].items():
                    entry = aggregate.setdefault(name, {'runs': 0, count_key: 0})
                    entry['runs'] += 1
                    entry[count_key] += value
            claimed = summary.get(field)
            if not isinstance(claimed, dict) or claimed.keys() != aggregate.keys():
                raise ValueError('checkpoint summary disagrees with ' + field)
            for name, expected in aggregate.items():
                if not isinstance(claimed[name], dict) or any(
                        type(claimed[name].get(key)) is not int or claimed[name][key] != value
                        for key, value in expected.items()):
                    raise ValueError('checkpoint summary disagrees with ' + field)
        if require_valid:
            valid_execution(summary, records)
        return summary, records, path
    except (ValueError, TypeError, KeyError, OSError, InvalidInfra) as error:
        raise InvalidInfra(f'{error}; {verdict_detail(summary, path)}; {detail}') from error
