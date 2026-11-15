"""Fan-out freshness top-up with stubbed search backends and model calls: no network, keys or models."""
import datetime
import json
import sys
import tempfile
import threading
import time
import types
import io
import re
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'factory'), str(Path(__file__).parent)]
import admission
import freshness_fanout
import model_runtime
import run

NOW = lambda: datetime.datetime.now(datetime.timezone.utc)


class FanoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); case = root / 'case'; case.mkdir()
        (case / 'statement.md').write_text('bug'); (case / 'case.json').write_text(json.dumps({'app': {'version': '2.19.0 (x)'}}))
        self.c = types.SimpleNamespace(case=case, work=root, card={},
            # The engine's attempt deadline bounds freshness work, as in production.
            engine=types.SimpleNamespace(deadline_monotonic=time.monotonic() + 3600), models={'builder': ['claude/x'], 'attacker': ['opencode-go/y']},
            args=types.SimpleNamespace(source='port', runs=1, scenario_runs=1, agent_timeout=1200, freshness_fanout=True))
        self.calls, self.searches, self.prompts = [], [], {}
        self.lock = threading.Lock()
        self.scores = lambda listing: {}
        self.dive = None
        self.cwds, self.during = {}, None
        self.per_query, self.rerun_finds_old = 2, True
        for target in (patch.object(run, 'opencode', self.model), patch.dict(freshness_fanout.SEARCH, {
                'web': lambda q: self.search('web', q), 'github': lambda q: self.search('github', q)})):
            target.start(); self.addCleanup(target.stop)

    def search(self, kind, query):
        with self.lock: self.searches.append((kind, query))
        slug = query.replace(' ', '-')
        found = [{'url': f'https://github.com/stub/{slug}/{n}',
                  'title': f'title {slug} {n}', 'snippet': 'body text of the result ' * 5} for n in range(self.per_query)]
        old = re.fullmatch(r'old \w+ \w+ (\d)', query)   # a re-run of an old row finds that row's URL again
        if old and self.rerun_finds_old: found.append({'url': f'https://github.com/o/r/issues/{old[1]}', 'title': 'old',
                                                       'snippet': 'body text of the result ' * 5})
        return found

    def model(self, c, models, text, cwd, name, **kw):
        self.calls.append(name); self.prompts[name] = text
        self.cwds[name] = cwd
        if self.during: self.during(name, cwd)
        who = name.split('-')[0]
        if name.endswith('-plan'):
            (cwd / f'{who}-freshness-plan.json').write_text(json.dumps(
                {k: [f'{who} {k} idea {i}' for i in range(6)] for k in ('web', 'github')}))
        elif name.endswith('-score'):
            listing = json.loads(text.split('```json\n')[1].split('\n```')[0])
            verdicts = {'results': [{'id': r['id'], 'verdict': self.scores(listing).get(r['id'], 'miss'), 'reason': 'ok'} for r in listing]}
            (cwd / f'{who}-freshness-scores.json').write_text(json.dumps(verdicts))
        elif name.endswith('-dive') and self.dive:
            leads = json.loads(text.split('```json\n')[1].split('\n```')[0])
            (cwd / f'{who}-freshness-dive.json').write_text(json.dumps({'leads': self.dive(leads)}))
        return 0

    def rows(self): return run.freshness_lines(self.c)

    def test_both_roles_plan_independently_and_log_g2_valid_rows(self):
        run.freshness_topup(self.c)
        self.assertEqual(sorted(self.calls), ['attacker-freshness-plan', 'attacker-freshness-score',
                                              'builder-freshness-plan', 'builder-freshness-score'])
        self.assertNotIn('builder-freshness', self.calls)   # no agentic browsing: nothing was unsure
        rows = self.rows()
        self.assertTrue(rows and all(admission.search_evidence_error(r) is None for r in rows))
        counts = run.freshness_counts(self.c)
        self.assertGreaterEqual(counts['builder_web'], 3); self.assertGreaterEqual(counts['builder_github'], 3)
        self.assertGreaterEqual(counts['attacker'], 2)
        # each role scored only the results of the queries from its own plan
        for who in ('builder', 'attacker'):
            listing = json.loads(self.prompts[f'{who}-freshness-score'].split('```json\n')[1].split('\n```')[0])
            self.assertTrue(listing and all(f'/{who}-' in r['url'] for r in listing))
            self.assertNotIn('idea', self.prompts[f'{who}-freshness-plan'].split('## This run')[0])
        self.assertEqual({r['who'] for r in rows}, {'builder', 'attacker'})
        self.assertFalse(list(self.c.case.glob('*-freshness-*.json')))

    def test_only_close_or_unsure_results_get_a_deep_dive(self):
        self.scores = lambda listing: {listing[0]['id']: 'close', listing[2]['id']: 'unsure'}
        seen = []
        def dive(leads):
            seen.extend(l['url'] for l in leads)
            return [{'id': leads[0]['id'], 'verdict': 'hit', 'note': 'same bug', 'version_scope': 'applies'}]  # second lead unanswered
        self.dive = dive
        run.freshness_topup(self.c, completed_roles=('attacker',))
        self.assertEqual(self.calls.count('builder-freshness-dive'), 1)
        self.assertEqual(len(seen), 2)   # the two flagged results only, not the ~dozens of misses
        rows = self.rows()
        self.assertEqual([r['url'] for r in rows if r.get('hit') is True], [seen[0]])
        self.assertEqual([r['url'] for r in rows if r.get('ambiguous') is True], [seen[1]])  # unanswered lead stays flagged
        self.assertTrue(all(admission.search_evidence_error(r) is None for r in rows))

    def test_a_deep_dive_can_clear_a_lead_it_read(self):
        self.scores = lambda listing: {listing[0]['id']: 'unsure'}
        self.dive = lambda leads: [{'id': leads[0]['id'], 'verdict': 'miss', 'note': 'other app', 'version_scope': 'no'}]
        run.freshness_topup(self.c, completed_roles=('attacker',))
        self.assertFalse(any(r.get('hit') or r.get('ambiguous') for r in self.rows()))

    def test_expired_rows_are_rerun_and_amended_in_place(self):
        old = (NOW() - datetime.timedelta(days=3)).isoformat()
        rows = [{'who': who, 'kind': kind, 'query': f'old {who} {kind} {i}', 'url': f'https://github.com/o/r/issues/{i}', 'at': old,
                 'hit': False, 'retrieved': True, 'note': 'n', 'app_version': '2.19.0', 'version_scope': 's'}
                for who in ('builder', 'attacker') for kind in ('web', 'github') for i in range(3)]
        (self.c.case / 'freshness.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        run.freshness_topup(self.c)
        self.assertEqual(sorted(self.calls), ['attacker-freshness-score', 'builder-freshness-score'])  # no plan: minimums met
        after = self.rows()
        self.assertTrue(all(r.get('_search_id') and r['at'] > old for r in after))   # kept identity, fresh timestamp
        self.assertEqual([r['query'] for r in after], [r['query'] for r in rows])   # identity and query retained
        self.assertTrue(all(admission.search_evidence_error(r) is None for r in after))

    def expired_rows(self):
        old = (NOW() - datetime.timedelta(days=3)).isoformat()
        rows = [{'who': who, 'kind': kind, 'query': f'old {who} {kind} {i}', 'url': f'https://github.com/o/r/issues/{i}', 'at': old,
                 'hit': False, 'retrieved': True, 'note': 'n', 'app_version': '2.19.0', 'version_scope': 's'}
                for who in ('builder', 'attacker') for kind in ('web', 'github') for i in range(3)]
        (self.c.case / 'freshness.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        return old

    def test_a_rerun_that_does_not_retrieve_the_rows_url_supersedes_it_with_a_new_row(self):
        # A row whose own URL a re-run never returns (case f46dac's bot-challenged search pages) is kept
        # unchanged as history; the re-run is logged as a new row of the same query, which replaces it.
        self.rerun_finds_old = False
        old = self.expired_rows()
        run.freshness_topup(self.c, completed_roles=('attacker',))
        rows = self.rows()
        mine = [(r, gone) for r, gone in zip(rows, admission.superseded(rows))
                if r['who'] == 'builder' and '/o/r/issues/' in r['url']]
        self.assertTrue(mine and all(r['at'] == old and r['note'] == 'n' for r, _ in mine))   # never claimed as retrieved
        self.assertTrue(all(gone for _, gone in mine))
        self.assertEqual(len(rows), 12 + 6)   # one re-run row per old builder query
        self.assertNotIn('builder-freshness', self.calls)   # nothing left for the agentic repair

    def test_an_unretrieved_search_page_row_is_rerun_and_superseded(self):
        # case f46dac: an unflagged html.duckduckgo.com row logged retrieved:false. Fan-out re-runs its
        # query; the new row's result page replaces it, with no paid agentic top-up.
        self.expired_rows()
        rows = run.freshness_lines(self.c)
        dead = {**rows[0], 'url': 'https://html.duckduckgo.com/html/?q=old+builder+web+0', 'retrieved': False}
        (self.c.case / 'freshness.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in [dead, *rows[1:]]))
        run.freshness_topup(self.c, completed_roles=('attacker',))
        self.assertIn(('web', dead['query']), self.searches)
        after = self.rows()
        self.assertTrue(any(r['url'] == dead['url'] and gone for r, gone in zip(after, admission.superseded(after))))
        self.assertNotIn('builder-freshness', self.calls)

    def test_an_amended_rows_note_counts_the_flagged_results(self):
        self.expired_rows()
        self.scores = lambda listing: {listing[0]['id']: 'unsure'}
        self.dive = lambda leads: []
        run.freshness_topup(self.c, completed_roles=('attacker',))
        notes = [r['note'] for r in self.rows() if r.get('_search_id') and r['who'] == 'builder' and r['query'] == 'old builder web 0']
        self.assertEqual(len(notes), 1)
        self.assertIn('1 flagged', notes[0]); self.assertNotIn('none flagged', notes[0])

    def test_every_flagged_result_is_logged_and_close_leads_are_read_first(self):
        self.per_query = 5
        # the fourth result of a query is the close one, after three unsure: all four are logged
        urls = []
        def scores(listing):
            urls.extend(r['url'] for r in listing if r['id'].startswith('0.'))
            return {r['id']: ('close' if r['id'].endswith('.3') else 'unsure')
                    for r in listing if r['id'].startswith('0.') and r['id'] != '0.4'}
        self.scores = scores
        seen = []
        self.dive = lambda leads: seen.extend(l['id'] for l in leads) or []
        run.freshness_topup(self.c, completed_roles=('attacker',))
        first = [r for r in self.rows() if r['url'] in urls and (r.get('hit') or r.get('ambiguous'))]
        self.assertEqual(len(first), 4)
        self.assertEqual(sum(r['hit'] for r in first), 1)
        self.assertEqual(seen[0], '0.3')

    def test_the_scorer_is_told_which_excerpts_were_cut_short(self):
        self.assertEqual(freshness_fanout.excerpt('a  b'), {'snippet': 'a b'})
        cut = freshness_fanout.excerpt('x' * (freshness_fanout.SNIPPET + 1))
        self.assertTrue(cut['truncated']); self.assertEqual(len(cut['snippet']), freshness_fanout.SNIPPET)
        long = lambda q: [{'url': 'https://github.com/x/y/1', 'title': 't', **cut}]
        with patch.dict(freshness_fanout.SEARCH, {'web': long, 'github': long}):
            run.freshness_topup(self.c, completed_roles=('attacker',))
        listing = json.loads(self.prompts['builder-freshness-score'].split('```json\n')[1].split('\n```')[0])
        self.assertTrue(all(r.get('truncated') is True for r in listing))
        self.assertIn('"truncated" was cut short', self.prompts['builder-freshness-score'])
        # The scorer called every cut excerpt a miss (the default): none is cleared unread; each goes to
        # the deep dive and, unanswered there, stays an unresolved lead for G2's review.
        self.assertIn('builder-freshness-dive', self.calls)
        cut_rows = [r for r in self.rows() if r['url'] == 'https://github.com/x/y/1']
        self.assertTrue(cut_rows and all(r.get('ambiguous') is True and r['hit'] is False for r in cut_rows))

    def test_failed_backend_falls_back_to_the_agentic_search(self):
        def down(q): raise OSError('rate limited')
        with patch.dict(freshness_fanout.SEARCH, {'web': down, 'github': down}):
            run.freshness_topup(self.c, completed_roles=('attacker',))
        self.assertEqual(self.calls, ['builder-freshness-plan', 'builder-freshness'])

    def test_scratch_json_never_touches_the_case_even_when_a_call_fails(self):
        def during(name, cwd):
            self.assertNotEqual(cwd, self.c.case)
            self.assertFalse(list(self.c.case.glob('*-freshness-*.json')))
            if name == 'builder-freshness-dive': raise run.BudgetError('timeout')
        self.during = during
        self.scores = lambda listing: {listing[0]['id']: 'close'}
        self.dive = lambda leads: []
        with self.assertRaises(run.BudgetError): run.freshness_topup(self.c, completed_roles=('attacker',))
        self.assertFalse(list(self.c.case.glob('*-freshness-*.json')))
        self.assertFalse(list((self.c.work / 'freshness').rglob('*.json')))   # scratch removed too

    def test_roles_see_only_their_own_private_directory(self):
        def during(name, cwd):
            who = name.split('-')[0]
            other = 'attacker' if who == 'builder' else 'builder'
            self.assertEqual(cwd.name, who)
            self.assertFalse(list(cwd.glob('freshness.jsonl')) or list(cwd.glob(f'{other}-*')))
            self.assertNotIn(str(self.c.case), self.prompts[name])
            self.assertTrue((cwd / 'statement.md').is_file())
        self.during = during
        run.freshness_topup(self.c)
        self.assertEqual(len(self.calls), 4)

    def test_the_two_roles_model_calls_overlap(self):
        gate = threading.Barrier(2, timeout=5)   # each plan call waits for the other role's: serial calls time out
        met = []
        self.during = lambda name, cwd: (gate.wait(), met.append(name)) if name.endswith('-plan') else None
        run.freshness_topup(self.c)
        self.assertEqual(len(met), 2)
        self.assertEqual(sorted(c for c in self.calls if c.endswith('-plan')), ['attacker-freshness-plan', 'builder-freshness-plan'])

    def test_incomplete_scoring_is_retried_then_left_to_the_agentic_search(self):
        orig = self.model
        def partial(c, models, text, cwd, name, **kw):
            if name.endswith('-score') or name.endswith('-score-retry'):
                self.calls.append(name)
                (cwd / 'builder-freshness-scores.json').write_text('{"results": []}')
                return 0
            return orig(c, models, text, cwd, name, **kw)
        with patch.object(run, 'opencode', partial):
            run.freshness_topup(self.c, completed_roles=('attacker',))
        self.assertEqual(self.calls[:3], ['builder-freshness-plan', 'builder-freshness-score', 'builder-freshness-score-retry'])
        self.assertFalse(self.rows() and any(r.get('ambiguous') for r in self.rows()))   # nothing defaulted to unsure rows

    def test_a_result_with_next_to_no_text_is_not_cleared_unread(self):
        thin = lambda kind, q: [{'url': 'https://github.com/x/y/1', 'title': 't', 'snippet': ''}]
        with patch.dict(freshness_fanout.SEARCH, {'web': lambda q: thin('web', q), 'github': lambda q: thin('github', q)}):
            self.dive = lambda leads: []
            run.freshness_topup(self.c, completed_roles=('attacker',))
        self.assertIn('builder-freshness-dive', self.calls)   # scorer said miss; the empty excerpt forced a look

    def test_exa_excerpt_drops_the_header_and_keeps_body_text(self):
        text = 'Title: A post\nURL: https://blog.example/p\nPublished: 2026-01-01\nbody about the bug ' + 'x' * 900
        reply = 'data: ' + json.dumps({'result': {'content': [{'text': text}]}})
        response = io.BytesIO(reply.encode()); response.__enter__ = lambda s=response: s; response.__exit__ = lambda *a: None
        with patch.object(freshness_fanout, 'urlopen', lambda *a, **k: response):
            hit = freshness_fanout.web_search('q')[0]
        self.assertTrue(hit['snippet'].startswith('body about the bug')); self.assertGreater(len(hit['snippet']), 500)

    def test_fanout_can_be_switched_off(self):
        self.c.args.freshness_fanout = False
        run.freshness_topup(self.c)
        self.assertEqual(self.calls, ['builder-freshness', 'attacker-freshness'])

    def test_fanout_names_keep_the_freshness_timeout_exemption(self):
        self.c.args.agent_timeout = 14400
        for name in ('attacker-freshness-plan', 'attacker-freshness-score', 'attacker-freshness-dive'):
            self.assertEqual(model_runtime.role_timeout(self.c, name, 9000), 9000)


if __name__ == '__main__':
    unittest.main()
