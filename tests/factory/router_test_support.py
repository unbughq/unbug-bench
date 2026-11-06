"""Offline router and synthetic RAM credentials for legacy execution contracts."""
import atexit
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
import model_router
import model_call_gate


def synthetic_maximum(route):
    """Scheduler/argv tests only: never evidence that a real driver is bounded."""
    return dict(max_usd=50.0, max_input_tokens=1000000, max_output_tokens=32768,
                price_source='synthetic-test-only')


@contextmanager
def synthetic_enforcement(lease, env, cap_used, timeout, cancel=None, *, user=None):
    # Every caller of this helper mocks the CLI or runs a synthetic event emitter.
    yield cancel


def offline_router():
    stack = ExitStack()
    root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
    secrets = root / 'secrets'; secrets.mkdir()
    for account in model_router.ACCOUNTS:
        (secrets / account).write_text('synthetic-only')
    (secrets / 'codex-auth.json').write_text(json.dumps({'auth_mode': 'chatgpt',
        'tokens': {'access_token': 'e30.eyJleHAiOjk5OTk5OTk5OTl9.synthetic',
                   'refresh_token': 'synthetic', 'account_id': 'synthetic'},
        'last_refresh': '2026-10-29T00:00:00Z'}))
    store = model_router.Store(root / 'router.sqlite')
    stack.enter_context(patch.object(model_router, 'route_maximum', synthetic_maximum))
    stack.enter_context(patch.object(model_call_gate, 'enforce', synthetic_enforcement))
    stack.enter_context(patch.object(model_router, '_rpc', store.rpc))
    stack.enter_context(patch.object(model_router, 'SECRETS', secrets))
    stack.enter_context(patch.object(model_router, 'WAIT_SECONDS', 0))
    stack.enter_context(patch.object(model_router, 'metadata', return_value=('test-batch', 'test-job', time.time() + 86400)))
    stack.enter_context(patch.dict('os.environ', {'UNBUG_PROVIDER_WAIT': '1'}))
    atexit.register(stack.close)
    return stack, store


def historical_minimax_profile():
    """Replay the captured 2026-10-31 tariff, not a claim about today's endpoint.

    Verified against router-item8-minimax-availability.json.gz by its profile test.
    Financial fault tests freeze that input so provider changes cannot alter the
    authored credit/unknown-spend examples.
    """
    return patch.dict(model_router.GATED_OPENROUTER, {
        'openrouter/minimax/minimax-m3.1-flash': dict(endpoint='tenstorrent/fp8',
            prices=('0.05','0.005','0.2'),context=1000000,output=900000,windows=3,
            cache_write='0',source_date='2026-10-31')})
