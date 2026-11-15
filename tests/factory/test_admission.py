"""Synthetic candidate admission/prototype checks: no keys, Docker, or model calls."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import shlex
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory")))
import admission
import ordinary_freshness
import run


def ENGINE():
    """The engine's attempt deadline, the only bound on a freshness top-up."""
    return types.SimpleNamespace(deadline_monotonic=time.monotonic() + 3600)


def engine_topups(test):
    """Only the top-up sees the engine deadline; the rest of the test keeps its own context."""
    real = run.freshness_topup
    def topup(c, **kwargs):
        c.engine = ENGINE()
        try: return real(c, **kwargs)
        finally: del c.engine
    mocked = patch.object(run, 'freshness_topup', topup)
    mocked.start(); test.addCleanup(mocked.stop)


def evidence(who, kind, i, **more):
    return {"who": who, "kind": kind, "query": f"stock query {i}", "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "url": f"https://github.com/medusajs/medusa/issues/{i}", "retrieved": True,
            "hit": False, "app_version": "2.19.0", "version_scope": "Pinned release investigated",
            "note": "Unrelated result", **more}


def scratch_rows(cwd):
    """The search rows of a freshness call's own working copy (each role searches in its own directory)."""
    path = pathlib.Path(cwd) / 'freshness.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []


def scratch_write(cwd, rows):
    (pathlib.Path(cwd) / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        from freshness_test_transport import start
        start(self)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name); case = root / "case"; case.mkdir()
        self.c = types.SimpleNamespace(work=root, case=case, case_id="case-new", card={}, seed=42, batch_deadline="2999-01-01T00:00:00Z",
            args=argparse.Namespace(dry_run=False, source="hunt", rounds=1, runs=10, scenario_runs=3, resume=None),
            models={"builder": ["claude/writer"], "attacker": ["deepseek/attacker"],
                    "easy_calibrator": ["glm/easy"], "reviewers": [["minimax/reviewer"]]})
        (case / "statement.md").write_text("Synthetic selected stock accounting failure in app 2.19.0.")
        self.rows = [evidence("builder", kind, i) for kind in ("web", "github") for i in range(3)]
        self.rows += [evidence("attacker", "web", i) for i in range(2)]
        (case / "freshness.jsonl").write_text("\n".join(map(json.dumps, self.rows)))

    def test_selection_only_uses_short_dedicated_prompt(self):
        c = self.c; (c.case / "statement.md").unlink(); c.args.statement_only = True
        calls = []
        def select(ctx, models, text, cwd, name):
            calls.append(name)
            self.assertIn("up to three SHORT sketches", text)
            self.assertNotIn("V2 recipe", text)
            (c.case / "statement.md").write_text("Synthetic selected bug in 2.19.0.")
            return 0
        with patch.object(run, "opencode", select), patch.object(run, 'selection_statements', return_value={}), \
             patch.object(run, "prior_statements", side_effect=AssertionError("registry before publication")):
            self.assertTrue(run.statement_precheck(c))
        self.assertEqual(calls, ["builder-selection"])
        self.assertEqual(c.card["admission"]["status"], "awaiting_shared_reservation")

    def test_rejected_or_unavailable_candidate_never_constructs(self):
        for mode in ("duplicate", "malformed", "unavailable", "public"):
            with self.subTest(mode=mode):
                c = self.c; c.card = {}; c.__dict__.pop("precheck_problems", None)
                earlier = c.work / "synthetic.md"; earlier.write_text("Synthetic earlier statement.")
                def compare(ctx, models, text, cwd, name):
                    if mode == "unavailable": raise run.BudgetError("synthetic unavailable")
                    request = json.loads(text.split("\n", 1)[1])
                    if name.endswith("-second-opinion-dedup"):   # a second family confirms the duplicate
                        self.assertNotIn(models[0].split("/")[0], ("claude", "glm"))
                        pathlib.Path(request["result_path"]).write_text(json.dumps({"same_bug": True, "reason": "same"}))
                        return 0
                    verdict = {} if mode == "malformed" else {"duplicate_of": "case-old" if mode == "duplicate" else None, "reason": "Compared mechanisms"}
                    pathlib.Path(request["result_path"]).write_text(json.dumps(verdict)); return 0
                with patch.object(run, "prior_statements", return_value={"case-old": str(earlier)}), \
                     patch.object(run, "model_call", compare), patch.object(run, "opencode") as builder, \
                     patch.object(run, "ensure_freshness", return_value=(mode != "public", {"outcome": "public_match"} if mode == "public" else {})):
                    try: run.statement_precheck(c)
                    except run.BudgetError:
                        self.assertIn(mode, ("malformed", "unavailable"))
                    builder.assert_not_called()

    def test_unavailable_registry_blocks_and_statement_only_publishes(self):
        with patch.object(run, "prior_statements", side_effect=RuntimeError("snapshot unavailable")), \
             patch.object(run, "opencode") as model:
            with self.assertRaisesRegex(run.BudgetError, "admission_registry_unavailable"):
                run.statement_precheck(self.c)
            model.assert_not_called()
            self.c.args.statement_only = True
            self.assertTrue(run.statement_precheck(self.c))
        self.assertEqual(self.c.card["statement_sha256"], hashlib.sha256(self.c.statement.encode()).hexdigest())

    def test_registry_requires_complete_bound_snapshot(self):
        directory = self.c.work / "registry"; directory.mkdir()
        f = directory / "case-old.statement.age"; f.write_bytes(b"synthetic ciphertext")
        attestation = {"version": 1, "case_id": self.c.case_id, "registry_revision": 3,
            "statement_sha256": hashlib.sha256(b"candidate").hexdigest(), "complete": True,
            "reservation": "synthetic-reservation", "statements": {"case-old": hashlib.sha256(f.read_bytes()).hexdigest()}}
        (directory / "admission.json").write_text(json.dumps(attestation))
        self.assertEqual(set(admission.registry_snapshot(directory, self.c.case_id, "candidate")), {"case-old"})
        for mode in ("candidate", "ciphertext", "missing"):
            with self.subTest(mode=mode):
                if mode == "ciphertext": f.write_bytes(b"changed")
                if mode == "missing": f.unlink()
                with self.assertRaises(ValueError): admission.registry_snapshot(directory, self.c.case_id, "changed" if mode == "candidate" else "candidate")

    def test_distinct_retrieved_evidence_required(self):
        self.assertTrue(run.g2(self.c)[0])
        original = self.rows
        for rows in ([original[0]] * 3 + original[3:],
                     [{**r, "retrieved": False} for r in original],
                     [{**r, "url": "https://example.invalid/a"} for r in original],
                     [{**r, "app_version": "unknown"} for r in original]):
            (self.c.case / "freshness.jsonl").write_text("\n".join(map(json.dumps, rows)))
            self.assertFalse(run.g2(self.c)[0])

    def test_invalid_search_evidence_is_repaired_without_reselecting(self):
        self.c.engine = ENGINE()   # top-ups run under the engine's attempt deadline
        c = self.c
        c.args.agent_timeout = 14400
        broken = [{**self.rows[i % len(self.rows)], "retrieved": False} for i in range(20)]
        (c.case / "freshness.jsonl").write_text("\n".join(map(json.dumps, broken)))
        before = (c.case / "statement.md").read_bytes()
        calls = []
        def repair(ctx, models, text, cwd, name, **kwargs):
            calls.append(name)
            self.assertIn("retrieval_failed", text)
            self.assertGreater(kwargs["timeout"], 300)
            self.assertAlmostEqual(kwargs["timeout"], kwargs["deadline"] - time.monotonic(), delta=5)   # the attempt deadline
            scratch_write(cwd, [{**row, 'retrieved': True} for row in scratch_rows(cwd)])
            return 0
        with patch.object(run, "prior_statements", return_value={}), patch.object(run, "opencode", repair), \
             patch.object(run, "idea_realism", return_value=True):
            self.assertTrue(run.statement_precheck(c))
        self.assertEqual((c.case / "statement.md").read_bytes(), before)
        self.assertEqual(c.card["candidate_attempts"], 1)
        self.assertNotIn("rejected_candidates", c.card)
        self.assertEqual(c.card["admission_freshness"]["outcome"], "clear")
        self.assertEqual(sorted(calls), ["attacker-freshness", "builder-freshness"])   # each role repairs its own rows
        self.assertEqual(len(run.freshness_lines(c)), 20)
        self.assertTrue(all(type(v) is int for counts in c.card['freshness_topup'].values() for v in counts.values()))

    def test_unrepaired_search_evidence_pauses_same_idea_and_cannot_reset_on_resume(self):
        self.c.engine = ENGINE()   # top-ups run under the engine's attempt deadline
        c = self.c
        rows = [{**r, "retrieved": False} for r in self.rows]
        (c.case / "freshness.jsonl").write_text("\n".join(map(json.dumps, rows)))
        before = (c.case / "statement.md").read_bytes()
        with patch.object(run, "prior_statements", return_value={}), \
             patch.object(run, "opencode", return_value=0) as model:
            # Unretrieved rows need a re-run search, not a repair: a refresh that re-ran nothing is a
            # retryable stall, and a later attempt tries again without spending the defect bound.
            with self.assertRaisesRegex(run.BudgetError, "^freshness_refresh_stalled$"):
                run.statement_precheck(c)
            self.assertEqual(model.call_count, 2)
            resumed = types.SimpleNamespace(**vars(c))
            with self.assertRaisesRegex(run.BudgetError, "^freshness_refresh_stalled$"):
                run.statement_precheck(resumed)
            self.assertEqual(model.call_count, 4)
        self.assertEqual(json.loads((c.work / "freshness-repair.json").read_text())["completed_defects"], 0)
        self.assertEqual((c.case / "statement.md").read_bytes(), before)
        self.assertEqual(c.card["candidate_attempts"], 1)
        self.assertNotIn("rejected_candidates", c.card)
        self.assertEqual(c.card["admission_freshness"]["invalid_evidence_reasons"], {"retrieval_failed": 8})

    def test_search_validation_reports_specific_reasons_without_exposing_contents(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        bad = [({"retrieved": False}, "retrieval_failed"), ({"note": ""}, "missing_note"),
               ({"at": "not a timestamp"}, "invalid_timestamp"),
               ({"at": (now + datetime.timedelta(hours=1)).isoformat()}, "timestamp_in_future"),
               ({"at": (now - datetime.timedelta(days=2)).isoformat()}, "evidence_expired"),
               ({"app_version": "latest"}, "invalid_app_version"),
               ({"url": "http://[malformed"}, "invalid_url"),
               ({"kind": "github", "url": "https://elsewhere.test/search"}, "github_url_required")]
        for fields, reason in bad:
            with self.subTest(reason=reason):
                row = {**self.rows[0], **fields}
                self.assertEqual(admission.search_evidence_error(row), reason)
                self.assertIsNone(admission.search_evidence(row))

    def test_public_match_is_rejected_but_unknown_review_preserves_the_idea(self):
        c = self.c; self.rows[0]['hit'] = True
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, self.rows)))
        def confirm(ctx, models, text, cwd, name, **kwargs):
            self.assertEqual(name, 'reviewer-g2-confirm')
            (pathlib.Path(cwd) / 'verdict.json').write_text(json.dumps({'hits': [{
                'same_bug': True, 'resolved': True, 'url': self.rows[0]['url'], 'retrieved': True,
                'app_version': '2.19.0', 'version_scope': 'Synthetic exact pinned version', 'why': 'Same synthetic fix'}]}))
            return 0
        with patch.object(run, 'prior_statements', return_value={}), patch.object(run, 'opencode', confirm):
            self.assertFalse(run.statement_precheck(c))
        self.assertEqual(c.card['admission']['screen'], 'public_freshness')
        self.assertEqual(c.card['admission_freshness']['outcome'], 'public_match')
        self.assertEqual(c.card['admission_freshness']['confirmed_hits'], 1)
        c.card = {}
        (c.work / 'freshness-verdict.json').unlink()  # next scenario has no retained independent answer
        with patch.object(run, 'prior_statements', return_value={}), \
             patch.object(run, 'opencode', return_value=0) as model:
            with self.assertRaisesRegex(run.BudgetError, 'freshness_review_unavailable'):
                run.statement_precheck(c)
            self.assertEqual(model.call_count, 1 + ordinary_freshness.REVIEW_REASKS)
        self.assertEqual(c.card['admission_freshness']['unresolved_hits'], 1)

    def test_evidence_repair_cannot_change_the_selected_bug(self):
        self.c.engine = ENGINE()   # top-ups run under the engine's attempt deadline
        c = self.c; original = (c.case / 'statement.md').read_bytes()
        rows = [{**r, 'retrieved': False} for r in self.rows]
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        def change(*args, **kwargs):
            (c.case / 'statement.md').write_text('An unauthorized replacement idea')
            (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, self.rows)))
            return 0
        with patch.object(run, 'opencode', change):
            with self.assertRaisesRegex(run.BudgetError, 'freshness_statement_changed'):
                run.ensure_freshness(c)
        self.assertEqual((c.case / 'statement.md').read_bytes(), original)
        self.assertEqual([{k: v for k, v in row.items() if k != '_search_id'} for row in run.freshness_lines(c)], rows)

    def test_interrupted_evidence_repair_preserves_flagged_searches(self):
        self.c.engine = ENGINE()   # top-ups run under the engine's attempt deadline
        c = self.c; rows = [{**r, 'retrieved': False} for r in self.rows];rows[0]['hit'] = True
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        def interrupt(*args, **kwargs):
            (c.case / 'freshness.jsonl').write_text('')
            raise run.BudgetError('provider_limit:synthetic')
        with patch.object(run, 'opencode', interrupt), patch.object(run, 'confirm_hits', return_value=[]):
            with self.assertRaisesRegex(run.BudgetError, 'provider_limit'):
                run.ensure_freshness(c)
        self.assertTrue(any(row.get('hit') is True for row in run.freshness_lines(c)))
        state = json.loads((c.work / 'freshness-repair.json').read_text())
        self.assertEqual((state['completed_defects'], state['pending']['phase']), (0, 'pending'))

    def test_unresolved_applicability_is_not_a_confirmed_public_match(self):
        c = self.c; self.rows[0]['hit'] = True
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, self.rows)))
        def unknown(ctx, models, text, cwd, name, **kwargs):
            (pathlib.Path(cwd) / 'verdict.json').write_text(json.dumps({'hits': [{
                'same_bug': True, 'retrieved': True, 'url': self.rows[0]['url'],
                'app_version': '2.19.0', 'version_scope': 'Applicability cannot be determined',
                'why': 'Retrieved but applicability unresolved'}]}))
            return 0
        with patch.object(run, 'opencode', unknown):
            with self.assertRaisesRegex(run.BudgetError, 'freshness_review_unavailable'):
                run.ensure_freshness(c)
        self.assertEqual(c.card['admission_freshness']['confirmed_hits'], 0)

    def test_each_repair_call_preserves_new_flags_and_failed_history(self):
        self.c.engine = ENGINE()   # top-ups run under the engine's attempt deadline
        c = self.c
        rows = [{**r, 'retrieved': False} for r in self.rows[:6]]
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        calls = []
        def repair(ctx, models, text, cwd, name, **kwargs):
            calls.append(name)
            current = scratch_rows(cwd)
            if name == 'builder-freshness':
                for row in current: row['retrieved'] = True
                current[0]['hit'] = True
            else:
                # A later role must not silently erase the first role's discovery.
                current = [{**row, 'hit': False} for row in current] + self.rows[6:]
            scratch_write(cwd, current)
            return 0
        with patch.object(run, 'opencode', repair): run.freshness_topup(c)
        self.assertEqual(sorted(calls), ['attacker-freshness', 'builder-freshness'])   # the roles search together
        self.assertTrue(any(row.get('hit') is True for row in run.freshness_lines(c)))
        failed = evidence('builder', 'web', 99, retrieved=False)
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, self.rows + [failed])))
        def delete_failed(ctx, models, text, cwd, name, **kwargs):
            scratch_write(cwd, [row for row in scratch_rows(cwd) if row['retrieved']])
            return 0
        with patch.object(run, 'opencode', delete_failed):
            with self.assertRaisesRegex(run.BudgetError, '^freshness_refresh_stalled$'):
                run.ensure_freshness(c)
        self.assertTrue(any(row['retrieved'] is False for row in run.freshness_lines(c)))

    def test_invalid_flagged_evidence_is_repaired_before_review(self):
        engine_topups(self)   # the review that follows runs outside the engine, as this test always did
        c = self.c; rows = [dict(r) for r in self.rows]
        rows[0].update(hit=True, retrieved=False, app_version='unknown')
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        calls = []
        def repair_then_review(ctx, models, text, cwd, name, **kwargs):
            calls.append(name)
            if name.endswith('-freshness'):
                repaired = scratch_rows(cwd)
                repaired[0].update(retrieved=True, app_version='2.19.0')
                scratch_write(cwd, repaired)
            else:
                (pathlib.Path(cwd) / 'verdict.json').write_text(json.dumps({'hits': [{
                    'same_bug': False, 'resolved': True, 'retrieved': True, 'url': rows[0]['url'],
                    'app_version': '2.19.0', 'version_scope': 'Different app', 'why': 'Unrelated result'}]}))
            return 0
        with patch.object(run, 'opencode', repair_then_review):
            self.assertTrue(run.ensure_freshness(c)[0])
        self.assertEqual(calls, ['builder-freshness', 'reviewer-g2-confirm'])

    def test_search_results_page_is_not_evidence(self):
        # 1bb2ad (15 Nov): the runner's fetch of a results page is the engine's script interstitial.
        for url in ('https://www.google.com/search?q=medusa+oversell', 'https://google.co.uk/search?q=x',
                    'https://www.bing.com/search?q=x', 'https://duckduckgo.com/?q=x', 'https://html.duckduckgo.com/html/?q=x',
                    'https://search.yahoo.com/search?p=x', 'https://search.brave.com/search?q=x',
                    'https://www.google.com/url?q=https://github.com/a/b', 'https://duckduckgo.com/l/?uddg=https%3A%2F%2Fa.dev',
                    'https://www.bing.com/ck/a?u=a1aHR0cHM', 'https://www.startpage.com/sp/search?query=x',
                    'https://search.yahoo.co.jp/search?p=x', 'https://scholar.google.com/scholar?q=x'):
            with self.subTest(url=url):
                self.assertEqual(admission.search_evidence_error({**self.rows[0], 'url': url}), 'search_page_url')
        # Result pages stay evidence, and fan-out's own no-result GitHub search row stays valid.
        for url in ('https://www.google.com/about', 'https://bing.com/news/a', 'https://duckduckgo.com/privacy',
                    'https://github.com/search?type=issues&q=x', 'https://researchgate.net/search?q=x'):
            with self.subTest(url=url):
                self.assertIsNone(admission.search_url_error({**self.rows[0], 'url': url}))

    def test_search_results_page_row_is_amended_to_its_result_before_review(self):
        engine_topups(self)
        c = self.c; rows = [dict(r) for r in self.rows]
        rows[0].update(url='https://www.google.com/search?q=stock+query+0', ambiguous=True)
        rows[1].update(url='https://www.bing.com/search?q=stock+query+1')
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        result = 'https://github.com/medusajs/medusa/discussions/700'
        calls = []
        def repair_then_review(ctx, models, text, cwd, name, **kwargs):
            calls.append(name)
            if name.endswith('-freshness'):
                self.assertIn('search_page_url', text)
                self.assertIn('never a search-results page', text)
                repaired = scratch_rows(cwd)
                repaired[0]['url'], repaired[1]['url'] = result, 'https://github.com/medusajs/medusa/discussions/701'
                scratch_write(cwd, repaired)
            else:
                (pathlib.Path(cwd) / 'verdict.json').write_text(json.dumps({'hits': [{
                    'same_bug': False, 'resolved': True, 'retrieved': True, 'url': result,
                    'app_version': '2.19.0', 'version_scope': 'Different app', 'why': 'Unrelated result'}]}))
            return 0
        with patch.object(run, 'opencode', repair_then_review):
            self.assertTrue(run.ensure_freshness(c)[0])
        self.assertEqual(calls, ['builder-freshness', 'reviewer-g2-confirm'])   # the reviewer reads the result page
        kept = run.freshness_lines(c)
        self.assertEqual(len(kept), len(rows))
        self.assertTrue(any(r['url'] == result and r.get('ambiguous') is True for r in kept))   # the flag moved with it

    def test_search_results_page_row_is_never_cleared_by_dropping_it(self):
        engine_topups(self)
        c = self.c; rows = [dict(r) for r in self.rows]
        serp = 'https://www.google.com/search?q=stock+query+0'
        rows[0].update(url=serp, ambiguous=True)
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        calls = []
        def drop(ctx, models, text, cwd, name, **kwargs):
            calls.append(name)
            kept = [r for r in scratch_rows(cwd) if r['url'] != serp]
            scratch_write(cwd, kept + [evidence('builder', 'web', 50 + len(calls))])
            return 0
        with patch.object(run, 'opencode', drop):
            with self.assertRaisesRegex(run.BudgetError, '^freshness_evidence_unavailable$'):
                run.ensure_freshness(c)
        self.assertEqual(calls, ['builder-freshness'] * 2)   # bounded by the defect limit; no reviewer is paid
        self.assertTrue(any(r['url'] == serp and r.get('ambiguous') is True for r in run.freshness_lines(c)))

    def test_mid_call_checkpoint_restores_search_history_before_admission(self):
        c = self.c; dropped = evidence('builder', 'web', 99, retrieved=False, _search_id='a' * 64)
        # The model's completed-call checkpoint can exist before the caller's finally runs.
        (c.work / 'freshness-inflight.json').write_text(json.dumps({
            'rows': [dropped], 'statement_hex': (c.case / 'statement.md').read_bytes().hex()}))
        ok, info = run.g2(types.SimpleNamespace(**vars(c)))
        self.assertFalse(ok)
        self.assertEqual(info['invalid_evidence_reasons'], {'retrieval_failed': 1})
        self.assertIn(dropped, run.freshness_lines(c))
        self.assertFalse((c.work / 'freshness-inflight.json').exists())

    def test_repair_cannot_replace_a_historical_flagged_result(self):
        self.c.engine = ENGINE()   # top-ups run under the engine's attempt deadline
        c = self.c; rows = [dict(r) for r in self.rows]
        rows[0].update(hit=True, retrieved=False)
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        def replace(ctx, models, text, cwd, name, **kwargs):
            changed = scratch_rows(cwd)
            changed[0].update(retrieved=True, query='Different search', url='https://github.com/other/app/issues/123', hit=False)
            scratch_write(cwd, changed)
            return 0
        with patch.object(run, 'opencode', replace): run.freshness_topup(c)
        kept = run.freshness_lines(c)
        self.assertTrue(any(r['url'] == rows[0]['url'] and r['query'] == rows[0]['query'] and r['hit'] for r in kept))
        self.assertFalse(run._g2(c)[0])

    def test_statement_mutation_keeps_new_public_flags_for_resume(self):
        self.c.engine = ENGINE()   # top-ups run under the engine's attempt deadline
        c = self.c; rows = [{**r, 'retrieved': False} for r in self.rows]
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        discovered = evidence('builder', 'web', 99, hit=True)
        def mutate(*args, **kwargs):
            # fan_out runs one call per role in parallel: replace each file whole, never truncate it
            for name, text in (('statement.md', 'Unauthorized different idea'),
                               ('freshness.jsonl', '\n'.join(map(json.dumps, self.rows + [discovered])))):
                with tempfile.NamedTemporaryFile('w', dir=c.case, delete=False) as f: f.write(text)
                os.replace(f.name, c.case / name)
            return 0
        with patch.object(run, 'opencode', mutate):
            with self.assertRaisesRegex(run.BudgetError, 'freshness_statement_changed'): run.ensure_freshness(c)
        self.assertTrue(any(r['url'] == discovered['url'] and r['hit'] for r in run.freshness_lines(c)))

    def test_missing_or_malformed_search_identity_can_be_repaired(self):
        self.c.engine = ENGINE()   # top-ups run under the engine's attempt deadline
        c = self.c; rows = [dict(r) for r in self.rows]
        rows[0].update(url='http://[malformed', who='writer', kind='WEB', query='')
        (c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        def repair(ctx, models, text, cwd, name, **kwargs):
            changed = scratch_rows(cwd)
            changed[0].update({k: self.rows[0][k] for k in ('url', 'who', 'kind', 'query')})
            scratch_write(cwd, changed)
            return 0
        with patch.object(run, 'opencode', repair): self.assertTrue(run.ensure_freshness(c)[0])
        self.assertEqual(len(run.freshness_lines(c)), len(rows))

    def test_prototype_measures_real_controls_before_full_suite(self):
        c = self.c
        for file in ("case.json", "promise.md", "base/scenario.json", "base/key.json", "base/hooks.mjs", "base/judge.py", "guards/reference/services.patch", "guards/cheats/obvious/db.sql"):
            path = c.case / file; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("{}")
        (c.case / "case.json").write_text('{"promise_paths": ["stock"]}')
        def checkpoint(ctx, scenarios, guard, runs, seed, label):
            self.assertEqual(runs, 1)
            name = label.removeprefix("prototype-")
            return {"legit_completion": 1}, [{"errors": [], "checker": {"valid": True}, "judge": {
                "paths": {"stock": name in ("none", "wrong-fix")}, "checks": {"business": name != "refuse-all"}}}]
        with patch.object(run, "g3", return_value=(True, {})), patch.object(run, "checkpoint", checkpoint):
            self.assertTrue(admission.prototype(run, c)[0])
        with patch.object(run, "g3", return_value=(True, {})), \
             patch.object(run, "checkpoint", return_value=({"legit_completion": 1}, [])):
            from run_validity import InfrastructureExhausted
            with self.assertRaises(InfrastructureExhausted): admission.prototype(run, c)

    def test_search_receipt_expiry_binding_and_malformed_verdict(self):
        c = self.c
        self.assertTrue(run.g2(c)[0])
        receipt = json.loads((c.work / "public-search.json").read_text())
        binding = admission.search_binding(c, self.rows)
        self.assertIsNotNone(admission.reusable_search(receipt, binding))
        expired = datetime.datetime.fromisoformat(receipt["expires_at"])
        self.assertIsNone(admission.reusable_search(receipt, binding, expired))
        for changed in ({**binding, "statement_sha256": "a" * 64}, {**binding, "reservation": {"registry_revision": 9}}):
            self.assertIsNone(admission.reusable_search(receipt, changed))
        for field, value in (("ok", "true"), ("info", {}), ("expires_at", "invalid")):
            self.assertIsNone(admission.reusable_search({**receipt, field: value}, binding))
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)).isoformat()
        self.assertIsNone(admission.search_evidence({**self.rows[0], "at": old}))

    def test_g2_reuses_only_unchanged_valid_evidence(self):
        c = self.c; self.rows[0]["hit"] = True
        (c.case / "freshness.jsonl").write_text("\n".join(map(json.dumps, self.rows)))
        with patch.object(run, "confirm_hits", return_value=[]) as confirm:
            self.assertTrue(run.g2(c)[0]); self.assertTrue(run.g2(c)[0])
            self.assertEqual(confirm.call_count, 2)
            (c.case / "promise.md").write_text("changed search context")
            self.assertTrue(run.g2(c)[0]); self.assertEqual(confirm.call_count, 3)

    def test_idea_review_invalid_rejected_and_success_cached(self):
        c = self.c; c.statement = (c.case / "statement.md").read_text()
        c.card["statement_sha256"] = hashlib.sha256(c.statement.encode()).hexdigest()
        def model(verdict):
            def call(ctx, chain, text, cwd, name):
                self.assertEqual(name, "reviewer-idea-realism")
                self.assertEqual({p.name for p in pathlib.Path(cwd).iterdir()}, {"statement.md"})
                (pathlib.Path(cwd) / "verdict.json").write_text(json.dumps(verdict)); return 0
            return call
        with patch.object(run, "model_call", model({"approve": "true", "reason": "bad type"})):
            with self.assertRaisesRegex(run.BudgetError, "admission_idea_review_invalid"): run.idea_realism(c)
        with patch.object(run, "model_call", model({"approve": False, "reason": "Contrived mechanism"})):
            self.assertFalse(run.idea_realism(c))
        with patch.object(run, "model_call", model({"approve": True, "reason": "Plausible pinned behavior"})):
            self.assertTrue(run.idea_realism(c))
        with patch.object(run, "model_call", side_effect=AssertionError("unnecessary repeat")):
            self.assertTrue(run.idea_realism(c))

    def test_g15_rejects_before_expensive_early_checks(self):
        c = self.c; (c.case / "answer-key.json").write_text("{}")
        with patch.object(run, "g15", return_value=(False, {"honest_reference": "invalid"})), \
             patch.object(run, "g3", side_effect=AssertionError("expensive build")), patch.object(run, "log"):
            self.assertIn("G15", run.early_checks(c)[0])

    def test_reference_strategy_cache_invalidates_when_writer_repairs_inputs(self):
        c = self.c
        bench = c.work / 'synthetic-bench'; bench.mkdir()
        calls = []
        def simulate(*args, **kwargs):
            calls.append((args, kwargs))
            checkpoint = bench / 'results/runs' / str(len(calls)) / 'checkpoint.json'
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text('{"runs":3,"error_runs":0}')
            return {'strategy': 'honest-reference',
                    'steps': [{'step': 'establish', 'unsafe': False, 'response_correct': True, 'human_minutes': 1}],
                    'totals': {'steps': 1, 'unsafe': 0, 'wrong': 0, 'human_minutes': 1}, 'skipped': [],
                    '_evidence_paths': [str(checkpoint)]}
        module = types.SimpleNamespace(STRATEGIES=('honest-reference',), simulate=simulate,
                                       steps=lambda case: [{'id': 'establish'}])
        with patch.object(run, "strategy_module", return_value=module), patch.object(run, 'BENCH', bench), \
             patch.object(run, 'bench_manifest', return_value='synthetic implementation'):
            run.strategy_run(c, "honest-reference"); run.strategy_run(c, "honest-reference")
            self.assertEqual(len(calls), 1)
            (c.case / "answer-key.json").write_text('{"changed": true}')
            run.strategy_run(c, "honest-reference")
            self.assertEqual(len(calls), 2)

    def test_seal_exports_only_opaque_search_ciphertext_with_bound_digest(self):
        c = self.c; c.statement = (c.case / "statement.md").read_text(); c.recipient = "synthetic-recipient"
        c.t0 = 0
        self.assertTrue(run.g2(c)[0])
        sealed = c.work / "sealed"; recipient = c.work / "recipient.txt"; recipient.write_text("synthetic-recipient")
        def encrypt(args, **kwargs):
            if isinstance(args, list):
                pathlib.Path(args[args.index("-o") + 1]).write_bytes(b"age-encryption.org/v1\nsynthetic ciphertext")
            else:
                pathlib.Path(shlex.split(args)[-1]).write_bytes(b"age-encryption.org/v1\nsynthetic archive")
            return types.SimpleNamespace(returncode=0)
        import r2_upload
        with patch.object(run, "SEALED", sealed), patch.object(run, "STATEMENTS_RECIPIENT", recipient), \
             patch.object(run, "AGENT_STATE", []), patch.object(run, "pilot_homes", return_value=[]), \
             patch.object(run.RunArtifacts, "results_since", return_value=[]), patch("run_artifacts.processes.run", encrypt), \
             patch.object(r2_upload, "case_recipient", return_value=None):
            run.seal(c)
        search = sealed / (c.case_id + ".search.age")
        self.assertEqual(c.card["public_search"]["cipher_sha256"], hashlib.sha256(search.read_bytes()).hexdigest())
        self.assertNotIn("stock query", search.read_text())


if __name__ == "__main__": unittest.main()
