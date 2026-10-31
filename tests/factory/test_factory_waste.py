"""Saved public practice ledger, actual monetary APIs; authored failure controls."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'factory'), str(ROOT/'bin'), str(ROOT/'tests/factory')]
import budget
import diagnosis
import factory_waste as waste
from run_validity import InvalidInfra
import test_stream_d as saved


class WasteTests(unittest.TestCase):
    setUp = saved.AccountingTests.setUp
    ledger = saved.AccountingTests.ledger
    reserve = saved.AccountingTests.reserve
    receipt = saved.AccountingTests.receipt
    wait = saved.AccountingTests.wait

    def context(self):
        channel = asdict(saved.authority()); channel['schema'] = 1
        channel['committed_total_usd'] = format(channel['committed_total_usd'], '.9f')
        return SimpleNamespace(work=self.work, ledger=self.path, case_id=channel['case'],
            batch_id=channel['batch'], job_id=channel['job'], source_generation=None,
            batch_deadline=channel['batch_deadline'], job_money=channel,
            authenticated_job_config={'job_money': copy.deepcopy(channel), 'batch_release_sha256':'a'*64},
            args=SimpleNamespace(batch_release_sha256='a'*64), card=copy.deepcopy(self.card))

    def failure(self, c, amount=1, *, final=True):
        with self.assertRaises(InvalidInfra):
            with waste.attempt(c, 'G8', 'b'*64):
                lease, row = self.reserve()
                waste.record_reservation(c, row)
                self.receipt(lease, [('authored-'+lease.lease_id, amount)], final=final)
                budget.settle(self.wait(lease, 'usage-receipts/'+lease.lease_id+'.json'),
                              work=self.work, ledger_path=self.path)
                raise InvalidInfra('authored factory failure')
        return row

    def freeze(self, c, identity=None):
        identity = identity or str(uuid.uuid4())
        root = self.work/'diagnosis'/identity/'inputs'; (root/'work').mkdir(parents=True)
        (root/'ledger.json').write_bytes(self.path.read_bytes())
        (root/'work/job-money.json').write_text(json.dumps(c.job_money))
        (root/'card.json').write_text(json.dumps({'diagnosis_state': {'exhaustion_id': identity}, 'batch_release_sha256':'a'*64}))
        import shutil
        shutil.copytree(self.work/'factory-failures', root/'work/factory-failures')
        operations, references = waste.eligible(root, c.case_id, identity)
        finding = dict(finding_id=identity, eligible_operation_ids=operations, failure_receipts=references,
                       diagnosis={'authored': 'control'})
        return finding, root

    def test_hold_moves_saved_ledger_spend_without_refunding_total_and_replays_once(self):
        c = self.context(); self.failure(c)
        finding, root = self.freeze(c)
        before = budget.case_spending(self.ledger())
        for _ in range(2): waste.classify(c, finding)
        after = budget.case_spending(self.ledger())
        self.assertEqual(before['total_spent_usd'], after['total_spent_usd'])
        self.assertEqual(after['spent_usd'], before['spent_usd']-1)
        self.assertEqual(len(self.ledger()['infrastructure_waste']), 1)
        self.assertEqual(waste.eligible(root, c.case_id, finding['finding_id']),
                         (finding['eligible_operation_ids'], finding['failure_receipts']))
        record = self.ledger()['infrastructure_waste'][0]
        self.assertEqual(record['infrastructure_waste_usd'], '1.000000000')
        self.assertIsNone(record['resume_id'])

    def test_second_same_batch_hold_excludes_owned_operations_and_can_be_empty(self):
        c = self.context(); first = self.failure(c)
        one, _ = self.freeze(c); waste.classify(c, one)
        empty, _ = self.freeze(c); self.assertEqual(empty['eligible_operation_ids'], [])
        waste.classify(c, empty)
        second = self.failure(c, 2)
        two, _ = self.freeze(c); waste.classify(c, two)
        self.assertEqual(two['eligible_operation_ids'], [second['operation_id']])
        records = self.ledger()['infrastructure_waste']
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['operation_ids'], [first['operation_id']])
        self.assertEqual(budget.case_spending(self.ledger())['infrastructure_waste_usd'], 3)

    def test_frozen_identity_live_late_settlement_does_not_rewrite_finding(self):
        c = self.context(); row = self.failure(c, final=False)
        finding, root = self.freeze(c); frozen = (root/'ledger.json').read_bytes()
        waste.classify(c, finding)
        self.assertEqual(self.ledger().get('infrastructure_waste', []), [])
        lease = SimpleNamespace(lease_id=row['lease_id'])
        call = self.receipt(lease, [('final-authored', 2)], final=True)
        budget.settle(self.wait(lease, call), work=self.work, ledger_path=self.path)
        waste.classify(c, finding)
        self.assertEqual((root/'ledger.json').read_bytes(), frozen)
        self.assertEqual(self.ledger()['infrastructure_waste'][0]['infrastructure_waste_usd'], '3.000000000')

    def test_v2_growth_resume_pair_and_late_string_refresh(self):
        c = self.context(); row = self.failure(c, .1234567894)
        finding, _ = self.freeze(c); waste.classify(c, finding)
        record = self.ledger()['infrastructure_waste'][0]
        record.update(resume_id=str(uuid.uuid4()), resume_binding_sha256='c'*64)
        budget.reclassify_factory_bug(self.path, record)
        self.failure(c, 2)
        ledger = self.ledger(); all_rows = ledger['invocation_reservations'].values()
        record.update(operation_ids=sorted({r['operation_id'] for r in all_rows}),
            event_ids=sorted({i for r in all_rows for i in r['event_ids']}))
        events = {e['id']:e for e in ledger['events']}
        # Keep the saved ledger's genuine historical events ordinary.
        record['infrastructure_waste_usd'] = format(budget.usd(budget._waste_amount(events, record['event_ids'])), '.9f')
        budget.reclassify_factory_bug(self.path, record)
        self.assertEqual(len(self.ledger()['infrastructure_waste']), 1)
        bad = {**record, 'resume_id':str(uuid.uuid4())}
        with self.assertRaisesRegex(budget.BudgetError, 'waste_attribution_mismatch'):
            budget.reclassify_factory_bug(self.path, bad)
        lease = SimpleNamespace(lease_id=row['lease_id'])
        values = [('authored-'+row['lease_id'], .1234567894), ('late-authored', .0000000004)]
        budget.settle(self.wait(lease, self.receipt(lease, values, final=True)), work=self.work, ledger_path=self.path)
        self.assertIsInstance(self.ledger()['infrastructure_waste'][0]['infrastructure_waste_usd'], str)
        self.assertIsNotNone(budget.case_spending(self.ledger())['total_spent_usd'])

    def test_replay_failure_emits_only_replay_proof(self):
        c = self.context(); self.failure(c)
        finding, _ = self.freeze(c)
        attempt_id = json.loads(next((self.work/'factory-failures').glob('*.json')).read_text())['attempt_id']
        link = dict(finding=finding, admission={'resume_id':str(uuid.uuid4())}, attempt_ids=[attempt_id])
        before = len(list((self.work/'factory-failures').glob('*.json')))
        with patch.object(waste, 'resume_scope', return_value=link), patch.object(waste, 'classify') as classify:
            self.failure(c)
        self.assertEqual(len(list((self.work/'factory-failures').glob('*.json'))), before)
        self.assertEqual(len(list((self.work/'factory-replays').glob('*.json'))), 1)
        classify.assert_called_once_with(c, finding, link['admission'])

    def test_tampered_owner_reservation_and_unsafe_proofs_refuse(self):
        c = self.context(); self.failure(c); finding, root = self.freeze(c)
        proof = root/finding['failure_receipts'][0]['path']; original = proof.read_bytes()
        for mutation in ('owner', 'parent'):
            value = json.loads(original)
            if mutation == 'owner': value['money_owner']['batch'] = 'foreign'
            else: value['reservations'][0]['parent_call_name'] = 'foreign'
            proof.write_text(json.dumps(value))
            with self.assertRaises((ValueError, budget.BudgetError)): waste.eligible(root, c.case_id, finding['finding_id'])
        proof.unlink(); proof.symlink_to(self.path)
        with self.assertRaises(ValueError): waste.eligible(root, c.case_id, finding['finding_id'])

    def test_zero_cost_settled_operation_accepts_empty_event_union(self):
        c = self.context()
        with self.assertRaises(InvalidInfra):
            with waste.attempt(c, 'G8', 'b'*64):
                lease, row = self.reserve()
                waste.record_reservation(c, row)
                budget.settle(self.wait(lease, self.receipt(lease, [], final=True)), work=self.work, ledger_path=self.path)
                raise InvalidInfra('authored zero charge')
        finding, _ = self.freeze(c); waste.classify(c, finding)
        record = self.ledger()['infrastructure_waste'][0]
        self.assertEqual(record['event_ids'], [])
        self.assertEqual(record['infrastructure_waste_usd'], '0.000000000')
        with self.assertRaisesRegex(budget.BudgetError, 'invalid_waste_attribution'):
            budget.reclassify_factory_bug(self.path, {**record, 'infrastructure_waste_usd':0.0})

    def test_copied_g10_child_context_and_foreground_attempt_are_disjoint(self):
        import contextvars
        from concurrent.futures import ThreadPoolExecutor
        c = self.context()
        with ThreadPoolExecutor(2) as pool:
            def foreground():
                with self.assertRaises(InvalidInfra):
                    with waste.attempt(c, 'G8', 'b'*64):
                        lease, row = self.reserve()
                        waste.record_reservation(c, row)
                        raise InvalidInfra('authored foreground')
            with self.assertRaises(InvalidInfra):
                with waste.attempt(c, 'G10', 'b'*64):
                    lease, row = self.reserve()
                    child = pool.submit(contextvars.copy_context().run, waste.record_reservation, c, row)
                    other = pool.submit(foreground)
                    child.result(); other.result()
                    raise InvalidInfra('authored G10')
        records = [json.loads(p.read_text()) for p in (self.work/'factory-failures').glob('*.json')]
        self.assertEqual({r['stage'] for r in records}, {'G8', 'G10'})
        self.assertEqual([len(r['reservations']) for r in records], [1,1])
        self.assertNotEqual(records[0]['reservations'][0]['operation_id'], records[1]['reservations'][0]['operation_id'])

    def test_noninfra_and_incomplete_attempts_publish_nothing(self):
        c = self.context()
        for error in (None, budget.BudgetError('provider_wait'), ValueError('authored invalid output')):
            try:
                with waste.attempt(c, 'G8', 'b'*64):
                    if error: raise error
            except (budget.BudgetError, ValueError): pass
        with self.assertRaises(InvalidInfra):
            with waste.attempt(c, 'G8', 'b'*64) as scope:
                scope.mark_unpublishable('authored owner timeout')
                raise InvalidInfra('authored failure')
        self.assertFalse((self.work/'factory-failures').exists())
        self.assertIsNone(waste.current_attempt())


class RuntimeProofTests(unittest.TestCase):
    import test_stream_d_runtime as runtime_fixture
    setUp = runtime_fixture.RuntimeTests.setUp
    patch = runtime_fixture.RuntimeTests.patch

    def test_runtime_hook_records_only_current_attempt_with_actual_reservation(self):
        import model_runtime
        import run
        def invoke(rt, c, *args, **kwargs):
            c.model_process_state['started'] = True
            return 0
        self.patch(model_runtime.ModelRuntime, '_invoke', invoke)
        with self.assertRaises(InvalidInfra):
            with waste.attempt(self.c, 'G8', run.case_hash(self.c)):
                run.opencode(self.c, self.c.models['builder'], 'authored control', self.case, 'builder-proof')
                raise InvalidInfra('authored infra')
        path = next((self.work/'factory-failures').glob('*.json'))
        proof = json.loads(path.read_text()); self.assertEqual(len(proof['reservations']), 1)
        retained = path.read_bytes()
        run.opencode(self.c, self.c.models['builder'], 'authored foreground', self.case, 'builder-foreground')
        self.assertEqual(path.read_bytes(), retained)
        rows = json.loads(self.ledger.read_text())['invocation_reservations']
        row = rows[proof['reservations'][0]['lease_id']]
        self.assertEqual(proof['reservations'][0], {k:row.get(k) for k in waste._FIELDS})
        self.assertEqual(len(rows), 2)


class ReplayLifecycleTests(unittest.TestCase):
    import test_stream_d_held as held_fixture
    setUp = held_fixture.ResumeTests.setUp
    patch = held_fixture.ResumeTests.patch
    transition = held_fixture.ResumeTests.transition
    install_receipt = held_fixture.ResumeTests.install_receipt
    result = held_fixture.ResumeTests.result

    def paid_failure(self, *, final=True):
        import run
        from model_router import Lease
        from router_test_support import synthetic_maximum
        lease = Lease(str(uuid.uuid4()), 'claude/claude-opus-5-5', 'claude-account1', 1,
            'subscription', 'anthropic', 'claude-account1', **synthetic_maximum('authored-cost-control'))
        with self.assertRaises(InvalidInfra):
            with waste.attempt(self.c, 'G8', run.case_hash(self.c)):
                row = budget.reserve_invocation(self.c.ledger, lease, 1,
                    __import__('job_authority').for_case(self.c), operation_id=str(uuid.uuid4()), call_name='reviewer-authored')
                waste.record_reservation(self.c, row)
                directory = self.work/'usage-receipts'; directory.mkdir(exist_ok=True)
                call = 'usage-receipts/'+lease.lease_id+'.json'
                event = {'id': 'authored-'+lease.lease_id, 'cost':.25, 'role':'reviewer', 'invocation':'reviewer-authored'}
                (self.work/call).write_text(json.dumps({'lease_id':lease.lease_id, 'invocation':'reviewer-authored',
                    'events':[event], 'booked_event_ids':[event['id']], 'usage_delta':{'cost':.25}, 'final_usage_known':final}))
                budget.settle({'wait_id':str(uuid.uuid4()), 'lease_id':lease.lease_id, 'call_id':call},
                              work=self.work, ledger_path=self.c.ledger)
                raise InvalidInfra('authored replay lifecycle failure')
        return lease

    def freeze(self):
        if not hasattr(self, 'initial_failure'):
            self.initial_failure = True
            self.initial_lease = self.paid_failure(final='never_final' not in self._testMethodName)
            self.c.card['continuation_budget'] = json.loads(self.c.ledger.read_text())
            self.c.card['batch_release_sha256'] = self.c.authenticated_job_config['batch_release_sha256']
            self.c.checkpoint_card = copy.deepcopy(self.c.card)
            (self.work/'job-money.json').write_text(json.dumps(self.c.job_money))
            (self.c.ledger.parent/(self.c.case_id+'.continuation-budget.json')).unlink(missing_ok=True)  # authored new installation
            self.install_receipt()
        return diagnosis.queued_inputs(self.c, self.bench, quiescent=True)

    def test_never_final_usage_stays_held_with_one_admission(self):
        (self.work/'usage-receipts'/ (self.initial_lease.lease_id+'.json')).unlink()
        retained = None
        for _ in range(2):
            with self.assertRaises(diagnosis.FactoryBugHeldWait) as error:
                diagnosis.resume_factory_bug(self.c)
            self.assertEqual(error.exception.reason, 'money_wait')
            self.assertEqual(self.c.card['terminal_stop'], 'factory_bug_held')
            path = self.work/'factory-bug-resumes.json'
            if retained is None: retained = path.read_bytes()
            else: self.assertEqual(path.read_bytes(), retained)
            self.assertEqual(len(json.loads(retained)), 1)
            self.assertEqual(json.loads(self.c.ledger.read_text()).get('infrastructure_waste', []), [])

    def test_cross_batch_replay_failure_grows_original_waste_and_second_hold_is_empty(self):
        self.assertTrue(diagnosis.resume_factory_bug(self.c))
        self.paid_failure()
        records = json.loads(self.c.ledger.read_text())['infrastructure_waste']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['infrastructure_waste_usd'], '0.500000000')
        self.assertEqual(len(list((self.work/'factory-failures').glob('*.json'))), 1)
        self.assertEqual(len(list((self.work/'factory-replays').glob('*.json'))), 1)
        self.c.card.update(terminal_stop='infrastructure_exhausted',
            infrastructure_gate={'gate':'G8', 'classification':'invalid-infra', 'exhausted':True})
        diagnosis.record_exhaustion(self.c.card, new_exhaustion=True)
        self.parent = self.work/'diagnosis'/self.c.card['diagnosis_state']['exhaustion_id']
        self.c.card['continuation_budget'] = json.loads(self.c.ledger.read_text())
        self.c.card['batch_release_sha256'] = self.c.authenticated_job_config['batch_release_sha256']
        self.c.checkpoint_card = copy.deepcopy(self.c.card)
        (self.work/'job-money.json').write_text(json.dumps(self.c.job_money))
        (self.c.ledger.parent/(self.c.case_id+'.continuation-budget.json')).unlink(missing_ok=True)  # authored next installation
        self.install_receipt()
        manifest = self.freeze()
        diagnosis.persist_factory_bug(self.c, self.result(manifest), generation=manifest['generation'], evidence_root=self.parent/'inputs')
        finding = json.loads((self.parent/'finding.json').read_text())
        self.assertEqual(finding['eligible_operation_ids'], [])
        self.assertEqual(self.c.card['terminal_stop'], 'factory_bug_held')
        self.assertEqual(len(json.loads(self.c.ledger.read_text())['infrastructure_waste']), 1)


if __name__ == '__main__': unittest.main()
