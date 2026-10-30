"""Control-flow replays using saved public ledgers and practice-case bytes.

Model outputs, provider conditions and the job config are authored test inputs.
Only Python stream emitters and the real local router/HTTP protocol execute;
there is no model CLI, cloud launch, decryption or real crash-artifact claim.
These tests do not close Murphy rows or qualify B/E rollout.
"""
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import coordinator
import durable_checkpoint
import exam_responder
import job_authority
import model_router
import model_runtime
import run
from router_test_support import offline_router, synthetic_maximum
from test_stream_d import cards


class Killed(BaseException): pass


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.patch(run, 'BENCH', ROOT)
        router, self.store = offline_router(); self.addCleanup(router.close)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.case = self.work / 'case'; self.case.mkdir()
        (self.work / 'transcripts').mkdir()
        practice = json.loads(gzip.decompress((ROOT / 'tests/factory/fixtures/invalid-runs-practice.json.gz').read_bytes()))
        for name, value in practice['files'].items():
            data = value.encode()
            self.assertEqual(hashlib.sha256(data).hexdigest(), practice['sha256'][name])
            target = self.case / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        # A genuine ledger already beyond the old $5 priced-provider cap.
        self.source = next(row['card'] for row in cards() if row['card']['case'].endswith('5813be'))
        self.ledger = self.work / 'ledger.json'; self.ledger.write_text(json.dumps(self.source['continuation_budget']))
        self.channel = json.loads((ROOT / 'tests/fixtures/factory/stream-d/job-money.json').read_text())
        self.channel.update(case=self.source['case'], source_generation=self.source['sha256'])
        args = run.argument_parser().parse_args(['--source', 'hunt', '--batch-release-sha256', 'a' * 64])
        writer, stress, reviewer, strong = ('claude/claude-opus-5-5', 'opencode/minimax-m3.1-flash-free',
                                           'openrouter/deepseek/deepseek-v4.1-flash', 'codex/gpt-6.1-sol')
        self.c = c = SimpleNamespace(work=self.work, case=self.case, ledger=self.ledger, args=args,
            case_id=self.source['case'], seed=7, manifest0='public-practice-control-flow', role_cancel=threading.Event(),
            card={'case': self.source['case'], 'builder_rounds': 0, 'roles': {
                role: {'model': model} for role, model in zip(('writer', 'stress_tester', 'reviewer', 'strong_calibrator'),
                                                             (writer, stress, reviewer, strong))}},
            models={'builder': [writer], 'attacker': [stress], 'reviewers': [[reviewer]], 'strong_calibrator': [strong]},
            job_money=self.channel, authenticated_job_config={'job_money': copy.deepcopy(self.channel)},
            batch_id=self.channel['batch'], job_id=self.channel['job'], batch_deadline=self.channel['batch_deadline'],
            source_generation=self.channel['source_generation'])
        self.baseline = budget.case_spending(self.source['continuation_budget'])['total_spent_usd']
        self.patch(model_router, 'metadata', return_value=(c.batch_id, c.job_id, model_router.epoch(c.batch_deadline)))
        bounds = {'requests': 1, 'input_tokens': 1000, 'output_tokens': 1000, 'tool_fees_usd': '0'}
        from token_prices import invocation_maximum
        configured = {model: {**synthetic_maximum(model), 'max_usd': float(invocation_maximum(model, bounds))}
                      for model in (writer, stress, reviewer, strong)}
        # Accounting/control-flow only: these synthetic bounds do not qualify a route.
        self.bounds = patch.object(model_router, 'route_maximum', configured.get)
        self.bounds.start(); self.addCleanup(self.bounds.stop)

    def patch(self, target, name, *args, **kwargs):
        patched = patch.object(target, name, *args, **kwargs)
        value = patched.start(); self.addCleanup(patched.stop); return value

    def receipt(self, role='writer'):
        return {'round': 1, 'round_limit': 8, 'binding': {'case': 'control-input'}, 'report': 'round-1.json',
                'actor': role, 'repair_pending' if role == 'writer' else 'review_pending': True,
                'release_rereviews': [], 'release_review_attempts': [], 'next_phase': 'G1' if role == 'writer' else 'gates',
                **({'review_attempt': uuid.uuid4().hex} if role == 'stress_tester' else {})}

    def test_pre_route_failure_preserves_original_error_after_double_release(self):
        for family_change in (False, True):
            with self.subTest(family_change=family_change):
                self.ledger.write_text(json.dumps(self.source['continuation_budget']))
                self.c.card['builder_rounds'] = 0
                self.c.card['roles']['writer']['model'] = (
                    self.c.models['strong_calibrator'][0] if family_change else self.c.models['builder'][0])
                error = ValueError if family_change else budget.BudgetError
                message = 'role family changed' if family_change else 'money_wait'
                with patch.object(model_runtime, 'case_budget_boundary',
                                  side_effect=None if family_change else budget.BudgetError('money_wait')):
                    with self.assertRaisesRegex(error, '^' + message + '$'):
                        run.pending_call(self.c, self.c.models['builder'], 'pre-route failure', self.case,
                            'builder-1', self.receipt(), role='writer', on_complete=lambda: None)
                ledger = json.loads(self.ledger.read_text())
                row, = ledger['invocation_reservations'].values()
                self.assertEqual((row['state'], row['event_ids'], row['estimated_gap_usd']),
                                 ('settled', [], '0.000000000'))
                self.assertEqual(budget.case_spending(ledger)['total_spent_usd'], self.baseline)

    def test_stream_accountant_links_unknown_usage_and_settles_once_above_five_dollars(self):
        self.assertGreater(self.source['continuation_budget']['cost'], 5)
        lease = model_router.Lease(str(uuid.uuid4()), self.c.models['builder'][0], 'claude-token', 1,
                                   'subscription', 'anthropic', 'claude-token',
                                   **synthetic_maximum(self.c.models['builder'][0]))
        authority = job_authority.for_case(self.c)
        row = budget.reserve_invocation(self.ledger, lease, 100, authority,
            operation_id=str(uuid.uuid4()), call_name='builder-stream-test')
        # Authored CLI envelopes hit the real streaming accountant; no CLI/model starts.
        stream = [{'type': 'system', 'subtype': 'init', 'session_id': 'stream-test'}, {'type': 'result', 'is_error': True}]
        code = '\n'.join('print(' + repr(json.dumps(event)) + ', flush=True)' for event in stream)
        with self.assertRaisesRegex(budget.BudgetError, '^claude_error$'):
            budget.run_budgeted([sys.executable, '-c', code], self.work, os.environ.copy(), self.work / 'stream.jsonl',
                self.ledger, 3, max_cost=None, driver='claude', configured_model=lease.route, role='writer',
                invocation_name='builder-stream-test', case_budget=200, job_authority=authority,
                invocation_id=row['invocation_id'], lease_id=lease.lease_id, concurrent=True, resume=True,
                max_total_calls=self.source['continuation_budget']['calls'] + 10)
        current = json.loads(self.ledger.read_text())
        self.assertEqual(current['unpriced_invocations'][0]['invocation_id'], row['invocation_id'])
        budget.reconcile_reservations(self.work, self.ledger)
        current = json.loads(self.ledger.read_text())
        self.assertEqual(current['unpriced_invocations'], [])
        self.assertEqual(budget.case_spending(current)['total_spent_usd'], round(self.baseline + 100, 9))
        budget.reconcile_reservations(self.work, self.ledger)
        self.assertEqual(json.loads(self.ledger.read_text()), current)

    def test_real_high_call_cards_continue_with_telemetry_and_invocation_limit_stays(self):
        for suffix, count in (('5813be', 2496), ('e15450', 1627), ('873d7f', 1040)):
            with self.subTest(case=suffix):
                card = next(r['card'] for r in cards() if r['card']['case'].endswith(suffix)
                            and r['card']['continuation_budget']['calls'] == count)
                original = copy.deepcopy(card['continuation_budget'])
                self.ledger.write_text(json.dumps(original))
                lease = model_router.Lease(uuid.uuid4().hex, self.c.models['attacker'][0], 'free', 1,
                                           'free', 'minimax', 'free', **synthetic_maximum(self.c.models['attacker'][0]))
                authority = job_authority.for_case(self.c)
                row = budget.reserve_invocation(self.ledger, lease, 1, authority,
                    operation_id=str(uuid.uuid4()), call_name='builder-telemetry')
                event = {'type': 'step_finish', 'part': {'id': 'telemetry-' + suffix, 'messageID': 'message-' + suffix, 'cost': 0,
                                                       'tokens': {'input': 1, 'output': 1, 'reasoning': 0,
                                                                  'cache': {'read': 0, 'write': 0}}}}
                code = 'print(' + repr(json.dumps(event)) + ', flush=True)'
                budget.run_budgeted([sys.executable, '-c', code], self.work, os.environ.copy(),
                    self.work / ('telemetry-' + suffix + '.jsonl'), self.ledger, 3,
                    max_cost=None, max_calls=2, max_total_calls=1000, driver='opencode',
                    configured_model=lease.route, role='writer', invocation_name='builder-telemetry',
                    case_budget=200, job_authority=authority, invocation_id=row['invocation_id'],
                    lease_id=lease.lease_id, concurrent=True, resume=True)
                after = json.loads(self.ledger.read_text())
                self.assertGreater(after['calls'], count)
                self.assertEqual(after['events'][:len(original['events'])], original['events'])
                self.assertEqual(budget.case_spending(after)['total_spent_usd'],
                                 budget.case_spending(original)['total_spent_usd'])
                card = {**card, 'batch_release_sha256': 'a' * 64, 'continuation_budget': after}
                self.assertIn(f"model calls: {after['calls']} (telemetry)", run.scorecard_text(card))
                event['part']['id'] += '-second'
                code = 'print(' + repr(json.dumps(event)) + ', flush=True)'
                with self.assertRaisesRegex(budget.BudgetError, '^call_limit$'):
                    budget.run_budgeted([sys.executable, '-c', code], self.work, os.environ.copy(),
                        self.work / ('capped-' + suffix + '.jsonl'), self.ledger, 3,
                        max_cost=None, max_calls=1, max_total_calls=1000, driver='opencode',
                        configured_model=lease.route, role='writer', invocation_name='builder-telemetry',
                        case_budget=200, job_authority=authority, invocation_id=row['invocation_id'],
                        lease_id=lease.lease_id, concurrent=True, resume=True)

    def test_denied_before_admission_changes_no_reservation_round_or_receipt(self):
        for account in ('claude-token', 'claude-factory-token-2'): self.store.capacities[account] = 0
        before = self.ledger.read_bytes()
        invoke = self.patch(model_runtime.ModelRuntime, '_invoke', side_effect=AssertionError('CLI must not start'))
        with self.assertRaises(model_router.ProviderWait) as error:
            run.pending_call(self.c, self.c.models['builder'], 'retained findings', self.case, 'builder-1', self.receipt(),
                             role='writer', on_complete=lambda: self.fail('must not complete'))
        self.assertIsNone(error.exception.wait.lease_id)
        self.assertEqual(self.c.card['builder_rounds'], 0)
        self.assertFalse((self.work / 'attack-state.json').exists())
        self.assertEqual(self.ledger.read_bytes(), before); invoke.assert_not_called()

    def test_missing_stale_or_expired_authority_refuses_before_router_admission(self):
        admit = self.patch(model_router, 'await_lease', side_effect=AssertionError('must not admit'))
        for change, reason in (({'job_money': None}, 'money_wait'),
                               ({'source_generation': 'f' * 64}, 'money_wait'),
                               ({'job_money': {**self.channel, 'batch_deadline': '2020-01-01T00:00:00Z'},
                                 'authenticated_job_config': {'job_money': {**self.channel, 'batch_deadline': '2020-01-01T00:00:00Z'}}},
                                'retired_batch_bound')):
            with self.subTest(reason=reason), patch.multiple(self.c, **change):
                with self.assertRaisesRegex(budget.BudgetError, '^' + reason + '$'):
                    run.model_call(self.c, self.c.models['builder'], 'must refuse', self.case, 'builder-1')
                self.assertIsNotNone(model_runtime.update_case_budget(self.c)[1]['total_spent_usd'])
        admit.assert_not_called()
        self.assertNotIn('invocation_reservations', json.loads(self.ledger.read_text()))

    def test_unknown_route_bounds_release_lease_without_model_work_or_unit(self):
        self.patch(model_router, 'route_maximum', return_value=None)
        invoke = self.patch(model_runtime.ModelRuntime, '_invoke', side_effect=AssertionError('must not invoke'))
        with self.assertRaises(model_router.ProviderWait) as error:
            run.pending_call(self.c, self.c.models['builder'], 'must refuse', self.case, 'builder-1', self.receipt(),
                             role='writer', on_complete=lambda: self.fail('must not complete'))
        self.assertEqual(error.exception.wait.reason, 'unbounded_route')
        self.assertEqual(self.c.card['builder_rounds'], 0)
        self.assertFalse((self.work / 'attack-state.json').exists())
        self.assertNotIn('invocation_reservations', json.loads(self.ledger.read_text()))
        invoke.assert_not_called()

    def test_wrapper_pre_cli_renewal_failure_or_lost_credential_settles_zero(self):
        rpc, await_lease = model_router._rpc, model_router.await_lease
        for cause in ('renewal', 'credential'):
            with self.subTest(cause=cause):
                self.c.provider_resume_done = False
                if hasattr(self.c, 'model_resume_state'): self.c.model_resume_state['done'] = False
                def fail_renewal(operation, payload):
                    if operation == 'renew': raise model_router.RouterUnavailable('authored renewal blip')
                    return rpc(operation, payload)
                removed = []
                def lose_credential(role, c, deadline=None):
                    lease = await_lease(role, c, deadline)
                    path = model_router.SECRETS / lease.account
                    removed.append((path, path.read_bytes())); path.unlink()
                    return lease
                with patch.object(model_router, '_rpc', fail_renewal if cause == 'renewal' else rpc), \
                        patch.object(model_router, 'await_lease', lose_credential if cause == 'credential' else await_lease), \
                        patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=AssertionError('must not start')):
                    with self.assertRaises(model_router.ProviderWait) as error:
                        run.model_call(self.c, self.c.models['builder'], 'must not start', self.case, 'builder-pre-cli')
                for path, data in removed: path.write_bytes(data)
                record = run.write_provider_wait(self.c, error.exception)
                self.assertIsNotNone(record['lease_id'])
                leaf = json.loads((self.work / record['call_id']).read_text())
                self.assertEqual(leaf['outcome'], 'denied'); self.assertTrue(leaf['final_usage_known'])
                self.c.provider_resume_done = False; self.c.model_resume_state['done'] = False
                run.resume_provider_wait(self.c)
                self.assertFalse((self.work / 'provider_wait.json').exists())
                self.assertEqual(budget.case_spending(json.loads(self.ledger.read_text()))['total_spent_usd'], self.baseline)

    def test_pre_process_setup_failure_releases_reservation_at_zero(self):
        self.patch(model_runtime.ModelRuntime, '_invoke', side_effect=OSError('authored CLI setup failure'))
        with self.assertRaises(OSError):
            run.model_call(self.c, self.c.models['builder'], 'must not start', self.case, 'builder-setup')
        rows = list(json.loads(self.ledger.read_text())['invocation_reservations'].values())
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['state'], 'settled')
        self.assertEqual(rows[0]['estimated_gap_usd'], '0.000000000')
        self.assertEqual(budget.case_spending(json.loads(self.ledger.read_text()))['total_spent_usd'], self.baseline)

    def test_unreserved_receipt_requires_explicit_known_zero_denial(self):
        lease_id = str(uuid.uuid4())
        directory = self.work / 'usage-receipts'; directory.mkdir()
        relative = 'usage-receipts/' + lease_id + '.json'
        receipt = {'lease_id': lease_id, 'events': [], 'booked_event_ids': [], 'final_usage_known': True,
                   'outcome': 'denied', 'usage_delta': {'cost': 0}}
        (self.work / relative).write_text(json.dumps(receipt))
        record = {'wait_id': str(uuid.uuid4()), 'lease_id': lease_id, 'call_id': relative, 'settled': False}
        self.assertEqual(budget.settle(record, work=self.work, ledger_path=self.ledger), 0)
        self.assertEqual(budget.settle(record, work=self.work, ledger_path=self.ledger), 0)
        for change in ({'final_usage_known': False}, {'outcome': 'interrupted'},
                       {'usage_delta': {'cost': 1}}, {'unidentified_events': 1},
                       {'events': [{'id': 'unreserved', 'cost': 1}], 'booked_event_ids': ['unreserved']}):
            (self.work / relative).write_text(json.dumps({**receipt, **change}))
            before = self.ledger.read_bytes()
            with self.assertRaisesRegex(budget.BudgetError, '^usage_reservation_missing$'):
                budget.settle({**record, 'wait_id': str(uuid.uuid4()), 'settled': False}, work=self.work, ledger_path=self.ledger)
            self.assertEqual(self.ledger.read_bytes(), before)

    def test_batch_deadline_interrupt_is_unscored_retirement_not_contestant_timeout(self):
        lease = model_router.Lease(str(uuid.uuid4()), self.c.models['builder'][0], 'claude-token', 1,
                                   'subscription', 'anthropic', 'claude-token',
                                   **synthetic_maximum(self.c.models['builder'][0]))
        authority = replace(job_authority.for_case(self.c), batch_deadline=(
            datetime.now(timezone.utc) + timedelta(seconds=.2)).isoformat())
        row = budget.reserve_invocation(self.ledger, lease, 1, authority,
            operation_id=str(uuid.uuid4()), call_name='builder-deadline-test')
        with self.assertRaisesRegex(budget.BudgetError, '^retired_batch_bound$'):
            budget.run_budgeted([sys.executable, '-c', 'import time; time.sleep(5)'], self.work, os.environ.copy(),
                self.work / 'deadline.jsonl', self.ledger, 2, max_cost=None, driver='claude', configured_model=lease.route,
                role='writer', invocation_name='builder-deadline-test', case_budget=200, job_authority=authority,
                invocation_id=row['invocation_id'], lease_id=lease.lease_id, concurrent=True, resume=True,
                max_total_calls=self.source['continuation_budget']['calls'] + 10)
        budget.reconcile_reservations(self.work, self.ledger)
        current = json.loads(self.ledger.read_text())
        self.assertEqual(current['terminal_stop'], 'retired_batch_bound')
        self.assertEqual(budget.case_spending(current)['total_spent_usd'], round(self.baseline + 1, 9))

    def test_ordinary_threshold_uses_next_maximum_without_call_or_reservation(self):
        with budget.ledger_transaction(self.ledger) as ledger:
            ledger['list_cost_usd'] += 44 - self.baseline
        self.patch(model_runtime, 'invocation_maximum', return_value=Decimal(12))
        invoke = self.patch(model_runtime.ModelRuntime, '_invoke', side_effect=AssertionError('CLI must not start'))
        with self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            run.pending_call(self.c, self.c.models['builder'], 'retained findings', self.case, 'builder-1', self.receipt(),
                             role='writer', on_complete=lambda: self.fail('must not complete'))
        self.assertEqual(self.c.card['builder_rounds'], 0)
        self.assertNotIn('invocation_reservations', json.loads(self.ledger.read_text())); invoke.assert_not_called()

    def test_ordinary_limit_survives_card_rebuild_and_coordinator_binding(self):
        self.c.card['source'], self.c.card['rotation_slot'] = 'hunt', 1
        self.c.card['recovery_config'] = {'version': 1, **{name: getattr(self.c.args, name) for name in coordinator.CONFIG_FIELDS}}
        model_runtime.update_case_budget(self.c)
        previous = copy.deepcopy(self.c.card)
        self.assertEqual(previous['case_budget']['limit_usd'], 200)
        self.assertEqual(previous['recovery_config']['case_budget'], 50)
        # Also recover a card written by the earlier D runtime, where this field
        # incorrectly held the commitment. The explicit ordinary value wins.
        previous['recovery_config']['case_budget'] = 200
        job = {'args': ['release', '--source', 'hunt', '--rotation-slot', '1', '--case-budget', '50'],
               'roles': {name: {**role, 'effort': 'high'} for name, role in previous['roles'].items()}}
        proposed = coordinator.configuration_args(previous, job)
        ordinary_only = copy.deepcopy(previous); ordinary_only['recovery_config'].pop('case_budget')
        self.assertEqual(coordinator.configuration_args(ordinary_only, job), proposed)
        resumed = copy.copy(self.c); resumed.args = run.argument_parser().parse_args(proposed[1:])
        resumed.args.batch_release_sha256 = 'a' * 64
        resumed.card = {'roles': copy.deepcopy(previous['roles']), 'recovery_config': {'version': 1}}
        run.inherit_recovery_history(resumed, previous)
        _, summary = model_runtime.update_case_budget(resumed)
        self.assertEqual(summary['ordinary_limit_usd'], 50)
        self.assertEqual(summary['limit_usd'], 200)
        self.assertEqual(resumed.args.case_budget, 50)
        self.assertEqual(resumed.card['recovery_config']['case_budget'], 50)
        mismatch = copy.deepcopy(previous); mismatch['recovery_config']['ordinary_limit_usd'] = 100
        with self.assertRaisesRegex(budget.BudgetError, '^ordinary_limit_mismatch$'):
            run.inherit_recovery_history(resumed, mismatch)

    def test_writer_completion_checkpoints_then_resumes_validation_without_second_writer(self):
        self.c.recipient = 'synthetic-only'
        calls, checkpoints, kill = [], [], [True]
        def invoke(runtime, c, models, text, cwd, name, **kwargs):
            c.model_process_state['started'] = True
            calls.append(name)
            if name == 'builder-1': (self.case / 'draft.txt').write_text('completed writer unit')
            elif name == 'attacker-1': (self.work / 'attacks/round-1.json').write_text('{"complete":true,"blocking":[]}')
            else: self.fail(name)
            return 0
        def checkpoint(c, *args, **kwargs):
            receipt = json.loads((self.work / 'attack-state.json').read_text())
            self.assertEqual(receipt['phase'], 'completed'); checkpoints.append(receipt['actor'])
            if kill[0]: kill[0] = False; raise Killed()
        self.patch(model_runtime.ModelRuntime, '_invoke', invoke)
        self.patch(durable_checkpoint, 'checkpoint_progress', checkpoint)
        self.patch(run, 'prompt', lambda role, text: text)
        self.patch(run, 'run_context', lambda c, **kwargs: json.dumps(kwargs))
        self.patch(run, 'g1', lambda c: (True, {'problems': []}))
        self.patch(run, 'early_checks', lambda c: None); self.patch(run, 'early_review', lambda c: None)
        self.patch(run, 'loop_freshness', lambda c, result, report: (result, report))
        with self.assertRaises(Killed): run.write_and_attack(self.c, {})
        saved = json.loads((self.work / 'attack-state.json').read_text())
        self.assertFalse(saved['repair_pending']); self.assertEqual(saved['output_sha256'], run.case_hash(self.c))
        self.assertEqual(self.c.card['builder_rounds'], 1)
        self.c.args.resume = self.c.case_id
        self.c.provider_resume_done = False; self.c.model_resume_state['done'] = False
        run.write_and_attack(self.c, copy.deepcopy(self.c.card))
        self.assertEqual(calls, ['builder-1', 'attacker-1'])
        self.assertEqual(self.c.card['builder_rounds'], 1)
        self.assertEqual(self.c.card['stress_review'], {'status': 'completed', 'round': 1})
        self.assertEqual(checkpoints, ['writer', 'stress_tester'])

    def test_validated_writer_rebinding_resumes_stress_without_second_writer(self):
        calls, killed = [], [False]
        def invoke(runtime, c, models, text, cwd, name, **kwargs):
            c.model_process_state['started'] = True
            calls.append(name)
            if name == 'builder-1': (self.case / 'draft.txt').write_text('completed writer unit')
            elif name == 'attacker-1': (self.work / 'attacks/round-1.json').write_text('{"complete":true,"blocking":[]}')
            else: self.fail('unexpected new author round: ' + name)
            return 0
        boundary = run.case_budget_boundary
        def interrupt(c, *args, **kwargs):
            saved = run.jload(self.work / 'attack-state.json', {})
            if not killed[0] and saved.get('phase') == 'validated' and saved.get('awaiting_stress'):
                killed[0] = True; raise Killed()
            return boundary(c, *args, **kwargs)
        self.patch(model_runtime.ModelRuntime, '_invoke', invoke)
        self.patch(run, 'case_budget_boundary', interrupt)
        self.patch(run, 'prompt', lambda role, text: text)
        self.patch(run, 'g1', lambda c: (True, {'problems': []}))
        self.patch(run, 'early_checks', lambda c: None); self.patch(run, 'early_review', lambda c: None)
        self.patch(run, 'loop_freshness', lambda c, result, report: (result, report))
        with self.assertRaises(Killed): run.write_and_attack(self.c, {})
        saved = json.loads((self.work / 'attack-state.json').read_text())
        self.assertEqual(saved['phase'], 'validated'); self.assertEqual(self.c.card['builder_rounds'], 1)
        binding = run.attack_binding(self.c)
        self.patch(run, 'attack_binding', return_value={**binding, 'prompt': 'f' * 64})
        self.c.args.resume = self.c.case_id
        run.write_and_attack(self.c, copy.deepcopy(self.c.card))
        self.assertEqual(calls, ['builder-1', 'attacker-1'])
        self.assertEqual(self.c.card['builder_rounds'], 1)
        self.assertEqual(self.c.card['stress_review'], {'status': 'completed', 'round': 1})

    def test_pending_stress_rebind_keeps_round_one_at_ordinary_round_limit(self):
        self.stress_rebind('pending')

    def test_finished_stress_rebind_rereviews_before_delivering_findings(self):
        self.stress_rebind('finished')

    def stress_rebind(self, phase):
        self.c.args.rounds = 1 if phase == 'pending' else 2
        calls, first_stress, killed = [], [True], [False]
        units, writer_feedback = [], []
        def invoke(runtime, c, models, text, cwd, name, **kwargs):
            c.model_process_state['started'] = True
            calls.append(name)
            if name == 'builder-1': (self.case / 'draft.txt').write_text('completed writer unit')
            elif name == 'builder-2': writer_feedback.append(text); raise Killed()
            elif name == 'attacker-1':
                units.append(json.loads((self.work / 'attack-state.json').read_text()))
                if first_stress[0] and phase == 'pending':
                    first_stress[0] = False
                    raise budget.BudgetError('provider_limit:' + c.model_lease.route,
                        provider_failure={'reason': 'quota', 'scope': 'account', 'model': c.model_lease.route})
                (self.work / 'attacks/round-1.json').write_text(json.dumps({'complete': True,
                    'blocking': ['retained genuine defect'] if phase == 'finished' else []}))
            else: self.fail('renumbered stress: ' + name)
            return 0
        def freshness(c, result, report):
            if phase == 'finished' and not killed[0]: killed[0] = True; raise Killed()
            return result, report
        self.patch(model_runtime.ModelRuntime, '_invoke', invoke)
        self.patch(run, 'prompt', lambda role, text: text)
        self.patch(run, 'g1', lambda c: (True, {'problems': []}))
        self.patch(run, 'early_checks', lambda c: None); self.patch(run, 'early_review', lambda c: None)
        self.patch(run, 'loop_freshness', freshness)
        if phase == 'pending':
            with self.assertRaises(model_router.ProviderWait) as error: run.write_and_attack(self.c, {})
            run.write_provider_wait(self.c, error.exception)
        else:
            with self.assertRaises(Killed): run.write_and_attack(self.c, {})
        saved = json.loads((self.work / 'attack-state.json').read_text())
        self.assertEqual(saved['actor'], 'stress_tester'); self.assertEqual(saved['round'], 1)
        binding = run.attack_binding(self.c)
        self.patch(run, 'attack_binding', return_value={**binding, 'prompt': 'f' * 64})
        self.c.args.resume = self.c.case_id
        self.c.provider_resume_done = False; self.c.model_resume_state['done'] = False
        if phase == 'pending': run.write_and_attack(self.c, copy.deepcopy(self.c.card))
        else:
            with self.assertRaises(Killed): run.write_and_attack(self.c, copy.deepcopy(self.c.card))
        self.assertEqual(calls[:3], ['builder-1', 'attacker-1', 'attacker-1'])
        self.assertEqual(units[0]['operation_id'], units[1]['operation_id'])
        self.assertEqual(units[0]['review_attempt'], units[1]['review_attempt'])
        if phase == 'pending':
            self.assertEqual(self.c.card['builder_rounds'], 1)
            self.assertEqual(self.c.card['stress_review'], {'status': 'completed', 'round': 1})
        else:
            self.assertEqual(calls[3:], ['builder-2'])
            self.assertIn('retained genuine defect', writer_feedback[0])
            self.assertIn('round-1.json', writer_feedback[0])

    def test_three_waits_continue_the_same_writer_or_stress_unit(self):
        for role, key, name, pools, added in (
                ('writer', 'builder', 'builder-1', ('claude-token', 'claude-factory-token-2'), .056),
                ('stress_tester', 'attacker', 'attacker-1', ('opencode-go-key', 'opencode-go-key-2', 'openrouter-key'), 0)):
            with self.subTest(role=role):
                # Reset only the authored test context and actual source ledger.
                self.ledger.write_text(json.dumps(self.source['continuation_budget']))
                (self.work / 'attack-state.json').unlink(missing_ok=True)
                self.c.card['builder_rounds'] = 0
                self.c.provider_resume_done = False
                if hasattr(self.c, 'model_resume_state'): self.c.model_resume_state['done'] = False
                receipt = self.receipt(role)
                def invoke(runtime, c, *args, **kwargs):
                    c.model_process_state['started'] = True
                    raise budget.BudgetError('provider_limit:' + c.model_lease.route,
                        provider_failure={'reason': 'quota', 'scope': 'account', 'model': c.model_lease.route})
                def attempt():
                    with self.assertRaises(model_router.ProviderWait) as error:
                        run.pending_call(self.c, self.c.models[key], 'retained findings', self.case, name, receipt,
                                         role=role, on_complete=lambda: self.fail('must not complete'))
                    return run.write_provider_wait(self.c, error.exception)
                def resume():
                    self.c.provider_resume_done = False; self.c.model_resume_state['done'] = False
                    self.c.card.pop('terminal_stop', None); self.c.card.pop('provider_wait', None)
                    run.resume_provider_wait(self.c)
                    saved = json.loads((self.work / 'attack-state.json').read_text())
                    self.assertIsNone(saved['lease_id']); self.assertIsNone(saved['invocation_id'])
                    self.assertEqual(saved['operation_id'], operation)
                    self.assertTrue(run.provider_continuation(self.c, saved, role))
                    receipt.clear(); receipt.update(saved)
                with patch.object(model_runtime.ModelRuntime, '_invoke', invoke):
                    first = attempt(); operation = receipt['operation_id']; first_lease = first['lease_id']
                    self.assertIsNotNone(first_lease); resume()
                    for pool in pools: self.store.capacities[pool] = 0
                    second = attempt(); self.assertIsNone(second['lease_id']); self.assertIsNone(second['call_id']); resume()
                    for pool in pools: self.store.capacities[pool] = 1
                    third = attempt(); self.assertIsNotNone(third['lease_id']); self.assertNotEqual(third['lease_id'], first_lease); resume()
                current = json.loads(self.ledger.read_text())
                self.assertEqual(len(current['invocation_reservations']), 2)
                self.assertEqual(budget.case_spending(current)['total_spent_usd'], round(self.baseline + added, 9))
                self.assertEqual(self.c.card['builder_rounds'], 1 if role == 'writer' else 0)
                for path in (self.work / 'provider_waits').glob('*.json'):
                    # Only replays from this unit; older subtest archives name another ledger.
                    record = json.loads(path.read_text())
                    if record['role'] == role:
                        self.assertEqual(budget.settle(record, work=self.work, ledger_path=self.ledger), 0)
                self.assertFalse((self.work / 'provider_wait.json').exists())

    def test_flag_off_keeps_crash_reservation_without_forcing_router_deferral(self):
        observed, invoked = [], []
        await_lease = model_router.await_lease
        def admit(role, c, deadline=None):
            observed.append(getattr(c, 'router_deferred', False))
            return await_lease(role, c, deadline)
        def invoke(runtime, c, *args, **kwargs):
            c.model_process_state['started'] = True
            invoked.append(c.model_lease.lease_id)
            with budget.ledger_transaction(self.ledger) as ledger:
                ledger.setdefault('unpriced_invocations', []).append({'role': 'writer', 'model': c.model_lease.route,
                    'invocation_id': c.invocation_reservation['invocation_id'], 'lease_id': c.model_lease.lease_id})
            raise budget.BudgetError('provider_limit:' + c.model_lease.route,
                provider_failure={'reason': 'quota', 'scope': 'account', 'model': c.model_lease.route})
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT': '0'}), patch.object(model_router, 'await_lease', admit), \
                patch.object(model_runtime.ModelRuntime, '_invoke', invoke):
            with self.assertRaisesRegex(budget.BudgetError, '^money_wait$'):
                run.pending_call(self.c, self.c.models['builder'], 'retained findings', self.case, 'builder-1', self.receipt(),
                                 role='writer', on_complete=lambda: self.fail('must not complete'))
        self.assertEqual(len(invoked), 1); self.assertEqual(observed, [False, False])
        self.assertFalse((self.work / 'provider_wait.json').exists())
        self.assertEqual(len(json.loads(self.ledger.read_text())['invocation_reservations']), 1)
        budget.reconcile_reservations(self.work, self.ledger)
        self.assertIsNotNone(budget.case_spending(json.loads(self.ledger.read_text()))['total_spent_usd'])

    def test_owner_http_question_uses_independent_lease_while_tester_holds_lock(self):
        self.owner_http('done')

    def test_owner_denial_cancels_tester_and_settles_only_tester_reservation(self):
        self.owner_http('denied')

    def test_interrupted_owner_usage_settles_both_independent_leases_once(self):
        self.owner_http('interrupted')

    def owner_http(self, outcome):
        parent = 'strong-calibrator-strong_calibrator-1'
        workspace = self.work / 'strong_calibrator/try-1'; workspace.mkdir(parents=True)
        calls, owner_errors = [], []
        model_call = run.model_call
        def call(c, models, text, cwd, name, **kwargs):
            try: return model_call(c, models, text, cwd, name, **kwargs)
            except BaseException as error:
                if name != parent: owner_errors.append(error)
                raise
        self.patch(run, 'model_call', call)
        def invoke(runtime, c, models, text, cwd, name, **kwargs):
            c.model_process_state['started'] = True
            calls.append((name, c.model_lease.lease_id, c.model_lease.family))
            if name == parent:
                self.assertIn(parent, self.c.active_model_calls)
                try:
                    with urllib.request.urlopen(urllib.request.Request(url,
                            data=b'{"question":"What does the supplied public practice contract establish?"}'), timeout=3) as response:
                        self.assertTrue(json.load(response)['answer'])
                except urllib.error.HTTPError as error:
                    error.close()
                    self.assertNotEqual(outcome, 'done'); self.assertTrue(self.c.role_cancel.is_set())
                    raise budget.BudgetError('cancelled') from None
            else:
                self.assertTrue(c._owner_lock_bypass); self.assertEqual(c.parent_call_name, parent)
                if outcome == 'interrupted':
                    with budget.ledger_transaction(self.ledger) as ledger:
                        identity = str(uuid.uuid4())
                        ledger['events'].append({'id': identity, 'cost': .0005, 'role': 'reviewer', 'invocation': name,
                            'invocation_id': c.invocation_reservation['invocation_id'], 'lease_id': c.model_lease.lease_id})
                        ledger['cost'] += .0005; ledger['calls'] += 1
                        ledger['invocation_reservations'][c.model_lease.lease_id]['event_ids'].append(identity)
                    raise budget.BudgetError('provider_limit:' + c.model_lease.route,
                        provider_failure={'reason': 'quota', 'scope': 'account', 'model': c.model_lease.route})
                (Path(cwd) / 'answer.json').write_text('{"answer":"Use the supplied public practice contract."}')
            return 0
        self.patch(model_runtime.ModelRuntime, '_invoke', invoke)
        self.c.recipient = 'synthetic-only'
        checkpoint = self.patch(durable_checkpoint, 'checkpoint_progress', side_effect=AssertionError('active G10 cannot checkpoint'))
        if outcome == 'denied':
            for route in model_router.routes(self.c.models['reviewers'][0][0]):
                self.store.capacities[route['pool']] = 0
        model_runtime.prepare_dispatch(self.c)
        try:
            with exam_responder.owner_server(self.c, run, workspace, parent_call_name=parent) as url:
                run.model_call(self.c, self.c.models['strong_calibrator'], 'owner protocol test', self.case, parent, user='pilot')
        except budget.BudgetError as error:
            self.assertNotEqual(outcome, 'done'); self.assertEqual(str(error), 'cancelled')
            self.assertTrue(owner_errors)
            self.assertIsInstance(owner_errors[0], model_router.ProviderWait)
            record = run.write_provider_wait(self.c, error)
            budget.settle(record, work=self.work, ledger_path=self.ledger)
            self.assertEqual(budget.settle(record, work=self.work, ledger_path=self.ledger), 0)
            self.assertEqual(self.c.card['terminal_stop'], 'provider_wait')
            self.assertNotIn('failed_gate', self.c.card)
            expected = .019 if outcome == 'denied' else .02002
            self.assertEqual(budget.case_spending(json.loads(self.ledger.read_text()))['total_spent_usd'], round(self.baseline + expected, 9))
        else:
            self.assertEqual(outcome, 'done')
        reservations = list(json.loads(self.ledger.read_text())['invocation_reservations'].values())
        count = 1 if outcome == 'denied' else 2
        self.assertEqual(len(calls), count); self.assertEqual(len(reservations), count)
        self.assertEqual(len({row[1] for row in calls}), count)
        self.assertEqual({row[2] for row in calls}, {'openai'} if outcome == 'denied' else {'openai', 'deepseek'})
        if outcome != 'denied':
            owner = next(row for row in reservations if row['parent_call_name'])
            self.assertEqual(owner['parent_call_name'], parent)
        if outcome == 'done': self.assertTrue(all(row['state'] == 'settled' for row in reservations))
        self.assertEqual(len(self.c.card['route_receipts']), count)
        checkpoint.assert_not_called()


if __name__ == '__main__': unittest.main()
