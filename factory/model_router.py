"""Batch-wide model admission. Public metadata only; the control VM owns SQLite.

No model or credential transport lives here. Tests may inject _rpc; production
callers always use authenticated HTTP and the same await_lease seam.
"""
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import hmac
import json
import math
import os
import re
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

from budget import BudgetError

WAIT_SECONDS, RENEW_SECONDS, LEASE_SECONDS = 60, 60, 180
SECRETS = Path('/dev/shm/secrets')
ACCOUNTS = ('claude-token', 'claude-factory-token-2', 'opencode-go-key',
            'opencode-go-key-2', 'codex-auth.json', 'openrouter-key')
CHAINS = (
    ('opencode/deepseek-v4.1-flash-free', 'openrouter/deepseek/deepseek-v4.1-flash'),
    ('opencode/minimax-m3.1-flash-free', 'openrouter/minimax/minimax-m3.1-flash:free'),
    ('opencode-go/mimo-v2.6-pro', 'openrouter/xiaomi/mimo-v2.6-pro'),
    ('opencode-go/muse-spark-1.3-contributor', 'openrouter/meta/muse-spark-1.3-contributor'),
    ('opencode/glm-5.3-flash-free', 'opencode-go/glm-5.3-flash'),
)
REASONS = {'quota', 'rate', 'credit', 'outage', 'router_unavailable', 'credential_expiring'}


def family(model):
    if model.startswith(('claude/', 'anthropic/')) or '/anthropic/' in model: return 'anthropic'
    if model.startswith(('codex/', 'openai/')) or '/openai/' in model: return 'openai'
    for name, result in (('minimax', 'minimax'), ('deepseek', 'deepseek'), ('mimo', 'xiaomi'),
                         ('muse-spark', 'meta'), ('grok', 'xai'), ('qwen', 'alibaba'), ('glm', 'z-ai')):
        if name in model.lower(): return result
    return model.split('/')[1 if model.startswith('openrouter/') else 0]


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def epoch(value):
    if finite(value): return value
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def retry_at(reason, *, now=None, failures=1, reset_at=None):
    now = time.time() if now is None else now
    if finite(reset_at) and reset_at > now: return reset_at
    delay = 300 if reason == 'router_unavailable' and failures == 1 else min(3600, 900 * 2 ** min(max(failures - 1, 0), 2))
    return now + delay


def routes(model, accounts=ACCOUNTS):
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,200}', model) or '/' not in model:
        raise ValueError('invalid requested model')
    if any(a not in ACCOUNTS for a in accounts): raise ValueError('unapproved account')
    if model == 'opencode-go/deepseek-v4.1-flash': model = CHAINS[0][0]
    chain = next((list(c) if c[0] == model else [model, c[0]] for c in CHAINS if model in c), [model])
    result = []
    for route in chain:
        billing = ('subscription' if route.startswith(('claude/', 'codex/', 'opencode-go/')) else
                   'free' if route.endswith(('-free', ':free')) else 'paid')
        labels = (ACCOUNTS[:2] if route.startswith('claude/') else ('codex-auth.json',) if route.startswith('codex/') else
                  ('openrouter-key',) if route.startswith('openrouter/') else
                  ACCOUNTS[2:4] if route.startswith('opencode-go/') or 'minimax-m3.1-flash-free' in route
                  or (route.startswith('opencode/') and billing == 'paid') else (None,))
        if labels != (None,): labels = tuple(a for a in accounts if a in labels)
        for account in labels:
            if account is not None and account not in accounts: continue
            result.append(dict(route=route, account=account, billing=billing, family=family(route),
                               pool=account or ('opencode-free' if billing == 'free' else 'provider:' + route.partition('/')[0])))
    if any(r['family'] != family(model) for r in result): raise ValueError('fallback changed family')
    return result


@dataclass(frozen=True)
class Lease:
    lease_id: str
    route: str
    account: str | None
    expires_at: float
    billing: str
    family: str
    pool: str


@dataclass(frozen=True)
class Wait:
    reason: str
    retry_after: float
    evidence: str = 'denied_before_work'
    route: str | None = None
    account: str | None = None
    lease_id: str | None = None
    call_id: str | None = None


class ProviderWait(BudgetError):
    def __init__(self, role, wait):
        super().__init__('provider_wait')
        self.role, self.wait = role, wait


class RouterUnavailable(RuntimeError):
    pass


class Store:
    """One short SQLite transaction per RPC; no process-local availability cache."""
    def __init__(self, path, *, capacities=None, accounts=ACCOUNTS, clock=time.time):
        self.path, self.clock = str(path), clock
        self.capacities, self.accounts = capacities or {}, tuple(accounts)
        if any(a not in ACCOUNTS for a in self.accounts): raise ValueError('unapproved account')
        if any(type(n) is not int or not 0 <= n <= 100 for n in self.capacities.values()):
            raise ValueError('invalid lane capacity')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, payload TEXT, created REAL, seen REAL);'
                             'CREATE TABLE IF NOT EXISTS leases (id TEXT PRIMARY KEY, route TEXT, expires REAL, outcome TEXT, receipt TEXT);'
                             'CREATE TABLE IF NOT EXISTS health (pool TEXT PRIMARY KEY, value TEXT);'
                             'CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY);')
            if 'seen' not in {row[1] for row in db.execute('PRAGMA table_info(requests)')}:
                db.execute('ALTER TABLE requests ADD COLUMN seen REAL NOT NULL DEFAULT 0')

    def rpc(self, operation, data):
        now = self.clock()
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE leases SET outcome='expired' WHERE outcome IS NULL AND expires<=?", (now,))
            health = {k: json.loads(v) for k, v in db.execute('SELECT pool,value FROM health')}
            for key, value in health.items():
                if value.get('reason') not in ('credit', 'credential_expiring') and value.get('blocked_until', 0) <= now:
                    value['blocked_until'] = 0
            def save_health():
                for key, value in health.items():
                    db.execute('INSERT OR REPLACE INTO health VALUES (?,?)', (key, json.dumps(value)))
            def blocked(route):
                values = [health.get(route['pool'], {}), health.get(route['pool'] + '/' + route['route'], {})]
                return next((v for v in values if v.get('reason') in ('credit', 'credential_expiring') or v.get('blocked_until', 0) > now), None)
            def free(route):
                occupied = sum(json.loads(r)['pool'] == route['pool'] for (r,) in db.execute('SELECT route FROM leases WHERE outcome IS NULL'))
                return 0 if blocked(route) else max(0, self.capacities.get(route['pool'], 1) - occupied)
            result = None
            if operation == 'status':
                result = dict(observed_at=now, health=health, leases=[dict(lease_id=i, **json.loads(r), expires_at=e)
                    for i, r, e in db.execute('SELECT id,route,expires FROM leases WHERE outcome IS NULL')])
            elif operation == 'capacity':
                choices = [r for r in routes(data['route'], self.accounts) if r['route'] == data['route']]
                # Alternatives sharing a wallet/account do not create extra capacity.
                pools = {r['pool']: free(r) for r in choices}
                result = {'slots': sum(pools.values())}
            elif operation == 'cancel':
                identity = data['id']
                if not re.fullmatch(r'[a-f0-9]{32}', identity): raise ValueError('invalid attempt id')
                tombstone = json.dumps(dict(deadline=0, accounts=[], model='opencode/cancelled', id=identity))
                db.execute('INSERT OR REPLACE INTO requests VALUES (?,?,?,?)', (identity, tombstone, now, now))
                db.execute("UPDATE leases SET outcome='denied' WHERE id=? AND outcome IS NULL", (identity,))
                result = {'cancelled': True}
            elif operation == 'acquire':
                if set(data) - {'excluded_lanes'} != {'id', 'model', 'accounts', 'role', 'deadline'}: raise ValueError('invalid admission fields')
                if not isinstance(data['role'], str) or not re.fullmatch(r'[a-z_0-9]{1,40}', data['role']): raise ValueError('invalid role')
                identity = data['id']
                if not re.fullmatch(r'[a-f0-9]{32}', identity): raise ValueError('invalid attempt id')
                if not finite(data['deadline']) or not now < data['deadline']: raise ValueError('expired admission deadline')
                choices = [r for r in routes(data['model'], [a for a in data['accounts'] if a in self.accounts])
                           if r['pool'] + '/' + r['route'] not in data.get('excluded_lanes', [])]
                payload = json.dumps(data, sort_keys=True, allow_nan=False)
                previous = db.execute('SELECT payload FROM requests WHERE id=?', (identity,)).fetchone()
                if previous and previous[0] != payload: raise ValueError('attempt id changed')
                db.execute('INSERT OR IGNORE INTO requests VALUES (?,?,?,?)', (identity, payload, now, now))
                db.execute('UPDATE requests SET seen=? WHERE id=?', (now, identity))
                lease = db.execute('SELECT route,expires,outcome FROM leases WHERE id=?', (identity,)).fetchone()
                if lease:
                    if lease[2] is not None: raise ValueError('closed lease cannot be replayed')
                    result = dict(kind='lease', lease_id=identity, **json.loads(lease[0]), expires_at=lease[1])
                else:
                    order = db.execute('SELECT rowid FROM requests WHERE id=?', (identity,)).fetchone()[0]
                    older = [json.loads(p) for (p,) in db.execute('SELECT payload FROM requests WHERE rowid<? AND seen>? ORDER BY rowid', (order, now - LEASE_SECONDS))
                             if json.loads(p)['deadline'] > now and not db.execute('SELECT 1 FROM leases WHERE id=?', (json.loads(p)['id'],)).fetchone()]
                    for route in choices:
                        if not free(route): continue
                        if any(any(r['pool'] == route['pool'] and r['pool'] + '/' + r['route'] not in p.get('excluded_lanes', [])
                                   for r in routes(p['model'], p['accounts'])) for p in older): continue
                        expires = min(now + LEASE_SECONDS, data['deadline'])
                        db.execute('INSERT INTO leases VALUES (?,?,?,NULL,NULL)', (identity, json.dumps(route), expires))
                        result = dict(kind='lease', lease_id=identity, **route, expires_at=expires)
                        break
                    if result is None:
                        alternatives = []
                        active = [(json.loads(r)['pool'], e) for r,e in db.execute('SELECT route,expires FROM leases WHERE outcome IS NULL')]
                        for route in choices:
                            limit = blocked(route)
                            ready = (max(now + 1, limit.get('blocked_until', now + 900)) if limit else
                                     min((e for pool,e in active if pool == route['pool']), default=now + 15))
                            alternatives.append((ready, limit['reason'] if limit else 'rate', route))
                        ready, reason, route = min(alternatives, key=lambda row: row[0]) if alternatives else (now + 900, 'outage', dict(route=data['model'],account=None))
                        result = dict(kind='wait', reason=reason, retry_after=ready, route=route['route'], account=route['account'])
            elif operation in ('renew', 'finish'):
                row = db.execute('SELECT route,expires,outcome,receipt FROM leases WHERE id=?', (data['lease_id'],)).fetchone()
                if not row: raise ValueError('unknown lease')
                if operation == 'renew':
                    if row[2] is not None: raise ValueError('closed lease')
                    request = json.loads(db.execute('SELECT payload FROM requests WHERE id=?', (data['lease_id'],)).fetchone()[0])
                    expires = min(now + LEASE_SECONDS, request['deadline'])
                    db.execute('UPDATE leases SET expires=? WHERE id=?', (expires, data['lease_id']))
                    result = dict(expires_at=expires, **json.loads(row[0]))
                else:
                    if data['outcome'] not in ('done', 'interrupted', 'denied'): raise ValueError('invalid finish outcome')
                    receipt = data.get('receipt')
                    if receipt is not None and (not isinstance(receipt, str) or not re.fullmatch(r'usage-receipts/[a-f0-9-]+\.json', receipt)):
                        raise ValueError('invalid receipt path')
                    if row[2] not in (None, 'expired') and (row[2], row[3]) != (data['outcome'], receipt):
                        raise ValueError('finish changed')
                    db.execute('UPDATE leases SET outcome=?,receipt=? WHERE id=?', (data['outcome'], receipt, data['lease_id']))
                    if data['outcome'] == 'done':
                        route = json.loads(row[0]); old = health.get(route['pool'], {})
                        old['ready_at'] = now
                        if not blocked(route): old.update(failures=0, observed_at=now)
                        health[route['pool']] = old
                    result = {'finished': True}
            elif operation == 'observe':
                identity = data['observation_id']
                if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', identity): raise ValueError('invalid observation id')
                if not db.execute('SELECT 1 FROM observations WHERE id=?', (identity,)).fetchone():
                    if data.get('healthy') is True:
                        pool = data['pool']
                        if pool not in (*self.accounts, 'opencode-free') and not any(
                                key == pool or key.startswith(pool + '/') for key in health):
                            raise ValueError('unapproved pool')
                        for key in list(health):
                            if key == pool or key.startswith(pool + '/'):
                                health[key].update(blocked_until=0, reason=None, observed_at=now, credit='unknown')
                    else:
                        row = db.execute('SELECT route FROM leases WHERE id=?', (data['lease_id'],)).fetchone()
                        if not row: raise ValueError('unknown observation lease')
                        route = json.loads(row[0]); reason = data['reason']
                        if reason not in REASONS: raise ValueError('invalid provider reason')
                        key = route['pool'] + ('/' + route['route'] if reason == 'outage' else '')
                        old = health.get(key, {}); failures = old.get('failures', 0) + 1
                        reset = retry_at(reason, now=now, failures=failures, reset_at=data.get('reset_at'))
                        health[key] = dict(reason=reason, blocked_until=reset, observed_at=now, failures=failures,
                                           credit='denied' if reason == 'credit' else old.get('credit', 'unknown'))
                    db.execute('INSERT INTO observations VALUES (?)', (identity,))
                result = {'observed': True}
            else: raise ValueError('unknown router operation')
            save_health()
            return result


def _rpc(operation, data):
    url, token = os.environ.get('FACTORY_ROUTER_URL', ''), os.environ.get('FACTORY_ROUTER_TOKEN', '')
    parsed = urlsplit(url)
    if not token or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1'))):
        raise RouterUnavailable('router unconfigured')
    request = urllib.request.Request(url.rstrip('/') + '/' + operation, json.dumps(data, allow_nan=False).encode(),
                                     {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.loads(response.read(1024 * 1024))
            if not isinstance(result, dict): raise ValueError('invalid router response')
            return result
    except urllib.error.HTTPError as error:
        error.close()
        raise RouterUnavailable('router response unavailable') from None
    except (OSError, ValueError, urllib.error.URLError):
        raise RouterUnavailable('router response unavailable') from None


def metadata(case):
    batch = getattr(case, 'batch_id', None) or os.environ.get('FACTORY_BATCH_ID')
    job = getattr(case, 'job_id', None) or os.environ.get('FACTORY_JOB_ID')
    value = getattr(case, 'batch_deadline', None) or os.environ.get('FACTORY_BATCH_DEADLINE')
    if not batch or not job or value is None: raise BudgetError('router_batch_unconfigured')
    try: deadline = epoch(value)
    except (ValueError, TypeError, OverflowError): raise BudgetError('router_batch_unconfigured') from None
    if not finite(deadline) or deadline <= time.time(): raise BudgetError('provider_wait_deadline')
    return batch, job, deadline


def _account_order(case):
    from account_handoff import ACCOUNTS as LABELS
    preferred = {LABELS[p].get(n) for p,n in (case.card.get('provider_accounts') or {}).items() if p in LABELS}
    return sorted(getattr(case, 'router_accounts', ACCOUNTS),
                  key=lambda a: (not (SECRETS / a).is_file(), a not in preferred))


def _admit(role, case, deadline, identity, accounts, excluded=()):
    model = getattr(case, 'router_model', None) or case.card['roles'][role]['model']
    data = dict(id=identity, model=model, accounts=list(accounts), deadline=deadline, role=role, excluded_lanes=list(excluded))
    result = _rpc('acquire', data)
    if result.get('kind') == 'lease':
        result.pop('kind')
        allowed = [r for r in routes(model, accounts) if r['pool'] + '/' + r['route'] not in excluded]
        if (result.get('lease_id') != identity or not finite(result.get('expires_at'))
                or result['expires_at'] <= time.time() or result['expires_at'] > deadline
                or {k: result.get(k) for k in ('route', 'account', 'pool', 'family', 'billing')} not in allowed):
            raise RouterUnavailable('invalid lease response')
        return Lease(**result)
    if result.get('kind') != 'wait' or result.get('reason') not in REASONS or not finite(result.get('retry_after')):
        raise RouterUnavailable('invalid admission response')
    result.pop('kind')
    return Wait(**result)


def _credential_ready(lease):
    if lease.account is None: return True
    try:
        raw = (SECRETS / lease.account).read_text()
        if lease.account == 'codex-auth.json':
            from codex_login import worker_auth
            worker_auth(json.loads(raw))
        elif not raw.strip(): return False
    except (OSError, ValueError, KeyError, TypeError): return False
    return True


def _deadlines(case, deadline):
    enabled = os.environ.get('UNBUG_PROVIDER_WAIT', '0') == '1'
    value = getattr(case, 'batch_deadline', None) or os.environ.get('FACTORY_BATCH_DEADLINE')
    batch_end = metadata(case)[2] if enabled else epoch(value) if value is not None else time.time() + 7 * 86400
    stop_at = min(batch_end, time.time() + max(0, deadline - time.monotonic())) if deadline is not None else batch_end
    return enabled, batch_end, stop_at


def _heartbeat(case, seconds):
    if hasattr(case, 'work'): (Path(case.work) / '.router-wait').touch()
    cancel = getattr(case, 'role_cancel', None)
    if cancel is None: time.sleep(seconds)
    else: cancel.wait(seconds)


def _finish_until_known(lease, outcome, receipt, role, case, deadline, *, since=None):
    """Retry one idempotent finish; never rerun completed model work."""
    enabled, batch_end, stop_at = _deadlines(case, deadline)
    started = time.monotonic() if since is None else since
    while True:
        try: return finish(lease.lease_id, outcome, receipt)
        except RouterUnavailable:
            if time.time() >= stop_at and not enabled:
                raise BudgetError('provider_wait_deadline' if time.time() >= batch_end else 'timeout') from None
            if enabled and (time.monotonic() - started >= WAIT_SECONDS or time.time() >= stop_at):
                raise ProviderWait(role, Wait('router_unavailable', retry_at('router_unavailable'),
                    evidence='interrupted', route=lease.route,
                    account=lease.account, lease_id=lease.lease_id, call_id=receipt)) from None
            seconds = min(15, max(.01, stop_at - time.time()))
            if enabled: seconds = min(seconds, max(.01, WAIT_SECONDS - (time.monotonic() - started)))
            # A renewal may have cancelled the old CLI. Cleanup reconciliation
            # still needs a bounded sleep rather than spinning on that event.
            if getattr(case, 'role_cancel', None) is not None and case.role_cancel.is_set():
                if hasattr(case, 'work'): (Path(case.work) / '.router-wait').touch()
                time.sleep(seconds)
            else: _heartbeat(case, seconds)


def await_lease(role, case, deadline=None):
    """The only admission seam, including D's pre-reservation calls.

    deadline is a caller monotonic deadline; the server sees UTC epochs only.
    ProviderWait is handled by run.py's ordinary checkpoint-and-exit path.
    """
    enabled = os.environ.get('UNBUG_PROVIDER_WAIT', '0') == '1'
    model = getattr(case, 'router_model', None) or case.card['roles'][role]['model']
    choices = routes(model, getattr(case, 'router_accounts', ACCOUNTS))  # Configuration errors are not outages.
    exhausted = choices and all(r['pool'] + '/' + r['route'] in getattr(case, 'router_excluded', ()) for r in choices)
    if not enabled and exhausted:
        raise BudgetError('provider_routes_exhausted')
    if hasattr(case, 'work'):
        live = Path(case.work) / 'provider_wait.json'
        if live.is_file():
            record = json.loads(live.read_text())
            if record.get('settled') is not True: raise BudgetError('provider_wait_unsettled')
            identity = str(uuid.UUID(record['wait_id']))
            archive = live.parent / 'provider_waits'
            archive.mkdir(exist_ok=True)
            live.replace(archive / (identity + '.json'))
    enabled, batch_deadline, stop_at = _deadlines(case, deadline)
    identity = uuid.uuid4().hex
    accounts = _account_order(case)  # Frozen for this request ID, including lost replies.
    excluded = tuple(sorted(getattr(case, 'router_excluded', ())))
    started = getattr(case, 'router_condition_since', None) or time.monotonic()
    wait = getattr(case, 'router_wait', None)
    deferred = getattr(case, 'router_deferred', False) or (exhausted and wait is not None)
    while True:
        cancellation = getattr(case, 'role_cancel', None)
        if cancellation is not None and cancellation.is_set(): raise BudgetError('cancelled')
        if time.time() >= stop_at and not enabled:
            try: _rpc('cancel', {'id': identity})
            except RouterUnavailable: pass
            raise BudgetError('provider_wait_deadline' if time.time() >= batch_deadline else 'timeout')
        try:
            if getattr(case, 'router_uncertain', False):
                _rpc('status', {})  # The old CLI is stopped and finish was acknowledged.
                case.router_uncertain = False
            if stop_at <= time.time(): raise RouterUnavailable('admission deadline')
            result = wait if enabled and deferred else _admit(role, case, batch_deadline, identity, accounts, excluded)
            if isinstance(result, Lease):
                if _credential_ready(result): return result
                finish(result.lease_id, 'denied', None)
                result = Wait('credential_expiring', retry_at('credential_expiring'),
                              route=result.route, account=result.account)
                deferred = True
                if not enabled:
                    identity, accounts = uuid.uuid4().hex, _account_order(case)
            wait = Wait(result.reason, result.retry_after,
                        evidence=wait.evidence if wait else result.evidence,
                        route=result.route, account=result.account,
                        lease_id=wait.lease_id if wait else None, call_id=wait.call_id if wait else None)
        except RouterUnavailable:
            wait = Wait('router_unavailable', retry_at('router_unavailable'),
                        evidence=wait.evidence if wait else 'denied_before_work',
                        route=wait.route if wait else getattr(case, 'router_model', None),
                        account=wait.account if wait else None,
                        lease_id=wait.lease_id if wait else None, call_id=wait.call_id if wait else None)
        if enabled and (time.monotonic() - started >= WAIT_SECONDS or time.time() >= stop_at):
            try: _rpc('cancel', {'id': identity})
            except RouterUnavailable:
                case.card.setdefault('router_pending_requests', []).append(identity)
            raise ProviderWait(role, wait)
        seconds = min(15, max(.01, wait.retry_after - time.time()))
        seconds = min(seconds, max(.01, stop_at - time.time()))
        if enabled: seconds = min(seconds, max(.01, WAIT_SECONDS - (time.monotonic() - started)))
        _heartbeat(case, seconds)


def finish(lease_id, outcome, receipt):
    return _rpc('finish', dict(lease_id=lease_id, outcome=outcome, receipt=receipt))


def observe(pool=None, *, healthy=False, observation_id=None, lease=None, reason=None, reset_at=None):
    return _rpc('observe', dict(pool=pool, healthy=healthy, observation_id=observation_id or uuid.uuid4().hex,
                               lease_id=lease.lease_id if lease else None, reason=reason, reset_at=reset_at))


def capacity(route):
    return _rpc('capacity', {'route': route})['slots']


@contextmanager
def running(lease, cancel):
    """Keep ownership alive; uncertain renewal cancels useful work, never retries it."""
    stopped, lost = threading.Event(), threading.Event()
    def renew_once():
        result = _rpc('renew', {'lease_id': lease.lease_id})
        if any(result.get(k) != getattr(lease, k) for k in ('route', 'account', 'pool', 'family', 'billing')):
            raise RouterUnavailable('lease binding changed')
    renew_once()
    def renew():
        while not stopped.wait(RENEW_SECONDS):
            try: renew_once()
            except (RouterUnavailable, ValueError):
                lost.set(); cancel.set(); return
    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try: yield lost
    finally:
        stopped.set(); thread.join(timeout=6)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, store, token):
        if not token: raise ValueError('router token required')
        self.store, self.token = store, token
        super().__init__(address, Handler)
    def handle_error(self, *args): pass

    def enable_tls(self, cert, key):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        # Handshake in each handler thread, never in the single accept loop.
        self.socket = context.wrap_socket(self.socket, server_side=True, do_handshake_on_connect=False)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(5)
        if isinstance(self.request, ssl.SSLSocket): self.request.do_handshake()
        super().setup()
    def log_message(self, *args): pass
    def do_POST(self):
        self.connection.settimeout(5)
        status, value = 400, {'error': 'invalid router request'}
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.token):
            status, value = 403, {'error': 'router authentication required'}
        else:
            try:
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1: raise ValueError()
                size = int(self.headers['Content-Length'])
                if not 0 < size <= 16384: raise ValueError()
                value = self.server.store.rpc(self.path.removeprefix('/'), json.loads(self.rfile.read(size)))
                status = 200
            except (ValueError, KeyError, TypeError, OSError, sqlite3.Error): pass
        encoded = json.dumps(value, allow_nan=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded))); self.end_headers()
        self.wfile.write(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    token = os.environ.get('FACTORY_ROUTER_TOKEN', '')
    server = Server(('0.0.0.0', 8765), Store(config['database'], capacities=config.get('capacities'), accounts=config.get('accounts', ACCOUNTS)), token)
    server.enable_tls(os.environ['FACTORY_ROUTER_CERT'], os.environ['FACTORY_ROUTER_KEY'])
    server.serve_forever()


if __name__ == '__main__':
    try: main()
    except Exception: raise SystemExit('router startup failed; no credential output') from None
