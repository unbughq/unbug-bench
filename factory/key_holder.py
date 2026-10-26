#!/usr/bin/env python3
"""Local, bounded recovery launcher. Its socket never exports the founder identity."""
import argparse
import ctypes
import datetime
import getpass
import fcntl
import hashlib
import json
import math
import mmap
import os
import pathlib
import re
import resource
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import uuid

from recovery import explicit_pause, require_holder_stop, ledger_agrees

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Linux control-VM reservations must survive a reboot; keep the Mac socket location.
CONTROL_HOME = pathlib.Path(os.environ.get('UNBUG_CONTROL_HOME', str(pathlib.Path.home()/'.unbug-control'))).expanduser().resolve()
RUNTIME = (pathlib.Path('/private/tmp') if sys.platform == 'darwin' else CONTROL_HOME) / ('unbug-key-holder-' + str(os.getuid()) + '-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:8])
SOCKET = RUNTIME / 'control.sock'
OPENCODE_ACCOUNTS = {1: 'opencode-go-key', 2: 'opencode-go-key-2'}
# 2026-10-20: factory Claude subscriptions, one per launch; claude-token-2 is the exam account and never a factory one.
CLAUDE_ACCOUNTS = {1: 'claude-token', 2: 'claude-factory-token-2', 3: 'claude-factory-token-3'}


def concurrent_peer_cancel(card, budget, job):
    """The last cancelled calibrator can overwrite its peer's primary process error."""
    if (job.get('allow_parallel_peer_cancellation') is not True or job['mode'] != 'case' or
            card.get('dry_run') is not False or card.get('terminal_stop') not in ('opencode_error', 'process_error') or
            budget.get('terminal_stop') != 'cancelled'):
        return False
    counts = card.get('calibration_interruptions') or {}
    positive = lambda x: type(x) is int and x > 0
    for primary, peer in (('strong_calibrator', 'easy_calibrator'), ('easy_calibrator', 'strong_calibrator')):
        first, second = counts.get(primary) or {}, counts.get(peer) or {}
        if (positive(first.get('model_process_error')) and positive(second.get('cancelled')) and
                set(first) <= {'model_process_error'} and set(second) <= {'cancelled'}):
            return True
    return False


def secret_labels(identity, path):
    """Decrypt only the approved credential bundle into an age|tar pipe; return labels only."""
    age = subprocess.Popen(['age', '-d', '-i', '/dev/stdin', str(path)], stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    listing = subprocess.Popen(['tar', '-tf', '-'], stdin=age.stdout, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    age.stdout.close()
    try:
        age.stdin.write(identity); age.stdin.close()
        output, _ = listing.communicate(timeout=10)
        if age.wait(timeout=5) != 0 or listing.returncode != 0:
            raise ValueError('credential bundle metadata unavailable')
        names = {line.removeprefix('./') for line in output.decode('utf-8').splitlines()}
        return (set(OPENCODE_ACCOUNTS.values()) | set(CLAUDE_ACCOUNTS.values())) & names
    except BaseException:
        for child in (age, listing):
            if child.poll() is None: child.kill()
            child.wait()
        raise


def secure_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.lstat()
    if path.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError('unsafe private directory')


def read_control_identity(path):
    """Open once without following links; accept one age identity and keygen comments."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        st = os.fstat(file.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600:
            raise ValueError('control identity requires a regular 0600 file owned by the current owner')
        raw = bytearray(file.read(4097))
    lines = [line for line in raw.splitlines() if line and not line.startswith(b'#')]
    if len(raw) > 4096 or len(lines) != 1 or not re.fullmatch(rb'AGE-SECRET-KEY-1[0-9A-Z]+', lines[0]):
        raw[:] = b'\0' * len(raw)
        raise ValueError('invalid control age identity file')
    identity = bytearray(lines[0] + b'\n')
    raw[:] = b'\0' * len(raw)
    return identity


# Host code that holds the founder identity, decrypted model keys or decrypted cases (2026-10-19). VM-side factory
# code (run.py, prompts, rotation tables) runs beside those keys and cases on the VM anyway, so pinning it never
# protected the identity; it made every factory fix cost the founder a new unlock.
# Admission helpers imported by the host restart planner are part of the trusted launcher.
PINNED = ('factory/qualified-adapter.sha256', 'factory/control_resume.py', 'factory/key_holder.py', 'factory/launch.sh', 'factory/collect.sh', 'bin/boat-launch-guards.sh', 'bin/boat-call',
          'bin/boat-name', 'bin/boat-spend', 'bin/hcloud-boat', 'bin/hcloud-park', 'bin/push-secrets',
          'factory/sealed_audit.py', 'factory/ttl_continuation.py', 'factory/coordinator.py', 'factory/restart.py', 'factory/recovery.py', 'factory/registry.py',
          'factory/statement_round.py', 'factory/admission.py', 'factory/calibration.py', 'factory/account_handoff.py')


def fingerprint(root):
    h = hashlib.sha256()
    for name in PINNED:
        p = root / name
        if p.is_symlink(): raise ValueError('symlink in trusted launcher code')
        h.update(name.encode() + b'\0' + (p.read_bytes() if p.is_file() else b'<absent>') + b'\0')
    return h.hexdigest()


def policy_load(path):
    policy = json.loads(path.read_text())
    if policy['root'] != str(ROOT) or policy['code_sha256'] != fingerprint(ROOT):
        raise ValueError('trusted launcher code changed; unlock requires a reviewed policy')
    for name, job in policy['jobs'].items():
        if not re.fullmatch(r'[a-z0-9-]+', name):
            raise ValueError('invalid job name')
        args = job['args']
        additional_attempt_policy_check(job)
        if 'ttl_continuation' in job:
            from ttl_continuation import policy_check
            policy_check(job)
        audit_flag = {"fairness": "--audit-fairness", "rehearsal": "--rehearse-only"}.get(job["mode"])
        if any(flag in args for flag in ("--audit-fairness", "--rehearse-only")):
            if not audit_flag or args.count(audit_flag) != 1:
                raise ValueError("sealed audit flag requires its explicit policy mode")
        elif audit_flag:
            raise ValueError("sealed audit policy is missing its mode flag")
        restore_flags = [i for i, value in enumerate(args) if value in ('--restore', '--restore-review')]
        if job['mode'] == 'any':  # 2026-10-19: repair or rerun any collected case; the case id comes with the launch request
            if restore_flags or job.get('variant') not in ('repair', 'rerun') or '--skip-build' in args or '--source' in args or '--rotation-slot' in args:
                raise ValueError('an any-case job names a variant and only common options')
        elif job['mode'] == 'new':  # founder 2026-10-19: wave-2 cases launch through the holder too, one VM per job
            if (args[0] != '1' or restore_flags or not re.fullmatch(r'new-[a-z0-9-]+', job['case']) or
                    '--rotation-slot' not in args or '--source' not in args):
                raise ValueError('a new-case job launches exactly one case on one rotation slot')
        else:
            if args[0] != '1' or len(restore_flags) != 1:
                raise ValueError('only one-case recovery jobs are allowed')
            index = restore_flags[0]
            if (index + 1 >= len(args) or args[index + 1] != job['case'] or
                    args[index] != ('--restore-review' if job['mode'] == 'review' else '--restore')):
                raise ValueError('recovery mode or case argument differs from policy')
            if job['case'] not in args or not re.fullmatch(r'case-[A-Za-z0-9-]+', job['case']):
                raise ValueError('invalid recovery case')
        initial = job.get('initial_accounts', {})
        if not isinstance(initial, dict) or any(p not in ('opencode', 'claude') or type(a) is not int or
                a not in job.get(p + '_accounts', []) for p, a in initial.items()):
            raise ValueError('invalid explicit initial account selection')
        accounts = job.get('opencode_accounts', [])
        if (not isinstance(accounts, list) or len(accounts) != len(set(accounts)) or
                any(type(v) is not int or v not in OPENCODE_ACCOUNTS for v in accounts) or
                (accounts and job.get('opencode_account', accounts[0]) not in accounts)):
            raise ValueError('invalid OpenCode account policy')
        for provider, available in (('opencode', OPENCODE_ACCOUNTS), ('claude', CLAUDE_ACCOUNTS)):
            limited = job.get(provider + '_limited_accounts', [])
            if not isinstance(limited, list) or any(type(a) is not int or a not in available for a in limited):
                raise ValueError('invalid limited account history')
        claude = job.get('claude_accounts', [])
        if (not isinstance(claude, list) or len(claude) != len(set(claude)) or
                any(type(v) is not int or v not in CLAUDE_ACCOUNTS for v in claude)):
            raise ValueError('invalid Claude account policy')
    return policy


def additional_attempt_policy_check(job):
    """One explicit retry against retained history; defaults to the fourth attempt."""
    if 'additional_attempt' not in job: return
    auth = job['additional_attempt']
    if (job.get('mode') != 'case' or not isinstance(auth, dict) or
            set(auth) not in ({'case', 'generation', 'recovery_conditions_sha256', 'reason'},
                              {'case', 'generation', 'recovery_conditions_sha256', 'reason', 'prior_attempts_sha256'}) or
            ('prior_attempts_sha256' in auth and (not isinstance(auth['prior_attempts_sha256'], str) or
             not re.fullmatch(r'[0-9a-f]{64}', auth['prior_attempts_sha256']))) or
            auth['case'] != job.get('case') or
            any(not isinstance(auth[k], str) or not re.fullmatch(r'[0-9a-f]{64}', auth[k])
                for k in ('generation', 'recovery_conditions_sha256')) or
            not isinstance(auth['reason'], str) or not auth['reason'].strip()):
        raise ValueError('invalid additional attempt authorization')


def admit_attempt(job, generation, req, receipts, counted):
    """Called in the serialized request loop, before durable reservation/start.

    Extensions count ALL case rows, ignoring legacy resolution/cutoff knobs.
    The explicit request opt-in keeps an ordinary coordinator launch refused.
    """
    additional_attempt_policy_check(job)
    auth = job.get('additional_attempt')
    requested = req.get('additional_attempt_generation')
    if auth is None:
        if requested is not None or counted >= 3:
            raise ValueError('cohort recovery attempt limit reached')
        return None
    rows = [v for v in receipts if v['case'] == job['case']]
    fifth = 'prior_attempts_sha256' in auth
    expected = 4 if fifth else 3
    history_ok = (hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest() ==
                  auth['prior_attempts_sha256']) if fifth else not any(v.get('additional_attempt') for v in rows)
    if (len(rows) != expected or counted != expected or generation != auth['generation'] or
            requested != generation or not history_ok):
        raise ValueError('additional attempt requires exact retained history and manual generation')
    card = json.loads((ROOT/'sealed'/job['card']).read_text())
    if (card.get('case') != auth['case'] or card.get('sha256') != generation or
            recovery_conditions_digest(card) != auth['recovery_conditions_sha256']):
        raise ValueError('additional attempt recovery conditions changed')
    return auth.copy()


def policy_digest(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def recovery_conditions_digest(card):
    """Exact model, original conditions and cumulative usage form one attestation."""
    config, roles = card.get('recovery_config'), card.get('roles')
    if (not isinstance(config, dict) or config.get('version') != 1 or type(card.get('seed')) is not int or
            not isinstance(roles, dict) or not roles):
        raise ValueError('missing recovery conditions')
    exact = {}
    for name, data in roles.items():
        if not isinstance(data, dict) or not isinstance(data.get('model'), str) or not isinstance(data.get('effort'), str):
            raise ValueError('missing exact recovery model')
        exact[name] = {'model': data['model'], 'effort': data['effort']}
    budget = card.get('continuation_budget') or {}
    calls, cost = budget.get('calls'), budget.get('cost')
    if type(calls) is not int or calls < 0 or type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
        raise ValueError('missing cumulative recovery usage')
    return hashlib.sha256(json.dumps({'recovery_config': config, 'roles': exact, 'seed': card['seed'],
                                     'source': card.get('source'), 'rotation_slot': card.get('rotation_slot'),
                                     'cumulative_usage': {'calls': calls, 'cost': cost}},
                                     sort_keys=True, allow_nan=False).encode()).hexdigest()


def attest_launch(job, generation, req):
    """Optional coordinator expectations are checked inside the holder's request lock.

    Existing direct clients keep their policy behavior. Attested clients can never
    launch a different collected generation, model route, limit set or explicit pause.
    """
    fields = {'expected_generation', 'expected_recovery_config_sha256'}
    if not fields.intersection(req): return
    if (not fields <= set(req) or job['mode'] != 'case' or
            any(not isinstance(req[key], str) or not re.fullmatch(r'[0-9a-f]{64}', req[key]) for key in fields)):
        raise ValueError('invalid launch expectations')
    card = json.loads((ROOT / 'sealed' / job['card']).read_text())
    if card.get('sha256') != generation or generation != req['expected_generation']:
        raise ValueError('recovery generation changed')
    if recovery_conditions_digest(card) != req['expected_recovery_config_sha256']:
        raise ValueError('recovery conditions changed')
    exact = lambda values: {name: (data.get('model'), data.get('effort')) for name, data in values.items()}
    if exact(card['roles']) != exact(job['roles']): raise ValueError('exact recovery role changed')
    if explicit_pause(card):
        from free_models import approved_pause
        if not approved_pause(card, job['args'][1:]): raise ValueError('explicit pause requires deliberate resume')


def request(payload):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(60 if payload.get('op') == 'launch' else 5)
        client.connect(str(SOCKET))
        client.sendall(json.dumps(payload).encode() + b'\n')
        data = bytearray()
        while not data.endswith(b'\n') and len(data) < 16384:
            part = client.recv(4096)
            if not part:
                break
            data.extend(part)
    return json.loads(data)


def same_roles(roles):
    """Roles by family, model name and effort: the route (openrouter/xiaomi/…, opencode-go/…) may change (2026-10-19)."""
    if not isinstance(roles, dict): return roles
    return {r: (v.get('family'), str(v.get('model', '')).rsplit('/', 1)[-1], v.get('effort')) for r, v in roles.items() if isinstance(v, dict)}


def current_generation(job):
    card_path = ROOT / 'sealed' / job['card']
    card = json.loads(card_path.read_text())
    if card.get('terminal_stop') == 'ttl_retired':
        from ttl_continuation import ready
        ready(ROOT, job, card)
    sealed_audit = job["mode"] in ("fairness", "rehearsal")
    if sealed_audit:
        from sealed_audit import verify_source
        verify_source(card, job["case"])
    if card.get('case') != job['case'] or (not sealed_audit and card.get('status') != 'stopped' and card.get('failed_gate') not in job.get('allow_failed_gates', [])):
        raise ValueError('recovery requires a stopped current case')
    if same_roles(card.get('roles')) != same_roles(job['roles']):
        raise ValueError('recorded model roles changed')
    rereview = False
    if job['mode'] == 'review':
        if card.get('kind') != 'g11-independent-review' or card.get('inputs_unchanged') is not True:
            raise ValueError('review checkpoint is not eligible')
        limits = card.get('limits') or {}
        if (type(limits.get('max_role_calls')) is not int or type(card.get('calls_delta')) is not int or
                card['calls_delta'] < 0 or card['calls_delta'] >= limits['max_role_calls']):
            raise ValueError('original audit role allowance exhausted or invalid')
    elif sealed_audit or card.get('failed_gate') in job.get('allow_failed_gates', []):
        pass  # founder 2026-10-18: repair failed cases (writer fixes the gate's findings, all gates rerun)
    else:
        rereview = require_holder_stop(card, job['args'], job['mode'])
    budget = card.get('continuation_budget') or {}
    calls, cost = budget.get('calls'), budget.get('cost')
    if (type(calls) is not int or calls < 0 or type(cost) not in (int, float) or
            not math.isfinite(cost) or cost < 0 or not isinstance(budget.get('events'), list) or
            budget.get('active') or card.get('checkpoint_error') or
            calls >= job['max_calls'] or cost >= job['max_cost']):
        raise ValueError('invalid, active or exhausted original recovery allowance')
    repair = bool(card.get('failed_gate')) and card['failed_gate'] in job.get('allow_failed_gates', [])
    if (not sealed_audit and not repair and
            not ledger_agrees(card, route='holder', mode=job['mode'], rereview=rereview) and
            not concurrent_peer_cancel(card, budget, job)):
        raise ValueError('scorecard and ledger stop reasons disagree')
    candidates = [ROOT / 'sealed' / (job['archive_prefix'] + suffix) for suffix in ('.tar.gz.age', '.checkpoint.tar.gz.age')]
    final, checkpoint = candidates
    # Match launch.sh exactly: a review uses final; a case uses checkpoint unless final is newer.
    p = final if sealed_audit or job['mode'] == 'review' or not checkpoint.is_file() or (final.is_file() and final.stat().st_mtime_ns > checkpoint.stat().st_mtime_ns) else checkpoint
    if p.is_file() and not p.is_symlink():
        h = hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        if h.hexdigest() == card.get('sha256'):
            return card['sha256']
    raise ValueError('current encrypted archive is not verified')


def collected_successor(job, generation, receipt, state):
    """Resolve an old controller receipt only from a verified newer collected generation.

    The original reservation remains consumed. A missing worker or an unchanged
    archive alone cannot resolve an uncertain start.
    """
    if job.get('ttl_continuation'):
        from ttl_continuation import successor
        return successor(ROOT, job, generation, receipt)
    if (job.get('allow_collected_generation_reconciliation') is not True or
            receipt.get('case') != job['case'] or receipt.get('generation') == generation):
        return None
    workers = [w for w in state.get('workers', []) if w.get('case') == job['case']]
    if not workers or any(not w.get('retired') for w in workers): return None
    card = json.loads((ROOT/'sealed'/job['card']).read_text())
    budget = card.get('continuation_budget') or {}
    calls, cost = budget.get('calls'), budget.get('cost')
    if (card.get('case') != job['case'] or card.get('sha256') != generation or type(calls) is not int or
            type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0 or
            type(receipt.get('at')) not in (int, float) or not math.isfinite(receipt['at'])): return None
    baseline = receipt if 'budget_calls' in receipt and 'budget_cost' in receipt else (job.get('legacy_generation_budgets') or {}).get(receipt.get('generation'), {})
    if type(baseline.get('budget_calls')) is not int or type(baseline.get('budget_cost')) not in (int, float): return None
    floors = [(baseline['budget_calls'], baseline['budget_cost'])]
    proof = None
    for worker in workers:
        term = worker.get('terminal') or {}
        floors.append((term.get('cumulative_calls', 0), term.get('cumulative_cost', 0)))
        for observed in (worker.get('observed') or {}).get('work', []):
            if observed.get('case') == job['case']:
                old = observed.get('budget') or {}; floors.append((old.get('calls', 0), old.get('cost', 0)))
        try: stamp = datetime.datetime.fromisoformat(term['card_mtime_utc'].replace('Z', '+00:00')).timestamp()
        except (KeyError, ValueError, TypeError): continue
        if (term.get('retired') is True and term.get('archive_verified') is True and
                term.get('expected_archive_sha256') == generation and stamp >= receipt['at']):
            proof = worker.get('id')
    if any(type(n) is not int or n < 0 or type(c) not in (int, float) or not math.isfinite(c) or c < 0 or
           calls < n or cost + 1e-9 < c for n, c in floors): return None
    return proof


def peer_is_owner(conn):
    if hasattr(conn, 'getpeereid'):
        return conn.getpeereid()[0] == os.getuid()
    if hasattr(socket, 'SO_PEERCRED'):
        return struct.unpack('3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1] == os.getuid()
    # Darwin Python does not expose getpeereid on every build.
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    libc = ctypes.CDLL(None)
    return libc.getpeereid(conn.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0 and uid.value == os.getuid()


def serve(policy_path, hours, identity_file=None):
    deadline = time.monotonic() + hours * 3600
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    policy = policy_load(policy_path)
    secure_directory(RUNTIME)
    lock_fd = os.open(RUNTIME/'holder.lock', os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if SOCKET.is_symlink(): raise ValueError('unsafe socket')
    SOCKET.unlink(missing_ok=True)
    raw = read_control_identity(identity_file) if identity_file else bytearray(sys.stdin.buffer.read(256))
    if not re.fullmatch(rb'AGE-SECRET-KEY-1[0-9A-Z]+\n?', raw):
        raise ValueError('invalid identity input')
    key = mmap.mmap(-1, mmap.PAGESIZE)
    key[:len(raw)] = raw
    length = len(raw)
    raw[:] = b'\0' * length
    address = ctypes.addressof(ctypes.c_char.from_buffer(key))
    libc = ctypes.CDLL(None)
    if libc.mlock(ctypes.c_void_p(address), mmap.PAGESIZE) != 0:
        key[:] = b'\0' * mmap.PAGESIZE
        raise ValueError('could not lock identity memory')
    # Only a public recipient is returned by age-keygen; no real archive is opened.
    verify = subprocess.Popen(['age-keygen', '-y'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    key_view = memoryview(key)[:length]
    try:
        public, _ = verify.communicate(key_view, timeout=5)
    except subprocess.TimeoutExpired:
        verify.kill(); verify.wait()
        key[:] = b'\0' * mmap.PAGESIZE
        raise ValueError('identity verification timed out')
    finally:
        key_view.release()
    recipient = public.strip().decode('ascii')
    if verify.returncode != 0 or (not identity_file and recipient != policy['recipient']):
        key[:] = b'\0' * mmap.PAGESIZE
        raise ValueError('identity does not match the experiment recipient')
    receipts_path = RUNTIME/'reservations.json'
    if receipts_path.is_symlink(): raise ValueError('unsafe reservation file')
    receipts = json.loads(receipts_path.read_text()) if receipts_path.exists() else []
    # Launches the policy explains: listed generations, or any recorded before the policy was written (resolved_before).
    def resolved(v): return v.get('generation') in policy.get('resolved_generations', {}) or v.get('at', 0) < policy.get('resolved_before', 0)
    job_case = {}
    jobs = {}; consumed = {(v['case'], v['generation']) for v in receipts if not resolved(v)}
    account_labels = None
    control_identity = bool(identity_file) and recipient != policy['recipient']
    secrets_file = pathlib.Path(os.environ.get('UNBUG_SECRETS_FILE', str(pathlib.Path.home()/'.config/unbug-bench/secrets.age')))
    def save_receipts():
        with tempfile.NamedTemporaryFile('w', dir=RUNTIME, delete=False) as f:
            json.dump(receipts, f); f.flush(); os.fsync(f.fileno())
        os.replace(f.name, receipts_path)
    def reap():
        changed = False
        for p in jobs.values():
            code = p.poll()
            if code is None: continue
            for row in receipts:
                if row.get('pid') == p.pid and 'exit' not in row:
                    row.update(exit=code, completed_ok=code == 0); changed = True
        if changed: save_receipts()
    log_dir = RUNTIME / 'jobs'; secure_directory(log_dir)
    def stop(*_):
        nonlocal deadline
        deadline = 0
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGHUP, signal.SIG_IGN)
    awake = subprocess.Popen(['/usr/bin/caffeinate', '-i', '-w', str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) if sys.platform == 'darwin' else None
    try:
        if identity_file or any(job.get('opencode_accounts') or job.get('claude_accounts') for job in policy['jobs'].values()):
            key_view = memoryview(key)[:length]
            try: account_labels = secret_labels(key_view, secrets_file)
            finally: key_view.release()
        with socket.socket(socket.AF_UNIX) as server:
            server.bind(str(SOCKET)); os.chmod(SOCKET, 0o600); server.listen(4); server.settimeout(1)
            while time.monotonic() < deadline:
                try: conn, _ = server.accept()
                except socket.timeout: continue
                with conn:
                    conn.settimeout(5)
                    try:
                        if not peer_is_owner(conn): raise ValueError('unauthorized local peer')
                        data = bytearray()
                        while not data.endswith(b'\n') and len(data) <= 8192:
                            part = conn.recv(1024)
                            if not part: break
                            data.extend(part)
                        if len(data) > 8192: raise ValueError('request too large')
                        req = json.loads(data)
                        reap()
                        if req == {'op': 'status'}:
                            result = {'unlocked': True, 'policy_sha256': policy_digest(policy), 'seconds_remaining': max(0, int(deadline-time.monotonic())), 'jobs': {name: {'pid': p.pid, 'exit': p.poll()} for name, p in jobs.items()}}
                            if account_labels is not None:
                                result['opencode_accounts'] = {str(n): label in account_labels for n, label in OPENCODE_ACCOUNTS.items()}
                                result['claude_accounts'] = {str(n): label in account_labels for n, label in CLAUDE_ACCOUNTS.items()}
                        elif req == {'op': 'stop'}:
                            stop(); result = {'stopping': True}
                        elif req == {'op': 'launch', 'resume_launches': True}:
                            if fingerprint(ROOT) != policy['code_sha256']: raise ValueError('trusted launcher code changed')
                            pending = []; refused = []
                            for row in receipts:
                                launch_id = row.get('launch_id')
                                if not launch_id: continue  # Legacy launches require manual reconciliation.
                                if not re.fullmatch(r'[0-9a-f]{32}', launch_id): raise ValueError('invalid reserved launch')
                                state = CONTROL_HOME/'launches'/launch_id
                                if (state/'complete').exists() or not (state/'monitor.sh').is_file(): continue
                                with (state/'controller.lock').open('a+') as lock:
                                    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                    except BlockingIOError: continue
                                    # Live controllers need no resume, even under an older policy.
                                    # Orphans fail closed individually so other reservations can resume.
                                    try:
                                        unchanged = (row.get('policy_sha256') == policy_digest(policy) and
                                                     row.get('policy_job') in policy['jobs'] and
                                                     json.loads((state/'launch.json').read_text()) == row['launch'])
                                    except (OSError, ValueError, KeyError, TypeError):
                                        unchanged = False
                                    if not unchanged:
                                        refused.append({'launch_id': launch_id, 'error': 'reserved launch policy or routing changed'})
                                        continue
                                pending.append((row, launch_id))
                            for row, launch_id in pending:
                                name = 'resume-' + launch_id
                                env = {'PATH': policy['path'], 'HOME': str(pathlib.Path.home()),
                                       'USER': os.environ.get('USER', ''), 'UNBUG_CONTROL_HOME': str(CONTROL_HOME)}
                                log = log_dir/(name + '-' + str(time.time_ns()) + '.log')
                                with log.open('xb') as output:
                                    p = subprocess.Popen(['/bin/sh', str(ROOT/'factory/launch.sh'), '--resume-launch', launch_id],
                                                         stdin=subprocess.PIPE, stdout=output, stderr=output, cwd=ROOT, env=env, start_new_session=True)
                                jobs[name] = p; job_case[name] = row['case']
                                row.update(pid=p.pid, completed_ok=False); row.pop('exit', None); save_receipts()
                                p.stdin.write(memoryview(key)[:length]); p.stdin.close()
                            result = {'resumed': len(pending), 'refused': refused}
                        elif set(req) - {'opencode_account', 'claude_account', 'case', 'machine', 'expected_generation', 'expected_recovery_config_sha256', 'additional_attempt_generation'} == {'op', 'job'} and req['op'] == 'launch':
                            name = req['job']; job = policy['jobs'][name]
                            if control_identity and job['mode'] != 'new':
                                conn.sendall(json.dumps({'error': 'founder identity required to restore a checkpoint onto a new worker'}).encode() + b'\n')
                                continue
                            if job['mode'] == 'any':  # bind the template to one collected case
                                case = req.get('case')
                                if not isinstance(case, str) or not re.fullmatch(r'case-[A-Za-z0-9-]+', case): raise ValueError('any-case job needs a case id')
                                card = json.loads((ROOT / 'sealed' / f'{case}.scorecard.json').read_text())
                                gates = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8', 'G9', 'G10', 'G11', 'G13', 'G14', 'G15']
                                job = {**job, 'mode': 'case', 'case': case, 'card': f'{case}.scorecard.json', 'archive_prefix': case,
                                       'roles': card.get('roles'), 'allow_failed_gates': gates,
                                       'args': ['1', '--restore', case, '--source', str(card['source']), '--rotation-slot', str(card['rotation_slot']),
                                                *job['args'], *(['--skip-build'] if job['variant'] == 'rerun' else [])]}
                                name = f"{name}-{case[-6:]}"
                            elif 'case' in req: raise ValueError('only any-case jobs take a case id')
                            public_card = json.loads((ROOT / 'sealed' / job['card']).read_text()) if job['mode'] == 'case' else {}
                            from account_handoff import launch_accounts
                            account, claude_account, account_state = launch_accounts(public_card, job, req, account_labels or set())
                            if ('opencode_account' in req and not job.get('opencode_accounts')) or (job.get('opencode_accounts') and (type(account) is not int or account not in job['opencode_accounts'] or OPENCODE_ACCOUNTS[account] not in (account_labels or set()))):
                                raise ValueError('approved OpenCode account unavailable')

                            if type(claude_account) is not int or (claude_account != 1 and claude_account not in job.get('claude_accounts', [])) or (
                                    claude_account != 1 and CLAUDE_ACCOUNTS[claude_account] not in (account_labels or set())):
                                raise ValueError('approved Claude account unavailable')
                            if any(p.poll() is None and job_case.get(n) == job['case'] for n, p in jobs.items()): raise ValueError('case recovery already active')
                            if fingerprint(ROOT) != policy['code_sha256']: raise ValueError('trusted launcher code changed')
                            inventory = subprocess.run([str(ROOT/'bin/boat-call'), 'list', '--json'], capture_output=True, text=True, timeout=25)
                            if inventory.returncode: raise ValueError('cannot verify current workers')
                            fleet = json.loads(inventory.stdout)
                            if (not isinstance(fleet.get('sandboxes'), list) or
                                    not isinstance(fleet.get('pageInfo'), dict) or fleet['pageInfo'].get('hasMore') is not False or
                                    any(not isinstance(v, dict) or not isinstance(v.get('id'), str) for v in fleet['sandboxes'])):
                                raise ValueError('worker inventory is incomplete or malformed')
                            known = set(job.get('known_worker_ids', []))
                            state_path = ROOT/'results/infrastructure/2026-10-18-claude-return/monitor-state.json'
                            if state_path.is_file():
                                known.update(v['id'] for v in json.loads(state_path.read_text()).get('workers', []) if v.get('case') == job['case'])
                            if any(v['id'] in known or (v.get('name', '').startswith('factory:') and v.get('name', '').endswith(job['case'].rsplit('-', 1)[-1])) for v in fleet['sandboxes']):
                                raise ValueError('case worker already exists')
                            if job['mode'] == 'new':
                                if sum(v.get('job') == name and not resolved(v) for v in receipts) >= 3: raise ValueError('new-case job launched 3 times')
                                generation = 'new'
                            else: generation = current_generation(job)
                            stamp = (job['case'], generation)
                            if job.get('ttl_continuation'):
                                from ttl_continuation import admit
                                ttl_card = json.loads((ROOT/'sealed'/job['card']).read_text())
                                admit(ROOT, job, ttl_card, generation, req, receipts, consumed)
                            # 2026-10-19: a launch that failed (boat SSH resets while uploading) may be retried; the cap is 3 launches
                            # per case since this policy, never two at once. The run's own ledger keeps the cumulative budget.
                            if policy.get('retry_failed_launches') is not True and job['mode'] != 'new' and stamp in consumed: raise ValueError('checkpoint already used; reconcile before retrying')
                            state = json.loads(state_path.read_text()) if state_path.is_file() else {}
                            for row in receipts:
                                if row['case'] != job['case'] or row.get('completed_ok') or row.get('resolved_by_verified_generation'): continue
                                proof = collected_successor(job, generation, row, state)
                                if proof:
                                    row.update(resolved_by_verified_generation=generation, resolved_worker_id=proof, resolved_at=time.time())
                                    save_receipts()
                            # resolved_generations: earlier failed launches the policy explains and clears (2026-10-19), visible in the policy file.
                            if policy.get('retry_failed_launches') is not True and any(v['case'] == job['case'] and not v.get('completed_ok') and not v.get('resolved_by_verified_generation')
                                   and not resolved(v) for v in receipts):
                                raise ValueError('previous recovery outcome requires reconciliation')
                            additional_attempt = admit_attempt(job, generation, req, receipts,
                                sum(v['case'] == job['case'] and not resolved(v) for v in receipts))
                            attest_launch(job, generation, req)  # serialized with reservation; a stale coordinator cannot change the restore target
                            consumed.add(stamp)  # reserve before any uncertain process start
                            budget = {'calls': 0, 'cost': 0} if job['mode'] == 'new' else json.loads((ROOT/'sealed'/job['card']).read_text())['continuation_budget']
                            receipts.append({'case': job['case'], 'job': name, 'generation': generation, 'at': time.time(), 'completed_ok': False,
                                             'budget_calls': budget['calls'], 'budget_cost': budget['cost'], 'opencode_account': account,
                                             'claude_account': claude_account})
                            if additional_attempt is not None:
                                receipts[-1]['additional_attempt'] = additional_attempt
                            save_receipts()
                            log = log_dir / (name + '-' + str(time.time_ns()) + '.log')
                            fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                            env = {'BOAT_COMMAND_TIMEOUT_SECONDS': '120', 'PATH': policy['path'], 'HOME': str(pathlib.Path.home()), 'USER': os.environ.get('USER', ''), 'LANG': 'en_US.UTF-8', 'UNBUG_CLOUD': 'boat', 'BOAT_TYPE': 'default'}
                            env.update(UNBUG_SECRETS_FILE=str(secrets_file), UNBUG_CONTROL_HOME=str(CONTROL_HOME), UNBUG_LAUNCH_ID=uuid.uuid4().hex)
                            if job.get('ttl_continuation'): env['FACTORY_TTL_CONTINUATION'] = json.dumps(job)
                            if account is not None: env['OPENCODE_SECRET_NAME'] = OPENCODE_ACCOUNTS[account]
                            env['CLAUDE_SECRET_NAME'] = CLAUDE_ACCOUNTS[claude_account]
                            env['FACTORY_ACCOUNT_POLICY'] = json.dumps({p + '_accounts': job.get(p + '_accounts', []) for p in ('opencode', 'claude')}, sort_keys=True)
                            env['FACTORY_ACCOUNT_STATE'] = json.dumps(account_state, sort_keys=True)
                            # 2026-10-20: large (8 vCPU, 16 GB, 2x rate) fits the G10 testers beside the bench gates.
                            if req.get('machine', 'default') not in ('default', 'large'): raise ValueError('unapproved machine size')
                            env['BOAT_TYPE'] = req.get('machine', 'default')
                            from control_resume import ENVIRONMENT
                            receipts[-1].update(launch_id=env['UNBUG_LAUNCH_ID'], policy_job=req['job'], policy_sha256=policy_digest(policy),
                                                launch={'argv': job['args'], 'environment': {k:env[k] for k in ENVIRONMENT if k in env}})
                            save_receipts()
                            with os.fdopen(fd, 'wb') as output:
                                p = subprocess.Popen(['/bin/sh', str(ROOT/'factory/launch.sh'), *job['args']], stdin=subprocess.PIPE, stdout=output, stderr=output, cwd=ROOT, env=env, start_new_session=True)
                            jobs[name] = p; job_case[name] = job['case']
                            receipts[-1]['pid'] = p.pid; save_receipts()
                            p.stdin.write(memoryview(key)[:length]); p.stdin.close()
                            result = {'started': True, 'job': name, 'pid': p.pid}
                        else: raise ValueError('operation not allowed')
                    except Exception:
                        result = {'error': 'request refused; no key or private output returned'}
                    try: conn.sendall(json.dumps(result).encode() + b'\n')
                    except OSError: pass
    finally:
        key[:] = b'\0' * mmap.PAGESIZE
        libc.munlock(ctypes.c_void_p(address), mmap.PAGESIZE); key.close()
        SOCKET.unlink(missing_ok=True)
        if awake: awake.terminate()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('op', choices=['unlock', 'serve', 'status', 'stop', 'launch'])
    parser.add_argument('--policy', type=pathlib.Path)
    parser.add_argument('--identity-file', type=pathlib.Path, help='serve: control age key in an owner-only 0600 file')
    parser.add_argument('--hours', type=float, default=24)
    parser.add_argument('--job')
    parser.add_argument('--resume-launches', action='store_true', help='launch: resume reserved orphan controllers without another job attempt')
    parser.add_argument('--opencode-account', type=int, choices=[1, 2])
    parser.add_argument('--claude-account', type=int, choices=[1, 2, 3])
    parser.add_argument('--machine', choices=['default', 'large'])
    parser.add_argument('--case', help='case id for an any-case (repair/rerun) job')
    parser.add_argument('--expected-generation', help='coordinator: exact collected encrypted archive digest')
    parser.add_argument('--expected-recovery-config-sha256', help='coordinator: exact model, original-conditions and cumulative-usage digest')
    parser.add_argument('--additional-attempt-generation', help='manual opt-in to a policy-authorized additional attempt on this exact ciphertext digest')
    parser.add_argument('--start', nargs='*', default=[])
    args = parser.parse_args()
    if args.identity_file and args.op != 'serve': parser.error('--identity-file requires serve')
    if args.resume_launches and (args.op != 'launch' or args.job or args.case or args.machine or args.opencode_account is not None or args.claude_account is not None or args.expected_generation or args.expected_recovery_config_sha256 or args.additional_attempt_generation):
        parser.error('--resume-launches requires launch without job overrides')
    if args.opencode_account is not None and args.op != 'launch': parser.error('--opencode-account requires launch')
    if args.claude_account is not None and args.op != 'launch': parser.error('--claude-account requires launch')
    if not 0 < args.hours <= 24: parser.error('maximum key-holder lifetime is 24 hours')
    if args.op in ('serve', 'unlock') and not args.policy: parser.error('--policy is required')
    if args.op == 'serve': serve(args.policy.resolve(), args.hours, args.identity_file)
    elif args.op == 'unlock':
        if not sys.stdin.isatty(): raise ValueError('unlock requires your local terminal')
        requested_policy = policy_load(args.policy.resolve()); secure_directory(RUNTIME)
        try: status = request({'op':'status'})
        except (OSError, ValueError):
            status = None
            if SOCKET.exists(): raise ValueError('existing holder is unconfirmed; do not enter another key')
        if status:
            if status.get('policy_sha256') != policy_digest(requested_policy): raise ValueError('active key holder has a different policy')
            print(json.dumps(status))
            for name in args.start: print(json.dumps(request({'op':'launch', 'job':name})))
            return
        secret = bytearray(getpass.getpass('Founder AGE private key (hidden; stays local): ').strip().encode() + b'\n')
        p = subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), 'serve', '--policy', str(args.policy.resolve()), '--hours', str(args.hours)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        p.stdin.write(secret); p.stdin.close(); secret[:] = b'\0' * len(secret)
        try:
            status = None
            for _ in range(400):
                if p.poll() is not None: raise ValueError('unlock failed; check identity and local memory-lock support')
                try: status = request({'op':'status'}); break
                except (OSError, ValueError): time.sleep(.1)
            if not status: raise ValueError('key holder startup unconfirmed')
        except BaseException:
            p.terminate(); p.wait(timeout=10)
            raise
        print(json.dumps(status))
        # A launch timeout is uncertain; never reprompt or silently retry it.
        for name in args.start: print(json.dumps(request({'op':'launch', 'job':name})))
    else:
        if args.op == 'launch' and args.resume_launches:
            print(json.dumps(request({'op': 'launch', 'resume_launches': True})))
            return
        if args.op == 'launch' and not args.job: parser.error('--job is required')
        extra = {'opencode_account': args.opencode_account} if args.opencode_account is not None else {}
        if args.case: extra['case'] = args.case
        if args.claude_account is not None: extra['claude_account'] = args.claude_account
        if args.machine: extra['machine'] = args.machine
        if args.expected_generation: extra['expected_generation'] = args.expected_generation
        if args.expected_recovery_config_sha256: extra['expected_recovery_config_sha256'] = args.expected_recovery_config_sha256
        if args.additional_attempt_generation: extra['additional_attempt_generation'] = args.additional_attempt_generation
        if extra and args.op != 'launch': parser.error('--opencode-account requires launch')
        print(json.dumps(request({'op':args.op, **({'job':args.job, **extra} if args.op=='launch' else {})})))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError):
        print('Key holder operation failed; no secret was printed.', file=sys.stderr)
        sys.exit(1)
