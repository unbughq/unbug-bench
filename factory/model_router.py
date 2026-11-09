"""Batch-wide model admission. Public metadata only; the control VM owns SQLite.

No model payload transport lives here. The optional credit reader holds the
OpenRouter credential only for read-only credit queries. Tests may inject _rpc; production
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
import pwd
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
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
from token_prices import (GATED_OPENROUTER, GATED_CLAUDE, CLAUDE_PROFILES, CODEX_PROFILES, FREE_ROUTES, GO_ROUTES, claude_gate_maximum,
                          codex_gate_maximum, free_maximum, go_maximum, openrouter_gate_maximum)

WAIT_SECONDS, RENEW_SECONDS, LEASE_SECONDS = 60, 60, 180
from worker_secrets import SECRETS
ACCOUNTS = ('claude-token', 'claude-factory-token-2', 'opencode-go-key',
            'opencode-go-key-2', 'codex-auth.json', 'openrouter-key')
# Every request in a chain starts at the chain's head (founder 2026-11-09: OpenCode first, OpenRouter as
# the fallback). The Go plan routes lead on both accounts; OpenRouter's paid route follows. The anonymous
# free lanes hang (8 of 9 free DeepSeek calls, 2026-11-08), so they come after paid, as a last resort.
CHAINS = (
    ('opencode-go/deepseek-v4.1-flash', 'openrouter/deepseek/deepseek-v4.1-flash', 'opencode/deepseek-v4.1-flash-free'),
    # The OpenRouter :free variant has no maximum, so it is never leased.
    ('opencode-go/minimax-m3.1-flash', 'opencode/minimax-m3.1-flash-free', 'openrouter/minimax/minimax-m3.1-flash:free',
     'openrouter/minimax/minimax-m3.1-flash'),
    ('opencode-go/mimo-v2.6-pro', 'openrouter/xiaomi/mimo-v2.6-pro'),
    ('opencode-go/muse-spark-1.3-contributor', 'openrouter/meta/muse-spark-1.3-contributor'),
    ('opencode-go/glm-5.3-flash', 'openrouter/z-ai/glm-5.3-flash', 'opencode/glm-5.3-flash-free'),
)
REASONS = {'quota', 'rate', 'credit', 'outage', 'router_unavailable', 'credential_expiring', 'unbounded_route'}
MAXIMUM_FIELDS = ('max_usd', 'max_input_tokens', 'max_output_tokens', 'price_source')


def route_maximum(route):
    # Only explicit profiles qualify; native CLI knobs alone grant no lease.
    if route in FREE_ROUTES: return free_maximum(route)
    if route in GO_ROUTES: return go_maximum(route)
    if route in CODEX_PROFILES: return codex_gate_maximum(route)
    return claude_gate_maximum(route) if route in CLAUDE_PROFILES else openrouter_gate_maximum(route)


def valid_maximum(value):
    get = value.get if isinstance(value, dict) else lambda k: getattr(value, k, None)
    maximum = route_maximum(get('route'))
    if maximum is not None and isinstance(get('price_source'), str):
        prefix = maximum['price_source'] + ':funded:'
        if get('price_source').startswith(prefix):
            try: maximum = funded_maximum(get('route'), get('price_source')[len(prefix):])
            except ValueError: return False
    return (maximum is not None and all(type(get(k)) is type(v) and get(k) == v for k, v in maximum.items()))


def funded_maximum(route, funding):
    """Quote an enforced invocation window inside the caller's existing grant.

    OpenRouter's small default windows are qualification probes, not case budgets.
    A funded window may use at most $50; explicit Claude and Codex profiles remain ceilings.
    The worker still atomically reserves this quote before any provider execution.
    """
    maximum = route_maximum(route)
    if maximum is None: return None
    if route in FREE_ROUTES: return maximum   # $0 whatever the funding: nothing to fund
    amount = min(_nano(funding, ROUND_FLOOR), _nano(50),
                 _nano(maximum['max_usd']) if route in CLAUDE_PROFILES or route in CODEX_PROFILES else _nano(50))
    if amount <= 0: raise ValueError('empty invocation funding')
    scale = Decimal(amount) / _nano(maximum['max_usd'])
    return dict(max_usd=float(_dollars(amount)),
                max_input_tokens=int(Decimal(maximum['max_input_tokens']) * scale),
                max_output_tokens=int(Decimal(maximum['max_output_tokens']) * scale),
                price_source=maximum['price_source'] + ':funded:' + _dollars(amount))


def _bounded_routes(model, accounts, funding=None):
    return [dict(r, **maximum) for r in routes(model, accounts)
            if (maximum := (route_maximum(r['route']) if funding is None else funded_maximum(r['route'], funding))) is not None]


def valid_lease(lease, model, accounts=ACCOUNTS):
    return (isinstance(lease, Lease) and valid_maximum(lease)
            and isinstance(lease.lease_id, str) and re.fullmatch(r'[a-f0-9]{32}', lease.lease_id) is not None
            and finite(lease.expires_at) and lease.expires_at > time.time()
            and {k: getattr(lease, k) for k in ('route', 'account', 'billing', 'family', 'pool')} in routes(model, accounts))


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
    chain = next((list(c) for c in CHAINS if model in c), [model])
    result = []
    for route in chain:
        billing = ('subscription' if route.startswith(('claude/', 'codex/', 'opencode-go/')) else
                   'free' if route.endswith(('-free', ':free')) else 'paid')
        labels = (('claude-factory-token-2', 'claude-token') if route.startswith('claude/') else ('codex-auth.json',) if route.startswith('codex/') else
                  ('openrouter-key',) if route.startswith('openrouter/') else
                  ACCOUNTS[2:4] if route.startswith('opencode-go/') or 'minimax-m3.1-flash-free' in route
                  or (route.startswith('opencode/') and billing == 'paid') else (None,))
        if labels != (None,):
            labels = tuple(a for a in (labels if route.startswith('claude/') else accounts)
                           if a in labels and a in accounts)
        for account in labels:
            if account is not None and account not in accounts: continue
            result.append(dict(route=route, account=account, billing=billing, family=family(route),
                               pool=account or ('opencode-free' if billing == 'free' else 'provider:' + route.partition('/')[0])))
    if any(r['family'] != family(model) for r in result): raise ValueError('fallback changed family')
    return result


# Calibrators run behind the isolation wall (user=pilot): they can reach only a gate's port.
WALLED_ROLES = ('strong_calibrator', 'easy_calibrator')


def ungated_lanes(model, accounts):
    """The lanes of model's chain that have no gate (free and Go plan routes), as admission's
    excluded_lanes spells them. A walled role reaches only a gate's port, so it never takes one."""
    return tuple(r['pool'] + '/' + r['route'] for r in routes(model, accounts)
                 if r['route'] in FREE_ROUTES or r['route'] in GO_ROUTES)


@dataclass(frozen=True)
class Lease:
    lease_id: str
    route: str
    account: str | None
    expires_at: float
    billing: str
    family: str
    pool: str
    max_usd: float
    max_input_tokens: int
    max_output_tokens: int
    price_source: str


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


PAID_CEILING = 11_630_000_000
CREDIT_OVERLAP = 900


def _nano(value, rounding=ROUND_CEILING):
    if isinstance(value, bool): raise ValueError('invalid paid amount')
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0: raise ValueError()
        return int((number * 1_000_000_000).to_integral_value(rounding=rounding))
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError('invalid paid amount') from None


def _dollars(value):
    return format(Decimal(value) / 1_000_000_000, '.9f')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def available_credit(token=None):
    """Read-only, bounded observation. Never expose credentials/provider diagnostics."""
    if token is None: token = os.environ.get('OPENROUTER_API_KEY')
    if not token: return None
    request = urllib.request.Request('https://openrouter.ai/api/v1/credits',
        headers={'Authorization': 'Bearer ' + token})
    try:
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=2) as response:
            raw = response.read(16385)
            if len(raw) > 16384: return None
            data = json.loads(raw, parse_float=Decimal)['data']
            credit, usage = data['total_credits'], data['total_usage']
            if any(type(v) not in (int, Decimal) or not Decimal(v).is_finite() or v < 0 for v in (credit, usage)):
                return None
            value = Decimal(credit) - Decimal(usage)
            return value if value >= 0 else None
    except Exception:
        return None


def production_database(config):
    if 'database' in config or 'UNBUG_CONTROL_HOME' in os.environ:
        raise ValueError('router database is not configurable')
    home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    path = home / '.unbug-control' / 'router' / 'factory.sqlite3'
    if any(p.is_symlink() for p in (path, path.parent, path.parent.parent)):
        raise ValueError('linked router ledger')
    return path


def _paid_envelope(operation, data):
    fields = {'lease_id', 'request_id'} | ({'usage'} if operation == 'paid_settle' else set())
    if (not isinstance(data, dict) or set(data) != fields or any(
            not isinstance(data[k], str) or not re.fullmatch('[a-f0-9]{32}', data[k])
            for k in ('lease_id', 'request_id'))):
        raise ValueError('invalid paid request')


def _paid_counts(db, since):
    """Total charges, and charges the provider's balance may not show yet. A settled or unknown
    request older than the credit window is already in that balance; counting it again blocked
    calls with credit to spare (7 November). An unknown row's time is when it became unknown, or
    its lease's end for rows written before that was recorded; with neither it stays counted."""
    total = outstanding = 0
    for hold, charge, state, settled, ended in db.execute(
            'SELECT p.hold,p.charge,p.state,p.settled_at,l.expires FROM paid_requests p LEFT JOIN leases l ON l.id=p.lease_id'):
        if (type(hold) is not int or hold < 0 or type(charge) is not int or not 0 <= charge <= hold
                or state not in ('pending', 'unknown', 'settled') or
                (state != 'settled' and charge != hold) or
                (state == 'settled' and not finite(settled))):
            raise ValueError('invalid paid ledger')
        total += charge
        if state == 'unknown':
            at = settled if finite(settled) else ended if finite(ended) else None
            if at is None or at >= since: outstanding += charge
        elif state != 'settled' or settled >= since: outstanding += charge
    return total, outstanding


def _paid_charge(profile, usage):
    if not isinstance(usage, dict): return None
    try:
        incoming, output = usage['prompt_tokens'], usage['completion_tokens']
        if (type(incoming) is not int or not 0 <= incoming <= profile['context'] or
                type(output) is not int or not 0 <= output <= profile['output']): return None
        value = (incoming * Decimal(profile['prices'][0]) + output * Decimal(profile['prices'][2])) / 1_000_000
        if 'cost' in usage:
            # The provider's own charge, within this request's maximum, is what the balance loses.
            # The token estimate prices every prompt token at the full rate and ignores cached ones;
            # on 7 November it booked $29.29 where OpenRouter charged $3.25.
            cost = usage['cost']
            if type(cost) not in (int, float) or not finite(cost) or not 0 <= Decimal(str(cost)) <= value: return None
            return _nano(Decimal(str(cost)), ROUND_CEILING)
        return _nano(value)
    except (KeyError, TypeError, ValueError, InvalidOperation): return None


class Store:
    """One short SQLite transaction per RPC; no process-local availability cache."""
    def __init__(self, path, *, capacities=None, accounts=ACCOUNTS, clock=time.time, credit_reader=None,
                 paid_ceiling_usd=None):
        approved_ceiling = None if paid_ceiling_usd is None else _nano(paid_ceiling_usd, ROUND_FLOOR)
        if approved_ceiling is not None and approved_ceiling > 2**63 - 1:
            raise ValueError('invalid paid ceiling')
        self.credit_reader = credit_reader
        self.path, self.clock = str(path), clock
        self.capacities, self.accounts = capacities or {}, tuple(accounts)
        if any(a not in ACCOUNTS for a in self.accounts): raise ValueError('unapproved account')
        if any(type(n) is not int or not 0 <= n <= 100 for n in self.capacities.values()):
            raise ValueError('invalid lane capacity')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, payload TEXT, created REAL, seen REAL);'
                             'CREATE TABLE IF NOT EXISTS leases (id TEXT PRIMARY KEY, route TEXT, expires REAL, outcome TEXT, receipt TEXT);'
                             'CREATE TABLE IF NOT EXISTS health (pool TEXT PRIMARY KEY, value TEXT);'
                             'CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY);'
                             'CREATE TABLE IF NOT EXISTS paid_account (id INTEGER PRIMARY KEY CHECK(id=1), ceiling INTEGER, credit INTEGER);'
                             'CREATE TABLE IF NOT EXISTS paid_requests (id TEXT PRIMARY KEY, lease_id TEXT, route TEXT, profile TEXT, '
                             'hold INTEGER, charge INTEGER, state TEXT, settled_at REAL, usage TEXT);')
            if 'seen' not in {row[1] for row in db.execute('PRAGMA table_info(requests)')}:
                db.execute('ALTER TABLE requests ADD COLUMN seen REAL NOT NULL DEFAULT 0')
            if approved_ceiling is not None:
                # Operator configuration changes the limit, never the retained charges.
                db.execute('BEGIN IMMEDIATE')
                total, _ = _paid_counts(db, self.clock() - CREDIT_OVERLAP)
                if approved_ceiling < total:
                    raise ValueError('paid ceiling below retained spending')
                db.execute('INSERT INTO paid_account(id,ceiling,credit) VALUES(1,?,NULL) '
                           'ON CONFLICT(id) DO UPDATE SET ceiling=excluded.ceiling', (approved_ceiling,))

    def rpc(self, operation, data, *, handling_started=None):
        started = time.monotonic() if handling_started is None else handling_started
        credit, fetched_at = None, self.clock()
        if operation in ('paid_reserve', 'paid_settle'): _paid_envelope(operation, data)
        if operation == 'paid_reserve':
            try:
                observed = self.credit_reader() if self.credit_reader else None
                if observed is not None: credit = _nano(observed, ROUND_FLOOR)
            except Exception: pass  # Unknown credit refuses; no provider diagnostics.
        now = self.clock()
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE leases SET outcome='expired' WHERE outcome IS NULL AND expires<=?", (now,))
            db.execute("UPDATE paid_requests SET state='unknown',settled_at=? WHERE state='pending' AND lease_id IN (SELECT id FROM leases WHERE outcome IS NOT NULL)", (now,))
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
            def eligible(route):
                # Spare capacity and caller preferences never unlock the builder account.
                second = health.get('claude-factory-token-2', {})
                return (route['account'] != 'claude-token' or
                        (second.get('reason') in ('rate', 'quota') and second.get('blocked_until', 0) > now))
            def free(route):
                occupied = sum(json.loads(r)['pool'] == route['pool'] for (r,) in db.execute('SELECT route FROM leases WHERE outcome IS NULL'))
                return 0 if not eligible(route) or blocked(route) else max(0, self.capacities.get(route['pool'], 1) - occupied)
            result = None
            if operation == 'paid_reserve':
                result = self._paid_reserve(db, data, credit, fetched_at, started)
            elif operation == 'paid_settle':
                result = self._paid_settle(db, data, now)
            elif operation == 'status':
                result = dict(observed_at=now, health=health, leases=[dict(lease_id=i, **json.loads(r), expires_at=e)
                    for i, r, e in db.execute('SELECT id,route,expires FROM leases WHERE outcome IS NULL')])
                account = db.execute('SELECT ceiling,credit FROM paid_account WHERE id=1').fetchone()
                total, outstanding = _paid_counts(db, now - CREDIT_OVERLAP)
                result['paid'] = dict(total_usd=_dollars(total), outstanding_usd=_dollars(outstanding),
                    ceiling_usd=_dollars(account[0]) if account else None,
                    available_credit_usd=_dollars(account[1]) if account and account[1] is not None else None)
            elif operation == 'capacity':
                choices = [r for r in _bounded_routes(data['route'], self.accounts) if r['route'] == data['route']]
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
                if set(data) - {'excluded_lanes', 'paid_protocol', 'funding_usd'} != {'id', 'model', 'accounts', 'role', 'deadline'}: raise ValueError('invalid admission fields')
                if 'funding_usd' in data and _nano(data['funding_usd'], ROUND_FLOOR) <= 0: raise ValueError('empty invocation funding')
                if not isinstance(data['role'], str) or not re.fullmatch(r'[a-z_0-9]{1,40}', data['role']): raise ValueError('invalid role')
                identity = data['id']
                if not re.fullmatch(r'[a-f0-9]{32}', identity): raise ValueError('invalid attempt id')
                if not finite(data['deadline']) or not now < data['deadline']: raise ValueError('expired admission deadline')
                choices = [r for r in _bounded_routes(data['model'], [a for a in data['accounts'] if a in self.accounts], data.get('funding_usd'))
                           if (r['route'] not in GATED_OPENROUTER or type(data.get('paid_protocol')) is int and data['paid_protocol'] == 1)
                           and eligible(r) and r['pool'] + '/' + r['route'] not in data.get('excluded_lanes', [])]
                payload = json.dumps(data, sort_keys=True, allow_nan=False)
                previous = db.execute('SELECT payload FROM requests WHERE id=?', (identity,)).fetchone()
                if previous and previous[0] != payload: raise ValueError('attempt id changed')
                db.execute('INSERT OR IGNORE INTO requests VALUES (?,?,?,?)', (identity, payload, now, now))
                db.execute('UPDATE requests SET seen=? WHERE id=?', (now, identity))
                lease = db.execute('SELECT route,expires,outcome FROM leases WHERE id=?', (identity,)).fetchone()
                if lease:
                    if lease[2] is not None: raise ValueError('closed lease cannot be replayed')
                    if (valid_maximum(json.loads(lease[0])) and
                            (json.loads(lease[0])['route'] not in GATED_OPENROUTER or data.get('paid_protocol') == 1)):
                        result = dict(kind='lease', lease_id=identity, **json.loads(lease[0]), expires_at=lease[1])
                    else:
                        db.execute("UPDATE leases SET outcome='denied' WHERE id=?", (identity,))
                        result = dict(kind='wait', reason='unbounded_route', retry_after=now+900, route=data['model'], account=None)
                else:
                    order = db.execute('SELECT rowid FROM requests WHERE id=?', (identity,)).fetchone()[0]
                    older = [json.loads(p) for (p,) in db.execute('SELECT payload FROM requests WHERE rowid<? AND seen>? ORDER BY rowid', (order, now - LEASE_SECONDS))
                             if json.loads(p)['deadline'] > now and not db.execute('SELECT 1 FROM leases WHERE id=?', (json.loads(p)['id'],)).fetchone()]
                    for route in choices:
                        if not free(route): continue
                        if any(any(eligible(r) and r['pool'] == route['pool'] and r['pool'] + '/' + r['route'] not in p.get('excluded_lanes', [])
                                   for r in _bounded_routes(p['model'], p['accounts'])) for p in older): continue
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
                        bounded = any(route_maximum(r['route']) is not None for r in routes(data['model']))
                        ready, reason, route = min(alternatives, key=lambda row: row[0]) if alternatives else (
                            now + 900, ('credential_expiring' if data['model'].startswith('claude/') else 'outage') if bounded
                            else 'unbounded_route', dict(route=data['model'], account=None))
                        result = dict(kind='wait', reason=reason, retry_after=ready, route=route['route'], account=route['account'])
            elif operation in ('renew', 'finish', 'start'):
                row = db.execute('SELECT route,expires,outcome,receipt FROM leases WHERE id=?', (data['lease_id'],)).fetchone()
                if not row: raise ValueError('unknown lease')
                if operation in ('renew', 'start'):
                    if row[2] is not None: raise ValueError('closed lease')
                    if not valid_maximum(json.loads(row[0])): raise ValueError('unbounded lease')
                    if json.loads(row[0])['route'] in GATED_OPENROUTER:
                        admitted = json.loads(db.execute('SELECT payload FROM requests WHERE id=?', (data['lease_id'],)).fetchone()[0])
                        if type(admitted.get('paid_protocol')) is not int or admitted['paid_protocol'] != 1:
                            raise ValueError('legacy paid lease')
                    if operation == 'start':
                        marker = '/execution/' + data['lease_id']
                        if db.execute('SELECT 1 FROM observations WHERE id=?', (marker,)).fetchone():
                            raise ValueError('lease execution already started')
                        db.execute('INSERT INTO observations VALUES (?)', (marker,))
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
                        if reason not in REASONS - {'unbounded_route'}: raise ValueError('invalid provider reason')
                        key = route['pool'] + ('/' + route['route'] if reason == 'outage' else '')
                        old = health.get(key, {}); failures = old.get('failures', 0) + 1
                        reset = retry_at(reason, now=now, failures=failures, reset_at=data.get('reset_at'))
                        health[key] = dict(reason=reason, blocked_until=reset, observed_at=now, failures=failures,
                                           credit='denied' if reason == 'credit' else old.get('credit', 'unknown'))
                    db.execute('INSERT INTO observations VALUES (?)', (identity,))
                result = {'observed': True}
            else: raise ValueError('unknown router operation')
            db.execute("UPDATE paid_requests SET state='unknown',settled_at=? WHERE state='pending' AND lease_id IN (SELECT id FROM leases WHERE outcome IS NOT NULL)", (now,))
            save_health()
            return result



    def _paid_reserve(self, db, data, credit, fetched_at, started):
        denied = lambda reason: dict(granted=False, reason=reason)
        prior = db.execute('SELECT lease_id FROM paid_requests WHERE id=?', (data['request_id'],)).fetchone()
        if prior: return denied('duplicate' if prior[0] == data['lease_id'] else 'binding')
        row = db.execute('SELECT route,outcome FROM leases WHERE id=?', (data['lease_id'],)).fetchone()
        if not row or row[1] is not None: return denied('binding')
        lease = json.loads(row[0])
        if lease['route'] not in GATED_OPENROUTER or lease['account'] != 'openrouter-key' or not valid_maximum(lease):
            return denied('binding')
        request = db.execute('SELECT payload FROM requests WHERE id=?', (data['lease_id'],)).fetchone()
        if not request: return denied('binding')
        request = json.loads(request[0])
        if (type(request.get('paid_protocol')) is not int or request['paid_protocol'] != 1 or
                not db.execute('SELECT 1 FROM observations WHERE id=?', ('/execution/' + data['lease_id'],)).fetchone()):
            return denied('binding')
        if time.monotonic() - started >= 4: return denied('binding')
        account = db.execute('SELECT ceiling FROM paid_account WHERE id=1').fetchone()
        ceiling = account[0] if account else min(PAID_CEILING, credit) if credit is not None else None
        if ceiling is not None and (type(ceiling) is not int or not 0 <= ceiling <= 2**63 - 1):
            raise ValueError('invalid paid ceiling')
        if credit is None: return denied('credit')
        profile = GATED_OPENROUTER[lease['route']]
        hold = _paid_charge(profile, dict(prompt_tokens=profile['context'], completion_tokens=profile['output']))
        total, outstanding = _paid_counts(db, fetched_at - CREDIT_OVERLAP)
        if total + hold > ceiling or outstanding + hold > credit: return denied('credit')
        db.execute('INSERT OR REPLACE INTO paid_account VALUES (1,?,?)', (ceiling, credit))
        frozen = dict(profile, price_source=lease['price_source'])
        db.execute('INSERT INTO paid_requests VALUES (?,?,?,?,?,?,?,?,?)',
            (data['request_id'], data['lease_id'], lease['route'], json.dumps(frozen), hold, hold, 'pending', None, None))
        return dict(granted=True)

    def _paid_settle(self, db, data, now):
        row = db.execute('SELECT lease_id,profile,hold,state,usage FROM paid_requests WHERE id=?', (data['request_id'],)).fetchone()
        if not row or row[0] != data['lease_id']: return dict(settled=False)
        usage = json.dumps(data['usage'], sort_keys=True, allow_nan=False)
        if row[3] != 'pending':
            return dict(settled=row[3] == 'settled' and row[4] == usage)
        charge = _paid_charge(json.loads(row[1]), data['usage'])
        known = charge is not None and charge <= row[2]
        db.execute('UPDATE paid_requests SET charge=?,state=?,settled_at=?,usage=? WHERE id=?',
            (charge if known else row[2], 'settled' if known else 'unknown', now,
             usage if known else None, data['request_id']))
        return dict(settled=known)


def router_request(url, token, operation, data, *, ca_file=None, ca_pem=None):
    """Authenticated router-only TLS; never proxy or redirect bearer authority."""
    parsed = urlsplit(url)
    if not token or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1'))):
        raise RouterUnavailable('router unconfigured')
    try:
        context = ssl.create_default_context()
        if ca_file or ca_pem: context.load_verify_locations(cafile=ca_file, cadata=ca_pem)
        opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}),
                                             urllib.request.HTTPSHandler(context=context))
        request = urllib.request.Request(url.rstrip('/') + '/' + operation, json.dumps(data, allow_nan=False).encode(),
                                         {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        with opener.open(request, timeout=5) as response:
            raw = response.read(1024 * 1024 + 1)
            if response.status != 200 or len(raw) > 1024 * 1024: raise ValueError()
            result = json.loads(raw)
            if not isinstance(result, dict): raise ValueError()
            return result
    except urllib.error.HTTPError as error:
        error.close()
        raise RouterUnavailable('router response unavailable') from None
    except (OSError, ValueError, urllib.error.URLError):
        raise RouterUnavailable('router response unavailable') from None


def _rpc(operation, data):
    return router_request(os.environ.get('FACTORY_ROUTER_URL', ''),
                          os.environ.get('FACTORY_ROUTER_TOKEN', ''), operation, data,
                          ca_file=os.environ.get('FACTORY_ROUTER_CA_FILE'))


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
    LABELS = {'opencode': {1: 'opencode-go-key', 2: 'opencode-go-key-2'},
              'claude': {1: 'claude-token', 2: 'claude-factory-token-2', 3: 'claude-factory-token-3'}}
    preferred = {LABELS[p].get(n) for p,n in (case.card.get('provider_accounts') or {}).items() if p in LABELS}
    return sorted(getattr(case, 'router_accounts', ACCOUNTS),
                  key=lambda a: (not (SECRETS / a).is_file(), a not in preferred))


def _admit(role, case, deadline, identity, accounts, excluded=()):
    model = getattr(case, 'router_model', None) or case.card['roles'][role]['model']
    data = dict(id=identity, model=model, accounts=list(accounts), deadline=deadline, role=role, excluded_lanes=list(excluded), paid_protocol=1)
    funding = getattr(case, 'router_funding_usd', None)
    if funding is not None: data['funding_usd'] = funding
    result = _rpc('acquire', data)
    if result.get('kind') == 'lease':
        result.pop('kind')
        allowed = [r for r in routes(model, accounts) if r['pool'] + '/' + r['route'] not in excluded]
        if (result.get('lease_id') != identity or not finite(result.get('expires_at'))
                or result['expires_at'] <= time.time() or result['expires_at'] > deadline
                or {k: result.get(k) for k in ('route', 'account', 'pool', 'family', 'billing')} not in allowed):
            raise RouterUnavailable('invalid lease response')
        if not valid_maximum(result) or (funding is not None and _nano(result.get('max_usd')) > _nano(funding)):
            finish(identity, 'denied', None)
            case.router_unbounded = True
            case.router_wait = Wait('unbounded_route', retry_at('unbounded_route'), route=model)
            return case.router_wait
        try: return Lease(**result)
        except TypeError: raise RouterUnavailable('invalid lease fields') from None
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
    enabled = getattr(case, 'engine', None) is not None or os.environ.get('UNBUG_PROVIDER_WAIT', '0') == '1'
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
    enabled = getattr(case, 'engine', None) is not None or os.environ.get('UNBUG_PROVIDER_WAIT', '0') == '1'
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
            result = (case.router_wait if getattr(case, 'router_unbounded', False) else
                      wait if enabled and deferred else _admit(role, case, batch_deadline, identity, accounts, excluded))
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
    routes(route)  # Validate configuration even when no enforcement adapter exists.
    if route_maximum(route) is None: return 0
    return _rpc('capacity', {'route': route})['slots']


def _start(lease):
    try: result = _rpc('start', {'lease_id': lease.lease_id})
    except ValueError: raise RouterUnavailable('lease execution unavailable') from None
    if not valid_maximum(result) or any(result.get(k) != getattr(lease, k)
            for k in ('route', 'account', 'pool', 'family', 'billing', *MAXIMUM_FIELDS)):
        raise RouterUnavailable('lease execution binding changed')


@contextmanager
def running(lease, cancel):
    """Keep ownership alive; uncertain renewal cancels useful work, never retries it."""
    stopped, lost = threading.Event(), threading.Event()
    def renew_once():
        try: result = _rpc('renew', {'lease_id': lease.lease_id})
        except ValueError: raise RouterUnavailable('lease renewal unavailable') from None
        if not valid_maximum(result) or any(result.get(k) != getattr(lease, k)
                for k in ('route', 'account', 'pool', 'family', 'billing', *MAXIMUM_FIELDS)):
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
        handling_started = time.monotonic()
        self.connection.settimeout(5)
        status, value = 400, {'error': 'invalid router request'}
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + self.server.token):
            status, value = 403, {'error': 'router authentication required'}
        else:
            try:
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1: raise ValueError()
                size = int(self.headers['Content-Length'])
                if not 0 < size <= 16384: raise ValueError()
                value = self.server.store.rpc(self.path.removeprefix('/'), json.loads(self.rfile.read(size)), handling_started=handling_started)
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
    server = Server(('0.0.0.0', 8765), Store(production_database(config), capacities=config.get('capacities'),
        accounts=config.get('accounts', ACCOUNTS), credit_reader=available_credit,
        paid_ceiling_usd=config.get('paid_ceiling_usd')), token)
    server.enable_tls(os.environ['FACTORY_ROUTER_CERT'], os.environ['FACTORY_ROUTER_KEY'])
    server.serve_forever()


if __name__ == '__main__':
    try: main()
    except Exception: raise SystemExit('router startup failed; no credential output') from None
