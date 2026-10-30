"""Extension state replay on retained public-practice bytes, authored stage receipts.

This proves lifecycle/progress guards, not live gate or checkpoint qualification.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
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

    def begin(self, entry):
        self.diagnosis()
        proposal = extensions.propose(self.c, entry)
        operation = str(uuid.uuid4())
        route = self.c.models['attacker'][0]
        lease = model_router.Lease(uuid.uuid4().hex, route, 'free', 1, 'free', 'minimax', 'free',
                                   **synthetic_maximum(route))
        budget.reserve_invocation(self.ledger, lease, 0, job_authority.for_case(self.c),
            operation_id=operation, call_name='builder-' + str(proposal['round']))
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


if __name__ == '__main__': unittest.main()
