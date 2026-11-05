"""Offline usage valuation, price ceilings and worker scientific guards."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import os
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import budget
import gate_state
import run
import model_runtime
import token_prices


MODEL = 'codex/gpt-6.1-sol'


class CaseBudgetTests(unittest.TestCase):
    def setUp(self):
        from freshness_test_transport import start
        start(self)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.c = c = types.SimpleNamespace(work=self.root, case=self.root / 'case', case_id='case-test',
            ledger=self.root / 'ledger.json', manifest0='synthetic', models={'builder': ['writer'], 'attacker': ['tester']},
            card={'gates': {}}, args=types.SimpleNamespace(source='hunt', resume='case-test', dry_run=False,
                rounds=3, case_budget=50, skip_build=False, no_early_probe=True))
        (c.work / 'logs').mkdir(); (c.work / 'attacks').mkdir(); (c.case / 'scenarios/S1').mkdir(parents=True)
        for name in ('case.json', 'answer-key.json', 'scenarios/S1/key.json'):
            (c.case / name).write_text('{}')
        # Never read production templates or case content.
        for target, replacement in (
            ('prompt', lambda role, text: text), ('run_context', lambda c, **kw: json.dumps(kw)),
            ('g1', lambda c: (True, {'problems': []})), ('early_checks', lambda c: None),
            ('early_review', lambda c: None)):
            p = patch.object(run, target, replacement); p.start(); self.addCleanup(p.stop)
        self.ledger(0)

    def ledger(self, spent, events=None, **extra):
        data = {'cost': 0, 'calls': 2, 'events': events or [], 'list_cost_usd': spent,
                'terminal_stop': 'complete', **extra}
        self.c.ledger.write_text(json.dumps(data)); return data

    def invoke(self, events, driver, model=None, **kw):
        code = ''.join('print(' + repr(json.dumps(e)) + ', flush=True)\n' for e in events)
        code += kw.pop('tail', '')
        return budget.run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
            self.root / 'synthetic-stream', self.c.ledger, 3, containment=False, driver=driver, configured_model=model,
            max_cost=100, max_total_calls=1000, **kw)

    def stress_round(self):
        from durable.contract import ArtifactKind, Ref, Step, StepInput, StepKind
        si = StepInput('b-offline', self.c.case_id, 1, Step(StepKind.STRESS, 1), 1,
            'a' * 64, 'b' * 64, Ref('a' * 64, ArtifactKind.INPUTS),
            Ref('b' * 64, ArtifactKind.CASE_SNAPSHOT), 300, 10_000_000)
        self.c.engine = run.EngineStep(si, 0)
        def stress(c, n, report, receipt, completed):
            return run.opencode(c, c.models['attacker'], json.dumps({'report_path': str(report)}),
                                c.work, f'attacker-{n}')
        with patch.object(run, 'engine_prepare_bench'), patch.object(run, 'stress_categories', stress), \
             patch.object(run, 'loop_freshness', side_effect=lambda c, result, path: (result, path)):
            return run.engine_stress_round(self.c, 1)

    def test_live_case_change_during_review_is_infrastructure_failure(self):
        from durable.contract import Outcome
        calls = []
        def call(c, models, text, cwd, name):
            calls.append(name)
            (c.case / 'unexpected.txt').write_text('changed during live review')
            (self.root / 'attacks/round-1.json').write_text('{"complete": true, "blocking": []}')
        with patch.object(run, 'opencode', call):
            result = self.stress_round()
        self.assertEqual(result, {'outcome': Outcome.INFRA_ERROR, 'reason': 'stress:case_changed'})
        self.assertEqual(calls, ['attacker-1'])

    def test_counts_all_drivers_once_and_by_role(self):
        usage = {'input_tokens': 1000000, 'cached_input_tokens': 400000, 'output_tokens': 10000}
        # Use short aggregate context here to exercise the ordinary cached-input rate.
        usage['input_tokens'], usage['cached_input_tokens'] = 100000, 40000
        self.invoke([{'type': 'thread.started', 'thread_id': 's'}, {'type': 'turn.started'},
            {'type': 'turn.completed', 'usage': usage}], 'codex', MODEL,
            role='strong_calibrator', invocation_name='strong-calibrator-1')
        self.invoke([{'type': 'result', 'session_id': 'claude', 'total_cost_usd': 3,
            'usage': {'input_tokens': 1, 'output_tokens': 2, 'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0}}], 'claude', 'claude/synthetic', role='writer')
        self.invoke([{'type': 'step_finish', 'sessionID': 'priced', 'part': {'id': 'p', 'messageID': 'p',
            'cost': .5, 'tokens': {'input': 1, 'output': 1, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}}}],
            'opencode', 'paid/synthetic', role='reviewer')
        summary = run.update_case_budget(self.c)[1]
        self.assertAlmostEqual(summary['spent_usd'], 3.724)
        self.assertEqual(summary['limit_usd'], 50)
        self.assertEqual(summary['breakdown_by_role']['writer'], 3)
        self.assertAlmostEqual(summary['breakdown_by_role']['strong_calibrator'], .224)
        data = json.loads(self.c.ledger.read_text())
        self.assertAlmostEqual(data['estimated_subscription_cost_usd'], .224)
        self.assertEqual(data['cost'], .5)

    def test_legacy_codex_tokens_are_estimated_and_unknown_usage_refuses(self):
        event = {'id': 'old', 'priced': 'subscription', 'cost': 0, 'configured_model': MODEL,
                 'tokens': {'input_tokens': 1000, 'cached_input_tokens': 500, 'output_tokens': 100}}
        data = self.ledger(30.08, [event], cost=.017)
        summary = budget.case_spending(data, {'strong-calibrator-1': MODEL})
        self.assertAlmostEqual(summary['spent_usd'], 30.09905)
        self.assertAlmostEqual(summary['breakdown_by_role']['strong_calibrator'], .00205)
        event['configured_model'] = 'codex/unknown'
        self.ledger(30.08, [event])
        summary = run.update_case_budget(self.c)[1]
        self.assertIsNone(summary['spent_usd'])
        self.assertEqual(summary['unpriced_events'], 1)
        with self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            run.case_budget_boundary(self.c)

    def test_unknown_codex_refuses_before_process(self):
        marker = self.root / 'must-not-start'
        with self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            self.invoke([], 'codex', 'codex/unknown', tail=f'open({str(marker)!r}, "w").close()')
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / 'synthetic-stream').exists())

    def test_large_codex_turn_uses_conservative_long_context_rate(self):
        self.assertAlmostEqual(token_prices.codex_cost(MODEL, {'input_tokens': 300000,
            'cached_input_tokens': 100000, 'output_tokens': 10000}), .97)
        self.assertIsNone(token_prices.codex_cost(MODEL, {'input_tokens': 1, 'cached_input_tokens': 2, 'output_tokens': 1}))

    def test_missing_subscription_usage_is_unknown_not_zero(self):
        with self.assertRaisesRegex(budget.BudgetError, 'missing_usage'):
            self.invoke([], 'codex', MODEL)
        summary = run.update_case_budget(self.c)[1]
        self.assertIsNone(summary['spent_usd'])
        self.assertEqual(summary['unpriced_events'], 1)
        with self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            self.invoke([], 'opencode', 'paid/synthetic', resume=True, case_budget=100)

    def test_inflight_role_finishes_and_next_role_stops(self):
        self.ledger(49)
        marker = self.root / 'finished'
        self.invoke([{'type': 'result', 'session_id': 'c', 'total_cost_usd': 4,
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0}}], 'claude', 'claude/synthetic',
            tail=f'open({str(marker)!r}, "w").close()', role='reviewer')
        self.assertTrue(marker.exists())
        self.assertEqual(run.update_case_budget(self.c)[1]['spent_usd'], 53)
        with self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            self.invoke([], 'opencode', 'paid/synthetic')

    def test_observed_round_cost_raises_floor(self):
        events = [{'id': 'w', 'role': 'writer', 'invocation': 'builder-1', 'cost': 0, 'list_cost_usd': 10},
                  {'id': 's', 'role': 'stress_tester', 'invocation': 'attacker-1', 'cost': 0, 'list_cost_usd': 2}]
        self.ledger(40, events)
        self.assertEqual(model_runtime.writer_round_estimate(self.c), 12)

    def test_live_missing_report_is_infrastructure_failure(self):
        from durable.contract import Outcome
        with patch.object(run, 'opencode') as call:
            result = self.stress_round()
        self.assertEqual(result, {'outcome': Outcome.INFRA_ERROR, 'reason': 'stress:malformed_report'})
        self.assertEqual([args.args[4] for args in call.call_args_list], ['attacker-1'])

    def test_gate_finishes_verdict_then_next_boundary_stops(self):
        self.c.audit_gates = ['G4', 'G5']
        def gate(c, name):
            self.assertEqual(name, 'G4')
            self.ledger(51)
            return True, {'measured': True}
        with patch.object(run.GatePipeline, 'check', staticmethod(gate)), self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            run.run_gates(self.c)
        self.assertEqual(self.c.card['gates'], {'G4': 'pass'})
        self.assertEqual(self.c.card['gate_results']['G4'], {'measured': True})
        self.assertNotIn('failed_gate', self.c.card)

    def test_budget_boundary_joins_active_calibrator_without_cancelling(self):
        import threading
        self.c.audit_gates = ['G6', 'G7']; self.c.args.bench_workers = 1
        self.c.prepared_factory_slots = 3
        active, release, finished = threading.Event(), threading.Event(), threading.Event()
        def gate(c, name):
            if name == 'G10':
                active.set(); self.assertTrue(release.wait(2))
                self.assertFalse(c.role_cancel.is_set()); finished.set()
            else:
                self.assertEqual(name, 'G6'); self.assertTrue(active.wait(2))
                self.ledger(51)
                timer = threading.Timer(.05, release.set); timer.start(); self.addCleanup(timer.join)
            return True, {'measured': True}
        with patch.object(run.GatePipeline, 'check', staticmethod(gate)), patch.object(run, 'g10_overlap_reason', return_value=None), \
                self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            run.run_gates(self.c)
        self.assertTrue(finished.is_set())
        self.assertEqual(self.c.card['gates'], {'G6': 'pass'})

    def test_budget_raise_uses_v2_evidence_rules(self):
        runner = self.root / 'runner.py'; runner.write_text('def g4(c):\n    return True\n')
        bench = self.root / 'bench'; (bench / 'results').mkdir(parents=True)
        evidence = bench / 'results/trial.json'; evidence.write_text('{}')
        self.c.seed = 7
        with patch.object(gate_state, 'RUNNER', runner):
            signature = gate_state.fingerprint(self.c, 'G4', bench)
            gate_state.save(self.c, 'G4', {'measured': True}, signature, {}, bench)
            self.c.args.case_budget = 100; self.c.args.rounds = 9
            with patch.object(run, 'BENCH', bench), patch.object(run, 'g4') as gate:
                ok, info = run.checked_gate(self.c, 'G4')
            self.assertTrue(ok); gate.assert_not_called()
            self.assertEqual(info['fingerprint_version'], gate_state.VERSION)
            path = self.root / 'gate-cache/G4.json'; receipt = json.loads(path.read_text())
            receipt.pop('fingerprint_version'); path.write_text(json.dumps(receipt))
            self.assertIsNone(gate_state.load(self.c, 'G4', bench))


if __name__ == '__main__': unittest.main()
