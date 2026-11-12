"""Real collected aggregates, synthetic evidence only; no model or plaintext access."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'factory'), str(Path(__file__).parent)]
import run
import g11_review
import model_runtime
import model_router
from router_test_support import offline_router
_ROUTING = offline_router()
from test_freshness_restore_fixes import FreshnessRestoreTests


class ConfirmDeadlineTests(FreshnessRestoreTests):
    def test_a_slow_route_gets_three_minutes_to_answer_its_availability_check(self):
        seen = []
        self.c.models = {'builder': ['b'], 'attacker': ['a'], 'reviewers': [['r']], 'strong_calibrator': ['s'], 'easy_calibrator': ['e']}
        with patch.object(run, 'opencode', lambda *args, **kw: seen.append(kw['timeout']) or 0):
            run.provider_preflight(self.c)
        self.assertEqual(seen, [180] * 4)

    def test_the_stress_cap_stays_on_stress_review_and_off_freshness_search(self):
        self.c.args.agent_timeout = 14400
        self.assertEqual(model_runtime.role_timeout(self.c, 'attacker-freshness', 9000), 9000)
        self.assertEqual(model_runtime.role_timeout(self.c, 'attacker-1', 9000), model_runtime.attacker_timeout(self.c))
        self.assertEqual(model_runtime.role_timeout(self.c, 'builder-selection-1', None), None)

    def test_under_the_engine_only_the_attempt_deadline_bounds_a_confirmation(self):
        import time, types
        self.c.engine = types.SimpleNamespace(deadline_monotonic=time.monotonic() + 14000)
        self.addCleanup(lambda: delattr(self.c, 'engine'))
        self.assertGreater(run.confirm_timeout(self.c, 20), 13000)

    def test_a_progressing_freshness_search_keeps_the_attempt_deadline(self):
        """The 6 November stop: both roles shared 20 minutes and a busy search hit it."""
        import time, types
        (self.c.case / 'statement.md').write_text('statement')
        self.c.engine = types.SimpleNamespace(deadline_monotonic=time.monotonic() + 14000)
        self.addCleanup(lambda: delattr(self.c, 'engine'))
        windows = []
        def search(c, models, text, cwd, name, **kw):
            windows.append((name, kw['deadline'] - time.monotonic()))
        self.c.models = {'builder': ['m'], 'attacker': ['m']}
        with patch.object(run, 'opencode', search), patch.object(run, 'case_budget_boundary'), \
                patch.object(run, 'freshness_lines', return_value=[]), patch.object(run, 'run_context', return_value=''), \
                patch.object(run, 'finish_freshness_repair'):
            run.freshness_topup(self.c)
        self.assertEqual([name for name, _ in windows], ['builder-freshness', 'attacker-freshness'])
        self.assertTrue(all(seconds > 13000 for _, seconds in windows), windows)

    def test_deadline_formula_cap_and_agent_timeout(self):
        self.addCleanup(offline_router()[0].close)
        for rows, agent, seconds in ((1,14400,420),(5,14400,900),(20,14400,1800),(10,600,600)):
            self.c.args.agent_timeout = agent
            self.assertEqual(run.confirm_timeout(self.c, rows), seconds)

    def cards(self):
        for label, counts in [('canary6', (56, 5, 16, 0, 900)), ('c7d405', (40, 10, 7, 2, 1500))]:
            card = json.loads((Path(__file__).parent / f'fixtures/{label}-confirm-timeout-card.json').read_text())
            info = card['admission_freshness']
            self.assertEqual((info['searches'], info['flagged_hits'], info['invalid_evidence'],
                              card['freshness_repair']['attempts']), counts[:4])
            self.assertEqual(info['unresolved_hits'], counts[1])
            self.assertEqual(info['invalid_evidence_reasons'], {'evidence_expired': counts[2]})
            yield card, counts[-1]

    def prepare(self, card):
        self.c.card = copy.deepcopy(card)
        self.c.case_id = card['case']
        self.c.args.resume = card['case']
        state = {**card['freshness_repair'], 'statement_sha256': hashlib.sha256(
            (self.c.case / 'statement.md').read_bytes()).hexdigest()}
        (self.c.work / 'freshness-repair.json').write_text(json.dumps(state))
        self.rows = [dict(self.rows[i % 8], query=f'Synthetic search {i}',
                          url=f'https://github.com/example/project/issues/{i}', hit=i < card['admission_freshness']['flagged_hits'])
                     for i in range(card['admission_freshness']['searches'])]
        self.save()
        for name in ('freshness-verdict.json', 'public-search.json'):
            (self.c.work / name).unlink(missing_ok=True)
        return state


    def test_in_loop_real_url_counts_get_same_deadlines(self):
        self.addCleanup(offline_router()[0].close)
        for card, seconds in self.cards():
            self.prepare(card)
            self.result['freshness_review'] = [self.rows[0]['url']]
            with patch.object(run, 'opencode', side_effect=run.BudgetError('timeout')) as call:
                with self.assertRaisesRegex(run.BudgetError, '^timeout$'):
                    run.loop_freshness(self.c, self.result, self.report)
            self.assertEqual(call.call_args.kwargs['timeout'], seconds)

    def test_deadline_floor_cap_and_agent_limit(self):
        self.addCleanup(offline_router()[0].close)
        for count, agent, expected in [(0, 14400, 300), (5, 14400, 900), (10, 14400, 1500),
                                        (100, 14400, 1800), (10, 600, 600), (1, 60, 60)]:
            self.c.args.agent_timeout = agent
            self.assertEqual(run.confirm_timeout(self.c, count), expected)

    def test_file_and_fix_review_deadlines_scale_and_obey_operator_limit(self):
        self.addCleanup(offline_router()[0].close)
        self.c.args.agent_timeout = 14400
        files = sum(p.is_file() for p in self.c.case.rglob('*'))
        self.assertEqual(model_runtime.attacker_timeout(self.c), 1200 + 60 * files)
        guard = self.c.work / 'guard'; guard.mkdir()
        (guard / 'fix.py').touch()
        self.assertEqual(g11_review.audit_timeout(self.c, [guard]), 1200 + 30 * max(0, files - 1))
        self.assertEqual(g11_review.audit_timeout(self.c, [guard, guard]),
                         1500 + 30 * files)
        for i in range(100): (guard / f'file-{i}').touch()
        self.assertEqual(g11_review.audit_timeout(self.c, [guard]), 3600)
        for i in range(100): (self.c.case / f'file-{i}').touch()
        self.assertEqual(model_runtime.attacker_timeout(self.c), 2400)
        self.c.args.agent_timeout = 60
        self.assertEqual(g11_review.audit_timeout(self.c, [guard]), 60)
        self.assertEqual(model_runtime.attacker_timeout(self.c), 60)

    def test_killed_full_shaped_partial_verdict_is_reasked(self):
        self.addCleanup(offline_router()[0].close)
        self.retain_verdict(self.answer())
        with patch.object(run, 'opencode', side_effect=self.reviewer) as call:
            run.loop_freshness(self.c, self.result, self.report)
        call.assert_called_once()

    def test_confirmation_fallback_shares_one_wall_deadline(self):
        self.addCleanup(offline_router()[0].close)
        card, seconds = next(self.cards())
        self.prepare(card)
        primary = "opencode/glm-5.3-flash-free"
        self.c.models['reviewers'] = [[primary]]
        self.c.card.setdefault('roles', {}).setdefault('reviewer', {})['model'] = primary
        runtime = model_runtime.ModelRuntime(self.c.work, None, lambda *a: None, None, None)
        now = [1000]
        seen = []
        def invoke(ctx, models, text, cwd, name, **kwargs):
            seen.append(kwargs['timeout'])
            if len(seen) == 1:
                now[0] += seconds - 10
                raise run.BudgetError('provider_limit')
            self.assertEqual(kwargs['deadline'], 1000 + seconds)
            self.assertEqual(kwargs['timeout'], 10)
            raise run.BudgetError('timeout')
        def call(ctx, models, text, cwd, name, **kwargs):
            return runtime.call(ctx, models, text, cwd, name, **kwargs)
        with patch.object(model_runtime.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=invoke), \
             patch.object(run, 'opencode', side_effect=call):
            with self.assertRaisesRegex(run.BudgetError, '^timeout$'):
                run.ensure_freshness(self.c)
        self.assertEqual(seen, [seconds, 10])

    def test_fallback_cannot_certify_failed_primary_partial_verdict(self):
        self.addCleanup(offline_router()[0].close)
        primary = "opencode/glm-5.3-flash-free"
        self.c.models['reviewers'] = [[primary]]
        self.c.card.setdefault('roles', {}).setdefault('reviewer', {})['model'] = primary
        runtime = model_runtime.ModelRuntime(self.c.work, None, lambda *a: None, None, None)
        seen = []
        def invoke(ctx, models, text, cwd, name, **kwargs):
            out = Path(cwd) / 'verdict.json'
            self.assertFalse(out.exists(), 'previous provider output survived')
            seen.append(models[0])
            if len(seen) == 1:
                out.write_text(json.dumps({'hits': [self.answer()]}))
                raise run.BudgetError('provider_limit')
            return 0  # provider completed without producing an answer
        def call(ctx, models, text, cwd, name, **kwargs):
            return runtime.call(ctx, models, text, cwd, name, **kwargs)
        with patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=invoke), \
             patch.object(run, 'opencode', side_effect=call):
            with self.assertRaisesRegex(run.BudgetError, '^freshness_unresolved$'):
                run.loop_freshness(self.c, self.result, self.report)
        # The chain starts at the Go plan (founder 2026-11-09); the first account's limit moves it to the second.
        self.assertEqual(seen, ["opencode-go/glm-5.3-flash"] * 2)
        self.assertFalse((self.c.work / 'freshness-verdict.json').exists())

    def test_confirm_timeout_preserves_repair_allowance_and_retries_confirmation(self):
        self.addCleanup(offline_router()[0].close)
        for card, seconds in self.cards():
            state = self.prepare(card)
            self.result['freshness_review'] = [self.rows[0]['url']]
            with patch.object(run, 'opencode', side_effect=run.BudgetError('timeout')) as call:
                for _ in range(2):
                    with self.assertRaisesRegex(run.BudgetError, '^timeout$'):
                        run.loop_freshness(self.c, self.result, self.report)
                    self.assertEqual(json.loads((self.c.work / 'freshness-repair.json').read_text()), state)
                self.assertEqual([v.args[4] for v in call.call_args_list], ['reviewer-g2-confirm'] * 2)
                self.assertTrue(all(v.kwargs['timeout'] == seconds for v in call.call_args_list))


if __name__ == '__main__': unittest.main()
