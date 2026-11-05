"""Real context, age artifacts, verdict validation and ledger; only model work is replaced."""
import gzip
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import types
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
os.environ.setdefault('BENCH', str(ROOT))
import budget
import run as runner
from durable.artifacts import AgeSealer
from durable.classify import classify
from durable import contract as k
from durable.worker_step import Worker, blob_name
from durable.steps.diagnosis import run


@unittest.skipUnless(shutil.which('age'), 'requires local age CLI')
class DiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.key = os.urandom(32)
        self.sealer = AgeSealer()
        self.worker = Worker(self.home, sealer=self.sealer, classifier=classify, runner=runner)
        self.case, self.batch = 'case-diagnosis-test', 'b-diagnosis'
        release = self.home / k.RELEASE_MANIFEST
        release.parent.mkdir(parents=True)
        release.write_text(json.dumps(dict(plumbing_version='a' * 64, bench_version='b' * 64)))
        self.blobs = self.home / k.WORKER_ROOT / 'blobs'
        self.blobs.mkdir(parents=True)
        self.evidence = self.push(k.ArtifactKind.DIAGNOSTIC, b'private evidence sentinel')
        source = self.home / 'source'
        runner.build_fixture(types.SimpleNamespace(case=source / 'case'))
        retained = json.loads(gzip.decompress((Path(__file__).parent / 'fixtures/router-paid-deepseek.json.gz').read_bytes()))
        card = next(c for c in retained if c['case'].endswith('e15450'))
        self.card = dict(case=self.case, seed=7, dry_run=True, source='fixture (dry-run)',
                         models=card['models'], roles=card['roles'], gates={},
                         failed_gate='G1', failed_detail=['actual gate finding'])
        (source / 'scorecard.json').write_text(json.dumps(self.card))
        (source / 'continuation-budget.json').write_text(json.dumps({'calls': 0, 'events': [], 'cost': 0}))
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w:gz') as tar:
            for path in source.iterdir(): tar.add(path, arcname=path.name)
        snapshot = self.push(k.ArtifactKind.CASE_SNAPSHOT, archive.getvalue())
        self.si = k.StepInput(self.batch, self.case, 4, k.Step(k.StepKind.DIAGNOSIS), 1,
                              'a' * 64, 'b' * 64, k.Ref('c' * 64, k.ArtifactKind.INPUTS),
                              snapshot, 60, 10_000_000, evidence=(self.evidence,))
        self.worker.paths(self.si.idempotency_key)['attempt'].mkdir(parents=True)
        self.answer = 'close_to_passing'
        self.corrupt = None

    def push(self, kind, raw):
        ref, encrypted = self.sealer.seal(self.key, kind, raw)
        (self.blobs / blob_name(ref)).write_bytes(encrypted)
        return ref

    def model(self, c, *, model, prompt, inputs, output):
        self.assertTrue(runner.under_engine(c))
        self.assertEqual(c.engine.ceiling_usd, 10)
        self.assertEqual(model, self.card['roles']['reviewer']['model'])
        self.assertFalse(hasattr(c, 'authenticated_job_config'))
        context = json.loads(prompt.split('Run context (data):\n')[1])
        evidence = 'evidence/' + blob_name(self.evidence)
        self.assertEqual((inputs / evidence).read_bytes(), b'private evidence sentinel')
        event = {'type': 'step_finish', 'sessionID': 's', 'part': {
            'id': uuid.uuid4().hex, 'messageID': 'm', 'cost': .25, 'reason': 'stop',
            'tokens': {'input': 10, 'output': 20, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}}}
        # The only substituted operation is a local model process. Real accounting
        # parses its priced event and writes the attempt's continuation ledger.
        budget.run_budgeted([sys.executable, '-c', 'print(' + repr(json.dumps(event)) + ')'],
            output, os.environ.copy(), c.work / 'transcripts/diagnosis.jsonl', c.ledger, 10,
            max_cost=c.args.max_cost, max_calls=c.args.max_role_calls,
            max_total_calls=c.args.max_total_calls, driver='opencode',
            configured_model=model, concurrent=True, case_budget=c.args.case_budget,
            role='reviewer', invocation_name='diagnosis-test', containment=False)
        if self.corrupt == 'raise': raise RuntimeError('private exception sentinel')
        if self.corrupt == 'provider': raise budget.BudgetError('provider_limit:codex/private')
        if self.corrupt == 'json': return b'{private invalid JSON'
        if self.corrupt == 'oversized': return b' ' * 65537
        result = dict(schema_version=1, case_id=c.case_id,
                      checkpoint_sha256=context['checkpoint_sha256'], outcome=self.answer,
                      reason='private diagnosis prose sentinel',
                      evidence=[dict(path=evidence, sha256=hashlib.sha256((inputs / evidence).read_bytes()).hexdigest(),
                                     finding='private finding sentinel')], factory_bug=None)
        if self.answer == 'factory_bug':
            result['factory_bug'] = dict(component='runtime', reproducer='private reproducer',
                                         affected_operations=[], fix_required='private fix')
        if self.corrupt == 'hash': result['evidence'][0]['sha256'] = '0' * 64
        if self.corrupt == 'mutate': (inputs / evidence).write_bytes(b'changed')
        if self.corrupt == 'processing':
            (c.work / 'attack-state.json').write_text(json.dumps({'report': '../private-invalid'}))
        return json.dumps(result).encode()

    def execute(self, expected_calls=1):
        with patch.object(runner, 'invoke_diagnosis', side_effect=self.model, create=True) as invoke:
            result, outputs = run(self.worker, self.si, {self.case: self.key})
        self.assertEqual(invoke.call_count, expected_calls)
        k.check_result_for(self.si.step, result)
        self.assertEqual(result.usage.calls, expected_calls)
        self.assertEqual(result.usage.paid_usd_micros, 250_000 * expected_calls)
        wire = json.dumps(k.to_record(result))
        self.assertNotIn('private', wire)
        self.assertNotIn(self.key.hex(), wire)
        return result, outputs

    def opened(self, ref, outputs):
        return self.sealer.open(self.key, ref, outputs[blob_name(ref)])

    def test_all_verdicts_and_private_report_snapshot_feedback(self):
        for verdict in ('factory_bug', 'close_to_passing', 'not_converging'):
            with self.subTest(verdict=verdict):
                self.answer = verdict
                result, outputs = self.execute()
                self.assertEqual(result.outcome, k.Outcome.OK)
                self.assertEqual(result.verdict.value, verdict)
                self.assertIn(b'private diagnosis prose sentinel', self.opened(result.report, outputs))
                if verdict == 'close_to_passing':
                    feedback = json.loads(self.opened(result.feedback, outputs))
                    self.assertEqual(feedback['source'], 'diagnosis')
                    self.assertIn('actual gate finding', str(feedback['problems']))
                    self.assertNotIn('diagnosis prose', str(feedback))
                else: self.assertIsNone(result.feedback)
                with tarfile.open(fileobj=io.BytesIO(self.opened(result.snapshot, outputs))) as tar:
                    card = json.load(tar.extractfile('scorecard.json'))
                    self.assertEqual(card['engine_diagnosis']['verdict'], verdict)
                    self.assertEqual(card['gates'], {})
                    self.assertNotIn('diagnosis_state', card)

    def test_malformed_and_invalid_results_preserve_paid_usage(self):
        for corrupt in ('json', 'oversized', 'hash', 'mutate', 'raise', 'processing'):
            with self.subTest(corrupt=corrupt):
                self.corrupt = corrupt
                result, _ = self.execute()
                self.assertEqual(result.outcome, k.Outcome.INFRA_ERROR)
                self.assertIsNone(result.verdict)

    def test_unknown_verdict_is_infrastructure_failure(self):
        self.answer = 'private unknown verdict'
        result, _ = self.execute()
        self.assertEqual(result.outcome, k.Outcome.INFRA_ERROR)

    def test_provider_limit_after_paid_work_keeps_usage(self):
        self.corrupt = 'provider'
        result, _ = self.execute()
        self.assertEqual(result.outcome, k.Outcome.PROVIDER_LIMIT)
        self.assertIsNotNone(result.retry_at)

    def test_bad_key_cannot_open_evidence_or_snapshot(self):
        result, outputs = run(self.worker, self.si, {self.case: os.urandom(32)})
        self.assertEqual(result.outcome, k.Outcome.INFRA_ERROR)
        self.assertEqual(result.usage, k.Usage())
        self.assertEqual(outputs, {})

    def test_corrupt_encrypted_evidence_stops_before_model(self):
        (self.blobs / blob_name(self.evidence)).write_bytes(b'private corrupt ciphertext')
        with patch.object(runner, 'invoke_diagnosis', create=True) as invoke:
            result, _ = run(self.worker, self.si, {self.case: self.key})
        invoke.assert_not_called()
        self.assertEqual(result.outcome, k.Outcome.INFRA_ERROR)
        self.assertEqual(result.usage, k.Usage())

    def test_missing_runtime_hook_is_explicit(self):
        with patch.object(runner, 'invoke_diagnosis', None, create=True):
            result, _ = run(self.worker, self.si, {self.case: self.key})
        self.assertEqual(result.reason, 'engine:diagnosis_unavailable')
        self.assertEqual(result.usage, k.Usage())

    def test_restored_prior_spend_is_not_charged_again(self):
        result, outputs = self.execute()
        (self.blobs / blob_name(result.snapshot)).write_bytes(outputs[blob_name(result.snapshot)])
        self.si = replace(self.si, snapshot=result.snapshot)
        again, _ = self.execute(expected_calls=0)
        self.assertEqual(again.outcome, k.Outcome.OK)
        self.assertEqual(again.usage, k.Usage())


if __name__ == '__main__': unittest.main()
