"""2026-11-10: open attack findings reach G8/G9 and the scorecard; the seal audit flags a replayed cheat.

Both are non-blocking and only for cases admitted with the new-case settings."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory'), str(ROOT / 'tests/bench')]
import json
import tempfile
import types
import unittest
from unittest.mock import patch

import attack_audit
import run
import sealed_audit
from durable.steps import admit

CHEAT = 'Guard keyed-on-seed passes: it refuses only the seeded customer IDs.'
JUDGE = 'S2 judge reads a column the promise never mentions.'


def report(blocking, cheats=(), **more):
    return {'complete': True, 'blocking': list(blocking), 'unfinished_validation': [], 'non_blocking': [],
            'freshness_review': [], 'cheats_tried': list(cheats), **more}


class Harness(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        case = root / 'case'
        (case / 'scenarios/S1').mkdir(parents=True)
        for name in ('case.json', 'answer-key.json', 'scenarios/S1/key.json'):
            (case / name).write_text('{}')
        (root / 'attacks').mkdir()
        self.c = types.SimpleNamespace(work=root, case=case, case_id='synthetic', card={}, seed=7,
            manifest0='synthetic bench revision', models={'builder': ['writer'], 'attacker': ['tester']},
            engine=types.SimpleNamespace(source_binding={}), stopped=False,
            args=types.SimpleNamespace(dry_run=False, source='hunt', rounds=3, runs=1, scenario_runs=1,
                                       seal_audit=True, attack_open_findings=True))

    def write(self, name, value):
        (self.root / 'attacks' / name).write_text(json.dumps(value))


class OpenFindings(Harness):
    def test_findings_no_kept_cheat_replays_are_open(self):
        self.write('round-1.json', report(['old finding']))
        self.write('round-2.json', report([CHEAT, JUDGE, 'review incomplete'],
                                          [{'name': 'keyed-on-seed', 'passed': True}, {'name': 'other', 'passed': False}]))
        (self.c.case / 'guards/cheats/keyed-on-seed').mkdir(parents=True)
        found = attack_audit.open_findings(self.root, self.c.case)
        self.assertEqual(found, {'round': 2, 'findings': 2, 'replayed': 1, 'open': 1, 'open_findings': [JUDGE]})

    def test_a_cheat_the_writer_did_not_keep_stays_open(self):
        self.write('round-1.json', report([CHEAT], [{'name': 'keyed-on-seed', 'passed': True}]))
        self.assertEqual(attack_audit.open_findings(self.root, self.c.case)['open_findings'], [CHEAT])

    def test_the_freshness_cleared_copy_wins_and_audit_reports_are_not_attacks(self):
        self.write('round-1.json', report([CHEAT, '[freshness-review] independent verdict required']))
        self.write('round-1-writer.json', report([CHEAT]))
        self.write('audit-3.json', report(['an audit finding']))
        self.assertEqual(attack_audit.open_findings(self.root, self.c.case)['open_findings'], [CHEAT])

    def test_no_attack_and_a_clean_last_attack(self):
        self.assertIsNone(attack_audit.open_findings(self.root, self.c.case))
        self.write('round-1.json', report([CHEAT]))
        self.write('round-2.json', report([]))
        self.assertEqual(attack_audit.open_findings(self.root, self.c.case)['open'], 0)
        self.assertEqual(attack_audit.review_note(attack_audit.open_findings(self.root, self.c.case)), '')

    def test_the_panel_sees_open_findings_and_its_retained_answer_is_keyed_on_them(self):
        self.write('round-1.json', report([JUDGE]))
        self.c.open_attack_findings = attack_audit.open_findings(self.root, self.c.case)
        self.c.models['reviewers'] = [['reviewer-a']]
        seen = {}
        def answer(c, chain, text, cwd, name, out, identity, *rest):
            seen.update(text=text, identity=identity)
            return {'fairness': {'approve': True, 'findings': []}, 'realism': {'approve': True, 'findings': []}}
        with patch.object(run, 'retained_answer', answer), patch.object(run, 'prompt', lambda role, ctx: ctx), \
                patch.object(run, 'run_context', lambda c, **kw: 'context'):
            run.review(self.c)
        self.assertIn('Open attack findings', seen['text'])
        self.assertIn(JUDGE, seen['text'])
        self.assertIn('a finding alone is not a reason to reject', seen['text'])
        self.assertEqual(seen['identity']['open_attack_findings'], [JUDGE])
        # Nothing open: the request and its retained-answer identity are as before.
        self.c.open_attack_findings = {'open_findings': []}
        self.c.__dict__.pop('votes', None)
        with patch.object(run, 'retained_answer', answer), patch.object(run, 'prompt', lambda role, ctx: ctx), \
                patch.object(run, 'run_context', lambda c, **kw: 'context'):
            run.review(self.c)
        self.assertNotIn('open_attack_findings', seen['identity'])
        self.assertNotIn('Open attack findings', seen['text'])

    def test_gates_record_the_count_and_ask_for_the_audit_only_when_enabled(self):
        self.write('round-1.json', report([JUDGE, CHEAT]))
        def gates(c):
            c.card['gates'] = {g: 'pass' for g in run.GATES}
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                self.c.card = {}
                self.c.args.seal_audit = self.c.args.attack_open_findings = enabled
                with patch.object(run, 'validate_and_repair', gates), patch.object(run, 'ensure_freshness'), \
                        patch.object(run, 'g1', return_value=(True, {'problems': []})):
                    result = run.engine_gates(self.c)
                self.assertEqual(result['reason'], 'engine:gates_passed_audit' if enabled else 'engine:gates_passed')
                if enabled:
                    self.assertEqual(self.c.card['attack_open_findings'],
                                     {'round': 1, 'findings': 2, 'replayed': 0, 'open': 2})
                    self.assertIn(b'attack_open_findings', result['receipt'])
                    self.assertIn('open attack findings: 2 of 2', run.scorecard_text(
                        {**self.c.card, 'dry_run': False, 'case': 'x', 'source': 's'}))
                else:
                    self.assertNotIn('attack_open_findings', self.c.card)
                    self.assertNotIn(b'attack_open_findings', result['receipt'])


class SealAudit(Harness):
    def setUp(self):
        super().setUp()
        self.c.card['gates'] = {g: 'pass' for g in run.GATES}
        for name in ('engine_prepare_bench', 'case_budget_boundary'):
            mocked = patch.object(run, name); mocked.start(); self.addCleanup(mocked.stop)

    def audit(self, result, *, replay_passes=(), guards=()):
        for name in guards:
            g = self.root / 'attacks' / 'round-audit-3' / name
            g.mkdir(parents=True); (g / 'db.sql').write_text('-- guard')
        calls = []
        def categories(c, label, path, receipt, completed):
            self.assertEqual(label, 'audit-3')
            path.write_text(json.dumps(result)); completed()
        def cheat_runs(c, seed, tag, *, guards, runs, deadline, failures):
            calls.append(guards[0].name)
            if guards[0].name in replay_passes: failures.append(str(guards[0]))
            return len(failures), 1
        with patch.object(run, 'stress_categories', categories), patch.object(run, 'cheat_runs', cheat_runs):
            out = run.engine_stress_round(self.c, 3)
        return out, calls

    def test_a_replayed_cheat_flags_the_case_without_touching_gates(self):
        out, calls = self.audit(report([CHEAT], [{'name': 'keyed-on-seed', 'passed': True},
                                                 {'name': 'claimed-only', 'passed': True}]),
                                replay_passes=('keyed-on-seed',), guards=('keyed-on-seed',))
        self.assertEqual(out['reason'], 'stress:audit_cheat')
        self.assertNotIn('feedback', out)
        self.assertEqual(calls, ['keyed-on-seed'])
        self.assertEqual(self.c.card['seal_audit'], {'round': 'audit-3', 'complete': True, 'findings': 1,
            'cheats_claimed': 2, 'cheats_confirmed': 1, 'freshness_requests': 0, 'cheat': True, 'result': 'cheat'})
        self.assertTrue(all(v == 'pass' for v in self.c.card['gates'].values()))
        self.assertIn('OUT OF THE EXAM', run.scorecard_text({**self.c.card, 'dry_run': False, 'case': 'x', 'source': 's'}))

    def test_a_claimed_cheat_that_does_not_replay_is_only_a_finding(self):
        out, _ = self.audit(report([CHEAT], [{'name': 'keyed-on-seed', 'passed': True}]), guards=('keyed-on-seed',))
        self.assertEqual(out['reason'], 'stress:audit_findings')
        self.assertFalse(self.c.card['seal_audit']['cheat'])

    def test_clean_audit_and_freshness_requests_are_counted_not_resolved(self):
        with patch.object(run, 'loop_freshness') as loop:
            out, _ = self.audit(report([], freshness_review=['https://example.invalid/issue']))
        loop.assert_not_called()
        self.assertEqual(out['reason'], 'stress:audit_clean')
        self.assertEqual(self.c.card['seal_audit']['freshness_requests'], 1)

    def test_an_unfinished_audit_with_no_findings_is_infra(self):
        out, _ = self.audit({**report([]), 'complete': False})
        self.assertEqual(out['reason'], 'stress:interrupted_review')
        self.assertNotIn('seal_audit', self.c.card)

    def test_only_a_gated_case_with_the_setting_is_audited(self):
        for change in ({'failed_gate': 'G5'}, {'gates': {}}, {'recertify': {'case': 'x'}}):
            with self.subTest(change=change):
                self.assertFalse(run.seal_audit_due(types.SimpleNamespace(**{**self.c.__dict__, 'card': {**self.c.card, **change}})))
        self.assertTrue(run.seal_audit_due(self.c))
        self.c.args.seal_audit = False
        self.assertFalse(run.seal_audit_due(self.c))


class Exam(unittest.TestCase):
    def test_a_flagged_or_malformed_audit_keeps_the_case_out(self):
        for audit in ({'cheat': True}, {}, {'cheat': 'no'}):
            with self.subTest(audit=audit), patch.object(sealed_audit, 'verify_source'):
                with self.assertRaisesRegex(ValueError, 'seal audit'):
                    sealed_audit.verify_exam_metadata({'seal_audit': audit, 'gates': {}}, 'x')

    def test_a_clean_or_absent_audit_passes_on_to_the_other_checks(self):
        for card in ({'seal_audit': {'cheat': False}, 'gates': {}}, {'gates': {}}):
            with self.subTest(card=card), patch.object(sealed_audit, 'verify_source'):
                with self.assertRaisesRegex(ValueError, 'fairness checks'):
                    sealed_audit.verify_exam_metadata(card, 'x')


class Settings(unittest.TestCase):
    def test_new_cases_only(self):
        self.assertIn('attack_open_findings', run.ENGINE_SETTINGS)
        self.assertIn('seal_audit', run.ENGINE_SETTINGS)
        args = run.argument_parser().parse_args([])
        self.assertFalse(args.seal_audit or args.attack_open_findings)
        card = admit._card({'seed': 7, 'source': 'port'}, 'case-new', False)
        self.assertTrue(card['recovery_config']['seal_audit'] and card['recovery_config']['attack_open_findings'])
        old = admit._card({'seed': 7, 'source': 'port', 'recertify': True}, 'case-old', False)
        self.assertNotIn('recovery_config', old)


if __name__ == '__main__':
    unittest.main()
