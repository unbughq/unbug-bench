"""One $0 call per free model per OpenCode account, to check each answers before going free-first.

    python3 factory/free_route_smoke.py [--secrets DIR] [--account opencode-go-key] [--model opencode/...]

Each call runs exactly as a factory free call does: OpenCode's own provider only, that one model,
that one account's key (model_call_gate.free_environment), scratch config dirs, and a budget that
stops the call at the first booked cost. It asks for one word and prints one JSON line per call
with only content-free fields: ok, seconds, error_class, http_status, error_name, events_seen.
It never prints a key or anything the model wrote, takes no router lease and spends nothing.
Run it where the account files are, such as a worker (/dev/shm/secrets) or with --secrets.
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


def smoke(account, model, secrets, timeout=180, *, run=budget.run_budgeted):
    if account not in ACCOUNTS or model not in FREE_ROUTES:
        raise ValueError('unapproved free route')
    row = {'account': account, 'model': model, 'ok': False, 'seconds': None, 'error_class': None,
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
        lease = SimpleNamespace(route=model, account=account)
        env = model_call_gate.free_environment(lease, env)
        binary = model_runtime.OPENCODE_BIN
        cmd = [binary, 'run', *model_runtime._opencode_flags(binary), '-m', model, '--format', 'json',
               '--title', 'factory-free-route-smoke', PROMPT]
        run(cmd, str(scratch), env, scratch / 'transcript.jsonl', scratch / 'ledger.json', timeout,
            max_cost=STOP_AT_ANY_COST, max_calls=5, max_total_calls=5, driver='opencode',
            configured_model=model, containment=False)
        row['ok'] = True
    except budget.BudgetError as error:
        info = getattr(error, 'provider_error', None) or {}
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
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args(argv)
    failed = False
    for account in args.account or ACCOUNTS:
        for model in args.model or sorted(FREE_ROUTES):
            row = smoke(account, model, args.secrets, args.timeout)
            failed |= not row['ok']
            print(json.dumps(row, sort_keys=True), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
