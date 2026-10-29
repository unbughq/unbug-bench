"""Late stops and ordinary successors; synthetic private state, no model/cloud calls."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/bench'), str(ROOT / 'tests/factory')]
import fairness
import founder_decisions
import founder_ruling
import gate_state
import late_recovery
import late_rehearsal
import recovery
import restore_ledger
import run
import test_case_budget as fixtures


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class LateGateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CaseBudgetTests('test_transient_review_resume_rereviews_same_round_without_raise')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.c = c = self.fixture.c
        c.card.update(builder_rounds=3, recovery_config={'rounds':3, 'case_budget':50}, case=c.case_id)
        c.case.joinpath('statement.md').write_text('synthetic statement')
        self.fixture.receipt(n=3, limit=3)
        path = c.work / 'attack-state.json'
        receipt = json.loads(path.read_text())
        report = c.work / 'attacks/round-3.json'
        save(report, {'complete':True, 'blocking':[]})
        receipt.update(review_attempt='a'*32, review_pending=False, review_completed={
            'attempt':'a'*32, 'binding':hashlib.sha256(json.dumps(receipt['binding'],sort_keys=True).encode()).hexdigest(),
            'report_sha256':late_recovery.sha(report)})
        save(path, receipt)

    def test_pause_inside_final_gates_needs_no_writer_round_but_authenticates_stress(self):
        c = self.c
        late_recovery.mark_gates(c)
        card = {**c.card, 'status':'stopped', 'terminal_stop':'paused', 'gates':{'G4':'pass'},
                'continuation_budget':self.fixture.ledger(12, terminal_stop='PauseRequested')}
        self.assertFalse(recovery.paused_rounds_exhausted(card))
        self.assertEqual(recovery.raised_limits(card,50,3), {})
        self.assertFalse(recovery.require_holder_stop(card,['--rounds','3'], 'case'))
        recovery.require_restart_stop(card,['--rounds','3'])
        self.assertTrue(recovery.ledger_agrees(card,route='restart'))
        late_recovery.authenticate_gates(c,card)
        save(c.work / 'attacks/round-3.json', {'complete':False,'blocking':['review incomplete']})
        with self.assertRaises(restore_ledger.Refused): late_recovery.authenticate_gates(c,card)

    def test_mixed_report_cannot_authorize_gate_continuation(self):
        report = self.c.work / 'attacks/round-3.json'
        save(report, {'complete': False, 'blocking': ['Broken judge.'],
                      'unfinished_validation': ['No valid diagnostics.']})
        with self.assertRaises(restore_ledger.Refused): late_recovery.mark_gates(self.c)

    def test_late_defect_stops_without_writer_then_new_pinned_ruling_writes_stresses_and_gates(self):
        c = self.c
        prior = {'authorization':{'sha256':'b'*64, 'record':{'sequence':2}}}
        c.card['founder_ruling'] = prior
        save(c.work/'founder-ruling-applied.json',prior)
        def fail(ctx):
            ctx.card.update(failed_gate='G16',failed_detail={'private':'synthetic judge defect'})
            ctx.card['gates']['G16']='fail'
        with patch.object(run,'run_gates',side_effect=fail), patch.object(run,'opencode') as model:
            with self.assertRaisesRegex(run.BudgetError,'late_defect_needs_ruling:G16'):
                run.validate_and_repair(c)
        model.assert_not_called()
        self.assertNotIn('failed_detail',c.card)
        self.assertNotIn('G16',c.card['gates'])
        card={**copy.deepcopy(c.card),'status':'stopped','terminal_stop':'late_defect_needs_ruling:G16',
              'sha256':'d'*64,'continuation_budget':self.fixture.ledger(12)}
        with self.assertRaisesRegex(ValueError,'pinned'):
            recovery.require_holder_stop(card,['--rounds','4','--case-budget','50'],'case')
        recovery.require_holder_stop(card,['--rounds','4','--case-budget','50','--founder-ruling-sha256','f'*64],'case')
        record=dict(version=3,authority='founder-2026-10-26',case=c.case_id,generation=card['sha256'],
            sequence=3,public_card_sha256=restore_ledger.digest(card),ledger_sha256=restore_ledger.digest(card['continuation_budget']),
            prior_receipt_sha256=restore_ledger.digest(prior),prior_ruling_sha256='b'*64,
            allowances=dict(case_budget_usd=50,round_limit=4),late_defect=card['late_defect'],reason='One repair and stress round')
        ruling=c.work/'ruling.json'; save(ruling,record)
        accepted=founder_ruling.authenticate(ruling,late_recovery.sha(ruling),c.case_id,card['sha256'],card)
        applied=founder_ruling.apply(c.work,accepted)
        save(c.work/'scorecard.json',card)
        save(c.ledger.parent/(c.case_id+'.restore-accounting.json'), {'attempt_allowances_authenticated':True,'founder_ruling':applied})
        c.args.rounds=4; c.args.resume=c.case_id; c.stopped=False
        c.card={'gates':{}}
        founder_ruling.context(c)
        run.inherit_recovery_history(c,card)
        self.assertEqual(c.card['founder_ruling'],applied)  # startup cannot restore the predecessor
        c.limits_raised=recovery.raised_limits(card,50,4,explicit_rounds=True)
        calls=[]
        def model(ctx,models,text,cwd,name):
            calls.append(name)
            if name=='builder-4':
                self.assertIn('synthetic judge defect',text)
                (c.case/'fixed.txt').write_text('repaired')
            elif name=='attacker-4': save(c.work/'attacks/round-4.json',{'complete':True,'blocking':[]})
            else: self.fail(name)
            return 0
        # Real recovery dispatch and writer/stress loop; only model/checker execution stubbed.
        with patch.object(run,'opencode',side_effect=model), patch.object(run,'ensure_freshness',return_value=(True,{})):
            run.build(c)
        self.assertEqual(calls,['builder-4','attacker-4'])
        c.card.pop('failed_gate',None); c.card['gates']={}
        with patch.object(run,'run_gates') as gates:
            run.validate_and_repair(c)
        gates.assert_called_once()
        self.assertEqual(c.card['stress_review'],{'status':'completed','round':4})

    def test_independently_cleared_freshness_report_authorizes_gate_phase(self):
        c=self.c; c.models['reviewers']=[['reviewer']]; c.args.agent_timeout=14400
        save(c.case/'case.json',{'app':{'version':'2.19.0'}})
        report=c.work/'attacks/round-3.json'
        save(report,{'complete':True,'blocking':['[freshness-review] independent verdict required'],
                     'freshness_review':['https://example.com/independent-public-pattern']})
        path=c.work/'attack-state.json'; attack=json.loads(path.read_text())
        attack['binding']=run.attack_binding(c)
        attack['review_completed'].update(report_sha256=late_recovery.sha(report),
            binding=hashlib.sha256(json.dumps(attack['binding'],sort_keys=True).encode()).hexdigest())
        save(path,attack)
        def reviewer(ctx,models,text,cwd,name,**kwargs):
            save(cwd/'verdict.json',{'hits':[dict(url='https://example.com/independent-public-pattern',
                resolved=True,same_bug=False,retrieved=True,app_version='2.19.0',
                version_scope='different public pattern',why='independent synthetic exclusion')]})
            return 0
        with patch.object(run,'opencode',side_effect=reviewer):
            resolved,_=run.loop_freshness(c,run.attack_report(report),report)
        self.assertEqual(resolved['blocking'],[])
        late_recovery.mark_gates(c)
        self.assertIn('clearance_sha256',c.card['gate_continuation'])
        proof=report.with_suffix('.clearance.json'); immutable=proof.read_bytes()
        phase=copy.deepcopy(c.card['gate_continuation'])
        (c.work/'freshness-verdict.json').unlink()  # force a real second independent confirmation
        with patch.object(run,'opencode',side_effect=reviewer) as renewed:
            run.loop_freshness(c,run.attack_report(report),report)
        renewed.assert_called_once()
        self.assertEqual(proof.read_bytes(),immutable)
        self.assertEqual(c.card['gate_continuation'],phase)
        card=copy.deepcopy(c.card)
        late_recovery.authenticate_gates(c,card)
        verdict=c.work/json.loads(proof.read_text())['verdict_path']
        save(verdict,{'hits':[]})
        with self.assertRaises(restore_ledger.Refused):late_recovery.authenticate_gates(c,card)

    def test_restored_early_panel_rejection_at_cap_stops_without_precheck_writer(self):
        c=self.c
        late_recovery.mark_gates(c)
        def panel(ctx):
            ctx.card.setdefault('early_gates',{})['G8']={'ok':False}
            return ['synthetic fairness defect']
        with patch.object(run,'early_review',side_effect=panel),patch.object(run,'opencode') as writer:
            with self.assertRaisesRegex(run.BudgetError,'late_defect_needs_ruling:G8'):
                run.write_and_attack(c,{})
        writer.assert_not_called()
        self.assertNotIn('gate_continuation',c.card)
        self.assertFalse((c.work/'gate-continuation.json').exists())
        self.assertEqual(json.loads((c.work/'late-defect.json').read_text())['detail'],
                         {'problems':['synthetic fairness defect']})

    def test_interrupted_late_writer_invalidates_gate_phase_before_mutation(self):
        c=self.c; c.args.rounds=4
        def fail(ctx):ctx.card.update(failed_gate='G16',failed_detail={'defect':'synthetic'})
        def interrupted(ctx,previous):
            self.assertNotIn('gate_continuation',ctx.card)
            self.assertFalse((ctx.work/'gate-continuation.json').exists())
            (ctx.case/'partial.txt').write_text('partial writer work')
            raise run.BudgetError('provider_limit:writer')
        with patch.object(run,'run_gates',side_effect=fail),patch.object(run,'write_and_attack',side_effect=interrupted):
            with self.assertRaisesRegex(run.BudgetError,'provider_limit'):
                run.validate_and_repair(c)
        late_recovery.authenticate_gates(c,c.card)  # no stale public marker rejects extraction
        self.assertNotIn('gate_continuation',c.card)

    def test_startup_failure_checkpoint_carries_new_applied_ruling_on_ordinary_restore(self):
        home=self.c.work/'startup'; work=home/'case-startup'; work.mkdir(parents=True)
        (work/'case').mkdir()
        record={'version':3,'case':'case-startup','allowances':{'case_budget_usd':50,'round_limit':4}}
        applied={'authorization':{'record':record,'record_sha256':restore_ledger.digest(record)}}
        save(work/'founder-ruling-applied.json',applied)
        ledger=home/'sealed/case-startup.continuation-budget.json'
        save(ledger.parent/'case-startup.restore-accounting.json',
             {'attempt_allowances_authenticated':True,'founder_ruling':applied})
        c=SimpleNamespace(work=work,case_id='case-startup',card={'gates':{}},ledger=ledger,
                          args=SimpleNamespace(case_budget=50,rounds=4))
        founder_ruling.context(c)
        run.inherit_recovery_history(c,{'founder_ruling':{'predecessor':True},'builder_rounds':3})
        self.assertEqual(c.card['founder_ruling'],applied)
        # Runtime preparation failed before build() had a chance to re-read context.
        card={**c.card,'case':c.case_id,'sha256':'e'*64,'status':'stopped','terminal_stop':'runner_error:OSError',
              'continuation_budget':{'calls':12,'cost':0.2,'list_cost_usd':12,'events':[]}}
        save(work/'scorecard.json',card);save(work/'continuation-budget.json',card['continuation_budget'])
        imported=restore_ledger.install(work,home/'next-sealed',c.case_id,card['sha256'],card)
        self.assertTrue(imported['ruling_carried_forward'])
        self.assertEqual(imported['founder_ruling'],applied)

    def test_rehearsal_recipient_requires_valid_explicit_age_checksum(self):
        self.assertEqual(late_rehearsal.recipient(run.FOUNDER_RECIPIENT),run.FOUNDER_RECIPIENT)
        for bad in (None,'',run.FOUNDER_RECIPIENT[:-1]+'q','AGE1'+run.FOUNDER_RECIPIENT[4:]):
            with self.assertRaises(ValueError):late_rehearsal.recipient(bad)

    def test_failed_last_late_repair_never_spends_builder_precheck(self):
        c=self.c; c.args.rounds=4; c.limits_raised={'rounds_raised':{'from':3,'to':4}}
        c.card.update(failed_gate='G16',failed_detail={'defect':'synthetic'})
        c.card['gates']['G16']='fail'
        calls=[]
        def model(ctx,models,text,cwd,name):
            calls.append(name)
            if name=='builder-4': (c.case/'repair.txt').write_text('still defective')
            elif name=='attacker-4': save(c.work/'attacks/round-4.json',{'complete':False,'blocking':['remaining defect'], 'unfinished_validation':['Broken judge blocked diagnostics.']})
            else: self.fail('unverifiable spend: '+name)
            return 0
        with patch.object(run,'opencode',side_effect=model):
            with self.assertRaisesRegex(run.BudgetError,'late_defect_needs_ruling:G16'):
                run.write_and_attack(c,copy.deepcopy(c.card))
        self.assertEqual(calls,['builder-4','attacker-4'])

    def test_early_panel_uses_authenticated_durable_checks_on_each_restore(self):
        c=self.c
        pipeline=run._gate_pipeline()
        pipeline.evaluate=Mock(side_effect=AssertionError('reviewer was repeated'))
        cached={'approve':'1/1'}
        def load(ctx,gate,bench):
            ctx.gate_fingerprint_versions={gate:gate_state.VERSION}
            return cached
        with patch.object(gate_state,'load',side_effect=load), patch.object(run,'public_progress'), patch.object(run,'log'):
            for _ in range(2):
                c.__dict__.pop('votes',None); c.__dict__.pop('early',None)
                self.assertIsNone(pipeline.early_review(c))
        pipeline.evaluate.assert_not_called()

    def test_d1_caps_every_case_and_preserves_smaller_allowances(self):
        c=self.c; c.case_id='case-any-new-case'; c.args.max_total_calls=5001
        with self.assertRaisesRegex(ValueError,'D1'): founder_decisions.record(c)
        c.args.max_total_calls=5000; founder_decisions.record(c)
        self.assertEqual(c.card['call_cap_ruling']['authority'],'founder-2026-10-26')
        c.args.max_total_calls=2000; founder_decisions.record(c)
        self.assertEqual(c.card['call_cap_ruling']['max_total_calls'],2000)

    def test_rehearsal_interruption_preserves_atomic_completed_attempt_once(self):
        from calibration import AttemptSeries
        c=self.c; c.args.rehearsal_interrupt_g10=True
        folder=c.work/'strong_calibrator'; folder.mkdir()
        workspace=folder/'try-1'; workspace.mkdir(); (workspace/'answer').write_text('synthetic')
        series=AttemptSeries(folder/'results.json',{},c.work,1,'synthetic')
        series.commit({'try':1,'solved':False,'guard_submitted':False,'stop_reason':'completed'},workspace)
        before=(folder/'results.json').read_bytes()
        with self.assertRaises(run.PauseRequested):late_rehearsal.after_attempt(c,'strong_calibrator')
        self.assertEqual((folder/'results.json').read_bytes(),before)
        late_rehearsal.after_attempt(c,'strong_calibrator')
        self.assertEqual(json.loads((folder/'results.json').read_text())[0]['try'],1)


class FairnessOperationalTests(unittest.TestCase):
    def test_nonzero_invalid_and_explicit_inconclusive_stop_then_bounded_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); case=root/'case'; case.mkdir(); (case/'promise.md').write_text('synthetic')
            work=root/'work'; attempt=work/'strong_calibrator/try-1'; attempt.mkdir(parents=True)
            save(work/'strong_calibrator/results.json',[{'try':1,'workspace':str(attempt)}])
            c=SimpleNamespace(work=work,case=case,models={'builder':['writer'],'strong_calibrator':['solver'],'reviewers':[['reviewer']]})
            for code,payload in ((1,{}),(0,{}),(0,{'inconclusive':True,'reason':'no fix'})):
                def call(ctx,models,text,cwd,name):
                    self.assertIn('"inconclusive":true',text)
                    save(cwd/'verdict.json',payload); return code
                r=SimpleNamespace(family=lambda x:x,jload=run.jload,time=run.time,model_call=call)
                with self.assertRaises(ValueError): fairness.review_attempts(c,r,'G17','strong_calibrator')
            c.card={'gates':{}}; c.args=SimpleNamespace(dry_run=False); c.audit_gates=['G17']
            pipeline=run._gate_pipeline(); pipeline.evaluate=Mock(side_effect=ValueError('inconclusive'))
            pipeline.publish=Mock(); pipeline.log=Mock(); pipeline.budget_boundary=Mock(); pipeline.after_gate=Mock()
            pipeline.run(c)
            self.assertEqual(pipeline.evaluate.call_count,2)
            self.assertTrue(c.stopped)
            self.assertEqual(c.card['terminal_stop'],'runner_error:ValueError')
            self.assertEqual(recovery.recoverable_crash(c.card),{'gate':'G17','error_type':'ValueError'})


if __name__=='__main__': unittest.main()
