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
import uuid
from contextlib import contextmanager


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
    new = any(os.path.lexists(pathlib.Path(state)/(w+'.retiring.json')) for w in workers)
    for worker in workers:
        if new:
            root = pathlib.Path(__file__).resolve().parent.parent
            proof,usage,dollars = read_meter(root,pathlib.Path(spend),worker,pathlib.Path(state))
            done = receipts[worker]
            result.append(dict(id=worker,deletion_operation_id=done['id'],completed_at=done['completedAt'],
                seconds=usage['seconds'],dollars=format(dollars,'f'),retirement_id=proof['retirement_id'],
                stop_id=proof['stop_id'],receipt_sha256=sha256(pathlib.Path(spend).with_suffix('.deletions')/worker/'retirement-proof.json')))
            continue
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
    return dict(schema=2 if new else 1, state_path=str(state), settled_at=utc_now(),
                basis='stopped_usage_then_deleted' if new else ('deleted_lifetime_usage' if workers else 'no_creation'), workers=result)


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


def atomic_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = pathlib.Path(stream.name)
        try:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            temporary.replace(path)
            fsync_directory(path.parent)
        finally: temporary.unlink(missing_ok=True)


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


def argument(argv, key):
    positions = [i for i, value in enumerate(argv) if value.split('=', 1)[0] == key]
    if not positions: return None
    if len(positions) != 1: raise ValueError('duplicate launch argument')
    i = positions[0]
    if argv[i] != key or i+1 >= len(argv): raise ValueError('invalid launch argument')
    return argv[i+1]


def bounded_context(root, spend, worker, state):
    """Recompute authority from the existing policy, operation, creation and ledger."""
    import batch_holder as holder
    import batch_money as money
    import key_holder
    import practice
    root, spend, state = map(pathlib.Path, (root, spend, state))
    home = pathlib.Path(os.environ.get('UNBUG_CONTROL_HOME', str(pathlib.Path.home()/'.unbug-control'))).resolve()
    if (state != state.resolve() or state.is_symlink() or state.parent != home/'launches' or
            not re.fullmatch('[0-9a-f]{32}', state.name) or spend != spend.resolve() or
            not spend.is_relative_to(root.resolve()/'results/spend')): raise ValueError('invalid launch path')
    policy = key_holder.policy_load(home/'policy.json')
    if not holder.active(policy, root): raise ValueError('inactive bounded launch')
    record = money.manifest(policy, root)
    if record['id'] != practice.BATCH and not __import__('pilot').managed(policy):
        raise ValueError('not bounded practice or pilot')
    launch = loads(regular(state/'launch.json'))
    identity = launch['environment']['UNBUG_BATCH_OPERATION']
    directory = home/'batches'/record['id']
    op = holder._operations(directory, record, policy)[identity]
    if not op['dispatch_started'] or op['launch_id'] != state.name or op['launch'] != launch:
        raise ValueError('launch mismatch')
    config = holder._config(policy, home, op)
    if (argument(launch['argv'], '--factory-job-config') != str(config) or
            argument(launch['argv'], '--factory-job-config-sha256') != op['config_sha256'] or
            argument(launch['argv'], '--checkpoint-sha256') != op['source_generation']):
        raise ValueError('launch generation mismatch')
    ledger = read_ledger(home/'boat-reservations.json', missing_ok=False)
    matches = [(path,row) for path,row in ledger['reservations'].items() if row.get('state_path') == str(state)]
    if len(matches) != 1 or matches[0][0] != str(spend): raise ValueError('spend binding mismatch')
    row = matches[0][1]
    if row['status'] not in ('reserved','finished'): raise ValueError('unknown liability')
    data = loads(regular(spend))
    if (data.get('provider') != 'boat' or data.get('allowed') is not True or
            data.get('vms') != row['vms'] or data.get('ttl_seconds') != row['ttl_seconds'] or
            number(data.get('max_spend_usd')) != number(row['max_spend_usd'])):
        raise ValueError('envelope mismatch')
    if worker not in settlement_workers(state,row): raise ValueError('worker not owned')
    sources = []
    for path in state.glob('new.*'):
        events = [loads(line) for line in regular(path).splitlines() if line.strip()]
        if any(e.get('event') == 'created' and e.get('id') == worker for e in events): sources.append(path)
    if len(sources) != 1: raise ValueError('creation ambiguous')
    started = regular(state/(worker+'.started')).decode().strip()
    if not started.isascii() or not started.isdigit() or not 0 < int(started) <= time.time():
        raise ValueError('invalid start')
    _, due, _ = practice.deadlines(int(started))
    return dict(worker_id=worker,state_path=str(state),spend_path=str(spend),
        launch_sha256=sha256(state/'launch.json'), creation_sha256=sha256(sources[0]),
        source_generation=op['source_generation'],job_config_sha256=op['config_sha256'],
        started_unix=int(started),delete_due_utc=due)


MARKER_KEYS = {'schema','retirement_id','worker_id','state_path','spend_path','launch_sha256',
    'creation_sha256','source_generation','job_config_sha256','started_unix','created_at','boot_id',
    'meter_deadline_mono','meter_deadline_utc','delete_due_utc'}


def boot_id():
    return regular(pathlib.Path('/proc/sys/kernel/random/boot_id')).decode().strip()


def retirement_marker(root, spend, worker, state, delete_due=None):
    facts = bounded_context(root,spend,worker,state)
    path = state/(worker+'.retiring.json')
    if os.path.lexists(path):
        marker = loads(regular(path))
        if (not isinstance(marker,dict) or set(marker) != MARKER_KEYS or type(marker['schema']) is not int or
                marker['schema'] != 1 or any(marker[k] != v for k,v in facts.items())):
            raise ValueError('retirement binding mismatch')
        if str(uuid.UUID(marker['retirement_id'])) != marker['retirement_id']: raise ValueError('invalid generation')
        created = stamp(marker['created_at'])
        for key in ('meter_deadline_mono','meter_deadline_utc'):
            if type(marker[key]) not in (int,float,Decimal) or not math.isfinite(marker[key]) or marker[key] < 0:
                raise ValueError('invalid clock')
        if (not isinstance(marker['boot_id'],str) or
                marker['meter_deadline_utc'] > min(created+120, facts['delete_due_utc']-180)):
            raise ValueError('invalid meter deadline')
        return marker
    if delete_due != facts['delete_due_utc']: raise ValueError('deadline mismatch')
    now = time.time(); cutoff = min(now+120,delete_due-180)
    try: boot = boot_id()
    except OSError: boot = ''  # No Linux clock proof: safety deletion only, never meter.
    marker = dict(schema=1,retirement_id=str(uuid.uuid4()),**facts,created_at=utc_now(),boot_id=boot,
        meter_deadline_mono=max(0,time.monotonic()+cutoff-now),meter_deadline_utc=max(0,cutoff))
    try: exclusive_bytes(path,json.dumps(marker).encode())
    except FileExistsError: return retirement_marker(root,spend,worker,state,delete_due)
    return marker


def owner_fd(state, worker, fd):
    """Existing kernel WRITE FLOCK only. Never upgrade a shared descriptor."""
    try:
        if fcntl.fcntl(fd,fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR: return False
        proof = os.fstat(fd); target = (state/(worker+'.deletion.lock')).lstat()
        if (not stat.S_ISREG(proof.st_mode) or not stat.S_ISREG(target.st_mode) or
                (proof.st_dev,proof.st_ino) != (target.st_dev,target.st_ino)): return False
        lines = regular(pathlib.Path('/proc/self/fdinfo')/str(fd)).decode().splitlines()
        return any(re.fullmatch(r'lock:\s+\d+:\s+FLOCK\s+ADVISORY\s+WRITE\s+\d+\s+[0-9a-f]+:[0-9a-f]+:\d+\s+0\s+EOF', line) for line in lines)
    except (OSError,ValueError,TypeError): return False


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


@contextmanager
def command_fence(root, args, timeout):
    """One wrapper gate; only deadline DELETE may bypass another owner's EX."""
    raw = os.environ.get('UNBUG_LAUNCH_STATE')
    if not raw:
        yield None; return
    state = pathlib.Path(raw)
    if state.is_symlink() or (state != state.resolve() and list(state.glob('*.retiring.json'))):
        raise ValueError('invalid managed state')
    state = state.resolve()
    try: names = regular(state/'ids').decode().split()
    except FileNotFoundError:
        if list(state.glob('*.retiring.json')): raise ValueError('missing ownership')
        names = []
    if len(names) != len(set(names)): raise ValueError('duplicate ownership')
    for name in names: worker_id(name)
    targets = [w for w in names if any(a.split('=',1)[-1] == w or a.split('=',1)[-1].startswith(w+':') for a in args[1:])]
    if not targets:
        if args[:1] == ['delete'] and list(state.glob('*.retiring.json')):
            raise ValueError('foreign deletion')
        yield None; return
    if (args[0] in ('info','usage','list','deletion') or
            (len(args)==5 and args[:1]==['stop'] and args[2]=='--status' and args[4]=='--json')):
        yield None; return
    if len(targets) != 1: raise ValueError('ambiguous managed command')
    worker = targets[0]
    fenced = state/(worker+'.retiring.json')
    inherited = os.environ.get('UNBUG_BOAT_RETIREMENT_FD','')
    owns = inherited.isascii() and inherited.isdigit() and owner_fd(state,worker,int(inherited))
    if os.path.lexists(fenced):
        marker = loads(regular(fenced))
        marker = retirement_marker(root,pathlib.Path(marker['spend_path']),worker,state)
        emergency = args == ['delete',worker,'--yes','--json'] and time.time() >= marker['delete_due_utc']
        if args[:1] == ['delete']:
            if args != ['delete',worker,'--yes','--json'] or not (owns or emergency):
                raise ValueError('retirement deletion refused')
            yield dict(worker=worker,state=state,emergency=emergency); return
        if args != ['stop',worker,'--json'] or not owns:
            raise ValueError('worker retiring')
        yield None; return
    # Ordinary deletion must own EX; legacy helper's child passes its actual FD.
    if args[:1] == ['delete']:
        if bounded_launch(state): raise ValueError('bounded deletion requires retirement marker')
        yield None; return
    fd = os.open(state/(worker+'.deletion.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode): raise ValueError('invalid lock')
        deadline = time.monotonic()+timeout
        while True:
            try: fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise TimeoutError()
                time.sleep(min(.05,max(0,deadline-time.monotonic())))
        if os.path.lexists(fenced): raise ValueError('worker retiring')
        yield None



def bounded_launch(state):
    try: env = loads(regular(state/'launch.json'))['environment']
    except FileNotFoundError: return False
    return bool(env.get('UNBUG_PRACTICE_BATCH') or env.get('UNBUG_PILOT_PIN'))

def claim_delete(authorization):
    if authorization is None: return
    state, worker = authorization['state'], authorization['worker']
    exclusive_bytes(state/(worker+'.deletion-attempted'),b'')
    if authorization['emergency']:
        exclusive_bytes(state/(worker+'.metering-bypassed'),b'')


PROOF_KEYS = {'schema','retirement_id','worker_id','state_path','spend_path','retiring_sha256',
    'launch_sha256','creation_sha256','stop_id','stop_ended_at','source_generation','job_config_sha256','files','captured_at'}
METER_FILES = {'stop-status.json','stopped-info.json','rechecked-info.json','final-usage.json'}


def meter_deadline(marker):
    if not marker['boot_id'] or marker['boot_id'] != boot_id(): raise ValueError('boot changed')
    return min(float(marker['meter_deadline_mono']),time.monotonic()+float(marker['meter_deadline_utc'])-time.time())


def read_meter(root, spend, worker, state):
    marker = retirement_marker(root,spend,worker,state)
    if os.path.lexists(state/(worker+'.metering-bypassed')): raise ValueError('meter bypassed')
    evidence = spend.with_suffix('.deletions')/worker
    if evidence.is_symlink() or evidence.parent.is_symlink(): raise ValueError('invalid evidence')
    proof = loads(regular(evidence/'retirement-proof.json'))
    bindings = {k:marker[k] for k in ('retirement_id','worker_id','state_path','spend_path','launch_sha256',
                                     'creation_sha256','source_generation','job_config_sha256')}
    if (not isinstance(proof,dict) or set(proof) != PROOF_KEYS or type(proof['schema']) is not int or
            proof['schema'] != 1 or any(proof[k] != v for k,v in bindings.items()) or
            proof['retiring_sha256'] != sha256(state/(worker+'.retiring.json')) or
            not isinstance(proof['files'],dict) or set(proof['files']) != METER_FILES or
            any(sha256(evidence/name) != value for name,value in proof['files'].items())):
        raise ValueError('invalid meter proof')
    info, status, rechecked, usage = (loads(regular(evidence/name)) for name in
        ('stopped-info.json','stop-status.json','rechecked-info.json','final-usage.json'))
    # Info files retain public projection plus exact command and capture clock.
    for item in (info,rechecked):
        if (not isinstance(item,dict) or set(item) != {'command','captured_at','response'} or
                item['command'] != ['info',worker,'--json']): raise ValueError('invalid info receipt')
        stamp(item['captured_at'])
    stop = stopped(info['response'],status,worker)
    if stopped(rechecked['response'],status,worker)['id'] != stop['id']: raise ValueError('stop changed')
    dollars = stopped_usage(usage,worker,stop['endedAt'])
    if (proof['stop_id'] != stop['id'] or proof['stop_ended_at'] != stop['endedAt'] or
            not stamp(stop['endedAt']) <= stamp(proof['captured_at']) <= float(marker['meter_deadline_utc']) or
            stamp(rechecked['captured_at']) > stamp(proof['captured_at'])):
        raise ValueError('invalid capture time')
    return proof, usage, dollars


def capture_meter(root, spend, worker, state, marker, fd):
    target=spend.with_suffix('.deletions')/worker/'capture-stage.json'
    if os.path.lexists(state/(worker+'.deletion-attempted')):
        return _capture_meter(root,spend,worker,state,marker,fd,['initial_info'])
    if target.exists():
        old=loads(regular(target))
        if not isinstance(old,dict): raise ValueError('invalid capture receipt')
        if old.get('retirement_id') != marker['retirement_id'] or old.get('worker_id') != worker:
            raise ValueError('capture receipt identity mismatch')
        if old.get('outcome')=='failed':
            # Diagnostic only: retain the first failure; existing window/proof
            # rules still decide whether a recheck can succeed.
            return _capture_meter(root,spend,worker,state,marker,fd,['initial_info'])
    stage=['initial_info']
    try:
        result=_capture_meter(root,spend,worker,state,marker,fd,stage)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        kind=('timeout' if isinstance(error,(TimeoutError,subprocess.TimeoutExpired)) else
              'rpc' if isinstance(error,subprocess.SubprocessError) else
              'io' if isinstance(error,OSError) else 'invalid_response')
        atomic_bytes(target,json.dumps(dict(schema=1,retirement_id=marker['retirement_id'],worker_id=worker,
            stage=stage[0],outcome='failed',error_class=kind,observed_at=utc_now())).encode())
        raise
    atomic_bytes(target,json.dumps(dict(schema=1,retirement_id=marker['retirement_id'],worker_id=worker,
        stage=stage[0],outcome='complete',error_class=None,observed_at=utc_now())).encode())
    return result


def _capture_meter(root, spend, worker, state, marker, fd, stage):
    evidence = spend.with_suffix('.deletions')/worker
    evidence.mkdir(parents=True,exist_ok=True)
    if evidence.is_symlink() or evidence.parent.is_symlink(): raise ValueError('invalid evidence')
    attempted = state/(worker+'.deletion-attempted')
    if os.path.lexists(attempted): return read_meter(root,spend,worker,state)
    deadline = meter_deadline(marker)
    def query(*args):
        remaining = deadline-time.monotonic()
        command = min(20,remaining-71)
        if command <= 0: raise TimeoutError()
        response = subprocess.run([str(root/'bin/boat-call'),*args],capture_output=True,check=True,
            timeout=command+71,pass_fds=(fd,),env={**os.environ,'UNBUG_LAUNCH_STATE':str(state),
            'UNBUG_BOAT_RETIREMENT_FD':str(fd),'BOAT_COMMAND_TIMEOUT_SECONDS':str(command)})
        if time.monotonic() >= deadline: raise TimeoutError()
        return bytes(response.stdout), loads(response.stdout)
    def info():
        _, data = query('info',worker,'--json')
        sandbox = data['sandbox']
        # Never persist provider environment/commands/user data from info.
        projection = {'sandbox':{k:sandbox[k] for k in ('id','state','stop')}}
        if sandbox['id'] != worker: raise ValueError('wrong info identity')
        return dict(command=['info',worker,'--json'],captured_at=utc_now(),response=projection)
    if (evidence/'retirement-proof.json').exists():
        receipt = read_meter(root,spend,worker,state)
        current = info()
        stopped(current['response'],loads(regular(evidence/'stop-status.json')),worker)
        return receipt  # Immutable capture; a restart never renews its generation/window.
    current = info()
    stop = current['response']['sandbox']['stop']
    if (not isinstance(stop,dict) or not isinstance(stop.get('id'),str) or not stop['id'] or
            (current['response']['sandbox']['state'] != 'stopped' and stop.get('status') in ('completed','superseded'))):
        if not os.path.lexists(evidence/'stop-request.json'):
            stage[0]='stop_request'
            _, response = query('stop',worker,'--json')
            if not isinstance(response,dict): raise ValueError('invalid stop response')
            nested=response.get('sandbox')
            if nested is not None and not isinstance(nested,dict): raise ValueError('invalid stop response')
            if response.get('id',worker) != worker or (nested is not None and nested.get('id',worker) != worker):
                raise ValueError('wrong stop response')
            # Do not persist arbitrary action DTO fields: only allowlisted public identity/stop.
            public = {k:response[k] for k in ('id','stop') if k in response}
            atomic_bytes(evidence/'stop-request.json',json.dumps(public).encode())
        stage[0]='stop_identity'
        while True:
            current = info(); stop = current['response']['sandbox']['stop']
            if stop is not None:
                if not isinstance(stop,dict) or not isinstance(stop.get('id'),str) or not stop['id']:
                    raise ValueError('invalid stop identity')
                if stop.get('status')=='superseded': raise ValueError('stop superseded')
                break
            if deadline-time.monotonic() <= 73: raise TimeoutError()
            time.sleep(2)
    stop_id = stop['id']
    if not isinstance(stop_id,str) or not stop_id: raise ValueError('no stop id')
    while True:
        stage[0]='stop_status'
        raw_status,status = query('stop',worker,'--status',stop_id,'--json')
        if (not isinstance(status,dict) or not isinstance(status.get('stop'),dict) or status.get('id') != worker or status.get('stop',{}).get('id') != stop_id or
                status['stop'].get('status') not in ('pending','failing','completed','superseded')):
            raise ValueError('stop identity mismatch')
        if status['stop']['status']=='superseded': raise ValueError('stop superseded')
        if status['stop']['status']=='completed': break
        if deadline-time.monotonic() <= 73: raise TimeoutError()
        time.sleep(2)
    stage[0]='stopped_info'
    while True:
        current=info(); sandbox=current['response']['sandbox']
        observed=sandbox['stop']
        if observed is not None and (not isinstance(observed,dict) or observed.get('id') != stop_id):
            raise ValueError('stop changed')
        if isinstance(observed,dict) and observed.get('status')=='superseded': raise ValueError('stop superseded')
        if sandbox['state']=='stopped': break
        if deadline-time.monotonic() <= 73: raise TimeoutError()
        time.sleep(2)
    ended = stopped(current['response'],status,worker)['endedAt']
    stage[0]='usage'
    raw_usage, usage = query('usage',worker,'--json')
    stopped_usage(usage,worker,ended)
    stage[0]='recheck_info'
    rechecked = info(); stopped(rechecked['response'],status,worker)
    if time.monotonic() >= deadline or os.path.lexists(state/(worker+'.metering-bypassed')): raise TimeoutError()
    raw = {'stop-status.json':raw_status,'final-usage.json':raw_usage,
           'stopped-info.json':json.dumps(current).encode(),'rechecked-info.json':json.dumps(rechecked).encode()}
    for name,content in raw.items(): atomic_bytes(evidence/name,content)
    proof = dict(schema=1,**{k:marker[k] for k in ('retirement_id','worker_id','state_path','spend_path',
        'launch_sha256','creation_sha256','source_generation','job_config_sha256')},
        retiring_sha256=sha256(state/(worker+'.retiring.json')),stop_id=stop_id,stop_ended_at=ended,
        files={name:hashlib.sha256(content).hexdigest() for name,content in raw.items()},captured_at=utc_now())
    if os.path.lexists(attempted) or time.monotonic() >= deadline: raise TimeoutError()
    stage[0]='proof_commit'
    atomic_bytes(evidence/'retirement-proof.json',json.dumps(proof).encode())
    return read_meter(root,spend,worker,state)


def delete_receipt(root, spend_file, worker, ids_path, timeout=60, delete_due=None):
    root, spend, ids_path = pathlib.Path(root), pathlib.Path(spend_file), pathlib.Path(ids_path)
    worker_id(worker); state = ids_path.parent
    if not math.isfinite(timeout) or timeout <= 0: raise ValueError('invalid deadline')
    # The absolute query budget is fixed before any lock acquisition.
    deadline = time.monotonic()+timeout
    fenced = os.path.lexists(state/(worker+'.retiring.json'))
    if fenced or delete_due is not None or bounded_launch(state):
        if not fenced:
            due = bounded_context(root,spend,worker,state)['delete_due_utc']
            if delete_due is not None and delete_due != due: raise ValueError('wrong delete deadline')
            if time.time() < due:
                regular(state/(worker+'.collected'))  # No preemption to gain a meter.
            marker = retirement_marker(root,spend,worker,state,due)
        else: marker = retirement_marker(root,spend,worker,state,delete_due)
        # Metering has its own original bound; deleting gets no fresh minute after it.
        if time.time() >= marker['delete_due_utc']:
            return _delete(root,spend,worker,ids_path,min(timeout,5),fenced=True)
        delete_end = min(time.monotonic()+max(0,min(120,float(marker['meter_deadline_utc'])-time.time()))+timeout,
                         time.monotonic()+max(0,marker['delete_due_utc']-time.time()))
        fd = os.open(state/(worker+'.deletion.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+') as lock:
            if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError('invalid lock')
            wait_end = min(time.monotonic()+5,deadline)
            while True:
                try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic() >= wait_end: raise TimeoutError()
                    time.sleep(min(.05,max(0,wait_end-time.monotonic())))
            retained = os.path.lexists(spend.with_suffix('.deletions')/worker/'retirement-proof.json')
            try: capture_meter(root,spend,worker,state,marker,fd)
            except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError):
                # A retained meter needs its current-stop recheck before a new
                # ordinary DELETE. Keep it immutable; deadline deletion can
                # later invalidate it via the wrapper winner's bypass marker.
                if retained: raise
            # Metering allowance and delete budget are independent, both absolute.
            return _delete(root,spend,worker,ids_path,timeout,deadline=delete_end,fenced=True,owner=fd)
    fd = os.open(state/(worker+'.deletion.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+') as lock:
        if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError('invalid lock')
        while True:
            try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise TimeoutError()
                time.sleep(min(.05,max(0,deadline-time.monotonic())))
        return _delete(root,spend,worker,ids_path,timeout,deadline=deadline)

def _delete(root, spend, worker, ids_path, timeout, *, deadline=None, fenced=False, owner=None):
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
        inherited = ()
        if fenced:
            env['UNBUG_LAUNCH_STATE'] = str(ids_path.parent)
            if owner is not None:
                env['UNBUG_BOAT_RETIREMENT_FD'] = str(owner); inherited = (owner,)
        response = subprocess.run([str(root / 'bin/boat-call'), *args], capture_output=True,
                                  text=True, timeout=remaining + 70, pass_fds=inherited, env=env)
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
        if not fenced: exclusive_bytes(attempted,b'')
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
