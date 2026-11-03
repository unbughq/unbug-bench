"""Admitted execution over saved practice bytes and the 5813be ledger.

Model/gate outputs are authored; admission, receipts, reservations and loop run
for real. No live CLI, qualification, or Murphy closure is claimed.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import durable_checkpoint
import extensions
import model_runtime
import model_router
from run_validity import InfrastructureExhausted
import registry
import run
REAL_G1 = run.g1
import test_stream_d_extensions as states
import test_stream_d_runtime as runtime


class ExecutionTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    snapshot = states.ExtensionTests.snapshot
    diagnosis = states.ExtensionTests.diagnosis

    def setUp(self):
        runtime.RuntimeTests.setUp(self)
        self.c.card['builder_rounds'] = 8
        self.c.args.rounds = 8
        self.c.args.resume = self.c.case_id
        self.c.recipient = 'synthetic-only'
        self.diagnosis()
        self.proposal = extensions.propose(self.c, self.snapshot(1))
        self.intent = runtime.RuntimeTests.receipt(self)
        self.intent.update(round=9, round_limit=9, report='round-9.json', binding=run.attack_binding(self.c))
        # Retain real admission, then interrupt before model invocation.
        with patch.object(run, 'opencode', side_effect=runtime.Killed):
            with self.assertRaises(runtime.Killed):
                run.pending_call(self.c, self.c.models['builder'], 'authored extension', self.case,
                    'builder-9', self.intent, role='writer', on_complete=lambda: None,
                    extension_proposal=self.proposal)
        self.row = extensions.active(self.c)
        self.prev = {'failed_gate': 'G8', 'failed_detail': {'authored': 'origin'},
                     'models_used': {'attacker-8': 'old'}}
        self.calls = []
        self.kill = None
        self.failure = None
        self.findings = []
        def invoke(rt, c, models, text, cwd, name, **kwargs):
            c.model_process_state['started'] = True
            self.calls.append(name)
            if name == self.kill: raise runtime.Killed()
            if self.failure == ('writer', name):
                raise budget.BudgetError('provider_limit:' + c.model_lease.route,
                    provider_failure={'reason': 'quota', 'scope': 'account', 'model': c.model_lease.route})
            if self.failure == ('stress', name):
                raise InfrastructureExhausted('authored stress transport exhaustion')
            if name == 'builder-9': (self.case / 'draft.txt').write_text('authored changed draft')
            elif name == 'attacker-9':
                (self.work / 'attacks/round-9.json').write_text(json.dumps({
                    'complete': True, 'blocking': self.findings}))
            else: self.fail('unexpected work: ' + name)
            return 0
        self.patch(model_runtime.ModelRuntime, '_invoke', invoke)
        self.patch(durable_checkpoint, 'checkpoint_progress', lambda *a, **k: None)
        self.patch(run, 'prompt', lambda role, text: text)
        self.patch(run, 'run_context', lambda c, **kw: json.dumps(kw))
        self.g1 = self.patch(run, 'g1', return_value=(True, {'problems': []}))
        self.early = self.patch(run, 'early_checks', return_value=None)
        self.fresh = self.patch(run, 'loop_freshness', side_effect=lambda c, result, report: (result, report))
        for name in ('early_review', 'statement_precheck', 'reselect_candidate', 'validate_and_repair'):
            self.patch(run, name, side_effect=AssertionError('forbidden: ' + name))

    def execute(self):
        self.c.provider_resume_done = False
        self.c.model_resume_state = {'done': False}
        return run.write_and_attack(self.c, self.prev, extension_id=self.row['extension_id'])

    def saved(self):
        return json.loads((self.work / 'attack-state.json').read_text())

    def terminal_replays(self, label):
        before = (self.work / 'attack-state.json').read_bytes()
        calls = list(self.calls)
        self.g1.side_effect = self.early.side_effect = self.fresh.side_effect = AssertionError('terminal replay work')
        self.c.card.pop('stress_review', None)  # simulate lagging card after receipt publication
        for _ in range(2):
            with self.assertRaisesRegex(budget.BudgetError, '^' + label + '$'): self.execute()
            self.assertEqual((self.work / 'attack-state.json').read_bytes(), before)
        self.assertEqual(self.calls, calls)

    def test_pending_above_cap_missing_case_skips_prototype_and_finishes_once(self):
        (self.case / 'case.json').unlink(missing_ok=True)
        self.execute()
        self.assertEqual(self.calls, ['builder-9', 'attacker-9'])
        self.assertEqual(self.c.args.rounds, 8)
        self.assertEqual(self.c.card['builder_rounds'], 9)
        self.assertEqual(self.saved()['next_phase'], 'extension_comparison')
        self.assertEqual(len(extensions.read(self.c)), 1)
        self.terminal_replays('extension_comparison_pending')

    def test_completed_writer_validation_hash_and_no_second_writer(self):
        (self.case / 'draft.txt').write_text('completed before kill')
        receipt = self.saved()
        run.complete_writer(self.c, receipt, self.work / 'attack-state.json')
        observed = []
        categories = run.stress_categories
        def before_stress(*args):
            writer = self.saved()
            observed.append(writer)
            self.assertEqual(writer['binding_sha256'], hashlib.sha256(
                json.dumps(writer['binding'], sort_keys=True).encode()).hexdigest())
            self.assertEqual(extensions.writer_receipt(self.c), writer)
            return categories(*args)
        with patch.object(run, 'stress_categories', side_effect=before_stress): self.execute()
        self.assertEqual(self.calls, ['attacker-9'])
        self.assertEqual(len(observed), 1)
        self.terminal_replays('extension_comparison_pending')

    def test_validated_writer_failure_is_exhausted_without_stress(self):
        (self.case / 'draft.txt').write_text('completed invalid draft')
        receipt = self.saved()
        run.complete_writer(self.c, receipt, self.work / 'attack-state.json')
        self.g1.return_value = (False, {'problems': ['authored invalid case']})
        with self.assertRaisesRegex(budget.BudgetError, 'stress_review_unresolved:rounds_exhausted'): self.execute()
        self.assertEqual(self.calls, [])
        self.assertTrue(self.saved()['exhausted'])
        self.terminal_replays('stress_review_unresolved:rounds_exhausted')

    def test_stress_findings_exhaust_one_round_and_never_start_another(self):
        self.findings = ['authored blocking defect']
        with self.assertRaisesRegex(budget.BudgetError, 'stress_review_unresolved:rounds_exhausted'): self.execute()
        self.assertEqual(self.calls, ['builder-9', 'attacker-9'])
        self.terminal_replays('stress_review_unresolved:rounds_exhausted')

    def test_pending_stress_from_gate_failure_resumes_without_writer(self):
        self.kill = 'attacker-9'
        with self.assertRaises(runtime.Killed): self.execute()
        self.assertEqual(self.saved()['actor'], 'stress_tester')
        self.kill = None
        self.execute()
        self.assertEqual(self.calls, ['builder-9', 'attacker-9', 'attacker-9'])
        self.terminal_replays('extension_comparison_pending')

    def test_pending_writer_keeps_immutable_intent_on_retry(self):
        original = self.saved()
        self.kill = 'builder-9'
        with self.assertRaises(runtime.Killed): self.execute()
        frozen = lambda r: {k: v for k, v in r.items() if k not in extensions._WRITER_MUTABLE}
        self.assertEqual(frozen(self.saved()), frozen(original))
        self.assertEqual(extensions.writer_receipt(self.c), self.saved())
        self.kill = None
        self.execute()
        self.assertEqual(self.calls, ['builder-9', 'builder-9', 'attacker-9'])

    def test_writer_provider_wait_resumes_same_intent_through_loop(self):
        original = self.saved()
        frozen = lambda r: {k: v for k, v in r.items() if k not in extensions._WRITER_MUTABLE}
        history = (self.work / 'extension-history.json').read_bytes()
        self.failure = ('writer', 'builder-9')
        with self.assertRaises(model_router.ProviderWait) as caught: self.execute()
        self.assertEqual(str(caught.exception), 'provider_wait')
        run.write_provider_wait(self.c, caught.exception)
        self.assertEqual(self.c.card['terminal_stop'], 'provider_wait')
        self.assertEqual(self.calls, ['builder-9'])
        self.c.provider_resume_done = False
        self.c.model_resume_state['done'] = False
        run.resume_provider_wait(self.c)
        resumed = self.saved()
        self.assertIsNone(resumed['lease_id'])
        self.assertIsNone(resumed['invocation_id'])
        self.assertTrue(run.provider_continuation(self.c, resumed, 'writer'))
        self.assertEqual(frozen(resumed), frozen(original))
        self.failure = None
        categories = run.stress_categories
        def before_stress(*args):
            completed = self.saved()
            self.assertEqual(frozen(completed), frozen(original))
            self.assertEqual(completed['operation_id'], self.row['writer_operation_id'])
            self.assertNotEqual(completed['lease_id'], original['lease_id'])
            return categories(*args)
        with patch.object(run, 'stress_categories', side_effect=before_stress): self.execute()
        self.assertEqual(self.calls, ['builder-9', 'builder-9', 'attacker-9'])
        self.assertEqual((self.work / 'extension-history.json').read_bytes(), history)
        self.assertEqual(self.saved()['next_phase'], 'extension_comparison')
        self.terminal_replays('extension_comparison_pending')

    def test_stress_infrastructure_exhaustion_resumes_only_stress(self):
        self.failure = ('stress', 'attacker-9')
        with self.assertRaises(InfrastructureExhausted) as caught: self.execute()
        # main maps this exact exception type to infrastructure_exhausted; it is
        # not a BudgetError or a scientific stress finding.
        self.assertNotIsInstance(caught.exception, budget.BudgetError)
        interrupted = self.saved()
        self.assertEqual((interrupted['actor'], interrupted['phase']), ('stress_tester', 'pending'))
        self.assertNotIn('exhausted', interrupted)
        self.assertNotEqual(self.c.card.get('stress_review', {}).get('status'), 'completed')
        self.failure = None
        self.execute()
        self.assertEqual(self.calls, ['builder-9', 'attacker-9', 'attacker-9'])
        self.assertEqual(self.saved()['operation_id'], interrupted['operation_id'])
        self.assertEqual(self.saved()['next_phase'], 'extension_comparison')
        self.terminal_replays('extension_comparison_pending')

    def test_invalid_round_limit_refuses_before_execution(self):
        receipt = self.saved(); receipt['round_limit'] = 8
        registry.atomic_json(self.work / 'attack-state.json', receipt)
        with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'): self.execute()
        self.assertEqual(self.calls, [])

    def test_stale_authority_refuses_before_execution(self):
        self.c.job_money['source_generation'] = 'f' * 64
        with self.assertRaises(budget.BudgetError): self.execute()
        self.assertEqual(self.calls, [])

    def test_terminal_report_tamper_refuses_without_reroll(self):
        self.execute()
        (self.work / 'attacks/round-9.json').write_text('{}')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_reservation_mismatch$'): self.execute()
        self.assertEqual(self.calls, ['builder-9', 'attacker-9'])


class PackageRecordTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    snapshot = states.ExtensionTests.snapshot
    diagnosis = states.ExtensionTests.diagnosis
    execute = ExecutionTests.execute
    saved = ExecutionTests.saved

    def setUp(self):
        ExecutionTests.setUp(self)
        (self.work / 'logs').mkdir(exist_ok=True)

    def records(self):
        import extension_package
        return extension_package.Records(self.c, run, self.row)

    def test_record_replays_fail_and_retains_real_case_inputs(self):
        records = self.records()
        calls = []
        def invoke():
            calls.append('G1')
            return False, {'problems': ['authored failure']}
        records.capture(self.c, 'G1', invoke)
        for _ in range(2):
            self.assertEqual(records.replay(self.c, 'G1')[0], False)
        self.assertEqual(calls, ['G1'])
        data = records.load('G1')
        self.assertTrue(any('/case/' in p for p in data['support']))
        source = next(self.work / p for p in data['support'] if '/case/' in p)
        source.write_text('corrupt')
        with self.assertRaisesRegex(budget.BudgetError, 'extension_snapshot_changed'):
            records.replay(self.c, 'G1')

    def test_real_g1_retains_practice_contract_result(self):
        # Run the actual contract and local git patch checks over saved practice
        # files. The practice specimen can fail today's full contract; its real
        # diagnostics, not an invented pass, must be retained and replayed.
        self.c.manifest0 = run.bench_manifest()
        records = self.records()
        result = records.capture(self.c, 'G1', lambda: REAL_G1(self.c))
        self.assertEqual(result[1]['content_checks'], 'on')
        self.assertGreater(self.c.card['counts']['scenarios'], 0)
        self.assertEqual(records.replay(self.c, 'G1'), result)
        data = records.load('G1')
        for name in ('case.json', 'base/app.patch', 'promise.md'):
            retained = next(self.work / p for p in data['support'] if p.endswith('/case/' + name))
            self.assertEqual(retained.read_bytes(), (self.case / name).read_bytes())

    def test_real_g2_retains_freshness_confirmation_and_response_bytes(self):
        import freshness_retrieval
        import test_scientific_receipts as artifacts
        http = artifacts.fixture('invalid-runs-http.json.gz')
        self.assertEqual(hashlib.sha256(http['body'].encode()).hexdigest(), http['sha256'])
        rows = [json.loads(line) for line in (self.case / 'freshness.jsonl').read_text().splitlines() if line]
        for row in rows:
            row.update(at=datetime.now(timezone.utc).isoformat(), hit=False, ambiguous=False)
        rows[0].update(url=http['url'], hit=True)
        (self.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        # Saved HTTP bytes drive the real retrieval and confirmation validators.
        # The model's exclusion answer is authored, as in the G2 fixture tests;
        # it is not a claim of live review or live qualification.
        answer = dict(url=rows[0]['url'], app_version=rows[0]['app_version'],
                      resolved=True, retrieved=True, same_bug=False,
                      version_scope='Different behavior in the pinned practice release',
                      why='The retrieved page describes a different behavior')
        def fetch(url, **kwargs):
            return {'url': url, 'final_url': url, 'status': 200}, http['body'].encode()
        def review(c, chain, text, directory, name, out, *args, **kwargs):
            registry.atomic_json(out, {'hits': [answer]})
        with patch.object(freshness_retrieval, 'fetch', side_effect=fetch), \
                patch.object(run, 'retained_answer', side_effect=review) as reviewer:
            records = self.records()
            result = records.capture(self.c, 'G2', lambda: run.g2(self.c))
        self.assertTrue(result[0], result)
        self.assertEqual(result[1]['flagged_hits'], 1)
        reviewer.assert_called_once()
        data = records.load('G2')
        names = list(data['support'])
        for suffix in ('/public-search.json', '/freshness-verdict.json',
                       '/verdict.json', '/review-completed.json', '/retrieval/receipts.json'):
            self.assertTrue(any(name.endswith(suffix) for name in names), suffix)
        bodies = [self.work / name for name in names if name.endswith('.body')]
        self.assertTrue(bodies)
        self.assertTrue(all(path.read_bytes() == http['body'].encode() for path in bodies))
        self.assertTrue(any('/confirmation-retrieval-' in name for name in names))
        with patch.object(run, 'retained_answer', side_effect=AssertionError('fresh confirmation')), \
                patch.object(freshness_retrieval, 'fetch', side_effect=AssertionError('fresh fetch')):
            self.assertEqual(records.replay(self.c, 'G2'), result)

    def test_stage_support_roots_and_calibration_filter(self):
        import gate_state
        import test_scientific_receipts as artifacts
        # Authored VM layout populated with saved execution/HTTP/practice bytes.
        # Expected roots are independent of Records.sources, so deleting a root
        # or broadening a calibration filter breaks this test.
        calibrations = ('strong_calibrator', 'easy_calibrator', 'early_probe',
                        'judge_breadth', 'fairness-replacement-saved')
        files = {}
        execution = json.dumps(artifacts.execution('reference')).encode()
        for root in calibrations:
            for tail in ('results.json', 'try-1/execution.json', 'try-1/guard/db.sql',
                         'try-1/workspace/private.txt', 'try-1/prompt.txt'):
                files[root + '/' + tail] = artifacts.REAL['suffix-case']['files']['guards/reference/db.sql'].encode() if tail.endswith('.sql') else execution
        for name in ('g11-evidence/checked.json', 'fairness-g16-inputs/attempt.json',
                     'fairness-g17-inputs/attempt.json', 'public-search.json',
                     'freshness-verdict.json', 'g2-confirm-123/verdict.json',
                     'confirmation-retrieval-saved/0-0.body', 'attacks/round-9.json',
                     'stress-saved/report.json', 'pilot/secret.txt',
                     'pilot-strong/secret.txt', 'pilot-easy/secret.txt'):
            files[name] = execution
        for name in ('strong-calibrator-strong_calibrator-1.jsonl',
                     'easy-calibrator-easy_calibrator-1.jsonl', 'attacker-9.jsonl', 'unrelated.jsonl'):
            files['transcripts/' + name] = execution
        for name, content in files.items():
            path = self.work / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
        expected_roots = {
            'G10': ('strong_calibrator', 'easy_calibrator', 'early_probe'),
            'G11': ('strong_calibrator', 'easy_calibrator', 'early_probe', 'g11-evidence'),
            'G16': ('judge_breadth', 'fairness-g16-inputs', 'fairness-replacement-saved'),
            'G17': ('strong_calibrator', 'fairness-g17-inputs', 'fairness-replacement-saved'),
            'G2': ('public-search.json', 'freshness-verdict.json', 'g2-confirm-123', 'confirmation-retrieval-saved'),
            'stress': ('attack-state.json', 'attacks', 'stress-saved', 'freshness-verdict.json',
                       'g2-confirm-123', 'confirmation-retrieval-saved')}
        records = self.records()
        before = {key: gate_state.digest(path) for key, path in gate_state.inventory(self.c, run.BENCH).items()}
        for stage, roots in expected_roots.items():
            with self.subTest(stage=stage):
                records.save(stage, True, {'authored': 'artifact-selection-only'}, before, {})
                data = records.load(stage)
                prefix = f'extension-package/{self.row["extension_id"]}/{stage}/support/work/'
                actual = {name.removeprefix(prefix) for name in data['support'] if name.startswith(prefix)}
                expected = {name for name in files if name.split('/')[0] in roots
                            and (name.split('/')[0] not in calibrations or
                                 Path(name).name in ('results.json', 'execution.json') or '/guard/' in name)}
                if stage == 'stress': expected.add('attack-state.json')
                if stage in ('G10', 'G11', 'G16', 'G17', 'stress'):
                    expected.update(name for name in files if name.startswith('transcripts/') and not name.endswith('unrelated.jsonl'))
                self.assertEqual(actual, expected)
                for name in actual:
                    self.assertEqual((self.work / (prefix + name)).read_bytes(), (self.work / name).read_bytes())
                self.assertFalse(any('pilot' in name.split('/')[0] for name in actual))

    def test_early_projection_excludes_plumbing_and_preserves_owner(self):
        records = self.records()
        self.c.card.update(plain_app_broke=True, reference_fix=True, scenario_keys_match=True,
                           owner_contract={'authored': 'owner'}, cleanup_errors=['new'],
                           durable_checkpoint={'remote_durable': True}, calibration_interruptions={'strong': 2})
        for gate in ('G4', 'G5'):
            records.capture(self.c, gate, lambda: (True, {'reused_from_early_check': True}))
        expected = {k: copy.deepcopy(self.c.card[k]) for k in
                    ('plain_app_broke', 'reference_fix', 'scenario_keys_match', 'owner_contract')}
        self.c.card = {'cleanup_errors': ['later'], 'durable_checkpoint': {'remote_durable': False},
                       'calibration_interruptions': {'strong': 3}, 'roles': self.c.card['roles']}
        for gate in ('G4', 'G5'):
            data = records.load(gate)
            self.assertFalse({'cleanup_errors', 'durable_checkpoint', 'calibration_interruptions'} & data['card'].keys())
            records.replay(self.c, gate)
        self.assertEqual({k: self.c.card[k] for k in expected}, expected)
        self.assertEqual(self.c.card['cleanup_errors'], ['later'])
        self.assertEqual(self.c.card['durable_checkpoint'], {'remote_durable': False})
        self.assertEqual(self.c.card['calibration_interruptions'], {'strong': 3})

    def test_valid_record_bypasses_exhausted_retry_journal(self):
        records = self.records()
        records.capture(self.c, 'G1', lambda: (False, {'problems': ['retained']}))
        journal = self.work / 'infra-attempts.json'
        journal.write_text('{"authored": {"running": true, "invalid_attempts": 1}}')
        before = journal.read_bytes()
        self.c.card['gates'] = {}; self.c.stopped = False
        pipeline = run._gate_pipeline()
        pipeline.gates = ('G1',)
        pipeline.budget_boundary = pipeline.after_gate = lambda *a: None
        pipeline.publish = pipeline.log = lambda *a: None
        pipeline.evaluate = lambda *a: self.fail('replayed execution')
        with patch('gate_attempt.execute', side_effect=AssertionError('retry journal consulted')):
            pipeline.run(self.c, replay_gate=records.replay, around_gate=records.capture)
        self.assertEqual(journal.read_bytes(), before)
        self.assertEqual(self.c.card['failed_gate'], 'G1')

    def test_real_g3_reduced_workers_replay_and_further_reduction(self):
        import bench
        import factory_pool
        from types import SimpleNamespace
        records = self.records()
        self.c.args.bench_workers = 2
        with patch.object(bench, 'load_scenario', return_value={}), patch.object(bench, 'factory_memory_fits', return_value=False), \
                patch.object(factory_pool, 'prepare', return_value=True) as prepare, \
                patch.object(run, 'sh', return_value=SimpleNamespace(stdout='authored-image')):
            records.capture(self.c, 'G3', lambda: run.g3(self.c))
            self.assertEqual(self.c.args.bench_workers, 1)
            self.c.args.bench_workers = 2
            self.assertIsNone(records.replay(self.c, 'G3'))
            self.assertEqual(self.c.args.bench_workers, 1)
            records.capture(self.c, 'G3', lambda: run.g3(self.c))
            self.assertEqual(prepare.call_count, 2)
            records.completed = True
            self.c.args.bench_workers = 2
            records.replay(self.c, 'G3')
            self.assertEqual(self.c.args.bench_workers, 1)
            self.assertEqual(prepare.call_count, 2)

    def test_real_g3_new_smaller_vm_refuses_without_rewriting_record(self):
        import bench
        import factory_pool
        from types import SimpleNamespace
        records = self.records()
        self.c.args.bench_workers = 2
        with patch.object(bench, 'load_scenario', return_value={}), patch.object(bench, 'factory_memory_fits', return_value=True) as memory, \
                patch.object(factory_pool, 'prepare', return_value=True), \
                patch.object(run, 'sh', return_value=SimpleNamespace(stdout='authored-image')):
            records.capture(self.c, 'G3', lambda: run.g3(self.c))
            path = records.root / 'G3/record.json'; original = path.read_bytes()
            memory.return_value = False
            self.assertIsNone(records.replay(self.c, 'G3'))
            with self.assertRaisesRegex(budget.BudgetError, 'extension_comparison_pending'):
                records.capture(self.c, 'G3', lambda: run.g3(self.c))
            self.assertEqual(path.read_bytes(), original)

    def test_retry_after_record_commit_does_not_repeat_evaluation(self):
        records = self.records()
        invoke = self.patch(run, 'g7', return_value=(True, {'authored': 'passed'}))
        original = extensions._sync_directory
        failed = False
        def sync(path):
            nonlocal failed
            if (records.root / 'G7/record.json').exists() and not failed:
                failed = True
                raise OSError('authored directory sync failure after rename')
            return original(path)
        with patch.object(extensions, '_sync_directory', side_effect=sync):
            with self.assertRaises(OSError): records.capture(self.c, 'G7', lambda: run.g7(self.c))
        records.capture(self.c, 'G7', lambda: run.g7(self.c))
        invoke.assert_called_once()


    def test_real_gate_pipeline_copies_saved_bench_and_detail_proofs(self):
        import test_scientific_receipts as artifacts
        import gate_state
        bench = self.work / 'bench'; (bench / 'results').mkdir(parents=True)
        (self.case / 'case.json').write_text(json.dumps(artifacts.REAL['suffix-case']['files']['case.json']))
        with patch.object(run, 'BENCH', bench):
            records = self.records()
            pipeline = run._gate_pipeline()
            for gate, label in (('G4', 'plain'), ('G5', 'reference')):
                saved = artifacts.execution(label)
                def checkpoint(*a, **kw):
                    registry.atomic_json(bench / 'results' / (gate + '.json'), saved)
                    return saved['summary'], saved['records']
                with patch.object(run, 'checkpoint', side_effect=checkpoint):
                    records.capture(self.c, gate, lambda: pipeline.check(self.c, gate))
                data = records.load(gate)
                self.assertTrue(any('/bench/' in name for name in data['support']))
                if gate == 'G5':
                    self.assertTrue(any('/gate-details/G5.json' in name for name in data['support']))
                with patch.object(pipeline, 'evaluate', side_effect=AssertionError('record reroll')):
                    self.assertEqual(records.replay(self.c, gate), (data['ok'], data['info']))
            self.assertIsNotNone(gate_state.load(self.c, 'G4', bench))



class PackageTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    snapshot = states.ExtensionTests.snapshot
    diagnosis = states.ExtensionTests.diagnosis
    execute = ExecutionTests.execute
    saved = ExecutionTests.saved
    setUp = PackageRecordTests.setUp

    def pipeline(self):
        import gate_state
        import extension_package
        self.executed = []
        self.crash_after = None
        self.reject = None
        self.c.stopped = False
        # These tests exercise orchestration with authored scientific versions;
        # PackageRecordTests exercises real versioning and G3 over practice bytes.
        self.patch(gate_state, 'scientific_version', side_effect=lambda c, stage, bench: hashlib.sha256(stage.encode()).hexdigest())
        self.patch(gate_state, 'inputs', side_effect=lambda c, gate, bench: {'stage': gate, 'case': run.case_hash(c)})
        pipeline = run._gate_pipeline()
        pipeline.budget_boundary = lambda c: None
        pipeline.publish = pipeline.log = lambda *a: None
        def evaluate(c, gate):
            self.executed.append(gate)
            if gate == 'G3':
                c.card['bench_workers_effective'] = c.args.bench_workers
                c.card['factory_slots_prepared'] = 1
                c.prepared_factory_slots = 1
            if gate == 'G10': c.card['owner_contract'] = {'authored': 'exam-owner'}
            directory = c.work / 'gate-details'; directory.mkdir(exist_ok=True)
            registry.atomic_json(directory / (gate + '.json'), {'authored': gate})
            return gate != self.reject, {'authored': gate}
        pipeline.evaluate = evaluate
        def after(c, gate, ok, quiescent):
            if gate == self.crash_after: raise runtime.Killed()
        pipeline.after_gate = after
        self.patch(run, '_gate_pipeline', return_value=pipeline)
        self.package = lambda: extension_package.run(self.c, run, self.prev, 1)

    def test_package_kill_after_g10_replays_without_second_stochastic_gate(self):
        self.pipeline()
        self.crash_after = 'G10'
        with self.assertRaises(runtime.Killed): self.package()
        calls, gates = list(self.calls), list(self.executed)
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        self.crash_after = None
        self.c.card.pop('owner_contract')
        self.package()
        self.assertEqual(self.calls, calls)
        self.assertEqual(self.executed, gates + ['G3', 'G17', 'G11'])
        self.assertEqual(self.c.card['owner_contract'], {'authored': 'exam-owner'})
        outcome = copy.deepcopy(extensions.read(self.c)[-1]['outcome'])
        import extension_package
        models = self.c.models
        del self.c.models
        extension_package.completed_route(self.c, extensions.read(self.c)[-1])
        self.c.models = models
        import extension_compare
        with patch.object(extension_compare, 'snapshot', side_effect=AssertionError('recreated outcome')), \
                patch.object(extensions, 'complete', side_effect=AssertionError('recompleted outcome')):
            self.c.factory_slot = 9
            self.c.card.update(failed_gate='G4', terminal_stop='seal_error:authored')
            self.package()
        self.assertEqual(extensions.read(self.c)[-1]['outcome'], outcome)
        self.assertNotIn('failed_gate', self.c.card)
        self.assertEqual(self.calls, calls)
        self.assertEqual(self.executed, gates + ['G3', 'G17', 'G11'])

    def test_dispatch_recovers_history_committed_before_card(self):
        import diagnosis_dispatch
        self.pipeline()
        lagging = copy.deepcopy(self.c.card['extension_history'])
        self.package()
        self.assertIsNotNone(extensions.read(self.c)[-1]['outcome'])
        self.c.card['extension_history'] = lagging
        self.assertIsNone(self.c.card['extension_history'][-1]['outcome_sha256'])
        manifest = {'exhaustion_id': self.row['exhaustion_id']}
        with runtime.diagnosis_policy(self.c), \
                patch.object(extensions, 'writer_receipt', side_effect=AssertionError('completed row is not writer work')):
            result = diagnosis_dispatch.apply(self.c, self.work, manifest,
                                             {'outcome': 'close_to_passing'}, resume=True)
        self.assertEqual(result, self.row['extension_id'])
        self.c.card['diagnosis_state']['exhaustion_id'] = 'different-exhaustion'
        with runtime.diagnosis_policy(self.c), \
                patch.object(extensions, 'writer_receipt', side_effect=AssertionError('old writer work')):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_comparison_pending$'):
                diagnosis_dispatch.apply(self.c, self.work, {'exhaustion_id': 'different-exhaustion'},
                                         {'outcome': 'close_to_passing'}, resume=True)

    def test_package_failure_completes_and_queues_one_diagnosis(self):
        self.pipeline(); self.reject = 'G10'
        with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): self.package()
        self.assertNotIn('G17', self.executed)
        self.assertIsNotNone(extensions.read(self.c)[-1]['outcome'])
        self.c.stopped = True
        self.c.exhaustion_occurred = True
        self.c.card['terminal_stop'] = 'extension_incomplete'
        run.finalize_accounting(self.c)
        state = copy.deepcopy(self.c.card['diagnosis_state'])
        self.assertEqual(state['status'], 'pending')
        calls, gates = list(self.calls), list(self.executed)
        # Completed replay is accounting-free, including an exhausted commitment.
        self.c.card['failed_gate'] = 'G1'
        with patch.object(run, 'case_budget_boundary', side_effect=budget.BudgetError('money_wait')):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): self.package()
        self.c.card['terminal_stop'] = 'extension_incomplete'
        run.finalize_accounting(self.c)
        self.assertEqual(self.c.card['diagnosis_state'], state)
        self.assertEqual(self.calls, calls); self.assertEqual(self.executed, gates)

    def test_stress_handoff_before_first_record_ignores_restored_worker_count(self):
        self.pipeline()
        self.c.args.bench_workers = 1
        self.execute()  # terminal stress checkpoint, before package record publication
        calls = list(self.calls)
        self.c.args.bench_workers = 2
        self.package()
        self.assertEqual(self.calls, calls)
        self.assertIsNotNone(extensions.read(self.c)[-1]['outcome'])


    def test_stress_failure_completes_without_gates(self):
        self.pipeline(); self.findings = ['authored blocking defect']
        with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): self.package()
        outcome = extensions.read(self.c)[-1]['outcome']
        self.assertEqual(outcome['stages'][0]['status'], 'fail')
        self.assertEqual(self.executed, [])
        with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): self.package()
        self.assertEqual(self.calls, ['builder-9', 'attacker-9'])

    def test_infrastructure_gate_keeps_original_stop_and_open_history(self):
        self.pipeline()
        pipeline = run._gate_pipeline()
        evaluate = pipeline.evaluate
        pipeline.evaluate = lambda c, gate: (_ for _ in ()).throw(InfrastructureExhausted('authored outage')) if gate == 'G2' else evaluate(c, gate)
        self.package()
        self.assertTrue(self.c.stopped)
        self.assertEqual(self.c.card['terminal_stop'], 'infrastructure_exhausted')
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])



if __name__ == '__main__': unittest.main()

