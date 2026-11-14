"""Attempt preauthorization at the existing runtime, ledger and provider gate boundaries."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(Path(__file__).resolve().parent)]
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from decimal import Decimal
import json
import shutil
import subprocess
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
from durable import worker_step
from durable.classify import classify
from durable.contract import Grant, LimitedBy, Outcome, StepKind, StepResult
from durable.policy import Action, Counters, decide
from test_durable_policy import SPEC, GATES, DIAG

ROUTE = 'claude/claude-opus-5-5'
# These tests drive OpenRouter's gated paid route; without the Go accounts a chain starts there.
NO_GO = tuple(a for a in model_router.ACCOUNTS if not a.startswith('opencode-go'))


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

    def test_ram_cleanup_survives_model_cancellation_and_expired_deadline(self):
        import processes
        import run
        (self.root/'logs').mkdir()
        for cancelled in (False,True):
            scratch=self.root/('state-'+str(cancelled));scratch.mkdir()
            (scratch/'private').write_text('synthetic')
            token=threading.Event()
            if cancelled:token.set()
            self.c.role_cancel=token
            def spawn(*args,**kwargs):
                return SimpleNamespace(pid=99999999,returncode=0,stdin=None,stdout=None,stderr=None,
                    communicate=lambda *a,**kw:('',None),poll=lambda:0,wait=lambda *a,**kw:0)
            runtime=replace(self.runtime,command=run.sh)
            with self.subTest(cancelled=cancelled),patch.object(run,'log'),                  patch.object(processes.subprocess,'Popen',side_effect=spawn) as popen,                  patch.dict(processes.os.environ,UNBUG_PROCESS_DEADLINE=str(time.monotonic()-1)):
                with processes.deadline(.001):
                    time.sleep(.01)
                    runtime._remove_state(self.c,scratch,memory=True)
                self.assertEqual(popen.call_args_list[0].args[0],['sudo','umount','--',str(scratch)])
                self.assertFalse(scratch.exists())
                self.assertIs(self.c.role_cancel,token)
                self.assertEqual(token.is_set(),cancelled)

    def test_durable_opencode_discards_ram_state_without_slow_disk_wiping(self):
        paid='openrouter/minimax/minimax-m3.1-flash'
        self.c.card['roles']['writer']['model']=paid
        self.c.router_accounts=NO_GO
        for failure in (None,'mount','umount'):
            self.ledger.unlink(missing_ok=True)
            self.c.card.pop('cleanup_errors',None)
            self.c.card.pop('route_receipts',None)
            scratch=[];commands=[]
            slow=Mock(side_effect=subprocess.TimeoutExpired('shred',120))
            def command(c,args,**kwargs):
                commands.append(list(map(str,args)))
                if args[1]==failure:raise subprocess.CalledProcessError(1,args)
            runtime=replace(self.runtime,command=command,cleanup=slow)
            @contextmanager
            def gate_only(lease,env,cap,*args,**kwargs):
                cap.update(closed=True,forwarded_requests=1,validated_requests=1,
                           unknown_requests=0,in_flight_requests=0,settled_usd='0.000000000',held_usd='0.000000000')
                yield threading.Event()
            def run_cli(cmd,cwd,env,*args,**kwargs):
                path=Path(env['XDG_CACHE_HOME']);path.mkdir(parents=True)
                (path/'private-state').write_text('synthetic case data')
                scratch.append(path.parent)
                self.assertEqual(kwargs['state_mount'],path.parent)  # recorded for the leftover reaper
                self.addCleanup(shutil.rmtree,path.parent,True)
                kwargs['on_started']()
                return subprocess.CompletedProcess(cmd,0)
            with self.subTest(failure=failure),patch.multiple(model_runtime,UNMOUNT_PAUSE_S=0,UNMOUNT_TOTAL_S=.05),patch.object(model_runtime.sys,'platform','linux'),                  patch.object(model_runtime,'_opencode_flags',return_value=()),                  patch.object(model_runtime.model_call_gate,'enforce',gate_only),                  patch.object(model_runtime,'run_budgeted',side_effect=run_cli) as process:
                if failure:
                    label='containment_unavailable' if failure=='mount' else 'cleanup_failed'
                    with self.assertRaisesRegex(budget.BudgetError,label):
                        runtime.call(self.c,[paid],'synthetic',self.root,'builder-ram')
                else:self.assertEqual(runtime.call(self.c,[paid],'synthetic',self.root,'builder-ram'),0)
                if failure=='mount':process.assert_not_called()
            slow.assert_not_called()
            mount=next(args for args in commands if args[1]=='mount')
            options=mount[mount.index('-o')+1]
            self.assertIn('mode=0700',options);self.assertIn('nosuid',options);self.assertIn('nodev',options)
            self.assertNotIn('noexec',options)
            self.assertTrue(any(args[1]=='umount' for args in commands))
            if failure=='umount':
                self.assertTrue(scratch[0].exists())
                self.assertIn({'stage':'model_scratch','error':'CalledProcessError'},self.c.card['cleanup_errors'])
            elif scratch:self.assertFalse(scratch[0].exists())

    def test_slow_scratch_unmount_is_retried_and_the_paid_result_kept(self):
        """fresh-1110b writer:1 (11 November): one umount over its 30 s limit turned a successful
        $48.70 call into cleanup_failed. A slow or busy unmount is retried; the mount still must go."""
        paid='openrouter/minimax/minimax-m3.1-flash'
        self.c.card['roles']['writer']['model']=paid
        self.c.router_accounts=NO_GO
        scratch=[];commands=[]
        failures=[subprocess.TimeoutExpired('umount',60),subprocess.CalledProcessError(32,'umount')]
        def command(c,args,**kwargs):
            commands.append(list(map(str,args)))
            if args[1]=='umount' and failures:raise failures.pop(0)
        runtime=replace(self.runtime,command=command,cleanup=Mock())
        @contextmanager
        def gate_only(lease,env,cap,*args,**kwargs):
            cap.update(closed=True,forwarded_requests=1,validated_requests=1,
                       unknown_requests=0,in_flight_requests=0,settled_usd='0.000000000',held_usd='0.000000000')
            yield threading.Event()
        def run_cli(cmd,cwd,env,*args,**kwargs):
            path=Path(env['XDG_CACHE_HOME']);path.mkdir(parents=True)
            scratch.append(path.parent)
            self.addCleanup(shutil.rmtree,path.parent,True)
            kwargs['on_started']()
            return subprocess.CompletedProcess(cmd,0)
        with patch.multiple(model_runtime,UNMOUNT_PAUSE_S=0),\
             patch.object(model_runtime.sys,'platform','linux'),\
             patch.object(model_runtime,'_opencode_flags',return_value=()),\
             patch.object(model_runtime.model_call_gate,'enforce',gate_only),\
             patch.object(model_runtime,'run_budgeted',side_effect=run_cli):
            self.assertEqual(runtime.call(self.c,[paid],'synthetic',self.root,'builder-ram'),0)
        umounts=[a for a in commands if a[1]=='umount']
        self.assertEqual(len(umounts),3)
        self.assertTrue(all(a==['sudo','umount','--',str(scratch[0])] for a in umounts))  # never lazy
        self.assertFalse(scratch[0].exists())
        self.assertNotIn('model_scratch',[e['stage'] for e in self.c.card.get('cleanup_errors',[])])

    def test_busy_isolated_scratch_kills_the_user_before_each_retry_and_fails_if_it_stays(self):
        state=self.root/'factory-tester-state-x';state.mkdir()
        commands=[]
        def command(c,args,**kwargs):
            commands.append(list(map(str,args)))
            if args[1]=='umount':raise subprocess.CalledProcessError(32,'umount')
        runtime=replace(self.runtime,command=command)
        with patch.multiple(model_runtime,UNMOUNT_PAUSE_S=0,UNMOUNT_TOTAL_S=.05):
            with self.assertRaises(subprocess.CalledProcessError):
                runtime._remove_state(self.c,state,memory=True,user='pilot')
        self.assertTrue(state.exists())  # a mount that cannot go is never removed underneath
        self.assertGreater(len(commands),2)
        for before,after in zip(commands[::2],commands[1::2]):
            self.assertEqual(before[1],'umount');self.assertEqual(after,['sudo','pkill','-KILL','-u','pilot'])

    def test_funded_invocation_continues_past_the_live_small_profile_stop(self):
        self.attempt.ceiling_usd = Decimal('40.792858')
        def transport(c, *args, **kwargs):
            c.model_process_state['started'] = True
            self.assertEqual(Decimal(str(c.model_lease.max_usd)), self.attempt.ceiling_usd)
            state = model_call_gate.Allowance(c.model_lease)
            # The live failure: five validated responses cost this much, then
            # the next $9.520896 hold did not fit the old $10 CLI profile.
            state.settled[0] = Decimal('0.551782')
            state.validated = 5
            identity = state.reserve(32768)
            self.assertIsNotNone(identity)
            state.finish(identity, dict.fromkeys(model_call_gate.CLAUDE_GATE_FIELDS, 0))
            state.close()
            c.model_cap_used = state.snapshot()
            return 0
        with patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=transport):
            self.assertEqual(self.runtime.call(self.c, [ROUTE], 'x', self.root, 'builder-1'), 0)
        saved = json.loads(self.ledger.read_text())
        row = next(iter(saved['invocation_reservations'].values()))
        self.assertEqual(row['maximum_usd'], '40.792858000')
        receipt = json.loads((self.root / 'usage-receipts' / (row['lease_id'] + '.json')).read_text())
        self.assertEqual(Decimal(receipt['cap_used']['settled_usd']), Decimal('.551782'))

    def test_exam_parent_leaves_funded_owner_room_without_releasing_its_hold(self):
        self.attempt.ceiling_usd=Decimal('40.792858')
        reviewer='openrouter/xiaomi/mimo-v2.6-pro'
        self.c.exam_owner_models=[reviewer]
        self.c.router_accounts=NO_GO
        expected=Decimal(str(model_router.route_maximum(reviewer)['max_usd']))
        invoked=[]
        def transport(c, models, text, cwd, name, *args, **kwargs):
            c.model_process_state['started']=True
            invoked.append(name)
            if name.startswith('strong-calibrator'):
                # Capped like every non-writer call, and never into the owner's room.
                self.assertEqual(Decimal(str(c.model_lease.max_usd)),
                                 min(Decimal(str(model_runtime.CHEAP_CALL_WINDOW_USD)), self.attempt.ceiling_usd-expected))
                parent=next(r for r in json.loads(self.ledger.read_text())['invocation_reservations'].values())
                owner=copy.copy(self.c);owner.parent_call_name=name
                self.assertEqual(self.runtime.call(owner,[reviewer],'question',self.root,'reviewer-owner-example'),0)
                self.assertEqual(json.loads(self.ledger.read_text())['invocation_reservations'][parent['lease_id']]['state'],'pending')
            else:   # the owner is funded beside the parent's capped hold
                self.assertEqual(Decimal(str(c.model_lease.max_usd)),Decimal(str(model_runtime.CHEAP_CALL_WINDOW_USD)))
                self.assertLessEqual(budget.outstanding_reservations(json.loads(self.ledger.read_text())),self.attempt.ceiling_usd)
            state=model_call_gate.Allowance(c.model_lease)
            request=state.reserve(1);self.assertIsNotNone(request)
            usage=(dict.fromkeys(model_call_gate.CLAUDE_GATE_FIELDS,0) if models[0]==ROUTE else
                   dict(prompt_tokens=0,completion_tokens=0,total_tokens=0))
            state.finish(request,usage);state.close();c.model_cap_used=state.snapshot()
            return 0
        with patch.object(model_runtime.ModelRuntime,'_invoke',side_effect=transport):
            self.assertEqual(self.runtime.call(self.c,[ROUTE],'exam',self.root,'strong-calibrator-example'),0)
        self.assertEqual(invoked,['strong-calibrator-example','reviewer-owner-example'])
        self.assertEqual(budget.outstanding_reservations(json.loads(self.ledger.read_text())),0)

    def test_funded_quotes_keep_default_profiles_and_reject_forgery(self):
        paid = 'openrouter/minimax/minimax-m3.1-flash'
        default = model_router.route_maximum(paid)
        quoted = model_router.funded_maximum(paid, '20.000000000')
        self.assertGreater(quoted['max_usd'], default['max_usd'])
        self.assertEqual(quoted['max_usd'], 20.0)
        record = dict(route=paid, **quoted)
        self.assertTrue(model_router.valid_maximum(record))
        for change in ({'max_usd': 21.0}, {'max_input_tokens': quoted['max_input_tokens'] + 1},
                       {'price_source': quoted['price_source'] + '0'}):
            self.assertFalse(model_router.valid_maximum(record | change))
        self.assertEqual(model_router.route_maximum(paid), default)
        self.assertEqual(model_router.funded_maximum(ROUTE + ':small', 40)['max_usd'], 10.0)
        self.assertEqual(model_router.funded_maximum(paid, 100)['max_usd'], 50.0)
        for value in (0, -1, 'nan', 'inf', True):
            with self.assertRaises(ValueError): model_router.funded_maximum(paid, value)

    def test_router_paid_funding_is_bound_to_the_request_id(self):
        data = dict(id=uuid.uuid4().hex, model='openrouter/minimax/minimax-m3.1-flash',
                    role='writer', accounts=list(model_router.ACCOUNTS), deadline=time.time()+60,
                    paid_protocol=1, funding_usd='20.000000000')
        quote = self.store.rpc('acquire', data)
        self.assertEqual(quote['max_usd'], 20.0)
        self.assertTrue(model_router.valid_maximum(quote))
        self.assertEqual(self.store.rpc('acquire', data), quote)
        with self.assertRaises(ValueError):
            self.store.rpc('acquire', data | {'funding_usd': '21.000000000'})

    def test_bound_worker_prepares_containment_before_model_execution(self):
        from durable.worker_step import Worker
        lease = self.lease()
        self.c.model_lease = lease
        self.c._model_launch_permit = lease.lease_id
        Worker(self.root).bind_checkpoint(None, self.c, None, None, None)
        with patch.dict(model_runtime.os.environ, {'UNBUG_MODEL_CGROUP_ROOT': ''}), \
                patch('processes.prepare_model_containment') as prepare:
            def boundary(*args, **kwargs):
                prepare.assert_called_once_with(self.root)
                raise budget.BudgetError('test_boundary')
            with patch.object(model_runtime, 'case_budget_boundary', side_effect=boundary):
                with self.assertRaisesRegex(budget.BudgetError, 'test_boundary'):
                    self.runtime._invoke(self.c, [lease.route], 'x', self.root, 'builder-1')

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
        budget.mark_launched(self.ledger, lease.lease_id)   # the call's process may be spending
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

    def test_a_call_that_never_launched_settles_at_zero(self):
        """case-import-f46dac-3, November: an admit attempt booked its $45.70 hold with 0 calls."""
        from durable.worker_step import Worker, ledger_totals
        self.ledger.write_text(json.dumps({'calls': 0, 'events': [], 'cost': 0}))
        worker = Worker(self.root)
        si = SimpleNamespace(idempotency_key=self.attempt.key, money_ceiling_usd_micros=50_000_000)
        worker.paths(si.idempotency_key)['attempt'].mkdir(parents=True)
        worker._save_baseline(si, self.ledger, ledger_totals(self.ledger))
        lease = self.lease()
        self.reserve(lease)                               # reserved, then the worker died before launch
        self.assertEqual(worker._failure_result(si.idempotency_key, 'infra:deadline').usage.paid_usd_micros, 0)
        # Admission still counts the hold while it is pending: it could launch at any moment.
        second = self.lease()
        with self.assertRaisesRegex(budget.BudgetError, 'grant_insufficient'):
            self.reserve(second)
        budget.reconcile_reservations(self.root, self.ledger)
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual(ledger['invocation_reservations'][lease.lease_id]['state'], 'settled')
        self.assertEqual(ledger_totals(self.ledger)['total'], 0)
        self.assertIsNotNone(budget.usage_coverage(ledger))
        self.reserve(second)                              # the whole grant is free again

    def test_parallel_cheap_calls_are_both_funded_within_the_grant(self):
        """6-11 November: an OpenRouter call reserved the whole grant, and the call beside it in the
        same attempt failed grant_insufficient. Each now reserves at most CHEAP_CALL_WINDOW_USD."""
        paid = 'openrouter/minimax/minimax-m3.1-flash'
        self.c.card['roles']['writer']['model'] = paid
        self.c.router_accounts = NO_GO
        self.store.capacities['openrouter-key'] = 4
        window = Decimal(str(model_runtime.CHEAP_CALL_WINDOW_USD))
        both, release, windows = threading.Barrier(2, timeout=5), threading.Event(), []
        def transport(c, *args, **kwargs):
            c.model_process_state['started'] = True
            windows.append(Decimal(str(c.model_lease.max_usd)))
            both.wait()                                   # both calls hold their reservations at once
            ledger = json.loads(self.ledger.read_text())
            self.assertLessEqual(budget.outstanding_reservations(ledger), self.attempt.ceiling_usd)
            state = model_call_gate.Allowance(c.model_lease)
            request = state.reserve(1); self.assertIsNotNone(request)
            state.finish(request, dict(prompt_tokens=10, completion_tokens=1, total_tokens=11))
            state.close(); c.model_cap_used = state.snapshot()
            return 0
        with patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=transport), \
                ThreadPoolExecutor(2) as pool:
            calls = [pool.submit(self.runtime.call, self.c, [paid], 'x', self.root, name)
                     for name in ('stress-1', 'reviewer-1')]
            self.assertEqual([f.result(timeout=10) for f in calls], [0, 0])
        self.assertEqual(windows, [window, window])
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual(sorted(r['state'] for r in ledger['invocation_reservations'].values()), ['settled', 'settled'])
        self.assertEqual(budget.outstanding_reservations(ledger), 0)

    def test_a_non_final_codex_stress_call_books_at_most_the_cheap_window(self):
        """22e434-5 (11 November): a Codex attacker refused mid-turn after $0.17 of reported usage. Its
        receipt was non-final, so settlement booked its whole funded window ($48.68 of a $49.40 grant)
        and the next attacker call failed grant_insufficient. Stress is now capped on every family."""
        codex = 'codex/gpt-6.1-sol'
        self.store.capacities['codex-auth.json'] = 1
        self.attempt.ceiling_usd = Decimal('49.403501')
        windows = []
        def transport(c, models, text, cwd, name, *args, **kwargs):
            c.model_process_state['started'] = True
            windows.append(Decimal(str(c.model_lease.max_usd)))
            row = c.invocation_reservation
            with budget.ledger_transaction(self.ledger) as ledger:   # six reported Codex requests
                event = {'id': row['invocation_id'] + ':request-0', 'cost': 0, 'priced': 'subscription',
                         'estimated_subscription_cost_usd': 0.1664484, 'calls': 17,
                         'invocation': name, 'invocation_id': row['invocation_id'], 'lease_id': row['lease_id']}
                ledger['events'].append(event)
                ledger['invocation_reservations'][row['lease_id']]['event_ids'].append(event['id'])
            raise budget.BudgetError('refusal:' + codex)   # Codex flagged the attack mid-turn
        with patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=transport), \
                patch.object(model_router, '_credential_ready', return_value=True), \
                self.assertRaises(model_router.ProviderWait):   # Codex's one lane is excluded after it
            self.runtime.call(self.c, [codex], 'x', self.root, 'attacker-1', deadline=time.monotonic() + 2)
        window = Decimal(str(model_runtime.CHEAP_CALL_WINDOW_USD))
        self.assertEqual(windows, [window])
        ledger = json.loads(self.ledger.read_text())
        row = next(iter(ledger['invocation_reservations'].values()))
        self.assertEqual(row['state'], 'estimated')
        spent = budget.case_spending(ledger)['total_spent_usd']
        self.assertLessEqual(Decimal(str(spent)), window)          # was $48.68 on 22e434-5
        usage = worker_step.usage_since({'calls': 0, 'total': Decimal(0), 'known': Decimal(0), 'list': Decimal(0)},
                                        self.ledger, 49_403_501)
        self.assertLessEqual(usage.paid_usd_micros, 12_500_000)
        # The case is not money-exhausted: the next attacker call is still funded.
        self.assertGreater(Decimal(budget.available_invocation_funding(self.ledger, self.attempt)), 30)

    def test_writer_keeps_the_funded_window_and_stress_and_a_reviewer_are_capped(self):
        """An in-flight role finishes (FACTORY.md section 4): a long writer session keeps the whole
        funded window; stress and review calls are capped at CHEAP_CALL_WINDOW_USD."""
        paid = 'openrouter/minimax/minimax-m3.1-flash'
        self.c.card['roles']['writer']['model'] = paid
        self.c.router_accounts = NO_GO
        self.attempt.ceiling_usd = Decimal('40')
        windows = {}
        def transport(c, models, text, cwd, name, *args, **kwargs):
            c.model_process_state['started'] = True
            windows[name] = Decimal(str(c.model_lease.max_usd))
            state = model_call_gate.Allowance(c.model_lease)
            state.close(); c.model_cap_used = state.snapshot()
            return 0
        with patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=transport):
            for name in ('builder-1', 'attacker-1', 'reviewer-1', 'strong-calibrator-1'):
                self.assertEqual(self.runtime.call(self.c, [paid], 'x', self.root, name), 0)
        self.assertEqual(windows, {'builder-1': Decimal('40'), 'attacker-1': Decimal('12.5'),
                                   'reviewer-1': Decimal('12.5'), 'strong-calibrator-1': Decimal('12.5')})

    def test_codex_judges_are_capped_and_a_codex_writer_keeps_its_window(self):
        """86b100-r9 (11 November): a Codex strong calibrator (G16 judge_breadth) took a $48.71
        window, a parallel lane reserved first, and the case was held grant_insufficient with $41
        unspent. Every role but the writer is now capped on every family."""
        codex = 'codex/gpt-6.1-sol'
        self.c.card['roles']['writer']['model'] = codex
        self.store.capacities['codex-auth.json'] = 4
        self.attempt.ceiling_usd = Decimal('49.403501')
        windows = {}
        def transport(c, models, text, cwd, name, *args, **kwargs):
            c.model_process_state['started'] = True
            windows[name] = Decimal(str(c.model_lease.max_usd))
            state = model_call_gate.Allowance(c.model_lease)
            state.close(); c.model_cap_used = state.snapshot()
            return 0
        with patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=transport), \
                patch.object(model_router, '_credential_ready', return_value=True):
            for name in ('strong-calibrator-1', 'reviewer-1', 'builder-1'):
                self.assertEqual(self.runtime.call(self.c, [codex], 'x', self.root, name), 0)
        window = Decimal(str(model_runtime.CHEAP_CALL_WINDOW_USD))
        self.assertEqual(windows['strong-calibrator-1'], window)
        self.assertEqual(windows['reviewer-1'], window)
        self.assertGreater(windows['builder-1'], window)

    def test_cheap_windows_never_exceed_the_case_grant(self):
        paid = 'openrouter/minimax/minimax-m3.1-flash'
        self.c.card['roles']['writer']['model'] = paid
        self.c.router_accounts = NO_GO
        self.store.capacities['openrouter-key'] = 10
        self.attempt.ceiling_usd = Decimal('30')
        entered, release, windows = threading.Semaphore(0), threading.Event(), []
        def transport(c, *args, **kwargs):
            c.model_process_state['started'] = True
            windows.append(Decimal(str(c.model_lease.max_usd)))
            entered.release()
            self.assertTrue(release.wait(5))
            state = model_call_gate.Allowance(c.model_lease)
            state.close(); c.model_cap_used = state.snapshot()
            return 0
        with patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=transport), \
                ThreadPoolExecutor(3) as pool:
            calls = []
            for name in ('reviewer-1', 'reviewer2-1', 'stress-1'):   # each holds its window, in turn
                calls.append(pool.submit(self.runtime.call, self.c, [paid], 'x', self.root, name))
                self.assertTrue(entered.acquire(timeout=5))
            # Two windows fit; the third gets what is left; a fourth gets nothing.
            self.assertEqual(windows, [Decimal('12.5'), Decimal('12.5'), Decimal('5')])
            with self.assertRaisesRegex(budget.BudgetError, 'grant_insufficient'):
                self.runtime.call(self.c, [paid], 'x', self.root, 'reviewer-2')
            ledger = json.loads(self.ledger.read_text())
            self.assertEqual(budget.outstanding_reservations(ledger), self.attempt.ceiling_usd)
            release.set()
            self.assertEqual([f.result(timeout=10) for f in calls], [0, 0, 0])

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
            **next(r for r in model_router.routes(route) if r['route'] == route), **model_router.route_maximum(route))
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

    def go_lease(self, route='opencode-go/deepseek-v4.1-flash', funded='5'):
        return model_router.Lease(lease_id=uuid.uuid4().hex, expires_at=time.time()+60,
            **next(r for r in model_router.routes(route) if r['route'] == route), **model_router.funded_maximum(route, funded))

    def run_go(self, lease, row, costs, tokens):
        events = [dict(type='step_finish', sessionID='s', part=dict(id=f'p{i}', messageID=f'm{i}', cost=cost, tokens=tokens))
                  for i, cost in enumerate(costs)]
        command = [sys.executable, '-c', ''.join('print('+repr(json.dumps(e))+');' for e in events)]
        budget.run_budgeted(command, self.root, {}, self.root/'transcript', self.ledger, 3,
            max_cost=None, case_budget=50, configured_model=lease.route, concurrent=True,
            attempt=self.attempt, invocation_id=row['invocation_id'], lease_id=lease.lease_id,
            containment=False)

    def test_a_go_step_books_no_money_and_keeps_its_twin_list_value_for_its_bound(self):
        # Founder 2026-11-09, "book Go at cost": the Go plan pays (Extra Usage off), so a Go step
        # books $0 to case and batch money. Before, it booked its OpenRouter twin's list price, and
        # cae763-2 and 22e434-3 used their $50 with no real spend. A $0 report still completes with
        # known usage (review of #66): it is not unpriced, it is the plan's price.
        lease = self.go_lease()
        row = self.reserve(lease)
        tokens = dict(input=1000, output=2000, reasoning=500, cache=dict(read=4000, write=0))
        self.run_go(lease, row, (0, 1e-9), tokens)
        # Twin: $0.14/M input, $0.42/M output and reasoning, $0.0042/M cache read.
        step = (1000 * .14 + 2500 * .42 + 4000 * .0042) / 1_000_000
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual(ledger['terminal_stop'], 'complete')
        self.assertEqual([e['cost'] for e in ledger['events']], [0, 0])
        self.assertEqual([e['plan_list_cost_usd'] for e in ledger['events']], [step, step])
        self.assertEqual(ledger['cost'], 0)
        self.assertAlmostEqual(ledger['plan_list_cost_usd'], 2 * step)
        self.assertEqual(budget.case_spending(ledger)['total_spent_usd'], 0)
        self.assertEqual(ledger['invocation_reservations'][lease.lease_id]['event_ids'], ['s:m0:p0', 's:m1:p1'])
        # The running call is still held to its maximum by its list value.
        self.assertAlmostEqual(float(budget.outstanding_reservations(ledger)), 5 - 2 * step)
        # What the durable ledger books for the attempt: only the still-pending hold, nothing for the
        # steps themselves, and their list value as list price.
        usage = worker_step.usage_since({'calls': 0, 'total': Decimal(0), 'known': Decimal(0), 'list': Decimal(0)},
                                        self.ledger, 50_000_000)
        held = worker_step._micros_up(budget.outstanding_reservations(ledger))
        self.assertEqual((usage.calls, usage.paid_usd_micros), (2, held))
        self.assertEqual(usage.list_usd_micros, worker_step._micros_up(Decimal(str(ledger['plan_list_cost_usd']))))

    def test_a_go_call_is_still_stopped_at_its_twin_maximum(self):
        # Bounded per call: a Go call whose list value passes its reservation stops, as a paid one would.
        lease = self.go_lease(funded='0.001')
        row = self.reserve(lease)
        big = dict(input=10_000, output=10_000, reasoning=0, cache=dict(read=0, write=0))   # $0.0056 at the twin
        with self.assertRaises(budget.BudgetError) as stop:
            self.run_go(lease, row, (0,), big)
        self.assertEqual(str(stop.exception), 'usage_reservation_exceeded')
        self.assertEqual(budget.case_spending(json.loads(self.ledger.read_text()))['total_spent_usd'], 0)

    def test_a_go_call_with_unknown_final_usage_books_no_gap(self):
        # Its unseen tail is paid by the plan too; the whole maximum used to be booked as case money.
        lease = self.go_lease()
        row = self.reserve(lease)
        receipt = dict(lease_id=lease.lease_id, final_usage_known=False, events=[], booked_event_ids=[],
                       outcome='interrupted')
        directory = self.root / 'usage-receipts'; directory.mkdir(exist_ok=True)
        (directory / (lease.lease_id + '.json')).write_text(json.dumps(receipt))
        budget.complete_invocation(self.root, self.ledger, lease.lease_id)
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual(Decimal(ledger['invocation_reservations'][lease.lease_id]['estimated_gap_usd']), 0)
        self.assertEqual(budget.case_spending(ledger)['total_spent_usd'], 0)
        self.assertEqual(budget.outstanding_reservations(ledger), 0)
        self.assertNotEqual(Decimal(row['maximum_usd']), 0)

    def test_runtime_passes_reservation_to_real_monitor_and_settles(self):
        usage = dict(input_tokens=1, output_tokens=1, cache_read_input_tokens=0,
                     cache_creation_input_tokens=0)
        event = dict(type='result', session_id='synthetic', is_error=False,
                     total_cost_usd=.25, usage=usage)
        def transport(cmd, cwd, env, *args, **kwargs):
            self.assertIs(kwargs['attempt'], self.attempt)
            self.assertNotIn('job_authority', kwargs)
            command = [sys.executable, '-c', 'print('+repr(json.dumps(event))+')']
            return budget.run_budgeted(command, cwd, env, *args,
                                       **{**kwargs, 'containment': False})
        # Replace only CLI transport; keep runtime reservation, real provider gate,
        # usage monitor, receipt generation and settlement.
        with patch.object(model_runtime, 'pinned_cli', return_value='synthetic'), \
             patch.object(model_runtime, 'run_budgeted', side_effect=transport):
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

    def test_monitor_refuses_mismatched_reservation_before_process_start(self):
        lease = self.lease()
        row = self.reserve(lease)
        started = Mock()
        settings = dict(max_cost=None, configured_model=lease.route, attempt=self.attempt,
            invocation_id=row['invocation_id'], lease_id=lease.lease_id,
            on_started=started, containment=False)
        for change in (dict(invocation_id='wrong'), dict(lease_id='wrong'),
                       dict(configured_model='claude/unknown')):
            with self.subTest(change=change), patch.object(budget.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(budget.BudgetError, 'reservation_mismatch'):
                    budget.run_budgeted([sys.executable, '-c', 'raise AssertionError()'],
                        self.root, {}, self.root/'refused-transcript', self.ledger, 3,
                        **{**settings, **change})
                spawn.assert_not_called()
                started.assert_not_called()

    def test_replayed_reservation_refuses_each_changed_binding(self):
        lease = self.lease()
        row = self.reserve(lease)
        before = self.ledger.read_bytes()
        settings = dict(attempt=self.attempt, operation_id=row['operation_id'],
                        call_name=row['call_name'], parent_call_name=None)
        for change in (dict(operation_id=str(uuid.uuid4())), dict(call_name='builder-other'),
                       dict(parent_call_name='other-owner')):
            with self.subTest(change=change), self.assertRaisesRegex(budget.BudgetError, 'reservation_mismatch'):
                budget.reserve_invocation(self.ledger, lease, lease.max_usd, **{**settings, **change})
        with self.assertRaisesRegex(budget.BudgetError, 'reservation_mismatch'):
            budget.reserve_invocation(self.ledger, lease, lease.max_usd + 1, **settings)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_attempt_ceiling_cannot_change_after_reservation(self):
        self.reserve(self.lease())
        before = self.ledger.read_bytes()
        self.attempt.ceiling_usd = 100
        with self.assertRaisesRegex(budget.BudgetError, 'reservation_mismatch'):
            self.reserve(self.lease())
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_missing_attempt_baseline_refuses_before_funding(self):
        self.attempt.baseline_spent_usd = None
        with self.assertRaisesRegex(budget.BudgetError, 'usage_unknown'):
            self.reserve(self.lease())
        self.assertFalse(self.ledger.exists())

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

    def test_a_gate_that_refused_every_request_books_nothing(self):
        # b5521c, 7 November: a Claude preflight whose first request could not fit its hold
        # was booked as spending the whole hold, three times, though nothing reached Anthropic.
        def settle(cap):
            lease = self.lease()
            row = self.reserve(lease)
            receipt = dict(lease_id=lease.lease_id, final_usage_known=False, events=[], booked_event_ids=[],
                           outcome='interrupted', cap_used=cap)
            directory = self.root / 'usage-receipts'; directory.mkdir(exist_ok=True)
            (directory / (lease.lease_id + '.json')).write_text(json.dumps(receipt))
            budget.complete_invocation(self.root, self.ledger, lease.lease_id)
            model_router.finish(lease.lease_id, 'interrupted', 'usage-receipts/' + lease.lease_id + '.json')
            return row, json.loads(self.ledger.read_text())['invocation_reservations'][lease.lease_id]
        probe = self.lease()
        gate = model_call_gate.Allowance(replace(probe, max_usd=1.0), deadline=time.monotonic()+2)
        model_router.finish(probe.lease_id, 'denied', None)
        self.assertIsNone(gate.reserve(32768))           # the hold does not fit: refused, never forwarded
        gate.close()
        refused = gate.snapshot()
        self.assertEqual((refused['forwarded_requests'], refused['exhausted'], refused['closed']), (0, True, True))
        _, row = settle(refused)
        self.assertEqual(Decimal(row['estimated_gap_usd']), 0)
        # An unstarted gate's default snapshot still keeps the whole maximum.
        reserved, row = settle(model_call_gate.empty_usage(ROUTE))
        self.assertEqual(Decimal(row['estimated_gap_usd']), Decimal(reserved['maximum_usd']))

    def test_request_hold_is_the_gate_reservation(self):
        lease = self.lease()
        model_router.finish(lease.lease_id, 'denied', None)
        hold = model_call_gate.request_hold(lease.route)
        gate = model_call_gate.Allowance(replace(lease, max_usd=float(hold) - 0.01), deadline=time.monotonic()+2)
        self.assertIsNone(gate.reserve(model_call_gate.worst_request(lease.route)['output_tokens']
                                       if lease.route in model_call_gate.CLAUDE_PROFILES else model_call_gate.OPENROUTER_OUTPUT))
        # ...and accepts exactly the hold plus the gate's headroom: the hold is not overstated.
        fits = model_call_gate.Allowance(replace(lease, max_usd=float(hold + model_call_gate.HEADROOM)), deadline=time.monotonic()+2)
        self.assertIsNotNone(fits.reserve(model_call_gate.worst_request(lease.route)['output_tokens']
                                          if lease.route in model_call_gate.CLAUDE_PROFILES else model_call_gate.OPENROUTER_OUTPUT))
        fits.close()
        self.assertEqual(model_call_gate.request_hold('claude/claude-opus-5-5'), Decimal('9.520896'))
        self.assertIsNone(model_call_gate.request_hold('codex/gpt-6.1-sol'))


    def test_unconfirmed_openrouter_requests_hold_only_their_clamped_output(self):
        """18681d (12 November): 19 of an easy calibrator's 75 GLM requests ended without stream
        usage. Each retained a hold priced at the model's 943,718-token output limit ($0.63), though
        every body is clamped to OPENROUTER_OUTPUT, and the call stopped model_call_cap at $0.17 spent."""
        glm = 'openrouter/z-ai/glm-5.3-flash'
        worst = model_call_gate.worst_request(glm, model_call_gate.OPENROUTER_OUTPUT)
        self.assertEqual(worst['completion_tokens'], model_call_gate.OPENROUTER_OUTPUT)
        self.assertEqual(model_call_gate.worst_request(glm), worst)          # the clamp is the default
        hold = model_call_gate.request_hold(glm)
        self.assertLess(hold, Decimal('0.2'))
        lease = SimpleNamespace(route=glm, max_usd=12.5, max_input_tokens=83333333, max_output_tokens=24999994)
        gate = model_call_gate.Allowance(lease, deadline=time.monotonic() + 5)
        for _ in range(19):                                                   # no usage on the stream
            identity = gate.reserve(model_call_gate.OPENROUTER_OUTPUT); self.assertIsNotNone(identity)
            gate.finish(identity, None)
        for _ in range(56):
            identity = gate.reserve(model_call_gate.OPENROUTER_OUTPUT); self.assertIsNotNone(identity)
            gate.finish(identity, dict(prompt_tokens=35000, completion_tokens=150))
        self.assertFalse(gate.exhaustion.is_set())
        gate.close()

if __name__ == '__main__': unittest.main()
