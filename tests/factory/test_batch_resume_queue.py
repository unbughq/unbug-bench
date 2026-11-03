"""Offline resume-queue composition using retained artifacts and real D projections.

Saved card/ledger/ciphertext and a saved creation event are reused. Batch bindings,
checkpoint stop fields, deletion receipts, transport and dispatch preflight
dependencies are authored controls. No worker, model, cloud or live diagnosis is
claimed; these tests do not close a Murphy row.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import batch_holder as holder
import batch_money as money
import batch_service as service
import budget
import diagnosis
import key_holder
import test_batch_holder as holder_fixtures
import test_batch_service as service_fixtures
import test_batch_transfer as transfer_fixtures
from registry import atomic_json


class ResumeQueueTests(unittest.TestCase):
    locals().update({k: v for k, v in vars(holder_fixtures.HolderTests).items()
                     if not k.startswith(('test_', '__'))})

    def setUp(self):
        holder_fixtures.HolderTests.setUp(self)
        self.record['replacement_policy']['enabled'] = False
        self.freeze()
        delays = patch.dict(holder._RESUME_RETRY_AFTER, {}, clear=True)
        delays.start(); self.addCleanup(delays.stop)
        plans = patch.dict(holder._PLAN_RETRY_AFTER, {}, clear=True)
        plans.start(); self.addCleanup(plans.stop)

    def state(self):
        return service._load(self.directory, self.record, self.policy['batch']['manifest_sha256'])

    def saved_card(self, op, card):
        path = self.home / 'launches' / op['launch_id'] / 'collected' / (op['case'] + '.scorecard.json')
        path.write_text(json.dumps(card))

    def exhausted(self, job='j', *, ledger=None, publish=True, retire=True):
        op = self.started(self.reserve(job))
        card = self.output(op, ledger=ledger)
        card.pop('diagnosis_state', None)
        card.update(status='stopped', terminal_stop='budget_exhausted', gates={})
        diagnosis.record_exhaustion(card)
        self.assertEqual(card['diagnosis_state']['status'], 'pending')
        self.saved_card(op, card)
        if publish: self.publish(op)
        if retire: self.retirement(op); self.reconcile()
        return self.ops()[op['operation_id']], card

    def plan(self): return holder.plan_collections(self.policy, self.root, self.home)
    def drain(self): return holder.drain_resumes(self.policy, self.root, self.home)

    def tick(self):
        spawned = []
        with patch.multiple(key_holder, ROOT=self.root, CONTROL_HOME=self.home):
            key_holder.batch_tick(self.policy, {}, {},
                                  lambda operation, action: spawned.append((operation, action)) or
                                  SimpleNamespace(poll=lambda: None))
        return spawned

    def successor(self, op, card):
        return self.ops()[holder.operation_id(self.policy, op['job'], card['sha256'])]

    def unchanged(self, money_bytes, ops_bytes, journal_bytes):
        self.assertEqual((self.directory / 'money.json').read_bytes(), money_bytes)
        self.assertEqual((self.directory / 'reservations.json').read_bytes(), ops_bytes)
        self.assertEqual((self.directory / 'journal.json').read_bytes(), journal_bytes)

    def bytes_before(self):
        return tuple((self.directory / name).read_bytes()
                     for name in ('money.json', 'reservations.json', 'journal.json'))

    def test_tick_drains_to_existing_reserve_reconcile_and_dispatch(self):
        predecessor, card = self.exhausted()
        before = self.money()
        self.assertEqual(self.tick(), [])  # Tick creates a reservation, not a child.
        successor = self.successor(predecessor, card)
        identity = successor['operation_id']
        journal = self.state()
        self.assertEqual(list(journal['queue']), ['resume/' + card['case'] + '/' + card['sha256']])
        self.assertEqual(successor['state'], 'pending')
        self.assertEqual(successor['authority']['reservation_id'], predecessor['authority']['reservation_id'])
        self.assertEqual(successor['authority']['source_generation'], card['sha256'])
        self.assertEqual(successor['authority']['revision'], predecessor['authority']['revision'] + 1)
        self.assertEqual(money.aggregate(self.money()), money.aggregate(before))
        self.assertEqual(self.money()['jobs']['j']['held_usd'], before['jobs']['j']['held_usd'])
        self.assertEqual(self.tick(), [(identity, 'dispatch')])
        # HolderTests.preflight uses real dispatch; identity, release verification,
        # fingerprint, accounts, credentials, Boat and Popen are authored doubles.
        result, calls = self.preflight(self.ops()[identity])
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        argv = calls[0]
        self.assertEqual(argv[argv.index('--restore') + 1], card['case'])
        self.assertEqual(argv[argv.index('--checkpoint-sha256') + 1], card['sha256'])
        self.assertTrue(self.ops()[identity]['dispatch_started'])
        self.assertEqual(self.preflight(self.ops()[identity]), (None, []))
        self.drain()
        self.assertEqual(len(self.ops()), 2)
        self.assertEqual(list(self.state()['queue']), list(journal['queue']))

    def test_covered_unknown_settles_then_queues_known_diagnosis(self):
        accountant = self.accountant()
        lease, _ = accountant.unknown()
        predecessor, card = self.exhausted(ledger=accountant.ledger())
        exhaustion_id = card['diagnosis_state']['exhaustion_id']
        self.assertIsNone(card['case_budget']['total_spent_usd'])
        original = self.money()['jobs']['j']
        original_bound = money.aggregate(self.money())
        self.plan(); self.drain()
        first = self.successor(predecessor, card)
        self.assertEqual(first['authority']['revision'], predecessor['authority']['revision'])
        self.assertEqual(first['authority']['reservation_id'], predecessor['authority']['reservation_id'])
        self.assertEqual(self.money()['jobs']['j']['held_usd'], original['held_usd'])
        self.assertEqual(money.aggregate(self.money()), original_bound)
        first = self.started(first)

        # Real saved-ledger settlement, with an authored final usage receipt.
        accountant.receipt(lease, [('streamed', 3)], final=True)
        budget.reconcile_reservations(accountant.work, accountant.path)
        self.assertIsNotNone(budget.case_spending(accountant.ledger())['total_spent_usd'])
        later = self.output(first, ledger=accountant.ledger(), payload=service_fixtures.KEY)
        later.update(status='stopped', terminal_stop='diagnosis_pending', gates={},
                     diagnosis_state=deepcopy(card['diagnosis_state']))
        self.saved_card(first, later)
        self.publish(first); self.retirement(first); self.reconcile()

        self.plan(); self.drain()
        second = self.successor(first, later)
        self.assertNotEqual(first['operation_id'], second['operation_id'])
        self.assertEqual(second['authority']['reservation_id'], first['authority']['reservation_id'])
        self.assertEqual(second['authority']['revision'], first['authority']['revision'] + 1)
        self.assertEqual(self.money()['jobs']['j']['held_usd'], original['held_usd'])
        self.assertEqual(money.aggregate(self.money()), original_bound)
        self.assertEqual(later['diagnosis_state']['exhaustion_id'], exhaustion_id)
        self.assertEqual(self.state()['queue']['resume/' + later['case'] + '/' + later['sha256']]['reason'],
                         'exhaustion')
        self.drain(); self.assertEqual(len(self.ops()), 3)
        result, calls = self.preflight(self.ops()[second['operation_id']])
        self.assertEqual(result, 0); self.assertEqual(len(calls), 1)
        self.assertEqual(self.preflight(self.ops()[second['operation_id']]), (None, []))

    def test_held_unknown_may_settle_but_cannot_take_a_model_lease(self):
        accountant = self.accountant(); accountant.unknown()
        op, card = self.exhausted(ledger=accountant.ledger(), publish=False, retire=False)
        card.update(terminal_stop='factory_bug_held', infrastructure_gate={'exhausted': True},
                    factory_bug={'finding_id': 'authored-held-finding'})
        card['diagnosis_state'].update(stop='infrastructure_exhausted', status='completed', outcome='factory_bug')
        self.saved_card(op, card)
        self.publish(op); self.retirement(op); self.reconcile()
        self.plan(); self.drain()
        self.assertEqual(self.state()['queue']['resume/' + card['case'] + '/' + card['sha256']]['reason'],
                         'settlement')
        self.assertEqual(self.successor(op, card)['authority']['revision'], op['authority']['revision'])
        with self.assertRaisesRegex(budget.BudgetError, '^factory_bug_held$'):
            diagnosis.require_model_work(card)

    def test_settlement_precedes_earlier_known_exhaustion(self):
        known_op, known = self.exhausted('j')
        accountant = self.accountant(); accountant.unknown()
        unknown_op, unknown = self.exhausted('k', ledger=accountant.ledger())
        self.plan()
        ordered = service.ordered_queue(self.state())
        self.assertEqual([(row['job'], row['reason']) for row in ordered],
                         [('k', 'settlement'), ('j', 'exhaustion')])
        attempted = []
        original = holder.reserve
        def reserve(*args, **kwargs):
            attempted.append(args[3])
            return original(*args, **kwargs)
        with patch.object(holder, 'reserve', side_effect=reserve):
            self.drain()
        self.assertEqual(attempted, ['k', 'j'])
        self.assertIn(holder.operation_id(self.policy, 'k', unknown['sha256']), self.ops())
        self.assertNotIn(holder.operation_id(self.policy, 'j', known['sha256']), self.ops())

    def test_tick_reserves_settlement_before_a_due_provider_wait(self):
        accountant = self.accountant(); accountant.unknown()
        settlement_op, settlement = self.exhausted('j', ledger=accountant.ledger())
        _, wait = holder_fixtures.WaitSchedulingTests.waiting(
            self, 'k', changes={'retry_after': '2020-01-01T00:00:00Z'})
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.successor(settlement_op, settlement)['state'], 'pending')
        self.assertNotIn(holder.operation_id(self.policy, 'k', wait['sha256']), self.ops())

    def test_replacement_policy_defers_known_but_not_settlement(self):
        self.record['replacement_policy']['enabled'] = True; self.freeze()
        op, card = self.exhausted('j')
        self.plan()
        before = self.bytes_before()
        self.drain()
        self.unchanged(*before)
        self.assertNotIn(holder.operation_id(self.policy, 'j', card['sha256']), self.ops())
        accountant = self.accountant(); accountant.unknown()
        other, unknown = self.exhausted('k', ledger=accountant.ledger())
        self.plan(); self.drain()
        self.assertIn(holder.operation_id(self.policy, 'k', unknown['sha256']), self.ops())
        self.assertNotIn(holder.operation_id(self.policy, 'j', card['sha256']), self.ops())

    def test_blocked_candidate_does_not_stop_later_eligible_candidate(self):
        first, _ = self.exhausted('j')
        second, card = self.exhausted('k', ledger=None)
        self.plan()
        (self.directory / 'current' / (first['case'] + '.json')).unlink()
        attempted = []
        original = holder.reserve
        def reserve(*args, **kwargs):
            attempted.append(args[3])
            return original(*args, **kwargs)
        with patch.object(holder, 'reserve', side_effect=reserve):
            self.drain()
        self.assertEqual(attempted, ['j', 'k'])
        self.assertEqual(self.successor(second, card)['job'], 'k')
        self.assertEqual(len(self.ops()), 3)

    def test_policy_gates_before_queue_scan(self):
        for value in (None, {'schema': 1, 'enabled': False}):
            with self.subTest(policy=value):
                self.setUp()
                if value is None: self.record.pop('diagnosis_policy')
                else: self.record['diagnosis_policy'] = value
                self.freeze()
                with patch.object(holder, '_operations', side_effect=AssertionError('policy is off')):
                    self.assertEqual(self.drain(), [])
        with patch.object(holder, 'HOLDER_ENABLED', False), self.assertRaises(ValueError):
            self.drain()

    def test_ack_retirement_source_and_config_faults_refuse(self):
        for fault in ('ack', 'retirement', 'outbox', 'pointer', 'stale_pointer',
                      'producer_incident', 'producer_config', 'snapshot', 'legacy_marker',
                      'marker_symlink', 'parent_symlink', 'case_symlink'):
            with self.subTest(fault=fault):
                self.setUp()
                op, card = self.exhausted()
                self.plan()
                state = self.money()
                if fault == 'ack':
                    del state['jobs']['j']['acks'][card['sha256']]
                    atomic_json(self.directory / 'money.json', state)
                elif fault in ('retirement', 'producer_incident'):
                    ops = self.ops()
                    ops[op['operation_id']]['retirement' if fault == 'retirement' else 'incident'] = (
                        None if fault == 'retirement' else 'publication_failed')
                    holder._save(self.directory, self.record, self.policy, ops)
                elif fault in ('outbox', 'pointer', 'stale_pointer'):
                    path = (self.directory / 'outbox' / (op['operation_id'] + '.json')
                            if fault == 'outbox' else self.directory / 'current' / (op['case'] + '.json'))
                    if fault == 'stale_pointer':
                        value = service._json(path); value['generation'] = 'b' * 64
                        atomic_json(path, value)
                    else: path.unlink()
                elif fault == 'producer_config':
                    (self.directory / 'configs' / (op['config_sha256'] + '.json')).write_text('{}')
                elif fault == 'snapshot':
                    (self.directory / 'generations' / op['case'] / card['sha256'] /
                     (op['case'] + '.statement.age')).write_bytes(b'tampered')
                elif fault in ('legacy_marker', 'marker_symlink'):
                    path = self.directory / 'retirements' / op['case'] / (card['sha256'] + '.json')
                    path.parent.mkdir(parents=True)
                    if fault == 'legacy_marker': path.write_text('{}')
                    else: path.symlink_to(self.root / 'absent-marker')
                elif fault == 'parent_symlink':
                    (self.directory / 'retirements').symlink_to(self.root / 'absent-retirements')
                else:
                    path = self.directory / 'retirements' / op['case']
                    path.parent.mkdir(parents=True); path.symlink_to(self.root / 'absent-case')
                before = self.bytes_before()
                self.assertEqual(self.drain(), [])
                self.unchanged(*before)
                self.assertEqual(len(self.ops()), 1)

    def test_money_deadline_capacity_and_export_refuse(self):
        for fault in ('incident', 'overrun', 'aggregate', 'capacity', 'deadline', 'export'):
            with self.subTest(fault=fault):
                self.setUp()
                op, card = self.exhausted(); self.plan()
                state = self.money()
                if fault == 'incident':
                    ack = state['jobs']['j']['acks'][card['sha256']]
                    state['incidents'][op['operation_id'] + '/' + card['sha256']] = dict(
                        operation_id=op['operation_id'], generation=card['sha256'],
                        manifest_sha256=ack['manifest_sha256'], reason='invalid_accounting_input')
                    atomic_json(self.directory / 'money.json', state)
                elif fault == 'overrun':
                    state['jobs']['j']['acks'][card['sha256']]['facts']['total_usd'] = '1001.000000000'
                    state['jobs']['j'].update(known_floor_usd='1001.000000000', overrun=True)
                    atomic_json(self.directory / 'money.json', state)
                elif fault == 'capacity':
                    self.reserve('k')
                elif fault == 'export':
                    (self.directory / 'export.json').write_text('{}')
                before = self.bytes_before()
                if fault == 'aggregate':
                    # Authored over-bound control, leaving the persistent ledger unchanged.
                    with patch.object(money, 'aggregate', return_value=money.amount('3001.000000000')):
                        self.drain()
                elif fault == 'deadline':
                    with patch.object(holder, 'datetime', wraps=datetime) as clock:
                        clock.now.return_value = datetime.fromisoformat('2100-01-01T00:00:00+00:00')
                        self.drain()
                elif fault == 'export':
                    with self.assertRaisesRegex(money.MoneyWait, 'batch_exported'):
                        self.drain()
                else:
                    self.drain()
                self.unchanged(*before)
                self.assertNotIn(holder.operation_id(self.policy, 'j', card['sha256']), self.ops())

    def test_rechecks_queue_inside_reserve_after_selection(self):
        for fault in ('removed', 'changed'):
            with self.subTest(fault=fault):
                self.setUp()
                _, card = self.exhausted()
                self.plan()
                original = holder.reserve
                def mutate(*args, **kwargs):
                    journal = self.state()
                    if fault == 'removed':
                        journal['queue'] = {}; journal['next_sequence'] = 0
                    else:
                        next(iter(journal['queue'].values()))['reason'] = 'settlement'
                    atomic_json(self.directory / 'journal.json', journal)
                    return original(*args, **kwargs)
                before_money = (self.directory / 'money.json').read_bytes()
                with patch.object(holder, 'reserve', side_effect=mutate): self.drain()
                self.assertEqual((self.directory / 'money.json').read_bytes(), before_money)
                self.assertEqual(len(self.ops()), 1)

    def test_structurally_invalid_journal_refuses_whole_scan(self):
        self.exhausted(); self.plan()
        journal = self.state()
        next(iter(journal['queue'].values()))['sequence'] = 9
        atomic_json(self.directory / 'journal.json', journal)
        before = self.bytes_before()
        with patch.object(holder, 'reserve') as reserve:
            with self.assertRaisesRegex(ValueError, 'invalid batch journal'):
                self.drain()
        reserve.assert_not_called()
        self.unchanged(*before)

    def test_queue_cannot_be_combined_with_provider_wait_mode(self):
        _, card = self.exhausted(); self.plan()
        row = self.state()['queue']['resume/' + card['case'] + '/' + card['sha256']]
        before = self.bytes_before()
        with self.assertRaisesRegex(ValueError, 'request_refused'):
            holder.reserve(self.policy, self.root, self.home, 'j', card['sha256'],
                           provider_wait=True, queued_resume=row)
        self.unchanged(*before)

    def test_forged_facts_reason_or_legacy_state_never_grants(self):
        for fault in ('facts', 'reason'):
            with self.subTest(fault=fault):
                self.setUp()
                op, card = self.exhausted()
                self.plan()
                journal = self.state()
                entry = journal['entries'][op['case'] + '/' + card['sha256']]
                request = next(iter(journal['queue'].values()))
                if fault == 'facts':
                    entry['facts']['actual_model_work'] = not entry['facts']['actual_model_work']
                    entry['facts']['pending_projection']['replacement_eligible'] = False
                elif fault == 'reason': request['reason'] = 'settlement'
                atomic_json(self.directory / 'journal.json', journal)
                before = self.bytes_before()
                self.drain()
                self.unchanged(*before)
                self.assertEqual(len(self.ops()), 1)

    def test_valid_legacy_sealed_and_retired_snapshots_cannot_be_forged_into_queue(self):
        for kind in ('legacy', 'sealed', 'retired'):
            with self.subTest(kind=kind):
                self.setUp()
                op, card = self.exhausted(publish=False, retire=False)
                if kind == 'legacy': card.pop('diagnosis_state')
                else: card['status'] = kind
                self.saved_card(op, card)
                self.publish(op); self.retirement(op); self.reconcile()
                journal = self.state()
                entry = journal['entries'][op['case'] + '/' + card['sha256']]
                entry['facts'] = service._project(card, diagnosis)
                key = 'resume/' + card['case'] + '/' + card['sha256']
                journal['queue'][key] = dict(kind='resume', job='j', case=card['case'],
                    source_generation=card['sha256'], owner_job='j', parent_case=None,
                    sequence=0, reason='exhaustion')
                journal['next_sequence'] = 1
                atomic_json(self.directory / 'journal.json', journal)
                # The retained snapshot and ACK are intact; this is not merely
                # a corrupt-file refusal. The queue itself is an authored forgery.
                with money.locked(self.home, self.record['id']):
                    _, _, authenticated = holder._source(self.directory, self.record, self.policy,
                        self.ops(), self.money(), 'j', card['sha256'])
                self.assertEqual(authenticated.get('diagnosis_state'), card.get('diagnosis_state'))
                before = self.bytes_before()
                self.drain()
                self.unchanged(*before)
                self.assertEqual(len(self.ops()), 1)

    def test_imported_source_checks_retained_producer_config(self):
        for fault in ('none', 'producer_config', 'current_facts'):
            with self.subTest(fault=fault):
                fixture = transfer_fixtures.TransferTests(
                    'test_saved_card_launch_keeps_spend_owner_lineage_and_freezes_source')
                fixture.setUp(); self.addCleanup(fixture.doCleanups)
                fixture.record['replacement_policy']['enabled'] = False; fixture.freeze()
                op = fixture.started(fixture.reserve())
                card = fixture.output(op)
                card.pop('diagnosis_state', None)
                card.update(status='stopped', terminal_stop='budget_exhausted', gates={})
                diagnosis.record_exhaustion(card)
                incoming = (fixture.home / 'launches' / op['launch_id'] / 'collected' /
                            (op['case'] + '.scorecard.json'))
                incoming.write_text(json.dumps(card))
                fixture.publish(op); fixture.retirement(op); fixture.reconcile()
                holder.plan_collections(fixture.policy, fixture.root, fixture.home)
                source_journal = service._load(fixture.directory, fixture.record,
                                                fixture.policy['batch']['manifest_sha256'])
                record, policy = fixture.target({'j': card['sha256']})
                import batch_transfer
                batch_transfer.prepare(policy, fixture.root, fixture.home)
                target = fixture.home / 'batches' / record['id']
                journal = service._load(target, record, policy['batch']['manifest_sha256'])
                # Authored imported queue control: the current planner does not
                # generate imported-only entries, but _source supports them.
                journal['entries'] = deepcopy(source_journal['entries'])
                journal['queue'] = deepcopy(source_journal['queue'])
                journal['next_sequence'] = source_journal['next_sequence']
                if fault == 'current_facts':
                    facts = journal['entries'][op['case'] + '/' + card['sha256']]['facts']
                    facts['actual_model_work'] = not facts['actual_model_work']
                    facts['pending_projection']['replacement_eligible'] = False
                atomic_json(target / 'journal.json', journal)
                if fault == 'producer_config':
                    path = fixture.directory / 'configs' / (op['config_sha256'] + '.json')
                    path.write_text('{}')
                holder.drain_resumes(policy, fixture.root, fixture.home)
                operations = holder._operations(target, record, policy)
                identity = holder.operation_id(policy, 'j', card['sha256'])
                if fault != 'none': self.assertNotIn(identity, operations)
                else:
                    self.assertIn(identity, operations)
                    self.assertEqual(operations[identity]['authority']['source_generation'], card['sha256'])
                    self.assertNotEqual(operations[identity]['authority']['reservation_id'],
                                        op['authority']['reservation_id'])

    def test_interrupted_reservations_and_lost_reply_are_idempotent(self):
        for boundary in ('configuration', 'reservations.json', 'journal.json', 'reply'):
            with self.subTest(boundary=boundary):
                self.setUp()
                op, card = self.exhausted()
                self.plan()
                real_write, real_reserve = holder.atomic_json, holder.reserve
                def write(path, value):
                    if path.name == boundary: raise OSError('authored crash')
                    return real_write(path, value)
                def lost(*args, **kwargs):
                    real_reserve(*args, **kwargs)
                    raise OSError('authored lost reply')
                if boundary == 'configuration':
                    context = patch.object(money, 'configuration', side_effect=OSError('authored crash'))
                elif boundary == 'reply': context = patch.object(holder, 'reserve', side_effect=lost)
                else: context = patch.object(holder, 'atomic_json', side_effect=write)
                with context: self.drain()
                authority = deepcopy(self.money()['jobs']['j']['authority'])
                self.assertEqual(authority['source_generation'], card['sha256'])
                holder._RESUME_RETRY_AFTER.clear()  # Simulate a holder restart.
                self.reconcile(); self.drain(); self.reconcile()
                successor = self.successor(op, card)
                self.assertEqual(successor['authority'], authority)
                self.assertEqual(self.money()['jobs']['j']['sources'], [None, card['sha256']])
                self.assertEqual(len(self.ops()), 2)
                self.assertEqual(service._json(self.directory / 'journal.json')['operations'], self.ops())
                result, calls = self.preflight(successor)
                self.assertEqual(result, 0); self.assertEqual(len(calls), 1)
                self.assertEqual(self.preflight(self.ops()[successor['operation_id']]), (None, []))

    def test_concurrent_scans_and_existing_failed_identity_do_not_duplicate(self):
        op, card = self.exhausted()
        self.plan()
        barrier = threading.Barrier(2)
        original = holder.reserve
        def overlap(*args, **kwargs):
            barrier.wait(timeout=30)  # Both scans selected before either reserves.
            return original(*args, **kwargs)
        with patch.object(holder, 'reserve', side_effect=overlap):
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(list(pool.map(lambda _: self.drain(), range(2))), [[], []])
        successor = self.successor(op, card)
        self.assertEqual(len(self.ops()), 2)
        holder.record_exit(self.policy, self.root, self.home, successor['operation_id'], 1)
        self.assertEqual(self.ops()[successor['operation_id']]['state'], 'failed')
        self.drain(); self.assertEqual(len(self.ops()), 2)
        self.assertEqual(self.successor(op, card)['operation_id'], successor['operation_id'])

    def test_uncertain_dispatch_never_creates_a_second_successor(self):
        op, card = self.exhausted(); self.plan(); self.drain()
        successor = self.successor(op, card)
        result, calls = self.preflight(successor, popen_error=OSError('authored transport uncertainty'))
        self.assertEqual(result, holder.TEMPFAIL)
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.ops()[successor['operation_id']]['dispatch_started'])
        self.drain()
        self.assertEqual(len(self.ops()), 2)
        self.assertEqual(self.preflight(self.ops()[successor['operation_id']]), (None, []))

    def test_refusal_retry_waits_60_seconds_or_restart(self):
        op, card = self.exhausted()
        self.plan()
        path = self.directory / 'configs' / (op['config_sha256'] + '.json')
        original = path.read_bytes(); path.write_text('{}')
        with patch.object(holder.time, 'monotonic', return_value=10) as clock, \
             patch.object(holder, 'reserve', wraps=holder.reserve) as reserve:
            self.drain(); self.assertEqual(reserve.call_count, 1)
            path.write_bytes(original)
            clock.return_value = 69
            self.drain(); self.assertEqual(reserve.call_count, 1)
            clock.return_value = 70
            self.drain(); self.assertEqual(reserve.call_count, 2)
        self.assertEqual(self.successor(op, card)['state'], 'pending')

    def test_scan_and_reserve_never_nest_money_lock(self):
        _, card = self.exhausted()
        self.plan()
        original = money.locked
        depth, maximum = 0, 0
        @contextmanager
        def single(*args, **kwargs):
            nonlocal depth, maximum
            depth += 1
            self.assertEqual(depth, 1, 'nested money lock would deadlock')
            maximum = max(maximum, depth)
            try:
                with original(*args, **kwargs) as directory: yield directory
            finally: depth -= 1
        with patch.object(money, 'locked', side_effect=single):
            self.drain()
        self.assertEqual(maximum, 1)
        self.assertIn(holder.operation_id(self.policy, 'j', card['sha256']), self.ops())


if __name__ == '__main__':
    unittest.main()

