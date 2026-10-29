"""Canary pending-writer authority and private real-artifact decision replay."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from test_founder_round10 import read, save, sha, replay, ROOT
import founder_ruling
import restore_ledger
import run

PRIVATE = Path('/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/00d02e9b-ca70-4919-b958-898ec30f1b3a/scratchpad/873d7f-open/checkpoint/case-20261024T085209Z-873d7f')
FIXTURE = Path(__file__).parent / 'fixtures/canary6-round8-collected-card.json'


def make_record(card, work):
    state = read(work / 'attack-state.json')
    prior = card['founder_ruling']
    return dict(version=2, authority='founder-2026-10-26', sequence=2, case=card['case'],
        generation=card['sha256'], public_card_sha256=restore_ledger.digest(card),
        ledger_sha256=restore_ledger.digest(card['continuation_budget']),
        prior_ruling_sha256=prior['authorization']['sha256'], prior_receipt_sha256=restore_ledger.digest(prior),
        allowances=dict(case_budget_usd=70, round_limit=state['round'] + 1),
        case_spent_usd=35.168597415, infrastructure_waste_usd=16.0,
        resume=dict(round=state['round'], pending_writer=True, attack_state_sha256=sha(work/'attack-state.json'),
            attack_state_record_sha256=restore_ledger.digest(state),
            case_sha256=run.case_hash(SimpleNamespace(case=work/'case'))),
        feedback=dict(round=state['round'], findings=2, reask_unresolved_freshness=True),
        feedback_report_sha256=sha(work/'attacks'/state['report']),
        diagnosis=dict(path=str(work/'attack-state.json'), sha256=sha(work/'attack-state.json')),
        reason='Founder authorizes $70 and one more stress round (9), derived from real completed stress round 8. '
            'The budget stop preceded the final writer repair; repair the retained blockers before stress. '
            'Writer reserve max(8, costliest round) is unchanged. Other allowances and histories are preserved. '
            'Builder-8 $0.744762 remains case spend: an unreclassifiable infra-caused cost; '
            'the completed invocation cannot be subtracted by the shipped accounting model. '
            'Infrastructure waste remains $16.0. Legacy unfinished-validation wording remains blocking/fail-closed.')


class CanaryFounderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name); self.card = read(FIXTURE)
        self.work = self.home / self.card['case']; self.work.mkdir()
        (self.work/'case').mkdir(); (self.work/'case/input').write_text('synthetic')
        (self.work/'attacks').mkdir()
        save(self.work/'attacks/round-8.json', dict(complete=False, blocking=[
            'Synthetic defect', 'Unfinished required validation (review incomplete): synthetic']))
        save(self.work/'founder-ruling-applied.json', self.card['founder_ruling'])
        save(self.work/'attack-state.json', dict(round=8, round_limit=8, final_repair=True,
            stop_reason='budget_exhausted', report='round-8.json', findings_report='round-8.json',
            binding=dict(case_id=self.card['case']), rereviews=2, release_rereviews=['a'*64]))
        self.record = make_record(self.card, self.work)
        self.record['diagnosis']['path'] = '/private/tmp/synthetic-canary-state.json'

    def accepted(self, record=None):
        p = self.home/'ruling.json'; save(p, record or self.record)
        return founder_ruling.authenticate(p, sha(p), self.card['case'], self.card['sha256'], self.card)

    def test_pending_writer_preserves_other_allowances_and_retry_does_not_reset(self):
        before = read(self.work/'attack-state.json'); accepted = self.accepted()
        receipt = founder_ruling.apply(self.work, accepted)
        after = {**before, 'round_limit': 9}
        self.assertEqual(read(self.work/'attack-state.json'), after)
        self.assertEqual(receipt['feedback_report_sha256'], self.record['feedback_report_sha256'])
        save(self.work/'attack-state.json', {**after, 'round': 9})
        self.assertEqual(founder_ruling.apply(self.work, accepted), receipt)
        self.assertEqual(read(self.work/'attack-state.json')['round'], 9)

    def test_pending_writer_accepts_defects_that_prevented_validation(self):
        save(self.work/'attacks/round-8.json', dict(complete=False,
            blocking=['Synthetic broken judge.', 'Synthetic reset collision.'],
            unfinished_validation=['No diagnostic produced a valid verdict.']))
        self.record = make_record(self.card, self.work)
        self.record['diagnosis']['path'] = '/private/tmp/synthetic-canary-state.json'
        accepted = self.accepted()
        receipt = founder_ruling.apply(self.work, accepted)
        self.assertFalse(receipt['stress_verdict_granted'])
        self.assertEqual(read(self.work/'attack-state.json')['round_limit'], 9)

    def test_wrong_round_money_feedback_or_added_allowance_refused(self):
        for change in (dict(allowances=dict(case_budget_usd=70, round_limit=10)),
                dict(case_spent_usd=34.423835415), dict(infrastructure_waste_usd=16.744762),
                dict(feedback=dict(round=8, findings=1, reask_unresolved_freshness=True)),
                dict(resume={**self.record['resume'], 'pending_writer': False})):
            with self.subTest(fields=list(change)), self.assertRaises(restore_ledger.Refused):
                self.accepted({**self.record, **change})

    def test_report_and_pending_state_are_bound_before_application(self):
        accepted = self.accepted()
        (self.work/'attacks/round-8.json').write_text('{}')
        with self.assertRaises(restore_ledger.Refused): founder_ruling.apply(self.work, accepted)

    def test_ordinary_successor_preserves_pending_writer_authority_without_reapplying(self):
        applied = founder_ruling.apply(self.work, self.accepted())
        before = read(self.work / 'attack-state.json')
        successor = copy.deepcopy(self.card)
        successor.update(sha256='e'*64, founder_ruling=applied, terminal_stop='provider_limit:openrouter/deepseek/deepseek-v4.1-flash')
        successor['recovery_config'].update(case_budget=70, rounds=9)
        successor['case_budget']['limit_usd'] = 70
        save(self.work/'scorecard.json', successor)
        save(self.work/'continuation-budget.json', successor['continuation_budget'])
        fresh = self.work/'freshness-repair.json'; save(fresh, {'attempts':2})
        sealed = self.home/'successor-sealed'
        with patch.object(founder_ruling, 'apply', side_effect=AssertionError('ruling reapplied')):
            imported = restore_ledger.install(self.work, sealed, successor['case'], successor['sha256'], successor)
        self.assertTrue(imported['ruling_carried_forward'])
        self.assertEqual(read(self.work/'attack-state.json'),before)
        self.assertEqual(read(fresh),{'attempts':2})
        args=SimpleNamespace(**{**successor['recovery_config'],'resume':successor['case'],
            'dry_run':False,'source':'hunt','rounds':9,'case_budget':70,'skip_build':False})
        c=SimpleNamespace(work=self.work,case=self.work/'case',case_id=successor['case'],
            card=copy.deepcopy(successor),args=args,models=successor['models'],
            ledger=sealed/(successor['case']+'.continuation-budget.json'))
        calls=[]
        def model(ctx,models,text,cwd,name):
            calls.append(name)
            if name=='builder-9':
                self.assertIn('Synthetic defect',text)
                (c.case/'fixed.txt').write_text('synthetic repair')
            elif name=='attacker-9': save(c.work/'attacks/round-9.json',{'complete':True,'blocking':[]})
            else: self.fail(name)
            return 0
        with patch.object(run,'g1',return_value=(True,{'problems':[]})), \
             patch.object(run,'attack_binding',return_value=before['binding']), \
             patch.object(run,'early_checks',return_value=None), patch.object(run,'early_review',return_value=None), \
             patch.object(run,'opencode',side_effect=model), \
             patch.object(run,'loop_freshness',side_effect=lambda c,r,p:(r,p)):
            run.write_and_attack(c,successor)
        self.assertEqual(calls,['builder-9','attacker-9'])
        self.assertEqual(c.card['founder_ruling'],applied)
        tampered=copy.deepcopy(successor); tampered['founder_ruling']['reset_once']=False
        with self.assertRaises(restore_ledger.Refused):
            restore_ledger.install(self.work,self.home/'refused',successor['case'],successor['sha256'],tampered)

    @unittest.skipUnless(os.environ.get('UNBUG_PRIVATE_REPLAY') == '1' and PRIVATE.is_dir(), 'already-open checkpoint absent; never decrypt')
    def test_real_clean_blocking_and_budget_branches(self):
        card = read(FIXTURE); record = make_record(card, PRIVATE)
        for blocking, cost in ((False, 0), (True, 0), (True, 20)):
            with self.subTest(blocking=blocking, cost=cost):
                result = replay(card, record, blocking=blocking, stress_cost=cost, private=PRIVATE)
                self.assertEqual(result['writer_estimate_usd'], 15.05)
                self.assertEqual(result['actions'][0], 'builder-9')


if __name__ == '__main__': unittest.main()
