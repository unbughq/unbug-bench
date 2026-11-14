"""Restore regressions; synthetic plaintext plus read-only collected public artifacts."""
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import run
import model_runtime
import model_router
from router_test_support import offline_router
_ROUTING = offline_router()
from test_admission import ENGINE, evidence


class FreshnessRestoreTests(unittest.TestCase):
    def setUp(self):
        from freshness_test_transport import start
        start(self)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        work = pathlib.Path(tmp.name); case = work / 'case'; case.mkdir()
        self.c = types.SimpleNamespace(work=work, case=case, case_id='case-test', card={}, batch_deadline='2999-01-01T00:00:00Z',
            args=types.SimpleNamespace(resume='case-test', dry_run=False, agent_timeout=14400,
                                       source='hunt', runs=1, scenario_runs=1),
            models={'builder': ['claude/writer'], 'attacker': ['deepseek/tester'],
                    'reviewers': [['minimax/reviewer']]})
        (case / 'statement.md').write_text('Unchanged bug in 2.19.0')
        (case / 'case.json').write_text(json.dumps({'app': {
            'commit': '87d77fa1b5' + '0' * 30, 'version': '2.19.0 (tag v2.19.0; pinned commit)'}}))
        self.rows = [evidence('builder', kind, i) for kind in ('web', 'github') for i in range(3)]
        self.rows += [evidence('attacker', 'web', i) for i in range(2)]
        self.save()
        self.url = 'https://github.com/medusajs/medusa/pull/17431'
        self.result = {'complete': True, 'blocking': ['[freshness-review] independent verdict required'],
                       'freshness_review': [self.url]}
        self.report = work / 'report.json'; self.report.write_text(json.dumps(self.result))

    def save(self):
        (self.c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, self.rows)))

    def answer(self, version='2.19.0'):
        return {'url': self.url, 'resolved': True, 'same_bug': False, 'retrieved': True,
                'app_version': version, 'version_scope': 'Checked pinned version', 'why': 'Different bug'}

    def reviewer(self, c, models, text, cwd, name, **kwargs):
        self.assertEqual(name, 'reviewer-g2-confirm')
        (pathlib.Path(cwd) / 'verdict.json').write_text(json.dumps({'hits': [self.answer()]}))
        return 0

    def test_requested_url_uses_leading_semver_with_commit_sha(self):
        self.addCleanup(offline_router()[0].close)
        with patch.object(run, 'opencode', self.reviewer):
            result, _ = run.loop_freshness(self.c, self.result, self.report)
        self.assertEqual(result['blocking'], [])
        self.assertEqual(self.c.card['loop_freshness']['outcome'], 'excluded')

    def test_canary_shape_flagged_search_and_requested_PR_both_excluded(self):
        self.addCleanup(offline_router()[0].close)
        search = 'https://github.com/search?q=repo%3Amedusajs%2Fmedusa+reservation&type=issues'
        self.rows.append(evidence('attacker', 'github', 99, url=search, ambiguous=True))
        self.save()
        def reviewer(c, models, text, cwd, name, **kwargs):
            answers = [{**self.answer(), 'url': url} for url in (search, self.url)]
            (pathlib.Path(cwd) / 'verdict.json').write_text(json.dumps({'hits': answers}))
            return 0
        with patch.object(run, 'opencode', side_effect=reviewer) as call:
            run.loop_freshness(self.c, self.result, self.report)
        call.assert_called_once()
        info = self.c.card['loop_freshness']
        self.assertEqual((info['rows'], info['requested'], info['outcome']), (2, 1, 'excluded'))

    def test_pinned_version_supports_prerelease_and_build_metadata(self):
        self.addCleanup(offline_router()[0].close)
        version = '2.19.0-rc.1+build.42'
        (self.c.case / 'case.json').write_text(json.dumps({'app': {
            'commit': '87d77fa1b5', 'version': version + ' (pinned commit)'}}))
        def reviewer(c, models, text, cwd, name, **kwargs):
            (pathlib.Path(cwd) / 'verdict.json').write_text(json.dumps({'hits': [self.answer(version)]}))
            return 0
        with patch.object(run, 'opencode', side_effect=reviewer):
            run.loop_freshness(self.c, self.result, self.report)
        self.assertEqual(self.c.card['loop_freshness']['outcome'], 'excluded')

    def test_provider_fallback_preserves_expiry_deadline(self):
        self.addCleanup(offline_router()[0].close)
        now = [1000]
        runtime = model_runtime.ModelRuntime(self.c.work, None, None, None, None)
        durations = []
        def invoke(c, models, text, cwd, name, **kwargs):
            durations.append(kwargs['timeout'])
            now[0] += kwargs['timeout'] - (10 if len(durations) == 1 else 0)
            if len(durations) == 1: raise run.BudgetError('provider_limit')
            return 0
        model = "opencode/glm-5.3-flash-free"
        with patch.object(model_runtime.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=invoke):
            self.assertEqual(runtime.call(self.c, [model], '', self.c.case,
                'builder-freshness', timeout=1200, deadline=2200), 0)
        self.assertEqual(durations, [1200, 10])
        self.assertEqual(now[0], 2200)

    def test_expired_deadline_prevents_provider_fallback(self):
        self.addCleanup(offline_router()[0].close)
        now = [1000]
        runtime = model_runtime.ModelRuntime(self.c.work, None, None, None, None)
        def fail(*args, **kwargs):
            now[0] = 2200
            raise run.BudgetError('provider_limit')
        with patch.object(model_runtime.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(model_runtime.ModelRuntime, '_invoke', side_effect=fail) as call, \
             self.assertRaisesRegex(run.BudgetError, '^provider_wait$'):
            runtime.call(self.c, ["opencode/glm-5.3-flash-free"], '', self.c.case,
                         'builder-freshness', timeout=1200, deadline=2200)
        call.assert_called_once()

    def test_unknown_version_stops_before_review(self):
        self.addCleanup(offline_router()[0].close)
        (self.c.case / 'case.json').write_text(json.dumps({'app': {'commit': '87d77fa1b5'}}))
        # A SHA pin may take its release from the search rows, but only when they record one.
        for row in self.rows: row['app_version'] = ''
        self.save()
        with patch.object(run, 'opencode') as call, self.assertRaisesRegex(run.BudgetError, '^freshness_unresolved$'):
            run.loop_freshness(self.c, self.result, self.report)
        call.assert_not_called()
        self.assertEqual(self.c.card['loop_freshness']['reason'], 'pinned_version_unknown')

    def retain_verdict(self, answer):
        path = self.c.work / 'g2-confirm-1792916679897600904'
        path.mkdir(); shutil.copytree(self.c.case, path / 'case')
        (path / 'verdict.json').write_text(json.dumps({'hits': [answer]}))
        (self.c.work / 'scorecard.json').write_text(json.dumps({'terminal_stop': 'freshness_unresolved',
            'loop_freshness': {'outcome': 'unresolved', 'verdict_path': path.name + '/verdict.json'}}))

    def test_restore_rechecks_retained_verdict_with_correct_version(self):
        self.addCleanup(offline_router()[0].close)
        self.retain_verdict(self.answer())
        from admission import search_binding
        directory = self.c.work / 'g2-confirm-1792916679897600904'
        (directory / 'review-completed.json').write_text(json.dumps({'binding': {
            **search_binding(self.c, [{'who': 'attacker', 'url': self.url, 'app_version': '2.19.0',
                'query': 'Attacker freshness_review request',
                'note': 'Attacker requested an independent same_bug/version_scope verdict.\n'}]),
            'confirmation_contract': 2}}))
        import freshness_retrieval
        receipts = freshness_retrieval.retrieve([{'url':self.url}], directory / 'retrieval')
        marker = json.loads((directory / 'review-completed.json').read_text())
        marker['retrieval_sha256'] = freshness_retrieval.digest(receipts)
        (directory / 'review-completed.json').write_text(json.dumps(marker))
        with patch.object(run, 'opencode') as call:
            run.loop_freshness(self.c, self.result, self.report)
        call.assert_not_called()
        self.assertEqual(self.c.card['loop_freshness']['outcome'], 'excluded')

    def diagnosis_republish(self):
        from registry import atomic_json
        # Durable restoration carries the authenticated card as snapshot bytes;
        # no legacy dispatcher projects scheduler state onto a new card.
        self.c.card = json.loads((self.c.work / 'scorecard.json').read_text())
        atomic_json(self.c.work / 'scorecard.json', self.c.card)

    def completed_review_checkpoint(self, *, public_match=False):
        from registry import atomic_json
        answer = {**self.answer(), 'same_bug': public_match}
        def reviewer(c, models, text, cwd, name, **kwargs):
            (pathlib.Path(cwd) / 'verdict.json').write_text(json.dumps({'hits': [answer]}))
            return 0
        with patch.object(run, 'opencode', side_effect=reviewer) as call:
            if public_match:
                with self.assertRaisesRegex(run.BudgetError, '^freshness_public_match$'):
                    run.loop_freshness(self.c, self.result, self.report)
            else:
                run.loop_freshness(self.c, self.result, self.report)
        call.assert_called_once()
        atomic_json(self.c.work / 'scorecard.json', self.c.card)
        directory = (self.c.work / self.c.card['loop_freshness']['verdict_path']).parent
        self.assertTrue((directory / 'review-completed.json').is_file())
        self.assertTrue((directory / 'retrieval').is_dir())
        # Model a restore missing only the binding receipt, retaining completed
        # answer, current mtime, snapshot and independently retrieved HTTP bytes.
        (self.c.work / 'freshness-verdict.json').unlink()
        return directory

    def test_diagnosis_republish_recovers_completed_freshness_without_reroll(self):
        before = self.report.read_bytes()
        self.completed_review_checkpoint()
        self.diagnosis_republish()
        with patch.object(run, 'opencode', side_effect=AssertionError('duplicate review')) as call:
            result, _ = run.loop_freshness(self.c, self.result, self.report)
        call.assert_not_called()
        self.assertEqual(result['blocking'], [])
        self.assertEqual(self.report.read_bytes(), before)
        self.assertTrue((self.c.work / 'freshness-verdict.json').is_file())

    def test_diagnosis_republish_cannot_reuse_without_completion_marker(self):
        directory = self.completed_review_checkpoint()
        (directory / 'review-completed.json').unlink()
        self.diagnosis_republish()
        with patch.object(run, 'opencode', side_effect=self.reviewer) as call:
            run.loop_freshness(self.c, self.result, self.report)
        call.assert_called_once()

    def test_diagnosis_republish_preserves_public_match_failure(self):
        self.completed_review_checkpoint(public_match=True)
        self.diagnosis_republish()
        with patch.object(run, 'opencode', side_effect=AssertionError('duplicate review')) as call:
            with self.assertRaisesRegex(run.BudgetError, '^freshness_public_match$'):
                run.loop_freshness(self.c, self.result, self.report)
        call.assert_not_called()
        self.assertEqual(self.c.card['gates']['G2'], 'fail')
        self.assertEqual(self.c.card['loop_freshness']['outcome'], 'public_match')

    def test_restore_reasks_invalid_retained_version_or_changed_case(self):
        self.addCleanup(offline_router()[0].close)
        self.retain_verdict(self.answer('9.9.9'))
        with patch.object(run, 'opencode', side_effect=self.reviewer) as call:
            run.loop_freshness(self.c, self.result, self.report)
        call.assert_called_once()
        (self.c.work / 'freshness-verdict.json').unlink(missing_ok=True)
        (self.c.case / 'statement.md').write_text('Changed bug')
        with patch.object(run, 'opencode', side_effect=self.reviewer) as call:
            run.loop_freshness(self.c, self.result, self.report)
        call.assert_called_once()

    def test_stale_retained_verdict_requires_a_new_review(self):
        self.addCleanup(offline_router()[0].close)
        self.retain_verdict(self.answer())
        path = self.c.work / 'g2-confirm-1792916679897600904/verdict.json'
        os.utime(path, (1, 1))
        with patch.object(run, 'opencode', side_effect=self.reviewer) as call:
            run.loop_freshness(self.c, self.result, self.report)
        call.assert_called_once()

    def expire(self, count=26, attempts=2):
        at = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=25)).isoformat()
        self.rows = [{**self.rows[i % 8], 'query': f'Expired search {i}', 'at': at} for i in range(count)]
        self.save()
        state = {'version': 1, 'statement_sha256': hashlib.sha256((self.c.case / 'statement.md').read_bytes()).hexdigest(),
                 'attempts': attempts}
        (self.c.work / 'freshness-repair.json').write_text(json.dumps(state))
        return state

    def test_expiry_research_keeps_case_budget_boundary(self):
        self.c.engine = ENGINE()   # top-ups run under the engine's attempt deadline
        self.addCleanup(offline_router()[0].close)
        self.expire()
        with patch.object(run, 'case_budget_boundary', side_effect=run.BudgetError('budget_exhausted')), \
             patch.object(run, 'opencode') as call, self.assertRaisesRegex(run.BudgetError, 'budget_exhausted'):
            run.ensure_freshness(self.c)
        call.assert_not_called()


if __name__ == '__main__': unittest.main()
