"""Offline list-price ceilings and economic salvage; synthetic fixtures only."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import budget
import gate_state
import restart
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

    def receipt(self, *, final=False, n=3, limit=3):
        binding = run.attack_binding(self.c)
        (self.root / 'attack-state.json').write_text(json.dumps({'round': n, 'round_limit': limit,
            'report': f'round-{n}.json', 'binding': binding, 'final_repair': final}))
        (self.root / f'attacks/round-{n}.json').write_text(json.dumps({'complete': False,
            'blocking': ['synthetic latest stock finding']}))

    def invoke(self, events, driver, model=None, **kw):
        code = ''.join('print(' + repr(json.dumps(e)) + ', flush=True)\n' for e in events)
        code += kw.pop('tail', '')
        return budget.run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
            self.root / 'synthetic-stream', self.c.ledger, 3, containment=False, driver=driver, configured_model=model,
            max_cost=100, max_total_calls=1000, **kw)

    def public_card(self, stop='stress_review_unresolved:rounds_exhausted', spent=30.08, limit=None):
        archive = self.root / 'case-test.checkpoint.tar.gz.age'
        archive.write_bytes(b'synthetic ciphertext only')
        card = {'case': 'case-test', 'seed': 7, 'status': 'stopped', 'terminal_stop': stop,
            'gates': {}, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
            'recovery_config': {'rounds': 3}, 'continuation_budget': self.ledger(spent)}
        if limit is not None: card['case_budget'] = {'limit_usd': limit, 'spent_usd': spent}
        return card

    def plan(self, card, args):
        path = self.root / 'case-test.scorecard.json'; path.write_text(json.dumps(card))
        return restart.plan(path, 0, 7200, args)

    def test_transient_review_resume_rereviews_same_round_without_raise(self):
        for stop in (None, 'stalled', 'paused', 'timeout', 'opencode_error', 'provider_limit:opencode/test',
                     'stress_review_unresolved:interrupted_review',
                     'stress_review_unresolved:missing_or_malformed_report',
                     'stress_review_unresolved:case_changed_since_review'):
            for content in (None, '{"complete": false, "blocking": ["review incomplete"]}'):
                with self.subTest(stop=stop, content=content):
                    self.ledger(0, terminal_stop='stalled')
                    self.receipt()
                    report = self.root / 'attacks/round-3.json'
                    if content is None: report.unlink()
                    else: report.write_text(content)
                    before = run.attack_binding(self.c)
                    def call(c, models, text, cwd, name):
                        self.assertEqual(name, 'attacker-3')
                        self.assertEqual(run.attack_binding(c), before)
                        self.assertEqual(json.loads((self.root / 'attack-state.json').read_text())['rereviews'], 1)
                        report.write_text('{"complete": true, "blocking": []}')
                    with patch.object(run, 'opencode', call):
                        run.write_and_attack(self.c, {'terminal_stop': stop})
                    self.assertEqual(self.c.card['resume_rereview'], {'round': 3, 'reason':
                        'missing_or_malformed_report' if content is None else 'interrupted_review', 'binding_changed': []})
                    self.assertEqual(self.c.card['stress_review'], {'status': 'completed', 'round': 3})

    def test_stall_during_initial_review_resumes_in_place_without_writer(self):
        self.c.args.resume = None
        calls = []
        def stalled(c, models, text, cwd, name):
            calls.append(name)
            if name == 'attacker-1': raise budget.BudgetError('stalled')
        with patch.object(run, 'opencode', stalled), self.assertRaisesRegex(budget.BudgetError, '^stalled$'):
            run.write_and_attack(self.c, {})
        self.c.args.resume = 'case-test'
        def resumed(c, models, text, cwd, name):
            calls.append(name)
            self.assertEqual(name, 'attacker-1')
            pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).write_text(
                '{"complete": true, "blocking": []}')
        with patch.object(run, 'opencode', resumed):
            run.write_and_attack(self.c, {'terminal_stop': 'stalled'})
        self.assertEqual(calls, ['builder-1', 'attacker-1', 'attacker-1'])
        self.assertEqual(self.c.card['resume_rereview'], {'round': 1, 'reason': 'interrupted_review', 'binding_changed': []})

    def test_rereview_retains_diagnostic_allowance_and_unfinished_guard(self):
        for completed in (False, True):
            self.receipt()
            (self.root / 'attacks/round-3.json').unlink()
            diagnostic = self.root / 'diagnostic-budgets/attacker-3'
            diagnostic.mkdir(parents=True, exist_ok=True)
            (diagnostic / 'claimed').touch()
            (diagnostic / 'status.json').write_text(json.dumps({'status': 'completed' if completed else 'running'}))
            def call(c, models, text, cwd, name):
                self.assertEqual(name, 'attacker-3')
                self.assertIn('EXHAUSTED', text)
                self.assertTrue((diagnostic / 'claimed').exists())
                (self.root / 'attacks/round-3.json').write_text('{"complete": true, "blocking": []}')
            with patch.object(run, 'opencode', call):
                if completed: run.write_and_attack(self.c, {'terminal_stop': 'stalled'})
                else:
                    with self.assertRaisesRegex(budget.BudgetError, 'unfinished_diagnostic'):
                        run.write_and_attack(self.c, {'terminal_stop': 'stalled'})

    def test_rereview_repeat_bound_survives_transient_stops(self):
        self.receipt()
        (self.root / 'attacks/round-3.json').write_text('{"complete": false, "blocking": ["review incomplete"]}')
        def stalled(*args, **kw): raise budget.BudgetError('stalled')
        for expected in (1, 2):
            with patch.object(run, 'opencode', stalled), self.assertRaisesRegex(budget.BudgetError, '^stalled$'):
                run.write_and_attack(self.c, {'terminal_stop': 'stalled'})
            self.assertEqual(json.loads((self.root / 'attack-state.json').read_text())['rereviews'], expected)
        with patch.object(run, 'opencode') as call, self.assertRaisesRegex(budget.BudgetError, 'interrupted_review'):
            run.write_and_attack(self.c, {'terminal_stop': 'stalled'})
        call.assert_not_called()

    def test_release_binding_changes_rereview_before_writer(self):
        # Compute the old/new manifests through production bench_manifest(), as
        # releases do; never forge a saved binding or patch attack_binding().
        bench = self.root / 'public-bench'; bench.mkdir()
        binding_bench = patch.object(run, 'BENCH', bench)
        binding_bench.start(); self.addCleanup(binding_bench.stop)
        for field in ('bench', 'models', 'prompt', 'case'):
            for content in (None, '{bad json',
                            '{"complete": false, "blocking": ["review incomplete"]}',
                            '{"complete": true, "blocking": []}',
                            '{"complete": false, "blocking": ["stale finding"]}'):
                with self.subTest(field=field, content=content):
                    self.c.card = {'gates': {}}
                    self.c.args.rounds = 8
                    (self.c.case / 'repair.txt').unlink(missing_ok=True)
                    (bench / 'README.md').write_text('old release')
                    with patch.object(run, 'BENCH', bench), patch.object(run, 'prompt', lambda role, text: 'old prompt\n' + text):
                        self.c.manifest0 = run.bench_manifest()
                        self.receipt(n=3, limit=8)
                    old = json.loads((self.root / 'attack-state.json').read_text())['binding']
                    report = self.root / 'attacks/round-3.json'
                    if content is None: report.unlink()
                    else: report.write_text(content)
                    if field == 'bench':
                        (bench / 'README.md').write_text('new release')
                        with patch.object(run, 'BENCH', bench): self.c.manifest0 = run.bench_manifest()
                    elif field == 'models': self.c.models['attacker'] = [str(self.c.models['attacker']) + '-new']
                    elif field == 'case': (self.c.case / 'pending.txt').write_text(str(content))
                    calls = []
                    def call(c, models, text, cwd, name):
                        calls.append(name)
                        self.assertNotIn('stale finding', text)
                        if name == 'attacker-3':
                            self.assertEqual(models, c.models['attacker'])
                            self.assertEqual(json.loads((self.root / 'attack-state.json').read_text())['binding'], run.attack_binding(c))
                            report.write_text('{"complete": true, "blocking": ["fresh finding"]}')
                        elif name == 'builder-4':
                            self.assertIn('round-3.json', text)
                            self.assertIn('fresh finding', text)
                            (c.case / 'repair.txt').write_text('fixed')
                        else:
                            self.assertEqual(name, 'attacker-4')
                            (self.root / 'attacks/round-4.json').write_text('{"complete": true, "blocking": []}')
                    with patch.object(run, 'prompt', lambda role, text: ('new' if field == 'prompt' else 'old') + ' prompt\n' + text):
                        current = run.attack_binding(self.c)
                        self.assertNotEqual(old, current)
                        with patch.object(run, 'opencode', call):
                            run.write_and_attack(self.c, {'terminal_stop': 'stress_review_unresolved:interrupted_review'})
                    self.assertEqual(calls, ['attacker-3', 'builder-4', 'attacker-4'])
                    reason = ('missing_or_malformed_report' if content is None or content == '{bad json' else
                              'interrupted_review' if 'review incomplete' in content else 'binding_changed')
                    self.assertEqual(self.c.card['resume_rereview'], {'round': 3, 'reason': reason,
                        'binding_changed': [field]})

    def test_changed_binding_rereview_keeps_cap_and_budget_boundary(self):
        for exhausted in ('cap', 'budget'):
            self.receipt()
            (self.root / 'attacks/round-3.json').unlink()
            self.c.manifest0 += '-new-release'
            if exhausted == 'cap':
                path = self.root / 'attack-state.json'
                receipt = json.loads(path.read_text()); receipt['rereviews'] = 2
                path.write_text(json.dumps(receipt))
            else: self.ledger(50)
            with patch.object(run, 'opencode') as call, self.assertRaises(budget.BudgetError):
                run.write_and_attack(self.c, {'terminal_stop': 'stalled'})
            call.assert_not_called()
            receipt = json.loads((self.root / 'attack-state.json').read_text())
            self.assertEqual(receipt.get('rereviews', 0), 2 if exhausted == 'cap' else 0)

    def test_live_case_change_during_review_still_stops(self):
        self.c.args.resume = None
        calls = []
        def call(c, models, text, cwd, name):
            calls.append(name)
            if name == 'attacker-1':
                (c.case / 'unexpected.txt').write_text('changed during live review')
                (self.root / 'attacks/round-1.json').write_text('{"complete": true, "blocking": []}')
        with patch.object(run, 'opencode', call), self.assertRaisesRegex(
                budget.BudgetError, 'stress_review_unresolved:case_changed_during_review'):
            run.write_and_attack(self.c, {})
        self.assertEqual(calls, ['builder-1', 'attacker-1'])
        self.assertNotIn('resume_rereview', self.c.card)

    def test_completed_claude_writer_budget_ignores_throttled_work_snapshot(self):
        from durable_checkpoint import checkpoint_progress
        c = self.c
        old = self.ledger(49)
        snapshot = c.work / 'continuation-budget.json'
        snapshot.write_text(json.dumps(old))
        c.durable_checkpoint_at = 100
        result = self.invoke([{'type': 'result', 'session_id': 'fresh-writer', 'total_cost_usd': 2,
            'usage': {'input_tokens': 10, 'output_tokens': 20, 'cache_read_input_tokens': 0,
                      'cache_creation_input_tokens': 0}}], 'claude', 'claude/synthetic',
            role='writer', invocation_name='builder-6')
        self.assertEqual(result.returncode, 0)
        with patch('durable_checkpoint.time.monotonic', return_value=725), patch.object(run, 'seal') as seal:
            self.assertFalse(checkpoint_progress(c, seal, quiescent=True))
        seal.assert_not_called()
        self.assertEqual(json.loads(snapshot.read_text()), old)
        ledger, summary = run.update_case_budget(c)
        self.assertEqual(summary['spent_usd'], 51)
        self.assertEqual(ledger['events'][-1]['invocation'], 'builder-6')
        with self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            run.case_budget_boundary(c)

    def test_interrupted_review_planner_without_raise_and_failed_gate_refusal(self):
        for stop in ('stress_review_unresolved:interrupted_review',
                     'stress_review_unresolved:missing_or_malformed_report',
                     'stress_review_unresolved:case_changed_since_review'):
            card = self.public_card(stop, limit=50)
            self.assertEqual(self.plan(card, ''), ('case-test', 60, 7))
            self.assertEqual(self.plan(card, '--case-budget 50 --rounds 3'), ('case-test', 60, 7))
            for ledger_stop in ('stalled', 'timeout', 'provider_limit:opencode/test', 'budget_exhausted'):
                value = {**card, 'continuation_budget': {**card['continuation_budget'], 'terminal_stop': ledger_stop}}
                if ledger_stop == 'budget_exhausted':
                    with self.assertRaises(ValueError): self.plan(value, '')
                else: self.assertEqual(self.plan(value, ''), ('case-test', 60, 7))
            for extra in ({'failed_gate': 'G15'}, {'gates': {'G15': 'fail'}}):
                with self.assertRaises(ValueError): self.plan({**card, **extra}, '')
        with self.assertRaises(ValueError): self.plan(self.public_card(limit=50), '')

    def test_attacker_call_timeout_is_transient_and_shorter_than_global_stall(self):
        from router_test_support import offline_router
        self.addCleanup(offline_router()[0].close)
        c = self.c
        c.models['attacker'] = ['opencode/test-free']
        for key, value in dict(agent_timeout=4 * 3600, no_progress_minutes=45, max_cost=5,
                               max_role_calls=400, max_total_calls=2000, max_zero_tokens=3).items():
            setattr(c.args, key, value)
        (c.work / 'transcripts').mkdir()
        limits = []
        real_run = model_runtime.run_budgeted
        def hung(cmd, cwd, env, transcript, ledger, timeout, **kw):
            limits.append(timeout)
            self.assertLess(timeout, c.args.no_progress_minutes * 60)
            return real_run([sys.executable, '-c', 'import time; time.sleep(5)'], cwd, env,
                            transcript, ledger, .05, **{**kw, 'containment': False})
        with patch.object(model_runtime, 'run_budgeted', hung), patch.object(run, 'public_progress'), \
                patch.object(model_runtime, 'opencode_config', return_value=self.root / 'config.json'):
            with self.assertRaisesRegex(budget.BudgetError, '^timeout$'):
                run.opencode(c, c.models['attacker'], 'synthetic', c.work, 'attacker-3')
        self.assertEqual(limits, [1200 + 60 * sum(p.is_file() for p in c.case.rglob('*'))])
        self.assertEqual(json.loads(c.ledger.read_text())['terminal_stop'], 'timeout')
        self.assertTrue(restart.RETRY.fullmatch('timeout'))
        for overall, explicit, expected in ((14400, 60, 60), (30, 60, 30)):
            c.args.agent_timeout = overall
            with patch.object(model_runtime, 'run_budgeted', return_value=types.SimpleNamespace(returncode=0)) as call, \
                    patch.object(run, 'public_progress'), \
                    patch.object(model_runtime, 'opencode_config', return_value=self.root / 'config.json'):
                run.opencode(c, c.models['attacker'], 'synthetic', c.work, 'attacker-3', timeout=explicit)
            self.assertEqual(call.call_args.args[5], expected)

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

    def test_budget_stop_before_round_never_buys_unreserved_final_fix(self):
        self.receipt(n=1); self.ledger(44)
        names = []
        def call(c, models, text, cwd, name):
            names.append(name)
            self.assertIn('synthetic latest stock finding', text)
            return 0
        with patch.object(run, 'opencode', call), self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            run.write_and_attack(self.c, {})
        self.assertEqual(names, [])
        receipt = json.loads((self.root / 'attack-state.json').read_text())
        self.assertEqual(receipt['round'], 1); self.assertTrue(receipt['final_repair'])
        self.assertEqual(self.c.card['stress_review'], {'status': 'unresolved', 'reason': 'budget_exhausted'})

    def test_observed_round_cost_raises_floor(self):
        self.receipt(n=1)
        events = [{'id': 'w', 'role': 'writer', 'invocation': 'builder-1', 'cost': 0, 'list_cost_usd': 10},
                  {'id': 's', 'role': 'stress_tester', 'invocation': 'attacker-1', 'cost': 0, 'list_cost_usd': 2}]
        self.ledger(40, events)
        with patch.object(run, 'opencode') as model, self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            run.write_and_attack(self.c, {})
        model.assert_not_called()
        self.assertEqual(self.c.card['case_budget']['next_round_estimate_usd'], 12)

    def test_legacy_final_repair_changed_case_rereviews_before_writer_n_plus_one(self):
        self.receipt(final=True)
        # A final fix legitimately changes the revision after the stored stress report.
        (self.c.case / 'final-fix.txt').write_text('synthetic previous final fix')
        card = self.public_card()
        changes = restart.raised_limits(card, 50, 3, explicit_budget=True)
        self.c.limits_raised = changes; self.c.card.update(changes)
        names = []
        def call(c, models, text, cwd, name):
            names.append(name)
            if name == 'attacker-3':
                pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).write_text(
                    '{"complete": true, "blocking": ["fresh stock finding"]}')
            elif name == 'builder-4':
                self.assertIn('fresh stock finding', text)
                self.assertNotIn('synthetic latest stock finding', text)
                self.assertIn('round-3.json', text)
                (c.case / 'repair.txt').write_text('synthetic repair')
            else:
                self.assertEqual(name, 'attacker-4')
                pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).write_text('{"complete": true, "blocking": []}')
            return 0
        with patch.object(run, 'opencode', call): run.write_and_attack(self.c, card)
        self.assertEqual(names, ['attacker-3', 'builder-4', 'attacker-4'])
        self.assertEqual(self.c.card['builder_rounds'], 4)
        self.assertEqual(self.c.card['budget_raised'], {'from': None, 'to': 50, 'spent_at_raise': 30.08})
        self.assertTrue((self.c.case / 'final-fix.txt').exists())

    def test_unraised_final_repair_refuses_even_with_historical_raise_record(self):
        self.receipt(final=True)
        self.c.card['budget_raised'] = {'from': 20, 'to': 50, 'spent_at_raise': 21}
        self.c.args.rounds = 8
        with patch.object(run, 'opencode') as model, self.assertRaisesRegex(budget.BudgetError, 'rounds_exhausted'):
            run.write_and_attack(self.c, {})
        model.assert_not_called()

    def test_canary4_final_receipt_rereviews_before_writer(self):
        # Canary 4 wrote round=limit/report=round-limit even when early checks
        # skipped the attacker; it did not write findings_report or awaiting_stress.
        for content in (None, '{bad json', '{"complete": false, "blocking": ["review incomplete"]}',
                        '{"complete": false, "blocking": []}'):
            with self.subTest(content=content):
                self.receipt(final=True)
                path = self.root / 'attacks/round-3.json'
                if content is None: path.unlink()
                else: path.write_text(content)
                self.c.args.rounds = 8
                self.c.card = {'gates': {}}
                self.c.limits_raised = {'rounds_raised': {'from': 3, 'to': 8}}
                (self.c.case / 'final-fix.txt').write_text('canary-4 final fix')
                before = run.attack_binding(self.c)
                calls = []
                def call(c, models, text, cwd, name):
                    calls.append(name)
                    if name == 'attacker-3':
                        self.assertEqual(run.attack_binding(c), before)
                        pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).write_text(
                            '{"complete": true, "blocking": ["fresh synthetic finding"]}')
                    elif name == 'builder-4':
                        self.assertIn('fresh synthetic finding', text)
                        self.assertNotIn('review incomplete', text)
                        self.assertIn('round-3.json', text)
                        (c.case / 'repair.txt').write_text(str(content))
                    else:
                        self.assertEqual(name, 'attacker-4')
                        pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).write_text(
                            '{"complete": true, "blocking": []}')
                    return 0
                # A prior subtest's writer must change the case again.
                (self.c.case / 'repair.txt').unlink(missing_ok=True)
                before = run.attack_binding(self.c)
                with patch.object(run, 'opencode', call): run.write_and_attack(self.c, {})
                self.assertEqual(calls, ['attacker-3', 'builder-4', 'attacker-4'])
                self.assertEqual(self.c.card['resume_rereview']['round'], 3)
                self.assertEqual(self.c.card['stress_review'], {'status': 'completed', 'round': 4})

    def test_resume_rereview_can_pass_without_writer_and_keeps_live_report_guard(self):
        self.receipt(final=True)
        (self.root / 'attacks/round-3.json').unlink()
        self.c.limits_raised = {'rounds_raised': {'from': 3, 'to': 8}}
        def call(c, models, text, cwd, name):
            self.assertEqual(name, 'attacker-3')
            pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).write_text(
                '{"complete": true, "blocking": []}')
        with patch.object(run, 'opencode', call): run.write_and_attack(self.c, {})
        self.assertEqual(self.c.card['stress_review'], {'status': 'completed', 'round': 3})
        self.receipt(final=True)
        (self.root / 'attacks/round-3.json').unlink()
        def missing(c, models, text, cwd, name):
            self.assertEqual(name, 'attacker-3')
            pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).unlink()
        with patch.object(run, 'opencode', missing), self.assertRaisesRegex(
                budget.BudgetError, 'stress_review_unresolved:missing_or_malformed_report'):
            run.write_and_attack(self.c, {})

    def test_live_missing_report_still_stops(self):
        self.c.args.resume = None
        calls = []
        def call(c, models, text, cwd, name):
            calls.append(name)
            if name == 'attacker-1':
                pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).unlink()
            return 0
        with patch.object(run, 'opencode', call), self.assertRaisesRegex(
                budget.BudgetError, 'stress_review_unresolved:missing_or_malformed_report'):
            run.write_and_attack(self.c, {})
        self.assertEqual(calls, ['builder-1', 'attacker-1'])

    def test_missing_report_retry_allows_unraised_resume_and_preserves_explicit_raises(self):
        card = self.public_card('stress_review_unresolved:missing_or_malformed_report', limit=50)
        card.update(recovery_config={'rounds': 8, 'case_budget': 50},
                    budget_raised={'from': None, 'to': 50, 'spent_at_raise': 30},
                    rounds_raised={'from': 3, 'to': 8})
        for args in ('--case-budget 50 --rounds 8', '--case-budget 75', '--rounds 9'):
            self.assertEqual(self.plan(card, args), ('case-test', 60, 7))
        for args in ('', '--case-budget 40 --rounds 3'):
            self.assertEqual(self.plan(card, args), ('case-test', 60, 7))
        for changes in ({'failed_gate': 'G15', 'failed_detail': {'problems': ['real gate failure']}},
                        {'gates': {'G15': 'fail'}}):
            with self.assertRaises(ValueError): self.plan({**card, **changes}, '--case-budget 100 --rounds 9')
        card.pop('budget_raised'); card.pop('rounds_raised')
        self.assertEqual(self.plan(card, '--case-budget 50 --rounds 8'), ('case-test', 60, 7))

    def test_planner_allows_only_explicit_economic_salvage(self):
        for stop, old_limit, spent in [('stress_review_unresolved:rounds_exhausted', None, 30.08),
                                       ('budget_exhausted', 30, 31)]:
            with self.subTest(stop=stop):
                card = self.public_card(stop, spent=spent, limit=old_limit)
                self.assertEqual(self.plan(card, '--case-budget 50'), ('case-test', 60, 7))
                for args in ('', '--case-budget 20', '--rounds 3'):
                    with self.assertRaises(ValueError): self.plan(card, args)
                card['failed_gate'] = 'G5'; card['failed_detail'] = {'problems': ['real defect']}
                with self.assertRaises(ValueError): self.plan(card, '--case-budget 100 --rounds 9')

    def test_rounds_raise_is_recorded_and_same_budget_refuses(self):
        card = self.public_card('budget_exhausted', limit=50)
        changes = restart.raised_limits(card, 50, 8, explicit_rounds=True)
        self.assertEqual(changes, {'rounds_raised': {'from': 3, 'to': 8}})
        with self.assertRaises(ValueError): restart.raised_limits(card, 50, 3, explicit_budget=True)

    def test_completed_writer_survives_budget_boundary_before_stress(self):
        self.receipt(n=1)
        def writer(c, models, text, cwd, name):
            self.assertEqual(name, 'builder-2')
            (c.case / 'repair.txt').write_text('completed synthetic repair')
            self.ledger(51)
            return 0
        with patch.object(run, 'opencode', writer), self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
            run.write_and_attack(self.c, {})
        saved = json.loads((self.root / 'attack-state.json').read_text())
        self.assertTrue(saved['awaiting_stress']); self.assertEqual(saved['round'], 2)
        self.c.args.case_budget = 100
        self.c.limits_raised = {'budget_raised': {'from': 50, 'to': 100, 'spent_at_raise': 51}}
        def tester(c, models, text, cwd, name):
            self.assertEqual(name, 'attacker-2')
            pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).write_text('{"complete": true, "blocking": []}')
            return 0
        with patch.object(run, 'opencode', tester): run.write_and_attack(self.c, {})
        self.assertEqual(self.c.card['stress_review'], {'status': 'completed', 'round': 2})

    def test_recovery_policy_forwards_and_preserves_case_ceiling(self):
        import coordinator
        config = {key: 1 for key in coordinator.CONFIG_FIELDS}
        config.update(version=1, case_budget=75.5)
        card = {'source': 'hunt', 'rotation_slot': 1, 'seed': 7, 'recovery_config': config}
        job = {'args': ['1'], 'roles': {'writer': {'model': 'synthetic/writer', 'effort': 'high'}}}
        argv = coordinator.configuration_args(card, job)
        self.assertEqual(argv[argv.index('--case-budget') + 1], '75.5')
        with self.assertRaises(ValueError):
            coordinator.configuration_args(card, {**job, 'args': ['1', '--case-budget', '100']})

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

    def test_main_midcase_stop_checkpoints_public_budget(self):
        harness = r'''
import json, pathlib, sys
from unittest.mock import patch
import run
root = pathlib.Path(sys.argv[1]); run.HOME=root; run.SEALED=root/'out'; run.BENCH=root/'bench'
run.GATES=['G4', 'G5']; run.bench_manifest=lambda: 'trusted'
import types
run.sh=lambda *a, **kw: types.SimpleNamespace(stdout='synthetic recipient') if kw.get('capture') else 0
run.build_fixture=lambda c: c.case.mkdir(parents=True)
def gate(c):
    c.ledger.parent.mkdir(exist_ok=True)
    c.ledger.write_text(json.dumps({'cost': 0, 'calls': 1, 'events': [], 'list_cost_usd': 51}))
    return True, {'measured': True}
run.g4=gate
run.g5=lambda c: (_ for _ in ()).throw(AssertionError('must not run G5'))
run.seal=lambda c, checkpoint=False: (root/'checkpoint').write_text(str(checkpoint))
run.wipe=lambda c: (_ for _ in ()).throw(AssertionError('must keep checkpoint'))
with patch.object(run.shutil, 'which', return_value='synthetic'), patch.object(sys, 'argv', ['run.py', '--dry-run']):
    run.main()
'''
        result = subprocess.run([sys.executable, '-c', harness, str(self.root)],
            cwd=pathlib.Path(run.__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        card = json.loads(next((self.root / 'out').glob('*.scorecard.json')).read_text())
        self.assertEqual(card['terminal_stop'], 'budget_exhausted')
        self.assertEqual(card['status'], 'stopped'); self.assertEqual((self.root / 'checkpoint').read_text(), 'True')
        self.assertEqual(card['gates'], {'G4': 'pass'})
        self.assertEqual(card['case_budget']['spent_usd'], 51)
        self.assertEqual(card['recovery_config']['case_budget'], 50)
        self.assertEqual(card['recovery_config']['rounds'], 8)

    def test_main_raised_budget_rereviews_changed_case_and_records_public_decision(self):
        harness = r'''
import hashlib, json, pathlib, sys, types
from unittest.mock import patch
import run, worker_release
root=pathlib.Path(sys.argv[1]); run.HOME=root; run.SEALED=root/'out'; run.BENCH=root/'bench'
work=root/'work/case-test'; case=work/'case'
(case/'scenarios/S1').mkdir(parents=True); (work/'logs').mkdir(); (work/'attacks').mkdir()
run.SEALED.mkdir()
for name in ('case.json', 'answer-key.json', 'scenarios/S1/key.json'): (case/name).write_text('{}')
prior={'case':'case-test', 'status':'stopped', 'terminal_stop':'stress_review_unresolved:rounds_exhausted',
    'gates':{}, 'builder_rounds':3, 'recovery_config':{'rounds':3}}
ledger={'cost':.017,'calls':515,'events':[],'list_cost_usd':30.08,'terminal_stop':'complete'}
prior['continuation_budget']=ledger
(work/'scorecard.json').write_text(json.dumps(prior))
(run.SEALED/'case-test.continuation-budget.json').write_text(json.dumps(ledger))
run.prompt=lambda role,text:text; run.run_context=lambda c,**kw:json.dumps(kw)
c=types.SimpleNamespace(work=work,case=case,case_id='case-test',manifest0='trusted',
    args=types.SimpleNamespace(source='hunt'),models={'builder':['writer'],'attacker':['tester']})
(work/'attack-state.json').write_text(json.dumps({'round':3,'round_limit':3,'report':'round-3.json',
    'binding':run.attack_binding(c),'final_repair':True}))
(work/'attacks/round-3.json').write_text('{"complete":false,"blocking":["latest synthetic stress finding"]}')
(case/'final-fix.txt').write_text('preserved prior final fix')
calls=[]
def model(c, models, text, cwd, name):
    calls.append(name)
    if name=='attacker-3':
        pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).write_text(
            '{"complete":true,"blocking":["fresh synthetic stress finding"]}')
    elif name=='builder-4':
        assert 'fresh synthetic stress finding' in text and 'round-3.json' in text
        assert 'latest synthetic stress finding' not in text
        (case/'repair.txt').write_text('new synthetic repair')
    else:
        assert name=='attacker-4'
        pathlib.Path(json.JSONDecoder().raw_decode(text)[0]['report_path']).write_text('{"complete":true,"blocking":[]}')
    return 0
run.opencode=model; run.pick_models=lambda c:{'builder':['writer'],'attacker':['tester']}
run.bench_manifest=lambda:'trusted'; run.sh=lambda *a,**kw:0; run.pilot_homes=lambda:[]
run.g1=lambda c:(True,{'problems':[]}); run.early_checks=lambda c:None; run.early_review=lambda c:None
run.freshness_lines=lambda c:[]; run.ensure_freshness=lambda c:(True,{})
run.validate_and_repair=lambda c:None; run.seal=lambda *a,**kw:None; run.wipe=lambda c:None
worker_release.verify_selected_drivers=lambda *a:{}
with patch.object(run.shutil,'which',return_value='synthetic'), patch.object(sys,'argv',
    ['run.py','--source','hunt','--resume','case-test','--resume-bench-sha','trusted','--case-budget','50','--rounds','8']):
    run.main()
assert calls==['attacker-3','builder-4','attacker-4'], calls
'''
        result = subprocess.run([sys.executable, '-c', harness, str(self.root)],
            cwd=pathlib.Path(run.__file__).parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        card = json.loads((self.root / 'out/case-test.scorecard.json').read_text())
        self.assertNotIn('terminal_stop', card)
        self.assertEqual(card['budget_raised'], {'from': None, 'to': 50, 'spent_at_raise': 30.097})
        self.assertEqual(card['rounds_raised'], {'from': 3, 'to': 8})
        self.assertEqual(card['builder_rounds'], 4)
        self.assertTrue((self.root / 'work/case-test/case/final-fix.txt').exists())

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
