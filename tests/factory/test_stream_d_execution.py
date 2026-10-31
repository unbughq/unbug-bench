"""Admitted execution over saved practice bytes and the 5813be ledger.

Model/gate outputs are authored; admission, receipts, reservations and loop run
for real. No live CLI, qualification, or Murphy closure is claimed.
"""
import copy
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


if __name__ == '__main__': unittest.main()
