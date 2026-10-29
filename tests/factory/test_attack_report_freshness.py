"""Offline regressions for the round-7 report shape; no live case or worker access."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import key_holder
import restart
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
    loop = loop_fixture.LoopFreshnessTests.loop

    def test_live_object_reaches_independent_reviewer_and_writer_gets_real_blocker(self):
        self.log_match = False
        self.requested_urls = [LIVE_ENTRY]
        self.report_blocking = self.extra = [BLOCKER]
        self.loop()
        self.assertEqual(self.calls, ['attacker-1', 'reviewer-g2-confirm', 'builder-2', 'attacker-2'])
        self.assertEqual([row['url'] for row in self.reviewed_rows], [URL])
        self.assertIn(NOTE, self.reviewed_rows[0]['note'])
        self.assertEqual(self.c.card['stress_review']['status'], 'completed')

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
        with self.assertRaisesRegex(run.BudgetError, '^stress_review_unresolved:interrupted_review$'):
            self.loop()
        self.assertEqual(self.calls, ['attacker-1', 'reviewer-g2-confirm'])

    def test_round_seven_restore_rereviews_changed_prompt_then_repairs_without_raise(self):
        self.c.args.rounds = 8
        self.extra = [BLOCKER]
        attacks = self.c.work / 'attacks'; attacks.mkdir()
        report = attacks / 'round-7.json'; report.write_text(json.dumps(live_report([LIVE_ENTRY])))
        binding = {**run.attack_binding(self.c), 'prompt': 'previous-prompt-contract'}
        receipt = self.c.work / 'attack-state.json'
        receipt.write_text(json.dumps({'round': 7, 'round_limit': 8, 'report': report.name,
                                       'binding': binding, 'rereviews': 1}))
        before = report.read_bytes()
        def model(c, models, text, cwd, name, **kwargs):
            if name == 'attacker-7':
                self.calls.append(name)
                self.assertEqual(json.loads(receipt.read_text())['rereviews'], 1)
                self.assertEqual(len(json.loads(receipt.read_text())['release_rereviews']), 1)
                report.write_text(json.dumps(live_report([LIVE_ENTRY])))
                return 0
            return self.model(c, models, text, cwd, name, **kwargs)
        previous = {'terminal_stop': 'stress_review_unresolved:missing_or_malformed_report',
                    'resume_rereview': {'round': 7, 'reason': 'binding_changed', 'binding_changed': ['prompt']}}
        with patch.object(run, 'opencode', model):
            run.write_and_attack(self.c, previous)
        self.assertEqual(self.calls, ['attacker-7', 'reviewer-g2-confirm', 'builder-8', 'attacker-8'])
        self.assertEqual(self.c.card['resume_rereview']['round'], 7)
        self.assertEqual(self.c.card['stress_review'], {'status': 'completed', 'round': 8})
        self.assertFalse(getattr(self.c, 'limits_raised', {}))
        self.assertEqual(report.read_bytes(), before)


class RoundSevenRestoreTests(unittest.TestCase):
    def test_rereview_stop_is_eligible_in_planner_and_holder_without_raise(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp); sealed = root / 'sealed'; sealed.mkdir()
            case = 'case-round-seven'
            archive = sealed / (case + '.checkpoint.tar.gz.age')
            archive.write_bytes(b'synthetic ciphertext, never decrypted')
            card = {'case': case, 'seed': 42, 'status': 'stopped', 'roles': {}, 'gates': {},
                    'terminal_stop': 'stress_review_unresolved:missing_or_malformed_report',
                    'stress_review': {'status': 'unresolved', 'reason': 'missing_or_malformed_report'},
                    'resume_rereview': {'round': 7, 'reason': 'binding_changed', 'binding_changed': ['prompt']},
                    'case_budget': {'limit_usd': 50}, 'recovery_config': {'rounds': 8, 'case_budget': 50},
                    'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                    'continuation_budget': {'cost': .1, 'list_cost_usd': 30, 'calls': 20,
                                            'events': [], 'terminal_stop': 'complete'}}
            path = sealed / (case + '.scorecard.json')
            job = {'case': case, 'mode': 'case', 'card': path.name, 'archive_prefix': case,
                   'roles': {}, 'max_calls': 1000, 'max_cost': 5, 'args': ['1', '--restore', case]}
            with patch.object(key_holder, 'ROOT', root):
                path.write_text(json.dumps(card))
                self.assertEqual(restart.raised_limits(card, 50, 8), {})
                self.assertEqual(restart.plan(path, 0, 7200, ''), (case, 60, 42))
                self.assertEqual(key_holder.current_generation(job), card['sha256'])
                for changes in ({'failed_gate': 'G2', 'gates': {'G2': 'fail'},
                                 'failed_detail': {'findings': ['real gate failure']}},
                                {'gates': {'G15': 'fail'}}, {'checkpoint_error': 'OSError'},
                                {'continuation_budget': {**card['continuation_budget'], 'list_cost_usd': 50}}):
                    with self.subTest(changes=changes):
                        path.write_text(json.dumps({**card, **changes}))
                        with self.assertRaises(ValueError): restart.plan(path, 0, 7200, '')
                        with self.assertRaises(ValueError): key_holder.current_generation(job)


if __name__ == '__main__':
    unittest.main()
