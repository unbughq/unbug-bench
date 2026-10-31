"""Ordinary retry replays on captured practice/5813be bytes.

Model answers, failures, archive bodies and time shifts are authored inputs.
The HTTP 200 body is captured; no model CLI, cloud case or live web request runs.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import test_stream_d_runtime as runtime_fixture
from router_test_support import synthetic_maximum
from freshness_test_transport import HTTP
import budget
import diagnosis
import freshness_retrieval as retrieval
import model_router
import model_runtime
import ordinary_retry
import ordinary_freshness
import run
import stress_progress
from registry import atomic_json
from run_validity import InvalidInfra


class RetryTests(unittest.TestCase):
    patch = runtime_fixture.RuntimeTests.patch

    def setUp(self):
        real_categories = run.stress_categories
        runtime_fixture.RuntimeTests.setUp(self)
        self.patch(run, 'stress_categories', real_categories)
        self.patch(model_router, 'route_maximum', lambda route: {**synthetic_maximum(route), 'max_usd': .1})
        self.c.stress_checkpoint = lambda: True
        self.calls = []

    def cli(self, emit):
        calls = self.calls
        def invoke(runtime, c, models, text, cwd, name, **kwargs):
            c.model_process_state['started'] = True
            calls.append((name, c.model_lease.route, text))
            emit(c, text, name)
            return 0
        self.patch(model_runtime.ModelRuntime, '_invoke', invoke)

    def answer_path(self, text):
        return Path(re.search(r'(/[^\s]+/answer-[0-9]+\.json)', text)[1])

    def idea(self, identity='one'):
        out = self.work / 'idea.json'
        return run.retained_answer(self.c, self.c.models['reviewers'][0], 'OUTPUT: ' + str(out),
            self.work, 'reviewer-idea-realism', out, {'statement': (self.case / 'statement.md').read_text(),
            'revision': identity}, 'idea', '{approve: boolean, reason: nonempty string}',
            lambda v: isinstance(v, dict) and type(v.get('approve')) is bool and bool(v.get('reason')))

    def test_transport_failures_do_not_consume_work_and_deadline_cancels(self):
        count = []
        def fetch():
            count.append(1)
            if len(count) < 5: raise InvalidInfra('authored outage')
            return HTTP['body']
        self.patch(ordinary_retry, 'backoff', lambda *a, **k: None)
        self.assertEqual(ordinary_retry.transport(self.c, {'url': 'saved-response'}, fetch), HTTP['body'])
        state = next((self.work / 'ordinary-retries').glob('*/state.json'))
        self.assertEqual(json.loads(state.read_text())['transport_failures'], 4)
        self.assertEqual(self.c.card['builder_rounds'], 0)
        self.c.role_cancel.set()
        with self.assertRaisesRegex(budget.BudgetError, 'cancelled'):
            ordinary_retry.transport(self.c, {}, fetch)
        self.c.role_cancel.clear()
        self.channel['batch_deadline'] = '2000-01-01T00:00:00Z'
        self.c.authenticated_job_config['job_money'] = copy.deepcopy(self.channel)
        self.c.batch_deadline = self.channel['batch_deadline']
        with self.assertRaisesRegex(budget.BudgetError, 'retired_batch_bound'):
            ordinary_retry.transport(self.c, {}, fetch)
        self.assertEqual(len(count), 5)

    def test_retained_schema_repair_replays_without_new_call(self):
        def emit(c, text, name):
            self.answer_path(text).write_text(json.dumps({'approve': True, **({'reason': 'retained rationale'} if len(self.calls) == 2 else {})}))
        self.cli(emit)
        self.assertTrue(self.idea()['approve'])
        self.assertEqual(len(self.calls), 2)
        self.assertIn('Retained answer:', self.calls[1][2])
        self.assertTrue(self.idea()['approve'])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.c.card['builder_rounds'], 0)

    def test_repair_cannot_invent_decision_then_equivalent_gets_full_request(self):
        def emit(c, text, name):
            self.answer_path(text).write_text(json.dumps({'approve': False} if len(self.calls) == 1 else
                {'approve': True, 'reason': 'authored full judgment'}))
        self.cli(emit)
        self.assertTrue(self.idea()['approve'])
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.calls[0][1], self.calls[1][1])
        self.assertNotEqual(self.calls[1][1], self.calls[2][1])
        self.assertTrue(self.calls[2][2].startswith('OUTPUT:'))
        self.assertTrue(self.idea()['approve']); self.assertEqual(len(self.calls), 3)

    def test_undecodable_and_wait_preserve_route_bound(self):
        def emit(c, text, name):
            if len(self.calls) == 1: self.answer_path(text).write_text('{undecodable')
            elif len(self.calls) == 2: raise runtime_fixture.Killed()
            else: self.answer_path(text).write_text('{"approve":true,"reason":"new judgment"}')
        self.cli(emit)
        with self.assertRaises(runtime_fixture.Killed): self.idea()
        self.assertTrue(self.idea()['approve'])
        self.assertEqual(self.calls[1][1], self.calls[2][1])
        self.assertNotEqual(self.calls[0][1], self.calls[1][1])
        self.assertTrue(all('Retained answer:' not in call[2] for call in self.calls))

    def test_single_route_missing_output_exhausts_without_futile_repair(self):
        self.c.models['reviewers'] = [self.c.models['builder']]
        self.c.card['roles']['reviewer']['model'] = self.c.models['builder'][0]
        self.cli(lambda *a: None)
        for _ in range(2):
            with self.assertRaisesRegex(budget.BudgetError, '^malformed_output_exhausted$'): self.idea()
        self.assertEqual(len(self.calls), 1)
        with self.assertRaisesRegex(budget.BudgetError, '^malformed_output_exhausted$'): self.idea('changed')
        self.assertEqual(len(self.calls), 2)

    def test_raw_archive_projection_ignores_wrappers_and_access_body_nonce(self):
        url = 'https://github.com/medusajs/medusa/issues/1'
        selected = 'https://web.archive.org/web/20261001000000/' + url
        requested, cycle = [], [0]
        def fetch(target, **kwargs):
            requested.append(target)
            if target == url: status, body = 403, ('nonce-' + str(cycle[0])).encode()
            elif target.startswith('https://archive.org/'):
                status, body = 200, json.dumps({'archived_snapshots': {'closest': {
                    'url': selected, 'available': True, 'status': '200'}}, 'volatile': cycle[0]}).encode()
            elif 'id_/' in target: status, body = 200, HTTP['body'].encode()
            else: status, body = 200, ('replay wrapper playback ' + str(cycle[0])).encode()
            return {'url': target, 'final_url': target, 'status': status}, body
        self.patch(retrieval, 'fetch', fetch)
        a = retrieval.retrieve([{'url': url}], self.work / 'http', access=True)
        cycle[0] = 2
        b = retrieval.retrieve([{'url': url}], self.work / 'http', access=True)
        self.assertNotEqual(retrieval.digest(a), retrieval.digest(b))
        self.assertEqual(retrieval.judgment_digest(a), retrieval.judgment_digest(b))
        self.assertTrue(any('20261001000000id_/' in target for target in requested))
        self.assertNotIn(selected, requested)
        self.assertEqual(len(list(self.work.glob('http-superseded-*'))), 1)
        retrieval.load(self.work / 'http', [{'url': url}])
        response = b[0]['responses'][-1]
        (self.work / 'http' / response['body']).write_text('changed')
        with self.assertRaises(InvalidInfra): retrieval.load(self.work / 'http', [{'url': url}])

    def searches(self, expired=False):
        at = datetime.now(timezone.utc) - timedelta(hours=25 if expired else 0)
        rows = [{'who': who, 'kind': kind, 'query': f'{who} {kind} query {i}',
                 'url': f'https://github.com/medusajs/medusa/issues/{i + 1}', 'at': at.isoformat(),
                 'hit': False, 'retrieved': True, 'note': 'authored no-hit observation',
                 'app_version': '2.19.0', 'version_scope': 'authored applicability'}
                for who,kind,count in [('builder','web',3),('builder','github',3),('attacker','web',2)]
                for i in range(count)]
        (self.case / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        return rows

    def test_expiry_refresh_repeats_without_defect_charge(self):
        self.searches(True)
        self.patch(retrieval, 'fetch', lambda url, **kw: ({'url':url,'final_url':url,'status':200},HTTP['body'].encode()))
        def emit(c, text, name):
            who = name.split('-')[0]
            rows = run.freshness_lines(c)
            for row in rows:
                if row['who'] == who: row['at'] = datetime.now(timezone.utc).isoformat()
            (self.case / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.cli(emit)
        self.assertTrue(run.g2(self.c)[0])
        self.searches(True)
        self.assertTrue(run.g2(self.c)[0])
        state = json.loads((self.work / 'freshness-repair.json').read_text())
        self.assertEqual(state['completed_defects'], 0)
        self.assertEqual(len(self.calls), 4)

    def test_ineffective_completed_refresh_spends_defects(self):
        self.searches(True)
        self.cli(lambda *a: None)
        with self.assertRaisesRegex(budget.BudgetError, 'freshness_evidence_unavailable'): run.g2(self.c)
        self.assertEqual(json.loads((self.work/'freshness-repair.json').read_text())['completed_defects'], 2)
        self.assertEqual(len(self.calls), 4)

    def stress_setup(self, emit):
        self.patch(run, 'g1', return_value=(True, {'problems': []}))
        self.patch(run, 'early_checks', return_value=None)
        self.patch(run, 'early_review', return_value=None)
        self.patch(run, 'loop_freshness', lambda c,r,p:(r,p))
        def output(c, text, name):
            if name.startswith('builder-'): (self.case/'draft.txt').write_text('authored writer completion'); return
            config = json.loads(text.split('CATEGORY MODE (overrides whole-review completion instructions):\n')[1].split('\n')[0])
            value = {'category':config['category'],'category_complete':True,
                'completed_subchecks':config['required_subchecks'], 'blocking':[], 'unfinished_validation':[],
                'freshness_review':[], 'cheats_tried':[], 'non_blocking':[]}
            emit(config, value)
            Path(config['category_output']).write_text(json.dumps(value))
        self.cli(output)

    def test_category_kill_resumes_only_unfinished_and_preserves_operation(self):
        killed = [False]
        def emit(config, value):
            if config['category'] == 'fairness' and not killed[0]:
                killed[0] = True
                Path(config['category_output']).write_text(json.dumps({**value, 'category_complete': False}))
                raise runtime_fixture.Killed()
        self.stress_setup(emit)
        with self.assertRaises(runtime_fixture.Killed): run.write_and_attack(self.c, {})
        old = run.jload(self.work/'attack-state.json')
        self.assertEqual(old['phase'], 'pending')
        self.assertEqual(self.c.card['builder_rounds'],1)
        before = {p: p.read_bytes() for p in self.work.glob('attacks/round-1-categories/*/*-0.json')}
        self.c.args.resume = self.c.case_id
        run.write_and_attack(self.c, copy.deepcopy(self.c.card))
        after = run.jload(self.work/'attack-state.json')
        self.assertEqual(old['operation_id'], after['operation_id'])
        self.assertEqual(after['phase'], 'validated')
        self.assertEqual([call[0] for call in self.calls].count('builder-1'),1)
        self.assertEqual(len(self.calls),6) # writer, two complete categories, kill, two remaining
        for p,data in before.items(): self.assertEqual(p.read_bytes(),data)
        self.assertTrue(run.jload(self.work/'attacks/round-1.json')['complete'])

    def test_no_progress_is_operational_exhaustion_and_blocker_wins(self):
        def emit(config, value):
            value.update(category_complete=False, completed_subchecks=[], unfinished_validation=['authored diagnostic needed'])
        self.stress_setup(emit)
        with self.assertRaisesRegex(budget.BudgetError,'stress_validation_exhausted'): run.write_and_attack(self.c,{})
        self.assertEqual(len(self.calls),2)
        self.c.card.update(terminal_stop='stress_validation_exhausted',status='stopped',gates={})
        self.assertTrue(diagnosis.exhaustion(self.c.card))

    def test_publication_retries_before_next_dispatch(self):
        uploaded, failures = [], [0]
        def checkpoint():
            uploaded.append(len(self.calls)); failures[0] += 1
            return failures[0] > 3
        self.c.stress_checkpoint = checkpoint
        self.patch(ordinary_retry, 'backoff', lambda *a,**k:None)
        self.stress_setup(lambda *a: None)
        run.write_and_attack(self.c,{})
        self.assertEqual(uploaded[:4],[2,2,2,2])
        self.assertEqual(len(self.calls),5)
        self.assertFalse(run.jload(self.work/'stress-publication.json')['pending'])

    def test_identical_access_failed_snapshot_reuses_unresolved_judgment(self):
        rows = self.searches()
        flagged = [{**rows[0], 'hit': True}]
        url = flagged[0]['url']
        selected = 'https://web.archive.org/web/20261001000000/' + url
        def fetch(target, **kwargs):
            if target == url: status, body = 403, b'authored bot wall'
            elif target.startswith('https://archive.org/'):
                status, body = 200, json.dumps({'archived_snapshots': {'closest': {
                    'url': selected, 'available': True, 'status': '200'}}}).encode()
            else:
                self.assertIn('id_/', target)
                status, body = 200, HTTP['body'].encode()
            return {'url':target,'final_url':target,'status':status},body
        self.patch(retrieval, 'fetch', fetch)
        self.patch(ordinary_freshness, 'obtain', lambda c,rows,directory,**kw:
            retrieval.retrieve(rows,directory,access=True))
        def emit(c,text,name):
            self.answer_path(text).write_text(json.dumps({'hits':[{
                'url':url,'resolved':True,'same_bug':False,'retrieved':True,
                'app_version':'2.19.0','version_scope':'authored snapshot does not match',
                'retrieved_from':'archive','archive_checked':True,'archive_available':True,
                'archive_snapshot_url':selected,'live_failure':'http_403','why':'authored comparison'}]}))
        self.cli(emit)
        for _ in range(2):
            self.assertEqual(run.confirm_hits(self.c,flagged),flagged)
            self.assertTrue(self.c.freshness_transport_pending)
            self.assertEqual(self.c.freshness_confirmed_hits,0)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.c.card['builder_rounds'],0)

    def test_dedup_and_panel_callers_use_retained_schema_repair(self):
        self.c.models['easy_calibrator'] = self.c.models['reviewers'][0]
        self.c.card['roles']['easy_calibrator'] = {'model':self.c.models['easy_calibrator'][0]}
        prior = self.work/'earlier.md'; prior.write_bytes((self.case/'statement.md').read_bytes())
        self.patch(run,'prior_statements',return_value={'case-earlier':str(prior)})
        self.patch(run,'ensure_freshness',return_value=(True,{}))
        self.patch(run,'idea_realism',return_value=True)
        def emit(c,text,name):
            if 'dedup' in name:
                value = {'duplicate_of':None}
                if 'Retained answer:' in text: value['reason']='authored different case'
            else:
                value = {'fairness':{'approve':True},'realism':{'approve':True}}
            self.answer_path(text).write_text(json.dumps(value))
        self.cli(emit)
        self.assertTrue(run.statement_precheck(self.c))
        self.assertEqual(len(self.calls),2)
        self.assertTrue(run.g8(self.c)[0]); self.assertTrue(run.g9(self.c)[0])
        self.assertEqual(len(self.calls),3)
        # Semantic prior content, rather than the same path, invalidates dedup reuse.
        prior.write_text(prior.read_text()+' changed prior statement')
        self.assertTrue(run.statement_precheck(self.c))
        self.assertEqual(len(self.calls),5)

    def test_freshness_wait_does_not_repeat_completed_role(self):
        self.searches(True)
        self.patch(retrieval,'fetch',lambda url,**kw:({'url':url,'final_url':url,'status':200},HTTP['body'].encode()))
        killed = [False]
        def emit(c,text,name):
            who = name.split('-')[0]
            if who == 'attacker' and not killed[0]: killed[0]=True; raise runtime_fixture.Killed()
            rows = run.freshness_lines(c)
            for row in rows:
                if row['who']==who: row['at']=datetime.now(timezone.utc).isoformat()
            (self.case/'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.cli(emit)
        with self.assertRaises(runtime_fixture.Killed): run.g2(self.c)
        self.assertEqual(run.jload(self.work/'freshness-repair.json')['completed_defects'],0)
        self.assertTrue(run.g2(self.c)[0])
        self.assertEqual([name for name,_,_ in self.calls],['builder-freshness','attacker-freshness','attacker-freshness'])

    def test_progress_bound_exhausts_at_last_subcheck(self):
        count = [0]
        def emit(config,value):
            count[0]+=1
            value.update(category_complete=False, completed_subchecks=config['required_subchecks'][:count[0]],
                         unfinished_validation=['authored unexecuted check'])
        self.stress_setup(emit)
        with self.assertRaisesRegex(budget.BudgetError,'stress_validation_exhausted'): run.write_and_attack(self.c,{})
        self.assertEqual(count[0],len(stress_progress.CATEGORIES['wrong_fixes']))
        self.assertEqual(self.c.card['builder_rounds'],1)

    def test_interrupted_diagnostic_exhausts_before_more_category_work(self):
        self.stress_setup(lambda *a:None)
        claimed = self.work/'diagnostic-budgets/attacker-1/claimed'
        claimed.mkdir(parents=True)
        atomic_json(claimed.parent/'status.json',{'status':'timeout'})
        with self.assertRaisesRegex(budget.BudgetError,'stress_validation_exhausted'): run.write_and_attack(self.c,{})
        self.assertEqual(len(self.calls),1) # writer only; no impossible stress retry

    def test_broad_outage_retries_without_buying_topup(self):
        self.searches()
        attempts = []
        real = run._g2
        def gate(c):
            attempts.append(1)
            if len(attempts)<5:
                return False, {'outcome':'evidence_incomplete','all_transport_failed':True}
            return real(c)
        self.patch(run,'_g2',gate)
        self.patch(ordinary_freshness,'backoff',lambda *a,**kw:None)
        self.patch(retrieval,'fetch',lambda url,**kw:({'url':url,'final_url':url,'status':200},HTTP['body'].encode()))
        self.cli(lambda *a:self.fail('outage must not buy freshness work'))
        self.assertTrue(run.g2(self.c)[0])
        self.assertEqual(len(attempts),5)
        self.assertEqual(run.jload(self.work/'freshness-repair.json')['completed_defects'],0)

    def test_completed_blocker_wins_over_unfinished_no_progress(self):
        self.c.args.rounds=1
        def emit(config,value):
            value.update(category_complete=False, completed_subchecks=[],
                         blocking=['authored definite defect'], unfinished_validation=['authored diagnostic needed'])
        self.stress_setup(emit)
        with self.assertRaisesRegex(budget.BudgetError,'stress_review_unresolved:rounds_exhausted'):
            run.write_and_attack(self.c,{})
        self.assertEqual(len(self.calls),2)
        self.assertEqual(run.jload(self.work/'attacks/round-1.json')['blocking'],['authored definite defect'])

    def test_publication_kill_keeps_completed_category_on_resume(self):
        killed=[False]
        def checkpoint():
            if not killed[0]: killed[0]=True; raise runtime_fixture.Killed()
            return True
        self.c.stress_checkpoint=checkpoint
        self.stress_setup(lambda *a:None)
        with self.assertRaises(runtime_fixture.Killed): run.write_and_attack(self.c,{})
        self.assertTrue(run.jload(self.work/'stress-publication.json')['pending'])
        self.assertEqual(len(self.calls),2)
        self.c.args.resume=self.c.case_id
        run.write_and_attack(self.c,copy.deepcopy(self.c.card))
        self.assertEqual(len(self.calls),5)
        self.assertFalse(run.jload(self.work/'stress-publication.json')['pending'])

    def test_access_failure_archive_absence_cannot_clear_flagged_page(self):
        row=self.searches()[0]
        receipt={'url':row['url'],'retrieved_from':'none','live_failure':'http_403',
                 'archive_available':False,'archive_snapshot_url':None}
        self.c.freshness_retrieval=[receipt]
        self.c.freshness_confirmed_hits=0
        self.c.freshness_transport_pending=False
        verdict={**receipt,'resolved':True,'retrieved':False,'same_bug':None,
                 'archive_checked':True,'app_version':'2.19.0','version_scope':'authored scope','why':'authored no snapshot'}
        self.assertEqual(run.checked_freshness_verdict(self.c,[row],[verdict]),[row])
        self.assertTrue(self.c.freshness_transport_pending)
        self.assertEqual(self.c.freshness_confirmed_hits,0)
        self.assertEqual(self.c.freshness_review_summary['unreachable_hits'],0)


if __name__ == '__main__': unittest.main()
