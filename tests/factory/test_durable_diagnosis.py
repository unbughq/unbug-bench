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
import time
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
from diagnosis import _input_inventory as diagnosis_inventory
from extensions import digest as extensions_digest


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
        # The prompt carries the inventory's size and digest, never the inventory: it is one argv entry.
        self.assertNotIn('files', context)
        inventory = diagnosis_inventory(inputs)
        self.assertEqual(context['file_count'], len(inventory))
        self.assertEqual(context['files_sha256'], extensions_digest(inventory))
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
        if self.corrupt in ('cleanup_route', 'cleanup_raise', 'cleanup_provider'):
            # diagnosis_invocation.invoke marks the first error when the pilot cleanup also failed.
            error = {'cleanup_route': budget.BudgetError('route_feature_unsupported'),
                     'cleanup_raise': RuntimeError('private exception sentinel'),
                     'cleanup_provider': budget.BudgetError('provider_limit:codex/private')}[self.corrupt]
            error.diagnosis_cleanup_failed = True
            raise error
        if self.corrupt == 'provider': raise budget.BudgetError('provider_limit:codex/private')
        if self.corrupt == 'structured_provider':
            from model_router import ProviderWait, Wait
            raise ProviderWait('reviewer', Wait('rate', time.time() + 120,
                lease_id='b' * 32, call_id='usage-receipts/' + 'b' * 32 + '.json'))
        if self.corrupt == 'json': return b'{private invalid JSON'
        if self.corrupt == 'oversized': return b' ' * 65537
        result = dict(schema_version=1, case_id=c.case_id,
                      checkpoint_sha256=context['checkpoint_sha256'], outcome=self.answer,
                      reason='private diagnosis prose sentinel',
                      evidence=[dict(path=evidence, sha256=hashlib.sha256((inputs / evidence).read_bytes()).hexdigest(),
                                     finding='private finding sentinel')], factory_bug=None)
        if self.answer == 'factory_bug':
            result['factory_bug'] = dict(component='runtime', reproducer='private reproducer',
                                         fix_required='private fix')
        if self.corrupt == 'hash': result['evidence'][0]['sha256'] = '0' * 64
        if self.corrupt == 'mutate': (inputs / evidence).write_bytes(b'changed')
        if self.corrupt in ('writer_receipt', 'writer_receipt_first_round'):
            # A writer round's receipt names the stress report that follows it, not an existing one.
            (c.work / 'attack-state.json').write_text(json.dumps(
                {'engine': True, 'round': 2, 'report': 'round-2.json', 'repair_pending': True}))
            if self.corrupt == 'writer_receipt':
                (c.work / 'attacks').mkdir(exist_ok=True)
                (c.work / 'attacks/round-1.json').write_text('{}')
                (c.work / 'engine-feedback.json').write_text(json.dumps({'attack_report': 'round-1.json'}))
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

    def test_a_close_verdict_on_a_case_stopped_in_a_writer_round_gives_feedback(self):
        for corrupt, report in (('writer_receipt', 'round-1.json'), ('writer_receipt_first_round', None)):
            with self.subTest(corrupt=corrupt):
                self.corrupt = corrupt
                result, outputs = self.execute()
                self.assertEqual((result.outcome, result.verdict), (k.Outcome.OK, k.Verdict.CLOSE_TO_PASSING))
                self.assertEqual(json.loads(self.opened(result.feedback, outputs))['attack_report'], report)

    def test_a_processing_failure_names_its_cause(self):
        for corrupt, reason in (('json', 'infra:diagnosis_result_invalid'), ('raise', 'infra:raw_runtime_error'),
                                ('processing', 'infra:raw_value_error')):
            with self.subTest(corrupt=corrupt):
                self.corrupt = corrupt
                result, outputs = self.execute()
                self.assertEqual((result.outcome, result.reason), (k.Outcome.INFRA_ERROR, reason))
                # Every failure seals the same diagnostic as a writer step, not only a provider wait.
                details = json.loads(self.opened(result.diagnostic, outputs))
                self.assertLessEqual({'runner_log_tail', 'stop', 'operational', 'traceback'}, set(details))
                self.assertTrue(details['traceback'])

    def test_cleanup_failure_names_the_first_error(self):
        for corrupt, outcome, reason in (
                ('cleanup_route', k.Outcome.INFRA_ERROR, 'diagnosis:cf_route_feature_unsupported'),
                ('cleanup_raise', k.Outcome.INFRA_ERROR, 'diagnosis:cf_runtime_error'),
                ('cleanup_provider', k.Outcome.PROVIDER_LIMIT, 'router:codex_limit')):
            with self.subTest(corrupt=corrupt):
                self.corrupt = corrupt
                result, _ = self.execute()
                self.assertEqual((result.outcome, result.reason), (outcome, reason))

    def history(self, reasons):
        rows = [{'seq': 3, 'step': 'gates', 'attempt': 1, 'outcome': 'gate_failed', 'reason': 'gate:G5',
                 'paid_usd_micros': 0}]
        rows += [{'seq': 4, 'step': 'writer', 'attempt': n, 'outcome': o, 'reason': r, 'paid_usd_micros': 0}
                 for n, (o, r) in enumerate(reasons, 1)]
        self.si = replace(self.si, evidence=(self.evidence, self.push(k.ArtifactKind.DIAGNOSTIC,
                                                                      json.dumps(rows).encode())))

    def test_a_step_stopping_on_one_infra_reason_is_a_factory_bug_without_a_model_call(self):
        # f46dac-5-1, 11-14 November: every writer round stopped on expired freshness rows with its gates
        # passing; the agent said close_to_passing and policy retired it as making no progress.
        same = ('infra_error', 'infra:freshness_refresh_stalled')
        self.history([('provider_limit', 'router:claude_limit'), ('infra_error', 'router:opencode_error'),
                      same, ('infra_error', 'infra:paused'), same, same])
        result, outputs = self.execute(expected_calls=0)
        self.assertEqual((result.outcome, result.verdict), (k.Outcome.OK, k.Verdict.FACTORY_BUG))
        self.assertIsNone(result.feedback)
        report = json.loads(self.opened(result.report, outputs))
        self.assertEqual(report['factory_bug']['component'], 'infra:freshness_refresh_stalled')

    def test_mixed_too_few_or_case_caused_infra_stops_still_ask_the_agent(self):
        same = ('infra_error', 'infra:freshness_refresh_stalled')
        # A stop the case itself can cause is the agent's to judge, however often it repeats.
        case = [[('infra_error', reason)] * 3 for reason in ('infra:freshness_review_unavailable',
                'infra:freshness_evidence_unavailable', 'infra:freshness_unresolved')]
        for reasons in ([same, same], [same, ('infra_error', 'router:opencode_error'), same],
                        [same, same, same, ('exhausted', 'writer:money')], *case):
            with self.subTest(reasons=reasons):
                self.history(reasons)
                result, _ = self.execute()
                self.assertEqual(result.verdict, k.Verdict.CLOSE_TO_PASSING)

    def test_unknown_verdict_is_infrastructure_failure(self):
        self.answer = 'private unknown verdict'
        result, _ = self.execute()
        self.assertEqual(result.outcome, k.Outcome.INFRA_ERROR)

    def test_provider_limit_after_paid_work_keeps_usage(self):
        self.corrupt = 'provider'
        result, _ = self.execute()
        self.assertEqual(result.outcome, k.Outcome.PROVIDER_LIMIT)
        self.assertIsNotNone(result.retry_at)

    def test_structured_wait_retains_operational_diagnostic_and_usage(self):
        self.corrupt = 'structured_provider'
        result, outputs = self.execute()
        self.assertEqual(result.reason, 'router:rate')
        self.assertIsNotNone(result.retry_at)
        details = json.loads(self.opened(result.diagnostic, outputs))
        self.assertEqual(details['provider_wait']['waits'][-1]['lease_id'], 'b' * 32)

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
