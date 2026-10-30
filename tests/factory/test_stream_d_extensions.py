"""Extension state replay on retained public-practice bytes, authored stage receipts.

This proves lifecycle/progress guards, not live gate or checkpoint qualification.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import extensions
import job_authority
import late_recovery
import model_router
from router_test_support import synthetic_maximum
import test_stream_d_runtime as runtime


class ExtensionTests(unittest.TestCase):
    setUp = runtime.RuntimeTests.setUp
    patch = runtime.RuntimeTests.patch

    def snapshot(self, frontier, version='a'):
        # Authored stage evidence is retained alongside the real case bytes.
        proof = self.work / f'extension-test-evidence-{frontier}-{version}.json'
        proof.write_text(json.dumps({'frontier': frontier, 'version': version}))
        evidence = {proof.name: hashlib.sha256(proof.read_bytes()).hexdigest()}
        rows = [{'stage': name, 'version': version * 64, 'status': 'pass' if i < frontier else 'unreached',
                 'binding_sha256': 'b' * 64 if i < frontier else None,
                 'evidence_sha256': evidence[proof.name] if i < frontier else None}
                for i, name in enumerate(extensions.stages())]
        return {'source_generation': self.c.source_generation, 'case_sha256': extensions.digest(extensions.tree(self.case)),
                'stages': rows, 'frontier': frontier, 'evidence': evidence}

    def diagnosis(self):
        self.c.card['diagnosis_state'] = dict(schema_version=1, exhaustion_id=str(uuid.uuid4()),
            stop='budget_exhausted', status='completed', outcome='close_to_passing')

    def reserve(self, entry):
        self.diagnosis()
        proposal = extensions.propose(self.c, entry)
        operation = str(uuid.uuid4())
        route = self.c.models['attacker'][0]
        lease = model_router.Lease(uuid.uuid4().hex, route, 'free', 1, 'free', 'minimax', 'free',
                                   **synthetic_maximum(route))
        budget.reserve_invocation(self.ledger, lease, 0, job_authority.for_case(self.c),
            operation_id=operation, call_name='builder-' + str(proposal['round']))
        return proposal, lease, operation

    def begin(self, entry):
        proposal, lease, operation = self.reserve(entry)
        row = extensions.admit(self.c, proposal, lease, operation)
        self.c.card['builder_rounds'] = row['round']
        return row, proposal, lease

    def test_five_lifetime_extensions_and_rounds_survive_repairs(self):
        self.c.card['builder_rounds'] = 8
        for number in range(1, 6):
            row, proposal, lease = self.begin(self.snapshot(number))
            self.assertEqual(row['extension_id'], number)
            self.assertEqual(row['round'], 8 + number)
            before = (self.work / 'extension-history.json').read_bytes()
            public = copy.deepcopy(self.c.card['extension_history'])
            late_recovery.invalidate(self.c)
            self.c.card['gates'] = {}; self.c.card['gate_results'] = {}
            self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)
            self.assertEqual(self.c.card['extension_history'], public)
            self.assertEqual(extensions.active(self.c)['writer_operation_id'], row['writer_operation_id'])
            # An admission replay spends no second ID or round.
            self.assertEqual(extensions.admit(self.c, proposal, lease, row['writer_operation_id']), row)
            extensions.complete(self.c, self.snapshot(number + 1))
            self.assertIsNone(extensions.active(self.c))
        self.diagnosis()
        with self.assertRaisesRegex(budget.BudgetError, 'retired_extension_limit'):
            extensions.propose(self.c, self.snapshot(6))
        self.assertEqual(len(extensions.read(self.c)), 5)

    def test_entry_requires_stress_diagnosis_and_actual_admitted_reservation(self):
        self.diagnosis()
        with self.assertRaisesRegex(budget.BudgetError, 'retired_no_progress'):
            extensions.propose(self.c, self.snapshot(0))
        proposal = extensions.propose(self.c, self.snapshot(1))
        self.assertFalse((self.work / 'extension-history.json').exists())
        lease = model_router.Lease('not-admitted', 'free', 'free', 1, 'free', 'minimax', 'free',
                                   **synthetic_maximum('free'))
        with self.assertRaisesRegex(budget.BudgetError, 'extension_reservation_missing'):
            extensions.admit(self.c, proposal, lease, str(uuid.uuid4()))
        self.assertFalse((self.work / 'extension-history.json').exists())
        self.c.card['diagnosis_state']['outcome'] = 'factory_bug'
        with self.assertRaisesRegex(budget.BudgetError, 'extension_diagnosis_required'):
            extensions.propose(self.c, self.snapshot(1))

    def test_strict_progress_no_regression_and_changed_versions_are_pending(self):
        entry = self.snapshot(3); outcome = self.snapshot(4)
        self.assertEqual(extensions.progress(entry, outcome), 'progress')
        self.assertEqual(extensions.progress(entry, entry), 'no_progress')
        regressed = self.snapshot(1)
        regressed['stages'][1].update(status='fail', binding_sha256='b' * 64,
                                    evidence_sha256=next(iter(regressed['evidence'].values())))
        self.assertEqual(extensions.progress(entry, regressed), 'regression')
        self.assertEqual(extensions.progress(entry, self.snapshot(4, 'c')), 'pending')
        invalid = self.snapshot(3)
        invalid['stages'][3]['status'] = 'pending'
        self.assertEqual(extensions.progress(entry, invalid), 'pending')

    def test_version_rebase_retains_original_and_cannot_grant_without_same_version_progress(self):
        row, _, _ = self.begin(self.snapshot(1))
        extensions.complete(self.c, self.snapshot(2))
        original = copy.deepcopy(extensions.read(self.c)[0])
        self.diagnosis()
        with self.assertRaisesRegex(budget.BudgetError, 'extension_comparison_pending'):
            extensions.propose(self.c, self.snapshot(2, 'c'))
        extensions.retain_comparison(self.c, 1, self.snapshot(1, 'c'), self.snapshot(2, 'c'))
        proposal = extensions.propose(self.c, self.snapshot(2, 'c'))
        self.assertEqual(proposal['extension_id'], 2)
        saved = extensions.read(self.c)[0]
        self.assertEqual(saved['entry'], original['entry']); self.assertEqual(saved['outcome'], original['outcome'])
        self.assertEqual(len(saved['comparisons']), 1)

    def test_snapshot_case_bytes_are_immutable_and_outcome_is_append_once(self):
        row, _, _ = self.begin(self.snapshot(1))
        (self.case / 'repair.txt').write_text('authored repair control')
        outcome = self.snapshot(2)
        extensions.complete(self.c, outcome)
        extensions.complete(self.c, outcome)
        with self.assertRaisesRegex(budget.BudgetError, 'extension_outcome_changed'):
            extensions.complete(self.c, self.snapshot(3))
        self.assertFalse((self.work / 'extension-snapshots/1/entry/case/repair.txt').exists())
        (self.work / 'extension-snapshots/1/entry/case/case.json').write_text('{}')
        with self.assertRaisesRegex(budget.BudgetError, 'extension_snapshot_changed'):
            extensions.read(self.c)

    def test_pending_entry_never_reserves_or_admits_an_extension(self):
        before = self.ledger.read_bytes()
        entry = self.snapshot(1)
        entry['stages'][1]['status'] = 'pending'
        with self.assertRaisesRegex(budget.BudgetError, '^extension_execution_pending$'):
            self.begin(entry)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertFalse((self.work / 'extension-history.json').exists())
        self.assertEqual(self.c.card.get('extension_history'), [])

    def test_current_regression_cannot_borrow_historical_progress(self):
        self.begin(self.snapshot(3))
        extensions.complete(self.c, self.snapshot(4))
        original = (self.work / 'extension-history.json').read_bytes()
        (self.case / 'regression.txt').write_text('authored changed case')
        entry = self.snapshot(1)
        entry['stages'][1].update(status='fail', binding_sha256='b' * 64,
                                 evidence_sha256=next(iter(entry['evidence'].values())))
        self.diagnosis()
        with self.assertRaisesRegex(budget.BudgetError, '^extension_comparison_pending$'):
            extensions.propose(self.c, entry)
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), original)
        self.assertEqual(len(extensions.read(self.c)), 1)

    def test_one_diagnosis_admits_one_extension_but_replay_keeps_its_id(self):
        row, proposal, lease = self.begin(self.snapshot(1))
        exhaustion_id = self.c.card['diagnosis_state']['exhaustion_id']
        self.assertEqual(row['exhaustion_id'], exhaustion_id)
        self.assertEqual(extensions.admit(self.c, proposal, lease, row['writer_operation_id']), row)
        outcome = self.snapshot(2)
        extensions.complete(self.c, outcome)
        with self.assertRaisesRegex(budget.BudgetError, '^extension_diagnosis_already_used$'):
            extensions.propose(self.c, outcome)
        self.diagnosis()
        # A later checkpoint lineage is fine when the compared case/evidence is identical.
        outcome['source_generation'] = 'c' * 64
        next_proposal = extensions.propose(self.c, outcome)
        self.assertEqual(next_proposal['extension_id'], 2)
        self.assertNotEqual(next_proposal['exhaustion_id'], exhaustion_id)

    def test_round_history_and_restored_counter_cannot_move_backwards(self):
        self.c.card['builder_rounds'] = 8
        self.begin(self.snapshot(1)); extensions.complete(self.c, self.snapshot(2))
        self.c.card['builder_rounds'] = 0
        self.diagnosis()
        with self.assertRaisesRegex(budget.BudgetError, '^extension_history_invalid$'):
            extensions.propose(self.c, self.snapshot(2))
        self.c.card['builder_rounds'] = 9
        self.begin(self.snapshot(2)); extensions.complete(self.c, self.snapshot(3))
        path = self.work / 'extension-history.json'
        history = json.loads(path.read_text())
        self.assertEqual([r['round'] for r in history], [9, 10])
        history[-1]['round'] = 1
        path.write_text(json.dumps(history))
        with self.assertRaisesRegex(budget.BudgetError, '^extension_history_invalid$'):
            extensions.read(self.c)

    def test_completed_writer_operation_cannot_be_admitted_again(self):
        row, _, _ = self.begin(self.snapshot(1))
        extensions.complete(self.c, self.snapshot(2))
        self.diagnosis()
        proposal = extensions.propose(self.c, self.snapshot(2))
        operation = row['writer_operation_id']
        route = self.c.models['attacker'][0]
        lease = model_router.Lease(uuid.uuid4().hex, route, 'free', 1, 'free', 'minimax', 'free',
                                   **synthetic_maximum(route))
        budget.reserve_invocation(self.ledger, lease, 0, job_authority.for_case(self.c),
            operation_id=operation, call_name='builder-' + str(proposal['round']))
        before = (self.work / 'extension-history.json').read_bytes()
        public = copy.deepcopy(self.c.card['extension_history'])
        with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
            extensions.admit(self.c, proposal, lease, operation)
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)
        self.assertEqual(self.c.card['extension_history'], public)
        self.assertFalse((self.work / 'extension-snapshots/2').exists())
        self.assertEqual(len(extensions.read(self.c)), 1)
        self.assertIsNone(extensions.active(self.c))

    def test_durable_admission_and_completion_replay_publication_interruptions(self):
        self.c.card['builder_rounds'] = 8
        proposal, lease, operation = self.reserve(self.snapshot(1))
        atomic = extensions.atomic_json
        def interrupted(path, value):
            atomic(path, value)
            if Path(path).name == 'extension-history.json':
                raise OSError('authored interruption after durable history')
        with patch.object(extensions, 'atomic_json', side_effect=interrupted):
            with self.assertRaises(OSError): extensions.admit(self.c, proposal, lease, operation)
        self.assertEqual(self.c.card['extension_history'], [])
        before = (self.work / 'extension-history.json').read_bytes()
        row = extensions.active(self.c)
        self.assertEqual((row['extension_id'], row['round'], row['writer_operation_id']), (1, 9, operation))
        self.assertEqual(extensions.admit(self.c, proposal, lease, operation), row)
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)
        self.c.card['builder_rounds'] = 9
        outcome = self.snapshot(2)
        with patch.object(extensions, 'atomic_json', side_effect=interrupted):
            with self.assertRaises(OSError): extensions.complete(self.c, outcome)
        self.assertIsNone(self.c.card['extension_history'][-1]['outcome_sha256'])
        before = (self.work / 'extension-history.json').read_bytes()
        extensions.complete(self.c, outcome)
        self.assertIsNotNone(self.c.card['extension_history'][-1]['outcome_sha256'])
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), before)
        # Only the precise previous projection is recoverable, not an unrelated one.
        self.c.card['extension_history'][-1]['entry_sha256'] = 'f' * 64
        with self.assertRaisesRegex(budget.BudgetError, '^extension_history_invalid$'):
            extensions.read(self.c)


if __name__ == '__main__': unittest.main()
