"""One $0 call per free model per OpenCode account, to check each answers before going free-first.

    python3 factory/free_route_smoke.py [--secrets DIR] [--account opencode-go-key] [--model opencode/...]
                                        [--variant factory --variant zen --variant go]

Each call runs exactly as a factory free call does: OpenCode's own provider only, that one model,
that one account's key (model_call_gate.free_environment), scratch config dirs, and a budget that
stops the call at the first booked cost. It asks for one word and prints one JSON line per call
with only content-free fields: ok, seconds, error_class, http_status, error_name, events_seen.
It never prints a key or anything the model wrote, takes no router lease and spends nothing.
Run it where the account files are, such as a worker (/dev/shm/secrets) or with --secrets.

Variants settle which endpoint and model ID each account actually serves:
    factory  the factory's own config for the route (free_models.provider_config)
    zen      OpenCode's provider on the Zen endpoint (https://opencode.ai/zen/v1), the "-free" model ID
    go       OpenCode's built-in Go provider (opencode-go), the model ID without "-free"
The go variant uses Go plan usage, not money; any booked cost still stops it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import budget
import model_call_gate
import model_router
import model_runtime
from token_prices import FREE_ROUTES

ACCOUNTS = ('opencode-go-key', 'opencode-go-key-2')
PROMPT = 'Reply with the single word OK.'
# Any booked cost stops the call: the free routes are bounded at $0.
STOP_AT_ANY_COST = 1e-9


VARIANTS = ('factory', 'zen', 'go')


def _probe_environment(variant, model, env):
    """(route, clean env) for one variant: one provider, one model, no outside config."""
    if variant == 'factory':
        return model, model_call_gate.free_environment(SimpleNamespace(route=model, account='probe'), env)
    model_id = model.partition('/')[2]
    if variant == 'zen':
        provider, route, options = 'opencode', model, {'baseURL': 'https://opencode.ai/zen/v1'}
    else:
        model_id = model_id.removesuffix('-free')
        provider, route, options = 'opencode-go', 'opencode-go/' + model_id, {}
    cfg = dict(model=route, small_model=route, enabled_providers=[provider], permission={'task': 'deny'},
               compaction={'auto': True}, mcp={},
               provider={provider: {'options': {**options, 'apiKey': '{env:OPENCODE_API_KEY}'}, 'whitelist': [model_id]}})
    clean = {k: env[k] for k in ('PATH', 'HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'OPENCODE_API_KEY')}
    clean.update(OPENCODE_CONFIG_CONTENT=json.dumps(cfg), OPENCODE_PURE='1', OPENCODE_DISABLE_PROJECT_CONFIG='1',
                 OPENCODE_DISABLE_AUTOUPDATE='1')
    return route, clean


def smoke(account, model, secrets, timeout=180, *, variant='factory', run=budget.run_budgeted):
    if account not in ACCOUNTS or model not in FREE_ROUTES or variant not in VARIANTS:
        raise ValueError('unapproved free route')
    row = {'account': account, 'model': model, 'variant': variant, 'ok': False, 'seconds': None, 'error_class': None,
           'http_status': None, 'error_name': None, 'events_seen': None}
    key_file = Path(secrets) / account
    try:
        key = key_file.read_text().strip()
    except OSError:
        key = ''
    if not key:
        return {**row, 'error_class': 'credential_missing'}
    scratch = Path(tempfile.mkdtemp(prefix='free-route-smoke-'))
    started = time.monotonic()
    try:
        env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(scratch), 'OPENCODE_API_KEY': key,
               'OPENCODE_CONFIG': str(model_runtime.opencode_config(model)),
               **{name: str(scratch / name.lower()) for name in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME')}}
        route, env = _probe_environment(variant, model, env)
        row['route'] = route
        binary = model_runtime.OPENCODE_BIN
        cmd = [binary, 'run', *model_runtime._opencode_flags(binary), '-m', route, '--format', 'json',
               '--title', 'factory-free-route-smoke', PROMPT]
        run(cmd, str(scratch), env, scratch / 'transcript.jsonl', scratch / 'ledger.json', timeout,
            max_cost=STOP_AT_ANY_COST, max_calls=5, max_total_calls=5, driver='opencode',
            configured_model=route, containment=False)
        row['ok'] = True
    except budget.BudgetError as error:
        info = getattr(error, 'provider_error', None) or {}
        if variant == 'go' and str(error) == 'unpriced_usage' and info.get('events_seen'):
            # The Go plan is a subscription: an answer with tokens at cost 0 is a working route.
            # A positive reported cost still stops the call (cost_limit).
            row.update(ok=True, billing='subscription', events_seen=info['events_seen'])
            return row
        row.update(error_class=re.sub(r'[^a-z_]', '_', str(error).partition(':')[0].lower())[:40] or 'unknown',
                   **{k: info.get(k) for k in ('http_status', 'error_name', 'events_seen')})
    except Exception as error:   # a missing CLI, say; its text is not printed
        row['error_class'] = 'smoke_failed:' + type(error).__name__
    finally:
        row['seconds'] = round(time.monotonic() - started, 1)
        shutil.rmtree(scratch, ignore_errors=True)
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--secrets', default=str(model_router.SECRETS), help='directory holding the account files')
    parser.add_argument('--account', action='append', choices=ACCOUNTS, help='default: both')
    parser.add_argument('--model', action='append', choices=sorted(FREE_ROUTES), help='default: all free models')
    parser.add_argument('--variant', action='append', choices=VARIANTS, help='default: factory')
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args(argv)
    failed = False
    for account in args.account or ACCOUNTS:
        for model in args.model or sorted(FREE_ROUTES):
            for variant in args.variant or ('factory',):
                row = smoke(account, model, args.secrets, args.timeout, variant=variant)
                failed |= not row['ok']
                print(json.dumps(row, sort_keys=True), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
