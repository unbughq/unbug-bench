"""Reuse completed independent strategy checkpoints, never a live window's state."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import claims


def tree(path):
    path = Path(path)
    if path.is_symlink() or not path.is_dir(): raise ValueError('invalid evidence tree')
    result = {}
    for child in sorted(path.rglob('*')):
        if child.is_symlink(): raise ValueError('symlink in evidence tree')
        if child.is_file(): result[child.relative_to(path).as_posix()] = hashlib.sha256(child.read_bytes()).hexdigest()
    return result


def checkpoint_directory(root, checkpoint):
    root, checkpoint = Path(root), Path(checkpoint)
    relative = checkpoint.relative_to(root)
    if not re.fullmatch(r'(?:factory-slots/[0-9]+/)?runs/[^/.][^/]*/checkpoint\.json', relative.as_posix()):
        raise ValueError('invalid checkpoint provenance')
    for part in (root, *[root.joinpath(*relative.parts[:i]) for i in range(1, len(relative.parts) + 1)]):
        if part.is_symlink(): raise ValueError('symlink checkpoint provenance')
    return checkpoint.parent


def complete(summary, runs):
    return (isinstance(summary, dict) and summary.get('runs') == runs
            and summary.get('error_runs') == 0 and summary.get('invalid_runs') == 0
            and isinstance(summary.get('paths'), dict))


def _identity(scenarios, guard, report, runs, seed, label, workers, binding):
    return {'version': 3, **claims.scoring_identity(), 'binding': binding(), 'scenarios': [tree(p) for p in scenarios],
            'guard': tree(guard), 'guard_name': Path(guard).name, 'report': report,
            'runs': runs, 'seed': seed, 'label': label, 'workers': workers}


def _receipt_path(cache_dir, identity):
    return Path(cache_dir) / (hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest() + '.json')


def execute_cached(execute, scenarios, guard, report, runs, seed, label, *, workers, cache_dir, binding, results_root,
                   restored_results_root=None):
    """binding() comes from the trusted factory and covers case plus execution implementation."""
    initial = _identity(scenarios, guard, report, runs, seed, label, workers, binding)
    path = _receipt_path(cache_dir, initial)
    try:
        if path.is_symlink(): raise ValueError('symlink checkpoint receipt')
        receipt = json.loads(path.read_text())
        if receipt.get('identity') != initial: raise ValueError('changed checkpoint inputs')
        relative = Path(receipt['checkpoint'])
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('invalid checkpoint provenance')
        if 'checkpoint.json' not in receipt['files']: raise ValueError('missing checkpoint evidence')
        for root in (results_root, restored_results_root):
            if root is None: continue
            checkpoint = Path(root) / relative
            directory = checkpoint_directory(root, checkpoint)
            try:
                if tree(directory) == receipt['files']: break
            except (OSError, ValueError):
                continue
        else:
            raise ValueError('changed checkpoint evidence')
        summary = json.loads(Path(checkpoint).read_text())
        if not complete(summary, runs): raise ValueError('incomplete checkpoint')
        summary['_evidence_path'] = str(checkpoint)
        return summary
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    summary = execute(scenarios, guard, report, runs, seed, label)
    record_cached(scenarios, guard, report, runs, seed, label, summary, workers=workers, cache_dir=cache_dir,
                  binding=binding, results_root=results_root, restored_results_root=restored_results_root,
                  initial=initial)
    return summary


def record_cached(scenarios, guard, report, runs, seed, label, summary, *, workers, cache_dir, binding, results_root,
                  restored_results_root=None, initial=None):
    """Publish this step's receipt for a completed execution: one it just ran (`initial` is its identity
    before running) or one it borrowed from another strategy's identical request in this runner."""
    if not complete(summary, runs): return
    try:
        current = _identity(scenarios, guard, report, runs, seed, label, workers, binding)
        if initial is not None and current != initial: return  # inputs changed while it ran
        checkpoint = Path(summary['_evidence_path'])
        for root in (results_root, restored_results_root):
            if root is None: continue
            try: directory = checkpoint_directory(root, checkpoint); break
            except ValueError: continue
        else:
            return
        stored = json.loads(checkpoint.read_text())
        # Persist only the actual execution document, not a caller's invented/edited summary.
        if stored != {k: v for k, v in summary.items() if k != '_evidence_path'}: return
        files = tree(directory)
        if 'checkpoint.json' not in files: return
        receipt = {'identity': current, 'checkpoint': checkpoint.relative_to(root).as_posix(), 'files': files}
        path = _receipt_path(cache_dir, current)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.checkpoint-', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(receipt, stream, sort_keys=True)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError, TypeError):
        pass  # cache publication failure cannot turn completed validation into a failure
