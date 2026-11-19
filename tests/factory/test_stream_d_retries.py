"""Ordinary retry replays on captured practice/5813be bytes.

Model answers, failures, archive bodies and time shifts are authored inputs.
The HTTP 200 body is captured; no model CLI, cloud case or live web request runs.
"""
import inspect
import copy
import fnmatch
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess
import os
import threading
import shutil
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import test_stream_d_runtime as runtime_fixture
from router_test_support import synthetic_maximum
from freshness_test_transport import HTTP
import admission
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
        # Each authored interruption retains its synthetic $0.10 uncertainty.
        # Keep this control-flow fixture's quote bounded; real funded windows
        # and unknown-usage holds are exercised in test_durable_call_budget.
        quote = model_router.funded_maximum
        self.patch(model_router, 'funded_maximum', lambda route, funding:
                   quote(route, min(Decimal(str(funding)), Decimal('.1'))))
        self.c.args.freshness_fanout = False   # these tests drive the agentic top-up's call sequence
        self.c.stress_checkpoint = lambda: True
        self.calls = []
        self.context_inputs = {key: copy.deepcopy(value) for key, value in vars(self.c).items()
                               if key not in ('role_cancel', 'card', 'stress_checkpoint', 'model_publication_barrier')}

    def fresh_context(self):
        # Reconstruct only launch inputs and saved card; no runtime attributes,
        # locks, callback closures, exclusions or retrieval scratch survive.
        card = copy.deepcopy(self.c.card)
        self.c = run.Ctx()
        vars(self.c).update(copy.deepcopy(self.context_inputs), card=card, role_cancel=threading.Event())
        self.c.args.resume = self.c.case_id
        # The engine loads a step's runner settings from the saved card, as here (run.py, the
        # ENGINE_SETTINGS loop): a case that adopted the new-case settings in its writer round keeps
        # them, and with them its stress binding, on every retry.
        for key, value in (card.get('recovery_config') or {}).items():
            if key in run.ENGINE_SETTINGS: setattr(self.c.args, key, value)
        self.c.stress_checkpoint = lambda: True
        return self.c

    def cli(self, emit):
        calls = self.calls
        def invoke(runtime, c, models, text, cwd, name, **kwargs):
            c.model_process_state['started'] = True
            calls.append((name, c.model_lease.route, text))
            # The freshness roles search in their own working copies, so they need the call's directory.
            emit(c, text, name, **({'cwd': cwd} if 'cwd' in inspect.signature(emit).parameters else {}))
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
        with self.assertRaisesRegex(budget.BudgetError, 'provider_wait_deadline'):
            ordinary_retry.transport(self.c, {}, fetch)
        self.assertEqual(len(count), 5)

    def test_retained_schema_repair_replays_without_new_call(self):
        def emit(c, text, name):
            self.answer_path(text).write_text(json.dumps({'approve': True, **({'reason': 'retained rationale'} if len(self.calls) == 2 else {})}))
        self.cli(emit)
        self.assertTrue(self.idea()['approve'])
        self.assertEqual(len(self.calls), 2)
        self.assertIn('Retained answer:', self.calls[1][2])
        self.c.engine.key = self.c.engine.key.rsplit('/', 1)[0]+'/2'
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
        self.fresh_context()
        self.c.engine.key = self.c.engine.key.rsplit('/', 1)[0]+'/2'
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

    def test_exhausted_answer_gets_one_fresh_judgment_per_new_engine_attempt(self):
        self.c.models['reviewers'] = [self.c.models['builder']]
        self.c.card['roles']['reviewer']['model'] = self.c.models['builder'][0]
        def emit(c, text, name):
            if len(self.calls) > 1:
                state = next(json.loads(p.read_text()) for p in (self.work/'ordinary-retries').glob('*/state.json')
                             if json.loads(p.read_text()).get('binding', {}).get('kind')=='idea')
                self.assertEqual(state['engine_attempt'], c.engine.key)
                self.assertEqual(state['attempts'][-1]['phase'], 'pending')
                self.assertEqual(len(state['exhausted_attempts']), 1)
                self.answer_path(text).write_text('{"approve":true,"reason":"valid fresh judgment"}')
        self.cli(emit)
        for _ in range(2):
            with self.assertRaisesRegex(budget.BudgetError, '^malformed_output_exhausted$'): self.idea()
        self.assertEqual(len(self.calls), 1)
        before = json.loads(self.ledger.read_text())
        self.fresh_context()
        self.c.models['reviewers'] = [self.c.models['builder']]
        self.c.engine.key = self.c.engine.key.rsplit('/', 1)[0]+'/2'
        self.assertTrue(self.idea()['approve'])
        self.assertTrue(self.idea()['approve'])
        self.assertEqual(len(self.calls), 2)
        state = next(json.loads(p.read_text()) for p in (self.work/'ordinary-retries').glob('*/state.json')
                     if json.loads(p.read_text()).get('binding', {}).get('kind')=='idea')
        self.assertEqual([row['phase'] for row in state['attempts']], ['invalid', 'completed'])
        self.assertEqual(len(state['exhausted_attempts']), 1)
        after = json.loads(self.ledger.read_text())
        for key, value in before.get('invocation_reservations', {}).items():
            self.assertEqual(after['invocation_reservations'][key], value)

    def board_dedup(self, identity='one'):
        out = self.work / 'dedup.json'
        return run.retained_answer(self.c, self.c.models['easy_calibrator'], 'OUTPUT: ' + str(out),
            self.work, 'easy-calibrator-dedup', out, {'statement': 'candidate', 'revision': identity}, 'dedup',
            '{duplicate_of: case ID or null, reason: nonempty string}',
            lambda v: isinstance(v, dict) and 'duplicate_of' in v and bool(v.get('reason')))

    def test_cae763_walled_role_exhausts_its_one_gated_route_and_resets_next_attempt(self):
        # cae763-h3 (2026-11-18): the easy calibrator may lease only the gated OpenRouter lane of GLM's
        # chain (never Go or free). One empty answer spent that lane; spent_routes was compared with the
        # whole chain, so it never counted as exhausted, never reset on a new attempt, and every retry
        # failed at once as router:unbounded_route with no call.
        glm = 'openrouter/z-ai/glm-5.3-flash'
        self.assertTrue(any(r['route'].startswith('opencode') for r in model_router.routes(glm)))
        def setup():
            self.c.models['easy_calibrator'] = [glm]
            self.c.args.easy_calibrator = glm
        setup()
        def emit(c, text, name):
            if len(self.calls) > 1:
                self.answer_path(text).write_text('{"duplicate_of":null,"reason":"fresh judgment"}')
        self.cli(emit)
        for _ in range(2):
            with self.assertRaisesRegex(budget.BudgetError, '^malformed_output_exhausted$'): self.board_dedup()
        self.assertEqual([(n, r) for n, r, _ in self.calls], [('easy-calibrator-dedup', glm)])
        self.fresh_context(); setup()
        self.c.engine.key = self.c.engine.key.rsplit('/', 1)[0] + '/2'
        self.assertIsNone(self.board_dedup()['duplicate_of'])
        self.assertEqual([r for _, r, _ in self.calls], [glm, glm])
        state = self.dedup_state()
        self.assertEqual(state['exhausted_attempts'][0]['spent_routes'], [glm])
        self.assertEqual([row['phase'] for row in state['attempts']], ['invalid', 'completed'])

    def test_a_spent_neuralwatt_route_survives_the_key_being_withdrawn(self):
        # neuralwatt-routes rollback: a case spent the NW lane while its box held the key, then the key was
        # withdrawn. Its snapshot keeps that route in spent_routes; the next attempt must not fail
        # infra:ordinary_retry_state_invalid on every retry.
        glm = 'openrouter/z-ai/glm-5.3-flash'
        def setup():
            self.c.models['easy_calibrator'] = [glm]
            self.c.args.easy_calibrator = glm
        setup()
        self.cli(lambda c, text, name: len(self.calls) > 1 and
                 self.answer_path(text).write_text('{"duplicate_of":null,"reason":"fresh judgment"}'))
        for _ in range(2):
            with self.assertRaisesRegex(budget.BudgetError, '^malformed_output_exhausted$'): self.board_dedup()
        path = self.dedup_state(path=True)
        state = json.loads(path.read_text())
        state['spent_routes'].append('neuralwatt/glm-5.3-flash')
        path.write_text(json.dumps(state))
        self.fresh_context(); setup()
        self.c.router_accounts = [a for a in model_router.ACCOUNTS if a != 'neuralwatt-key']   # key withdrawn
        self.c.engine.key = self.c.engine.key.rsplit('/', 1)[0] + '/2'
        self.assertIsNone(self.board_dedup()['duplicate_of'])
        self.assertEqual([r for _, r, _ in self.calls], [glm, glm])

    def dedup_state(self, path=False):
        found = next(p for p in (self.work / 'ordinary-retries').glob('*/state.json')
                     if json.loads(p.read_text()).get('binding', {}).get('kind') == 'dedup')
        return found if path else json.loads(found.read_text())

    def test_cae763_saved_stuck_pending_judgment_resets_on_the_next_attempt(self):
        # The exact shape cae763-h3 saved before the fix: its gated lane spent, then a pending judgment
        # queued whose call found no lane. The next engine attempt must reset it and call once.
        glm = 'openrouter/z-ai/glm-5.3-flash'
        def setup():
            self.c.models['easy_calibrator'] = [glm]
            self.c.args.easy_calibrator = glm
        setup()
        def emit(c, text, name):
            if len(self.calls) > 1:
                self.answer_path(text).write_text('{"duplicate_of":null,"reason":"fresh judgment"}')
        self.cli(emit)
        with self.assertRaisesRegex(budget.BudgetError, '^malformed_output_exhausted$'): self.board_dedup()
        path = self.dedup_state(path=True)
        state = json.loads(path.read_text())
        state['attempts'].append({'kind': 'judgment', 'phase': 'pending', 'output': f'answer-{len(state["attempts"])}.json'})
        atomic_json(path, state)
        self.fresh_context(); setup()
        self.c.engine.key = self.c.engine.key.rsplit('/', 1)[0] + '/2'
        self.assertIsNone(self.board_dedup()['duplicate_of'])
        self.assertEqual([r for _, r, _ in self.calls], [glm, glm])
        state = self.dedup_state()
        self.assertEqual([row['phase'] for row in state['attempts']], ['invalid', 'completed'])
        self.assertEqual(len(state['exhausted_attempts']), 1)

    def test_pending_answer_adopts_new_attempt_before_it_exhausts(self):
        self.c.models['reviewers'] = [self.c.models['builder']]
        self.c.card['roles']['reviewer']['model'] = self.c.models['builder'][0]
        def emit(c, text, name):
            if len(self.calls)==1: raise runtime_fixture.Killed()
        self.cli(emit)
        with self.assertRaises(runtime_fixture.Killed): self.idea()
        self.fresh_context(); self.c.models['reviewers'] = [self.c.models['builder']]
        self.c.engine.key = self.c.engine.key.rsplit('/', 1)[0]+'/2'
        for _ in range(2):
            with self.assertRaisesRegex(budget.BudgetError, '^malformed_output_exhausted$'): self.idea()
        self.assertEqual(len(self.calls), 2)

    def test_legacy_exhaustion_adopts_first_key_without_guessing_a_reset(self):
        self.c.models['reviewers'] = [self.c.models['builder']]
        self.c.card['roles']['reviewer']['model'] = self.c.models['builder'][0]
        def emit(c, text, name):
            if len(self.calls)>1: self.answer_path(text).write_text('{"approve":true,"reason":"fresh judgment"}')
        self.cli(emit)
        with self.assertRaisesRegex(budget.BudgetError, '^malformed_output_exhausted$'): self.idea()
        path = next((self.work/'ordinary-retries').glob('*/state.json'))
        state = json.loads(path.read_text()); state.pop('engine_attempt'); atomic_json(path,state)
        self.c.engine.key = self.c.engine.key.rsplit('/', 1)[0]+'/2'
        for _ in range(2):
            with self.assertRaisesRegex(budget.BudgetError, '^malformed_output_exhausted$'): self.idea()
        self.assertEqual(len(self.calls),1)
        self.c.engine.key = self.c.engine.key.rsplit('/', 1)[0]+'/3'
        self.assertTrue(self.idea()['approve'])
        self.assertEqual(len(self.calls),2)

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
        def emit(c, text, name, cwd):
            who = name.split('-')[0]
            rows = [json.loads(line) for line in (Path(cwd) / 'freshness.jsonl').read_text().splitlines()]
            for row in rows:
                if row['who'] == who: row['at'] = datetime.now(timezone.utc).isoformat()
            (Path(cwd) / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.cli(emit)
        self.assertTrue(run.g2(self.c)[0])
        self.searches(True)
        self.assertTrue(run.g2(self.c)[0])
        state = json.loads((self.work / 'freshness-repair.json').read_text())
        self.assertEqual(state['completed_defects'], 0)
        self.assertEqual(len(self.calls), 4)

    def test_ineffective_refresh_is_a_retryable_stall_not_a_defect(self):
        # A refresh that re-ran no search is a retrieval outage: it stops this attempt with its own
        # infra reason, and it never spends the defect bound that would block every later refresh.
        self.searches(True)
        self.cli(lambda *a: None)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_refresh_stalled$'): run.g2(self.c)
        self.assertEqual(json.loads((self.work/'freshness-repair.json').read_text())['completed_defects'], 0)
        self.assertEqual(len(self.calls), 2)

    def test_expired_and_unretrieved_rows_are_refreshed_after_spent_defects(self):
        # case-import-f46dac-5-1, 11-14 November: two earlier repairs had spent the defect bound, so
        # every writer round stopped freshness_evidence_unavailable on 78 expired and 4 retrieval-failed
        # rows without re-running a single search, and the rows only grew older.
        rows = self.searches(True)
        rows[0]['retrieved'] = rows[-1]['retrieved'] = False
        (self.case / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        atomic_json(self.work / 'freshness-repair.json', {'version': 2, 'completed_defects': 2, 'pending': None,
            'statement_sha256': hashlib.sha256((self.case / 'statement.md').read_bytes()).hexdigest()})
        self.patch(retrieval, 'fetch', lambda url, **kw: ({'url':url,'final_url':url,'status':200},HTTP['body'].encode()))
        def emit(c, text, name, cwd):
            who = name.split('-')[0]
            rows = [json.loads(line) for line in (Path(cwd) / 'freshness.jsonl').read_text().splitlines()]
            for row in rows:
                if row['who'] == who: row.update(at=datetime.now(timezone.utc).isoformat(), retrieved=True)
            (Path(cwd) / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.cli(emit)
        self.assertTrue(run.g2(self.c)[0])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(run.jload(self.work / 'freshness-repair.json')['completed_defects'], 2)

    def test_new_valid_searches_count_as_refresh_progress(self):
        # A top-up opened because searches were short appends a real search and one that came back
        # unretrieved: it made progress, so it is not a stall; the next refresh retrieves the row.
        rows = self.searches()
        (self.case / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows[1:]))
        self.patch(retrieval, 'fetch', lambda url, **kw: ({'url':url,'final_url':url,'status':200},HTTP['body'].encode()))
        def emit(c, text, name, cwd):
            path = Path(cwd) / 'freshness.jsonl'
            current = [json.loads(line) for line in path.read_text().splitlines()]
            if len(self.calls) == 1:
                current += [{**rows[0], 'query': 'new web query', 'url': 'https://github.com/medusajs/medusa/issues/90'},
                            {**rows[0], 'query': 'unretrieved web query', 'retrieved': False,
                             'url': 'https://github.com/medusajs/medusa/issues/91'}]
            else:
                for row in current: row['retrieved'] = True
            path.write_text(''.join(json.dumps(r)+'\n' for r in current))
        self.cli(emit)
        self.assertTrue(run.g2(self.c)[0])
        self.assertEqual([name for name, _, _ in self.calls], ['builder-freshness'] * 2)
        self.assertEqual(run.jload(self.work / 'freshness-repair.json')['completed_defects'], 0)

    def test_an_unretrieved_row_with_spare_searches_stalls_after_one_useless_refresh(self):
        # Every top-up may add spare searches. With G2's minimum already met they are no progress on
        # the unretrieved row: one refresh that fixed nothing stalls.
        rows = self.searches()
        dead = {**rows[0], 'query': 'dead link query', 'retrieved': False,
                'url': 'https://github.com/medusajs/medusa/issues/404'}
        (self.case / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows + [dead]))
        def emit(c, text, name, cwd):
            path = Path(cwd) / 'freshness.jsonl'
            extra = [{**rows[0], 'query': f'spare query {len(self.calls)} {i}',
                      'url': f'https://github.com/medusajs/medusa/issues/{200 + 10 * len(self.calls) + i}'} for i in range(2)]
            path.write_text(path.read_text() + ''.join(json.dumps(r)+'\n' for r in extra))
        self.cli(emit)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_refresh_stalled$'): run.g2(self.c)
        self.assertEqual([name for name, _, _ in self.calls], ['builder-freshness'])
        self.assertEqual(run.jload(self.work / 'freshness-repair.json')['completed_defects'], 0)

    def short_builder_and_unretrieved_attacker_row(self, builder_adds):
        """Builder short of web searches; one attacker row stays unretrieved. The attacker always adds
        two spare searches; the builder adds one valid web search only if builder_adds."""
        rows = self.searches()
        dead = {**rows[-1], 'query': 'unretrieved attacker query', 'retrieved': False,
                'url': 'https://github.com/medusajs/medusa/issues/404'}
        (self.case / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows[1:] + [dead]))
        self.patch(retrieval, 'fetch', lambda url, **kw: ({'url':url,'final_url':url,'status':200},HTTP['body'].encode()))
        def emit(c, text, name, cwd):
            path, n = Path(cwd) / 'freshness.jsonl', len(self.calls)
            source = rows[0] if name.startswith('builder') else rows[-1]
            extra = [] if name.startswith('builder') and not builder_adds else [
                {**source, 'query': f'{name} spare {n} {i}',
                 'url': f'https://github.com/medusajs/medusa/issues/{300 + 10 * n + i}'}
                for i in range(1 if name.startswith('builder') else 2)]
            path.write_text(path.read_text() + ''.join(json.dumps(r)+'\n' for r in extra))
        self.cli(emit)

    def test_spare_searches_of_another_role_do_not_rescue_a_short_role(self):
        # A role still short after its top-up is a real defect, not a refresh: the attacker's spares do
        # not count for it, and two such top-ups spend the defect bound.
        self.short_builder_and_unretrieved_attacker_row(builder_adds=False)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_evidence_unavailable$'): run.g2(self.c)
        self.assertEqual(sorted(name for name, _, _ in self.calls), ['attacker-freshness'] * 2 + ['builder-freshness'] * 2)
        self.assertEqual(run.jload(self.work / 'freshness-repair.json')['completed_defects'], 2)

    def test_valid_searches_added_by_the_short_role_are_progress(self):
        self.short_builder_and_unretrieved_attacker_row(builder_adds=True)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_refresh_stalled$'): run.g2(self.c)
        # The builder's new search was progress, so a second refresh ran; it fixed nothing and stalled.
        self.assertEqual(sorted(name for name, _, _ in self.calls),
                         ['attacker-freshness', 'attacker-freshness', 'builder-freshness'])

    def test_a_real_defect_still_stops_after_spent_defects(self):
        rows = self.searches(True)
        rows[0]['app_version'] = 'not a version'
        (self.case / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        atomic_json(self.work / 'freshness-repair.json', {'version': 2, 'completed_defects': 2, 'pending': None,
            'statement_sha256': hashlib.sha256((self.case / 'statement.md').read_bytes()).hexdigest()})
        self.cli(lambda *a: self.fail('a spent defect bound buys no more repairs'))
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_evidence_unavailable$'): run.g2(self.c)

    def bot_challenged_row(self, **fields):
        """G2's minimum met, plus one search whose result page never retrieves (case f46dac's
        html.duckduckgo.com rows, logged retrieved:false)."""
        rows = self.searches()
        dead = {**rows[0], 'query': 'bot challenged query', 'retrieved': False,
                'url': 'https://html.duckduckgo.com/html/?q=bot+challenged+query', **fields}
        (self.case / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows + [dead]))
        self.patch(retrieval, 'fetch', lambda url, **kw: ({'url':url,'final_url':url,'status':200},HTTP['body'].encode()))
        return rows, dead

    def test_a_rerun_of_an_unretrievable_search_supersedes_it(self):
        # case-import-f46dac-5-1: a row whose result URL never retrieves could not be dropped (history is
        # restored) nor amended truthfully, so G2 stayed blocked forever. A valid re-run of the same query
        # logged as a new row replaces it; the old row stays in the log as history.
        rows, dead = self.bot_challenged_row()
        def emit(c, text, name, cwd):
            path = Path(cwd) / 'freshness.jsonl'
            rerun = {**dead, 'retrieved': True, 'url': 'https://github.com/medusajs/medusa/issues/77'}
            rerun.pop('_search_id', None)
            path.write_text(path.read_text() + json.dumps(rerun) + '\n')
        self.cli(emit)
        ok, info = run.g2(self.c)
        self.assertTrue(ok, info)
        self.assertEqual(info['superseded_searches'], 1)
        self.assertIn(dead['url'], [r['url'] for r in run.freshness_lines(self.c)])
        self.assertEqual(run.jload(self.work / 'freshness-repair.json')['completed_defects'], 0)

    def test_an_unretrieved_rows_missing_note_is_refresh_work_not_a_defect(self):
        # An unretrieved result has no note yet; a refresh that could not re-run it stalls (retryable)
        # and never spends the defect bound, which would stop every later round.
        self.bot_challenged_row(note='')
        atomic_json(self.work / 'freshness-repair.json', {'version': 2, 'completed_defects': 1, 'pending': None,
            'statement_sha256': hashlib.sha256((self.case / 'statement.md').read_bytes()).hexdigest()})
        self.cli(lambda *a: None)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_refresh_stalled$'): run.g2(self.c)
        self.assertEqual(run.jload(self.work / 'freshness-repair.json')['completed_defects'], 1)

    def test_a_flagged_unretrieved_row_is_never_superseded(self):
        # The science check: a possible public match stays blocking whatever else was searched.
        rows = self.searches()
        flagged = {**rows[0], 'retrieved': False, 'hit': True}
        lines = rows + [flagged, {**rows[0], 'retrieved': False}, {**rows[0], 'retrieved': False, 'who': 'attacker'}]
        self.assertEqual(admission.superseded(lines), [False] * len(rows) + [False, True, False])

    def stress_setup(self, emit):
        self.patch(run, 'g1', return_value=(True, {'problems': []}))
        self.patch(run, 'early_checks', return_value=None)
        self.patch(run, 'early_review', return_value=None)
        self.patch(run, 'ensure_freshness', return_value=(True, {}))
        self.patch(run, 'engine_prepare_bench', return_value=None)
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

    def stress_round(self, c, previous=None):
        if not c.card.get('builder_rounds'):
            self.assertEqual(run.engine_writer_round(c, 1, None)['reason'], 'writer:validated')
        return run.engine_stress_round(c, 1)

    def timeout_report(self, category, raw):
        timed_out = [False]
        def emit(config, value):
            value['non_blocking'] = ['retained observation: ' + config['category']]
            if config['category'] == category and not timed_out[0]:
                timed_out[0] = True
                if raw is not None: Path(config['category_output']).write_bytes(raw)
                raise budget.BudgetError('timeout')
        self.stress_setup(emit)
        with self.assertRaisesRegex(budget.BudgetError, '^timeout$'):
            self.stress_round(self.c, {})
        report = run.attack_report(self.work/'attacks/round-1.json')
        receipt = run.jload(self.work/'attack-state.json')
        self.assertEqual((report['status'], report['complete'], report['stop_reason']), ('pending', False, 'timeout'))
        self.assertEqual(report['operation_id'], receipt['operation_id'])
        self.assertEqual(report['round'], receipt['round'])
        self.assertEqual(report['blocking'], [])
        self.assertEqual((receipt['phase'], receipt['review_pending']), ('pending', True))
        self.assertTrue(run.jload(self.work/'stress-publication.json')['pending'])
        done = list(stress_progress.CATEGORIES)[:list(stress_progress.CATEGORIES).index(category)]
        self.assertEqual([k for k,v in report['coverage'].items() if v['complete']], sorted(done))
        self.assertEqual(report['non_blocking'], ['retained observation: ' + k for k in done])
        self.assertEqual(report['coverage'][category]['pending'], sorted(stress_progress.CATEGORIES[category]))
        partials = [(self.work/r['file']).read_bytes() for r in report['partial_reports']]
        for row in report['partial_reports']:
            self.assertEqual(hashlib.sha256((self.work/row['file']).read_bytes()).hexdigest(), row['sha256'])
        if raw is not None: self.assertIn(raw, partials)
        elif not done: self.assertEqual(partials, [])
        before = {p.relative_to(self.work): p.read_bytes() for p in self.work.glob('attacks/round-1-categories/*/*-0.json')}
        # Actual archive/restore of the captured case and ledger plus runtime evidence.
        archive = self.work.with_suffix('.row13.tar')
        self.addCleanup(archive.unlink, missing_ok=True)
        with tarfile.open(archive, 'w') as tar: tar.add(self.work, arcname=self.work.name)
        shutil.rmtree(self.work)
        with tarfile.open(archive) as tar: tar.extractall(self.work.parent, filter='data')
        self.assertEqual(run.attack_report(self.work/'attacks/round-1.json'), report)
        self.fresh_context()
        resumed = len(self.calls)
        self.stress_round(self.c, copy.deepcopy(self.c.card))
        final = run.attack_report(self.work/'attacks/round-1.json')
        self.assertEqual((final['status'], final['complete'], final['stop_reason']), ('scored', True, None))
        self.assertEqual(final['operation_id'], receipt['operation_id'])
        self.assertEqual(self.c.card['builder_rounds'], 1)
        self.assertEqual(len(self.calls)-resumed, len(stress_progress.CATEGORIES)-len(done))
        for p, data in before.items(): self.assertEqual((self.work/p).read_bytes(), data)

    def test_row13_real_artifacts_timeout_before_output(self):
        self.timeout_report('wrong_fixes', None)

    def test_row13_real_artifacts_timeout_malformed_partial(self):
        self.timeout_report('wrong_fixes', b'{"blocking": ["untrusted partial"')

    def test_row13_real_artifacts_timeout_after_categories(self):
        self.timeout_report('fairness', b'{"category_complete":true,"blocking":["untrusted"]}')

    def test_category_kill_resumes_only_unfinished_and_preserves_operation(self):
        killed = [False]
        def emit(config, value):
            if config['category'] == 'fairness' and not killed[0]:
                killed[0] = True
                Path(config['category_output']).write_text(json.dumps({**value, 'category_complete': False}))
                raise runtime_fixture.Killed()
        self.stress_setup(emit)
        with self.assertRaises(runtime_fixture.Killed): self.stress_round(self.c, {})
        old = run.jload(self.work/'attack-state.json')
        self.assertEqual(old['phase'], 'pending')
        self.assertEqual(self.c.card['builder_rounds'],1)
        before = {p: p.read_bytes() for p in self.work.glob('attacks/round-1-categories/*/*-0.json')}
        self.fresh_context()
        self.stress_round(self.c, copy.deepcopy(self.c.card))
        after = run.jload(self.work/'attack-state.json')
        self.assertEqual(old['operation_id'], after['operation_id'])
        self.assertEqual(after['phase'], 'validated')
        self.assertEqual([call[0] for call in self.calls].count('builder-1'),1)
        self.assertEqual(len(self.calls),6) # writer, two complete categories, kill, two remaining
        for p,data in before.items(): self.assertEqual(p.read_bytes(),data)
        self.assertTrue(run.jload(self.work/'attacks/round-1.json')['complete'])

    def test_category_progress_survives_an_attempt_with_less_time_left(self):
        """run.context_for_step sets args.agent_timeout to the attempt's remaining time, and the stress
        binding (attack_binding, gate_state.judge_dependencies) held it: the category state folder was new
        on every engine attempt, so finished categories ran again."""
        killed = [False]
        def emit(config, value):
            if config['category'] == 'fairness' and not killed[0]:
                killed[0] = True
                raise runtime_fixture.Killed()
        self.stress_setup(emit)
        self.c.args.agent_timeout = 5_000.0   # as context_for_step: this attempt's remaining time
        with self.assertRaises(runtime_fixture.Killed): self.stress_round(self.c, {})
        first = len(self.calls)
        self.fresh_context()
        self.c.args.agent_timeout = 3_000.0
        self.stress_round(self.c, copy.deepcopy(self.c.card))
        self.assertEqual(len(list(self.work.glob('attacks/round-1-categories/*/state.json'))), 1)
        self.assertEqual(len(self.calls) - first, 2)   # the killed category and the one after it, nothing finished
        self.assertTrue(run.jload(self.work/'attacks/round-1.json')['complete'])

    def test_no_progress_is_operational_exhaustion_and_blocker_wins(self):
        def emit(config, value):
            value.update(category_complete=False, completed_subchecks=[], unfinished_validation=['authored diagnostic needed'])
        self.stress_setup(emit)
        with self.assertRaisesRegex(budget.BudgetError,'stress_validation_exhausted'): self.stress_round(self.c,{})
        self.assertEqual(len(self.calls),1+len(stress_progress.CATEGORIES)) # every category still gets its turn
        self.c.card.update(terminal_stop='stress_validation_exhausted',status='stopped',gates={})
        self.assertTrue(diagnosis.exhaustion(self.c.card))

    def test_resume_retries_exhausted_category(self):
        # A resumed stress step must call the attacker again for a category the first run left exhausted.
        stuck = [True]
        def emit(config, value):
            if stuck[0]: value.update(category_complete=False, completed_subchecks=[], unfinished_validation=['stuck'])
        self.stress_setup(emit)
        with self.assertRaisesRegex(budget.BudgetError,'stress_validation_exhausted'): self.stress_round(self.c,{})
        first = len(self.calls)
        stuck[0] = False
        self.fresh_context()
        self.stress_round(self.c, copy.deepcopy(self.c.card))
        self.assertGreater(len(self.calls), first)
        self.assertTrue(run.jload(self.work/'attacks/round-1.json')['complete'])

    def test_publication_retries_before_next_dispatch(self):
        uploaded, failures = [], [0]
        def checkpoint():
            uploaded.append(len(self.calls)); failures[0] += 1
            return failures[0] > 3
        self.c.stress_checkpoint = checkpoint
        self.patch(ordinary_retry, 'backoff', lambda *a,**k:None)
        self.stress_setup(lambda *a: None)
        self.stress_round(self.c,{})
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

    def unresolved_reviews(self, unresolved):
        """A live hit the reviewer leaves unresolved `unresolved` times, then clears."""
        rows = self.searches()
        rows[0]['hit'] = True
        (self.case / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.patch(retrieval, 'fetch', lambda url, **kw: ({'url':url,'final_url':url,'status':200},HTTP['body'].encode()))
        def emit(c, text, name):
            self.assertEqual(name, 'reviewer-g2-confirm')
            resolved = len(self.calls) > unresolved
            self.answer_path(text).write_text(json.dumps({'hits':[{
                'url':rows[0]['url'],'resolved':resolved,'same_bug':False if resolved else None,'retrieved':True,
                'app_version':'2.19.0','version_scope':'authored applicability','retrieved_from':'live',
                'archive_checked':False,'archive_available':None,'archive_snapshot_url':None,
                'live_failure':None,'why':'authored review'}]}))
        self.cli(emit)

    def test_an_unresolved_freshness_review_is_asked_again_in_the_same_attempt(self):
        """Nov 6-11: 8 admits failed infra:freshness_review_unavailable (4.2 h) on one unresolved review."""
        self.unresolved_reviews(1)
        self.assertTrue(run.g2(self.c)[0])
        self.assertEqual(len(self.calls), 2)          # a new question, not the retained unresolved answer
        self.assertEqual(self.c.card['freshness_reasks'], 1)

    def test_freshness_reasks_are_bounded_and_the_hit_still_blocks(self):
        self.unresolved_reviews(99)
        refetch, real = [], ordinary_freshness.obtain
        def obtain(c, rows, directory, **kw):
            refetch.append(set(getattr(c, 'freshness_refetch_urls', set())))
            return real(c, rows, directory, **kw)
        self.patch(ordinary_freshness, 'obtain', obtain)
        with self.assertRaisesRegex(budget.BudgetError, 'freshness_review_unavailable'): run.g2(self.c)
        self.assertEqual(len(self.calls), 1 + ordinary_freshness.REVIEW_REASKS)
        flagged = json.loads((self.case / 'freshness.jsonl').read_text().splitlines()[0])['url']
        self.assertIn(flagged, set().union(*refetch))   # a re-ask re-fetches held pages, not old receipts

    def bot_wall(self, walled_cycles, status=403, cancel_after=8, minutes=0, **row):
        """18681d (14-15 Nov): a flagged hit answers 403 with no Wayback copy for `walled_cycles` G2
        cycles, then 200 (`status` may be a tuple, one per cycle in turn). A fake clock runs obtain()'s
        120 s live window and moves the wall clock `minutes` per G2 cycle; the case's cancel event, set after `cancel_after` G2 cycles, stands in for the
        batch deadline that ended the real run. `row` overrides the flagged row's fields."""
        rows = self.searches()
        rows[0].update({'hit': True, **row})
        (self.case / 'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        url, cycles, clock = rows[0]['url'], [0], [0.0]
        def fetch(target, **kw):
            if target.startswith('https://archive.org/'):
                return {'url':target,'final_url':target,'status':200}, b'{"archived_snapshots": {}}'
            walled = target == url and cycles[0] < walled_cycles
            code = status[cycles[0] % len(status)] if isinstance(status, tuple) else status
            return ({'url':target,'final_url':target,'status':code if walled else 200},
                    b'authored bot wall %d' % cycles[0] if walled else HTTP['body'].encode())
        self.patch(retrieval, 'fetch', fetch)
        real_time = ordinary_freshness.time
        self.patch(ordinary_freshness, 'time', SimpleNamespace(time=lambda: real_time.time() + cycles[0] * minutes * 60,
                                                               monotonic=lambda: clock[0]))
        def backoff(c, failures=1, *, deadline=None):
            clock[0] += 60
            if deadline is None:   # ensure()'s wait between G2 cycles
                cycles[0] += 1
                if cycles[0] >= cancel_after: c.role_cancel.set()
            ordinary_retry.check(c)
        self.patch(ordinary_freshness, 'backoff', backoff)
        def emit(c, text, name):
            # A live clearance: it agrees with a reachable receipt and not with a walled one.
            self.answer_path(text).write_text(json.dumps({'hits':[{
                'url':url,'resolved':True,'same_bug':False,'retrieved':True,'app_version':'2.19.0',
                'version_scope':'authored applicability','retrieved_from':'live','archive_checked':False,
                'archive_available':None,'archive_snapshot_url':None,'live_failure':None,'why':'authored review'}]}))
        self.cli(emit)
        return url, cycles

    def test_a_bot_walled_hit_with_no_archive_stops_g2_for_a_person(self):
        url, cycles = self.bot_wall(99)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_source_blocked$'): run.g2(self.c)
        self.assertEqual(cycles[0], ordinary_freshness.SOURCE_BLOCKED_CYCLES - 1)
        blocked = self.c.card['freshness_stalled']
        self.assertEqual(blocked['sources'], [{'url': url, 'failure': 'http_403', 'archive': False}])
        self.assertEqual(blocked['cycles'], ordinary_freshness.SOURCE_BLOCKED_CYCLES)
        self.assertIn(url, blocked['note']); self.assertIn('http_403', blocked['note'])

    def test_cae763_a_waf_challenge_202_is_a_bot_wall_not_an_endless_transport_retry(self):
        # cae763 (16-17 Nov 22:38-04:00): flagged hit community.squareup.com answered every request
        # "HTTP 202, empty body, x-amzn-waf-action: challenge" with no Wayback copy. fetch(access=True)
        # raised it as transport infra, so ordinary_retry.transport retried it 756 times and G2 never
        # reached its stall/wall stop. It is a page answer: recorded, archive-checked, and a wall.
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        class Challenge(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(202); self.send_header('x-amzn-waf-action', 'challenge')
                self.send_header('Content-Length', '0'); self.end_headers()
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Challenge)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        page = f'http://127.0.0.1:{server.server_port}/t5/m-p/758102'
        response, body = retrieval.fetch(page, access=True)
        self.assertEqual((response['status'], body), (202, b''))
        with self.assertRaisesRegex(Exception, 'public response unavailable'): retrieval.fetch(page)
        url, cycles = self.bot_wall(99, status=202)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_source_blocked$'): run.g2(self.c)
        self.assertEqual(self.c.card['freshness_stalled']['sources'],
                         [{'url': url, 'failure': 'http_202', 'archive': False}])

    def test_cae763_a_flagged_row_the_searcher_could_not_read_goes_to_the_runner_not_a_deadlock(self):
        # cae763 diagnosis/4 (17 Nov 06:34, factory_bug, retired): rows 312-313 were ambiguous with
        # retrieved=false (a WAF-walled Square thread, a 404 Shopify thread). retrieval_failed made them
        # invalid evidence; invalid evidence skipped the runner's retrieval and the reviewer, the only steps
        # that settle a flagged page, and a flagged row is never superseded, so no refresh could clear it.
        # The runner's own retrieval decides a flagged page: a wall with no archive copy stops for a person.
        flagged = {'who': 'builder', 'kind': 'web', 'hit': False, 'ambiguous': True, 'retrieved': False}
        self.assertIsNone(admission.search_evidence_error({**flagged, **{k: v for k, v in self.searches()[0].items()
            if k not in flagged}}))
        unflagged = {**self.searches()[0], 'hit': False, 'ambiguous': False, 'retrieved': False}
        self.assertEqual(admission.search_evidence_error(unflagged), 'retrieval_failed')
        url, cycles = self.bot_wall(99, status=202, hit=False, ambiguous=True, retrieved=False)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_source_blocked$'): run.g2(self.c)
        self.assertEqual(self.c.card['freshness_stalled']['sources'],
                         [{'url': url, 'failure': 'http_202', 'archive': False}])

    def test_18681d_a_hit_rate_limited_every_cycle_stops_as_our_own_infra_stall(self):
        # The real loop (worker work dir, 15 Nov 09:30-12:44): ambiguous row 175, answeroverflow, answered
        # 429 with a new body and no Wayback copy on 39 cycles; the one retained review was reused each
        # time, about every 5.3 minutes. 429 can be our own rate limit (0cc00438), so G2 waits 30 minutes
        # on the unchanged hold, then stops as our own retryable infra stall, not the case's.
        url = 'https://www.answeroverflow.com/m/1485906875999453345'
        url_, cycles = self.bot_wall(99, status=429, minutes=5.3, url=url, hit=False, ambiguous=True)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_refresh_stalled$'): run.g2(self.c)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(cycles[0], 6)   # the 7th cycle is the first 30 minutes after the hold began
        stalled = self.c.card['freshness_stalled']
        self.assertEqual(stalled['sources'], [{'url': url, 'failure': 'http_429', 'archive': False}])
        self.assertGreaterEqual(stalled['minutes'], 30)

    def test_a_cleared_dead_page_does_not_make_a_rate_limit_the_cases_stop(self):
        # Row 2's page is gone (404, no archive) and G2 clears it; row 1 answers 429. Only row 1 holds G2,
        # so the stop is our own infra stall.
        held, dead, cycles, requests = self.held_http(archive=False, held_status=429, live_status=404, minutes=15)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_refresh_stalled$'): run.g2(self.c)
        self.assertEqual(cycles[0], 2)
        self.assertEqual(self.c.card['freshness_stalled']['sources'],
                         [{'url': held, 'failure': 'http_429', 'archive': False}])

    def new_worker(self):
        """A new worker gets only the retained snapshot of the work dir (the engine supplies the ledger)."""
        for path in self.work.iterdir():
            if path.name != 'ledger.json' and not any(fnmatch.fnmatch(path.name, p) for p in run.SNAPSHOT_RETAINED):
                shutil.rmtree(path) if path.is_dir() else path.unlink()
        return self.fresh_context()

    def test_each_retry_of_our_own_stall_gets_its_own_wait(self):
        url, cycles = self.bot_wall(99, status=429, minutes=5.3, cancel_after=8)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_refresh_stalled$'): run.g2(self.c)
        self.assertEqual(cycles[0], 6)
        # The engine's retry: its first held cycles continue (a 45-minute rate limit can still lift),
        # until the stand-in deadline.
        self.new_worker()
        with self.assertRaisesRegex(budget.BudgetError, '^cancelled$'): run.g2(self.c)
        self.assertEqual(cycles[0], 8)

    def test_a_walled_hit_with_an_archive_copy_is_our_own_stall_after_30_minutes(self):
        held, live, cycles, requests = self.held_http(minutes=15)
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_refresh_stalled$'): run.g2(self.c)
        self.assertEqual(cycles[0], 2)
        self.assertEqual(self.c.card['freshness_stalled']['sources'],
                         [{'url': held, 'failure': 'http_403', 'archive': True}])

    def test_an_outage_of_ours_that_also_holds_a_flagged_hit_keeps_the_deadline(self):
        # Every page answers 429, one of them a flagged hit: G2 backs off to the deadline (here the
        # fixture's kill after 3 cycles, 30 minutes in), as before the stall cap.
        self.held_http(archive=False, broad=True, held_status=429, minutes=15, flagged=1)
        with self.assertRaises(runtime_fixture.Killed): run.g2(self.c)
        self.assertNotIn('freshness_stalled', self.c.card)
        self.assertFalse((self.work / ordinary_freshness.STALLED).exists())

    def test_the_identical_cycle_count_survives_a_new_worker(self):
        url, cycles = self.bot_wall(99, cancel_after=ordinary_freshness.SOURCE_BLOCKED_CYCLES - 1)
        with self.assertRaisesRegex(budget.BudgetError, '^cancelled$'): run.g2(self.c)
        self.new_worker()
        with self.assertRaisesRegex(budget.BudgetError, '^freshness_source_blocked$'): run.g2(self.c)
        self.assertEqual(cycles[0], ordinary_freshness.SOURCE_BLOCKED_CYCLES - 1)   # stopped on its first cycle

    def test_a_cycle_with_new_information_starts_the_count_again(self):
        # The held page's failure changes every cycle: each cycle is new, so the stand-in deadline ends it.
        self.bot_wall(99, status=(403, 429))
        with self.assertRaisesRegex(budget.BudgetError, '^cancelled$'): run.g2(self.c)
        self.assertNotIn('freshness_stalled', self.c.card)

    def test_a_hit_walled_once_then_reachable_still_passes(self):
        self.bot_wall(1)
        self.assertTrue(run.g2(self.c)[0])
        self.assertFalse((self.work / 'g2-stalled.json').exists())

    def test_dedup_and_panel_callers_use_retained_schema_repair(self):
        self.c.models['easy_calibrator'] = self.c.models['reviewers'][0]
        self.c.models['reviewers'] = [*self.c.models['reviewers'], self.c.models['builder']]  # G8/G9: two reviewers
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
        self.assertEqual(len(self.calls),4)  # one panel call per reviewer, shared by G8 and G9
        # Semantic prior content, rather than the same path, invalidates dedup reuse.
        prior.write_text(prior.read_text()+' changed prior statement')
        self.assertTrue(run.statement_precheck(self.c))
        self.assertEqual(len(self.calls),6)

    def test_freshness_wait_does_not_repeat_completed_role(self):
        self.searches(True)
        self.patch(retrieval,'fetch',lambda url,**kw:({'url':url,'final_url':url,'status':200},HTTP['body'].encode()))
        killed = [False]
        def emit(c,text,name,cwd):
            who = name.split('-')[0]
            if who == 'attacker' and not killed[0]: killed[0]=True; raise runtime_fixture.Killed()
            rows = [json.loads(line) for line in (Path(cwd)/'freshness.jsonl').read_text().splitlines()]
            for row in rows:
                if row['who']==who: row['at']=datetime.now(timezone.utc).isoformat()
            (Path(cwd)/'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.cli(emit)
        with self.assertRaises(runtime_fixture.Killed): run.g2(self.c)
        self.assertEqual(run.jload(self.work/'freshness-repair.json')['completed_defects'],0)
        self.fresh_context()
        self.assertTrue(run.g2(self.c)[0])
        # The roles search together, so the first round's order is not fixed; the finished builder is not repeated.
        self.assertEqual(sorted(name for name,_,_ in self.calls),['attacker-freshness','attacker-freshness','builder-freshness'])

    def test_progress_bound_exhausts_at_last_subcheck(self):
        count = [0]
        def emit(config,value):
            count[0]+=1
            value.update(category_complete=False, completed_subchecks=config['required_subchecks'][:count[0]],
                         unfinished_validation=['authored unexecuted check'])
        self.stress_setup(emit)
        with self.assertRaisesRegex(budget.BudgetError,'stress_validation_exhausted'): self.stress_round(self.c,{})
        self.assertEqual(count[0],len(stress_progress.CATEGORIES['wrong_fixes'])+len(stress_progress.CATEGORIES)-1)
        self.assertEqual(self.c.card['builder_rounds'],1)

    def test_interrupted_diagnostic_still_reports_other_categories_findings(self):
        # 1110b: the round's one diagnostic timed out; that must not end the round before the attacker
        # looked at any category, and a finding anywhere reaches the writer.
        def emit(config,value):
            if config['category'] == 'wrong_fixes':
                value.update(category_complete=False,completed_subchecks=[],unfinished_validation=['diagnostic timed out'])
            if config['category'] == 'fairness': value['blocking'] = ['a real defect']
        self.stress_setup(emit)
        claimed = self.work/'diagnostic-budgets/attacker-1/claimed'
        claimed.mkdir(parents=True)
        atomic_json(claimed.parent/'status.json',{'status':'timeout'})
        result = self.stress_round(self.c,{})
        self.assertEqual(result['reason'],'stress:findings')
        self.assertEqual(len(self.calls),1+len(stress_progress.CATEGORIES))
        report = run.jload(self.work/'attacks/round-1.json')
        self.assertEqual(report['blocking'],['a real defect'])
        self.assertIn('diagnostic timed out',report['unfinished_validation'])
        self.assertFalse(report['coverage']['wrong_fixes']['complete'])
        self.assertFalse(report['complete'])

    def test_interrupted_diagnostic_without_findings_is_not_clean(self):
        self.stress_setup(lambda *a:None)
        claimed = self.work/'diagnostic-budgets/attacker-1/claimed'
        claimed.mkdir(parents=True)
        atomic_json(claimed.parent/'status.json',{'status':'timeout'})
        with self.assertRaisesRegex(budget.BudgetError,'stress_validation_exhausted'): self.stress_round(self.c,{})
        self.assertEqual(len(self.calls),1+len(stress_progress.CATEGORIES))

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
        result = self.stress_round(self.c,{})
        self.assertEqual(result['reason'], 'stress:findings')
        self.assertIn('authored definite defect', result['feedback'].decode())
        # One writer call, then one call per category: a finding ends its category, never the round.
        self.assertEqual(len(self.calls),1+len(stress_progress.CATEGORIES))
        self.assertEqual(run.jload(self.work/'attacks/round-1.json')['blocking'],['authored definite defect'])

    def test_one_round_reports_the_findings_of_every_category(self):
        self.c.args.rounds=1
        def emit(config,value):
            if config['category'] in ('wrong_fixes','fairness'):
                value.update(blocking=['defect in '+config['category']])
        self.stress_setup(emit)
        result = self.stress_round(self.c,{})
        self.assertEqual(result['reason'], 'stress:findings')
        report = run.jload(self.work/'attacks/round-1.json')
        self.assertEqual(report['blocking'],['defect in wrong_fixes','defect in fairness'])
        self.assertEqual({k for k,v in report['coverage'].items() if v['complete']}, set(stress_progress.CATEGORIES))
        self.assertEqual(len(self.calls),1+len(stress_progress.CATEGORIES))

    def test_an_attacker_that_repeats_retained_findings_still_covers_later_categories(self):
        self.c.args.rounds=1
        def emit(config,value):
            # The request says "Retain prior findings": a compliant attacker copies them back.
            value.update(blocking=list(config['retained_findings']['blocking']))
            if config['category']=='wrong_fixes' and not config['completed_subchecks']:
                value.update(category_complete=False, completed_subchecks=[], blocking=['defect in wrong_fixes'])
        self.stress_setup(emit)
        result = self.stress_round(self.c,{})
        self.assertEqual(result['reason'], 'stress:findings')
        report = run.jload(self.work/'attacks/round-1.json')
        self.assertEqual(report['blocking'],['defect in wrong_fixes'])
        self.assertEqual({k for k,v in report['coverage'].items() if v['complete']},
                         set(stress_progress.CATEGORIES)-{'wrong_fixes'})
        state = run.jload(self.work/report['category_state'])['categories']
        self.assertEqual([k for k,v in state.items() if v.get('found')], ['wrong_fixes'])

    def test_publication_kill_keeps_completed_category_on_resume(self):
        killed=[False]
        def checkpoint():
            if not killed[0]: killed[0]=True; raise runtime_fixture.Killed()
            return True
        self.c.stress_checkpoint=checkpoint
        self.stress_setup(lambda *a:None)
        with self.assertRaises(runtime_fixture.Killed): self.stress_round(self.c,{})
        self.assertTrue(run.jload(self.work/'stress-publication.json')['pending'])
        self.assertEqual(len(self.calls),2)
        self.fresh_context()
        self.stress_round(self.c,copy.deepcopy(self.c.card))
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

    def test_duplicate_decision_keys_are_not_repairable_projection(self):
        with self.assertRaisesRegex(ValueError,'duplicate JSON key'):
            ordinary_retry.decode(b'{"approve":false,"approve":true}')
        with self.assertRaises((KeyError, ValueError)):
            ordinary_retry.projection({'hits':[{'url':'https://github.com/medusajs',
                'resolved':True,'retrieved':True,'same_bug':False}]},'freshness')

    def held_http(self, *, archive=True, broad=False, recover=False, held_status=403, live_status=200, minutes=0,
                  flagged=None):
        rows = self.searches()
        for index, row in enumerate(rows):
            row['url'] = f'https://github.com/medusajs/medusa/issues/{index + 1}'
            row['hit'] = index < (flagged if flagged is not None else 0 if broad else 2)
        (self.case/'freshness.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        held, live = rows[0]['url'], rows[1]['url']
        clock, cycles, requests = [0.0], [0], []
        real = __import__('time').time
        self.patch(ordinary_freshness, 'time', SimpleNamespace(monotonic=lambda: clock[0],
                                                               time=lambda: real() + cycles[0] * minutes * 60))
        def wait(c, failures=1, *, deadline=None):
            if deadline is not None:
                clock[0] = deadline
            else:
                cycles[0] += 1
                if not recover and cycles[0] == 3: raise runtime_fixture.Killed()
                if recover and cycles[0] > 3: self.fail('recovery did not leave hold')
        self.patch(ordinary_freshness, 'backoff', wait)
        def fetch(url, **kwargs):
            requests.append(url)
            if url.startswith('https://archive.org/'):
                from urllib.parse import unquote
                original = unquote(url.split('url=')[1])
                closest = {'closest': {'url':'https://web.archive.org/web/20261001000000/'+original,
                           'available':True,'status':'200'}} if archive else {}
                status, body = 200, json.dumps({'archived_snapshots':closest}).encode()
            elif 'web.archive.org' in url:
                self.assertIn('id_/', url)
                status, body = 200, HTTP['body'].encode()
            elif (broad or url == held) and not (recover and cycles[0] >= 2):
                status, body = held_status, b'authored bot wall'
            elif live_status != 200:
                status, body = live_status, b''
            else:
                status, body = 200, (HTTP['body'] + str(requests.count(url))).encode()
            return {'url':url,'final_url':url,'status':status}, body
        self.patch(retrieval,'fetch',fetch)
        def emit(c,text,name):
            self.assertEqual(name, 'reviewer-g2-confirm')
            self.assertIn('Copy live_failure exactly',text)
            hits=[]
            for receipt in c.freshness_retrieval:
                hits.append({**{k:receipt[k] for k in ('url','retrieved_from','archive_available',
                    'archive_snapshot_url','live_failure')}, 'resolved':True,
                    'same_bug':False if receipt['retrieved_from'] != 'none' else None,
                    'retrieved':receipt['retrieved_from'] != 'none','archive_checked':True,
                    'app_version':'2.19.0','version_scope':'authored comparison','why':'authored exclusion'})
            self.answer_path(text).write_text(json.dumps({'hits':hits}))
        self.cli(emit)
        return held, live, cycles, requests

    def test_mixed_held_and_changing_live_page_reuses_real_orchestration_judgment(self):
        held, live, cycles, requests = self.held_http()
        with self.assertRaises(runtime_fixture.Killed): run.g2(self.c)
        self.assertEqual(cycles[0],3)
        self.assertEqual(requests.count(live),1)
        self.assertGreater(requests.count(held),3)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(run.jload(self.work/'freshness-repair.json')['completed_defects'],0)

    def test_403_without_archive_holds_until_live_recovery(self):
        held, live, cycles, requests = self.held_http(archive=False,recover=True)
        self.assertTrue(run.g2(self.c)[0])
        self.assertEqual(cycles[0],2)
        self.assertEqual(len(self.calls),2)  # no archive, then new live bytes
        self.assertEqual(requests.count(live),1)
        self.assertFalse(self.c.freshness_refetch_urls)

    def test_broad_http_outage_never_buys_topup(self):
        self.held_http(archive=False,broad=True,recover=True)
        self.assertTrue(run.g2(self.c)[0])
        self.assertEqual(self.calls,[])
        self.assertEqual(run.jload(self.work/'freshness-repair.json')['completed_defects'],0)

    def test_last_category_interrupted_diagnostic_is_recognized_exhaustion(self):
        def emit(config,value):
            if config['category'] == 'v2_strategies':
                claimed = self.work/'diagnostic-budgets/attacker-1/claimed'
                claimed.mkdir(parents=True)
                atomic_json(claimed.parent/'status.json',{'status':'timeout'})
        self.stress_setup(emit)
        for attempt in range(2):
            if attempt: self.fresh_context()
            with self.assertRaisesRegex(budget.BudgetError,'^stress_validation_exhausted$'):
                self.stress_round(self.c,copy.deepcopy(self.c.card) if attempt else {})
            self.assertEqual(len(self.calls),5)

    def test_publication_marker_precedes_category_state_commit(self):
        real = stress_progress.atomic_json
        killed=[False]
        def write(path,value):
            if (path.name=='state.json' and 'categories' in value and
                    value['categories'].get('wrong_fixes',{}).get('complete') and not killed[0]):
                killed[0]=True
                self.assertTrue(run.jload(self.work/'stress-publication.json')['pending'])
                raise runtime_fixture.Killed()
            return real(path,value)
        self.patch(stress_progress,'atomic_json',write)
        self.stress_setup(lambda *a:None)
        with self.assertRaises(runtime_fixture.Killed): self.stress_round(self.c,{})
        uploads=[]
        self.fresh_context()
        self.c.stress_checkpoint=lambda: uploads.append(len(self.calls)) or True
        self.stress_round(self.c,copy.deepcopy(self.c.card))
        self.assertEqual(uploads[0],2)
        self.assertEqual(len(self.calls),5) # retained completed answer repairs the state without a paid call

    def test_cancellation_during_backoff(self):
        event=self.c.role_cancel
        self.patch(event,'wait',lambda seconds: event.set())
        with self.assertRaisesRegex(budget.BudgetError,'cancelled'):
            ordinary_retry.backoff(self.c)

    def test_v1_freshness_state_migrates_and_rejects_missing_statement(self):
        self.searches()
        self.patch(retrieval,'fetch',lambda url,**kw:({'url':url,'final_url':url,'status':200},HTTP['body'].encode()))
        path=self.work/'freshness-repair.json'
        atomic_json(path,{'version':1,'attempts':1,
                         'statement_sha256':hashlib.sha256((self.case/'statement.md').read_bytes()).hexdigest()})
        self.assertTrue(run.g2(self.c)[0])
        self.assertEqual(run.jload(path)['version'],2)
        self.assertEqual(run.jload(path)['completed_defects'],1)
        atomic_json(path,{'version':1,'attempts':1})
        with self.assertRaisesRegex(budget.BudgetError,'freshness_repair_state_invalid'): run.g2(self.c)

    def test_rebinding_restarts_real_category_coverage_without_new_writer(self):
        killed=[False]
        seen=[]
        def emit(config,value):
            seen.append(config['category'])
            if config['category']=='fairness' and not killed[0]:
                killed[0]=True
                raise runtime_fixture.Killed()
        self.stress_setup(emit)
        with self.assertRaises(runtime_fixture.Killed): self.stress_round(self.c,{})
        old=run.jload(self.work/'attack-state.json')
        binding=run.attack_binding(self.c)
        self.patch(run,'attack_binding',return_value={**binding,'prompt':'f'*64})
        self.fresh_context()
        self.stress_round(self.c,copy.deepcopy(self.c.card))
        self.assertEqual(seen[3:],list(stress_progress.CATEGORIES))
        self.assertNotEqual(old['operation_id'],run.jload(self.work/'attack-state.json')['operation_id'])
        self.assertEqual([name for name,_,_ in self.calls].count('builder-1'),1)

    def test_snapshot_and_case_context_changes_require_new_judgments(self):
        held, live, cycles, requests=self.held_http()
        flagged=[r for r in run.freshness_lines(self.c) if r['hit']]
        run.confirm_hits(self.c,flagged)
        self.assertEqual(len(self.calls),1)
        original=retrieval.fetch
        def changed(url,**kwargs):
            response,body=original(url,**kwargs)
            return response, body+b' authored changed snapshot' if 'id_/' in url else body
        self.patch(retrieval,'fetch',changed)
        self.c.freshness_refetch_urls={held}
        run.confirm_hits(self.c,flagged)
        self.assertEqual(len(self.calls),2)
        (self.case/'statement.md').write_text((self.case/'statement.md').read_text()+'\nAuthored context change.\n')
        run.confirm_hits(self.c,flagged)
        self.assertEqual(len(self.calls),3)


    def test_five_stress_interruptions_keep_same_round_and_operation(self):
        attempts=[0]
        def emit(config,value):
            if config['category']=='wrong_fixes' and attempts[0]<5:
                attempts[0]+=1
                raise runtime_fixture.Killed()
        self.stress_setup(emit)
        operation=None
        for _ in range(5):
            with self.assertRaises(runtime_fixture.Killed): self.stress_round(self.c,copy.deepcopy(self.c.card))
            receipt=run.jload(self.work/'attack-state.json')
            if operation is None: operation=receipt['operation_id']
            self.assertEqual(receipt['operation_id'],operation)
            self.fresh_context()
        self.stress_round(self.c,copy.deepcopy(self.c.card))
        self.assertEqual(self.c.card['builder_rounds'],1)
        self.assertEqual(run.jload(self.work/'attack-state.json')['operation_id'],operation)

    def test_new_production_context_installs_publication_barrier(self):
        fresh=run.Ctx()
        vars(fresh).update(copy.deepcopy(self.context_inputs))
        fresh.card=copy.deepcopy(self.c.card)
        fresh.role_cancel=threading.Event()
        calls=[]
        fresh.stress_checkpoint=lambda: calls.append('published') or True
        atomic_json(self.work/'stress-publication.json',{'pending':True,'identity':'authored-crash'})
        run.install_publication_barrier(fresh)
        fresh.model_publication_barrier()
        self.assertEqual(calls,['published'])
        self.assertFalse(run.jload(self.work/'stress-publication.json')['pending'])


if __name__ == '__main__': unittest.main()
