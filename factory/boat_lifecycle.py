"""Shared durable Boat identity and asynchronous deletion proof, used by both owners."""
import datetime
from decimal import Decimal, Inexact, localcontext
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


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj: raise ValueError('duplicate key')
        obj[key] = value
    return obj


def reject_constant(value):
    raise ValueError('invalid number')


def loads(data):
    return json.loads(data, parse_float=Decimal, parse_constant=reject_constant,
                      object_pairs_hook=unique_object)


def regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ValueError('not regular')
        return stream.read()


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('invalid number')
    value = Decimal(value)
    if not value.is_finite() or value < 0: raise ValueError('invalid number')
    digits = value.as_tuple()
    if len(digits.digits) > 32 or not -18 <= digits.exponent <= 18:
        raise ValueError('invalid number')
    return value


def total(values):
    with localcontext() as context:
        context.prec = 80
        context.traps[Inexact] = True
        return sum(values, Decimal(0))


def timestamp(value):
    if not isinstance(value, str): raise ValueError('invalid timestamp')
    if datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('timestamp lacks timezone')


def worker_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('invalid worker')
    return value


def completion(operation, worker, operation_id):
    if (not isinstance(operation, dict) or operation.get('id') != operation_id or
            not isinstance(operation_id, str) or not operation_id or
            operation.get('targetId') != worker or operation.get('kind') != 'sandbox' or
            operation.get('status') != 'completed' or operation.get('stage') != 'completed'):
        raise ValueError('invalid completion')
    timestamp(operation.get('completedAt'))
    return operation


def settlement_amount(row):
    """Validate durable authority, shared by admission and the inventory reader."""
    proof = row['settlement']
    if (not isinstance(proof, dict) or set(proof) !=
            {'schema', 'state_path', 'settled_at', 'basis', 'workers'} or
            type(proof['schema']) is not int or proof['schema'] != 1 or
            proof['state_path'] != row['state_path'] or
            not isinstance(proof['state_path'], str) or not pathlib.Path(proof['state_path']).is_absolute()):
        raise ValueError('invalid settlement')
    timestamp(proof['settled_at'])
    for key in ('vms', 'ttl_seconds'):
        if type(row[key]) is not int or row[key] < 1: raise ValueError('invalid envelope')
    number(row['max_spend_usd'])
    workers = proof['workers']
    if not isinstance(workers, list): raise ValueError('invalid workers')
    if proof['basis'] not in ('no_creation', 'deleted_lifetime_usage'):
        raise ValueError('invalid basis')
    if (proof['basis'] == 'no_creation') != (not workers): raise ValueError('invalid basis')
    names, amounts = [], []
    for item in workers:
        if not isinstance(item, dict) or set(item) != {'id', 'deletion_operation_id', 'completed_at', 'seconds', 'dollars'}:
            raise ValueError('invalid worker settlement')
        names.append(worker_id(item['id']))
        if not isinstance(item['deletion_operation_id'], str) or not item['deletion_operation_id']:
            raise ValueError('missing deletion identity')
        timestamp(item['completed_at'])
        if type(item['seconds']) is not int or item['seconds'] < 0: raise ValueError('invalid seconds')
        if not isinstance(item['dollars'], str): raise ValueError('invalid dollars')
        amounts.append(number(item['dollars']))
    if names != sorted(set(names)) or len(names) > row['vms']: raise ValueError('invalid workers')
    if not isinstance(row['actual_spend_usd'], str): raise ValueError('invalid total')
    amount = total(amounts)
    if number(row['actual_spend_usd']) != amount: raise ValueError('invalid total')
    return amount


def settlement_workers(state, row):
    """Strict read-only creation proof; tolerant recovery ids() is not authority."""
    state = pathlib.Path(state)
    if state.is_symlink() or not state.is_dir(): raise ValueError('invalid state')
    names = regular(state / 'ids').decode().split()
    if len(names) != len(set(names)): raise ValueError('duplicate worker')
    for name in names: worker_id(name)
    created, serials = [], []
    for path in state.iterdir():
        if not path.name.startswith('new.'): continue
        if not re.fullmatch(r'new\.[1-9][0-9]*', path.name): raise ValueError('creation unknown')
        events = [loads(line) for line in regular(path).decode().splitlines() if line.strip()]
        if not all(isinstance(e, dict) for e in events): raise ValueError('invalid creation')
        found = [worker_id(e.get('id')) for e in events if e.get('event') == 'created']
        if len(found) != 1: raise ValueError('creation unknown')
        created.extend(found); serials.append(int(path.name.split('.')[1]))
    if sorted(created) != sorted(names) or len(names) > row['vms']:
        raise ValueError('creation identity mismatch')
    if row['status'] == 'reserved' and (not names or sorted(serials) != list(range(1, row['vms'] + 1))):
        raise ValueError('creation still possible')
    if not names and row['status'] != 'finished': raise ValueError('creation still possible')
    return sorted(names)


def settlement_proof(spend, state, row, query):
    workers = settlement_workers(state, row)
    receipts = {}
    for worker in workers:
        directory = pathlib.Path(spend).with_suffix('.deletions') / worker
        if directory.is_symlink() or directory.parent.is_symlink(): raise ValueError('invalid evidence')
        request = loads(regular(directory / 'deletion-request.json'))
        done = loads(regular(directory / 'deletion-completion.json'))
        if not isinstance(request, dict) or request.get('targetId') != worker or request.get('kind') != 'sandbox':
            raise ValueError('wrong deletion request')
        receipts[worker] = completion(done, worker, request.get('id'))
    inventory = query('list', '--json')
    listed = [worker_id(item['id']) for item in inventory['sandboxes']]
    if inventory['pageInfo']['hasMore'] is not False or len(listed) != len(set(listed)) or set(workers).intersection(listed):
        raise ValueError('inventory incomplete')
    result = []
    for worker in workers:
        usage = query('usage', worker, '--json')
        if (not isinstance(usage, dict) or usage.get('running') is not False or
                type(usage.get('seconds')) is not int or usage['seconds'] < 0 or
                type(usage.get('dollars')) not in (int, Decimal)):
            raise ValueError('usage unavailable')
        if any(usage[key] != worker for key in ('id', 'sandboxId') if key in usage):
            raise ValueError('usage identity mismatch')
        dollars = number(usage['dollars'])
        done = receipts[worker]
        result.append(dict(id=worker, deletion_operation_id=done['id'], completed_at=done['completedAt'],
                           seconds=usage['seconds'], dollars=format(dollars, 'f')))
    return dict(schema=1, state_path=str(state), settled_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                basis='deleted_lifetime_usage' if workers else 'no_creation', workers=result)


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
        return completion(done, worker, operation_id)
    while True:
        operation = identity(query('deletion', 'status', operation_id, '--json'), operation_id)
        save('deletion-completion-query.json', operation)
        if time.monotonic() >= deadline: raise TimeoutError()
        if operation['status'] == 'completed':
            completion(operation, worker, operation_id)
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
        if len(sys.argv) > 1 and sys.argv[1] == 'ids':
            sys.exit('creation evidence could not be persisted; ownership retained')
        sys.exit('deletion receipt verification FAILED; manual reconciliation required')
