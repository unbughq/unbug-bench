"""First extension admission over saved practice bytes and the 5813be ledger.

Stage/money envelopes and route maxima are authored. Snapshot, router,
reservation, reconciliation and publication run for real; no CLI is launched.
Continuation coverage is direct pending_call replay; no launcher, scientific stage
producer or live qualification is claimed.
"""
import ast
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import diagnosis
import extensions
import job_authority
import model_router
import model_runtime
import registry
import run
import test_stream_d_extensions as states
import test_stream_d_runtime as runtime


class AdmissionTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    snapshot = states.ExtensionTests.snapshot
    diagnosis = states.ExtensionTests.diagnosis

    def setUp(self):
        runtime.RuntimeTests.setUp(self)
        self.c.args.case_budget = self.c.args.ordinary_case_budget = .01
        self.assertGreater(self.baseline, .01)
        self.diagnosis()
        self.entry = self.snapshot(1)
        self.proposal = extensions.propose(self.c, self.entry)
        self.receipt = runtime.RuntimeTests.receipt(self)
        self.receipt['round_limit'] = self.proposal['round']
        self.calls, self.callbacks = [], []

    def call(self, proposal=True, **kwargs):
        return run.pending_call(self.c, self.c.models['builder'], 'authored admission control',
            self.case, kwargs.pop('name', 'builder-1'), kwargs.pop('receipt', self.receipt),
            role=kwargs.pop('role', 'writer'), on_complete=lambda: None,
            on_admitted=kwargs.pop('on_admitted', lambda: self.callbacks.append('admitted')),
            **({'extension_proposal': self.proposal} if proposal else {}), **kwargs)

    def install_transport(self, fallback=False):
        def invoke(driver, context, *args, **kwargs):
            row, = extensions.read(self.c)
            receipt = json.loads((self.work / 'attack-state.json').read_text())
            reservation = json.loads(self.ledger.read_text())['invocation_reservations'][context.model_lease.lease_id]
            self.assertEqual((receipt['extension_id'], receipt['round']), (row['extension_id'], row['round']))
            self.assertEqual(receipt['operation_id'], row['writer_operation_id'])
            self.assertEqual(reservation['operation_id'], row['writer_operation_id'])
            self.assertEqual(reservation['call_name'], 'builder-1')
            self.assertEqual(reservation['state'], 'pending')
            self.assertEqual(self.callbacks, ['admitted'])
            self.calls.append(context.model_lease.lease_id)
            # Only provider rate evidence permits Claude's builder-account fallback.
            if fallback and len(self.calls) == 1:
                context.model_process_state['started'] = True
                raise budget.BudgetError('provider_limit:' + context.model_lease.route,
                    provider_failure=budget.classify_provider_failure('HTTP 429', context.model_lease.route))
            return 0
        return self.patch(model_runtime.ModelRuntime, '_invoke', invoke)

    def assert_unadmitted(self):
        self.assertFalse((self.work / 'extension-history.json').exists())
        self.assertFalse((self.work / 'extension-snapshots').exists())
        self.assertFalse((self.work / 'attack-state.json').exists())
        self.assertEqual(self.c.card['builder_rounds'], 0)
        self.assertEqual(self.callbacks, [])
        self.assertEqual(self.calls, [])

    def refuse(self, label, **kwargs):
        before = self.ledger.read_bytes()
        with patch.object(model_router, 'await_lease', side_effect=AssertionError('lease before verification')):
            with self.assertRaisesRegex(budget.BudgetError, '^' + label + '$'):
                self.call(**kwargs)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assert_unadmitted()

    def test_ordinary_attribute_cannot_bypass_limit_but_verified_extension_can(self):
        self.c.active_extension_id = 1
        with patch.object(run, 'opencode', side_effect=AssertionError('ordinary writer must refuse')):
            with self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
                self.call(proposal=False)
        self.assert_unadmitted()
        self.assertFalse(json.loads(self.ledger.read_text()).get('invocation_reservations'))
        prior = str(uuid.uuid4())
        self.c.model_operation_id = prior
        def admitted():
            row, = extensions.read(self.c)
            receipt = json.loads((self.work / 'attack-state.json').read_text())
            self.assertEqual(row['writer_operation_id'], receipt['operation_id'])
            self.assertEqual(receipt['extension_id'], 1)
            self.assertEqual(self.c.card['builder_rounds'], 1)
            self.callbacks.append('admitted')
        self.install_transport()
        self.call(on_admitted=admitted)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.c.model_operation_id, prior)
        row, = extensions.read(self.c)
        self.assertNotEqual(row['writer_operation_id'], prior)
        self.assertEqual(extensions.tree(self.work / 'extension-snapshots/1/entry/case'), extensions.tree(self.case))

    def test_receipt_contract_refuses_before_lease(self):
        for key in ('schema_version', 'operation_id', 'phase', 'lease_id', 'invocation_id',
                    'resumed_from_wait', 'extension_id'):
            with self.subTest(key=key):
                self.refuse('extension_reservation_mismatch', receipt={**self.receipt, key: None})
        for receipt in ({**self.receipt, 'actor': 'stress_tester'},
                        {**self.receipt, 'round': True}, {**self.receipt, 'round': 2}):
            self.refuse('extension_reservation_mismatch', receipt=receipt)
        self.refuse('extension_reservation_mismatch', role='stress_tester')
        self.refuse('extension_reservation_mismatch', name='builder-2')

    def test_missing_or_nondictionary_binding_refuses_before_admission(self):
        receipt = {key: value for key, value in self.receipt.items() if key != 'binding'}
        self.refuse('extension_reservation_mismatch', receipt=receipt)
        for binding in (None, [], '', False):
            with self.subTest(binding=binding):
                self.refuse('extension_reservation_mismatch', receipt={**self.receipt, 'binding': binding})

    def test_pending_ordinary_operation_cannot_be_adopted(self):
        lease = model_router.await_lease('writer', self.c)
        operation = str(uuid.uuid4())
        budget.reserve_invocation(self.ledger, lease, model_runtime.invocation_maximum(self.c, lease),
            job_authority.for_case(self.c), operation_id=operation, call_name='builder-1')
        budget.release_uninvoked(self.ledger, lease.lease_id)
        model_router.finish(lease.lease_id, 'denied', None)
        self.refuse('extension_reservation_mismatch',
                    receipt={**self.receipt, 'operation_id': operation, 'phase': 'pending'})

    def test_malformed_envelope_and_entry_keep_distinct_labels(self):
        original = copy.deepcopy(self.proposal)
        for changed in ({**original, 'extra': 1}, {**original, 'extension_id': True},
                        {**original, 'exhaustion_id': str(uuid.uuid4())}):
            self.proposal = changed
            self.refuse('extension_reservation_mismatch')
        self.proposal = {**original, 'entry': {}}
        self.refuse('extension_snapshot_invalid')

    def test_source_generation_and_case_changes_refuse(self):
        original = copy.deepcopy(self.proposal)
        self.proposal['entry']['source_generation'] = 'c' * 64
        self.refuse('extension_snapshot_changed')
        self.proposal = original
        (self.case / 'changed.txt').write_text('authored changed case')
        self.refuse('extension_snapshot_changed')

    def test_missing_changed_and_unsafe_evidence_refuse(self):
        name = next(iter(self.entry['evidence']))
        path = self.work / name
        data = path.read_bytes()
        for kind in ('missing', 'changed', 'symlink', 'fifo', 'directory'):
            with self.subTest(kind=kind):
                path.unlink()
                if kind == 'changed': path.write_text('changed')
                elif kind == 'symlink': path.symlink_to(self.case / 'case.json')
                elif kind == 'fifo': os.mkfifo(path)
                elif kind == 'directory': path.mkdir()
                self.refuse('extension_snapshot_changed')
                if path.is_dir() and not path.is_symlink(): path.rmdir()
                else: path.unlink(missing_ok=True)
                path.write_bytes(data)

    def test_evidence_parent_replaced_with_file_refuses(self):
        old = self.work / next(iter(self.entry['evidence']))
        parent = self.work / 'stage-proof'
        parent.mkdir()
        data = old.read_bytes()
        (parent / 'result.json').write_bytes(data)
        self.proposal['entry']['evidence'] = {'stage-proof/result.json': hashlib.sha256(data).hexdigest()}
        (parent / 'result.json').unlink()
        parent.rmdir()
        parent.write_text('not a directory')
        self.refuse('extension_snapshot_changed')

    def test_open_errors_distinguish_changed_evidence_from_infrastructure(self):
        for number in (errno.ELOOP, errno.ENXIO):
            with self.subTest(errno=number), patch.object(diagnosis, '_input_bytes',
                    side_effect=OSError(number, 'authored open failure')):
                self.refuse('extension_snapshot_changed')
        for error in (PermissionError('authored permission failure'), OSError(errno.EIO, 'authored read failure')):
            with self.subTest(error=type(error).__name__), patch.object(diagnosis, '_input_bytes', side_effect=error), \
                    patch.object(model_router, 'await_lease', side_effect=AssertionError('lease must not start')):
                with self.assertRaises(type(error)): self.call()
                self.assert_unadmitted()

    def test_second_verification_refuses_mutation_during_lease_wait(self):
        await_lease = model_router.await_lease
        original_card = copy.deepcopy(self.c.card)
        evidence = self.work / next(iter(self.entry['evidence']))
        data = evidence.read_bytes()
        for kind in ('case', 'evidence', 'diagnosis'):
            observed = []
            def acquire(*args, **kwargs):
                lease = await_lease(*args, **kwargs)
                observed.append(lease.lease_id)
                if kind == 'case': (self.case / 'late-change').write_text('changed')
                elif kind == 'evidence': evidence.write_text('changed')
                else: self.c.card['diagnosis_state']['exhaustion_id'] = str(uuid.uuid4())
                return lease
            with self.subTest(kind=kind), patch.object(model_router, 'await_lease', acquire), \
                    patch.object(model_router, 'finish', wraps=model_router.finish) as finish:
                with self.assertRaises(budget.BudgetError): self.call()
                self.assertEqual(len(observed), 1)
                self.assertNotIn(observed[0], json.loads(self.ledger.read_text()).get('invocation_reservations', {}))
                finish.assert_called_once()
                self.assert_unadmitted()
            (self.case / 'late-change').unlink(missing_ok=True)
            evidence.write_bytes(data)
            self.c.card = copy.deepcopy(original_card)

    def test_caller_proposal_mutation_during_wait_cannot_change_local_copy(self):
        await_lease = model_router.await_lease
        def acquire(*args, **kwargs):
            lease = await_lease(*args, **kwargs)
            self.proposal['round'] = 99
            return lease
        self.install_transport()
        with patch.object(model_router, 'await_lease', acquire):
            self.call()
        self.assertEqual(extensions.read(self.c)[0]['round'], 1)

    def test_batch_money_stays_enforced_above_ordinary_limit(self):
        original = self.ledger.read_bytes()
        for kind in ('commitment', 'unknown'):
            self.ledger.write_bytes(original)
            with budget.ledger_transaction(self.ledger) as ledger:
                if kind == 'commitment': ledger['list_cost_usd'] += 200
                else: ledger.setdefault('unpriced_invocations', []).append(
                    {'role': 'writer', 'model': self.c.models['builder'][0]})
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(budget.BudgetError, '^money_wait$'): self.call()
                self.assert_unadmitted()
                self.assertFalse(json.loads(self.ledger.read_text()).get('invocation_reservations'))

    def test_authority_and_provider_wait_create_no_extension(self):
        with patch.object(self.c, 'job_money', None):
            self.refuse('money_wait')
        expired = {**self.channel, 'batch_deadline': '2020-01-01T00:00:00Z'}
        with patch.multiple(self.c, job_money=expired, authenticated_job_config={'job_money': expired}):
            self.refuse('retired_batch_bound')
        for account in ('claude-token', 'claude-factory-token-2'): self.store.capacities[account] = 0
        with self.assertRaises(model_router.ProviderWait): self.call()
        self.assert_unadmitted()
        self.assertFalse(json.loads(self.ledger.read_text()).get('invocation_reservations'))

    def test_captured_crash_after_reservation_books_maximum_without_admission(self):
        reserve = budget.reserve_invocation
        captured = []
        def die(*args, **kwargs):
            result = reserve(*args, **kwargs)
            captured.append(self.ledger.read_bytes())
            raise runtime.Killed()
        with patch.object(budget, 'reserve_invocation', die):
            with self.assertRaises(runtime.Killed): self.call()
        self.assert_unadmitted()
        # The captured durable image is exactly the process-death boundary:
        # the normal Python unwind above cannot run in that crashed image.
        self.ledger.write_bytes(captured[0])
        row, = json.loads(self.ledger.read_text())['invocation_reservations'].values()
        self.assertEqual(row['state'], 'pending')
        budget.reconcile_reservations(self.work, self.ledger)
        ledger = json.loads(self.ledger.read_text())
        self.assertAlmostEqual(budget.case_spending(ledger)['total_spent_usd'],
                               self.baseline + float(row['maximum_usd']), places=8)
        self.assert_unadmitted()

    def publication_failure(self, boundary):
        atomic = registry.atomic_json
        prior = str(uuid.uuid4())
        self.c.model_operation_id = prior
        def interrupted(path, value):
            if boundary == 'history' and Path(path).name == 'extension-history.json':
                atomic(path, value)
                raise OSError(errno.ENOSPC, 'authored after history publication')
            if boundary == 'attack' and Path(path).name == 'attack-state.json':
                raise OSError(errno.ENOSPC, 'authored attack publication failure')
            atomic(path, value)
        target = extensions if boundary == 'history' else registry
        with patch.object(target, 'atomic_json', interrupted), \
                patch.object(run, 'opencode', side_effect=AssertionError('writer before receipt')):
            with self.assertRaises(OSError): self.call()
        self.assertEqual(self.c.model_operation_id, prior)
        self.assertEqual(self.callbacks, [])
        self.assertFalse((self.work / 'attack-state.json').exists())
        row, = extensions.read(self.c)
        reservation, = json.loads(self.ledger.read_text())['invocation_reservations'].values()
        self.assertEqual(row['writer_operation_id'], reservation['operation_id'])
        self.assertEqual((reservation['state'], reservation['estimated_gap_usd']),
                         ('settled', '0.000000000'))
        with patch.object(model_router, 'await_lease', side_effect=AssertionError('active must refuse')):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_already_active$'):
                self.call(receipt=runtime.RuntimeTests.receipt(self))
        self.assertEqual(len(extensions.read(self.c)), 1)

    def test_history_publication_failure_keeps_id_and_settles_uninvoked_money(self):
        self.publication_failure('history')

    def test_attack_publication_failure_keeps_id_and_settles_uninvoked_money(self):
        self.publication_failure('attack')

    def test_snapshot_write_failure_is_infrastructure_and_starts_no_writer(self):
        with patch.object(extensions.shutil, 'copytree', side_effect=OSError(errno.ENOSPC, 'authored snapshot failure')), \
                patch.object(run, 'opencode', side_effect=AssertionError('writer must not start')):
            with self.assertRaises(OSError): self.call()
        self.assertFalse((self.work / 'extension-history.json').exists())
        self.assertFalse((self.work / 'attack-state.json').exists())
        self.assertEqual(self.callbacks, [])
        row, = json.loads(self.ledger.read_text())['invocation_reservations'].values()
        self.assertEqual((row['state'], row['estimated_gap_usd']), ('settled', '0.000000000'))

    def test_fallback_has_one_extension_and_operation_across_leases(self):
        self.install_transport(fallback=True)
        # Exercise immediate fallback; checkpoint mode separately parks unknown usage.
        with patch.dict(os.environ, {'UNBUG_PROVIDER_WAIT': '0'}):
            self.call()
        self.assertEqual(len(self.calls), 2)
        row, = extensions.read(self.c)
        reservations = list(json.loads(self.ledger.read_text())['invocation_reservations'].values())
        self.assertEqual(len(reservations), 2)
        self.assertEqual([r['account'] for r in reservations], ['claude-factory-token-2', 'claude-token'])
        self.assertEqual({r['operation_id'] for r in reservations}, {row['writer_operation_id']})
        self.assertEqual({r['call_name'] for r in reservations}, {'builder-1'})
        self.assertFalse(hasattr(self.c, 'model_operation_id'))

    def interrupted_extension(self, wait=False):
        if wait:
            rpc = model_router._rpc
            def renewal(operation, payload):
                if operation == 'renew': raise model_router.RouterUnavailable('authored renewal failure')
                return rpc(operation, payload)
            with patch.object(model_router, '_rpc', renewal):
                with self.assertRaises(model_router.ProviderWait) as caught: self.call()
            run.write_provider_wait(self.c, caught.exception)
            self.c.provider_resume_done = False
            self.c.model_resume_state['done'] = False
            run.resume_provider_wait(self.c)
        else:
            with patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=runtime.Killed):
                with self.assertRaises(runtime.Killed): self.call()
        self.receipt = json.loads((self.work / 'attack-state.json').read_text())
        return (self.work / 'extension-history.json').read_bytes()

    def intent_path(self):
        row = extensions.active(self.c)
        return self.work / 'extension-writers' / (row['writer_operation_id'] + '.json')

    def recover_publication(self, boundary, previous=None):
        path = self.work / 'attack-state.json'
        if previous is not None: registry.atomic_json(path, previous)
        atomic = extensions.atomic_json if boundary == 'history' else registry.atomic_json
        def interrupted(destination, value):
            if boundary == 'history' and Path(destination).name == 'extension-history.json':
                atomic(destination, value)
                raise OSError(errno.ENOSPC, 'after durable history')
            if boundary == 'attack' and Path(destination).name == 'attack-state.json':
                raise OSError(errno.ENOSPC, 'before attack publication')
            atomic(destination, value)
        with patch.object(extensions if boundary == 'history' else registry, 'atomic_json', interrupted), \
                patch.object(run, 'opencode', side_effect=AssertionError('writer before publication')):
            with self.assertRaises(OSError): self.call()
        history = (self.work / 'extension-history.json').read_bytes()
        ledger = self.ledger.read_bytes()
        intent = self.intent_path().read_bytes()
        self.assertEqual(json.loads(intent)['previous'], previous)
        recovered = extensions.writer_receipt(self.c)
        self.assertEqual(recovered, json.loads(intent)['receipt'])
        receipt_bytes = path.read_bytes()
        self.c.card['builder_rounds'] = 0  # crash after file but before card update
        self.assertEqual(extensions.writer_receipt(self.c), recovered)
        self.assertEqual(self.c.card['builder_rounds'], 1)
        self.assertEqual(path.read_bytes(), receipt_bytes)
        self.assertEqual(self.intent_path().read_bytes(), intent)
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), history)
        self.assertEqual(self.ledger.read_bytes(), ledger)
        self.receipt = recovered
        self.callbacks = ['admitted']  # first admission stopped before callback
        self.install_transport()
        self.call(proposal=False, on_admitted=None)
        self.assertEqual(len(extensions.read(self.c)), 1)
        self.assertEqual(self.receipt['operation_id'], recovered['operation_id'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(extensions.writer_receipt(self.c), self.receipt)

    def test_recover_history_before_attack_with_no_predecessor(self):
        self.recover_publication('history')

    def test_recover_attack_failure_over_completed_writer(self):
        self.recover_publication('attack', {'round': 0, 'actor': 'writer', 'phase': 'completed'})

    def test_recover_history_over_previous_stress_receipt(self):
        self.recover_publication('history', {'round': 0, 'actor': 'stress_tester', 'phase': 'validated'})

    def test_writer_selector_preserves_wait_and_finished_receipts(self):
        self.interrupted_extension(wait=True)
        path = self.work / 'attack-state.json'
        before = path.read_bytes()
        self.assertEqual(extensions.writer_receipt(self.c), self.receipt)
        self.assertEqual(path.read_bytes(), before)
        self.install_transport()
        self.call(proposal=False, on_admitted=None)
        run.complete_writer(self.c, self.receipt, path)
        for phase, next_phase in [('completed', 'G1'), ('validated', 'stress'), ('validated', 'writer')]:
            self.receipt.update(phase=phase, next_phase=next_phase)
            registry.atomic_json(path, self.receipt)
            before = path.read_bytes()
            self.assertEqual(extensions.writer_receipt(self.c), self.receipt)
            self.assertEqual(path.read_bytes(), before)
        self.receipt['binding']['case'] = 'inconsistent authored binding'
        registry.atomic_json(path, self.receipt)
        with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
            extensions.writer_receipt(self.c)

    def assert_selector_refuses_unchanged(self, receipt):
        path = self.work / 'attack-state.json'
        registry.atomic_json(path, receipt)
        files = (path, self.intent_path(), self.work / 'extension-history.json', self.ledger)
        before = [item.read_bytes() for item in files]
        with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
            extensions.writer_receipt(self.c)
        self.assertEqual([item.read_bytes() for item in files], before)

    def test_writer_selector_checks_finished_reservations_binding_and_phase(self):
        self.interrupted_extension()
        pending = copy.deepcopy(self.receipt)
        changed = {**pending, 'binding': {'case': 'changed with consistent hash'}}
        changed['binding_sha256'] = hashlib.sha256(json.dumps(changed['binding'], sort_keys=True).encode()).hexdigest()
        self.assert_selector_refuses_unchanged(changed)
        self.assert_selector_refuses_unchanged({**pending, 'phase': 'abandoned'})
        lease = model_router.await_lease('writer', self.c)
        foreign = budget.reserve_invocation(self.ledger, lease, '1', job_authority.for_case(self.c),
            operation_id=str(uuid.uuid4()), call_name='builder-1')
        budget.release_uninvoked(self.ledger, lease.lease_id)
        model_router.finish(lease.lease_id, 'denied', None)
        run.complete_writer(self.c, self.receipt, self.work / 'attack-state.json')
        for phase in ('completed', 'validated'):
            self.assert_selector_refuses_unchanged({**self.receipt, 'phase': phase,
                'lease_id': lease.lease_id, 'invocation_id': foreign['invocation_id']})
            self.assert_selector_refuses_unchanged({**self.receipt, 'phase': phase,
                'lease_id': None, 'invocation_id': None})

    def test_finished_writer_cannot_borrow_pending_wait_archive_proof(self):
        self.interrupted_extension(wait=True)
        self.assertIsNone(self.receipt['lease_id'])
        self.assertTrue(run.provider_continuation(self.c, self.receipt, 'writer'))
        self.assertEqual(extensions.writer_receipt(self.c), self.receipt)
        run.complete_writer(self.c, self.receipt, self.work / 'attack-state.json')
        for phase in ('completed', 'validated'):
            self.assert_selector_refuses_unchanged({**self.receipt, 'phase': phase})

    def test_writer_selector_leaves_same_round_stress_to_package(self):
        self.interrupted_extension()
        intent_path = self.intent_path()
        intent_bytes = intent_path.read_bytes()
        intent_path.unlink()  # no writer recovery or authority is needed
        path = self.work / 'attack-state.json'
        for phase in ('pending', 'completed', 'validated'):
            registry.atomic_json(path, {'round': 1, 'actor': 'stress_tester', 'phase': phase})
            before = path.read_bytes()
            self.assertIsNone(extensions.writer_receipt(self.c))
            self.assertEqual(path.read_bytes(), before)
        intent_path.write_bytes(intent_bytes)
        for number in (True, 2):
            registry.atomic_json(path, {'round': number, 'actor': 'stress_tester', 'phase': 'pending'})
            with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
                extensions.writer_receipt(self.c)

    def test_writer_selector_refuses_damaged_intent_or_current_without_writes(self):
        self.interrupted_extension()
        intent_path, path = self.intent_path(), self.work / 'attack-state.json'
        original_intent, original = intent_path.read_bytes(), path.read_bytes()
        for target, source in ((intent_path, original_intent), (path, original)):
            for field, value in [('operation_id', str(uuid.uuid4())), ('extension_id', True),
                                 ('round', 2), ('input_problems', ['changed']), ('binding_sha256', '0' * 64),
                                 ('invocation_id', str(uuid.uuid4())), ('actor', 'stress_tester')]:
                if target == intent_path and field == 'input_problems': continue  # retained input is authoritative
                if target == path and field == 'actor': value = 'foreign'
                changed = json.loads(source)
                receipt = changed['receipt'] if target == intent_path else changed
                receipt[field] = value
                if field == 'round': receipt['report'] = f'round-{value}.json'
                registry.atomic_json(target, changed)
                before = (path.read_bytes(), intent_path.read_bytes(), self.ledger.read_bytes())
                with self.subTest(target=target.name, field=field):
                    with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
                        extensions.writer_receipt(self.c)
                    self.assertEqual((path.read_bytes(), intent_path.read_bytes(), self.ledger.read_bytes()), before)
                target.write_bytes(source)
        for raw in ('null', '[]', '{bad', '{}'):
            intent_path.write_text(raw)
            with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
                extensions.writer_receipt(self.c)
        intent_path.unlink()
        with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
            extensions.writer_receipt(self.c)
        intent_path.write_bytes(original_intent)
        for target, source in ((intent_path, original_intent), (path, original)):
            target.unlink(); target.symlink_to(self.ledger)
            with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
                extensions.writer_receipt(self.c)
            target.unlink(); target.write_bytes(source)
        envelope = json.loads(original_intent)
        envelope['previous'] = {'round': 0}
        registry.atomic_json(intent_path, envelope)
        path.unlink()
        with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
            extensions.writer_receipt(self.c)

    def test_bad_predecessor_or_intent_write_failure_never_admits_history(self):
        path = self.work / 'attack-state.json'
        for previous in ({'round': 1}, {'round': True}, {'round': -1}, [], None):
            registry.atomic_json(path, previous)
            with patch.object(run, 'opencode', side_effect=AssertionError('must not invoke')):
                with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
                    self.call(receipt=runtime.RuntimeTests.receipt(self))
            self.assertFalse((self.work / 'extension-history.json').exists())
        path.unlink()
        atomic = extensions.atomic_json
        def failure(path, value):
            if Path(path).parent.name == 'extension-writers': raise OSError(errno.ENOSPC, 'intent write')
            atomic(path, value)
        with patch.object(extensions, 'atomic_json', failure):
            with self.assertRaises(OSError): self.call()
        self.assert_unadmitted()
        self.assertIsNone(extensions.writer_receipt(self.c))

    def test_orphan_intent_is_inert_and_helper_replay_is_immutable(self):
        with patch.object(extensions, 'admit', side_effect=OSError(errno.ENOSPC, 'before history')):
            with self.assertRaises(OSError): self.call()
        intent_path, = (self.work / 'extension-writers').glob('*.json')
        saved = intent_path.read_bytes()
        intent = json.loads(saved)['receipt']
        self.assertIsNone(extensions.writer_receipt(self.c))
        self.assertFalse((self.work / 'attack-state.json').exists())
        self.assertEqual(self.c.card['builder_rounds'], 0)
        extensions.retain_writer(self.c, intent)
        self.assertEqual(intent_path.read_bytes(), saved)
        with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
            extensions.retain_writer(self.c, {**intent, 'input_problems': ['changed']})
        self.assertEqual(intent_path.read_bytes(), saved)
        self.assertEqual(self.callbacks, [])
        self.assertEqual(self.calls, [])

    def test_receipt_read_io_is_infrastructure_and_parent_symlink_refuses(self):
        self.interrupted_extension()
        original = diagnosis._input_bytes
        intent = self.intent_path()
        for error in (PermissionError('authored permission denial'), OSError(errno.EIO, 'authored EIO')):
            def failed(path, base):
                if Path(path) == intent: raise error
                return original(path, base)
            with patch.object(diagnosis, '_input_bytes', failed):
                with self.assertRaises(type(error)): extensions.writer_receipt(self.c)
        directory = intent.parent
        moved = self.work / 'retained-writers'
        directory.rename(moved); directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
            extensions.writer_receipt(self.c)

    def test_pending_extension_continues_same_operation_above_ordinary_threshold(self):
        history = self.interrupted_extension()
        original = copy.deepcopy(self.receipt)
        self.install_transport()
        self.call(proposal=False, on_admitted=None)
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), history)
        for field in ('extension_id', 'operation_id', 'round'):
            self.assertEqual(self.receipt[field], original[field])
        self.assertNotEqual(self.receipt['lease_id'], original['lease_id'])
        self.assertEqual(self.c.card['builder_rounds'], 1)
        self.assertEqual(len(self.calls), 1)

    def test_settled_provider_wait_continues_extension(self):
        history = self.interrupted_extension(wait=True)
        original = copy.deepcopy(self.receipt)
        self.assertIsNone(original['lease_id'])
        self.assertIsNone(original['invocation_id'])
        self.assertTrue(run.provider_continuation(self.c, original, 'writer'))
        self.install_transport()
        self.call(proposal=False, on_admitted=None)
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), history)
        for field in ('extension_id', 'operation_id', 'round'):
            self.assertEqual(self.receipt[field], original[field])
        self.assertEqual(len(self.calls), 1)

    def refuse_continuation(self, receipt=None, name='builder-1', label='extension_reservation_mismatch'):
        before = self.ledger.read_bytes()
        with patch.object(model_router, 'await_lease', side_effect=AssertionError('lease before verification')):
            with self.assertRaisesRegex(budget.BudgetError, '^' + label + '$'):
                self.call(proposal=False, receipt=receipt or self.receipt, name=name)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_continuation_receipt_mismatches_refuse_before_provider(self):
        self.interrupted_extension()
        for key, values in {
            'extension_id': [None, True, 2], 'round': [True, 2],
            'operation_id': [None, str(uuid.uuid4())], 'schema_version': [True, 1],
            'phase': ['completed', 'validated'], 'actor': ['stress_tester'],
            'lease_id': [None, uuid.uuid4().hex], 'invocation_id': [None, str(uuid.uuid4())],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    self.refuse_continuation({**self.receipt, key: value})
        self.refuse_continuation(name='builder-2')
        self.refuse_continuation(runtime.RuntimeTests.receipt(self))
        self.refuse_continuation({**self.receipt, 'lease_id': None, 'invocation_id': None})

    def test_wait_requires_archive_and_matching_settlement_id(self):
        self.interrupted_extension(wait=True)
        identity = self.receipt['resumed_from_wait']
        archive = self.work / 'provider_waits' / (identity + '.json')
        data = archive.read_bytes(); archive.unlink()
        self.refuse_continuation()
        archive.write_bytes(data)
        with budget.ledger_transaction(self.ledger) as ledger:
            ledger['wait_settlements'][str(uuid.uuid4())] = ledger['wait_settlements'].pop(identity)
        self.refuse_continuation()

    def test_extension_marker_without_history_and_completed_history_refuse(self):
        self.refuse_continuation({**self.receipt, 'extension_id': 1})
        self.interrupted_extension()
        extensions.complete(self.c, self.snapshot(2))
        self.refuse_continuation()

    def test_continuation_keeps_batch_money_and_current_authority(self):
        history = self.interrupted_extension()
        with patch.object(self.c, 'job_money', {**self.channel, 'revision': 999}):
            self.refuse_continuation(label='money_wait')
        with budget.ledger_transaction(self.ledger) as ledger:
            ledger['list_cost_usd'] += 200
        with patch.object(run, 'opencode', side_effect=AssertionError('must not invoke')):
            with self.assertRaisesRegex(budget.BudgetError, '^money_wait$'):
                self.call(proposal=False)
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), history)
        self.assertEqual(self.c.card['builder_rounds'], 1)

    def test_continuation_rechecks_binding_after_lease_wait(self):
        self.interrupted_extension()
        acquire = model_router.await_lease
        def changed(*args, **kwargs):
            lease = acquire(*args, **kwargs)
            self.receipt['operation_id'] = str(uuid.uuid4())
            return lease
        before = self.ledger.read_bytes()
        with patch.object(model_router, 'await_lease', changed):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'):
                self.call(proposal=False)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_extension_argument_has_only_diagnosis_admission_caller(self):
        for path in (ROOT / 'factory').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call):
                    if 'extension_proposal' in {kw.arg for kw in node.keywords}:
                        self.assertEqual(path.name, 'diagnosis_dispatch.py')


if __name__ == '__main__': unittest.main()

