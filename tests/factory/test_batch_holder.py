"""Offline integration: retained card/ciphertext/created event, authored bindings.

Uses the real collection verifier and D APIs. Ciphertext is the retained opaque
transport envelope from test_batch_service, not a generated case archive.
Deletion/config/operation fields are authored; no live proof or Murphy closure.
"""
from copy import deepcopy
import fcntl
import io
import json
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
        self.reconcile()
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

    def test_dispatch_creator_intent_is_durable_and_never_repeated(self):
        import key_holder
        import account_handoff
        op = self.reserve(); self.policy.update(code_sha256='fingerprint', path='/usr/bin:/bin', recipient='founder-public')
        calls = []
        def run(argv, **kwargs):
            data = (self.record['restore_recipient'].encode() if argv[0] == 'age-keygen' else
                    json.dumps(dict(sandboxes=[], pageInfo=dict(hasMore=False))).encode())
            return SimpleNamespace(stdout=data)
        def popen(argv, **kwargs):
            self.assertTrue(self.ops()[op['operation_id']]['dispatch_started'])
            calls.append(argv)
            return SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 0)
        with ExitStack() as stack:
            stack.enter_context(patch.object(key_holder, 'fingerprint', return_value='fingerprint'))
            stack.enter_context(patch.object(key_holder, 'secret_labels', return_value={'claude-token'}))
            stack.enter_context(patch.object(account_handoff, 'launch_accounts', return_value=(None, 1, {})))
            stack.enter_context(patch.object(holder.subprocess, 'run', side_effect=run))
            stack.enter_context(patch.object(holder.subprocess, 'Popen', side_effect=popen))
            holder.dispatch(self.policy, self.root, self.home, op['operation_id'], b'authored test identity')
            holder.dispatch(self.policy, self.root, self.home, op['operation_id'], b'authored test identity')
        self.assertEqual(len(calls), 1)
        self.assertNotIn(b'authored test identity', (self.directory / 'reservations.json').read_bytes())

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


if __name__ == '__main__': unittest.main()
