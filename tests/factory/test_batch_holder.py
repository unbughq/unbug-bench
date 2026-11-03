"""Offline integration: retained card/ciphertext/created event, authored bindings.

Uses the real collection verifier and D APIs. Ciphertext is the retained opaque
transport envelope from test_batch_service, not a generated case archive.
Deletion/config/operation fields are authored; no live proof or Murphy closure.
"""
from copy import deepcopy
import fcntl
import io
import json
import os
import subprocess
import tarfile
import shutil
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import batch_holder as holder
import practice_preflight as preflight
import batch_money as money
import batch_service as service
import batch_status as status
import budget
import test_batch_service as fixtures
import test_batch_accounting as accounting_fixtures


class HolderTests(unittest.TestCase):
    setUpBase = fixtures.ServiceTests.setUp
    freeze = fixtures.ServiceTests.freeze
    input = fixtures.ServiceTests.input
    write_card = fixtures.ServiceTests.write_card
    answers = fixtures.ServiceTests.answers

    def setUp(self):
        self.setUpBase()
        self.record['money_limit_usd'] = '3000.000000000'
        for job in self.record['jobs'].values(): job['requested_total_usd'] = '1000.000000000'
        for job in self.record['jobs'].values(): job['args'] += ['--rotation-slot', '0']
        self.freeze()
        gate = patch.object(holder, 'HOLDER_ENABLED', True); gate.start(); self.addCleanup(gate.stop)
        self.objects = {}

    @property
    def directory(self): return self.home / 'batches/practice'

    def ops(self): return json.loads((self.directory / 'reservations.json').read_text())['operations']
    def money(self): return money.load_locked(self.directory, self.record, self.policy['batch']['manifest_sha256'])
    def reserve(self, job='j', source=None): return holder.reserve(self.policy, self.root, self.home, job, source)
    def reconcile(self): return holder.reconcile(self.policy, self.root, self.home)
    def publish(self, op):
        return holder.collect(self.policy, self.root, self.home, op['operation_id'],
                              lambda key, path: self.objects.update({key: path.read_bytes()}))

    def started(self, op, *, created=True):
        identity = op['operation_id']
        with money.locked(self.home, self.record['id']):
            ops = self.ops(); op = ops[identity]
            op.update(dispatch_started=True, launch=dict(argv=['1'], environment={'UNBUG_BATCH_OPERATION': identity}))
            holder._save(self.directory, self.record, self.policy, ops)
        path = self.home / 'launches' / op['launch_id']; path.mkdir(parents=True)
        (path / 'launch.json').write_text(json.dumps(op['launch']))
        (path / 'controller.lock').touch()
        (path / 'ids').write_text('')
        if created:
            event = json.loads((ROOT / 'tests/factory/fixtures/isolation-timeouts/created.json').read_text())
            (path / 'new.1').write_text(json.dumps(event) + '\n')
            (path / 'ids').write_text(event['id'] + '\n')
            self.reconcile()  # Without a creation record yet, the caller reconciles after staging one.
        return self.ops()[identity]

    def output(self, op, *, ledger=None, payload=fixtures.CIPHER, total='auto'):
        ledger = deepcopy(next(r['card']['continuation_budget'] for r in accounting_fixtures.d.cards()
                               if r['card']['case'].endswith('e15450'))) if ledger is None else ledger
        summary = budget.case_spending(ledger)
        card = self.input(op['job'], payload=payload,
                          total=summary['total_spent_usd'] if total == 'auto' else total,
                          continuation_budget=ledger, job_money=op['authority'])
        destination = self.home / 'launches' / op['launch_id'] / 'collected'; destination.mkdir(exist_ok=True)
        for path in self.source.iterdir():
            if path.name.startswith(op['case'] + '.'):
                (destination / path.name).write_bytes(path.read_bytes())
        return card

    def retirement(self, op):
        worker = op['worker_id']; path = self.home / 'launches' / op['launch_id']
        spend = self.root / 'results/spend' / (op['launch_id'] + '.json'); spend.parent.mkdir(parents=True, exist_ok=True)
        (path / 'monitor.sh').write_text('spend_file=' + shlex.quote(str(spend)) + '\n')
        proof = spend.with_suffix('.deletions') / worker; proof.mkdir(parents=True)
        request = dict(id='authored-delete-id', targetId=worker, kind='sandbox', status='pending', stage='pending', completedAt=None)
        done = dict(request, status='completed', stage='completed', completedAt='2026-10-30T00:00:00Z')
        (proof / 'deletion-request.json').write_text(json.dumps(request))
        (proof / 'deletion-completion.json').write_text(json.dumps(done))
        return proof

    def test_lifecycle_status_ack_retirement_source_and_replay(self):
        op = self.reserve()
        self.assertEqual(self.reserve(), op)
        self.assertEqual(status.read_rows(self.policy, self.root, self.home)[1][0]['phase'], 'pending')
        op = self.started(op)
        self.assertEqual(op['state'], 'launched')
        self.assertEqual(status.read_rows(self.policy, self.root, self.home)[1][0]['phase'], 'running')
        card = self.output(op); ack = self.publish(op)
        self.assertEqual(self.publish(op), ack)
        self.assertEqual(status.read_rows(self.policy, self.root, self.home)[1][0]['phase'], 'stopped')
        with self.assertRaises(ValueError): self.reserve(source=card['sha256'])
        self.retirement(op); self.reconcile()
        successor = self.reserve(source=card['sha256'])
        self.assertEqual(successor['authority']['revision'], 2)
        self.assertEqual(successor['authority']['reservation_id'], op['authority']['reservation_id'])
        self.assertEqual(self.reserve(source=card['sha256']), successor)
        with self.assertRaises(ValueError): self.reserve()
        self.assertEqual(holder.source_directory(self.policy, self.root, self.home, successor['operation_id']),
                         self.directory / 'generations' / op['case'] / card['sha256'])
        self.assertEqual(status.read_rows(self.policy, self.root, self.home)[1][0]['phase'], 'pending')

    def check_unexhausted_source(self, stop):
        import diagnosis
        op = self.started(self.reserve())
        card = self.output(op)  # retained interrupted card + saved usage; authored batch bindings
        card.pop('diagnosis_state')
        card['terminal_stop'] = stop
        diagnosis.record_exhaustion(card)  # The real runner's final-accounting producer.
        self.assertNotIn('diagnosis_state', card)
        self.assertFalse(diagnosis.exhaustion(card))
        incoming = self.home / 'launches' / op['launch_id'] / 'collected' / (op['case'] + '.scorecard.json')
        incoming.write_text(json.dumps(card))
        self.publish(op); self.retirement(op); self.reconcile()
        successor = self.reserve(source=card['sha256'])
        self.assertEqual(successor['authority']['revision'], 2)
        self.assertEqual(self.reserve(source=card['sha256']), successor)
        # Dispatch preflight uses the same proof; no transport is needed here.
        with money.locked(self.home, self.record['id']):
            checked = holder._post(self.directory, self.record, self.policy, self.home,
                                   self.ops(), self.money(), successor['operation_id'])
        self.assertEqual(checked['operation_id'], successor['operation_id'])
        self.assertFalse((self.directory / 'retirements').exists())

    def test_provider_wait_without_diagnosis_state_is_resumable(self):
        self.check_unexhausted_source('provider_wait')

    def test_pause_without_diagnosis_state_is_resumable(self):
        self.check_unexhausted_source('paused')

    def test_ttl_stop_without_diagnosis_state_is_resumable(self):
        self.check_unexhausted_source('ttl_retired')

    def check_dispatch_creator_intent(self, router_client):
        import key_holder
        import account_handoff
        op = self.reserve(); self.policy.update(code_sha256='fingerprint', path='/usr/bin:/bin', recipient='founder-public')
        calls = []
        environment = dict(os.environ)
        environment.pop('UNBUG_ROUTER_CLIENT_FILE', None)
        if router_client is not None: environment['UNBUG_ROUTER_CLIENT_FILE'] = router_client
        def run(argv, **kwargs):
            data = (self.record['restore_recipient'].encode() if argv[0] == 'age-keygen' else
                    json.dumps(dict(sandboxes=[], pageInfo=dict(hasMore=False))).encode())
            return SimpleNamespace(stdout=data)
        def popen(argv, **kwargs):
            self.assertTrue(self.ops()[op['operation_id']]['dispatch_started'])
            if router_client is None:
                self.assertNotIn('UNBUG_ROUTER_CLIENT_FILE', kwargs['env'])
            else:
                self.assertEqual(kwargs['env']['UNBUG_ROUTER_CLIENT_FILE'], router_client)
            calls.append(argv)
            return SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 0)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, environment, clear=True))
            stack.enter_context(patch.object(key_holder, 'fingerprint', return_value='fingerprint'))
            # Phase B live checks have their own real-dispatch tests (test_preflight.py).
            stack.enter_context(patch.object(preflight, 'decrypt', return_value={'claude-token': b''}))
            stack.enter_context(patch.object(preflight, 'dispatch_checks'))
            stack.enter_context(patch.object(account_handoff, 'launch_accounts', return_value=(None, 1, {})))
            stack.enter_context(patch.object(holder.subprocess, 'run', side_effect=run))
            stack.enter_context(patch.object(holder.subprocess, 'Popen', side_effect=popen))
            holder.dispatch(self.policy, self.root, self.home, op['operation_id'], b'authored test identity')
            holder.dispatch(self.policy, self.root, self.home, op['operation_id'], b'authored test identity')
        self.assertEqual(len(calls), 1)
        self.assertNotIn(b'authored test identity', (self.directory / 'reservations.json').read_bytes())

    def test_dispatch_creator_intent_is_durable_and_never_repeated(self):
        self.check_dispatch_creator_intent(None)

    def test_dispatch_forwards_router_client_path_when_set(self):
        self.check_dispatch_creator_intent(str(self.home / 'public-router-client.json'))

    def test_gate_off_and_schema1_never_migrate(self):
        with patch.object(holder, 'HOLDER_ENABLED', False), self.assertRaises(ValueError): self.reserve()
        auth = money.authorize(self.policy, 'j', None, self.root, self.home)
        raw = (self.directory / 'money.json').read_bytes()
        self.assertEqual(json.loads(raw)['schema'], 1)
        with self.assertRaises(ValueError): self.reserve()
        self.assertEqual((self.directory / 'money.json').read_bytes(), raw)
        self.assertEqual(money.authorize(self.policy, 'j', None, self.root, self.home), auth)

    def test_uncertain_creation_and_positive_precreation_failure(self):
        op = self.started(self.reserve(), created=False)
        self.assertEqual(op['state'], 'pending')
        path = self.home / 'launches' / op['launch_id']
        (path / 'new.1.pending').touch()
        holder.record_exit(self.policy, self.root, self.home, op['operation_id'], 1)
        self.reconcile(); self.assertEqual(self.ops()[op['operation_id']]['state'], 'pending')
        (path / 'new.1.pending').unlink()
        self.reconcile(); self.assertEqual(self.ops()[op['operation_id']]['state'], 'failed')
        self.assertEqual(self.reserve()['state'], 'failed')
        self.assertEqual(self.reconcile(), [])

    def test_preflight_overlap_loser_cannot_fail_owner(self):
        op = self.reserve()
        with holder.operation_lock(self.directory, op['operation_id']):
            holder.record_exit(self.policy, self.root, self.home, op['operation_id'], 1)
            self.assertEqual(self.reconcile(), [])
            self.assertEqual(self.ops()[op['operation_id']]['state'], 'pending')
        # Restart without exit record can schedule the never-started preflight.
        self.assertEqual(self.reconcile(), [op['operation_id']])
        holder.record_exit(self.policy, self.root, self.home, op['operation_id'], 1)
        self.assertEqual(self.ops()[op['operation_id']]['state'], 'failed')
        self.assertEqual(self.reconcile(), [])

    def test_duplicate_creation_and_park_do_not_retire(self):
        op = self.started(self.reserve()); path = self.home / 'launches' / op['launch_id']
        for marker in ('complete', op['worker_id'] + '.deleted', op['worker_id'] + '.parked', op['worker_id'] + '.retired'):
            (path / marker).touch()
        self.reconcile(); self.assertIsNone(self.ops()[op['operation_id']]['retirement'])
        proof = self.retirement(op)
        done = json.loads((proof / 'deletion-completion.json').read_text()); done['id'] = 'wrong'
        (proof / 'deletion-completion.json').write_text(json.dumps(done))
        self.reconcile(); self.assertIsNone(self.ops()[op['operation_id']]['retirement'])

    def test_wrong_authority_and_pointer_alone_never_grant(self):
        op = self.started(self.reserve()); card = self.output(op)
        path = self.home / 'launches' / op['launch_id'] / 'collected' / (op['case'] + '.scorecard.json')
        changed = deepcopy(card); changed['job_money']['revision'] += 1; path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'legacy_retire'): self.publish(op)
        self.assertEqual(self.money()['jobs']['j']['acks'], {})
        self.assertFalse((self.directory / 'current').exists())

    def test_pointer_before_ack_crash_replays(self):
        op = self.started(self.reserve()); card = self.output(op)
        real = holder.atomic_json
        def crash(path, value):
            if path.name == 'money.json' and value['jobs']['j']['acks']: raise OSError('authored crash')
            return real(path, value)
        with patch.object(holder, 'atomic_json', crash), self.assertRaises(OSError): self.publish(op)
        self.assertEqual(status.read_rows(self.policy, self.root, self.home)[1][0]['phase'], 'unreadable')
        self.assertEqual(self.money()['jobs']['j']['acks'], {})
        ack = self.publish(op)
        self.assertEqual(ack['generation'], card['sha256'])
        self.assertEqual(self.publish(op), ack)

    def test_accounting_freeze_and_later_evidence_reconciles(self):
        op = self.started(self.reserve()); card = self.output(op, total=0)
        with self.assertRaises(ValueError): self.publish(op)
        self.assertTrue(self.money()['incidents'])
        with self.assertRaises(ValueError): self.reserve('k')
        self.assertFalse((self.directory / 'current').exists())
        self.output(op, payload=fixtures.KEY)
        self.publish(op)
        self.assertEqual(self.money()['incidents'], {})
        self.assertEqual(self.ops()[op['operation_id']]['incident'], None)

    def accountant(self):
        helper = accounting_fixtures.AccountingTests(); helper.setUp(); self.addCleanup(helper.doCleanups)
        return helper

    def test_real_d_null_ack_keeps_full_hold_and_revision(self):
        helper = self.accountant(); helper.unknown()
        op = self.started(self.reserve()); card = self.output(op, ledger=helper.ledger())
        self.assertIsNone(self.publish(op)['facts']['total_usd'])
        self.retirement(op); self.reconcile()
        successor = self.reserve(source=card['sha256'])
        self.assertEqual(successor['authority']['revision'], 1)
        self.assertEqual(successor['authority']['committed_total_usd'], '1000.000000000')
        self.assertEqual(self.money()['jobs']['j']['held_usd'], '1000.000000000')

    def test_real_d_estimate_receipt_decrease_replay(self):
        helper = self.accountant(); lease, row, wait, _ = helper.estimate()
        op = self.started(self.reserve()); self.output(op, ledger=helper.ledger())
        first = self.publish(op)
        helper.final(lease, wait); self.output(op, ledger=helper.ledger(), payload=fixtures.KEY)
        second = self.publish(op)
        self.assertLess(money.amount(second['facts']['total_usd']), money.amount(first['facts']['total_usd']))
        self.assertEqual(len(second['facts']['reconciled_decreases']), 1)
        self.assertEqual(self.publish(op), second)
        self.assertEqual(self.money()['jobs']['j']['previous']['estimated'], {})

    def test_equal_or_higher_final_receipt_clears_incident(self):
        # Stream D money row 21: no reconciled-decrease record exists when the
        # final charge is not lower, so the refused estimate must still extend.
        for final in (7, 9):
            with self.subTest(final=final):
                self.setUp()
                helper = self.accountant(); lease, row, wait, _ = helper.estimate()
                op = self.started(self.reserve()); self.output(op, ledger=helper.ledger(), total=0)
                with self.assertRaises(ValueError): self.publish(op)
                self.assertTrue(self.money()['incidents'])
                helper.receipt(lease, [('part', 3), ('final', final)], final=True)
                budget.settle(wait, work=helper.work, ledger_path=helper.path)
                self.assertNotIn('reconciled_decreases', helper.ledger())
                self.output(op, ledger=helper.ledger(), payload=fixtures.KEY)
                self.publish(op)
                self.assertEqual(self.money()['incidents'], {})
        lowered = helper.ledger(); lowered['invocation_reservations'][lease.lease_id]['event_ids'].remove('final')
        refused = dict(continuation_budget=helper.ledger()); refused['continuation_budget']['invocation_reservations'][
            lease.lease_id].update(state='estimated', estimated_gap_usd='7.000000000', event_ids=['part'])
        self.assertFalse(holder._extends(refused, dict(continuation_budget=lowered)))

    def test_estimate_frozen_across_resume_then_final_decrease_collects(self):
        # Stream D money row 21: the first ACK sees the closed gate's $4 estimate.
        # A resume without the receipt file keeps it (no growth to the $8
        # remaining maximum), so the final release is exactly the drop from that ACK.
        helper = self.accountant(); lease, row = helper.reserve()
        relative = helper.receipt(lease, [('part', 2)]); path = helper.work / relative
        value = json.loads(path.read_text())
        value['cap_used'] = dict(closed=True, forwarded_requests=1, settled_usd='2', held_usd='4')
        path.write_text(json.dumps(value))
        wait = helper.wait(lease, relative); budget.settle(wait, work=helper.work, ledger_path=helper.path)
        other, other_row = helper.reserve(); budget.reconcile_reservations(helper.work, helper.path)
        op = self.started(self.reserve()); self.output(op, ledger=helper.ledger())
        first = self.publish(op)
        self.assertEqual(first['facts']['estimated'], {row['invocation_id']: '4.000000000',
                                                       other_row['invocation_id']: '10.000000000'})
        path.unlink(); budget.reconcile_reservations(helper.work, helper.path)
        self.assertEqual(helper.ledger()['invocation_reservations'][lease.lease_id]['estimated_gap_usd'], '4.000000000')
        helper.receipt(lease, [('part', 2)], final=True); budget.settle(wait, work=helper.work, ledger_path=helper.path)
        # Negative control: the other call's estimate lowered without a final
        # receipt is not covered by this call's release.
        lowered = helper.ledger(); lowered['invocation_reservations'][other.lease_id]['estimated_gap_usd'] = '7.000000000'
        previous = {k: first['facts'][k] for k in ('total_usd', 'estimated')}
        with self.assertRaisesRegex(ValueError, '^unsupported_decrease$'):
            helper.facts(helper.snapshot_card(lowered), previous)
        self.output(op, ledger=helper.ledger(), payload=fixtures.KEY)
        second = self.publish(op)
        self.assertEqual(money.amount(first['facts']['total_usd']) - money.amount(second['facts']['total_usd']),
                         money.amount('4.000000000'))
        self.assertEqual([r['released_usd'] for r in second['facts']['reconciled_decreases']], ['4.000000000'])
        self.assertEqual(self.money()['incidents'], {})

    def test_real_d_known_overrun_then_null_keeps_floor(self):
        helper = self.accountant(); ledger = helper.ledger()
        # Authored overrun event on saved D ledger. The later unknown ledger
        # deliberately omits it, reproducing the dangerous aggregate input.
        ledger['events'].append(dict(id='authored-overrun', cost=1500, calls=1))
        ledger['cost'] += 1500; ledger['calls'] += 1
        op = self.started(self.reserve()); self.output(op, ledger=ledger)
        first = self.publish(op)
        self.assertTrue(self.money()['jobs']['j']['overrun'])
        floor = self.money()['jobs']['j']['known_floor_usd']
        helper.unknown(); self.output(op, ledger=helper.ledger(), payload=fixtures.KEY)
        second = self.publish(op)
        self.assertIsNone(second['facts']['total_usd'])
        self.assertEqual(self.money()['jobs']['j']['known_floor_usd'], floor)
        self.assertEqual(money.aggregate(self.money()), money.amount(first['facts']['total_usd']))
        self.assertTrue(self.money()['jobs']['j']['overrun'])
        self.retirement(op); self.reconcile()
        with self.assertRaises(ValueError): self.reserve(source=second['generation'])

    def test_ack_before_outbox_and_journal_crash_repairs(self):
        op = self.started(self.reserve()); self.output(op); self.publish(op)
        self.output(op, payload=fixtures.KEY)
        real = holder.atomic_json
        def crash(path, value):
            if path.parent.name == 'outbox' and value['state'] == 'acknowledged': raise OSError('authored crash')
            return real(path, value)
        with patch.object(holder, 'atomic_json', crash), self.assertRaises(OSError): self.publish(op)
        self.assertEqual(len(self.money()['jobs']['j']['acks']), 2)
        ack = self.publish(op)
        self.assertEqual(self.ops()[op['operation_id']]['output_generation'], ack['generation'])
        self.assertEqual(status.read_rows(self.policy, self.root, self.home)[1][0]['phase'], 'stopped')

    def test_reservation_before_projection_crash_repairs(self):
        real = holder.atomic_json
        def crash(path, value):
            if path.name == 'journal.json': raise OSError('authored crash')
            return real(path, value)
        with patch.object(holder, 'atomic_json', crash), self.assertRaises(OSError): self.reserve()
        op = next(iter(self.ops().values()))
        self.assertEqual(self.reserve(), op)
        self.assertEqual(status.read_rows(self.policy, self.root, self.home)[1][0]['phase'], 'pending')

    def test_two_sources_never_return_to_old_generation(self):
        op = self.started(self.reserve()); first = self.output(op); self.publish(op)
        self.retirement(op); self.reconcile()
        next_op = self.started(self.reserve(source=first['sha256']))
        second = self.output(next_op, payload=fixtures.KEY); self.publish(next_op)
        self.retirement(next_op); self.reconcile()
        third = self.reserve(source=second['sha256'])
        self.assertEqual(third['authority']['revision'], 3)
        with self.assertRaises(ValueError): self.reserve(source=first['sha256'])
        with self.assertRaises(ValueError): self.reserve()

    def test_initialized_orphan_uses_existing_resume_path(self):
        op = self.started(self.reserve()); path = self.home / 'launches' / op['launch_id']
        (path / 'monitor.sh').write_text('poll=1\n')
        self.assertEqual(holder.orphaned(self.policy, self.root, self.home), [op['operation_id']])
        with (path / 'controller.lock').open() as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(holder.orphaned(self.policy, self.root, self.home), [])
        self.policy['path'] = '/usr/bin:/bin'
        child = SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 0)
        with patch.object(holder.subprocess, 'Popen', return_value=child) as launch:
            holder.resume_controller(self.policy, self.root, self.home, op['operation_id'], b'authored identity')
        self.assertEqual(launch.call_args.args[0][-2:], ['--resume-launch', op['launch_id']])
        (path / 'complete').touch()
        self.assertEqual(holder.orphaned(self.policy, self.root, self.home), [])

    def test_retired_without_output_status_is_not_running(self):
        op = self.started(self.reserve()); self.retirement(op); self.reconcile()
        self.assertEqual(status.read_rows(self.policy, self.root, self.home)[1][0]['phase'], 'not collected')
        self.assertEqual(self.reconcile(), [])

    def test_r2_get_hash_must_match(self):
        path = self.root / 'cipher'; path.write_bytes(fixtures.CIPHER)
        with patch.object(holder.subprocess, 'check_output', return_value='https://example.invalid/object'), \
             patch.object(holder.urllib.request, 'urlopen', side_effect=[io.BytesIO(b''), io.BytesIO(b'corrupt')]):
            with self.assertRaisesRegex(ValueError, '^publication_failed$'):
                holder.r2_publish(self.root, 'key', path)

    def test_reserved_money_config_crash_repair(self):
        with patch.object(money, 'configuration', side_effect=OSError('authored config crash')):
            with self.assertRaises(OSError): self.reserve()
        authority = self.money()['jobs']['j']['authority']
        op = self.reserve(); self.assertEqual(op['authority'], authority)
        self.assertEqual(self.reserve()['operation_id'], op['operation_id'])


    # Diff review 1: holder robustness, wiring and the remaining matrix rows.

    def concurrency(self, value=2):
        self.record['max_concurrency'] = self.policy['batch']['max_concurrency'] = value; self.freeze()

    def preflight(self, op, *, inventory=None, run_error=None, popen_error=None):
        """Real dispatch preflight; only identity, credential labels, Boat and the creator are doubles."""
        import key_holder
        import account_handoff
        self.policy.update(code_sha256='fingerprint', path='/usr/bin:/bin', recipient='founder-public')
        calls = []
        def run(argv, **kwargs):
            if run_error is not None: raise run_error
            data = (self.record['restore_recipient'].encode() if argv[0] == 'age-keygen' else
                    json.dumps(inventory or dict(sandboxes=[], pageInfo=dict(hasMore=False))).encode())
            return SimpleNamespace(stdout=data)
        def popen(argv, **kwargs):
            calls.append(argv)
            if popen_error is not None: raise popen_error
            return SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 0)
        with ExitStack() as stack:
            stack.enter_context(patch.object(key_holder, 'fingerprint', return_value='fingerprint'))
            # Phase B live checks have their own real-dispatch tests (test_preflight.py).
            stack.enter_context(patch.object(preflight, 'decrypt', return_value={'claude-token': b''}))
            stack.enter_context(patch.object(preflight, 'dispatch_checks'))
            stack.enter_context(patch.object(account_handoff, 'launch_accounts', return_value=(None, 1, {})))
            stack.enter_context(patch.object(holder.subprocess, 'run', side_effect=run))
            stack.enter_context(patch.object(holder.subprocess, 'Popen', side_effect=popen))
            try: result = holder.dispatch(self.policy, self.root, self.home, op['operation_id'], b'authored identity')
            except (OSError, ValueError) as error: result = error
        return result, calls

    def test_batch_tick_never_stops_and_records_only_dispatch_exits(self):
        import key_holder
        exits, spawned = [], []
        def done(code): return SimpleNamespace(poll=lambda: code)
        children = {'a': ('dispatch', done(1)), 'b': ('resume', done(0)), 'c': ('dispatch', done(holder.TEMPFAIL)),
                    'd': ('dispatch', done(1)), 'e': ('dispatch', done(None))}
        def record(policy, root, home, operation, code):
            if operation == 'd': raise ValueError('authored corrupt reservations')
            exits.append((operation, code))
        waits = {}
        with patch.object(holder, 'record_exit', side_effect=record), \
             patch.object(holder, 'record_child', return_value=0), \
             patch.object(holder, 'reconcile', side_effect=OSError('authored corrupt money')), \
             patch.object(holder, 'orphaned', return_value=['c', 'e', 'f']), \
             patch.object(holder, 'unpublished', return_value=[]):
            key_holder.batch_tick(self.policy, children, waits, lambda op, action: spawned.append((op, action)) or op)
        self.assertEqual(exits, [('a', 1), ('c', holder.TEMPFAIL)])
        # A refused exit record keeps its child for the next tick; a live child is never duplicated.
        self.assertEqual(set(children), {'d', 'e', 'f'})
        # A transient dispatch exit waits before the next preflight.
        self.assertEqual(spawned, [('f', 'resume')])
        with patch.object(holder, 'HOLDER_ENABLED', False), patch.object(holder, 'reconcile') as scan:
            key_holder.batch_tick(self.policy, {}, {}, None); scan.assert_not_called()

    def test_batch_tick_survives_real_corrupt_money(self):
        import key_holder
        self.reserve()
        (self.directory / 'money.json').write_text('{invalid')
        with patch.multiple(key_holder, ROOT=self.root, CONTROL_HOME=self.home), \
             patch.object(holder, 'orphaned', return_value=[]) as resume, \
             patch.object(holder, 'unpublished', return_value=[]) as publish, \
             patch.object(sys, 'stderr', io.StringIO()) as errors:
            key_holder.batch_tick(self.policy, {}, {}, None)
        self.assertIn('batch scan refused', errors.getvalue())
        resume.assert_called_once()
        publish.assert_called_once()

    def test_reconcile_isolates_a_refused_operation(self):
        self.concurrency()
        bad, good = self.started(self.reserve('j')), self.started(self.reserve('k'))
        path = self.home / 'launches' / bad['launch_id']
        (path / 'new.1').write_text(json.dumps(dict(event='created', id='authored-other')) + '\n')
        (path / 'ids').write_text('authored-other\n')
        self.retirement(bad); self.retirement(good)
        before = self.ops()[bad['operation_id']]
        self.assertEqual(self.reconcile(), [])
        self.assertEqual(self.ops()[bad['operation_id']], before)
        self.assertIsNotNone(self.ops()[good['operation_id']]['retirement'])

    def test_socket_routes_reply_refuse_and_fall_through(self):
        import key_holder
        with patch.multiple(key_holder, ROOT=self.root, CONTROL_HOME=self.home):
            launch = dict(op='launch', batch='practice', job='j', checkpoint=None)
            reply = key_holder.batch_request(self.policy, launch)
            self.assertEqual(set(reply), {'operation_id', 'launch_id', 'state', 'worker_id'})
            self.assertEqual(reply['state'], 'pending')
            self.assertEqual(key_holder.batch_request(self.policy, launch), reply)
            self.assertEqual(key_holder.batch_request(self.policy, dict(op='operation', batch='practice',
                             operation_id=reply['operation_id'])), reply)
            for request in (dict(launch, batch='other'), dict(launch, case='case-x'),
                            dict(op='operation', batch='practice', operation_id='not-a-uuid')):
                with self.assertRaises(ValueError): key_holder.batch_request(self.policy, request)
            with patch.object(holder, 'HOLDER_ENABLED', False):
                self.assertIsNone(key_holder.batch_request(self.policy, launch))
            self.assertIsNone(key_holder.batch_request({'jobs': {}}, launch))
            self.assertIsNone(key_holder.batch_request(self.policy, dict(op='status')))

    def test_serve_refuses_a_policy_the_shell_commands_would_not_load(self):
        import key_holder
        with patch.multiple(key_holder, CONTROL_HOME=self.home, policy_load=lambda path: self.policy), \
             patch.object(key_holder.resource, 'setrlimit'), patch.object(key_holder.os, 'umask'):
            with self.assertRaisesRegex(ValueError, 'control home policy'):
                key_holder.serve(self.root / 'elsewhere.json', .01)
            # The canonical path passes the policy check and reaches runtime setup.
            with patch.object(key_holder, 'secure_directory', side_effect=StopIteration) as setup:
                with self.assertRaises(StopIteration):
                    key_holder.serve((self.home / 'policy.json').resolve(), .01)
                setup.assert_called_once_with(key_holder.RUNTIME)

    def test_enabled_bind_restores_only_the_frozen_source(self):
        import batch
        op = self.started(self.reserve()); card = self.output(op); self.publish(op)
        self.retirement(op); self.reconcile()
        successor = self.reserve(source=card['sha256'])
        job = batch.bind(self.policy, 'j', card['sha256'], self.root, home=self.home, operation=successor['operation_id'])
        self.assertEqual(job['args'][-4:], ['--restore', op['case'], '--checkpoint-sha256', card['sha256']])
        with self.assertRaises(ValueError):  # The retired predecessor grants no source.
            batch.bind(self.policy, 'j', card['sha256'], self.root, home=self.home, operation=op['operation_id'])

    def test_transient_preflight_stays_pending(self):
        import subprocess
        self.concurrency(); op = self.reserve()
        result, calls = self.preflight(op, run_error=subprocess.TimeoutExpired('age-keygen', 10))
        self.assertEqual((result, calls), (holder.TEMPFAIL, []))
        holder.record_exit(self.policy, self.root, self.home, op['operation_id'], result)
        self.assertEqual(self.ops()[op['operation_id']]['state'], 'pending')
        self.assertIsNone(self.ops()[op['operation_id']]['dispatch_exit'])
        self.assertEqual(self.reconcile(), [op['operation_id']])
        # A peer's accounting incident freezes the batch; it is not a refusal of this operation.
        peer = self.started(self.reserve('k')); self.output(peer, total=0)
        with self.assertRaises(ValueError): self.publish(peer)
        result, calls = self.preflight(op)
        self.assertEqual((result, calls), (holder.TEMPFAIL, []))
        self.assertEqual(self.ops()[op['operation_id']]['state'], 'pending')

    def test_positive_preflight_refusal_fails_once_and_never_retries(self):
        for inventory in (dict(sandboxes=[], pageInfo=dict(hasMore=True)),
                          dict(sandboxes=[dict(id='w'), dict(id='w')], pageInfo=dict(hasMore=False))):
            with self.subTest(inventory=inventory):
                self.setUp()
                op = self.reserve()
                result, calls = self.preflight(op, inventory=inventory)
                self.assertIsInstance(result, ValueError); self.assertEqual(calls, [])
                self.assertEqual(self.ops()[op['operation_id']]['state'], 'failed')
                self.assertEqual(self.ops()[op['operation_id']]['incident'], 'preflight_refused')
                self.assertEqual(status.read_rows(self.policy, self.root, self.home)[1][0]['phase'], 'failed')
                self.assertEqual(self.reconcile(), [])
                self.assertEqual(self.preflight(op), (None, []))
                self.assertEqual(self.reserve()['state'], 'failed')

    def test_overlapping_dispatch_children_invoke_one_creator(self):
        op = self.reserve()
        with holder.operation_lock(self.directory, op['operation_id']):
            # The losing child cannot take the operation lock, and its exit is ignored.
            result, calls = self.preflight(op)
            self.assertIsInstance(result, BlockingIOError); self.assertEqual(calls, [])
            holder.record_exit(self.policy, self.root, self.home, op['operation_id'], 1)
            self.assertEqual(self.ops()[op['operation_id']]['state'], 'pending')
        self.assertEqual(len(self.preflight(op)[1]), 1)
        self.assertEqual(self.preflight(op)[1], [])

    def test_ambiguous_creation_records_stay_pending(self):
        event = json.loads((ROOT / 'tests/factory/fixtures/isolation-timeouts/created.json').read_text())
        for events, ids in (([event, event], [event['id']]), ([event, event], [event['id']] * 2),
                            ([event], [event['id']] * 2), ([event, dict(event, id='authored-other')], [event['id']])):
            with self.subTest(events=len(events), ids=ids):
                self.setUp()
                op = self.started(self.reserve(), created=False); path = self.home / 'launches' / op['launch_id']
                (path / 'new.1').write_text(''.join(json.dumps(e) + '\n' for e in events))
                (path / 'ids').write_text(''.join(i + '\n' for i in ids))
                self.reconcile()
                self.assertEqual(self.ops()[op['operation_id']]['state'], 'pending')
                self.assertEqual(self.ops()[op['operation_id']]['incident'], 'creation_unknown')

    def test_malformed_reservation_and_identity_refuse(self):
        op = self.reserve()
        with self.assertRaises(ValueError): holder.operation_lock(self.directory, str(__import__('uuid').uuid4())).__enter__()
        raw = json.loads((self.directory / 'reservations.json').read_text())
        del raw['operations'][op['operation_id']]['incident']
        (self.directory / 'reservations.json').write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, 'invalid batch operations'): self.reserve()
        with self.assertRaisesRegex(ValueError, 'invalid batch operations'): self.reconcile()

    def test_repeat_refusal_keeps_original_incident(self):
        op = self.started(self.reserve()); self.output(op)
        # Authored D answers: the same generation is refused for two different reasons.
        with patch.object(holder, 'collection_facts', side_effect=[ValueError('uncovered_total'),
                                                                   ValueError('accounting_api_refused')]):
            with self.assertRaises(ValueError): self.publish(op)
            first = deepcopy(self.money()['incidents'])
            with self.assertRaises(ValueError): self.publish(op)
        self.assertEqual([i['reason'] for i in first.values()], ['uncovered_total'])
        self.assertEqual(self.money()['incidents'], first)
        self.assertEqual(status.read_rows(self.policy, self.root, self.home)[1][0]['phase'], 'unreadable')

    def test_publication_crash_before_and_during_put_replays(self):
        for failing in (0, 1):
            with self.subTest(failing_object=failing):
                self.setUp()
                op = self.started(self.reserve()); self.output(op); sent = []
                def transport(key, path):
                    if len(sent) == failing: raise ValueError('publication_failed')
                    sent.append(key)
                with self.assertRaisesRegex(ValueError, 'publication_failed'):
                    holder.collect(self.policy, self.root, self.home, op['operation_id'], transport)
                self.assertEqual(self.money()['jobs']['j']['acks'], {})
                self.assertFalse((self.directory / 'current').exists())
                ack = self.publish(op)
                self.assertEqual(sorted(k.rsplit('/', 1)[1] for k in self.objects),
                                 sorted([*json.loads((self.directory / 'generations' / op['case'] / ack['generation']
                                                     / 'manifest.json').read_text())['files'], 'manifest.json']))

    def test_retirement_crash_between_money_and_reservations_repairs(self):
        op = self.started(self.reserve()); self.output(op); self.publish(op); self.retirement(op)
        with patch.object(holder, '_save', side_effect=OSError('authored crash')), self.assertRaises(OSError):
            self.reconcile()
        proof = self.money()['jobs']['j']['acks'][self.ops()[op['operation_id']]['output_generation']]['retirement']
        self.assertIsNotNone(proof); self.assertIsNone(self.ops()[op['operation_id']]['retirement'])
        self.reconcile()
        self.assertEqual(self.ops()[op['operation_id']]['retirement'], proof)

    def test_source_lookup_waits_for_the_holder_scan(self):
        import threading, time
        op = self.reserve(); result = []
        with money.locked(self.home, 'practice'):
            worker = threading.Thread(target=lambda: result.append(holder.source_directory(
                self.policy, self.root, self.home, op['operation_id'])))
            worker.start(); time.sleep(.2)
            self.assertTrue(worker.is_alive())
        worker.join(5)
        self.assertEqual(result, [None])

    def test_r2_interrupted_put_is_a_publication_failure(self):
        path = self.root / 'cipher'; path.write_bytes(fixtures.CIPHER)
        with patch.object(holder.subprocess, 'check_output', return_value='https://example.invalid/object'), \
             patch.object(holder.urllib.request, 'urlopen', side_effect=ConnectionResetError('authored reset')):
            with self.assertRaisesRegex(ValueError, '^publication_failed$'):
                holder.r2_publish(self.root, 'key', path)

    # Activation readiness: bounded retries, lost-exit, publication replay, terminal status.

    def test_resume_respawn_is_bounded_and_turns_terminal(self):
        import key_holder
        op = self.started(self.reserve()); identity = op['operation_id']
        (self.home / 'launches' / op['launch_id'] / 'monitor.sh').write_text('poll=1\n')
        self.assertEqual(holder.orphaned(self.policy, self.root, self.home), [identity])
        children, waits, spawned = {}, {}, []
        spawn = lambda operation, action: spawned.append((operation, action)) or SimpleNamespace(poll=lambda: 1)
        now = 1000.0
        with patch.multiple(key_holder, ROOT=self.root, CONTROL_HOME=self.home), \
             patch.object(key_holder.time, 'monotonic', side_effect=lambda: now):
            key_holder.batch_tick(self.policy, children, waits, spawn)
            for attempt in range(1, holder.RETRY_LIMIT + 1):
                key_holder.batch_tick(self.policy, children, waits, spawn)
                self.assertEqual(self.ops()[identity]['failures'], attempt)
                if attempt == holder.RETRY_LIMIT: break
                delay = 60 * 2 ** (attempt - 1)
                self.assertEqual(waits[identity], now + delay)
                now += delay - 1
                key_holder.batch_tick(self.policy, children, waits, spawn)
                self.assertEqual(len(spawned), attempt)
                now += 1
                if attempt == 2:
                    # A fresh holder must continue the durable count mid-retry.
                    children, waits = {}, {}
                key_holder.batch_tick(self.policy, children, waits, spawn)
                self.assertEqual(len(spawned), attempt + 1)
            self.assertEqual(spawned.count((identity, 'resume')), holder.RETRY_LIMIT)
            self.assertEqual(holder.orphaned(self.policy, self.root, self.home), [])
            target, rows = status.read_rows(self.policy, self.root, self.home)
            self.assertIn('resume failed', status.render(target, rows, None, {}))
            key_holder.batch_tick(self.policy, {}, {}, spawn)
            self.assertEqual(len(spawned), holder.RETRY_LIMIT)
            self.assertEqual(self.ops()[identity]['failures'], holder.RETRY_LIMIT)

    def test_resume_that_completes_is_not_counted(self):
        op = self.started(self.reserve()); identity = op['operation_id']
        (self.home / 'launches' / op['launch_id'] / 'complete').touch()
        # complete means the controller finished its job, so a nonzero exit is not a failure.
        self.assertEqual(holder.record_child(self.policy, self.root, self.home, identity, 'resume', 1), 0)
        self.assertEqual(self.ops()[identity]['failures'], 0)
        self.assertIsNone(self.ops()[identity]['incident'])

    def test_lost_dispatch_exit_fails_without_a_recorded_exit(self):
        self.concurrency()
        op = self.started(self.reserve(), created=False); identity = op['operation_id']
        self.assertIsNone(self.ops()[identity]['dispatch_exit'])
        # A live owner still holding the operation lock keeps it pending.
        with holder.operation_lock(self.directory, identity):
            self.reconcile()
        self.assertEqual(self.ops()[identity]['state'], 'pending')
        # Free locks, no creation records, no recorded exit: the dispatch child is gone, so fail it.
        self.reconcile()
        self.assertEqual(self.ops()[identity]['state'], 'failed')
        self.assertEqual(self.ops()[identity]['incident'], 'preflight_refused')
        # Missing launch directory: reconcile creates the fence, fails the op, and a late start refuses.
        k = self.reserve('k'); kid = k['operation_id']
        with money.locked(self.home, self.record['id']):
            ops = self.ops(); ops[kid].update(dispatch_started=True,
                launch=dict(argv=['1'], environment={'UNBUG_BATCH_OPERATION': kid}))
            holder._save(self.directory, self.record, self.policy, ops)
        path = self.home / 'launches' / k['launch_id']
        self.assertFalse(path.exists())
        self.reconcile()
        self.assertTrue(path.is_dir())
        self.assertEqual(self.ops()[kid]['state'], 'failed')
        start = subprocess.run([sys.executable, '-B', str(ROOT / 'factory/control_resume.py'), '1'],
                               capture_output=True, env={'PATH': os.environ['PATH'],
                               'UNBUG_CONTROL_HOME': str(self.home), 'UNBUG_LAUNCH_ID': k['launch_id']})
        self.assertNotEqual(start.returncode, 0)
        self.assertIn(b'FileExistsError', start.stderr)
        self.assertFalse((path / 'launch.json').exists())
        self.assertFalse((path / 'controller.lock').exists())

    def test_early_exit_before_guard_init_has_no_ids(self):
        op = self.started(self.reserve(), created=False); identity = op['operation_id']
        path = self.home / 'launches' / op['launch_id']
        (path / 'ids').unlink()  # control_resume initialized; launch.sh never reached guard_init.
        with (path / 'controller.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.reconcile()
            self.assertEqual(self.ops()[identity]['state'], 'pending')
        # Creation evidence is still ambiguous even without ids.
        (path / 'new.1.pending').touch()
        self.reconcile()
        self.assertEqual(self.ops()[identity]['state'], 'pending')
        (path / 'new.1.pending').unlink()
        # A nonregular ids entry must not be treated as missing.
        (path / 'ids').symlink_to(path / 'absent')
        self.reconcile()
        self.assertEqual(self.ops()[identity]['state'], 'pending')
        (path / 'ids').unlink()
        self.reconcile()
        self.assertEqual(self.ops()[identity]['state'], 'failed')
        self.assertEqual(self.ops()[identity]['incident'], 'preflight_refused')
        self.assertIsNone(self.ops()[identity]['dispatch_exit'])

    def test_publication_replay_and_terminal(self):
        self.concurrency()
        op = self.started(self.reserve()); self.output(op); identity = op['operation_id']
        (self.home / 'launches' / op['launch_id'] / 'complete').touch()
        import key_holder
        # First publication fails at transport, leaving durable pending evidence.
        with self.assertRaisesRegex(ValueError, 'publication_failed'):
            holder.collect(self.policy, self.root, self.home, identity,
                           lambda *args: (_ for _ in ()).throw(ValueError('publication_failed')))
        outbox = self.directory / 'outbox' / (identity + '.json')
        self.assertEqual(json.loads(outbox.read_text())['state'], 'pending')
        self.assertEqual(self.money()['jobs']['j']['acks'], {})
        self.assertFalse((self.directory / 'current' / (op['case'] + '.json')).exists())
        self.assertEqual(holder.unpublished(self.policy, self.root, self.home), [identity])
        # Synthetic assignments use bin/setup-secrets' exact four-line format.
        values = dict(R2_ACCOUNT_ID='synthetic-account', R2_ACCESS_KEY_ID='synthetic-access',
                      R2_SECRET_ACCESS_KEY='synthetic-key/+=', R2_BUCKET='synthetic-bucket')
        data = ''.join(f'{key}={value}\n' for key, value in values.items()).encode()
        archive = self.root / 'synthetic-r2.tar'
        with tarfile.open(archive, 'w') as target:
            member = tarfile.TarInfo('r2-env'); member.size = len(data)
            target.addfile(member, io.BytesIO(data))
        bindir = self.root / 'synthetic-bin'; bindir.mkdir()
        age = bindir / 'age'
        age.write_text('#!/bin/sh\ncat ' + shlex.quote(str(archive)) + '\n')
        age.chmod(0o755)
        keys = []
        real_replay = holder.publish_replay
        def replay(*args):
            keys.append(args[-1])
            return real_replay(*args)
        def transport(root, key, path):
            self.assertEqual({name: os.environ[name] for name in values}, values)
            self.objects[key] = path.read_bytes()
        with patch.dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH']), \
             patch.multiple(key_holder, ROOT=self.root, CONTROL_HOME=self.home), \
             patch.object(key_holder, 'policy_load', return_value=self.policy), \
             patch.object(sys, 'argv', ['batch_holder.py', 'publish', '--operation', identity]), \
             patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(b'synthetic identity'))), \
             patch.object(holder, 'publish_replay', side_effect=replay), \
             patch.object(holder, 'r2_publish', side_effect=transport):
            self.assertEqual(holder.main(), 0)
        self.assertEqual(keys, [bytearray(len(b'synthetic identity'))])
        generation = self.ops()[identity]['output_generation']
        self.assertIn(generation, self.money()['jobs']['j']['acks'])
        pointer = json.loads((self.directory / 'current' / (op['case'] + '.json')).read_text())
        self.assertEqual(pointer['generation'], generation)
        self.assertEqual(json.loads(outbox.read_text())['state'], 'acknowledged')
        self.assertTrue(self.objects)
        self.assertEqual(holder.unpublished(self.policy, self.root, self.home), [])
        # Five failed publish children make it terminal and stop the scan.
        peer = self.started(self.reserve('k')); self.output(peer); pid = peer['operation_id']
        (self.home / 'launches' / peer['launch_id'] / 'complete').touch()
        self.assertEqual(holder.unpublished(self.policy, self.root, self.home), [pid])
        for attempt in range(1, holder.RETRY_LIMIT + 1):
            expected = 0 if attempt == holder.RETRY_LIMIT else attempt
            self.assertEqual(holder.record_child(self.policy, self.root, self.home, pid, 'publish', 1), expected)
        self.assertEqual(self.ops()[pid]['incident'], 'publication_failed')
        self.assertEqual(holder.unpublished(self.policy, self.root, self.home), [])

    def test_status_flags_terminal_successors(self):
        for disposition in ('failed', 'retired'):
            with self.subTest(successor=disposition):
                self.setUp()
                op = self.started(self.reserve()); card = self.output(op); self.publish(op)
                self.retirement(op); self.reconcile()
                successor = self.reserve(source=card['sha256']); sid = successor['operation_id']
                if disposition == 'failed':
                    with money.locked(self.home, self.record['id']):
                        ops = self.ops(); ops[sid].update(dispatch_started=True,
                            launch=dict(argv=['1'], environment={'UNBUG_BATCH_OPERATION': sid}))
                        holder._save(self.directory, self.record, self.policy, ops)
                    self.reconcile()  # missing dir -> fenced and failed
                    phase, flag = 'failed', 'launch failed'
                else:
                    successor = self.started(successor); self.retirement(successor); self.reconcile()
                    phase, flag = 'stopped', 'retired without output'
                target, rows = status.read_rows(self.policy, self.root, self.home)
                row = next(r for r in rows if r['case'] == op['case'])
                # The terminal successor is the chain head; the predecessor's collected card is still shown.
                self.assertEqual(row['phase'], phase)
                self.assertEqual(row['card']['sha256'], card['sha256'])
                self.assertIn(op['case'] + ': ' + flag, status.render(target, rows, None, {}))

class WaitSchedulingTests(unittest.TestCase):
    """Offline controller composition, not live provider/retirement closure proof."""
    locals().update({k: v for k, v in vars(HolderTests).items() if not k.startswith(('test_', '__'))})

    def waiting(self, job='j', *, changes=None, stop='provider_wait', publish=True, retire=True,
                payload=fixtures.CIPHER):
        op = self.started(self.reserve(job))
        card = self.output(op, payload=payload)
        card.update(terminal_stop=stop, provider_wait=dict(
            wait_id='9cf3f991-b1d6-4e26-a3f5-92b54ac40a16', reason='rate',
            retry_after='2027-01-01T00:00:00Z', role='writer', route='claude/opus',
            account='claude-factory-token-2', evidence='denied_before_work',
            batch_deadline=self.record['batch_deadline']))
        card['provider_wait'].update(changes or {})
        # Real runner leaves diagnosis_state absent for non-exhausted waits.
        import diagnosis
        card.pop('diagnosis_state', None)
        diagnosis.record_exhaustion(card)
        path = self.home / 'launches' / op['launch_id'] / 'collected' / (op['case'] + '.scorecard.json')
        path.write_text(json.dumps(card))
        if publish: self.publish(op)
        if retire: self.retirement(op); self.reconcile()
        return op, card

    def clock(self, stamp):
        from datetime import datetime
        clock = patch.object(holder, 'datetime', wraps=datetime)
        mocked = clock.start(); self.addCleanup(clock.stop)
        mocked.now.return_value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        return mocked

    def scan(self): return holder.schedule_waits(self.policy, self.root, self.home)

    def test_tick_future_due_restart_and_single_successor(self):
        import key_holder
        op, card = self.waiting()
        self.assertNotIn('diagnosis_state', card)
        clock = self.clock('2026-12-31T23:59:59Z')
        def tick():
            with patch.multiple(key_holder, ROOT=self.root, CONTROL_HOME=self.home):
                key_holder.batch_tick(self.policy, {}, {}, spawn)
        spawned = []
        def spawn(identity, action):
            spawned.append((identity, action))
            return SimpleNamespace(poll=lambda: None)
        with patch.object(service, '_snapshot', wraps=service._snapshot) as snapshot:
            tick(); tick(); snapshot.assert_not_called()
        self.assertEqual(len(self.ops()), 1); self.assertEqual(spawned, [])
        clock.now.return_value = holder.datetime.fromisoformat('2027-01-01T00:00:00+00:00')
        before = self.money()['jobs']['j']
        tick()  # reserves only; no creator in this scan
        self.assertEqual(spawned, [])
        successor = next(v for v in self.ops().values() if v['source_generation'])
        after = self.money()['jobs']['j']
        self.assertEqual(after['held_usd'], before['held_usd'])
        self.assertEqual(successor['authority']['reservation_id'], op['authority']['reservation_id'])
        self.assertEqual(after['sources'], [None, card['sha256']])
        self.assertEqual(after['authority']['revision'], 2)
        self.assertFalse((self.directory / 'retirements').exists())
        tick()  # empty process maps model a holder restart
        self.assertEqual(spawned, [(successor['operation_id'], 'dispatch')])
        self.scan(); self.assertEqual(len(self.ops()), 2)
        # A failed successor still consumes the source; no fresh operation is minted.
        holder.record_exit(self.policy, self.root, self.home, successor['operation_id'], 1)
        tick(); self.assertEqual(len(self.ops()), 2)
        self.assertEqual(len(spawned), 1)

    def test_invalid_waits_never_reserve(self):
        variants = [dict(wait_id='bad'), dict(wait_id='9cf3f991-b1d6-5e26-a3f5-92b54ac40a16'),
                    dict(reason='unbounded_route'), dict(reason='unknown'), dict(reason=[]),
                    dict(evidence='unknown'), dict(retry_after=None),
                    dict(retry_after='2027-01-01T00:00:00'),
                    dict(retry_after='2099-01-01T00:00:00Z'),
                    dict(batch_deadline='2098-01-01T00:00:00Z')]
        for changes in variants:
            with self.subTest(changes=changes):
                self.setUp(); self.waiting(changes=changes); self.clock('2027-01-01T00:00:00Z')
                self.scan(); self.assertEqual(len(self.ops()), 1)
        for stop in ('budget_exhausted', 'sealed'):
            with self.subTest(stop=stop):
                self.setUp(); self.waiting(stop=stop); self.clock('2027-01-01T00:00:00Z')
                self.scan(); self.assertEqual(len(self.ops()), 1)

    def test_each_publication_and_retirement_proof_is_required(self):
        for missing in ('ack', 'pointer', 'outbox', 'retirement', 'snapshot'):
            with self.subTest(missing=missing):
                self.setUp(); op, card = self.waiting(); self.clock('2027-01-01T00:00:00Z')
                if missing == 'ack':
                    state = self.money(); state['jobs']['j']['acks'] = {}
                    holder.atomic_json(self.directory / 'money.json', state)
                elif missing == 'pointer':
                    (self.directory / 'current' / (op['case'] + '.json')).unlink()
                elif missing == 'outbox':
                    (self.directory / 'outbox' / (op['operation_id'] + '.json')).unlink()
                elif missing == 'retirement':
                    ops = self.ops(); ops[op['operation_id']]['retirement'] = None
                    holder._save(self.directory, self.record, self.policy, ops)
                else:
                    path = self.directory / 'generations' / op['case'] / card['sha256'] / card['archive']
                    path.write_bytes(b'corrupt retained ciphertext')
                self.scan(); self.assertEqual(len(self.ops()), 1)
                self.assertEqual(service._json(self.directory / 'money.json')['jobs']['j']['sources'], [None])

    def test_ack_and_retirement_arriving_later(self):
        op, card = self.waiting(publish=False, retire=False)
        self.clock('2027-01-01T00:00:00Z')
        self.scan(); self.assertEqual(len(self.ops()), 1)
        self.publish(op); self.scan(); self.assertEqual(len(self.ops()), 1)
        self.retirement(op); self.reconcile(); self.scan()
        self.assertEqual(len(self.ops()), 2)

    def test_money_advance_reservation_journal_and_lost_reply_crashes(self):
        for boundary in ('configuration', 'reservations.json', 'journal.json', 'reply'):
            with self.subTest(boundary=boundary):
                self.setUp(); op, card = self.waiting(); self.clock('2027-01-01T00:00:00Z')
                real_write, real_reserve = holder.atomic_json, holder.reserve
                def write(path, value):
                    if path.name == boundary: raise OSError('authored crash')
                    return real_write(path, value)
                def lost_reply(*args, **kwargs):
                    real_reserve(*args, **kwargs)
                    raise OSError('authored lost reply')
                with ExitStack() as stack:
                    if boundary == 'configuration':
                        stack.enter_context(patch.object(money, 'configuration', side_effect=OSError('authored crash')))
                    elif boundary == 'reply': stack.enter_context(patch.object(holder, 'reserve', side_effect=lost_reply))
                    else: stack.enter_context(patch.object(holder, 'atomic_json', side_effect=write))
                    self.scan()
                authority = self.money()['jobs']['j']['authority']
                self.assertEqual(authority['source_generation'], card['sha256'])
                self.scan(); self.reconcile(); self.scan()
                self.assertEqual(len(self.ops()), 2)
                self.assertEqual(self.money()['jobs']['j']['authority'], authority)
                self.assertEqual(self.money()['jobs']['j']['sources'], [None, card['sha256']])
                self.assertEqual(service._json(self.directory / 'journal.json')['operations'], self.ops())

    def test_concurrency_deadline_and_money_freeze(self):
        op, card = self.waiting(); self.clock('2027-01-01T00:00:00Z')
        peer = self.reserve('k')
        self.scan(); self.assertEqual(len(self.ops()), 2)  # peer consumes the only slot
        holder.record_exit(self.policy, self.root, self.home, peer['operation_id'], 1)
        state = self.money()
        state['incidents'][op['operation_id'] + '/' + card['sha256']] = dict(
            operation_id=op['operation_id'], generation=card['sha256'],
            manifest_sha256=state['jobs']['j']['acks'][card['sha256']]['manifest_sha256'],
            reason='invalid_accounting_input')
        holder.atomic_json(self.directory / 'money.json', state)
        self.scan(); self.assertEqual(len(self.ops()), 2)
        state['incidents'] = {}; holder.atomic_json(self.directory / 'money.json', state)
        self.clock('2099-01-01T00:00:00Z'); self.scan(); self.assertEqual(len(self.ops()), 2)

    def test_refused_candidate_does_not_block_peer_and_credentials_retry(self):
        self.concurrency()
        first, _ = self.waiting('j')
        second, _ = self.waiting('k', changes=dict(reason='credential_expiring', evidence='interrupted'))
        self.clock('2027-01-01T00:00:00Z')
        (self.directory / 'current' / (first['case'] + '.json')).unlink()
        self.scan()
        successors = [v for v in self.ops().values() if v['source_generation']]
        self.assertEqual([v['job'] for v in successors], ['k'])

    def test_filter_cannot_authorize_tampered_card_or_changed_predicate(self):
        op, card = self.waiting(); self.clock('2027-01-01T00:00:00Z')
        # A valid-looking public projection still requires the immutable manifest.
        path = self.directory / 'generations' / op['case'] / card['sha256'] / (op['case'] + '.scorecard.json')
        card['provider_wait']['reason'] = 'quota'; path.write_text(json.dumps(card))
        self.scan(); self.assertEqual(len(self.ops()), 1)
        self.setUp(); op, card = self.waiting(changes=dict(reason='unbounded_route'))
        self.clock('2027-01-01T00:00:00Z')
        real = holder._wait_due
        calls = []
        def only_skip_first(card, record):
            calls.append(True)
            if len(calls) > 1: return real(card, record)
        with patch.object(holder, '_wait_due', side_effect=only_skip_first): self.scan()
        self.assertEqual(len(calls), 2); self.assertEqual(len(self.ops()), 1)

    def test_stale_generation_and_incident_never_schedule(self):
        op, card = self.waiting(); self.clock('2027-01-01T00:00:00Z')
        ops = self.ops(); ops[op['operation_id']]['incident'] = 'publication_failed'
        holder._save(self.directory, self.record, self.policy, ops)
        self.scan(); self.assertEqual(len(self.ops()), 1)
        ops[op['operation_id']]['incident'] = None
        holder._save(self.directory, self.record, self.policy, ops)
        self.scan()
        successor = next(v for v in self.ops().values() if v['source_generation'])
        successor = self.started(successor)
        self.output(successor, payload=fixtures.KEY); self.publish(successor)
        self.retirement(successor); self.reconcile()
        self.scan(); self.assertEqual(len(self.ops()), 2)  # new terminal output isn't a wait
        with self.assertRaises(ValueError):
            holder.reserve(self.policy, self.root, self.home, 'j', card['sha256'], provider_wait=True)
        with self.assertRaises(ValueError):
            holder.reserve(self.policy, self.root, self.home, 'j', None, provider_wait=True)

    def test_scheduled_dispatch_uncertainty_never_creates_twice(self):
        op, card = self.waiting(); self.clock('2027-01-01T00:00:00Z'); self.scan()
        successor = next(v for v in self.ops().values() if v['source_generation'])
        # Existing preflight helper simulates a lost creator reply after durable intent.
        result, calls = self.preflight(successor, popen_error=OSError('authored transport uncertainty'))
        self.assertEqual(result, holder.TEMPFAIL); self.assertEqual(len(calls), 1)
        self.assertTrue(self.ops()[successor['operation_id']]['dispatch_started'])
        _, repeated = self.preflight(successor)
        self.assertEqual(repeated, [])
        self.scan()
        self.assertEqual(len(self.ops()), 2)
        self.assertEqual(self.money()['jobs']['j']['sources'], [None, card['sha256']])


class ShellWiringTests(unittest.TestCase):
    """Real collect.sh, launch.sh snippets, transfer, collection and r2-presign over subprocess.

    Only the process boundary is a double: factory/batch_holder.py in the copied root runs the
    real batch_holder.main() with the gate constant, root, control home and verify patched, and
    an in-memory object store behind urlopen. The worker is a local directory behind boat-call.
    """
    locals().update({k: v for k, v in vars(HolderTests).items() if not k.startswith(('test_', '__'))})

    def setUp(self):
        HolderTests.setUp(self)
        for name in ('collect.sh', 'transfer.py', 'collection.py'):
            shutil.copy2(ROOT / 'factory' / name, self.root / 'factory' / name)
        (self.root / 'bin').mkdir(exist_ok=True)
        shutil.copy2(ROOT / 'bin/r2-presign', self.root / 'bin/r2-presign')
        self.remote = self.root / 'worker'; (self.remote / 'sealed').mkdir(parents=True)
        (self.root / 'bin/boat-call').write_text('#!/bin/sh\n[ "$1" = ssh ] || exit 1\n'
                                                 'HOME=' + shlex.quote(str(self.remote)) + ' exec /bin/sh -c "$3"\n')
        (self.root / 'bin/boat-call').chmod(0o755)
        self.home.mkdir(exist_ok=True); (self.home / 'policy.json').write_text(json.dumps(self.policy))
        (self.root / 'factory/batch_holder.py').write_text(
            'import io, json, os, sys, urllib.parse, urllib.request\nfrom pathlib import Path\n'
            'from unittest.mock import patch\n'
            'sys.path[:0] = [' + repr(str(ROOT / 'factory')) + ', ' + repr(str(ROOT / 'bin')) + ']\n'
            'import batch, batch_holder, key_holder\n'
            'root, home = Path(' + repr(str(self.root)) + '), Path(os.environ["UNBUG_CONTROL_HOME"])\n'
            'log = root / "object-store.jsonl"\n'
            'def urlopen(request, timeout):\n'
            '    url = request.full_url if isinstance(request, urllib.request.Request) else request\n'
            '    parts = urllib.parse.urlsplit(url); store = root / "objects" / parts.path.lstrip("/")\n'
            '    with log.open("a") as out: out.write(json.dumps([parts.hostname, parts.path]) + "\\n")\n'
            '    if isinstance(request, urllib.request.Request):\n'
            '        store.parent.mkdir(parents=True, exist_ok=True); store.write_bytes(request.data.read())\n'
            '        return io.BytesIO(b"")\n'
            '    return io.BytesIO(store.read_bytes())\n'
            'with patch.object(batch_holder, "HOLDER_ENABLED", True), patch.object(batch, "verify"), \\\n'
            '     patch.multiple(key_holder, ROOT=root, CONTROL_HOME=home, policy_load=lambda p: json.loads(p.read_text())), \\\n'
            '     patch.object(urllib.request, "urlopen", urlopen):\n'
            '    raise SystemExit(batch_holder.main())\n')
        self.r2 = dict(R2_ACCOUNT_ID='authored-account', R2_ACCESS_KEY_ID='authored-access',
                       R2_SECRET_ACCESS_KEY='authored-secret', R2_BUCKET='authored-bucket')

    def env(self, **values):
        clean = {k: v for k, v in os.environ.items() if not k.startswith(('R2_', 'UNBUG_'))}
        return {**clean, 'UNBUG_CONTROL_HOME': str(self.home), **values}

    def worker_output(self, op):
        self.output(op)
        collected = self.home / 'launches' / op['launch_id'] / 'collected'
        for path in collected.iterdir(): path.rename(self.remote / 'sealed' / path.name)
        collected.rmdir(); (self.remote / 'sealed/DONE').write_text(op['case'] + '\n')

    def collect_vm(self, op, *, state=None):
        """launch.sh's own collect_vm with its R2 environment, as guard_retire calls it."""
        launch = (ROOT / 'factory/launch.sh').read_text()
        function = launch[launch.index('collect_vm() {'):launch.index('factory_ttl_retire() {')]
        r2_env = ''.join(k + '=' + shlex.quote(v) + '\n' for k, v in self.r2.items())
        script = ('set -eu\nhere=' + shlex.quote(str(self.root / 'factory')) + '\nr2_env=' + shlex.quote(r2_env)
                  + '\n' + function + '\ncollect_vm ' + shlex.quote(op['worker_id']) + '\n')
        state = state or self.home / 'launches' / op['launch_id']
        return subprocess.run(['/bin/sh', '-c', script], capture_output=True, text=True, timeout=120,
                              env=self.env(UNBUG_BATCH_OPERATION=op['operation_id'], UNBUG_LAUNCH_STATE=str(state)))

    def test_collect_sh_publishes_through_holder_and_r2_presign(self):
        op = self.started(self.reserve()); self.worker_output(op)
        result = self.collect_vm(op)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('publication refused', result.stderr)
        ack = self.money()['jobs']['j']['acks'][self.ops()[op['operation_id']]['output_generation']]
        self.assertEqual(json.loads((self.directory / 'current' / (op['case'] + '.json')).read_text())['generation'],
                         ack['generation'])
        calls = [json.loads(line) for line in (self.root / 'object-store.jsonl').read_text().splitlines()]
        # The launcher's R2 environment reached bin/r2-presign: real signed URLs name its account and bucket.
        self.assertEqual({host for host, _ in calls}, {'authored-account.r2.cloudflarestorage.com'})
        prefix = '/authored-bucket/generations/' + op['case'] + '/' + ack['generation'] + '/'
        self.assertTrue(calls and all(path.startswith(prefix) for _, path in calls))
        self.assertNotIn(b'authored-secret', b''.join(p.read_bytes() for p in self.home.rglob('*') if p.is_file()))

    def test_collect_sh_refused_publication_keeps_collection_status(self):
        op = self.started(self.reserve()); self.worker_output(op)
        elsewhere = self.root / 'other-state'; elsewhere.mkdir()
        result = self.collect_vm(op, state=elsewhere)
        # Collection integrity passed, so guard_retire may delete; publication is reported apart.
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('holder publication refused', result.stderr)
        self.assertEqual(self.money()['jobs']['j']['acks'], {})
        self.assertTrue((elsewhere / 'collected' / (op['case'] + '.scorecard.json')).exists())

    def test_launch_sh_batch_restore_reads_only_the_frozen_source(self):
        op = self.started(self.reserve()); card = self.output(op); self.publish(op)
        self.retirement(op); self.reconcile()
        successor = self.reserve(source=card['sha256'])
        identity = subprocess.run(['age-keygen'], capture_output=True, text=True, check=True).stdout
        identity = next(line for line in identity.splitlines() if line.startswith('AGE-SECRET-KEY-'))
        public = subprocess.run(['age-keygen', '-y'], input=identity + '\n', capture_output=True, text=True,
                                check=True).stdout.strip()
        self.policy['recipient'] = public; (self.home / 'policy.json').write_text(json.dumps(self.policy))
        launch = (ROOT / 'factory/launch.sh').read_text()
        start = launch.index('  founder_recipient=$(sed')
        end = launch.index('    casekey=$root/sealed/$restore.casekey.age\n  fi\n') + len('    casekey=$root/sealed/$restore.casekey.age\n  fi\n')
        def run(operation, key):
            script = ('set -eu\nhere=' + shlex.quote(str(self.root / 'factory')) + '\nroot=' + shlex.quote(str(self.root))
                      + '\nn=1\ncontinue_review=no\nrestore=' + op['case'] + '\nidentity=' + shlex.quote(key) + '\n'
                      + launch[start:end] + 'printf "%s\\n" "$card" "$ckpt" "$casekey"\n')
            (self.root / 'factory/run.py').write_text('FOUNDER_RECIPIENT = "age1unused"\n')
            return subprocess.run(['/bin/sh', '-c', script], capture_output=True, text=True, timeout=60,
                                  env=self.env(UNBUG_BATCH_OPERATION=operation))
        result = run(successor['operation_id'], identity)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = self.directory / 'generations' / op['case'] / card['sha256']
        self.assertEqual(result.stdout.split(), [str(source / (op['case'] + '.scorecard.json')),
                         str(source / card['archive']), str(source / (op['case'] + '.casekey.age'))])
        self.assertTrue(all(Path(path).is_file() for path in result.stdout.split()))
        # A key that is neither the founder's nor the scoped restore key, and an operation without a source, refuse.
        other = subprocess.run(['age-keygen'], capture_output=True, text=True, check=True).stdout
        other = next(line for line in other.splitlines() if line.startswith('AGE-SECRET-KEY-'))
        self.assertNotEqual(run(successor['operation_id'], other).returncode, 0)
        self.assertNotEqual(run(op['operation_id'], identity).returncode, 0)

if __name__ == '__main__': unittest.main()
