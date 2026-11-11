"""Full router seats wait inside the worker; a Go quota moves the call to its same-model twin."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(Path(__file__).resolve().parent)]
import argparse
from contextlib import ExitStack
import json
import os
import shutil
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

import budget
import model_call_gate
import model_router
import model_runtime
from durable.classify import PUBLISHED_REASONS, classify_wait
from durable.contract import Outcome, StepKind
from durable.policy import Action, Counters, decide, settles_as_waste
from durable.contract import StepResult
from durable.contract import Step
from test_durable_policy import SPEC

TWIN = 'openrouter/xiaomi/mimo-v2.6-pro'
GO = 'opencode-go/mimo-v2.6-pro'


class RouterCapacity(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.store = model_router.Store(self.root / 'router.sqlite', capacities={'openrouter-key': 1})
        secrets = self.root / 'secrets'; secrets.mkdir()
        for account in model_router.ACCOUNTS: (secrets / account).write_text('synthetic-token')
        self.stack.enter_context(patch.object(model_router, '_rpc', self.store.rpc))
        self.stack.enter_context(patch.object(model_router, 'SECRETS', secrets))
        # A rate or quota wait would end the attempt at once; only a capacity wait may stay.
        self.stack.enter_context(patch.object(model_router, 'WAIT_SECONDS', 0))
        self.stack.enter_context(patch.object(model_router, '_heartbeat', lambda case, s: time.sleep(min(s, .02))))

    def case(self, model=TWIN, accounts=('openrouter-key',)):
        return SimpleNamespace(card={'roles': {'writer': {'model': model}}}, engine=object(), router_accounts=accounts,
                               batch_id='batch', job_id='job', batch_deadline=time.time() + 3600)

    def hold_seat(self):
        return self.store.rpc('acquire', dict(id=uuid.uuid4().hex, model=TWIN, accounts=['openrouter-key'],
                                              role='reviewer', deadline=time.time() + 3600, paid_protocol=1))

    def test_full_seats_are_capacity_not_a_provider_limit(self):
        held = self.hold_seat()
        wait = self.hold_seat()
        self.assertEqual((wait['kind'], wait['reason'], wait['retry_after']), ('wait', 'capacity', held['expires_at']))
        self.assertEqual(self.store.rpc('status', {})['health'], {})   # nothing blocks the pool
        with self.assertRaises(ValueError):   # a worker cannot publish our own queue as provider health
            self.store.rpc('observe', dict(lease_id=held['lease_id'], reason='capacity', observation_id='x'))

    def test_seat_exhaustion_waits_in_the_worker_then_succeeds(self):
        held = self.hold_seat()
        threading.Timer(.2, lambda: self.store.rpc('finish', dict(lease_id=held['lease_id'], outcome='done', receipt=None))).start()
        lease = model_router.await_lease('writer', self.case())
        self.assertEqual((lease.route, lease.account), (TWIN, 'openrouter-key'))

    def test_capacity_wait_timeout_is_its_own_cheap_outcome(self):
        self.hold_seat()
        with patch.object(model_router, 'CAPACITY_WAIT_SECONDS', .2), self.assertRaises(model_router.ProviderWait) as caught:
            model_router.await_lease('writer', self.case())
        self.assertEqual(caught.exception.wait.reason, 'capacity')
        now = time.time()
        classified, _ = classify_wait(caught.exception, step=StepKind.WRITER, now=now)
        self.assertEqual((classified.outcome, classified.reason), (Outcome.PROVIDER_LIMIT, 'router:capacity'))
        self.assertLessEqual(classified.retry_at, now + model_router.LEASE_SECONDS)   # next lease expiry, not a 15-min backoff
        self.assertIn('router:capacity', PUBLISHED_REASONS)
        result = StepResult(Outcome.PROVIDER_LIMIT, 'router:capacity', retry_at=classified.retry_at)
        self.assertEqual(decide(Step(StepKind.WRITER, 1), result, Counters(), SPEC), Action.SLEEP)
        self.assertFalse(settles_as_waste(result))

    def test_no_chain_ever_crosses_model_family(self):
        for chain in model_router.CHAINS:
            for model in chain:
                self.assertEqual({r['family'] for r in model_router.routes(model)}, {model_router.family(model)})
        with patch.object(model_router, 'CHAINS', ((GO, 'openrouter/z-ai/glm-5.3-flash'),)), self.assertRaises(ValueError):
            model_router.routes(GO)

    def test_go_quota_moves_the_call_to_its_same_model_twin(self):
        ledger = self.root / 'ledger.json'
        (self.root / 'transcripts').mkdir()
        c = self.case(GO, ('opencode-go-key', 'openrouter-key'))
        c.engine = SimpleNamespace(key='attempt-1', baseline_spent_usd=0, ceiling_usd=50)
        c.work = c.case = self.root; c.ledger = ledger; c.model_env = {}
        c.args = argparse.Namespace(agent_timeout=5, max_cost=0, case_budget=50, max_role_calls=100, max_total_calls=10,
                                    no_progress_minutes=1, max_zero_tokens=3)
        runtime = model_runtime.ModelRuntime(self.root, Mock(), Mock(), lambda p, sudo=False: shutil.rmtree(p), Mock())
        routes = []
        def transport(ctx, models, *args, **kwargs):
            ctx.model_process_state['started'] = True
            routes.append(ctx.model_lease.route)
            if models[0] == GO: raise budget.BudgetError('provider_limit:' + GO)
            state = model_call_gate.Allowance(ctx.model_lease)
            request = state.reserve(1)
            state.finish(request, dict(prompt_tokens=0, completion_tokens=0, total_tokens=0))
            state.close(); ctx.model_cap_used = state.snapshot()
            return 0
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT': '1'}), \
             patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=transport):
            self.assertEqual(runtime.call(c, [GO], 'x', self.root, 'builder-1'), 0)
        self.assertEqual(routes, [GO, TWIN])
        self.assertEqual(model_router.family(GO), model_router.family(TWIN))
        # The Go account is blocked for later calls; the Go call booked nothing.
        self.assertEqual(self.store.rpc('status', {})['health']['opencode-go-key']['reason'], 'quota')
        self.assertEqual(budget.outstanding_reservations(json.loads(ledger.read_text())), 0)


if __name__ == '__main__':
    unittest.main()
