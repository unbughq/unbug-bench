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
import tempfile
import types
from attack_findings import classify

PRIVATE = Path('/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/00d02e9b-ca70-4919-b958-898ec30f1b3a/scratchpad/e15450-open/checkpoint/case-20261024T043353Z-e15450')


class StressLoopTests(unittest.TestCase):
    def harness(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); case = root / 'case'
        (case / 'scenarios/S1').mkdir(parents=True)
        for name in ('case.json', 'answer-key.json', 'scenarios/S1/key.json'):
            (case / name).write_text('{}')
        (case / 'statement.md').write_text('synthetic selected case')
        c = types.SimpleNamespace(work=root, case=case, case_id='synthetic', card={}, seed=7,
            manifest0='synthetic bench revision', models={'builder': ['writer'], 'attacker': ['tester']},
            args=types.SimpleNamespace(dry_run=False, source='hunt', rounds=3, runs=1, scenario_runs=1))
        h = types.SimpleNamespace(c=c)
        for name, value in (('g1', (True, {'problems': []})), ('early_checks', None),
                            ('early_review', None), ('ensure_freshness', None), ('engine_prepare_bench', None)):
            mocked = patch.object(run, name, return_value=value)
            setattr(h, name, mocked.start()); self.addCleanup(mocked.stop)
        return h

    def stress(self, h, result, number=1):
        def categories(c, n, report, receipt, completed):
            report.write_text(json.dumps(result))
            completed()
        with patch.object(run, 'stress_categories', categories):
            return run.engine_stress_round(h.c, number)

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

    def test_unfinished_validation_never_grants_writer_feedback_or_pass(self):
        from durable.contract import Outcome
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                h = self.harness()
                result = {'complete': True, 'blocking': ['review incomplete'] if legacy else []}
                if legacy: result['blocking'].append('Validation unfinished: tester command failed.')
                else: result['unfinished_validation'] = ['A diagnostic was never executed.']
                with patch.object(run, 'opencode') as model:
                    outcome = self.stress(h, result)
                self.assertEqual(outcome, {'outcome': Outcome.INFRA_ERROR,
                                          'reason': 'stress:unfinished_validation'})
                model.assert_not_called()
                h.early_review.assert_not_called()
                self.assertNotEqual(h.c.card.get('stress_review', {}).get('status'), 'completed')

    def test_blocking_defects_precede_unfinished_validation(self):
        from durable.contract import Outcome
        result = {'complete': False, 'blocking': ['Judge raises KeyError on establish.',
                  'Guard reset collides with the baseline function.'],
                  'unfinished_validation': ['No checkpoint or strategy could produce a verdict.']}
        h = self.harness()
        outcome = self.stress(h, result)
        self.assertEqual(outcome['outcome'], Outcome.OK)
        self.assertEqual(outcome['reason'], 'stress:findings')
        self.assertEqual(json.loads(outcome['feedback'])['problems'], result['blocking'])
        self.assertEqual(run.attack_report(h.c.work / 'attacks/round-1.json')['unfinished_validation'],
                         result['unfinished_validation'])
        self.assertEqual(h.c.card['stress_review'], {'status': 'findings', 'round': 1})
        h.early_review.assert_not_called()

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
                 self.assertRaises(type(failure)):
                run.early_cheat_check(h.c)
            self.assertEqual(checkpoint.call_count, 1)

    def test_reopened_cheat_returns_to_writer_before_next_stress_and_is_rechecked(self):
        from durable.contract import Outcome
        h = self.harness(); h.c.seed = 4
        (h.c.case / 'guards/cheats/alpha').mkdir(parents=True)
        calls = []
        def model(c, models, text, cwd, name):
            calls.append(name)
            if name == 'builder-2-fix-1': self.assertIn('Retained cheat passed after repair:', text)
            (c.case / 'repair.txt').write_text(name)
        records = [({}, [{'errors': [], 'checker': {'valid': True},
                          'judge': {'checks': {'synthetic': value}, 'paths': {}}}])
                   for value in (True, False)]
        with patch.object(run, 'opencode', model), \
             patch.object(run, 'checkpoint', side_effect=records) as checkpoint, \
             patch.object(run, 'case_budget_boundary'), \
             patch.object(run.GatePipeline, 'check', return_value=(True, {})), \
             patch.object(run, 'public_progress'), patch.object(run, 'log'):
            h.early_checks.side_effect = lambda c: run._gate_pipeline().early_checks(c)
            outcome = run.engine_writer_round(h.c, 2, run._feedback('stress', ['A synthetic defect.']))
        self.assertEqual(outcome['outcome'], Outcome.OK)
        self.assertEqual(calls, ['builder-2', 'builder-2-fix-1'])
        self.assertEqual(checkpoint.call_count, 2)
        self.assertNotIn('G6', h.c.early)
        self.assertNotIn('stress_review', h.c.card)
        self.assertEqual(self.stress(h, {'complete': True, 'blocking': []}, 2)['reason'], 'stress:clean')
        state = json.loads((h.c.work / 'attack-state.json').read_text())
        self.assertEqual(state['round'], 2)
        self.assertEqual(state['binding'], run.attack_binding(h.c))
        self.assertFalse(state['review_pending'])

    def test_saved_cheat_allowance_leaves_rest_unchecked_without_infra(self):
        from run_validity import retry
        h = self.harness(); h.c.seed = 5
        for name in ('alpha', 'beta', 'gamma'):
            (h.c.case / 'guards/cheats' / name).mkdir(parents=True)
        record = {'errors': [], 'checker': {'valid': True}, 'judge': {'checks': {'synthetic': False}, 'paths': {}}}
        runs = []
        def command(c, args, **kw):  # alpha completes, beta's run outlives the allowance
            runs.append(kw['timeout'])
            if len(runs) == 2: raise subprocess.TimeoutExpired(args, kw['timeout'])
            return types.SimpleNamespace()
        with patch.object(run, 'sh', command), patch.object(run, 'case_budget_boundary'), \
             patch.object(run, 'tree_digest', return_value='d'), patch.object(run, 'case_hash', return_value='h'), \
             patch('checkpoint_evidence.read_completed', return_value=({}, [record], None)), \
             patch.object(run.GatePipeline, 'record_crash') as crash:
            problems = run.early_cheat_check(h.c)
        self.assertIsNone(problems)
        self.assertEqual(len(runs), 2)  # beta's retry never started on a spent allowance; gamma never ran
        crash.assert_not_called()
        self.assertEqual(h.c.card['early_gates']['saved_cheats'],
                         {'ok': True, 'checked': 1, 'unchecked': 2, 'runs_each': 1})
        attempts = json.loads((h.c.work / 'infra-attempts.json').read_text())
        self.assertTrue(all(row['invalid_attempts'] == 0 for row in attempts.values()))
        # Full G6 passes no deadline: a timeout there is still an infrastructure failure.
        with patch.object(run, 'checkpoint', side_effect=subprocess.TimeoutExpired('x', 1)), \
             self.assertRaises(subprocess.TimeoutExpired):
            run.cheat_runs(h.c, 5, 'g6')

    def test_writer_hands_back_findings_instead_of_starting_a_doomed_cycle(self):
        from durable.contract import Outcome
        from durable.policy import WRITER_HANDBACK
        h = self.harness()
        calls, prompts = [], {}
        def model(c, models, text, cwd, name):
            calls.append(name); prompts[name] = text
            (c.case / 'repair.txt').write_text(name)
        h.early_checks.side_effect = [['early check G4 failed: synthetic'], None]
        feedback = run._feedback('stress', ['A synthetic defect.'])
        # Attempt 1: ten minutes left after the first cycle, below the cycle reserve.
        h.c.engine = types.SimpleNamespace(deadline_monotonic=run.time.monotonic() + 600,
                                           source_binding={'feedback': 'f'})
        with patch.object(run, 'opencode', model):
            first = run.engine_writer_round(h.c, 2, feedback)
        self.assertEqual(first, {'outcome': Outcome.OK, 'reason': WRITER_HANDBACK})
        self.assertEqual(calls, ['builder-2'])
        state = json.loads((h.c.work / 'attack-state.json').read_text())
        self.assertEqual(state['handback']['call'], 2)
        self.assertEqual(state['handback']['problems'], ['early check G4 failed: synthetic'])
        # A STRESS step that finds this pending handback (an engine without the retry patch advanced
        # it) stops as infrastructure instead of attacking an unvalidated case.
        with patch.object(run, 'stress_categories') as attack:
            self.assertEqual(run.engine_stress_round(h.c, 2),
                             {'outcome': Outcome.INFRA_ERROR, 'reason': 'stress:writer_handback_pending'})
        attack.assert_not_called()
        # Attempt 2 continues at call 2 with the early-check findings, not the stress feedback.
        h.c.engine.deadline_monotonic = run.time.monotonic() + 14400
        with patch.object(run, 'opencode', model):
            second = run.engine_writer_round(h.c, 2, feedback)
        self.assertEqual(second, {'outcome': Outcome.OK, 'reason': 'writer:validated'})
        self.assertEqual(calls, ['builder-2', 'builder-2-fix-1'])
        self.assertIn('early check G4 failed: synthetic', prompts['builder-2-fix-1'])
        self.assertNotIn('handback', json.loads((h.c.work / 'attack-state.json').read_text()))

    def test_writer_keeps_cycling_when_time_remains(self):
        from durable.contract import Outcome
        h = self.harness()
        h.early_checks.side_effect = [['early check G4 failed: synthetic'], None]
        h.c.engine = types.SimpleNamespace(deadline_monotonic=run.time.monotonic() + 14400, source_binding={})
        calls = []
        def model(c, models, text, cwd, name):
            calls.append(name); (c.case / 'repair.txt').write_text(name)
        with patch.object(run, 'opencode', model):
            self.assertEqual(run.engine_writer_round(h.c, 1, None)['reason'], 'writer:validated')
        self.assertEqual(calls, ['builder-1', 'builder-1-fix-1'])

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
