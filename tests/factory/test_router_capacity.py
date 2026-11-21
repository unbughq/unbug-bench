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
CLAUDE = 'claude/claude-opus-5-5'


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

    def hold_seat(self, **extra):
        return self.store.rpc('acquire', dict(id=uuid.uuid4().hex, model=TWIN, accounts=['openrouter-key'],
                                              role='reviewer', deadline=time.time() + 3600, paid_protocol=1, **extra))

    def test_full_seats_are_capacity_not_a_provider_limit(self):
        held = self.hold_seat()
        wait = self.hold_seat(capacity_protocol=1)
        self.assertEqual((wait['kind'], wait['reason'], wait['retry_after']), ('wait', 'capacity', held['expires_at']))
        # A worker that does not advertise the capacity wait still gets the reason it understands.
        self.assertEqual(self.hold_seat()['reason'], 'rate')
        self.assertEqual(self.store.rpc('status', {})['health'], {})   # nothing blocks the pool
        with self.assertRaises(ValueError):   # a worker cannot publish our own queue as provider health
            self.store.rpc('observe', dict(lease_id=held['lease_id'], reason='capacity', observation_id='x'))
        with self.assertRaises(ValueError):
            model_router.Store(self.root / 'negative.sqlite', capacities={'openrouter-key': -1})

    def test_a_zero_capacity_lane_is_closed_not_a_forever_wait(self):
        # The live config closes the anonymous free lane with "opencode-free": 0 (it hung on 8 Nov).
        closed = model_router.Store(self.root / 'zero.sqlite', capacities={
            'claude-factory-token-2': 3, 'claude-token': 3, 'openrouter-key': 0, 'opencode-free': 0,
            'opencode-go-key': 3, 'opencode-go-key-2': 3})
        answer = closed.rpc('acquire', dict(id=uuid.uuid4().hex, model=TWIN, accounts=['openrouter-key'],
                                            role='reviewer', deadline=time.time() + 3600, paid_protocol=1,
                                            capacity_protocol=1))
        self.assertNotEqual(answer.get('kind'), 'lease')
        self.assertNotEqual(answer.get('reason'), 'capacity')   # never a seat wait on a closed lane
        self.assertEqual(closed._routes(TWIN, ['openrouter-key']), [])

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
        # A stale lease expiry still retries within one lease, not after the 15-minute backoff.
        stale = model_router.ProviderWait('writer', model_router.Wait('capacity', now - 5))
        self.assertLessEqual(classify_wait(stale, step=StepKind.WRITER, now=now)[0].retry_at, now + 180)

    def test_capacity_wait_never_outlasts_the_calls_own_timeout(self):
        self.hold_seat()
        case = self.case(); case.router_capacity_seconds = .2   # an exam owner question's 120 s, scaled
        started = time.monotonic()
        with self.assertRaises(model_router.ProviderWait) as caught:
            model_router.await_lease('writer', case)
        self.assertEqual(caught.exception.wait.reason, 'capacity')
        self.assertLess(time.monotonic() - started, 5)

    def test_no_eligible_lane_is_its_own_wait_that_sleeps_out_its_retry(self):
        """1110a-h1, 18 November 00:17-01:37: a mimo request with no eligible lane was answered `outage` (+900 s) while
        other cases leased the same route; as an operational wait the engine relaunched it 8 times with 0 calls."""
        closed = model_router.Store(self.root / 'closed.sqlite', disabled_routes=('openrouter/xiaomi/',))
        with patch.object(model_router, '_rpc', closed.rpc), self.assertRaises(model_router.ProviderWait) as caught:
            model_router.await_lease('writer', self.case())
        wait = caught.exception.wait
        self.assertEqual(wait.reason, 'no_route')
        now = time.time()
        classified, record = classify_wait(caught.exception, step=StepKind.WRITER, now=now)
        self.assertEqual((classified.outcome, classified.reason), (Outcome.PROVIDER_LIMIT, 'router:no_route'))
        self.assertEqual(classified.retry_at, wait.retry_after)   # the router's +900 s, not a 2-minute recheck
        self.assertGreater(classified.retry_at, now + 800)
        self.assertEqual(record['waits'][-1]['reason'], 'no_route')
        result = StepResult(Outcome.PROVIDER_LIMIT, 'router:no_route', retry_at=classified.retry_at)
        self.assertEqual(decide(Step(StepKind.WRITER, 1), result, Counters(), SPEC), Action.SLEEP)
        self.assertFalse(settles_as_waste(result))
        from durable.stop_registry import lookup
        self.assertEqual(lookup('router:no_route'), {'kind': 'wait'})
        self.assertIn('router:no_route', PUBLISHED_REASONS)
        # A worker from before no_route (capacity_protocol 1) still gets the reason it understands.
        older = closed.rpc('acquire', dict(id=uuid.uuid4().hex, model=TWIN, accounts=['openrouter-key'], role='writer',
                                           deadline=time.time() + 3600, paid_protocol=1, capacity_protocol=1))
        self.assertEqual(older['reason'], 'outage')
        # A worker never publishes it as a provider limit.
        held = self.hold_seat()
        with self.assertRaises(ValueError):
            self.store.rpc('observe', dict(pool=None, healthy=False, observation_id=uuid.uuid4().hex,
                                           lease_id=held['lease_id'], reason='no_route', reset_at=None))

    def test_capacity_after_a_fault_keeps_the_original_stop(self):
        # A deterministic fault followed by a seat wait is still that fault: infra retries, then diagnosis.
        prior = [{'reason': 'outage', 'retry_after': time.time() + 900, 'historical': True, 'source_stop': 'opencode_error'}]
        error = model_router.ProviderWait('writer', model_router.Wait('capacity', time.time() + 60))
        classified, _ = classify_wait(error, step=StepKind.WRITER, now=time.time(), prior=prior)
        self.assertEqual((classified.outcome, classified.reason), (Outcome.INFRA_ERROR, 'router:opencode_error'))

    def test_no_chain_ever_crosses_model_family(self):
        for chain in model_router.CHAINS:
            for model in chain:
                self.assertEqual({r['family'] for r in model_router.routes(model)}, {model_router.family(model)})
        with patch.object(model_router, 'CHAINS', ((GO, 'openrouter/z-ai/glm-5.3-flash'),)), self.assertRaises(ValueError):
            model_router.routes(GO)

    def engine_case(self):
        ledger = self.root / 'ledger.json'
        (self.root / 'transcripts').mkdir()
        c = self.case(GO, ('opencode-go-key', 'openrouter-key'))
        c.engine = SimpleNamespace(key='attempt-1', baseline_spent_usd=0, ceiling_usd=50)
        c.work = c.case = self.root; c.ledger = ledger; c.model_env = {}
        c.args = argparse.Namespace(agent_timeout=5, max_cost=0, case_budget=50, max_role_calls=100, max_total_calls=10,
                                    no_progress_minutes=1, max_zero_tokens=3)
        runtime = model_runtime.ModelRuntime(self.root, Mock(), Mock(), lambda p, sudo=False: shutil.rmtree(p), Mock())
        return c, ledger, runtime

    def go_call(self, go_stop):
        c, ledger, runtime = self.engine_case()
        routes = []
        def transport(ctx, models, *args, **kwargs):
            ctx.model_process_state['started'] = True
            routes.append(ctx.model_lease.route)
            if models[0] == GO: raise budget.BudgetError(go_stop)
            state = model_call_gate.Allowance(ctx.model_lease)
            request = state.reserve(1)
            state.finish(request, dict(prompt_tokens=0, completion_tokens=0, total_tokens=0))
            state.close(); ctx.model_cap_used = state.snapshot()
            return 0
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT': '1'}), \
             patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=transport):
            return runtime.call(c, [GO], 'x', self.root, 'builder-1'), routes, ledger

    def test_go_quota_moves_the_call_to_its_same_model_twin(self):
        code, routes, ledger = self.go_call('provider_limit:' + GO)
        self.assertEqual(code, 0)
        self.assertEqual(routes, [GO, TWIN])
        self.assertEqual(model_router.family(GO), model_router.family(TWIN))
        # The Go account is blocked for later calls; the Go call booked nothing.
        self.assertEqual(self.store.rpc('status', {})['health']['opencode-go-key']['reason'], 'quota')
        self.assertEqual(budget.outstanding_reservations(json.loads(ledger.read_text())), 0)

    def test_other_go_faults_do_not_move_to_the_paid_twin(self):
        for stop in ('opencode_error', 'refusal:' + GO, 'process_error'):
            with self.subTest(stop=stop):
                self.setUp()
                with self.assertRaises(model_router.ProviderWait):
                    self.go_call(stop)


    def claude_call(self, stops):
        """A Claude call whose CLI fails with each of `stops` in turn, then succeeds."""
        c, ledger, runtime = self.engine_case()
        c.card['roles']['writer']['model'] = CLAUDE; c.router_accounts = ('claude-factory-token-2',)
        c.engine.ceiling_usd = c.args.case_budget = 500   # a subscription window holds $50 of funding
        self.store = model_router.Store(self.root / 'claude.sqlite', capacities={'claude-factory-token-2': 1})
        self.stack.enter_context(patch.object(model_router, '_rpc', self.store.rpc))
        routes, stops = [], list(stops)
        def transport(ctx, models, *args, **kwargs):
            ctx.model_process_state['started'] = True
            routes.append(ctx.model_lease.route)
            if stops: raise budget.BudgetError(stops.pop(0))
            state = model_call_gate.Allowance(ctx.model_lease)
            state.finish(state.reserve(1), dict(prompt_tokens=0, completion_tokens=0, total_tokens=0))
            state.close(); ctx.model_cap_used = state.snapshot()
            return 0
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT': '1'}), patch.object(model_runtime, 'SUBSCRIPTION_RETRY_SECONDS', 0, create=True), \
             patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=transport):
            return runtime.call(c, [CLAUDE], 'x', self.root, 'builder-1'), routes

    def test_one_claude_cli_fault_retries_its_lane_inside_the_attempt(self):
        # Speed plan 2026-11-18: one claude_error ended whole attempts as infra (2abb0a-h1: 63 min each).
        self.assertEqual(self.claude_call(['claude_error']), (0, [CLAUDE, CLAUDE]))
        with self.assertRaises(model_router.ProviderWait):   # a second fault on the lane still ends the attempt
            self.setUp(); self.claude_call(['claude_error', 'claude_error'])


if __name__ == '__main__':
    unittest.main()
