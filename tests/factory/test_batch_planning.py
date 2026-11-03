"""Offline production-caller contract: saved transport/card, authored bindings.

HolderTests supplies retained ciphertext and a saved card/creation event.
Deletion proofs, batch bindings and diagnosis API answers are authored controls.
This proves authentication/queue wiring, not live diagnosis or Murphy closure.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import batch_holder as holder
import batch_money as money
import batch_service as service
import key_holder
import test_batch_holder as holder_fixtures
from registry import atomic_json


class PlanningTests(unittest.TestCase):
    locals().update({k: v for k, v in vars(holder_fixtures.HolderTests).items()
                     if not k.startswith(('test_', '__'))})

    def setUp(self):
        holder_fixtures.HolderTests.setUp(self)
        self.record['replacement_policy']['enabled'] = False
        self.freeze()
        retry = patch.dict(holder._PLAN_RETRY_AFTER, {}, clear=True)
        retry.start(); self.addCleanup(retry.stop)
        # Labelled contract API double; no claim about this card's real eligibility.
        self.api = self.answers(pending=dict(schema_version=1, status='pending',
                                            replacement_eligible=False))

    def ready(self, job='j', *, publish=True, retire=True):
        op = self.started(self.reserve(job))
        card = self.output(op)
        if publish: self.publish(op)
        if retire: self.retirement(op); self.reconcile()
        return self.ops()[op['operation_id']], card

    def scan(self):
        with patch.dict(sys.modules, diagnosis=self.api):
            return holder.plan_collections(self.policy, self.root, self.home)

    def tick(self):
        spawned = []
        with patch.multiple(key_holder, ROOT=self.root, CONTROL_HOME=self.home), \
             patch.dict(sys.modules, diagnosis=self.api), \
             patch.object(holder, 'drain_resumes', return_value=[]), \
             patch.object(holder, 'reserve') as reserve, \
             patch.object(holder, 'dispatch') as dispatch:
            key_holder.batch_tick(self.policy, {}, {},
                                  lambda op, action: spawned.append((op, action)) or op)
        self.assertEqual(spawned, [])
        reserve.assert_not_called()
        dispatch.assert_not_called()

    def state(self): return service._load(self.directory, self.record, self.policy['batch']['manifest_sha256'])

    def protected(self):
        return {str(p.relative_to(self.directory)): p.read_bytes()
                for p in [self.directory / 'money.json', self.directory / 'reservations.json',
                          *(self.directory / 'configs').glob('*.json')]}

    def assert_unplanned(self):
        self.assertEqual(self.state()['queue'], {})
        self.assertTrue(all(e['facts'] is None for e in self.state()['entries'].values()))

    def test_tick_plans_once_without_reservation_or_money_mutation(self):
        op, card = self.ready()
        before = self.protected()
        with patch.object(service, '_snapshot', wraps=service._snapshot) as snapshot:
            self.tick()
            self.assertEqual(snapshot.call_count, 1)
            committed = (self.directory / 'journal.json').read_bytes()
            self.tick()
            # Restart loses delay state, not the durable facts/queue identity.
            holder._PLAN_RETRY_AFTER.clear()
            self.tick()
            self.assertEqual(snapshot.call_count, 1)
        state = self.state()
        key = 'resume/' + card['case'] + '/' + card['sha256']
        self.assertEqual(set(state['queue']), {key})
        self.assertEqual(state['queue'][key]['reason'], 'exhaustion')
        self.assertEqual(state['next_sequence'], 1)
        self.assertEqual(state['derivations'], {})
        self.assertEqual((self.directory / 'journal.json').read_bytes(), committed)
        self.assertEqual(self.protected(), before)

    def test_disabled_or_absent_policy_does_not_read_operations(self):
        for policy in (None, dict(schema=1, enabled=False)):
            with self.subTest(policy=policy):
                self.setUp()
                if policy is None: self.record.pop('diagnosis_policy')
                else: self.record['diagnosis_policy'] = policy
                self.freeze()
                with patch.object(holder, '_operations', side_effect=AssertionError('off')), \
                     patch.object(service, 'plan', side_effect=AssertionError('off')):
                    self.assertEqual(self.scan(), [])
        with patch.object(holder, 'HOLDER_ENABLED', False), self.assertRaises(ValueError):
            self.scan()

    def test_each_publication_and_retirement_proof_is_required(self):
        for fault in ('ack', 'retirement', 'outbox', 'pointer', 'stale_pointer',
                      'authority', 'config', 'snapshot'):
            with self.subTest(fault=fault):
                self.setUp()
                op, card = self.ready()
                state = self.money()
                if fault == 'ack':
                    del state['jobs']['j']['acks'][card['sha256']]
                    atomic_json(self.directory / 'money.json', state)
                elif fault == 'retirement':
                    ops = self.ops(); ops[op['operation_id']]['retirement'] = None
                    holder._save(self.directory, self.record, self.policy, ops)
                elif fault in ('outbox', 'pointer', 'stale_pointer'):
                    path = (self.directory / 'outbox' / (op['operation_id'] + '.json')
                            if fault == 'outbox' else self.directory / 'current' / (op['case'] + '.json'))
                    if fault == 'stale_pointer':
                        value = service._json(path); value['generation'] = 'b' * 64
                        atomic_json(path, value)
                    else: path.unlink()
                elif fault == 'authority':
                    state['jobs']['j']['authority']['revision'] += 1
                    atomic_json(self.directory / 'money.json', state)
                elif fault == 'config':
                    (self.directory / 'configs' / (op['config_sha256'] + '.json')).write_text('{}')
                else:
                    (self.directory / 'generations' / op['case'] / card['sha256'] /
                     (op['case'] + '.statement.age')).write_bytes(b'tampered')
                before = self.protected()
                journal = (self.directory / 'journal.json').read_bytes()
                with patch.object(service, '_project', side_effect=AssertionError('untrusted')):
                    self.scan()
                self.assert_unplanned()
                self.assertEqual((self.directory / 'journal.json').read_bytes(), journal)
                self.assertEqual(self.protected(), before)

    def test_money_export_and_consumed_source_refuse(self):
        for fault in ('incident', 'overrun', 'aggregate', 'deadline', 'export', 'successor'):
            with self.subTest(fault=fault):
                self.setUp()
                op, card = self.ready()
                state = self.money()
                if fault == 'incident':
                    state['incidents'][op['operation_id'] + '/' + card['sha256']] = dict(
                        operation_id=op['operation_id'], generation=card['sha256'],
                        manifest_sha256=self.state()['entries'][op['case'] + '/' + card['sha256']]['manifest_sha256'],
                        reason='invalid_accounting_input')
                    atomic_json(self.directory / 'money.json', state)
                elif fault == 'overrun':
                    # Valid accounting shape: retained ACK total raises the known floor.
                    state['jobs']['j']['acks'][card['sha256']]['facts']['total_usd'] = '1001.000000000'
                    state['jobs']['j'].update(known_floor_usd='1001.000000000', overrun=True)
                    atomic_json(self.directory / 'money.json', state)
                elif fault == 'export': (self.directory / 'export.json').write_text('{}')
                elif fault == 'successor': self.reserve(source=card['sha256'])
                before = self.protected()
                journal = (self.directory / 'journal.json').read_bytes()
                with patch.object(service, '_snapshot', side_effect=AssertionError('cheap refusal')):
                    if fault == 'aggregate':
                        with patch.object(money, 'aggregate', return_value=money.amount('3001.000000000')):
                            self.scan()  # Authored over-bound accounting control.
                    elif fault == 'deadline':
                        from datetime import datetime
                        with patch.object(holder, 'datetime', wraps=datetime) as clock:
                            clock.now.return_value = datetime.fromisoformat('2100-01-01T00:00:00+00:00')
                            self.scan()
                    elif fault == 'export':
                        with self.assertRaises(money.MoneyWait): self.scan()
                    else: self.scan()
                self.assert_unplanned()
                self.assertEqual((self.directory / 'journal.json').read_bytes(), journal)
                self.assertEqual(self.protected(), before)

    def test_selection_is_reauthenticated_inside_plan_lock(self):
        op, card = self.ready()
        original = service.plan
        def stale(*args, **kwargs):
            path = self.directory / 'current' / (op['case'] + '.json')
            value = service._json(path); value['generation'] = 'b' * 64
            atomic_json(path, value)
            self.assertEqual(kwargs['published_operation'], op['operation_id'])
            return original(*args, **kwargs)
        with patch.object(service, 'plan', side_effect=stale):
            self.scan()
        self.assert_unplanned()

    def test_legacy_retirement_is_not_rehashed(self):
        op = self.started(self.reserve())
        card = self.output(op); card.pop('diagnosis_state')
        incoming = self.home / 'launches' / op['launch_id'] / 'collected' / (op['case'] + '.scorecard.json')
        incoming.write_text(json.dumps(card))
        self.publish(op); self.retirement(op); self.reconcile()
        with patch.object(service, '_snapshot', wraps=service._snapshot) as snapshot:
            self.tick(); self.tick(); self.tick()
            self.assertEqual(snapshot.call_count, 1)
        self.assertTrue((self.directory / 'retirements' / op['case'] / (card['sha256'] + '.json')).exists())
        self.assert_unplanned()

    def test_refusal_backoff_is_bounded_and_not_an_auth_cache(self):
        op, card = self.ready()
        with patch.object(holder.time, 'monotonic', return_value=10) as clock, \
             patch.object(service, '_snapshot', wraps=service._snapshot) as snapshot, \
             patch.object(service, '_project', side_effect=ValueError('authored projection refusal')):
            self.tick(); self.tick()
            self.assertEqual(snapshot.call_count, 1)
            clock.return_value = 69
            self.tick(); self.assertEqual(snapshot.call_count, 1)
            clock.return_value = 70
            self.tick(); self.assertEqual(snapshot.call_count, 2)
        self.assert_unplanned()
        holder._PLAN_RETRY_AFTER.clear()  # Process restart retries safely.
        self.scan()
        self.assertEqual(len(self.state()['queue']), 1)

    def test_bad_candidate_does_not_block_peer(self):
        bad, _ = self.ready('j')
        good, card = self.ready('k')
        (self.directory / 'current' / (bad['case'] + '.json')).unlink()
        self.scan()
        self.assertEqual(set(self.state()['queue']),
                         {'resume/' + good['case'] + '/' + card['sha256']})

    def test_before_commit_and_lost_reply_replay(self):
        for point in ('before', 'after'):
            with self.subTest(point=point):
                self.setUp()
                op, card = self.ready()
                original = service.atomic_json
                def crash(path, value):
                    if path.name == 'journal.json':
                        if point == 'after': original(path, value)
                        raise OSError('authored commit interruption')
                    return original(path, value)
                with patch.object(service, 'atomic_json', side_effect=crash):
                    self.scan()
                self.assertEqual(len(self.state()['queue']), int(point == 'after'))
                holder._PLAN_RETRY_AFTER.clear()
                self.scan(); self.scan()
                self.assertEqual(self.state()['next_sequence'], 1)

    def test_late_publication_and_retirement_become_eligible(self):
        op, card = self.ready(publish=False, retire=False)
        self.scan(); self.assert_unplanned()
        self.publish(op)
        self.scan(); self.assert_unplanned()
        self.retirement(op); self.reconcile()
        self.scan()
        self.assertEqual(len(self.state()['queue']), 1)

    def test_lock_depth_never_exceeds_one(self):
        op, card = self.ready()
        original = money.locked
        depth, maximum = 0, 0
        @contextmanager
        def single(*args, **kwargs):
            nonlocal depth, maximum
            depth += 1
            self.assertEqual(depth, 1, 'nested money lock would deadlock')
            maximum = max(maximum, depth)
            try:
                with original(*args, **kwargs) as directory:
                    yield directory
            finally: depth -= 1
        with patch.object(money, 'locked', side_effect=single), patch.dict(sys.modules, diagnosis=self.api):
            self.scan()
            self.assertEqual(len(self.state()['queue']), 1)
            service.plan(self.policy, self.root, self.home, card['case'], card['sha256'],
                         published_operation=op['operation_id'])
        self.assertEqual(maximum, 1)


if __name__ == '__main__':
    unittest.main()

