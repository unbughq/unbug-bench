"""Attempt preauthorization at the existing runtime, ledger and provider gate boundaries."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(Path(__file__).resolve().parent)]
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from decimal import Decimal
import json
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
from durable.classify import classify
from durable.contract import Grant, LimitedBy, Outcome, StepKind, StepResult
from durable.policy import Action, Counters, decide
from test_durable_policy import SPEC, GATES, DIAG

ROUTE = 'claude/claude-opus-5-5'


class AttemptBudget(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.ledger = self.root / 'ledger.json'
        self.attempt = SimpleNamespace(key='attempt-1', baseline_spent_usd=0, ceiling_usd=50)
        self.store = model_router.Store(self.root / 'router.sqlite', capacities={'claude-factory-token-2': 2})
        secrets = self.root / 'secrets'; secrets.mkdir()
        for account in model_router.ACCOUNTS:
            (secrets / account).write_text('synthetic-token')
        self.stack.enter_context(patch.object(model_router, '_rpc', self.store.rpc))
        self.stack.enter_context(patch.object(model_router, 'SECRETS', secrets))
        self.c = SimpleNamespace(work=self.root, case=self.root, ledger=self.ledger, engine=self.attempt,
            card={'roles': {'writer': {'model': ROUTE}}}, batch_id='batch', job_id='case',
            batch_deadline=time.time()+3600, model_env={}, args=argparse.Namespace(agent_timeout=5,
                max_cost=0, case_budget=50, max_role_calls=100, max_total_calls=1,
                no_progress_minutes=1, max_zero_tokens=3))
        (self.root / 'transcripts').mkdir()
        self.runtime = model_runtime.ModelRuntime(self.root, Mock(), Mock(),
            lambda p, sudo=False: shutil.rmtree(p), Mock())

    def lease(self):
        return model_router.await_lease('writer', self.c, time.monotonic()+3)

    def reserve(self, lease, *, operation=None):
        return budget.reserve_invocation(self.ledger, lease, model_runtime.invocation_maximum(self.c, lease),
            attempt=self.attempt, operation_id=operation or str(uuid.uuid4()), call_name='builder-1')

    def test_parallel_runtime_denial_never_enters_transport(self):
        # Both leases are real router leases, with real (unmodified) price profiles.
        first, second = self.lease(), self.lease()
        entered, release = threading.Event(), threading.Event()
        def transport(c, *args, **kwargs):
            c.model_process_state['started'] = True
            entered.set()
            self.assertTrue(release.wait(5))
            raise budget.BudgetError('cancelled')
        with patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=transport) as provider:
            with ThreadPoolExecutor(2) as pool:
                running = pool.submit(self.runtime.call, self.c, [ROUTE], 'x', self.root, 'builder-1', lease=first)
                self.assertTrue(entered.wait(3))
                try:
                    with self.assertRaisesRegex(budget.BudgetError, 'grant_insufficient'):
                        self.runtime.call(self.c, [ROUTE], 'x', self.root, 'builder-2', lease=second)
                    self.assertEqual(provider.call_count, 1)
                finally:
                    release.set()
                with self.assertRaisesRegex(budget.BudgetError, 'cancelled'):
                    running.result()
        ledger = json.loads(self.ledger.read_text())
        row = ledger['invocation_reservations'][first.lease_id]
        self.assertEqual(row['state'], 'estimated')
        self.assertEqual(budget.case_spending(ledger)['total_spent_usd'], 50)
        # Cancellation/missing final usage retains ownership of the whole maximum.
        with self.assertRaisesRegex(budget.BudgetError, 'grant_insufficient'):
            self.reserve(second)

    def test_hard_worker_death_preserves_pending_authorizations(self):
        from durable.worker_step import Worker, ledger_totals
        from durable.policy import settles_as_waste
        self.ledger.write_text(json.dumps({'calls': 0, 'events': [], 'cost': 0}))
        worker = Worker(self.root)
        si = SimpleNamespace(idempotency_key=self.attempt.key, money_ceiling_usd_micros=50_000_000)
        worker.paths(si.idempotency_key)['attempt'].mkdir(parents=True)
        worker._save_baseline(si, self.ledger, ledger_totals(self.ledger))
        lease = self.lease()
        self.reserve(lease)
        for reason in ('infra:deadline', 'infra:step_crashed', 'infra:worker_error'):
            result = worker._failure_result(si.idempotency_key, reason)
            self.assertEqual(result.usage.paid_usd_micros, 50_000_000)
            self.assertTrue(settles_as_waste(result))
        # The next exclusive attempt reconciles the same hold, without charging twice.
        budget.reconcile_reservations(self.root, self.ledger)
        self.assertEqual(ledger_totals(self.ledger)['total'], 50)
        self.assertEqual(worker.usage_so_far(si.idempotency_key).paid_usd_micros, 50_000_000)
        self.attempt = SimpleNamespace(key='attempt-2', baseline_spent_usd=50, ceiling_usd=50)
        self.reserve(self.lease())

    def test_atomic_reservation_and_idempotent_honest_settlement(self):
        leases = [self.lease(), self.lease()]
        barrier = threading.Barrier(2)
        def reserve(lease):
            barrier.wait()
            try: return self.reserve(lease)
            except budget.BudgetError: return None
        with ThreadPoolExecutor(2) as pool:
            rows = list(pool.map(reserve, leases))
        self.assertEqual(sum(r is not None for r in rows), 1)
        row = next(r for r in rows if r is not None)
        lease = next(l for l in leases if l.lease_id == row['lease_id'])
        self.assertEqual(self.reserve(lease, operation=row['operation_id']), row)
        # Even a faulty transport exceeding its declaration is booked, never clamped.
        event = dict(id='synthetic-event', cost=51, invocation_id=row['invocation_id'], lease_id=lease.lease_id)
        receipt = dict(lease_id=lease.lease_id, final_usage_known=True, events=[event],
                       booked_event_ids=[event['id']])
        directory = self.root / 'usage-receipts'; directory.mkdir()
        (directory / (lease.lease_id+'.json')).write_text(json.dumps(receipt))
        for _ in range(2): budget.complete_invocation(self.root, self.ledger, lease.lease_id)
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual(ledger['cost'], 51)
        self.assertEqual(len(ledger['events']), 1)
        self.assertEqual(budget.case_spending(ledger)['total_spent_usd'], 51)

    def test_old_spend_fresh_grant_and_real_monitor(self):
        self.ledger.write_text(json.dumps(dict(cost=60, calls=900, events=[dict(id='old', cost=60)])))
        self.attempt.baseline_spent_usd = 60
        route = 'openrouter/deepseek/deepseek-v4.1-flash'
        lease = model_router.Lease(lease_id=uuid.uuid4().hex, expires_at=time.time()+60,
            **model_router.routes(route)[0], **model_router.route_maximum(route))
        row = self.reserve(lease)
        # Fake only model transport: the real monitor parses duplicate priced receipts.
        event = dict(type='step_finish', sessionID='s', part=dict(id='p', messageID='m', cost=.25,
            tokens=dict(input=1, output=1, reasoning=0, cache=dict(read=0, write=0))))
        command = [sys.executable, '-c', 'print('+repr(json.dumps(event))+'); print('+repr(json.dumps(event))+')']
        budget.run_budgeted(command, self.root, {}, self.root/'transcript', self.ledger, 3,
            max_cost=None, case_budget=50, configured_model=lease.route, concurrent=True,
            attempt=self.attempt, invocation_id=row['invocation_id'], lease_id=lease.lease_id,
            containment=False)
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual(ledger['cost'], 60.25)
        self.assertEqual(len(ledger['events']), 2)
        self.assertEqual(ledger['events'][-1]['invocation_id'], row['invocation_id'])
        self.assertEqual(budget.outstanding_reservations(ledger), Decimal(str(lease.max_usd)) - Decimal('.25'))
        # Recreating the attempt context cannot reset its baseline after usage.
        self.assertEqual(budget.attempt_limit(ledger, self.attempt), Decimal(110))

    def test_runtime_passes_reservation_to_real_monitor_and_settles(self):
        usage = dict(input_tokens=1, output_tokens=1, cache_read_input_tokens=0,
                     cache_creation_input_tokens=0)
        event = dict(type='result', session_id='synthetic', is_error=False,
                     total_cost_usd=.25, usage=usage)
        def transport(cmd, cwd, env, *args, **kwargs):
            self.assertIs(kwargs['attempt'], self.attempt)
            self.assertIsNone(kwargs.get('job_authority'))
            command = [sys.executable, '-c', 'print('+repr(json.dumps(event))+')']
            return budget.run_budgeted(command, cwd, env, *args,
                                       **{**kwargs, 'containment': False})
        # Replace only CLI transport; keep runtime reservation, real provider gate,
        # usage monitor, receipt generation and settlement.
        with patch.object(model_runtime, 'pinned_cli', return_value='synthetic'), \
             patch.object(model_runtime, 'run_budgeted', side_effect=transport), \
             patch('job_authority.for_case', side_effect=AssertionError('legacy authority')):
            self.runtime.call(self.c, [ROUTE], 'synthetic', self.root, 'builder-1')
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual(budget.case_spending(ledger)['total_spent_usd'], .25)
        self.assertEqual(budget.outstanding_reservations(ledger), 0)
        row = next(iter(ledger['invocation_reservations'].values()))
        self.assertEqual(row['state'], 'settled')
        budget.complete_invocation(self.root, self.ledger, row['lease_id'])
        self.assertEqual(json.loads(self.ledger.read_text()), ledger)

    def test_unknown_price_or_maximum_is_infrastructure(self):
        lease = self.lease()
        for invalid in (replace(lease, price_source='unknown'), replace(lease, max_usd=0),
                        replace(lease, route='codex/gpt-6.1-sol'),
                        replace(lease, route='opencode/deepseek-v4.1-flash-free')):
            with self.assertRaisesRegex(budget.BudgetError, 'route_maximum_unknown') as error:
                model_runtime.invocation_maximum(self.c, invalid)
            self.assertIs(classify(str(error.exception), step=StepKind.WRITER, now=0).outcome, Outcome.INFRA_ERROR)
        self.ledger.write_text(json.dumps(dict(cost=0, calls=0, events=[dict(id='unknown', cost=None)])))
        with self.assertRaisesRegex(budget.BudgetError, 'usage_unknown'):
            self.reserve(lease)

    def test_insufficient_grant_policy_uses_existing_money_reason(self):
        self.attempt.ceiling_usd = 1
        with self.assertRaisesRegex(budget.BudgetError, 'grant_insufficient') as error:
            self.reserve(self.lease())
        classified = classify(str(error.exception), step=StepKind.GATES, now=0)
        self.assertIs(classified.outcome, Outcome.EXHAUSTED)
        result = StepResult(classified.outcome, classified.reason)
        self.assertIs(decide(GATES, result, Counters(), SPEC, grant=Grant(1_000_000, LimitedBy.BATCH)),
                      Action.WAIT_FOR_BOUND)
        self.assertIs(decide(GATES, result, Counters(), SPEC, grant=Grant(1_000_000, LimitedBy.CASE)),
                      Action.DIAGNOSE)
        self.assertIs(decide(DIAG, result, Counters(), SPEC, grant=Grant(1_000_000, LimitedBy.NOTHING)),
                      Action.RETRY)

    def test_real_provider_gate_refuses_after_unknown_usage(self):
        lease = self.lease()
        gate = model_call_gate.Allowance(lease, deadline=time.monotonic()+2)
        request = gate.reserve(1)
        self.assertIsNotNone(request)
        self.assertFalse(gate.finish(request, None))
        gate.close()
        self.assertIsNone(gate.reserve(1))
        snapshot = gate.snapshot()
        self.assertEqual(snapshot['unknown_requests'], 1)
        self.assertGreater(Decimal(snapshot['held_usd']), 0)


if __name__ == '__main__': unittest.main()
