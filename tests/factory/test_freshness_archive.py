"""Attempt-8 G2 dead-link ruling; synthetic 17-row review, no network or models."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import run
import test_admission as fixtures
from test_admission import evidence

DEAD = 'https://medusa-docs-fqqfwm7cj-medusajs.vercel.app/modules/multiwarehouse/admin/manage-reservations'


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.AdmissionTests('test_selection_only_uses_short_dedicated_prompt')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.c = fixture.c
        self.c.work.chmod(0o700)
        self.rows = [evidence('builder' if i < 9 else 'attacker', 'github' if i < 3 else 'web',
                              i, hit=True) for i in range(17)]
        self.rows[13]['url'] = DEAD
        (self.c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, self.rows)))
        self.answers = [dict(url=r['url'], resolved=True, retrieved=True, same_bug=False,
            retrieved_from='live', archive_checked=False, archive_available=None,
            archive_snapshot_url=None, live_failure=None, app_version='2.19.0',
            version_scope='Checked pinned release', why='Different bug') for r in self.rows]
        self.answers[13].update(retrieved=False, same_bug=None, retrieved_from='none',
            archive_checked=True, archive_available=False, live_failure='http_404',
            why='HTTP 404, deployment root also 404; Wayback availability API returned no snapshot')

        from freshness_test_transport import start, fetched
        def transport(url):
            if url == DEAD:
                return {'url': url, 'final_url': url, 'status': 404}, b''
            if url.startswith('https://archive.org/wayback/available?'):
                answer = self.answers[13]
                closest = ({'available': True, 'status': '200', 'url': answer['archive_snapshot_url']}
                           if answer.get('archive_available') is True else None)
                return {'url': url, 'final_url': url, 'status': 200}, json.dumps(
                    {'archived_snapshots': {'closest': closest} if closest else {}}).encode()
            return fetched(url)
        start(self, transport)

    def review(self):
        def reviewer(c, models, text, cwd, name, **kwargs):
            self.assertEqual(name, 'reviewer-g2-confirm')
            self.assertIn('web.archive.org', text)
            self.assertIn('archive_checked', text)
            (Path(cwd) / 'verdict.json').write_text(json.dumps({'hits': self.answers}))
            return 0
        with patch.object(run, 'opencode', side_effect=reviewer):
            return run.ensure_freshness(self.c)

    def test_seventeen_rows_dead_row_fourteen_no_archive_clears_and_receipts_reuse(self):
        ok, info = self.review()
        self.assertTrue(ok)
        self.assertEqual(info['unreachable_hits'], 1)
        self.assertEqual(self.c.card['freshness_confirmation']['unreachable_hits'], 1)
        receipt = json.loads((self.c.work / 'freshness-verdict.json').read_text())
        self.assertEqual(receipt['hits'][13]['retrieved_from'], 'none')
        self.assertEqual(receipt['review_summary']['unreachable_hits'], 1)
        self.assertEqual(receipt['review_summary']['unreachable_rows'], [14])
        with patch.object(run, 'opencode', side_effect=AssertionError('paid repeat')):
            self.assertTrue(run.g2(self.c)[0])

    def test_confirmers_told_the_apps_own_source_is_not_public(self):
        seen = []
        def reviewer(c, models, text, cwd, name, **kwargs):
            seen.append(text)
            (Path(cwd) / 'verdict.json').write_text(json.dumps({'hits': self.answers}))
            return 0
        with patch.object(run, 'opencode', side_effect=reviewer):
            run.ensure_freshness(self.c)
        self.assertEqual(len(seen), 1)
        self.assertIn(run.SOURCE_CODE_NOT_PUBLIC, seen[0])
        self.assertIn("app's own source code", seen[0])
        self.assertIn('a commit or PR that fixes it', seen[0])

    def test_archived_same_bug_blocks(self):
        self.answers[13].update(retrieved=True, same_bug=True, retrieved_from='archive',
            archive_available=True, archive_snapshot_url='https://web.archive.org/web/20260101000000/' + DEAD)
        ok, info = self.review()
        self.assertFalse(ok)
        self.assertEqual(info['outcome'], 'public_match')
        self.assertEqual(info['confirmed_hits'], 1)
        self.assertEqual(info['archived_hits'], 1)

    def test_archive_exclusion_clears(self):
        self.answers[13].update(retrieved=True, same_bug=False, retrieved_from='archive',
            archive_available=True, archive_snapshot_url='https://web.archive.org/web/20260101000000/' + DEAD)
        self.assertTrue(self.review()[0])

    def test_missing_archive_check_and_transient_failures_stay_unresolved(self):
        original = copy.deepcopy(self.answers[13])
        for change in ({'archive_checked':False}, {'live_failure':'timeout'},
                       {'archive_available':None}, {'resolved':False},
                       {'archive_snapshot_url':'https://example.com/snapshot'},
                       {'same_bug':False}):
            with self.subTest(change=change):
                self.answers[13] = {**original, **change}
                with self.assertRaisesRegex(run.BudgetError, '^freshness_review_unavailable$'):
                    self.review()
                self.assertEqual(self.c.card['admission_freshness']['unresolved_hits'], 1)

    def test_archive_must_be_wayback_snapshot_of_supplied_url(self):
        for snapshot in ('https://example.com/web/20260101000000/' + DEAD,
                         'https://web.archive.org/web/20260101000000/https://example.com/other'):
            self.answers[13].update(retrieved=True, same_bug=False, retrieved_from='archive',
                archive_available=True, archive_snapshot_url=snapshot)
            from run_validity import InfrastructureExhausted
            with self.assertRaises(InfrastructureExhausted): self.review()


if __name__ == '__main__': unittest.main()
