"""Exhausted-round pause recovery: public policy and authenticated review order."""
import copy
import hashlib
import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO/'factory'),str(REPO/'tests/factory'),str(REPO/'bin'),str(REPO/'tests/bench')]
import key_holder
import restart
import run


class PausedRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        sealed = self.root/'sealed'; sealed.mkdir()
        case = 'case-paused-fixture'
        archive = sealed/(case+'.checkpoint.tar.gz.age')
        archive.write_bytes(b'synthetic encrypted checkpoint')
        self.path = sealed/(case+'.scorecard.json')
        self.card = {'case':case,'seed':42,'status':'stopped','terminal_stop':'paused',
                     'failed_gate':None,'gates':{},'roles':{},'builder_rounds':8,
                     'recovery_config':{'rounds':8,'case_budget':50},
                     'case_budget':{'limit_usd':50},'rounds_raised':{'from':3,'to':8},
                     'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
                     'continuation_budget':{'calls':20,'cost':.2,'events':[],
                                            'list_cost_usd':38.94,'terminal_stop':'PauseRequested'}}
        self.job = {'case':case,'mode':'case','card':self.path.name,'archive_prefix':case,
                    'roles':{},'max_calls':100,'max_cost':5,'args':[]}

    def policies(self, card, options, accepted):
        self.path.write_text(json.dumps(card))
        args = ['1','--restore',card['case'],*shlex.split(options)]
        for name, check in [('planner',lambda:restart.plan(self.path,0,28800,shlex.join(args))),
                            ('holder',lambda:key_holder.current_generation({**self.job,'args':args}))]:
            with self.subTest(policy=name,options=options), patch.object(key_holder,'ROOT',self.root):
                if accepted:
                    result = check()
                    self.assertEqual(result, (card['case'],60,42) if name=='planner' else card['sha256'])
                else:
                    with self.assertRaises(ValueError): check()

    def test_explicit_round_raise_accepts_both_policies_and_preserves_card(self):
        original = copy.deepcopy(self.card)
        for options in ('--case-budget 50 --rounds 9','--case-budget=50 --rounds=9'):
            self.policies(self.card,options,True)
        self.assertEqual(restart.raised_limits(self.card,50,9,explicit_rounds=True),
                         {'rounds_raised':{'from':8,'to':9}})
        self.assertEqual(self.card,original)

    def test_authenticated_final_gate_phase_allows_unchanged_exhausted_round_cap(self):
        card={**self.card,'gate_continuation':dict(version=1,phase='final_gates',round=8,
            case_sha256='a'*64,stress_receipt_sha256='b'*64,report_sha256='c'*64)}
        self.policies(card,'--case-budget 50 --rounds 8',True)
        self.assertEqual(restart.raised_limits(card,50,8),{})

    def test_unraised_exhausted_pause_is_refused_by_both(self):
        for options in ('','--rounds 8','--rounds=7','--case-budget 60',
                        '--case-budget 60 --rounds 8','--rounds 9 --rounds 8'):
            self.policies(self.card,options,False)
        # Merely passing a larger numeric value without the explicit flag is
        # insufficient, as are historical raises already published on the card.
        with self.assertRaises(ValueError):
            restart.raised_limits(self.card,50,9,explicit_rounds=False)

    def test_raise_must_exceed_both_saved_cap_and_completed_count(self):
        card = {**self.card,'builder_rounds':9}
        self.policies(card,'--rounds 9',False)
        self.policies(card,'--rounds 10',True)
        self.assertEqual(restart.raised_limits(card,50,10,explicit_rounds=True),
                         {'rounds_raised':{'from':9,'to':10}})

    def test_explicit_raise_cannot_mask_failed_gate_or_budget(self):
        for changes in ({'failed_gate':'G15','gates':{'G15':'fail'}},
                        {'gates':{'G15':'fail'}}, {'checkpoint_error':'OSError'},
                        {'continuation_budget':{**self.card['continuation_budget'],'list_cost_usd':50}},
                        {'continuation_budget':{**self.card['continuation_budget'],'terminal_stop':'cost_limit'}}):
            with self.subTest(changes=changes):
                self.policies({**self.card,**changes},'--case-budget 50 --rounds 9',False)

    def test_raised_pause_rereviews_round_seven_before_writer_eight(self):
        import test_case_budget as fixtures
        fixture = fixtures.CaseBudgetTests('test_transient_review_resume_rereviews_same_round_without_raise')
        fixture.setUp()
        try:
            c = fixture.c
            c.args.rounds = 9
            c.card.update(builder_rounds=8,recovery_config={'rounds':9,'case_budget':50})
            fixture.ledger(38.94,terminal_stop='PauseRequested')
            fixture.receipt(n=7,limit=8)
            path = c.work/'attack-state.json'; receipt = json.loads(path.read_text())
            receipt['binding']['bench'] = 'previous-release'
            receipt['rereviews'] = 1
            path.write_text(json.dumps(receipt))
            report = c.work/'attacks/round-7.json'
            report.write_text('{"complete":false,"blocking":["review incomplete"]}')
            c.limits_raised = restart.raised_limits(self.card,50,9,explicit_rounds=True)
            calls = []
            def model(ctx,models,text,cwd,name):
                calls.append(name)
                context = json.JSONDecoder().raw_decode(text)[0]
                if name=='attacker-7':
                    self.assertEqual(calls,['attacker-7'])
                    self.assertEqual(json.loads(path.read_text())['rereviews'],2)
                    report.write_text('{"complete":true,"blocking":["fresh reviewed finding"]}')
                elif name=='builder-8':
                    self.assertEqual(context['precheck_problems'],['fresh reviewed finding'])
                    self.assertEqual(context['attack_report'],str(report))
                    (c.case/'repair.txt').write_text('synthetic writer fix')
                elif name=='attacker-8':
                    Path(context['report_path']).write_text('{"complete":true,"blocking":[]}')
                else:
                    self.fail('unexpected role or extra writer: '+name)
                return 0
            with patch.object(run,'opencode',model):
                run.write_and_attack(c,self.card)
            self.assertEqual(calls,['attacker-7','builder-8','attacker-8'])
            self.assertEqual(c.card['resume_rereview'],{'round':7,'reason':'interrupted_review','binding_changed':['bench']})
            self.assertEqual(c.card['stress_review'],{'status':'completed','round':8})
            self.assertEqual(c.limits_raised,{'rounds_raised':{'from':8,'to':9}})
            self.assertEqual(json.loads(path.read_text())['round_limit'],9)
        finally:
            fixture.doCleanups()


if __name__=='__main__': unittest.main()
