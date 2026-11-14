"""Disposable diagnosis task tree. CLI arguments are identities, never paths.

The runner is trusted and already has sudo. This boundary protects its files
from the isolated pilot, and serializes helpers that outlive a killed runner.
"""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

# -I deliberately omits the script directory; only this shipped module root is added.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from carry_over import digest
from diagnosis import _input_bytes, _input_inventory

ROOT = Path('/var/lib/unbug-diagnosis')
ROOT_UID = 0
MAX_RESULT = 65536
MAX_RESPONSE = 96 * 1024


def identities(case, identity):
    if not isinstance(case, str) or not re.fullmatch(r'case-[A-Za-z0-9-]{1,128}', case):
        raise ValueError('invalid task identity')
    parsed = uuid.UUID(identity)
    if str(parsed) != identity or parsed.version != 4: raise ValueError('invalid task identity')


def _directory(path, mode=0o755):
    if path.is_symlink(): raise ValueError('linked task parent')
    path.mkdir(mode=mode, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022:
        raise ValueError('untrusted task parent')


@contextlib.contextmanager
def locked(root, case):
    # The fixed production parent /var/lib is root-owned; test roots are private.
    _directory(root)
    parent = root / case; _directory(parent)
    fd = os.open(parent / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('untrusted task lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield parent
    finally:
        os.close(fd)


def _remove(task):
    if task.is_symlink(): task.unlink()
    elif task.exists(): shutil.rmtree(task)


def _quiet(uid):
    end = time.monotonic() + 5
    while True:
        result = subprocess.run(['pgrep', '-u', str(uid)], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=5)
        if result.returncode == 1: return
        if result.returncode != 0 or time.monotonic() >= end: raise RuntimeError('pilot still active')
        time.sleep(.05)


def _response(status='ok', data=b'', inputs=None):
    return dict(schema_version=1, status=status, inputs_sha256=inputs,
                raw_sha256=hashlib.sha256(data).hexdigest(), raw_base64=base64.b64encode(data).decode())


def _mode(source, *, pending=False):
    journal = json.loads(_input_bytes(source / 'attempts.json', source))
    row = journal['attempts'][-1]
    if row['kind'] not in ('judgment', 'repair') or (pending and row['status'] != 'pending'):
        raise ValueError('invalid task mode')
    return row['kind']


def _result(task):
    try:
        path = task / 'output/result.json'
        if task.is_symlink() or path.parent.is_symlink(): return 'unsafe', b''
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): return 'unsafe', b''
            data = stream.read(MAX_RESULT + 1)
        return ('oversized' if len(data) > MAX_RESULT else 'ok'), data[:MAX_RESULT]
    except FileNotFoundError:
        return 'missing', b''
    except OSError:
        return 'unsafe', b''


def operate(operation, case, identity, *, runner_home, root=ROOT):
    """Paths are injected only by offline tests; the CLI derives both trusted roots."""
    identities(case, identity)
    if operation not in ('prepare', 'reset', 'collect', 'remove'): raise ValueError('invalid operation')
    source = Path(runner_home) / 'work' / case / 'diagnosis' / identity
    def verify_source():
        for path in (source, *source.parents):
            if path == Path(runner_home).parent: break
            if path.is_symlink(): raise ValueError('linked source parent')
    with locked(Path(root), case) as parent:
        task = parent / identity
        if operation == 'remove':
            _remove(task)
            return _response()
        if operation == 'collect':
            status, raw = _result(task)
            inputs = None
            try:
                verify_source()
                mode = _mode(source)
                if mode == 'judgment':
                    manifest = json.loads(_input_bytes(source / 'input.json', source))
                    inputs = digest(_input_inventory(task / 'inputs'))
                    if inputs != digest(manifest['files']): status = 'input_invalid'
                elif (task / 'inputs').exists() or (task / 'inputs').is_symlink():
                    status = 'input_invalid'
            except (ValueError, OSError, KeyError, TypeError, IndexError):
                status = 'input_invalid'
            return _response(status, raw, inputs)
        pilot = pwd.getpwnam('pilot')
        _quiet(pilot.pw_uid)
        if operation == 'prepare':
            # Build in place: a crash leaves only the canonical UUID, never a sibling.
            _remove(task)
            verify_source()
            mode = _mode(source, pending=True)
            manifest = json.loads(_input_bytes(source / 'input.json', source))
            if manifest['case_id'] != case or manifest['exhaustion_id'] != identity:
                raise ValueError('task binding differs')
            if _input_inventory(source / 'inputs') != manifest['files']:
                raise ValueError('changed immutable inputs')
            task.mkdir(mode=0o700)
            os.chown(task, ROOT_UID, pilot.pw_gid)
            if mode == 'judgment':
                exposed = task / 'inputs'; exposed.mkdir(mode=0o700)
                for name, expected in manifest['files'].items():
                    raw = _input_bytes(source / 'inputs' / name, source / 'inputs')
                    if hashlib.sha256(raw).hexdigest() != expected: raise ValueError('changed immutable input')
                    target = exposed / name; target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                from case_permissions import normalize_case_tree
                normalize_case_tree(exposed / 'case')
                for path in [*exposed.rglob('*'), exposed]:
                    os.chown(path, ROOT_UID, pilot.pw_gid)
                    path.chmod(0o550 if path.is_dir() else 0o440)
                if _input_inventory(exposed) != manifest['files']: raise ValueError('copy differs')
            task.chmod(0o750)
        else:
            if task.is_symlink() or not task.is_dir() or task.stat().st_uid != ROOT_UID:
                raise ValueError('missing prepared task')
        output = task / 'output'
        _remove(output)
        output.mkdir(mode=0o700); os.chown(output, pilot.pw_uid, pilot.pw_gid)
        return _response(inputs=digest(manifest['files']) if operation == 'prepare' and mode == 'judgment' else None)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3 or os.geteuid() != 0: raise ValueError('invalid helper invocation')
    runner = pwd.getpwuid(int(os.environ['SUDO_UID']))
    response = operate(*args, runner_home=Path(runner.pw_dir))
    wire = json.dumps(response, sort_keys=True).encode()
    if len(wire) > MAX_RESPONSE: raise ValueError('helper response too large')
    sys.stdout.buffer.write(wire)


if __name__ == '__main__':
    try: main()
    except Exception as error:
        # Neither source data nor exception strings belong in root-helper logs; the class name is neither.
        raise SystemExit('diagnosis task operation failed: ' + type(error).__name__) from None
