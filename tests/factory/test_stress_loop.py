"""Typed stress feedback and retained-cheat repair regressions; private replay is optional."""
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory'), str(ROOT / 'tests/bench')]
import json
import subprocess
import unittest
from unittest.mock import patch
import run
import test_attack_recovery as recovery
from attack_findings import classify

PRIVATE = Path('/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/00d02e9b-ca70-4919-b958-898ec30f1b3a/scratchpad/e15450-open/checkpoint/case-20261024T043353Z-e15450')


class StressLoopTests(unittest.TestCase):
    def harness(self):
        h = recovery.AttackRecoveryTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        return h

    def test_typed_and_legacy_classification_is_conservative(self):
        operational = 'Validation unfinished: a tester patch could not be applied.'
        defect = 'A broken guard passes when customer labels have punctuation.'
        result = classify({'complete': False, 'blocking': [operational, defect],
                           'unfinished_validation': ['A tool returned no result.']})
        self.assertEqual(result['blocking'], [defect])
        self.assertEqual(result['unfinished_validation'], ['A tool returned no result.', operational])
        for text in ('diagnostic problem may hide a case defect', 'The guard exploits a tool error',
                     'review incomplete', defect):
            self.assertEqual(classify({'complete': True, 'blocking': [text]})['blocking'], [text])
        for values in (None, {}, [False], ['']):
            self.assertIsNone(classify({'complete': True, 'blocking': [], 'unfinished_validation': values}))

    def test_live_and_resumed_unfinished_validation_never_reach_writer_or_pass(self):
        for legacy in (False, True):
            for resume in (False, True):
                with self.subTest(legacy=legacy, resume=resume):
                    h = self.harness()
                    result = {'complete': True, 'blocking': ['review incomplete'] if legacy else []}
                    if legacy: result['blocking'].append('Validation unfinished: tester command failed.')
                    else: result['unfinished_validation'] = ['A diagnostic was never executed.']
                    calls = []
                    def model(c, models, text, cwd, name):
                        calls.append(name)
                        self.assertEqual(name, 'attacker-1')
                        h.report_path(text).write_text(json.dumps(result))
                    if resume:
                        h.interrupt(result)
                    with patch.object(run, 'opencode', model), self.assertRaisesRegex(
                            run.BudgetError, 'stress_review_unresolved:unfinished_validation'):
                        run.build(h.c)
                    self.assertEqual(calls, [] if resume else ['attacker-1'])
                    h.early_review.assert_not_called()
                    h.doCleanups()

    def test_blocking_defects_precede_unfinished_validation_live_and_saved(self):
        # Synthetic shape of attempt 5: broken judge/reset prevented diagnostics.
        result = {'complete': False, 'blocking': ['Judge raises KeyError on establish.',
                  'Guard reset collides with the baseline function.'],
                  'unfinished_validation': ['No checkpoint or strategy could produce a verdict.']}
        for resume in (False, True):
            with self.subTest(resume=resume):
                h = self.harness()
                if resume: h.interrupt(result)
                calls = []
                def model(c, models, text, cwd, name):
                    calls.append(name)
                    if name == 'builder-2':
                        self.assertIn(result['blocking'][0], text)
                        (c.case / 'repair.txt').write_text('judge and reset repaired')
                    else:
                        h.report_path(text).write_text(json.dumps(result if name == 'attacker-1'
                            else {'complete': True, 'blocking': []}))
                with patch.object(run, 'opencode', model): run.build(h.c)
                self.assertEqual(calls, ([] if resume else ['attacker-1']) + ['builder-2', 'attacker-2'])
                self.assertEqual(h.c.card['stress_review'], {'status': 'completed', 'round': 2})
                h.early_review.assert_called_once()
                h.doCleanups()

    def test_mixed_report_at_round_limit_cannot_grant_stress_pass(self):
        h = self.harness(); h.c.args.rounds = 1
        h.interrupt({'complete': False, 'blocking': ['Broken judge.'],
                     'unfinished_validation': ['Diagnostics blocked.']})
        with patch.object(run, 'opencode', return_value=0) as model, self.assertRaisesRegex(
                run.BudgetError, 'rounds_exhausted'):
            run.build(h.c)
        self.assertEqual([call.args[4] for call in model.call_args_list], ['builder-precheck'])
        h.early_review.assert_not_called()
        self.assertEqual(h.c.card['stress_review']['status'], 'unresolved')

    def test_early_saved_cheats_run_once_each_and_reopenings_are_writer_feedback(self):
        h = self.harness()
        for name in ('alpha', 'beta'):
            (h.c.case / 'guards/cheats' / name).mkdir(parents=True)
        record = {'errors': [], 'checker': {'valid': True},
                  'judge': {'checks': {'synthetic': True}, 'paths': {}}}
        h.c.seed = 3
        with patch.object(run, 'checkpoint', return_value=({}, [record])) as checkpoint, \
             patch.object(run, 'case_budget_boundary'), \
             patch.object(run.GatePipeline, 'check', return_value=(True, {})), \
             patch.object(run, 'public_progress'), patch.object(run, 'log'):
            problems = run._gate_pipeline().early_checks(h.c)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all('Retained cheat passed after repair:' in p for p in problems))
        self.assertEqual([call.args[2].name for call in checkpoint.call_args_list], ['alpha', 'beta'])
        self.assertTrue(all(call.args[3] == 1 and 0 < call.kwargs['timeout'] <= 1800
                            for call in checkpoint.call_args_list))
        self.assertEqual(h.c.early, {})
        self.assertFalse((h.c.work / 'gate-cache/G6.json').exists())

    def test_saved_cheat_invalid_or_timeout_stops_without_writer_finding(self):
        h = self.harness(); h.c.seed = 2
        (h.c.case / 'guards/cheats/alpha').mkdir(parents=True)
        for failure in (subprocess.TimeoutExpired('synthetic', 1), RuntimeError('no receipt')):
            with self.subTest(failure=type(failure).__name__), \
                 patch.object(run, 'checkpoint', side_effect=failure) as checkpoint, \
                 patch.object(run, 'case_budget_boundary'), \
                 patch.object(run.GatePipeline, 'record_crash'), \
                 self.assertRaisesRegex(run.BudgetError, 'unfinished_saved_cheats'):
                run.early_cheat_check(h.c)
            self.assertEqual(checkpoint.call_count, 1)

    def test_reopened_cheat_returns_to_writer_before_next_stress_and_is_rechecked(self):
        h = self.harness(); h.c.seed = 4; h.c.args.rounds = 3
        (h.c.case / 'guards/cheats/alpha').mkdir(parents=True)
        h.interrupt({'complete': True, 'blocking': ['A synthetic defect.']})
        calls = []
        def model(c, models, text, cwd, name):
            calls.append(name)
            if name.startswith('builder-'):
                if name == 'builder-3': self.assertIn('Retained cheat passed after repair:', text)
                (c.case / 'repair.txt').write_text(name)
            else:
                self.assertEqual(name, 'attacker-3')
                h.report_path(text).write_text('{"complete": true, "blocking": []}')
        records = [({}, [{'errors': [], 'checker': {'valid': True},
                          'judge': {'checks': {'synthetic': value}, 'paths': {}}}])
                   for value in (True, False)]
        with patch.object(run, 'opencode', model), \
             patch.object(run, 'checkpoint', side_effect=records) as checkpoint, \
             patch.object(run, 'case_budget_boundary'), \
             patch.object(run.GatePipeline, 'check', return_value=(True, {})), \
             patch.object(run, 'public_progress'), patch.object(run, 'log'):
            h.early_checks.side_effect = lambda c: run._gate_pipeline().early_checks(c)
            run.build(h.c)
        self.assertEqual(calls, ['builder-2', 'builder-3', 'attacker-3'])
        self.assertEqual(checkpoint.call_count, 2)
        self.assertNotIn('G6', h.c.early)
        state = json.loads((h.c.work / 'attack-state.json').read_text())
        self.assertEqual(state['round'], 3)
        self.assertEqual(state['binding'], run.attack_binding(h.c))
        self.assertFalse(state['review_pending'])

    def test_final_repair_gets_early_validation_without_granting_stress_pass(self):
        h = self.harness(); h.c.args.rounds = 1
        h.interrupt({'complete': True, 'blocking': ['A synthetic defect.']})
        with patch.object(run, 'opencode', return_value=0), \
             self.assertRaisesRegex(run.BudgetError, 'rounds_exhausted'):
            run.build(h.c)
        h.early_checks.assert_called_once()
        self.assertEqual(h.c.card['stress_review']['status'], 'unresolved')

    @unittest.skipUnless(os.environ.get('UNBUG_PRIVATE_REPLAY') == '1' and PRIVATE.is_dir(), 'private e15450 replay artifacts absent')
    def test_private_e15450_replay(self):
        reports = {int(p.stem.split('-')[1]): run.attack_report(p)
                   for p in (PRIVATE / 'attacks').glob('round-*.json')}
        self.assertEqual(len(reports), 7)
        self.assertTrue(all(report is not None for report in reports.values()))
        self.assertEqual(sum(len(report['blocking']) for report in reports.values()), 8)
        self.assertEqual(sum(len(report['unfinished_validation']) for report in reports.values()), 3)
        for n in (3, 6, 7):
            with self.subTest(round=n):
                raw = json.loads((PRIVATE / 'attacks' / f'round-{n}.json').read_text())
                self.assertIsNotNone(reports[n])
                # Compare real entries without exposing their text in assertion failures.
                self.assertTrue(reports[n]['unfinished_validation'] == raw['blocking'][:1])
                self.assertTrue(reports[n]['blocking'] == raw['blocking'][1:])
        for n in (8, 9):
            self.assertEqual(len(reports[n]['blocking']), 1)
            self.assertEqual(reports[n]['unfinished_validation'], [])


if __name__ == '__main__': unittest.main()
