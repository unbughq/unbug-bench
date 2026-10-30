"""Extension state replay on retained public-practice bytes, authored stage receipts.

This proves lifecycle/progress guards, not live gate or checkpoint qualification.
"""
import copy
import errno
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
import batch_service
import diagnosis
import run
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

    def reserve(self, entry, *, retain_diagnosis=False):
        if not retain_diagnosis: self.diagnosis()
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


    def active_origin(self, origin):
        self.c.card.update(builder_rounds=8, recovery_config={'rounds': 8}, gates={})
        if origin == 'extension_incomplete':
            self.begin(self.snapshot(1))
            extensions.complete(self.c, self.snapshot(2))
            self.c.card['terminal_stop'] = origin
            diagnosis.record_exhaustion(self.c.card, new_exhaustion=True)
            self.c.card['diagnosis_state'].update(status='completed', outcome='close_to_passing')
        else:
            self.diagnosis()
            self.c.card['diagnosis_state']['stop'] = origin
        entry = self.snapshot(2 if origin == 'extension_incomplete' else 1)
        proposal, lease, operation = self.reserve(entry, retain_diagnosis=True)
        row = extensions.admit(self.c, proposal, lease, operation)
        self.c.card['builder_rounds'] = row['round']
        return row, proposal, lease

    def check_active_checkpoints(self, origin):
        row, proposal, lease = self.active_origin(origin)
        saved = copy.deepcopy(self.c.card['diagnosis_state'])
        history = copy.deepcopy(self.c.card['extension_history'])
        private = (self.work / 'extension-history.json').read_bytes()
        reservations = set(json.loads(self.ledger.read_text())['invocation_reservations'])
        self.c.stopped = True
        self.c.exhaustion_occurred = True
        self.c.card['infrastructure_gate'] = {'gate': 'G10', 'exhausted': True}
        # Authored queue envelope; real D projection and batch enqueue code.
        record = dict(schema=1, id='practice', jobs={'j': dict(mode='batch', case='case-practice-j',
            max_calls=10, requested_total_usd='1.000000000')}, money_limit_usd='3.000000000',
            batch_deadline='2099-01-01T00:00:00Z', max_concurrency=1, target_slots=1,
            restore_recipient=(ROOT / 'factory/control-recipient.txt').read_text().strip(),
            replacement_policy={'schema': 1, 'enabled': True})
        for stop in ('extension_comparison_pending', 'provider_wait', 'money_wait',
                     'runner_error:ValueError', 'infrastructure_exhausted', 'budget_exhausted'):
            self.c.card['terminal_stop'] = stop
            for _ in range(2):
                run.finalize_accounting(self.c)
                self.assertEqual(self.c.card['diagnosis_state'], saved)
                self.assertEqual(self.c.card['extension_history'], history)
                self.assertFalse(any(e['stage'] == 'diagnosis_state' for e in self.c.card.get('cleanup_errors', [])))
                self.assertFalse(diagnosis.exhaustion(self.c.card))
                self.assertIsNone(diagnosis.pending_projection(self.c.card))
                self.assertEqual((self.work / 'extension-history.json').read_bytes(), private)
                self.assertEqual(set(json.loads(self.ledger.read_text())['invocation_reservations']), reservations)
            for total in (None, self.baseline):
                card = copy.deepcopy(self.c.card)
                card['case_budget'] = {'total_spent_usd': total}
                facts = batch_service._project(card, diagnosis)
                state = dict(queue={}, derivations={}, next_sequence=0)
                batch_service._enqueue(state, record, dict(job='j', generation='a' * 64, facts=facts), card)
                self.assertEqual(state['queue'], {})
                self.assertEqual(state['derivations'], {})
        with self.assertRaisesRegex(budget.BudgetError, '^extension_already_active$'):
            extensions.propose(self.c, proposal['entry'])
        # One-write lag is repaired using the verified private projection.
        self.c.card['extension_history'] = history[:-1]
        self.assertEqual(extensions.read(self.c)[-1], row)
        self.assertEqual(self.c.card['extension_history'], history)
        extensions.complete(self.c, self.snapshot(3))
        self.c.card['terminal_stop'] = 'extension_incomplete'
        run.finalize_accounting(self.c)
        pending = copy.deepcopy(self.c.card['diagnosis_state'])
        self.assertEqual((pending['status'], pending['stop']), ('pending', 'extension_incomplete'))
        self.assertNotEqual(pending['exhaustion_id'], saved['exhaustion_id'])
        run.finalize_accounting(self.c)
        self.assertEqual(self.c.card['diagnosis_state'], pending)

    def test_late_g4_active_checkpoints(self):
        self.check_active_checkpoints('late_defect_needs_ruling:G4')

    def test_late_g6_active_checkpoints(self):
        self.check_active_checkpoints('late_defect_needs_ruling:G6')

    def test_second_extension_active_checkpoints(self):
        self.check_active_checkpoints('extension_incomplete')
        self.assertEqual(len(self.c.card['extension_history']), 2)

    def test_active_binding_rejects_changed_diagnosis_without_private_mutation(self):
        row, proposal, lease = self.active_origin('late_defect_needs_ruling:G4')
        saved = copy.deepcopy(self.c.card)
        before = extensions.tree(self.work)
        for change in ({'exhaustion_id': str(uuid.uuid4())}, {'status': 'pending', 'outcome': None},
                       {'outcome': 'factory_bug'}, {'outcome': 'not_converging'}):
            for action in (lambda: extensions.read(self.c),
                           lambda: extensions.admit(self.c, proposal, lease, row['writer_operation_id']),
                           lambda: extensions.complete(self.c, proposal['entry'])):
                self.c.card = copy.deepcopy(saved)
                self.c.card['diagnosis_state'].update(change)
                with self.assertRaisesRegex(budget.BudgetError, '^extension_history_invalid$'): action()
                self.assertEqual(extensions.tree(self.work), before)
                self.assertEqual(self.c.card['extension_history'], saved['extension_history'])
        self.c.card = saved
        self.assertEqual(extensions.active(self.c), row)

    def test_prefix_exception_does_not_validate_other_states_or_missing_origin(self):
        self.active_origin('late_defect_needs_ruling:G4')
        saved = copy.deepcopy(self.c.card)
        for changes in ({'stop': 'extension_incomplete'}, {'status': 'pending', 'outcome': None},
                        {'outcome': 'factory_bug'}, {'outcome': 'not_converging'}):
            card = copy.deepcopy(saved)
            card['diagnosis_state'].update(changes)
            self.assertIsNone(diagnosis._state(card, diagnosis.extension_history(card)))
            with self.assertRaisesRegex(budget.BudgetError, '^diagnosis_state_invalid$'):
                diagnosis.record_exhaustion(card, new_exhaustion=True)
        card = copy.deepcopy(saved); card['builder_rounds'] = 7
        self.assertIsNone(diagnosis._state(card, diagnosis.extension_history(card)))
        card = copy.deepcopy(saved); card['diagnosis_state']['stop'] = 'extension_incomplete'
        self.assertIsNone(diagnosis._state(card, None))
        card = copy.deepcopy(saved); card['extension_history'][0]['extension_id'] = False
        self.assertIsNone(diagnosis.extension_history(card))
        with self.assertRaisesRegex(budget.BudgetError, '^diagnosis_state_invalid$'):
            diagnosis.record_exhaustion(card)

    def test_active_read_errors_keep_io_infrastructure_and_bad_records_semantic(self):
        self.active_origin('late_defect_needs_ruling:G4')
        saved = copy.deepcopy(self.c.card)
        before = extensions.tree(self.work)
        read_text = Path.read_text
        for target in (self.work / 'extension-history.json', self.ledger):
            for error in (PermissionError(errno.EACCES, 'authored permission'),
                          OSError(errno.EIO, 'authored disk error')):
                def failing(path, *args, **kwargs):
                    if path == target: raise error
                    return read_text(path, *args, **kwargs)
                with patch.object(Path, 'read_text', failing):
                    with self.assertRaises(type(error)): extensions.read(self.c)
                self.assertEqual(self.c.card, saved)
                self.assertEqual(extensions.tree(self.work), before)
            original = target.read_bytes()
            for content in (b'{', b'null'):
                target.write_bytes(content)
                with self.assertRaisesRegex(budget.BudgetError, '^extension_history_invalid$'):
                    extensions.read(self.c)
                target.write_bytes(original)
            target.unlink()
            with self.assertRaisesRegex(budget.BudgetError, '^extension_history_invalid$'):
                extensions.read(self.c)
            target.mkdir()
            with self.assertRaises(IsADirectoryError): extensions.read(self.c)
            target.rmdir(); target.write_bytes(original)
            self.assertEqual(self.c.card, saved)
        self.assertEqual(extensions.tree(self.work), before)


if __name__ == '__main__': unittest.main()
