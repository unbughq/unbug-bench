"""Offline regressions for the round-7 report shape; no live case or worker access."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import run
import test_loop_freshness as loop_fixture


URL = 'https://docs.medusajs.com/api/admin/fulfillments/cancel-a-fulfillment'
NOTE = 'Cancellation may release reserved stock; pinned-version applicability needs review.'
BLOCKER = 'Wrong fix passes because every test customer shares one email domain'
LIVE_ENTRY = {'url': URL, 'verdict': 'ambiguous', 'note': NOTE}


def live_report(value):
    return {'complete': True, 'blocking': [BLOCKER],
            'non_blocking': [f'Inspection note {n}' for n in range(6)],
            'freshness_review': value,
            'cheats_tried': [{'name': 'cap-thirteen', 'idea': 'Hard-coded stock cap', 'passed': True}],
            'searches': 3}


class AttackReportFreshnessTests(unittest.TestCase):
    def setUp(self):
        from freshness_test_transport import start
        start(self)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = pathlib.Path(tmp.name) / 'report.json'

    def parse(self, value):
        self.path.write_text(json.dumps(value))
        return run.attack_report(self.path)

    def test_live_object_shape_retains_complete_report_and_every_finding(self):
        original = live_report([LIVE_ENTRY])
        result = self.parse(original)
        self.assertIsNotNone(result)
        self.assertEqual(result['freshness_review'], [URL])
        self.assertEqual(result['freshness_review_notes'], [{'url': URL, 'note': NOTE}])
        self.assertNotIn('freshness_review_malformed', result)
        for key in ('complete', 'blocking', 'non_blocking', 'cheats_tried', 'searches'):
            self.assertEqual(result[key], original[key])
        self.assertEqual(json.loads(self.path.read_text()), original)
        self.assertEqual(self.parse(result), result)  # derived writer reports retain notes

    def test_strings_and_objects_without_notes_normalize(self):
        result = self.parse(live_report(['  ' + URL + '  ', {'url': URL}]))
        self.assertIsNotNone(result)
        self.assertEqual(result['freshness_review'], [URL, URL])
        self.assertNotIn('freshness_review_malformed', result)

    def test_missing_url_is_recorded_and_cannot_clear_the_concern(self):
        invalid = {'verdict': 'ambiguous', 'note': 'Possible match with no URL'}
        result = self.parse(live_report([LIVE_ENTRY, invalid, ' ', {'url': 17}]))
        self.assertIsNotNone(result)
        self.assertEqual(result['freshness_review'], [URL])
        self.assertEqual(result['freshness_review_dropped'], [invalid, ' ', {'url': 17}])
        self.assertIs(result['freshness_review_malformed'], True)
        self.assertEqual(result['blocking'], [BLOCKER])
        self.assertEqual(self.parse(result), result)

    def test_whole_field_garbage_retains_report_and_marks_unresolved(self):
        for value in (None, 'garbage', {'url': URL}, 17, True, [{}]):
            with self.subTest(value=value):
                result = self.parse(live_report(value))
                self.assertIsNotNone(result)
                self.assertEqual(result['freshness_review'], [])
                self.assertIs(result['freshness_review_malformed'], True)
                self.assertEqual(result['freshness_review_dropped'], value if isinstance(value, list) else [value])
                self.assertEqual(result['blocking'], [BLOCKER])

    def test_optional_legacy_field_and_incomplete_review_stay_unchanged(self):
        legacy = {'complete': False, 'blocking': ['review incomplete']}
        self.assertEqual(self.parse(legacy), {**legacy, 'unfinished_validation': []})
        result = self.parse({**legacy, 'freshness_review': [LIVE_ENTRY]})
        self.assertIsNotNone(result)
        self.assertIs(result['complete'], False)
        self.assertEqual(result['blocking'], ['review incomplete'])
        for invalid in ({'complete': True}, {'complete': 'true', 'blocking': []},
                        {'complete': True, 'blocking': [None]}):
            self.assertIsNone(self.parse({**invalid, 'freshness_review': [LIVE_ENTRY]}))


class AttackReportFlowTests(unittest.TestCase):
    # Reuse the existing synthetic model/reviewer harness without inheriting its tests.
    setUp = loop_fixture.LoopFreshnessTests.setUp
    save_rows = loop_fixture.LoopFreshnessTests.save_rows
    model = loop_fixture.LoopFreshnessTests.model
    categories = loop_fixture.LoopFreshnessTests.categories
    loop = loop_fixture.LoopFreshnessTests.loop
    assert_feedback = loop_fixture.LoopFreshnessTests.assert_feedback

    def test_live_object_reaches_independent_reviewer_and_writer_feedback(self):
        self.log_match = False
        self.requested_urls = [LIVE_ENTRY]
        self.report_blocking = self.extra = [BLOCKER]
        self.loop()
        self.assertEqual(self.calls, ['attacker-1', 'reviewer-g2-confirm'])
        self.assertEqual([row['url'] for row in self.reviewed_rows], [URL])
        self.assertIn(NOTE, self.reviewed_rows[0]['note'])
        self.assert_feedback([BLOCKER])
        self.assertEqual(json.loads((self.c.work / 'attacks/round-1.json').read_text())['freshness_review'], [LIVE_ENTRY])
        self.assertEqual(self.c.card['stress_review']['status'], 'findings')

    def test_malformed_concern_still_reviews_usable_urls_then_stops(self):
        self.log_match = False
        self.requested_urls = [LIVE_ENTRY, {'note': 'Another possible match; URL missing'}]
        self.report_blocking = [BLOCKER]
        with self.assertRaisesRegex(run.BudgetError, '^freshness_unresolved$'):
            self.loop()
        self.assertEqual(self.calls, ['attacker-1', 'reviewer-g2-confirm'])
        self.assertEqual([row['url'] for row in self.reviewed_rows], [URL])
        self.assertEqual(run.attack_report(self.c.work / 'attacks/round-1.json')['blocking'], [BLOCKER])
        self.assertNotEqual(self.c.card.get('stress_review', {}).get('status'), 'completed')

    def test_object_note_reaches_reviewer_even_with_flagged_search_evidence(self):
        self.match = {**self.match, 'url': URL, 'note': 'Search evidence retained'}
        self.requested_urls = [LIVE_ENTRY]
        self.report_blocking = []
        self.loop()
        self.assertEqual([row['url'] for row in self.reviewed_rows], [URL])
        self.assertIn(NOTE, self.reviewed_rows[0]['note'])
        self.assertIn('Search evidence retained', self.reviewed_rows[0]['note'])

    def test_whole_field_garbage_still_reviews_flagged_search_evidence(self):
        self.rows.append(self.match); self.save_rows()
        path = self.c.work / 'report.json'; path.write_text(json.dumps(live_report('garbage')))
        result = run.attack_report(path)
        self.assertIsNotNone(result)
        with patch.object(run, 'opencode', self.model), self.assertRaisesRegex(run.BudgetError, '^freshness_unresolved$'):
            run.loop_freshness(self.c, result, path)
        self.assertEqual(self.calls, ['reviewer-g2-confirm'])
        self.assertEqual([row['url'] for row in self.reviewed_rows], [self.match['url']])
        self.assertEqual(result['blocking'], [BLOCKER])

    def test_whole_field_garbage_never_becomes_a_pass(self):
        path = self.c.work / 'report.json'
        path.write_text(json.dumps({**live_report('garbage'), 'blocking': []}))
        result = run.attack_report(path)
        self.assertIsNotNone(result)
        with patch.object(run, 'opencode') as model, self.assertRaisesRegex(run.BudgetError, '^freshness_unresolved$'):
            run.loop_freshness(self.c, result, path)
        model.assert_not_called()  # no URL can be independently inspected
        self.assertEqual(self.c.card['loop_freshness']['outcome'], 'unresolved')

    def test_incomplete_object_report_cannot_pass_after_exclusion(self):
        self.log_match = False
        self.requested_urls = [LIVE_ENTRY]
        self.report_blocking = []
        self.complete = False
        from durable.contract import Outcome
        self.assertEqual(self.loop(), {"outcome": Outcome.INFRA_ERROR,
                                       "reason": "stress:interrupted_review"})
        self.assertNotEqual(self.c.card.get('stress_review', {}).get('status'), 'completed')
        self.assertEqual(self.calls, ['attacker-1', 'reviewer-g2-confirm'])

if __name__ == '__main__':
    unittest.main()
