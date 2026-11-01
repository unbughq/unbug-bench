"""Retained ledgers/cards/ciphertext, authored lifecycle bindings; no live proof.

Queued-child money-only state is authored: production creation of that state is
an open carry-over gap. These tests do not close Murphy rows.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'tests/factory')]
import batch_holder as holder
import batch_money as money
import batch_service as service
import batch_transfer as transfer
import test_batch_transfer as fixtures
import test_batch_accounting as accounting
from registry import atomic_json

spec = importlib.util.spec_from_file_location('qualify_clamps', ROOT / 'tools/qualify-batch-inputs.py')
qualifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualifier)


def usd(n): return f'{n // 10**9}.{n % 10**9:09d}'
def allocation(e, s='0.000000000'): return dict(baseline_usd=s, incremental_usd=e)
def files(root): return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.TransferTests('test_saved_card_launch_keeps_spend_owner_lineage_and_freezes_source')
        self.h.setUp(); self.addCleanup(self.h.doCleanups)

    def practice(self, child=True):
        h = self.h
        h.record['practice_admission'] = dict(schema=1, jobs={
            'j': allocation('1000.000000000'), 'k': allocation('1000.000000000')})
        if child: h.record['practice_admission']['jobs']['j-r1'] = allocation('7.500000000')
        h.freeze()

    def target(self, selections, name='fixed'):
        h = self.h
        record, policy = h.target(selections, name=name)
        # Every release retains all templates, even when its import subset shrinks.
        for key, value in h.record['jobs'].items():
            if key not in record['jobs']:
                record['jobs'][key] = {**deepcopy(value), 'case': 'case-' + name + '-' + key}
        h.pin_target(record, policy)
        return record, policy

    def check_refusal(self, record, policy, job, source=None):
        h = self.h
        before = files(h.home)
        self.assertFalse(qualifier.qualify(policy, h.root, h.home, job, source)['eligible'])
        self.assertEqual(files(h.home), before)
        with self.assertRaises(ValueError): holder.reserve(policy, h.root, h.home, job, source)
        self.assertEqual(files(h.home), before)

    def test_twenty_dollar_template_is_not_child_authority(self):
        self.practice(); h = self.h
        h.record['jobs']['j']['requested_total_usd'] = '20.000000000'
        state = dict(jobs={}, incidents={})
        child = money.authorize_locked(state, h.record, 'j-r1', None)
        self.assertEqual(child['committed_total_usd'], '7.500000000')
        self.assertEqual(money.authorize_locked(state, h.record, 'j-r1', None), child)
        self.assertEqual(len(state['jobs']), 1)
        with self.assertRaises(ValueError): money.channel({**child, 'committed_total_usd': '20.000000000'}, h.record, 'j-r1')
        with self.assertRaises(ValueError): money.authorize_locked(state, h.record, 'j-r2', None)
        # No optional schema: production generations still inherit their template.
        del h.record['practice_admission']
        self.assertEqual(money.authorize_locked(dict(jobs={}, incidents={}), h.record, 'j-r2', None)
                         ['committed_total_usd'], '20.000000000')

    def test_production_oversized_template_refuses_without_partial_grant(self):
        h = self.h
        h.record['jobs']['j']['requested_total_usd'] = '5000.000000000'
        h.freeze()
        state = dict(jobs={}, incidents={})
        with self.assertRaises(money.MoneyWait):
            money.authorize_locked(state, h.record, 'j', None)
        self.assertEqual(state, dict(jobs={}, incidents={}))
        with money.locked(h.home, h.record['id']): pass
        self.check_refusal(h.record, h.policy, 'j')

    def test_manifest_rejects_malformed_or_unfunded_allocations(self):
        self.practice(); h = self.h
        good = deepcopy(h.record)
        changes = [lambda p: p.update(schema=True), lambda p: p.update(extra=0),
                   lambda p: p['jobs'].pop('j'), lambda p: p['jobs'].update({'j-r2': allocation('1.000000000')}),
                   lambda p: p['jobs']['j'].update(baseline_usd='1.000000000'),
                   lambda p: p['jobs']['j'].update(incremental_usd='0.000000000'),
                   lambda p: p['jobs']['j'].update(incremental_usd=True),
                   lambda p: p['jobs']['j'].update(incremental_usd='NaN'),
                   lambda p: p['jobs']['j'].update(incremental_usd='10000.000000000'),
                   lambda p: p['jobs']['j-r1'].update(baseline_usd='1.000000000')]
        for change in changes:
            bad = deepcopy(good); change(bad['practice_admission'])
            with self.subTest(record=bad['practice_admission']), self.assertRaises(ValueError): money.check_manifest(bad)
        h.record['replacement_policy']['enabled'] = False
        with self.assertRaises(ValueError): money.check_manifest(h.record)

    def test_legacy_api_refuses_practice(self):
        self.practice(); h = self.h
        with self.assertRaises(ValueError): money.authorize(h.policy, 'j', None, h.root, h.home)
        self.assertFalse(h.home.exists())

    def test_holder_replacement_replay_and_unlisted_next_generation(self):
        self.practice(); h = self.h
        card = h.stopped()
        # Plan a replacement, then let the real holder create its money row.
        with patch.object(service, 'DIAGNOSIS_ENABLED', True), patch.dict(sys.modules,
                diagnosis=h.answers(pending=dict(schema_version=1, status='pending', replacement_eligible=True))):
            service.plan(h.policy, h.root, h.home, card['case'], card['sha256'])
        self.assertNotIn('j-r1', h.money()['jobs'])
        op = h.reserve('j-r1')
        self.assertEqual(op['authority']['committed_total_usd'], '7.500000000')
        self.assertEqual(h.reserve('j-r1'), op)
        self.assertEqual(len(h.ops()), 2)
        # Use a real saved child ledger and D queue projection, not a fake ordinal.
        op = h.started(op); child = h.output(op)
        h.publish(op); h.retirement(op); h.reconcile()
        with money.locked(h.home, h.record['id']):
            journal = service._load(h.directory, h.record, h.policy['batch']['manifest_sha256'])
            entry = journal['entries'][child['case'] + '/' + child['sha256']]
            entry['facts'] = dict(exhaustion=True, actual_model_work=True, pending_projection=dict(
                schema_version=1, status='pending', replacement_eligible=True))
            service._enqueue(journal, h.record, entry, child)
            atomic_json(h.directory / 'journal.json', journal)
        self.assertIn('j-r2', [r['job'] for r in journal['queue'].values()])
        self.check_refusal(h.record, h.policy, 'j-r2')

    def test_exact_cumulative_cap_and_one_nanodollar_over_with_carried_debit(self):
        h = self.h
        # Isolate admission arithmetic on supplied memory; no fabricated import proof.
        h.record['money_limit_usd'] = '1000.000000001'; h.freeze()
        directory = h.home / 'batches/practice'
        for debit, allowed in [('0.000000001', True), ('0.000000002', False)]:
            state = dict(jobs={}, incidents={}, carried_debit_usd=debit)
            if allowed:
                auth = holder._admit(directory, h.record, h.policy, h.root, {}, state, 'j', None)
                self.assertEqual(money.aggregate(state), money.amount(h.record['money_limit_usd']))
                self.assertEqual(auth['committed_total_usd'], '1000.000000000')
            else:
                before = deepcopy(state)
                with self.assertRaises(ValueError): holder._admit(directory, h.record, h.policy, h.root, {}, state, 'j', None)
                self.assertEqual(state, before)

    def test_saved_ledger_overrun_refuses_replay_and_new_admission(self):
        h = self.h
        h.record['money_limit_usd'] = '1500.000000000'; h.freeze()
        op = h.started(h.reserve())
        ledger = deepcopy(next(r['card']['continuation_budget'] for r in accounting.d.cards()
                               if r['card']['case'].endswith('e15450')))
        ledger['events'].append(dict(id='authored-overrun', cost=1500, calls=1))
        ledger['cost'] += 1500; ledger['calls'] += 1
        h.output(op, ledger=ledger); h.publish(op)
        self.assertGreater(money.aggregate(h.money()), money.amount(h.record['money_limit_usd']))
        self.check_refusal(h.record, h.policy, 'j')
        h.retirement(op); h.reconcile()
        self.check_refusal(h.record, h.policy, 'k')

    def test_first_entry_authenticates_baseline_and_keeps_authority(self):
        h = self.h; card = h.stopped()
        s = h.money()['jobs']['j']['previous']['total_usd']
        self.assertEqual(h.money()['jobs']['j']['previous']['estimated'], {})
        for label in ('mismatch', 'too-small', 'good'):
            record, policy = self.target({'j': card['sha256']}, name=label)
            record['practice_admission'] = dict(schema=1, jobs={
                'j': allocation(usd(money.amount('1000.000000000') - money.amount(s)), s),
                'k': allocation('1000.000000000'), 'j-r1': allocation('7.500000000')})
            if label == 'mismatch':
                # Cap stays above held: only authenticated baseline equality can refuse.
                record['practice_admission']['jobs']['j']['baseline_usd'] = usd(money.amount(s) + 10**9)
            if label == 'too-small': record['practice_admission']['jobs']['j']['incremental_usd'] = '7.500000000'
            h.pin_target(record, policy)
            if label != 'good':
                with self.assertRaises(ValueError): transfer.prepare(policy, h.root, h.home)
                self.assertFalse((h.directory / 'export.json').exists())
            else:
                op = holder.reserve(policy, h.root, h.home, 'j', card['sha256'])
                self.assertEqual(op['authority']['committed_total_usd'], '1000.000000000')
                state = h.target_state(record, policy)
                self.assertEqual(state['jobs']['j']['previous']['total_usd'], s)
                # Persisted import reads apply the same baseline contract.
                bad = deepcopy(record); bad['practice_admission']['jobs']['j']['baseline_usd'] = usd(money.amount(s) + 10**9)
                with self.assertRaises(ValueError): transfer.read_import(h.home / 'batches/good', bad)

    def test_two_releases_retain_omitted_history_and_do_not_regrant(self):
        self.practice(); h = self.h
        # Re-admitting k fits the aggregate cap; only historical ownership refuses.
        h.record['money_limit_usd'] = '9000.000000000'; h.freeze()
        card = h.stopped(); h.stopped('k'); h.derive(card)
        total = money.aggregate(h.money())
        record, policy = self.target({'j': card['sha256'], 'j-r1': None})
        for kind in ('removed', 'increased'):
            bad = deepcopy(record)
            if kind == 'removed': bad.pop('practice_admission')
            else: bad['practice_admission']['jobs']['j']['incremental_usd'] = '1001.000000000'
            h.pin_target(bad, policy)
            with self.assertRaises(ValueError): transfer.prepare(policy, h.root, h.home)
            self.assertFalse((h.directory / 'export.json').exists())
        h.pin_target(record, policy)
        transfer.prepare(policy, h.root, h.home)
        h.use_target(record, policy)
        self.assertEqual(money.aggregate(h.money()), total)
        self.assertEqual(h.money()['carried_debit_usd'], '1000.000000000')
        self.assertLess(total + money.amount(record['jobs']['k']['requested_total_usd']),
                        money.amount(record['money_limit_usd']))
        self.check_refusal(record, policy, 'k')
        op = h.started(h.reserve(source=card['sha256']))
        payload = (ROOT / 'sealed/case-20261017T212118Z-1ad7fa.casekey.age').read_bytes()
        successor = h.output(op, payload=payload)
        h.publish(op); h.retirement(op); h.reconcile()
        second, second_policy = self.target({'j': successor['sha256'], 'j-r1': None}, name='fixed-again')
        transfer.prepare(second_policy, h.root, h.home)
        state = h.target_state(second, second_policy)
        self.assertEqual(money.aggregate(state), total)
        self.assertEqual(state['carried_debit_usd'], '1000.000000000')
        self.check_refusal(second, second_policy, 'k')
        child = holder.reserve(second_policy, h.root, h.home, 'j-r1', None)
        self.assertEqual(child['authority']['committed_total_usd'], '7.500000000')
        self.assertEqual(child, holder.reserve(second_policy, h.root, h.home, 'j-r1', None))
        self.assertEqual(money.aggregate(h.target_state(second, second_policy)), total)


if __name__ == '__main__': unittest.main()
