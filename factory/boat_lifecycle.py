"""Shared durable Boat identity and asynchronous deletion proof, used by both owners."""
import datetime
from decimal import DecimalException, Decimal, Inexact, localcontext
import fcntl
import hashlib
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
            type(proof['schema']) is not int or proof['schema'] not in (1,2) or
            proof['state_path'] != row['state_path'] or
            not isinstance(proof['state_path'], str) or not pathlib.Path(proof['state_path']).is_absolute()):
        raise ValueError('invalid settlement')
    timestamp(proof['settled_at'])
    for key in ('vms', 'ttl_seconds'):
        if type(row[key]) is not int or row[key] < 1: raise ValueError('invalid envelope')
    number(row['max_spend_usd'])
    workers = proof['workers']
    if not isinstance(workers, list): raise ValueError('invalid workers')
    if ((proof['schema']==2 and (proof['basis'] != 'stopped_usage_then_deleted' or not workers)) or
            (proof['schema']==1 and proof['basis'] not in ('no_creation', 'deleted_lifetime_usage'))):
        raise ValueError('invalid basis')
    if (proof['basis'] == 'no_creation') != (not workers): raise ValueError('invalid basis')
    names, amounts = [], []
    for item in workers:
        extra = {'retirement_id','stop_id','receipt_sha256'} if proof['schema']==2 else set()
        if not isinstance(item, dict) or set(item) != {'id', 'deletion_operation_id', 'completed_at', 'seconds', 'dollars'} | extra:
            raise ValueError('invalid worker settlement')
        if proof['schema']==2:
            if (not isinstance(item['retirement_id'],str) or not re.fullmatch('[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}',item['retirement_id']) or
                    not isinstance(item['stop_id'],str) or not item['stop_id'] or
                    not isinstance(item['receipt_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',item['receipt_sha256'])):
                raise ValueError('invalid retirement settlement')
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
    return dict(schema=1, state_path=str(state), settled_at=utc_now(),
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


def sha256(path):
    return hashlib.sha256(regular(path)).hexdigest()


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def exclusive_bytes(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    fsync_directory(path.parent)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def stamp(value):
    timestamp(value)
    parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() != datetime.timedelta(0): raise ValueError('not UTC')
    return parsed.timestamp()


def stopped(info, status, worker):
    if (not isinstance(info,dict) or set(info) != {'sandbox'} or not isinstance(status,dict) or
            set(status) != {'id','stop'} or set(info['sandbox']) != {'id','state','stop'}):
        raise ValueError('invalid stop envelope')
    sandbox = info['sandbox']; stop = status['stop']
    keys = {'id','status','requestedAt','lastAttemptAt','error','endedAt'}
    for item in (sandbox['stop'],stop):
        if (not isinstance(item,dict) or not keys <= set(item) or set(item)-keys-{'forced'} or
                not isinstance(item['id'],str) or not item['id'] or
                item['status'] not in ('pending','failing','completed','superseded') or
                ('forced' in item and type(item['forced']) is not bool)):
            raise ValueError('invalid stop')
        for key in ('requestedAt','lastAttemptAt','endedAt'):
            if item[key] is not None: stamp(item[key])
    if (sandbox['id'] != worker or sandbox['state'] != 'stopped' or status['id'] != worker or
            sandbox['stop']['id'] != stop['id'] or sandbox['stop']['endedAt'] != stop['endedAt'] or any(item['status'] != 'completed' or item['error'] is not None or
                item['endedAt'] is None for item in (sandbox['stop'],stop))): raise ValueError('stop incomplete')
    return stop


def stopped_usage(usage, worker, ended_at):
    if (not isinstance(usage,dict) or set(usage) != {'sandboxId','sandboxType','billingMultiplier',
            'secondsPerDollar','seconds','dollars','running','since','until'} or
            usage['sandboxId'] != worker or usage['running'] is not False or
            type(usage['seconds']) is not int or usage['seconds'] < 0 or
            type(usage['dollars']) not in (int,Decimal) or not isinstance(usage['sandboxType'],str)):
        raise ValueError('invalid stopped usage')
    for key in ('billingMultiplier','secondsPerDollar'):
        if type(usage[key]) not in (int,Decimal): raise ValueError('invalid usage numeric field')
        number(usage[key])
    if not stamp(usage['since']) <= stamp(usage['until']) or stamp(usage['until']) < stamp(ended_at):
        raise ValueError('invalid meter time')
    return number(usage['dollars'])


def delete_receipt(root, spend_file, worker, ids_path, timeout=60):
    root, spend, ids_path = pathlib.Path(root), pathlib.Path(spend_file), pathlib.Path(ids_path)
    worker_id(worker); state = ids_path.parent
    if not math.isfinite(timeout) or timeout <= 0: raise ValueError('invalid deadline')
    # The absolute query budget is fixed before any lock acquisition.
    deadline = time.monotonic()+timeout
    fd = os.open(state/(worker+'.deletion.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as lock:
        if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError('invalid lock')
        while True:
            try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise TimeoutError()
                time.sleep(min(.05,max(0,deadline-time.monotonic())))
        return _delete(root,spend,worker,ids_path,timeout,deadline=deadline)

def _delete(root, spend, worker, ids_path, timeout, *, deadline=None):
    if worker not in ids_path.read_text().split():
        raise ValueError('worker not owned by this launch')
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('invalid deadline')
    # Only shorten the caller deadline; unused metering time is not delete authority.
    deadline = min(time.monotonic() + timeout, deadline) if deadline is not None else time.monotonic() + timeout
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
        env = {**os.environ, 'BOAT_COMMAND_TIMEOUT_SECONDS': str(remaining)}
        response = subprocess.run([str(root / 'bin/boat-call'), *args], capture_output=True,
                                  text=True, timeout=remaining + 70, env=env)
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
        if os.path.lexists(attempted): raise ValueError('uncertain deletion request; reconcile manually')
        exclusive_bytes(attempted,b'')
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


LEGACY_DECISION_SHA = '4e5caa263a8bf323abb78791f03c3a064df3ab0ee0b9b5bbb0b950e97a350660'
LEGACY_DECISION_FILE = 'factory/legacy-bx-z4wktrbn-budget-decision-20261104.json'


SMOKE_DECISION_SHA = 'a774c1e9d284ec99b135d9a195e33617a00c4a366ac4962ae0790e8beb46a929'
SMOKE_DECISION_FILE = 'factory/smoke-bx-bykfqbyn-budget-decision-20261104.json'


def legacy_decision(selector='legacy'):
    if selector not in ('legacy','smoke'): raise ValueError('unapproved decision')
    name,expected = (LEGACY_DECISION_FILE,LEGACY_DECISION_SHA) if selector=='legacy' else (SMOKE_DECISION_FILE,SMOKE_DECISION_SHA)
    path = pathlib.Path(__file__).resolve().parent.parent/name
    if sha256(path) != expected: raise ValueError('decision changed')
    return loads(regular(path))


def approved_budget_row(original, selector='legacy'):
    decision = legacy_decision(selector)
    if selector=='smoke':
        required={'usd','expires_at','status','state_path','vms','ttl_seconds','max_spend_usd'}
        if (not isinstance(original,dict) or set(original) not in (required,required|{'actual_spend_usd'}) or
                original['usd']!='0.036' or original['status']!='reserved' or
                type(original['expires_at']) not in (int,float,Decimal) or Decimal(str(original['expires_at']))!=Decimal('1793790083.3712797') or
                original['state_path']!=decision['state_path'] or
                type(original['vms']) is not int or original['vms']!=1 or
                type(original['ttl_seconds']) is not int or original['ttl_seconds']!=3600 or
                original['max_spend_usd']!='5' or original.get('actual_spend_usd') is not None):
            raise ValueError('not the approved smoke row')
    elif (not isinstance(original,dict) or original.get('status') != 'finished' or
            number(original['usd']) != Decimal('0.036') or
            any(k in original for k in ('state_path','vms','ttl_seconds','max_spend_usd','settlement','budget_debit')) or
            original.get('actual_spend_usd') is not None): raise ValueError('not the approved historical row')
    proof = dict(schema=1,decision_sha256=LEGACY_DECISION_SHA if selector=='legacy' else SMOKE_DECISION_SHA,
        **{k:decision[k] for k in ('spend_path','state_path','worker_id','deletion_operation_id','spend_sha256','budget_debit_usd')},
        budget_cap_usd=decision['infrastructure_budget_cap_usd'],actual_charge_status='unknown',original_row=original)
    return dict(original,status='budget_debited',actual_spend_usd=None,budget_debit=proof)


def budget_amount(row, key):
    if row['status'] == 'settled': return settlement_amount(row)
    if row['status'] != 'budget_debited': raise ValueError('unaccounted liability')
    proof=row.get('budget_debit')
    if not isinstance(proof,dict) or type(proof.get('schema')) is not int: raise ValueError('invalid conservative debit')
    approval=proof.get('decision_sha256')
    if approval not in (LEGACY_DECISION_SHA,SMOKE_DECISION_SHA): raise ValueError('unapproved decision')
    selector='legacy' if approval==LEGACY_DECISION_SHA else 'smoke'
    decision = legacy_decision(selector)
    if (key != decision['spend_path'] or not isinstance(row.get('budget_debit'),dict) or
            row != approved_budget_row(row['budget_debit']['original_row'],selector)):
        raise ValueError('invalid conservative debit')
    return Decimal('0.036')


def record_approved_debit(ledger, selector='legacy'):
    decision = legacy_decision(selector); key = decision['spend_path']; original = ledger['reservations'][key]
    if original['status'] == 'budget_debited':
        budget_amount(original,key); return False
    candidate = approved_budget_row(original,selector)
    spend, state = pathlib.Path(key),pathlib.Path(decision['state_path'])
    if spend != spend.resolve() or state != state.resolve() or sha256(spend) != decision['spend_sha256']:
        raise ValueError('historical spend mismatch')
    data = loads(regular(spend))
    if (data.get('provider') != 'boat' or data.get('allowed') is not True or
            type(data.get('vms')) is not int or data['vms'] != 1 or data.get('ttl_seconds') != 3600 or
            number(data.get('max_spend_usd')) != 5 or data.get('actual_spend_usd') is not None or
            (selector=='legacy' and not data.get('finished_at'))): raise ValueError('historical envelope mismatch')
    workers = settlement_workers(state,dict(original,vms=1,ttl_seconds=3600,max_spend_usd='5'))
    if workers != [decision['worker_id']]: raise ValueError('historical worker mismatch')
    import shlex
    values = [shlex.split(line.split('=',1)[1]) for line in regular(state/'monitor.sh').decode().splitlines() if line.startswith('spend_file=')]
    if values != [[str(spend)]]: raise ValueError('historical monitor mismatch')
    evidence = spend.with_suffix('.deletions')/workers[0]
    if evidence.is_symlink() or evidence.parent.is_symlink(): raise ValueError('historical evidence mismatch')
    if selector=='smoke' and (sha256(evidence/'deletion-request.json') != decision['deletion_request_sha256'] or
            sha256(evidence/'deletion-completion.json') != decision['deletion_completion_sha256']):
        raise ValueError('historical deletion hash mismatch')
    request,done = (loads(regular(evidence/name)) for name in ('deletion-request.json','deletion-completion.json'))
    if request.get('id') != decision['deletion_operation_id'] or request.get('targetId') != workers[0] or request.get('kind') != 'sandbox':
        raise ValueError('historical deletion mismatch')
    completion(done,workers[0],decision['deletion_operation_id'])
    budget_amount(candidate,key)
    ledger['reservations'][key]=candidate
    return True

def read_ledger(path, *, missing_ok=True):
    try:
        ledger = (loads(regular(path)) if path and (not missing_ok or path.exists())
                  else {'version': 1, 'reservations': {}})
        if (not isinstance(ledger, dict) or type(ledger.get('version')) is not int or
                ledger['version'] != 1 or not isinstance(ledger.get('reservations'), dict)):
            raise ValueError()
        for key, row in ledger['reservations'].items():
            if (not isinstance(key, str) or not isinstance(row, dict) or
                    row.get('status') not in ('reserved', 'finished', 'reconciled_expired', 'settled', 'budget_debited') or
                    type(row.get('usd')) not in (str, int, Decimal)):
                raise ValueError()
            amount = Decimal(str(row['usd']))
            if not amount.is_finite() or amount < 0: raise ValueError()
            if 'state_path' in row:
                if row['state_path'] is not None and (not isinstance(row['state_path'], str) or not pathlib.Path(row['state_path']).is_absolute()):
                    raise ValueError()
                for field in ('vms', 'ttl_seconds'):
                    if type(row[field]) is not int or row[field] < 1: raise ValueError()
                number(row['max_spend_usd'])
            if row['status'] in ('settled','budget_debited'): budget_amount(row,key)
        return ledger
    except (ValueError, TypeError, KeyError, DecimalException):
        raise ValueError('invalid reservation ledger') from None


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
