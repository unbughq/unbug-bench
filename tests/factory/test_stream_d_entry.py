"""First-entry proof over saved practice/checkpoint/HTTP bytes, no live workers.

Gate pass controls and external stress/reviewer outputs are authored. G1, G4/G5,
G16, receipt validators and admission execute for real as named in each test.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import extension_package as package
import extensions
import gate_state
import registry
import run
import test_scientific_receipts as artifacts
import test_stream_d_runtime as runtime
import test_stream_d_extensions as states
from test_extension_compare import cached_source_inputs
from run_validity import InfrastructureExhausted


class EntryTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    diagnosis = states.ExtensionTests.diagnosis

    def setUp(self):
        runtime.RuntimeTests.setUp(self)
        self.c.card.update(builder_rounds=8, gates={})
        self.c.stopped = False
        self.c.args.rounds = 8
        self.c.args.no_early_probe = True
        self.c.args.bench_workers = 1
        (self.work / 'logs').mkdir()
        self.c.authenticated_batch_manifest['diagnosis_policy'] = dict(schema=1, enabled=True)
        # Version hashing remains real, cached only by identical source bytes.
        self.patch(gate_state, 'source_inputs', cached_source_inputs)
        self.pipeline = run._gate_pipeline()
        self.pipeline.publish = self.pipeline.log = lambda *a: None
        self.pipeline.budget_boundary = self.pipeline.after_gate = lambda *a: None
        self.patch(run, '_gate_pipeline', return_value=self.pipeline)
        self.patch(run.model_runtime, 'prepare_dispatch', lambda c: None)
        self.executed = []
        self.failure = 'G5'
        self.crash = None
        def check(c, stage):
            self.executed.append(stage)
            if stage == self.crash: raise budget.BudgetError('money_wait')
            if stage == 'G3':
                c.args.bench_workers = 1
                c.card['bench_workers_effective'] = 1
            return stage != self.failure, {'authored_stage_control': stage}
        self.pipeline.check = check
        self.stress()

    def stress(self):
        # Authored completed external stress answer; real binding/digest reader.
        report = self.work / 'attacks/round-8.json'; report.parent.mkdir(exist_ok=True)
        registry.atomic_json(report, {'complete': True, 'blocking': []})
        binding = run.attack_binding(self.c)
        receipt = dict(round=8, report=report.name, actor='stress_tester', phase='validated',
                       binding=binding, review_attempt=str(uuid.uuid4()), review_pending=False,
                       repair_pending=False, next_phase='gates')
        receipt['review_completed'] = dict(attempt=receipt['review_attempt'],
            binding=hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest(),
            report_sha256=gate_state.digest(report))
        registry.atomic_json(self.work / 'attack-state.json', receipt)

    def records(self):
        pointer = json.loads((self.work / 'entry-records/current.json').read_text())
        return package.Records(self.c, run, observation_id=pointer['observation_id'], round_number=pointer['round_number'])

    def pending(self):
        with self.assertRaisesRegex(budget.BudgetError, '^extension_comparison_pending$'):
            package.entry(self.c, run)

    def test_capture_entry_and_real_proposal_without_evaluation(self):
        run.run_gates(self.c)
        calls = list(self.executed)
        original = copy.deepcopy((vars(self.c.args), self.c.card, self.c.models))
        self.pipeline.check = lambda *a: self.fail('entry reran a gate')
        snapshot = package.entry(self.c, run)
        self.assertEqual(snapshot, package.entry(self.c, run))
        self.assertEqual(self.executed, calls)
        self.assertEqual((vars(self.c.args), self.c.card, self.c.models), original)
        rows = {row['stage']: row['status'] for row in snapshot['stages']}
        self.assertEqual(rows['stress'], 'pass'); self.assertEqual(rows['G5'], 'fail')
        self.assertEqual(rows['G6'], 'unreached')
        self.diagnosis()
        proposal = extensions.propose(self.c, snapshot)
        extensions.verify_proposal(self.c, proposal)
        self.assertEqual(proposal['extension_id'], 1)
        self.assertFalse((self.work / 'extension-history.json').exists())

    def test_real_g1_contract_diagnostics_are_recorded(self):
        self.c.manifest0 = run.bench_manifest()
        self.pipeline.check = lambda c, stage: run.g1(c) if stage == 'G1' else (False, {'authored_stage_control': stage})
        run.run_gates(self.c)
        record = self.records().load('G1')
        self.assertEqual(record['info']['content_checks'], 'on')
        self.assertGreater(record['card']['counts']['scenarios'], 0)
        self.assertTrue(any(name.endswith('/case/base/app.patch') for name in record['support']))

    def test_real_g4_g5_saved_executions_and_rejection(self):
        (self.case / 'case.json').write_text(json.dumps(artifacts.REAL['suffix-case']['files']['case.json']))
        self.stress()
        control = self.pipeline.check
        def check(c, stage):
            if stage not in ('G4', 'G5'): return control(c, stage)
            # G5 observes the actual plain-app broken checkpoint as a bad fix.
            saved = artifacts.execution('plain')
            def checkpoint(*a, **kw):
                path = self.work / 'gate-details' / (stage + '-saved.json'); path.parent.mkdir(exist_ok=True)
                registry.atomic_json(path, saved)
                return saved['summary'], saved['records']
            with patch.object(run, 'checkpoint', side_effect=checkpoint):
                return getattr(run, stage.lower())(c)
        self.pipeline.check = check
        run.run_gates(self.c)
        snapshot = package.entry(self.c, run)
        self.assertEqual(next(row for row in snapshot['stages'] if row['stage'] == 'G5')['status'], 'fail')
        self.assertFalse(self.records().load('G5')['ok'])
        self.assertTrue(self.records().load('G4')['ok'])

    def test_real_g16_inconclusive_is_one_review_and_bound_failure(self):
        import fairness
        import independent_review
        folder = self.work / 'judge_breadth'; trial = folder / 'try-1'
        (trial / 'guard').mkdir(parents=True)
        (trial / 'guard/db.sql').write_text(artifacts.REAL['suffix-case']['files']['guards/reference/db.sql'])
        registry.atomic_json(trial / 'execution.json', artifacts.execution('plain'))
        registry.atomic_json(folder / 'results.json', [{'try': 1, 'workspace': str(trial),
            'solved': False, 'guard_submitted': True, 'stop_reason': 'completed',
            'checked_runs': 1, 'solved_runs': 0, 'errors': 0}])
        self.failure = 'G16'
        control = self.pipeline.check
        self.pipeline.check = lambda c, stage: run.g16(c) if stage == 'G16' else control(c, stage)
        # Substitute the external review service, still running its real verdict
        # validator against the retained attempt and an authored unknown answer.
        def review(c, r, gate, inputs, text, validate):
            return validate({'inconclusive': True, 'reason': 'authored unknown'})
        with patch.object(run, 'make_pilots'), patch.object(run, 'calibrate', return_value={'solved': 0}), \
                patch.object(independent_review, 'review', side_effect=review) as reviews, \
                patch.object(run, 'write_and_attack', side_effect=AssertionError('writer repair')):
            run.validate_and_repair(self.c)
        reviews.assert_called_once()
        record = self.records().load('G16')
        self.assertFalse(record['ok']); self.assertTrue(record['info']['review_inconclusive'])
        snapshot = package.entry(self.c, run)
        self.assertEqual(next(row for row in snapshot['stages'] if row['stage'] == 'G16')['status'], 'fail')

    def test_pending_shape_and_capture_errors_do_not_retry_or_change_gate_result(self):
        for error in (None, OSError('copy failed'), budget.BudgetError('extension_snapshot_changed'),
                      ValueError('bad evidence'), TypeError('not JSON')):
            with self.subTest(error=error):
                self.c.card.update(gates={}); self.c.card.pop('failed_gate', None)
                self.executed.clear()
                result = (False, {'error': 'authored operational result'}) if error is None else (False, {'authored': 'fail'})
                self.pipeline.check = lambda c, stage: (self.executed.append(stage) or result)
                with patch.object(package.Records, 'save', side_effect=error) if error else patch.object(run, 'write_and_attack'):
                    run.run_gates(self.c)
                self.assertEqual(self.executed, ['G1'])
                self.assertEqual(self.c.card['gate_results']['G1'], result[1])
                self.assertEqual(self.c.card['gates']['G1'], 'fail')
                self.assertFalse((self.records().root / 'closed.json').exists())
                self.pending()

    def test_capture_failure_after_rename_does_not_retry(self):
        original = extensions._sync_directory
        def sync(path):
            if (path / 'G1/record.json').exists(): raise OSError('after rename')
            return original(path)
        with patch.object(extensions, '_sync_directory', side_effect=sync): run.run_gates(self.c)
        self.assertEqual(self.executed.count('G1'), 1)
        self.pending()

    def test_new_pointer_prevents_old_traversal_filling_interruption(self):
        run.run_gates(self.c); old = self.records().root
        for stage in ('G1', 'G4'):
            self.crash = stage
            self.c.card.pop('failed_gate', None)
            with self.assertRaisesRegex(budget.BudgetError, 'money_wait'): run.run_gates(self.c)
            self.assertFalse(old.exists())
            self.pending()
            old = self.records().root
        self.crash = None
        run.run_gates(self.c)
        self.assertEqual(len([p for p in old.parent.iterdir() if p.is_dir()]), 1)
        self.assertIsInstance(package.entry(self.c, run), dict)

    def test_infrastructure_has_no_close_marker(self):
        self.pipeline.check = lambda *a: (_ for _ in ()).throw(InfrastructureExhausted('authored outage'))
        run.run_gates(self.c)
        self.assertEqual(self.c.card['terminal_stop'], 'infrastructure_exhausted')
        self.pending()

    def test_bad_stress_proof_does_not_change_ordinary_gates(self):
        original = (self.work / 'attack-state.json').read_bytes()
        for kind in ('missing', 'round', 'path', 'tamper', 'unfinished'):
            with self.subTest(kind=kind):
                self.stress(); receipt = json.loads(original)
                if kind == 'missing': (self.work / 'attack-state.json').unlink()
                elif kind == 'tamper': (self.work / 'attacks/round-8.json').write_text('{}')
                else:
                    if kind == 'round': receipt['round'] = 7
                    if kind == 'path': receipt['report'] = '../attacks/round-8.json'
                    registry.atomic_json(self.work / 'attack-state.json', receipt)
                with patch.object(run, 'attack_diagnostic_unfinished', return_value=kind == 'unfinished'):
                    run.run_gates(self.c)
                self.assertEqual(self.c.card['gates']['G5'], 'fail')
                self.pending()

    def test_retained_freshness_clearance_is_required_and_copied(self):
        import freshness_retrieval
        report = self.work / 'attacks/round-8.json'
        http = artifacts.fixture('invalid-runs-http.json.gz')
        meta = json.loads((self.case / 'case.json').read_text())
        meta.setdefault('app', {})['version'] = '2.19.0'
        registry.atomic_json(self.case / 'case.json', meta)
        rows = [json.loads(line) for line in (self.case / 'freshness.jsonl').read_text().splitlines() if line]
        for row in rows: row.update(hit=False, ambiguous=False)
        (self.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        self.stress()
        registry.atomic_json(report, {'complete': True,
            'blocking': ['[freshness-review] independent verdict required'],
            'freshness_review': [http['url']]})
        receipt = json.loads((self.work / 'attack-state.json').read_text())
        receipt['review_completed']['report_sha256'] = gate_state.digest(report)
        registry.atomic_json(self.work / 'attack-state.json', receipt)
        def fetch(url, **kwargs):
            return {'url': url, 'final_url': url, 'status': 200}, http['body'].encode()
        def reviewer(c, chain, text, directory, name, out, *args, **kwargs):
            registry.atomic_json(out, {'hits': [dict(url=http['url'], resolved=True,
                same_bug=False, retrieved=True, app_version='2.19.0',
                version_scope='Different practice behavior', why='Authored independent exclusion')]})
        with patch.object(freshness_retrieval, 'fetch', side_effect=fetch), \
                patch.object(run, 'retained_answer', side_effect=reviewer):
            resolved, _ = run.loop_freshness(self.c, run.attack_report(report), report)
        self.assertFalse(resolved['blocking'])
        run.run_gates(self.c)
        self.assertEqual(package.entry(self.c, run)['stages'][0]['status'], 'pass')
        proof = self.records().load('stress')['support']
        self.assertTrue(any(name.endswith('/round-8.clearance.json') for name in proof))
        self.assertTrue(any(name.endswith('.body') for name in proof))
        report.with_suffix('.clearance.json').write_text('{}')
        run.run_gates(self.c)
        self.pending()

    def test_malformed_pointer_close_and_missing_g3_hold(self):
        run.run_gates(self.c)
        pointer = self.work / 'entry-records/current.json'
        original = pointer.read_bytes()
        pointer.write_text('{}'); self.pending(); pointer.write_bytes(original)
        closed = self.records().root / 'closed.json'
        original_close = closed.read_bytes()
        closed.unlink(); self.pending(); closed.write_bytes(original_close)
        g3 = self.records().root / 'G3'
        shutil.rmtree(g3); self.pending()

    def test_entry_refusals_and_current_generation_rebind(self):
        run.run_gates(self.c)
        records = self.records()
        support = next(self.work / p for p in records.load('G1')['support'])
        original = support.read_bytes()
        for kind in ('missing', 'tampered', 'symlink'):
            with self.subTest(kind=kind):
                support.unlink(missing_ok=True)
                if kind == 'tampered': support.write_bytes(b'changed')
                if kind == 'symlink': support.symlink_to(self.case / 'promise.md')
                self.pending()
                support.unlink(missing_ok=True); support.write_bytes(original)
        with patch.object(gate_state, 'scientific_version', return_value='0' * 64): self.pending()
        (self.case / 'changed.txt').write_text('different case'); self.pending(); (self.case / 'changed.txt').unlink()
        before = copy.deepcopy(vars(self.c.args)); self.c.args.bench_workers = 2
        package.entry(self.c, run); self.assertEqual(self.c.args.bench_workers, 2)
        vars(self.c.args).update(before)
        self.c.source_generation = 'f' * 64
        self.c.job_money['source_generation'] = 'f' * 64
        self.c.authenticated_job_config['job_money']['source_generation'] = 'f' * 64
        self.assertEqual(package.entry(self.c, run)['source_generation'], 'f' * 64)

    def test_history_refuses_without_snapshot_or_evaluation(self):
        run.run_gates(self.c)
        import extension_evaluator
        (self.work / 'extension-history.json').write_text('[{"authored": "invalid history"}]')
        with patch.object(package.comparison, 'snapshot', side_effect=AssertionError('snapshot')), \
                patch.object(extension_evaluator, 'Evaluator', side_effect=AssertionError('evaluation')):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_history_invalid$'):
                package.entry(self.c, run)

    def test_expired_enabled_policy_refuses_before_observation_or_gate_work(self):
        expired = {**self.c.job_money, 'batch_deadline': '2000-01-01T00:00:00Z'}
        with patch.object(self.c, 'job_money', expired), patch.object(
                self.c, 'authenticated_job_config', {'job_money': copy.deepcopy(expired)}), \
                patch.object(self.pipeline, 'run') as invoke, patch.object(package, 'observe') as observe:
            with self.assertRaisesRegex(budget.BudgetError, '^retired_batch_bound$'):
                run.run_gates(self.c)
            invoke.assert_not_called(); observe.assert_not_called()
            # Mode exclusions run before policy/authority and therefore stay cheap.
            self.c.args.rehearse_only = True
            self.assertFalse(package.observation_enabled(self.c))
            self.c.args.rehearse_only = False

    def test_exact_activation_and_mode_exclusions(self):
        for name in ('dry_run', 'rehearse_only', 'audit_fairness', 'late_gate_rehearsal'):
            with self.subTest(mode=name):
                setattr(self.c.args, name, True)
                self.assertFalse(package.observation_enabled(self.c))
                setattr(self.c.args, name, False)
        for name in ('audit_source', 'audit_gates'):
            setattr(self.c, name, None); self.assertFalse(package.observation_enabled(self.c)); delattr(self.c, name)
        self.c.args.skip_build = True
        self.assertTrue(package.observation_enabled(self.c))
        overlap = self.pipeline.overlap_reason
        with runtime.diagnosis_policy(self.c, False), \
                patch.object(self.pipeline, 'run') as invoke, \
                patch.object(package, 'observe', side_effect=AssertionError('capture while off')):
            run.run_gates(self.c); invoke.assert_called_once()
        self.assertIs(self.pipeline.overlap_reason, overlap)
        self.assertFalse((self.work / 'entry-records').exists())
        with patch.object(self.pipeline, 'run') as invoke, \
                patch.object(package, 'observe', side_effect=AssertionError('package capture')):
            run.run_gates(self.c, around_gate=lambda *a: None)
            invoke.assert_called_once()

    def test_symlink_root_stops_before_any_gate(self):
        target = self.work / 'other'; target.mkdir()
        (self.work / 'entry-records').symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'): run.run_gates(self.c)
        self.assertEqual(self.executed, [])
        self.pending()


if __name__ == '__main__': unittest.main()
