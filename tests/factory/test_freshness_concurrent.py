"""The writer's and the stress tester's freshness searches run at the same time, each in its own working
copy, and their rows merge back by owner. Same searches, same evidence validation (12 Nov: 17.6 + 9.4 min)."""
import json
import pathlib
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import run
import test_freshness_restore_fixes as fixtures
from router_test_support import offline_router
from test_admission import evidence


class ConcurrentFreshness(unittest.TestCase):
    save = fixtures.FreshnessRestoreTests.save
    def setUp(self):
        fixtures.FreshnessRestoreTests.setUp(self)   # a case with a statement and complete evidence
        # Both roles are short: each has one unretrieved row and needs one more search.
        self.rows = [{**r, 'retrieved': False} if i in (0, 6) else r for i, r in enumerate(self.rows)]
        self.save()

    def read(self, cwd):
        return [json.loads(line) for line in (pathlib.Path(cwd) / 'freshness.jsonl').read_text().splitlines()]

    def test_roles_overlap_and_their_rows_merge_by_owner(self):
        self.addCleanup(offline_router()[0].close)
        both_running = threading.Barrier(2, timeout=10)   # fails unless both calls are in flight together
        texts, dirs = {}, {}

        def model(ctx, models, text, cwd, name, **kwargs):
            who = name.split('-')[0]
            texts[who], dirs[who] = text, cwd
            both_running.wait()
            rows = self.read(cwd)
            rows = [{**r, 'retrieved': True} if r['who'] == who else r for r in rows]
            rows.append(evidence(who, 'web', 90 + len(who)))
            # A role cannot touch the other role's rows: this edit must not survive the merge.
            rows = [{**r, 'note': 'tampered'} if r['who'] != who else r for r in rows]
            (pathlib.Path(cwd) / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
            return 0

        with patch.object(run, 'opencode', model):
            run.freshness_topup(self.c)
        self.assertNotEqual(dirs['builder'], dirs['attacker'])
        self.assertNotIn(str(self.c.case), texts['builder'])    # the role is told its own directory
        merged = run.freshness_lines(self.c)
        self.assertEqual(len(merged), len(self.rows) + 2)
        self.assertTrue(all(r.get('retrieved') is True for r in merged))
        self.assertFalse(any(r.get('note') == 'tampered' for r in merged))
        self.assertEqual({r['who'] for r in merged[len(self.rows):]}, {'builder', 'attacker'})
        self.assertFalse(list(self.c.work.glob('freshness-*-*')))   # no working copy is left behind

    def test_the_prompt_caps_new_searches(self):
        self.addCleanup(offline_router()[0].close)
        texts = {}

        def model(ctx, models, text, cwd, name, **kwargs):
            texts[name.split('-')[0]] = text
            return 0

        with patch.object(run, 'opencode', model):
            run.freshness_topup(self.c)
        self.assertIn('at most 3 new searches', texts['builder'])   # one missing search plus two extra
        self.assertIn('at most 3 new searches', texts['attacker'])

    def test_a_failing_role_still_keeps_its_partial_rows_and_the_error_surfaces(self):
        self.addCleanup(offline_router()[0].close)

        def model(ctx, models, text, cwd, name, **kwargs):
            if name.startswith('attacker'):
                raise run.BudgetError('provider_limit:synthetic')
            rows = self.read(cwd)
            rows.append(evidence('builder', 'web', 95))
            (pathlib.Path(cwd) / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
            return 0

        with patch.object(run, 'opencode', model), self.assertRaisesRegex(run.BudgetError, 'provider_limit'):
            run.freshness_topup(self.c)
        self.assertEqual(len(run.freshness_lines(self.c)), len(self.rows) + 1)


if __name__ == '__main__':
    unittest.main()
