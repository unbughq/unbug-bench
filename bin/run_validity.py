"""Execution evidence has two states; neither state is a scientific verdict."""
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import threading


class InvalidInfra(RuntimeError):
    pass


class InfrastructureExhausted(InvalidInfra):
    pass


def classify(summary=None, records=None):
    if summary is not None:
        if (not isinstance(summary, dict) or type(summary.get('runs')) is not int
                or summary['runs'] < 1 or summary.get('error_runs') or summary.get('invalid_runs')
                or summary.get('errors')):
            return 'invalid-infra'
    if records is not None:
        if not isinstance(records, list) or not records:
            return 'invalid-infra'
        if summary is not None and len(records) != summary['runs']:
            return 'invalid-infra'
        for row in records:
            if (not isinstance(row, dict) or row.get('errors') != []
                    or not isinstance(row.get('checker'), dict) or row['checker'].get('valid') is not True
                    or not isinstance(row.get('judge'), dict) or row['judge'].get('invalid')):
                return 'invalid-infra'
            for field in ('paths', 'checks'):
                if not isinstance(row['judge'].get(field), dict) or any(type(v) is not bool for v in row['judge'][field].values()):
                    return 'invalid-infra'
    return 'valid' if summary is not None or records is not None else 'invalid-infra'


def require_valid(summary=None, records=None):
    if classify(summary, records) != 'valid':
        raise InvalidInfra('execution has no valid verdict')


_lock = threading.RLock()


@lru_cache(maxsize=1)
def runtime_revision():
    root = Path(__file__).resolve().parents[1]
    paths = [*sorted((root / 'factory').glob('*.py')),
             *(root / 'bin' / name for name in ('run_validity.py', 'checkpoint_evidence.py', 'strategy',
                'bench.py', 'bench_judging.py', 'silent_window.py', 'exposure.py'))]
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file(): digest.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def retry(path, identity, invoke, *, attempts=2, interruption=(), on_error=lambda error: None):
    """Persist invalid attempts before retrying; resume cannot reset their allowance.

    The operation owns its evidence. A successful deliberate repeat is allowed;
    only failed/interrupted executions consume this infrastructure allowance.
    """
    path = Path(path)
    key = hashlib.sha256(json.dumps({'execution': identity, 'runtime': runtime_revision()}, sort_keys=True, default=str).encode()).hexdigest()
    def update(change):
        with _lock:
            state = json.loads(path.read_text()) if path.exists() else {}
            row = state.setdefault(key, {'invalid_attempts': 0})
            change(row)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(state, sort_keys=True))
            temporary.replace(path)
            return dict(row)
    def start(row):
        if row.pop('running', False): row['invalid_attempts'] += 1
        if row['invalid_attempts'] >= attempts:
            raise InfrastructureExhausted('unchanged execution exhausted infrastructure retries')
        row['running'] = True
    while True:
        update(start)
        try:
            result = invoke()
        except InfrastructureExhausted:
            update(lambda row: row.update(running=False, invalid_attempts=attempts))
            raise
        except BaseException as error:
            if not isinstance(error, Exception) or isinstance(error, interruption):
                # A handled budget/provider wait or deliberate pause did not
                # produce an invalid verdict and must not spend this allowance.
                update(lambda row: row.update(running=False))
                raise
            def failed(row):
                row.update(running=False, invalid_attempts=row['invalid_attempts'] + 1,
                           error_type=type(error).__name__)
            state = update(failed)
            on_error(error)
            if state['invalid_attempts'] >= attempts:
                raise InfrastructureExhausted(type(error).__name__) from error
        else:
            update(lambda row: row.update(running=False, invalid_attempts=0))
            return result
