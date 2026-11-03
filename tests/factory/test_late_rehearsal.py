"""Offline rehearsal admission and writer/gate repair regressions; no model calls."""
import json
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'factory'), str(ROOT/'bin'), str(ROOT/'tests/factory'), str(ROOT/'tests/bench')]
import budget
import late_rehearsal
import run
import test_case_budget as fixtures


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CaseBudgetTests('test_transient_review_resume_rereviews_same_round_without_raise')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.c = c = self.fixture.c
        c.case_id = 'case-late-rehearsal-synthetic'
        c.args = run.argument_parser().parse_args([
            '--source', 'plant', '--late-gate-rehearsal', '--no-concurrent-roles',
            '--no-early-probe', '--pilot-tries', '1', '--runs', '1', '--pilot-runs', '1',
            '--calibrator-minutes', '3', '--case-budget', '25', '--max-cost', '25'])
        (c.work/'rehearsal-source.json').write_text(json.dumps({'kind':'public-practice', 'real_case':False}))

    def test_25_accepted_25_01_rejected(self):
        late_rehearsal.check(self.c)
        self.c.args.case_budget = 25.01
        with self.assertRaisesRegex(ValueError, r'<=\$25'):
            late_rehearsal.check(self.c)

    def test_other_rehearsal_admission_guards_remain(self):
        for name, value in (('dry_run', True), ('concurrent_roles', True), ('pilot_tries', 2),
                            ('runs', 2), ('pilot_runs', 2), ('calibrator_minutes', 3.01),
                            ('no_early_probe', False)):
            with self.subTest(name=name), patch.object(self.c.args, name, value), self.assertRaises(ValueError):
                late_rehearsal.check(self.c)

    def test_real_bundle_args_pass_production_parser_and_rehearsal_guard(self):
        bundle = ROOT.parent/'unbug-bench-late-rehearsal-20261026'
        if not (bundle/'live.py').is_file():
            self.skipTest('prepared public rehearsal bundle is not installed')
        # Import only module definitions; never instantiate Live or execute transport.
        with patch.dict(os.environ), patch.dict(sys.modules), patch.object(sys, 'path', [str(bundle), *sys.path]):
            live = runpy.run_path(str(bundle/'live.py'))
        args = run.argument_parser().parse_args(live['ARGS'])
        late_rehearsal.check(SimpleNamespace(args=args, case_id=live['CASE'], work=bundle/live['CASE'], card={}))
        self.assertEqual(args.case_budget, 25)
        self.assertGreaterEqual(args.max_cost, args.case_budget)
        self.assertEqual((args.rounds, args.max_repairs), (8, 2))
        self.assertEqual((args.agent_timeout, args.no_progress_minutes), (14400, 45))
        self.assertEqual((args.max_total_calls, args.max_role_calls), (1000, 400))

    def test_25_reserves_writer_repairs_past_round_two(self):
        c = self.c
        # The observed attempt-9 spend; priced spend above the old independent $5 cap.
        self.fixture.ledger(2.57, cost=5.5)
        calls = []
        def model(ctx, models, text, cwd, name):
            calls.append(name)
            if name.startswith('builder-'):
                (c.case/'repair.txt').write_text(name)
            else:
                n = int(name.rsplit('-', 1)[1])
                (c.work/f'attacks/round-{n}.json').write_text(json.dumps({
                    'complete':True, 'blocking':['synthetic defect'] if n < 3 else []}))
            return 0
        with patch.object(run, 'opencode', side_effect=model):
            run.write_and_attack(c, {})
        self.assertEqual(calls, [f'{role}-{n}' for n in range(1, 4) for role in ('builder', 'attacker')])
        self.assertEqual(c.card['stress_review'], {'status':'completed', 'round':3})

    def test_gate_defect_gets_writer_and_stress_repair_before_g10(self):
        c = self.c
        c.args.resume = c.case_id
        c.stopped = False
        calls = []
        def model(ctx, models, text, cwd, name):
            calls.append(name)
            if name.startswith('builder-'):
                (c.case/'repair.txt').write_text(name)
            else:
                n = int(name.rsplit('-', 1)[1])
                (c.work/f'attacks/round-{n}.json').write_text('{"complete":true,"blocking":[]}')
            return 0
        def gates(ctx):
            calls.append('gates')
            if calls.count('gates') == 1:
                c.card.update(failed_gate='G16', failed_detail={'defect':'synthetic'})
                c.card['gates']['G16'] = 'fail'
            else:
                c.card['gates'].update(G16='pass', G10='pass')
        with patch.object(run, 'run_gates', side_effect=gates), patch.object(run, 'opencode', side_effect=model):
            run.validate_and_repair(c)
        self.assertEqual(calls, ['gates', 'builder-1', 'attacker-1', 'gates'])
        self.assertEqual(c.card['gates']['G10'], 'pass')
        self.assertEqual(c.card['repairs'], [{'attempt':1, 'failed_gate':'G16'}])

    def test_priced_ceiling_5_stops_below_case_25_but_25_admits(self):
        c = self.c
        # A local synthetic emitter exercises the real monitor, never a model CLI.
        for ceiling in (5, 25):
            with self.subTest(ceiling=ceiling):
                self.fixture.ledger(2.57, cost=5.5)
                kwargs = dict(max_cost=ceiling, max_total_calls=c.args.max_total_calls,
                    max_calls=c.args.max_role_calls, case_budget=c.args.case_budget)
                event = dict(type='step_finish', sessionID='offline', part=dict(
                    id='synthetic', messageID='synthetic', cost=.01, reason='stop',
                    tokens=dict(input=10, output=20, reasoning=0, cache=dict(read=0, write=0))))
                args = ([sys.executable, '-c', 'print(' + repr(json.dumps(event)) + ')'], c.work, os.environ.copy(),
                        c.work/'synthetic-stream', c.ledger, 3)
                if ceiling == 5:
                    with self.assertRaisesRegex(budget.BudgetError, 'cost_limit'):
                        budget.run_budgeted(*args, **{**kwargs, 'containment': False})
                else:
                    self.assertEqual(budget.run_budgeted(*args, **{**kwargs, 'containment': False}).returncode, 0)


if __name__ == '__main__':
    unittest.main()
