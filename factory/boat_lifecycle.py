"""Shared durable Boat identity and asynchronous deletion proof, used by both owners."""
import datetime
import fcntl
import json
import math
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
import time


def ids(state, mode='print'):
    state = pathlib.Path(state)
    ids = set((state / "ids").read_text().split())
    known = []
    for path in sorted(state.glob("new.*")):
        if not re.fullmatch(r"new\.[0-9]+", path.name): continue
        found = False
        for line in path.read_text().splitlines():
            try: event = json.loads(line)
            except ValueError: continue
            if not isinstance(event, dict): raise ValueError('invalid event')
            worker = event.get("id")
            if (event.get("event") == "created" and isinstance(worker, str) and
                    re.fullmatch(r"[A-Za-z0-9_-]+", worker)):
                ids.add(worker); found = True
        if found: known.append(path)
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', worker) for worker in ids): raise ValueError('invalid worker')
    text = "".join(worker + "\n" for worker in sorted(ids))
    if mode == 'print':
        return sorted(ids)
    else:
        directory = os.open(state, os.O_RDONLY)
        try:
            # Identity must survive before its uncertainty marker can disappear.
            for path in known:
                with path.open('rb') as response: os.fsync(response.fileno())
            with tempfile.NamedTemporaryFile(mode='w', dir=state, delete=False) as stream:
                temporary = pathlib.Path(stream.name)
                try:
                    stream.write(text); stream.flush(); os.fsync(stream.fileno())
                    temporary.replace(state / 'ids')
                finally: temporary.unlink(missing_ok=True)
            os.fsync(directory)
            if mode == 'resolve':
                for path in known:
                    marker = path.with_name(path.name + '.pending')
                    try: regular = stat.S_ISREG(marker.lstat().st_mode)
                    except FileNotFoundError: continue
                    if regular: marker.unlink()
                os.fsync(directory)
        finally: os.close(directory)
    return sorted(ids)


def delete_receipt(root, spend_file, worker, ids_path, timeout=60):
    root, spend, ids_path = pathlib.Path(root), pathlib.Path(spend_file), pathlib.Path(ids_path)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', worker): raise ValueError('invalid worker')
    fd = os.open(ids_path.parent / (worker + '.deletion.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode): raise ValueError('invalid lock')
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _delete(root, spend, worker, ids_path, timeout)


def _delete(root, spend, worker, ids_path, timeout):
    if worker not in ids_path.read_text().split():
        raise ValueError('worker not owned by this launch')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('invalid deadline')
    deadline = time.monotonic() + timeout
    evidence = spend.with_suffix('.deletions') / worker
    evidence.mkdir(parents=True, exist_ok=True)
    def save(name, value):
        with tempfile.NamedTemporaryFile(mode='w', dir=evidence, delete=False) as stream:
            temporary = pathlib.Path(stream.name)
            try:
                json.dump(value, stream, indent=2)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
                temporary.replace(evidence / name)
                directory = os.open(evidence, os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
            finally:
                temporary.unlink(missing_ok=True)
    def query(*args):
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise TimeoutError()
        # boat-call owns process-group cancellation; allow it to finish that cleanup
        # (60 s ps probe plus two 2 s waits). boat-call may first check --version;
        # both runs share its deadline, leaving a small interpreter-startup margin.
        response = subprocess.run([str(root / 'bin/boat-call'), *args], capture_output=True,
                                  text=True, timeout=remaining + 70,
                                  env={**os.environ, 'BOAT_COMMAND_TIMEOUT_SECONDS': str(remaining)})
        if response.returncode: raise ValueError('command failed')
        return json.loads(response.stdout)['operation']
    def identity(operation, operation_id):
        if (not isinstance(operation, dict) or operation.get('id') != operation_id or
                operation.get('targetId') != worker or operation.get('kind') != 'sandbox'):
            raise ValueError('operation identity mismatch')
        return {k: operation.get(k) for k in
                ('id', 'targetId', 'kind', 'status', 'stage', 'completedAt')}
    completed = evidence / 'deletion-completion.json'
    request = evidence / 'deletion-request.json'
    if request.exists():
        operation = json.loads(request.read_text())
    else:
        attempted = ids_path.parent / (worker + '.deletion-attempted')
        if attempted.exists(): raise ValueError('uncertain deletion request; reconcile manually')
        with attempted.open('x') as marker:
            marker.flush(); os.fsync(marker.fileno())
        directory = os.open(attempted.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
        operation = query('delete', worker, '--yes', '--json')
    operation_id = operation.get('id')
    if not isinstance(operation_id, str) or not operation_id: raise ValueError('missing operation id')
    operation = identity(operation, operation_id)
    save('deletion-request.json', operation)
    if completed.exists():
        done = identity(json.loads(completed.read_text()), operation_id)
        if done['status'] != 'completed' or done['stage'] != 'completed' or not isinstance(done['completedAt'], str) or datetime.datetime.fromisoformat(done['completedAt'].replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('invalid completion')
        return done
    while True:
        operation = identity(query('deletion', 'status', operation_id, '--json'), operation_id)
        save('deletion-completion-query.json', operation)
        if time.monotonic() >= deadline: raise TimeoutError()
        if operation['status'] == 'completed':
            if operation['stage'] != 'completed': raise ValueError('completion stage mismatch')
            value = operation['completedAt']
            if not isinstance(value, str) or not value: raise ValueError('missing completion timestamp')
            if datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
                raise ValueError('completion timestamp lacks timezone')
            save('deletion-completion.json', operation)
            return operation
        if (operation['status'] not in ('pending', 'processing') or
                operation['stage'] in ('failed', 'cancelled', 'canceled', 'completed') or
                operation['completedAt'] is not None):
            raise ValueError('failed or inconsistent operation')
        time.sleep(min(2, max(0, deadline - time.monotonic())))

if __name__ == '__main__':
    try:
        if sys.argv[1] == 'ids':
            found = ids(pathlib.Path(sys.argv[2]), sys.argv[3])
            if sys.argv[3] == 'print': print(''.join(x + '\n' for x in found), end='')
        elif sys.argv[1] == 'delete':
            delete_receipt(*sys.argv[2:6], timeout=float(os.environ.get('BOAT_DELETION_TIMEOUT_SECONDS', '60')))
        else: raise ValueError()
    except Exception:
        sys.exit('lifecycle evidence unavailable; ownership retained; manual reconciliation required')
