"""Worker-local completion receipts; only encrypted snapshots cross the worker boundary."""
import base64
import contextlib
import hashlib
import json
from pathlib import Path
import threading

_INIT_LOCK = threading.Lock()
# Counters only; never held across a model call or a snapshot, unlike checkpoint_lock.
_COUNT_LOCK = threading.Lock()


def _lock(c):
    with _INIT_LOCK:
        if not hasattr(c.engine, "checkpoint_lock"):
            c.engine.checkpoint_lock = threading.RLock()
    return c.engine.checkpoint_lock

from registry import atomic_json


def _count(c, name, delta):
    with _COUNT_LOCK:
        value = getattr(c.engine, name, 0) + delta
        setattr(c.engine, name, value)
        return value


def _unsettled(c):
    with _COUNT_LOCK:
        return getattr(c.engine, 'isolated_model_active', 0) > 0 or getattr(c.engine, 'concurrent_sections', 0) > 0


def checkpoint(c):
    """Publish a snapshot only at a quiescent point; otherwise defer it to the next one.

    Inside a concurrent section another thread may be writing retained work, so a
    snapshot taken there could be torn. The request is remembered and published when
    the last section joins. The check runs before taking checkpoint_lock, which a
    same-case model call holds for its whole run in the other thread.
    """
    if _unsettled(c):
        c.engine.checkpoint_deferred = True
        return False
    with _lock(c):
        if _unsettled(c):
            c.engine.checkpoint_deferred = True
            return False
        c.engine.checkpoint_deferred = False
        return getattr(c, 'engine_checkpoint', lambda: True)()


@contextlib.contextmanager
def concurrent_section(c):
    """Parallel work on one case (G10's two calibrators, gates beside bench gates).

    Snapshots requested inside wait until every section has joined, then one is published.
    Outside the engine this does nothing.
    """
    if getattr(c, 'engine', None) is None:
        yield
        return
    _count(c, 'concurrent_sections', 1)
    try:
        yield
    finally:
        if _count(c, 'concurrent_sections', -1) == 0 and getattr(c.engine, 'checkpoint_deferred', False):
            checkpoint(c)


def directory(c):
    # Attempts of the same sequence share receipts. Later scientific steps do not.
    scope = c.engine.key.rsplit('/', 1)[0]
    identity = json.dumps([scope, getattr(c.engine, 'source_binding', None)], sort_keys=True)
    return c.work / 'engine-checkpoints' / hashlib.sha256(identity.encode()).hexdigest()


def workpath(c, label, suffix=''):
    """Stable logical output names survive a replacement worker's filesystem root."""
    counts = c.__dict__.setdefault('engine_path_ordinals', {})
    ordinal = counts.get(label, 0)
    counts[label] = ordinal + 1
    return c.work / f'{label}-{directory(c).name[:16]}-{ordinal}{suffix}'


def _files(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()
            and not any(parent.is_symlink() for parent in p.parents if parent.is_relative_to(root))
            and p.relative_to(root).parts[0] not in
            ('engine-checkpoints', 'continuation-budget.json', 'usage-receipts', 'scorecard.json', 'logs', 'transcripts',
             'ordinary-retries', 'stress-publication.json', 'engine-feedback.json', 'engine-ruling.json')}


def _matches(path, ws, current):
    """Each file the call saw or wrote is at its start or end digest (absent is a state).

    A file may instead sit at a later state only if the later receipts in this directory
    carry the replayed workspace forward to exactly the current one: each must itself match
    every path it covers. Replay then ends where it began, and a diverged rerun or a chain
    that cannot fully replay is not reusable, so nothing is moved backward and left there.
    """
    if not isinstance(ws, dict) or not isinstance(ws.get('before'), dict) or not isinstance(ws.get('after'), dict):
        return False
    before, after = ws['before'], ws['after']
    paths = before.keys() | after.keys()
    if all(current.get(p) in (before.get(p), after.get(p)) for p in paths):
        return True
    # ponytail: scans the directory only when a file moved on; chains are a handful of calls.
    pending = []
    for other in path.parent.glob('*.json'):
        if other == path: continue
        try: later = json.loads(other.read_text()).get('workspace')
        except (OSError, ValueError, AttributeError): continue
        if isinstance(later, dict) and isinstance(later.get('before'), dict) and isinstance(later.get('after'), dict):
            pending.append(later)
    explained = set()
    def apply(w, state):
        for q in w['before'].keys() | w['after'].keys():
            if w['before'].get(q) == w['after'].get(q): continue
            explained.add(q)
            if w['after'].get(q) is None: state.pop(q, None)
            else: state[q] = w['after'][q]
    virtual = dict(current)
    apply(ws, virtual)
    explained.clear()  # only later receipts may carry a file on to its current state
    reached = set()  # files the chain carried to exactly their current digest
    moved = True
    while moved:
        moved = False
        for later in pending[:]:
            qs = later['before'].keys() | later['after'].keys()
            if (all(virtual.get(q) in (later['before'].get(q), later['after'].get(q)) for q in qs)
                    and any(virtual.get(q) == later['before'].get(q) != later['after'].get(q) for q in qs)):
                apply(later, virtual)
                reached |= {q for q in explained if virtual.get(q) == current.get(q)}
                pending.remove(later)
                moved = True
    return all(current.get(p) in (before.get(p), after.get(p)) or p in reached
               for p in paths)


def model_call(c, models, cwd, name, invoke, *, text=None):
    """Replay completed local model effects in this exact logical step, in call order.

    Isolated pilot homes are deliberately handled by AttemptSeries.save_pending,
    after the guard is copied home and the owner channel has joined.
    """
    root = Path(cwd)
    # engine_parallel_call: a stress round's category attackers run together in c.work
    # (stress_progress.run). A workspace receipt would mix their files and the same-case lock
    # would serialise them, so they are counted like isolated calls: snapshots wait for the
    # join, and the retained answer replays a completed call.
    if not root.is_relative_to(c.work) or getattr(c, 'engine_parallel_call', False):
        _count(c, 'isolated_model_active', 1)
        try:
            return invoke()
        finally:
            _count(c, 'isolated_model_active', -1)
    # ponytail: serialize same-case calls that mutate retained work. Cases still
    # run concurrently; isolated owner channels must remain outside this lock.
    with _lock(c):
        return _model_effect(c, models, root, name, invoke, text)


def _model_effect(c, models, root, name, invoke, text):
    counts = c.__dict__.setdefault('engine_model_ordinals', {})
    ordinal = counts.get(name, 0)
    counts[name] = ordinal + 1
    request = text.replace(str(c.work), "<work>") if isinstance(text, str) else text
    if isinstance(request, str) and getattr(c, "bench_root", None) is not None:
        request = request.replace(str(c.bench_root), "<bench>")
    identity = json.dumps([name, models, c.card.get("roles"), str(root.relative_to(c.work)), ordinal, request], sort_keys=True)
    path = directory(c) / (hashlib.sha256(identity.encode()).hexdigest() + '.json')
    if path.exists():
        saved = json.loads(path.read_text())
        current = _files(root)
        # Receipts without a recorded pre-image (older shape) cannot prove their start state: rerun.
        # Untouched new files (later gate or call outputs in a restored snapshot) are tolerated to keep legitimate replay.
        if _matches(path, saved.get('workspace'), current):
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
                          'workspace': {'before': before, 'after': after},
                          'files': {p: {'data': base64.b64encode((root / p).read_bytes()).decode(),
                                        'mode': (root / p).stat().st_mode & 0o777}
                                    for p in after if before.get(p) != after[p]},
                          'deleted': sorted(before.keys() - after.keys())})
    checkpoint(c)
    return result


def gate_call(c, gate, invoke, binding):
    # G3 establishes host-local Docker state, which an archive cannot restore.
    if gate in ('G2', 'G3'): return invoke()
    binding = json.loads(json.dumps(binding))  # Scientific inventories contain tuples; receipts contain JSON lists.
    path = directory(c) / ('gate-' + gate + '.json')
    if path.exists():
        saved = json.loads(path.read_text())
        if saved['binding'] == binding:
            return saved['ok'], saved['info']
    ok, info = invoke()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, {'binding': binding, 'ok': ok, 'info': info})
    return ok, info
