"""Worker-local completion receipts; only encrypted snapshots cross the worker boundary."""
import base64
import hashlib
import json
from pathlib import Path

from registry import atomic_json


def checkpoint(c):
    if getattr(c.engine, 'isolated_model_active', 0): return False
    return getattr(c, 'engine_checkpoint', lambda: True)()


def _directory(c):
    # Attempts of the same sequence share receipts. Later scientific steps do not.
    scope = c.engine.key.rsplit('/', 1)[0]
    return c.work / 'engine-checkpoints' / hashlib.sha256(scope.encode()).hexdigest()


def _files(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()
            and not any(parent.is_symlink() for parent in p.parents if parent.is_relative_to(root))
            and p.relative_to(root).parts[0] not in
            ('engine-checkpoints', 'continuation-budget.json', 'usage-receipts', 'scorecard.json', 'logs', 'transcripts')}


def model_call(c, models, cwd, name, invoke):
    """Replay completed local model effects in this exact logical step, in call order.

    Isolated pilot homes are deliberately handled by AttemptSeries.save_pending,
    after the guard is copied home and the owner channel has joined.
    """
    root = Path(cwd)
    if not root.is_relative_to(c.work):
        c.engine.isolated_model_active = getattr(c.engine, 'isolated_model_active', 0) + 1
        try:
            return invoke()
        finally:
            c.engine.isolated_model_active -= 1
    counts = c.__dict__.setdefault('engine_model_ordinals', {})
    ordinal = counts.get(name, 0)
    counts[name] = ordinal + 1
    identity = json.dumps([name, models, str(root.relative_to(c.work)), ordinal])
    path = _directory(c) / (hashlib.sha256(identity.encode()).hexdigest() + '.json')
    if path.exists():
        saved = json.loads(path.read_text())
        # Path validation is independent of archive authentication.
        for relative in [*saved['files'], *saved['deleted']]:
            target = root / relative
            if not target.resolve().is_relative_to(root.resolve()):
                raise ValueError('completion path escapes workspace')
        for relative in saved['deleted']:
            (root / relative).unlink(missing_ok=True)
        for relative, encoded in saved['files'].items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(encoded['data'], validate=True))
            target.chmod(encoded['mode'])
        return saved['result']
    before = _files(root)
    try:
        result = invoke()
    except BaseException:
        checkpoint(c)
        raise
    after = _files(root)
    # Only a successful, fully settled invocation authorizes skipping model work.
    row = next((r for r in reversed(c.card.get('route_receipts', [])) if r.get('invocation') == name), {})
    receipt = c.work / row.get('call_id', 'missing-receipt')
    known = json.loads(receipt.read_text()).get('final_usage_known') if receipt.is_file() else False
    if result == 0 and row.get('outcome') == 'done' and known:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(path, {'result': result,
                          'files': {p: {'data': base64.b64encode((root / p).read_bytes()).decode(),
                                        'mode': (root / p).stat().st_mode & 0o777}
                                    for p in after if before.get(p) != after[p]},
                          'deleted': sorted(before.keys() - after.keys())})
    checkpoint(c)
    return result


def gate_call(c, gate, invoke, binding):
    # G3 establishes host-local Docker state, which an archive cannot restore.
    if gate == 'G3': return invoke()
    path = _directory(c) / ('gate-' + gate + '.json')
    if path.exists():
        saved = json.loads(path.read_text())
        if saved['binding'] == binding:
            return saved['ok'], saved['info']
    ok, info = invoke()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, {'binding': binding, 'ok': ok, 'info': info})
    return ok, info
