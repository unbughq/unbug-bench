"""Offline router and synthetic RAM credentials for legacy execution contracts."""
import atexit
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
import model_router


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
    stack.enter_context(patch.object(model_router, '_rpc', store.rpc))
    stack.enter_context(patch.object(model_router, 'SECRETS', secrets))
    stack.enter_context(patch.object(model_router, 'WAIT_SECONDS', 0))
    stack.enter_context(patch.object(model_router, 'metadata', return_value=('test-batch', 'test-job', time.time() + 86400)))
    stack.enter_context(patch.dict('os.environ', {'UNBUG_PROVIDER_WAIT': '1'}))
    atexit.register(stack.close)
    return stack, store
