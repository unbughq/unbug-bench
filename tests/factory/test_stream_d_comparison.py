"""Saved practice/ledger/checkpoint proof; process/model transports are authored.

The synchronous channel tests parent retry, capture and admission for real. Linux
process containment has a separate platform exam; these controls are not live
worker or model qualification.
"""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import diagnosis
import extension_compare as comparison
import extension_evaluator as evaluator
import extension_package as package
import extensions
import factory_waste
import gate_state
import model_runtime
import registry
import recovery
import run
from run_validity import InvalidInfra
import test_extension_compare as comparison_tests
import test_stream_d_runtime as runtime

REAL_PUBLIC_PROGRESS = run.public_progress
REAL_START_CHILD = evaluator.Evaluator.start_child
REAL_CHECKPOINT = evaluator.Evaluator.checkpoint


class ComparisonTests(unittest.TestCase):
    patch = comparison_tests.CompareTests.patch
    diagnosis = comparison_tests.CompareTests.diagnosis
    reserve = comparison_tests.CompareTests.reserve
    begin = comparison_tests.CompareTests.begin
    workspace = comparison_tests.CompareTests.workspace
    evaluator = comparison_tests.CompareTests.evaluator
    prepare = comparison_tests.CompareTests.prepare

    def setUp(self):
        comparison_tests.CompareTests.setUp(self)
        self.patch(run, 'SEALED', self.work / 'sealed-progress')
        self.checkpoints = []
        def checkpoint(instance, force=False):
            self.checkpoints.append(copy.deepcopy(instance.c.card))
            return False
        self.patch(evaluator.Evaluator, 'checkpoint', checkpoint)
        self.transport_calls = []
        self.failures = {}
        self.ack_loss = set()
        test = self
        class Channel:
            def __init__(channel, owner): channel.owner = owner
            def send(channel, message):
                if message[0] != 'stage': return
                owner = channel.owner
                stage = message[1]
                key = (owner.phase, stage)
                test.transport_calls.append(key)
                if test.failures.get(key, 0):
                    test.failures[key] -= 1
                    raise InvalidInfra('authored child death')
                c = owner.context
                if stage == 'G3':
                    c.card.update(bench_workers_effective=1, factory_slots_prepared=1)
                workspace = comparison.Workspace(c.case, c.work, run.BENCH, c.args,
                    c.models, c.card, c.seed, 0, c.case_id)
                ok, info, paths = test.evaluator(workspace, stage)
                owner.records.save(stage, ok, info, {}, package.project(c.card))
                if key in test.ack_loss:
                    test.ack_loss.remove(key)
                    raise InvalidInfra('authored death after record publication')
                channel.reply = ('result', evaluator.operations(c))
        def start(instance): instance.pipe = Channel(instance)
        self.patch(evaluator.Evaluator, 'start_child', start)
        self.patch(evaluator.Evaluator, 'receive', lambda instance: instance.pipe.reply)
        self.patch(evaluator.Evaluator, 'close_child', lambda instance: None)

    def ready(self, *, receipts=False):
        self.prepare(receipts=receipts)
        self.diagnosis()
        self.c.card.update(status='stopped', terminal_stop='extension_comparison_pending')
        self.original = copy.deepcopy(extensions.read(self.c)[0])

    def test_real_saved_g4_g5_pair_then_next_entry_and_no_reroll(self):
        self.ready()
        tree = extensions.tree(self.case)
        original_status = self.c.card['terminal_stop']
        value = package.entry(self.c, run)
        self.assertEqual(value['source_generation'], self.c.source_generation)
        self.assertEqual(extensions.tree(self.case), tree)
        self.assertEqual(self.c.card['terminal_stop'], original_status)
        history = extensions.read(self.c)
        self.assertEqual(history[0]['entry'], self.original['entry'])
        self.assertEqual(history[0]['outcome'], self.original['outcome'])
        self.assertEqual(extensions.propose(self.c, value)['extension_id'], 2)
        self.assertTrue(self.transport_calls)
        public = json.loads((run.SEALED / (self.c.case_id + '.progress.json')).read_text())
        self.assertEqual(public['stages']['comparison']['status'], 'completed')
        self.assertIn('comparison:G5', public['stages'])
        first = list(self.transport_calls)
        with patch.object(evaluator.Evaluator, '__init__', side_effect=AssertionError('new execution')):
            self.assertEqual(package.entry(self.c, run), value)
        self.assertEqual(self.transport_calls, first)
        for card in self.checkpoints:
            self.assertEqual(card['terminal_stop'], 'runner_error:comparison_in_progress')
            self.assertIsNone(card['failed_gate'])
            recovery.require_restart_stop(card, [])

    def test_one_child_death_retries_in_launch(self):
        self.ready()
        self.failures[('entry', 'stress')] = 1
        value = package.entry(self.c, run)
        self.assertEqual(extensions.propose(self.c, value)['extension_id'], 2)
        self.assertEqual(self.transport_calls.count(('entry', 'stress')), 2)
        proofs = list((self.work / 'factory-failures').glob('*.json'))
        self.assertEqual(len(proofs), 1)
        self.assertEqual(json.loads(proofs[0].read_text())['stage'], 'stress')

    def test_record_after_lost_reply_never_reinvokes(self):
        self.ready()
        self.ack_loss.add(('entry', 'G4'))
        package.entry(self.c, run)
        self.assertEqual(self.transport_calls.count(('entry', 'G4')), 1)

    def test_two_child_deaths_queue_stress_diagnosis(self):
        self.ready()
        self.failures[('entry', 'stress')] = 2
        with self.assertRaisesRegex(budget.BudgetError, '^stress_validation_exhausted$'):
            package.entry(self.c, run)
        self.c.card['terminal_stop'] = 'stress_validation_exhausted'
        diagnosis.record_exhaustion(self.c.card, new_exhaustion=True)
        self.assertEqual(self.c.card['diagnosis_state']['status'], 'pending')
        self.assertNotIn('infrastructure_gate', self.c.card)
        self.assertTrue(list((self.work / 'comparison-diagnostics').rglob('infra-attempts.json')))

    def test_gate_exhaustion_has_valid_owner_marker(self):
        self.ready()
        self.failures[('entry', 'G4')] = 2
        with self.assertRaisesRegex(budget.BudgetError, '^infrastructure_exhausted$'):
            package.entry(self.c, run)
        self.assertEqual(self.c.card['infrastructure_gate']['gate'], 'G4')
        self.assertTrue(self.c.card['infrastructure_gate']['exhausted'])
        self.c.card['terminal_stop'] = 'infrastructure_exhausted'
        diagnosis.record_exhaustion(self.c.card, new_exhaustion=True)
        self.assertEqual(self.c.card['diagnosis_state']['status'], 'pending')

    def test_completed_original_does_not_construct_evaluator(self):
        self.ready(receipts=True)
        with patch.object(evaluator, 'Evaluator', side_effect=AssertionError('execution')):
            value = package.entry(self.c, run)
        self.assertEqual(extensions.propose(self.c, value)['extension_id'], 2)

    def test_changed_live_freshness_is_evidence_stop(self):
        self.ready(receipts=True)
        with (self.case / 'freshness.jsonl').open('a') as out: out.write('\n')
        with patch.object(evaluator, 'Evaluator', side_effect=AssertionError('execution')):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
                package.entry(self.c, run)

    def test_receipts_report_actual_execution_without_changing_versions(self):
        w = self.workspace()
        versions = comparison._versions(w)
        w = comparison.Workspace(w.case, w.work, w.bench, w.args, w.models, w.card,
                                w.seed, w.factory_slot, w.case_id, evaluator.EXECUTION)
        self.assertEqual(comparison._versions(w), versions)
        snapshot = comparison.snapshot(w, self.c.source_generation, self.evaluator)
        receipt = json.loads((w.work / 'comparison-receipts/G4.json').read_text())
        self.assertEqual(receipt['execution']['bench_workers'], 1)
        self.assertFalse(receipt['execution']['concurrent_roles'])
        self.assertEqual(snapshot['stages'][4]['version'], versions['G4'])

    def test_parent_scope_never_links_comparison_to_old_resume(self):
        with patch.object(factory_waste, 'resume_scope', side_effect=AssertionError('old resume')), \
                patch.object(factory_waste, 'classify', side_effect=AssertionError('old attribution')):
            with self.assertRaises(InvalidInfra):
                with factory_waste.attempt(self.c, 'G10', run.case_hash(self.c), comparison=True):
                    raise InvalidInfra('authored comparison failure')
        self.assertFalse((self.work / 'factory-replays').exists())

    def test_forwarded_owner_timeout_suppresses_parent_proof(self):
        with self.assertRaises(InvalidInfra):
            with factory_waste.attempt(self.c, 'G10', run.case_hash(self.c), comparison=True) as parent:
                with factory_waste.forward_attempt(parent.mark_unpublishable):
                    scope = factory_waste.current_attempt()
                    self.assertIsNotNone(scope)
                    factory_waste.record_reservation(self.c, {'authored': 'ignored in child'})
                    scope.mark_unpublishable('owner_drain_timeout')
                    raise InvalidInfra('owner request cleanup incomplete')
        self.assertFalse((self.work / 'factory-failures').exists())
        self.assertFalse((self.work / 'factory-replays').exists())

    def test_dead_child_settles_final_receipt_before_retry_admission(self):
        import job_authority, model_router
        from router_test_support import synthetic_maximum
        self.ready()
        original_start = evaluator.Evaluator.start_child
        started = []
        lease = model_router.Lease(str(uuid.uuid4()), self.c.models['builder'][0], 'claude-token', 1,
            'subscription', 'anthropic', 'claude-token', **synthetic_maximum(self.c.models['builder'][0]))
        def start(instance):
            if not started:
                budget.reserve_invocation(self.ledger, lease, 1, job_authority.for_case(self.c),
                    operation_id=str(uuid.uuid4()), call_name='comparison-authored-dead-call')
                (self.work / 'usage-receipts').mkdir(exist_ok=True)
                registry.atomic_json(self.work / 'usage-receipts' / (lease.lease_id + '.json'),
                    dict(lease_id=lease.lease_id, events=[], booked_event_ids=[],
                         final_usage_known=True, outcome='done', usage_delta={'cost': 0}))
                started.append('died')
                raise InvalidInfra('authored death with final zero-usage receipt')
            row = json.loads(self.ledger.read_text())['invocation_reservations'][lease.lease_id]
            self.assertEqual(row['state'], 'settled')
            self.assertEqual(row['estimated_gap_usd'], '0.000000000')
            started.append('retry-after-settlement')
            original_start(instance)
        with patch.object(evaluator.Evaluator, 'start_child', start):
            package.entry(self.c, run)
        self.assertEqual(started[:2], ['died', 'retry-after-settlement'])
        self.assertEqual(budget.case_spending(json.loads(self.ledger.read_text()))['total_spent_usd'], self.baseline)

    def test_thread_wait_accepts_quiescence_and_exhausts_without_fork(self):
        import threading
        from unittest.mock import Mock
        self.ready()
        versions = comparison._versions(self.workspace())
        instance = evaluator.Evaluator(self.c, run, 1, versions)
        instance.context, instance.manifest = self.c, {}
        event = threading.Event()
        thread = threading.Thread(target=event.wait, daemon=True)
        thread.start()
        child = Mock(pid=12345)
        channel, peer = Mock(), Mock()
        context = Mock()
        context.Pipe.return_value = channel, peer
        context.Process.return_value = child
        def release(_): event.set(); thread.join(1)
        try:
            with patch.object(evaluator.threading, 'active_count', side_effect=lambda: 1 + thread.is_alive()), \
                    patch.object(evaluator.time, 'sleep', side_effect=release), \
                    patch.object(evaluator, 'install_bench'), patch.object(evaluator, 'subreaper', return_value=0), \
                    patch.object(evaluator.multiprocessing, 'get_context', return_value=context), \
                    patch.object(instance, 'receive', return_value=('ready', 12345)):
                REAL_START_CHILD(instance)
            child.start.assert_called_once()
            self.assertFalse(thread.is_alive())
        finally: event.set(); thread.join(1)
        # A genuinely live thread is held beyond each authored 30-second deadline.
        event.clear(); thread = threading.Thread(target=event.wait, daemon=True); thread.start()
        clock = [0]
        def elapsed(_): clock[0] += 31
        try:
            with patch.object(evaluator.Evaluator, 'start_child', REAL_START_CHILD), \
                    patch.object(evaluator.threading, 'active_count', side_effect=lambda: 1 + thread.is_alive()), \
                    patch.object(evaluator.time, 'monotonic', side_effect=lambda: clock[0]), \
                    patch.object(evaluator.time, 'sleep', side_effect=elapsed), \
                    patch.object(evaluator.multiprocessing, 'get_context', side_effect=AssertionError('unsafe fork')):
                with self.assertRaisesRegex(budget.BudgetError, '^stress_validation_exhausted$'):
                    package.entry(self.c, run)
        finally: event.set(); thread.join(1)
        journal = next((self.work / 'comparison-runs').rglob('infra-attempts.json'))
        self.assertEqual(next(iter(json.loads(journal.read_text()).values()))['invalid_attempts'], 2)

    def test_real_parent_checkpoint_is_restartable_and_forces_final_publication(self):
        import hashlib, restart
        self.ready()
        self.c.card['seed'] = self.c.seed
        # Frozen practice bytes stand in for ciphertext transport; no encryption/R2 call.
        archive_bytes = (ROOT / 'tests/factory/fixtures/invalid-runs-practice.json.gz').read_bytes()
        archive = self.work / (self.c.case_id + '.checkpoint.tar.gz.age')
        public = self.work / (self.c.case_id + '.scorecard.json')
        sealed = []
        def seal(c, checkpoint=False):
            self.assertIs(c, self.c)
            self.assertTrue(checkpoint)
            archive.write_bytes(archive_bytes)
            c.card.update(archive=str(archive), sha256=hashlib.sha256(archive_bytes).hexdigest(),
                          r2_object='authored-comparison-checkpoint')
            registry.atomic_json(public, c.card)
            self.assertEqual(restart.plan(public, 0, 7200,
                '--max-cost 100000 --max-total-calls 100000 --case-budget 100000'),
                (c.case_id, 60, c.seed))
            self.assertEqual(c.card['terminal_stop'], 'runner_error:comparison_in_progress')
            sealed.append(copy.deepcopy(c.card))
        with patch.object(evaluator.Evaluator, 'checkpoint', REAL_CHECKPOINT), patch.object(run, 'seal', seal):
            package.entry(self.c, run)
        self.assertEqual(len(sealed), 2)  # First stage plus forced completed-pair publication.
        self.assertTrue(extensions.read(self.c)[0]['comparisons'])
        self.assertFalse(list((self.work / 'comparison-runs').glob('*/*/bench')))

    def test_stale_remote_receipt_never_deletes_scratch(self):
        self.ready()
        self.c.card['durable_checkpoint'] = {'remote_durable': True}
        package.entry(self.c, run)  # Authored checkpoint callback returns False.
        self.assertTrue(list((self.work / 'comparison-runs').glob('*/*/pair-attempts.json')))

    def test_retry_checks_versions_before_replaying_committed_record(self):
        self.ready()
        instance = evaluator.Evaluator(self.c, run, 1, comparison._versions(self.workspace()))
        instance.records = SimpleNamespace(load=lambda stage: {'ok': True, 'info': {}})
        with patch.object(comparison, '_versions', return_value={'G1': 'f' * 64}), \
                patch.object(run, 'case_budget_boundary', side_effect=AssertionError('admission after drift')):
            with self.assertRaisesRegex(InvalidInfra, 'comparison version changed'):
                instance.invoke('G1')
            with patch.object(instance, 'phase_for', side_effect=AssertionError('cached result after drift')):
                with self.assertRaisesRegex(InvalidInfra, 'comparison version changed'):
                    instance(self.workspace(), 'G1')

    def test_pending_pair_routes_to_producer_before_writer_admission(self):
        import diagnosis_dispatch
        self.ready()
        manifest = dict(exhaustion_id=self.c.card['diagnosis_state']['exhaustion_id'])
        with runtime.diagnosis_policy(self.c), \
                patch.object(extensions, 'comparison_pair', return_value=None), \
                patch.object(extensions, 'writer_receipt', side_effect=AssertionError('writer before comparison')):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_comparison_pending$'):
                diagnosis_dispatch.apply(self.c, self.work, manifest, {'outcome': 'close_to_passing'})
            self.assertEqual(diagnosis_dispatch.apply(self.c, self.work, manifest,
                {'outcome': 'close_to_passing'}, comparison_route=True), 0)
        self.failures[('entry', 'stress')] = 2
        with patch.object(run, 'writer_request', side_effect=AssertionError('writer before comparison')):
            with self.assertRaisesRegex(budget.BudgetError, '^stress_validation_exhausted$'):
                package.entry(self.c, run)

    def test_tampered_completed_pair_never_reexecutes(self):
        self.ready()
        package.entry(self.c, run)
        pair, valid, retained = comparison.current_pair(self.c, 1, run.BENCH)
        self.assertTrue(valid and retained)
        # Mutate the retained receipt itself, not a fixture produced by the test.
        roots = list((self.work / 'extension-snapshots').rglob('*.json'))
        receipt = next(path for path in roots if 'comparison-receipts' in path.parts)
        receipt.write_text('{}')
        with patch.object(evaluator.Evaluator, '__init__', side_effect=AssertionError('reroll')):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
                package.entry(self.c, run)

    def test_accounting_root_does_not_change_scientific_work(self):
        child = evaluator.phase_context(self.c, self.work / 'isolated', 1)
        self.assertEqual(model_runtime.accounting_work(child), self.work)
        self.assertNotEqual(child.work, self.work)
        self.assertEqual(model_runtime.accounting_work(self.c), self.work)
        self.assertFalse(hasattr(child, 'recipient'))

    def test_pinned_record_version_does_not_change_cache_identity(self):
        self.c.args.bench_workers = 1
        version = gate_state.scientific_version(self.c, 'G4', ROOT)
        signature = gate_state.fingerprint(self.c, 'G4', ROOT)
        gate_state.save(self.c, 'G4', {'authored': 'pass'}, signature, {}, ROOT)
        self.assertIsNotNone(gate_state.load(self.c, 'G4', ROOT))
        self.assertEqual(gate_state.scientific_version(self.c, 'G4', ROOT), version)
        records = package.Records(self.c, run, observation_id=str(uuid.uuid4()),
                                  round_number=1, expected_versions={'G4': 'f' * 64})
        records.save('G4', True, {'authored': 'pass'}, {}, {})
        self.assertEqual(records.load('G4')['scientific_version'], 'f' * 64)
        self.assertEqual(gate_state.fingerprint(self.c, 'G4', ROOT), signature)


    def child_protocol(self, stage, action, attempt_id=None, on_send=None, real_setup=False, end=None):
        """Authored synchronous Pipe, exercising the real child loop on macOS too."""
        root = self.work / 'protocol'
        root.mkdir(exist_ok=True)
        context = evaluator.phase_context(self.c, root, 1)
        context.manifest0 = run.bench_manifest(ROOT)
        shutil.copytree(self.case, context.case, dirs_exist_ok=True)
        for name in ('logs', 'transcripts'):
            (context.work / name).mkdir(parents=True, exist_ok=True)
        manifest = dict(observation_id=str(uuid.uuid4()), round_number=1)
        versions = comparison._versions(self.workspace())
        messages = []
        class Pipe:
            def __init__(self): self.commands = [('stage', stage, attempt_id, *([] if end is None else [end])), ('close',)]
            def send(self, message):
                messages.append(message)
                if on_send: on_send(message)
                if message[0] in ('checkpoint', 'unpublishable', 'progress'):
                    self.commands.insert(0, ('ack', True))
            def recv(self): return self.commands.pop(0)
            def close(self): pass
        actual_setup = run.g3
        def setup(c):
            if real_setup:
                import factory_pool
                with patch.object(factory_pool, 'prepare', return_value=True) as prepared, \
                        patch.object(run, 'sh', return_value=SimpleNamespace(stdout='authored-image-id')):
                    result = actual_setup(c)
                    self.assertTrue(prepared.call_args.kwargs['fresh'])
                    return result
            c.card.update(bench_workers_effective=1, factory_slots_prepared=1)
            return True, {'authored': 'external Docker setup'}
        names = ('BENCH', 'COMPOSE', 'seal', 'parallel_calibrators', 'g10_overlap_reason',
                 'public_progress', '_opencode')
        with patch.multiple(run, **{k: getattr(run, k) for k in names}), \
                patch.dict(sys.modules), patch.object(sys, 'path', list(sys.path)), \
                patch.dict(evaluator.os.environ), patch.object(evaluator.os, 'setpgid'), \
                patch.object(run, 'g3', setup), patch.object(run, stage.lower(), action):
            evaluator.child(Pipe(), context, run, ROOT, manifest, versions)
        return context, messages, manifest, versions

    def test_long_lived_child_takes_each_stage_window_from_the_message_not_from_its_fork(self):
        import processes, time
        seen = []
        def gate(context):
            seen.append(processes._deadline.get()); return True, {}
        end = time.monotonic() + 3600
        with processes.deadline(1):  # the stale window the child was forked inside
            self.child_protocol('G14', gate, end=end)
            self.child_protocol('G7', gate)
        self.assertAlmostEqual(seen[0][0], end, delta=1)  # mechanical stage: the parent's window
        self.assertFalse(seen[0][1])  # never independent: the runner's inherited deadline still applies
        self.assertEqual(seen[1], (float('inf'), False))  # non-mechanical stage: no inherited window

    def test_real_g3_prepares_before_a_fresh_checkpoint(self):
        saved = comparison_tests.execution('plain')
        actual = run.g4
        def gate(context):
            self.assertEqual(context.args.bench_workers, 1)
            self.assertEqual(context.card['bench_workers_effective'], 1)
            self.assertGreaterEqual(context.prepared_factory_slots, 1)
            with patch.object(run, 'checkpoint', return_value=(saved['summary'], saved['records'])):
                return actual(context)
        _, messages, _, _ = self.child_protocol('G4', gate, real_setup=True)
        self.assertEqual(messages[-1][0], 'result', messages[-1])

    @unittest.skipUnless(sys.platform == 'linux', 'fork isolation is a Linux worker contract')
    def test_real_g1_g4_g5_in_fork_preserve_parent_globals(self):
        import multiprocessing
        import os
        original = (run.BENCH, list(sys.path), dict(os.environ), extensions.tree(self.case))
        parent, peer = multiprocessing.get_context('fork').Pipe()
        def check():
            try:
                summaries = []
                for stage in ('G1', 'G4', 'G5'):
                    saved = comparison_tests.execution('plain' if stage != 'G5' else 'reference')
                    actual = getattr(run, stage.lower())
                    with patch.object(run, 'checkpoint', return_value=(saved['summary'], saved['records'])):
                        context, messages, _, _ = self.child_protocol(stage, actual)
                    summaries.append(messages[-1][0])
                peer.send((os.getpid(), summaries))
            finally: peer.close()
        process = multiprocessing.get_context('fork').Process(target=check)
        process.start(); peer.close()
        try:
            self.assertTrue(parent.poll(60), 'child did not finish')
            pid, results = parent.recv()
            self.assertNotEqual(pid, os.getpid())
            self.assertEqual(results, ['result'] * 3)
        finally:
            process.join(5)
            if process.is_alive(): process.kill(); process.join()
            parent.close()
        self.assertEqual(process.exitcode, 0)
        self.assertEqual((run.BENCH, list(sys.path), dict(os.environ), extensions.tree(self.case)), original)

    def test_real_g2_child_loop_keeps_live_freshness_unchanged(self):
        import freshness_retrieval
        import test_scientific_receipts as artifacts
        from datetime import datetime, timezone
        http = artifacts.fixture('invalid-runs-http.json.gz')
        rows = [json.loads(line) for line in (self.case / 'freshness.jsonl').read_text().splitlines() if line]
        for row in rows: row.update(at=datetime.now(timezone.utc).isoformat(), hit=False, ambiguous=False)
        rows[0].update(url=http['url'], hit=True)
        (self.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        before = extensions.tree(self.case)
        answer = dict(url=rows[0]['url'], app_version=rows[0]['app_version'],
            resolved=True, retrieved=True, same_bug=False, version_scope='Different pinned behavior',
            why='The saved page describes a different behavior')
        def fetch(url, **kwargs):
            return {'url': url, 'final_url': url, 'status': 200}, http['body'].encode()
        def review(c, chain, text, directory, name, out, *args, **kwargs):
            registry.atomic_json(out, {'hits': [answer]})
        with patch.object(freshness_retrieval, 'fetch', side_effect=fetch), \
                patch.object(run, 'retained_answer', side_effect=review):
            context, messages, manifest, versions = self.child_protocol('G2', run.g2)
        self.assertEqual(messages[-1][0], 'result', messages[-1])
        record = package.Records(context, run, observation_id=manifest['observation_id'],
            round_number=1, expected_versions=versions).load('G2')
        self.assertTrue(record['ok'], record['info'])
        bodies = [context.work / name for name in record['support'] if name.endswith('.body')]
        self.assertTrue(bodies)
        self.assertTrue(all(path.read_bytes() == http['body'].encode() for path in bodies))
        self.assertEqual(extensions.tree(self.case), before)

    def test_child_checkpoint_uses_parent_protocol_and_never_seals(self):
        completed = []
        def model(context, *args, **kwargs):
            self.assertFalse(hasattr(context, 'recipient'))
            if kwargs.get('on_complete'): kwargs['on_complete']()
            return 'authored model transport'
        def gate(context):
            run._opencode(context, [], '', context.case, 'reviewer-1',
                          on_complete=lambda: completed.append(True))
            return True, {'authored': 'G2 transport seam'}
        with patch.object(run, '_opencode', model):
            context, messages, _, _ = self.child_protocol('G2', gate)
        self.assertEqual(completed, [True])
        requests = [m for m in messages if m[0] == 'checkpoint']
        self.assertEqual(len(requests), 1)
        self.assertFalse(requests[0][1]['force'])
        self.assertEqual(messages[-1][0], 'result')
        self.assertFalse(hasattr(context, 'recipient'))

    def test_child_stress_barrier_forces_one_parent_checkpoint(self):
        def gate(context):
            self.assertTrue(context.stress_checkpoint())
            return True, {'authored': 'stress publication seam'}
        _, messages, _, _ = self.child_protocol('G1', gate)
        requests = [m for m in messages if m[0] == 'checkpoint']
        self.assertEqual(len(requests), 1)
        self.assertTrue(requests[0][1]['force'])

    def test_child_owner_drain_signal_is_durable_before_parent_publish(self):
        def gate(context):
            factory_waste.current_attempt().mark_unpublishable('owner_drain_timeout')
            from run_validity import InvalidInfra as lazy_error
            raise lazy_error('authored incomplete owner drain')
        with self.assertRaises(InvalidInfra):
            with factory_waste.attempt(self.c, 'G10', run.case_hash(self.c), comparison=True) as scope:
                def effect(message):
                    if message[0] == 'unpublishable':
                        evaluator.Evaluator.apply_marks(message[1], scope)
                context, messages, _, _ = self.child_protocol('G10', gate,
                    scope.value['attempt_id'], effect)
                stop = messages[-1]
                self.assertEqual(stop[:2], ('stop', 'InvalidInfra'))
                saved = json.loads((context.work / 'attempt-effects' /
                                    (scope.value['attempt_id'] + '.json')).read_text())
                self.assertEqual(saved['unpublishable'], ['owner_drain_timeout'])
                raise InvalidInfra(stop[2])
        self.assertFalse((self.work / 'factory-failures').exists())

    def test_child_case_change_never_publishes_scientific_record(self):
        def gate(context):
            (context.case / 'promise.md').write_text('authored illegal mutation')
            return True, {'authored': 'bad evaluator'}
        context, messages, manifest, versions = self.child_protocol('G1', gate)
        self.assertEqual(messages[-1][:2], ('stop', 'InvalidInfra'))
        records = package.Records(context, run, observation_id=manifest['observation_id'],
                                  round_number=1, expected_versions=versions)
        self.assertIsNone(records.load('G1'))

    def test_real_g1_child_loop_preserves_diagnostics_and_inputs(self):
        actual = run.g1
        before = extensions.tree(self.case)
        context, messages, manifest, versions = self.child_protocol('G1', actual)
        self.assertEqual(messages[-1][0], 'result')
        record = package.Records(context, run, observation_id=manifest['observation_id'],
                                 round_number=1, expected_versions=versions).load('G1')
        self.assertIn('problems', record['info'])
        self.assertEqual(extensions.tree(self.case), before)


class StressComparisonTests(unittest.TestCase):
    # Real category engine, router admission and settlement over the saved ledger;
    # only the external CLI answer and remote publication acknowledgement are authored.
    import test_stream_d_retries as retry_tests
    patch = retry_tests.RetryTests.patch
    cli = retry_tests.RetryTests.cli

    def setUp(self):
        self.retry_tests.RetryTests.setUp(self)
        root = self.work / 'private-phase'
        self.phase = evaluator.phase_context(self.c, root, 1)
        shutil.copytree(self.case, self.phase.case)
        for name in ('logs', 'transcripts'):
            (self.phase.work / name).mkdir(parents=True, exist_ok=True)
        self.patch(run, 'loop_freshness', lambda c, result, report: (result, report))
        self.emit = lambda config, value: None
        def output(c, text, name):
            self.assertTrue(name.startswith('attacker-'), name)
            config = json.loads(text.split('CATEGORY MODE (overrides whole-review completion instructions):\n')[1].split('\n')[0])
            value = dict(category=config['category'], category_complete=True,
                completed_subchecks=config['required_subchecks'], blocking=[], unfinished_validation=[],
                freshness_review=[], cheats_tried=[], non_blocking=[])
            self.emit(config, value)
            Path(config['category_output']).write_text(json.dumps(value))
        self.cli(output)

    def test_real_categories_replay_and_settle_only_in_owner(self):
        before = extensions.tree(self.case)
        with patch.object(run, 'writer_request', side_effect=AssertionError('writer')):
            self.assertTrue(evaluator.stress(self.phase, run, 1)[0])
            calls = len(self.calls)
            self.assertEqual(calls, 4)
            self.assertTrue(evaluator.stress(self.phase, run, 1)[0])
            self.assertEqual(len(self.calls), calls)
        self.assertEqual(extensions.tree(self.case), before)
        self.assertFalse((self.phase.work / 'usage-receipts').exists())
        self.assertTrue(list((self.work / 'usage-receipts').glob('*.json')))
        rows = json.loads(self.c.ledger.read_text())['invocation_reservations']
        self.assertTrue(all(row['state'] == 'settled' for row in rows.values()))

    def test_real_categories_block_and_freshness_routes(self):
        self.emit = lambda config, value: value['blocking'].append('authored concrete blocker')
        ok, detail = evaluator.stress(self.phase, run, 1)
        self.assertFalse(ok)
        self.assertEqual(len(self.calls), 1)
        for stop, expected in [('freshness_public_match', None),
                               ('freshness_unresolved', 'freshness_evidence_unavailable')]:
            with patch.object(run, 'loop_freshness', side_effect=budget.BudgetError(stop)):
                if expected:
                    with self.assertRaisesRegex(budget.BudgetError, '^' + expected + '$'):
                        evaluator.stress(self.phase, run, 1)
                else:
                    ok, detail = evaluator.stress(self.phase, run, 1)
                    self.assertFalse(ok)
                    self.assertTrue(detail['confirmed_public_match'])
        self.assertEqual(len(self.calls), 1)


class DiagnosisBoundaryTests(unittest.TestCase):
    import test_stream_d_inputs as input_tests
    patch = input_tests.InputTests.patch
    install_receipt = input_tests.InputTests.install_receipt

    def setUp(self):
        self.input_tests.InputTests.setUp(self)

    def check_handoff(self, stage):
        import gate_attempt
        c = self.c
        c.card['diagnosis_state'].update(status='completed', outcome='close_to_passing')
        previous_id = c.card['diagnosis_state']['exhaustion_id']
        instance = evaluator.Evaluator.__new__(evaluator.Evaluator)
        instance.c, instance.r, instance.number = c, run, 1
        instance.identity, instance.versions, instance.phase = 'a' * 64, {stage: 'b' * 64}, 'entry'
        instance.row = {phase: {'case_sha256': 'c' * 64} for phase in ('entry', 'outcome')}
        instance.root = self.work / 'comparison-runs/1' / instance.identity
        phase = instance.root / 'entry'
        instance.context = SimpleNamespace(work=phase / 'work')
        instance.context.work.mkdir(parents=True)
        registry.atomic_json(phase / 'manifest.json', {'authored_phase_identity': stage})
        def failed(): raise InvalidInfra('authored dead phase transport')
        outcome = gate_attempt.execute(failed, publish=lambda *a: None,
            record_crash=lambda error: instance.crash(stage, error), interruption=budget.BudgetError,
            attempts=2, journal=instance.context.work / 'infra-attempts.json', identity={'stage': stage})
        self.assertTrue(outcome.crashed)
        label = 'stress_validation_exhausted' if stage == 'stress' else 'infrastructure_exhausted'
        with self.assertRaisesRegex(budget.BudgetError, '^' + label + '$'):
            instance.exhausted(stage)
        # Ordinary main handler fields, followed by the real finalizer and restore seam.
        c.card.update(status='stopped', terminal_stop=label)
        c.stopped = c.exhaustion_occurred = True
        run.finalize_accounting(c)
        self.assertEqual(c.card['diagnosis_state']['status'], 'pending')
        self.assertNotEqual(c.card['diagnosis_state']['exhaustion_id'], previous_id)
        c.checkpoint_card = copy.deepcopy(c.card)
        self.install_receipt()
        manifest = diagnosis.queued_inputs(c, self.bench, quiescent=True)
        selected = {name: sha for name, sha in manifest['files'].items()
                    if name.startswith('work/comparison-diagnostics/')}
        self.assertTrue(any(name.endswith('/infra-attempts.json') for name in selected))
        self.assertEqual(sum('.crash-' in name for name in selected), 2)
        root = self.work / 'diagnosis' / c.card['diagnosis_state']['exhaustion_id'] / 'inputs'
        for name, sha in selected.items():
            self.assertEqual(gate_state.digest(root / name), sha)
        self.assertNotEqual(c.card['terminal_stop'], 'diagnosis_input_invalid')

    def test_gate_exhaustion_finalizes_and_freezes_comparison_diagnostics(self):
        self.check_handoff('G4')

    def test_stress_exhaustion_finalizes_and_freezes_comparison_diagnostics(self):
        self.check_handoff('stress')


class CopyTests(unittest.TestCase):
    def test_real_repository_relative_link_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            c = SimpleNamespace(work=Path(directory), manifest0=run.bench_manifest(ROOT))
            runner = SimpleNamespace(BENCH=ROOT, bench_manifest=run.bench_manifest,
                                     bench_manifest_includes=run.bench_manifest_includes)
            with patch.object(run, 'BENCH', ROOT):
                target = c.work / 'private/bench'
                evaluator.install_bench(c, runner, target)
                self.assertFalse((target / 'CLAUDE.md').is_symlink())
                self.assertEqual((target / 'CLAUDE.md').read_bytes(), (ROOT / 'AGENTS.md').read_bytes())
                self.assertEqual(run.bench_manifest(target), c.manifest0)
                (target / 'AGENTS.md').unlink()
                with self.assertRaises(InvalidInfra): evaluator.install_bench(c, runner, target)

    def test_escaping_link_is_invalid_infrastructure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bad').symlink_to('/etc/hosts')
            with self.assertRaises(InvalidInfra): evaluator.source_files(root, run)


@unittest.skipUnless(sys.platform == 'linux', 'subreaper containment is Linux-only')
class ProcessContainmentTests(unittest.TestCase):
    def test_detached_descendant_is_gone_before_next_phase(self):
        import multiprocessing
        import os
        import subprocess
        import time
        parent, peer = multiprocessing.get_context('fork').Pipe()
        def escaped():
            os.setpgid(0, 0)
            process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                                       start_new_session=True)
            peer.send(process.pid)
            time.sleep(120)
        old = evaluator.subreaper(1)
        process = multiprocessing.get_context('fork').Process(target=escaped)
        process.start(); peer.close()
        instance = evaluator.Evaluator.__new__(evaluator.Evaluator)
        instance.process, instance.pipe, instance.cleanup_pending = process, parent, False
        instance.c = instance.context = SimpleNamespace()
        instance.r = SimpleNamespace(pilot_homes=lambda: [], archive_pilot_state=lambda c: None)
        try:
            self.assertTrue(parent.poll(10))
            escaped_pid = parent.recv()
            instance.close_child()
            self.assertFalse(Path('/proc', str(escaped_pid)).exists())
            self.assertFalse(instance.cleanup_pending)
            self.assertIsNone(instance.process)
        finally:
            if process.is_alive(): process.kill(); process.join()
            evaluator.subreaper(old)


from types import SimpleNamespace
if __name__ == '__main__': unittest.main()

