"""Founder 2026-11-20: a per-case, per-URL founder ruling settles one G2 row behind a source that blocks every
fetch. Real shapes: the flagged row, runner receipt and retained reviewer answer of the three held cases
(cae763-h5, 18681d-h5, 2a7b2a-h1), copied from their snapshots into fixtures/g2-blocked-source.json.
No network or model call; the end-to-end test drives run.g2 under the engine harness of test_stream_d_retries.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import gate_state
import run

HELD = {d['case']: d for d in json.loads((Path(__file__).with_name('fixtures') / 'g2-blocked-source.json').read_text())['cases']}
CAE763, D18681, A2A7B2 = 'case-import-cae763-h5-1', 'case-import-18681d-h5-1', 'case-import-2a7b2a-h1-1'
STATEMENT = b'authored statement: the real ones stay sealed in the snapshots\n'
AUTHORED = hashlib.sha256(STATEMENT).hexdigest()


def hand_check(held, reports):
    return {'gate': 'G2', 'kind': 'hand_checked', 'by': 'founder', 'at': '2026-11-20', 'case': held['case'],
            'statement_sha256': held['statement_sha256'], 'url': held['row']['url'],
            'ruling': 'A person opened the page; the factory takes the hand check as its content.',
            'hand_check': {'checked_at': '2026-11-20', 'checked_by': 'founder',
                           'page_says': 'authored page summary', 'reports_this_bug': reports}}


def shipped(case):
    found = [r for r in run.G2_SOURCE_RULINGS if r['case'] == case]
    assert len(found) == 1, case
    return found[0]


class RulingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.case = Path(directory.name)
        (self.case / 'statement.md').write_bytes(STATEMENT)

    def verdict(self, held, rulings, answer=None, receipt=None):
        """checked_freshness_verdict on one held row, with `rulings` re-keyed to the authored statement."""
        c = SimpleNamespace(case=self.case, card={}, freshness_confirmed_hits=0, freshness_transport_pending=False,
                            freshness_retrieval=[copy.deepcopy(receipt or held['receipt'])])
        rulings = tuple({**r, 'statement_sha256': AUTHORED} if r['statement_sha256'] == held['statement_sha256'] else r
                        for r in rulings)
        with patch.object(run, 'G2_SOURCE_RULINGS', rulings):
            blocked = run.checked_freshness_verdict(c, [held['row']], [copy.deepcopy(answer or held['answer'])])
        return c, blocked

    def test_each_held_row_stays_blocked_without_a_ruling(self):
        # Today's behaviour on the real rows: an access failure left unresolved holds G2 as transport.
        for case, held in HELD.items():
            c, blocked = self.verdict(held, ())
            self.assertEqual(blocked, [held['row']], case)
            self.assertTrue(c.freshness_transport_pending, case)
            self.assertNotIn('ruled_rows', c.card['freshness_confirmation'], case)
            self.assertEqual(set(c.freshness_review_summary), {'unreachable_hits', 'archived_hits', 'unreachable_rows'})

    def test_the_shipped_not_needed_rulings_clear_cae763_and_2a7b2a_and_are_on_the_card(self):
        for case in (CAE763, A2A7B2):
            held, ruling = HELD[case], shipped(case)
            self.assertEqual((ruling['kind'], ruling['url'], ruling['statement_sha256']),
                             ('not_needed', held['row']['url'], held['statement_sha256']))
            c, blocked = self.verdict(held, run.G2_SOURCE_RULINGS)
            self.assertEqual(blocked, [], case)
            self.assertFalse(c.freshness_transport_pending, case)
            self.assertEqual(c.freshness_confirmed_hits, 0)
            ruled = [{'row': 1, **ruling, 'statement_sha256': AUTHORED}]
            self.assertEqual(c.card['freshness_confirmation']['ruled_rows'], ruled, case)
            self.assertEqual(c.freshness_review_summary['ruled_rows'], ruled)

    def test_a_hand_check_settles_18681d_either_way(self):
        held = HELD[D18681]
        c, blocked = self.verdict(held, (hand_check(held, False),))
        self.assertEqual((blocked, c.freshness_confirmed_hits, c.freshness_transport_pending), ([], 0, False))
        self.assertEqual(c.card['freshness_confirmation']['ruled_rows'][0]['hand_check']['reports_this_bug'], False)
        c, blocked = self.verdict(held, (hand_check(held, True),))
        self.assertEqual((blocked, c.freshness_confirmed_hits, c.freshness_transport_pending), ([held['row']], 1, False))

    def test_every_shipped_ruling_is_valid_and_keyed_to_a_held_case(self):
        # A malformed entry would apply nothing at runtime and cost a held case a resume: fail here instead.
        for ruling in run.G2_SOURCE_RULINGS:
            held = [h for h in HELD.values() if (h['statement_sha256'], h['row']['url']) ==
                    (ruling['statement_sha256'], ruling['url'])]
            self.assertEqual(len(held), 1, ruling['case'])
            self.assertEqual(ruling['case'], held[0]['case'])
            c, blocked = self.verdict(held[0], (ruling,))
            self.assertEqual(c.card['freshness_confirmation']['ruled_rows'],
                             [{'row': 1, **ruling, 'statement_sha256': AUTHORED}], ruling['case'])

    def test_the_pre_release_check_names_each_ruling_ok_or_mismatch(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('check_g2_rulings', ROOT / 'tools/check-g2-rulings.py')
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        held = HELD[A2A7B2]
        url = held['row']['url']
        args = (STATEMENT, [held['row']], {url: held['receipt']}, {url: held['answer']})
        ruling = {**shipped(A2A7B2), 'statement_sha256': AUTHORED}
        moved = {**ruling, 'url': url + '/'}
        with patch.object(run, 'G2_SOURCE_RULINGS', (ruling, moved)):
            self.assertEqual(tool.check(*args), [(ruling, 'OK'), (moved, 'MISMATCH')])
        with patch.object(run, 'G2_SOURCE_RULINGS', (ruling,)):
            self.assertEqual(tool.check(*args[:3], {url: {**held['answer'], 'same_bug': True}}), [(ruling, 'MISMATCH')])
        self.assertEqual(tool.check(*args), [])   # no shipped ruling names the authored statement

    def test_a_ruling_settles_only_its_own_unread_row(self):
        held = HELD[CAE763]
        ruling = shipped(CAE763)
        for name, rulings, answer, receipt in (
                ('another statement', ({**ruling, 'statement_sha256': '0' * 64},), None, None),
                ('another url', ({**ruling, 'url': ruling['url'] + '?x'},), None, None),
                ('duplicate', (ruling, dict(ruling)), None, None),
                ('malformed kind', ({**ruling, 'kind': 'cleared'},), None, None),
                ('unknown field', ({**ruling, 'note': 'x'},), None, None),
                ('hand check without page text', ({**hand_check(held, False), 'hand_check': {
                    **hand_check(held, False)['hand_check'], 'page_says': ' '}},), None, None),
                ('not_needed with a hand_check key', ({**ruling, 'hand_check': None},), None, None),
                ('hand check with an extra key', ({**hand_check(held, False), 'hand_check': {
                    **hand_check(held, False)['hand_check'], 'url': 'x'}},), None, None),
                ('reviewer claims the match', (ruling,), {**held['answer'], 'same_bug': True}, None),
                ('page read live', (ruling,), None, {**held['receipt'], 'retrieved_from': 'live', 'live_failure': None}),
                ('dead page', (ruling,), None, {**held['receipt'], 'live_failure': 'http_404'})):
            c, blocked = self.verdict(held, rulings, answer, receipt)
            self.assertEqual(blocked, [held['row']], name)
            self.assertNotIn('ruled_rows', c.card['freshness_confirmation'], name)
        # A reviewer's confirmed match, even an invalid one, is never cleared; a valid one still counts.
        live = {**held['receipt'], 'retrieved_from': 'live', 'live_failure': None}
        answer = {**held['answer'], 'resolved': True, 'same_bug': True, 'retrieved': True, 'retrieved_from': 'live',
                  'archive_checked': False, 'archive_available': None, 'live_failure': None}
        c, blocked = self.verdict(held, (ruling,), answer, live)
        self.assertEqual((blocked, c.freshness_confirmed_hits), ([held['row']], 1))

    def test_the_card_shows_only_the_latest_verdicts_rulings(self):
        held = HELD[CAE763]
        c, _ = self.verdict(held, run.G2_SOURCE_RULINGS)
        self.assertIn('ruled_rows', c.card['freshness_confirmation'])
        c.freshness_retrieval = [copy.deepcopy(held['receipt'])]
        with patch.object(run, 'G2_SOURCE_RULINGS', ()):
            run.checked_freshness_verdict(c, [held['row']], [copy.deepcopy(held['answer'])])
        self.assertNotIn('ruled_rows', c.card['freshness_confirmation'])

    def test_the_mixed_receipt_lists_a_hand_checked_match_as_confirmed(self):
        import ordinary_freshness
        held = HELD[D18681]
        (self.case / 'verdict.json').write_text(json.dumps({'hits': [held['answer']]}))
        c = SimpleNamespace(case=self.case, work=self.case, freshness_verdict_path='verdict.json',
                            freshness_retrieval=[held['receipt']], freshness_review_summary={})
        fake = SimpleNamespace(freshness_lines=lambda c: [held['row']], jload=run.jload,
                               checked_freshness_verdict=run.checked_freshness_verdict,
                               CONFIRMATION_CONTRACT=run.CONFIRMATION_CONTRACT)
        for reports, confirmed in ((True, [1]), (False, [])):
            ruling = {**hand_check(held, reports), 'statement_sha256': AUTHORED}
            with patch.object(run, 'G2_SOURCE_RULINGS', (ruling,)), \
                    patch('admission.search_binding', lambda c, flagged: {}):
                ordinary_freshness.keep_mixed_receipt(fake, c)
            self.assertEqual(run.jload(self.case / 'freshness-verdict.json')['confirmed_rows'], confirmed, reports)

    def test_other_rows_of_the_same_verdict_are_judged_as_before(self):
        held = HELD[A2A7B2]
        other = {**held['row'], 'url': 'https://github.com/medusajs/medusa/issues/1'}
        other_receipt = {**held['receipt'], 'url': other['url']}
        other_answer = {**held['answer'], 'url': other['url']}
        c = SimpleNamespace(case=self.case, card={}, freshness_confirmed_hits=0, freshness_transport_pending=False,
                            freshness_retrieval=[copy.deepcopy(held['receipt']), other_receipt])
        with patch.object(run, 'G2_SOURCE_RULINGS', ({**shipped(A2A7B2), 'statement_sha256': AUTHORED},)):
            blocked = run.checked_freshness_verdict(c, [held['row'], other], [held['answer'], other_answer])
        self.assertEqual(blocked, [other])
        self.assertTrue(c.freshness_transport_pending)
        self.assertEqual([r['row'] for r in c.card['freshness_confirmation']['ruled_rows']], [1])

    def test_a_ruled_wall_never_stops_g2_while_another_row_is_held(self):
        # cae763's real WAF 202 receipt, ruled, next to another flagged row held on a 429: the hold waits on the
        # 429 (our own stall, STALLED_SECONDS), never stops as a bot wall after SOURCE_BLOCKED_CYCLES.
        import ordinary_freshness
        held = HELD[CAE763]
        other = {**held['receipt'], 'url': 'https://github.com/medusajs/medusa/issues/1', 'live_failure': 'http_429'}
        c = SimpleNamespace(work=self.case, card={}, freshness_retrieval=[held['receipt'], other],
                            freshness_review_summary={'ruled_rows': [{'row': 1, **shipped(CAE763)}]})
        fake = SimpleNamespace(freshness_lines=lambda c: [held['row']])
        for _ in range(ordinary_freshness.SOURCE_BLOCKED_CYCLES + 1):
            ordinary_freshness.stalled(fake, c, {'transport_pending': True})
        c.freshness_review_summary = {}
        with self.assertRaisesRegex(Exception, '^freshness_source_blocked$'):
            for _ in range(ordinary_freshness.SOURCE_BLOCKED_CYCLES):
                ordinary_freshness.stalled(fake, c, {'transport_pending': True})

    def test_only_g2_identity_reads_the_rulings(self):
        names = {'G2_SOURCE_RULINGS', 'g2_source_ruling', 'checked_freshness_verdict'}
        for gate in gate_state.STAGE_DEPENDENCIES:
            try: found = names & set(gate_state.runner_inputs(gate))
            except ValueError: found = set()
            self.assertEqual(found, names if gate == 'G2' else set(), gate)
        for roots in (('calibrate', 'make_pilots', 'calibration_identity'), ('attack_report', 'stress_request', 'g1')):
            self.assertFalse(names & set(gate_state.source_inputs(*roots)), roots)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        import test_stream_d_retries as retries
        self.fixture = retries.RetryTests('test_a_bot_walled_hit_with_no_archive_stops_g2_for_a_person')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_a_ruled_walled_hit_passes_g2_on_its_first_cycle(self):
        f = self.fixture
        held = HELD[CAE763]   # its real row: ambiguous builder/web, a WAF 202 with no archive copy
        url, cycles = f.bot_wall(99, status=202, url=held['row']['url'], hit=False, ambiguous=True)
        # An unread page is no search evidence (freshness_unfetched), so the held cases' minima stand without it
        # (cae763 counted 19 builder/web searches): one more builder/web row here.
        rows = [json.loads(line) for line in (f.case / 'freshness.jsonl').read_text().splitlines()]
        rows.append({**rows[1], 'query': 'builder web query 9', 'url': 'https://github.com/medusajs/medusa/issues/99'})
        (f.case / 'freshness.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        sha = hashlib.sha256((f.case / 'statement.md').read_bytes()).hexdigest()
        ruling = {**shipped(CAE763), 'statement_sha256': sha}
        f.cli(lambda c, text, name: f.answer_path(text).write_text(json.dumps({'hits': [held['answer']]})))   # its real answer
        with patch.object(run, 'G2_SOURCE_RULINGS', (ruling,)):
            ok, info = run.g2(f.c)
        self.assertTrue(ok)
        self.assertEqual(cycles[0], 0)
        self.assertEqual(info['outcome'], 'clear')
        self.assertEqual(info['ruled_rows'], [{'row': 1, **ruling}])
        self.assertEqual(f.c.card['freshness_confirmation']['ruled_rows'], [{'row': 1, **ruling}])
        self.assertNotIn('freshness_stalled', f.c.card)

    def test_18681d_a_ruled_unread_row_short_of_searches_buys_one_top_up_not_a_refetch_loop(self):
        # 18681d's real shape: its ruled row (ambiguous, searcher-unretrieved, 429) is unread, so G2 counts one
        # builder/web search short, and its saved repair state says the last top-up already ran on these rows.
        # The ruled row is no search evidence for the top-up guard either: one builder top-up, then G2 passes.
        import ordinary_freshness
        f = self.fixture
        held = HELD[D18681]
        url, cycles = f.bot_wall(99, status=429, url=held['row']['url'], hit=False, ambiguous=True, retrieved=False)
        statement = (f.case / 'statement.md').read_bytes()
        ruling = {**hand_check(held, False), 'statement_sha256': hashlib.sha256(statement).hexdigest()}
        (f.work / 'freshness-repair.json').write_text(json.dumps({
            'version': 2, 'statement_sha256': hashlib.sha256(statement).hexdigest(), 'completed_defects': 0,
            'pending': None, 'last_topup': ordinary_freshness.digest(run.freshness_lines(f.c))}))
        def emit(c, text, name, cwd=None):
            if name == 'builder-freshness':
                path = Path(cwd) / 'freshness.jsonl'
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                extra = {**rows[1], 'query': 'builder web query 9', 'url': 'https://github.com/medusajs/medusa/issues/99'}
                path.write_text(path.read_text() + json.dumps(extra) + '\n')
            else:
                f.answer_path(text).write_text(json.dumps({'hits': [{
                    'url': url, 'resolved': True, 'same_bug': False, 'retrieved': True, 'app_version': '2.19.0',
                    'version_scope': 'authored applicability', 'retrieved_from': 'live', 'archive_checked': False,
                    'archive_available': None, 'archive_snapshot_url': None, 'live_failure': None, 'why': 'authored review'}]}))
        f.cli(emit)
        with patch.object(run, 'G2_SOURCE_RULINGS', (ruling,)):
            ok, info = run.g2(f.c)
        self.assertTrue(ok)
        self.assertEqual([name for name, _, _ in f.calls if name.endswith('-freshness')], ['builder-freshness'])
        self.assertEqual(info['ruled_rows'], [{'row': 1, **ruling}])
        self.assertEqual(run.jload(f.work / 'freshness-repair.json')['completed_defects'], 0)
        self.assertNotIn('freshness_stalled', f.c.card)


if __name__ == '__main__':
    unittest.main()
