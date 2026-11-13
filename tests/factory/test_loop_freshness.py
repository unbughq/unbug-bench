"""Offline loop/G2 regression: an attacker appends a match after a clear G2 receipt."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

import run
import model_runtime
from router_test_support import offline_router
_ROUTING = offline_router()
from test_admission import evidence


class LoopFreshnessTests(unittest.TestCase):
    def setUp(self):
        from freshness_test_transport import start
        start(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        case = root / "case"
        (case / "scenarios/S1").mkdir(parents=True)
        for name in ("case.json", "answer-key.json", "scenarios/S1/key.json"):
            (case / name).write_text("{}")
        (case / "case.json").write_text(json.dumps({"app": {"commit": "v2.19.0"}}))
        (case / "statement.md").write_text("Synthetic stock bug, pinned to 2.19.0")
        (case / "disclosure.md").write_text("Synthetic disclosure")
        self.c = types.SimpleNamespace(case=case, work=root, case_id="case-synthetic", card={},
            models={"builder": ["claude/writer"], "attacker": ["deepseek/tester"],
                    "reviewers": [["minimax/reviewer"]]}, manifest0="synthetic",
            args=types.SimpleNamespace(resume="synthetic", dry_run=False, source="hunt",
                                       rounds=3, skip_build=False, agent_timeout=30, runs=1, scenario_runs=1))
        self.rows = [evidence("builder", kind, i) for kind in ("web", "github") for i in range(3)]
        self.rows += [evidence("attacker", "web", i) for i in range(2)]
        self.save_rows()
        self.assertTrue(run.g2(self.c)[0])
        self.old_receipt = (root / "public-search.json").read_bytes()
        self.match = evidence("attacker", "github", 17034, ambiguous=True,
            url="https://github.com/medusajs/medusa/discussions/17034",
            note="Possible public match at the pinned version; independent verdict required")
        self.request = ("Obtain an independent reviewer verdict on same_bug/version_scope for "
                        + self.match["url"] + "; do not delete the rows.")
        self.calls = []
        self.same_bug = False
        self.extra = []
        self.complete = True
        self.report_blocking = None
        self.log_match = True
        self.requested_urls = None
        self.reviewed_rows = []
        self.answer_limit = None
        for name, value in (("engine_prepare_bench", None), ("early_review", None)):
            patch.object(run, name, return_value=value).start()
        self.addCleanup(patch.stopall)

    def save_rows(self):
        (self.c.case / "freshness.jsonl").write_text("\n".join(map(json.dumps, self.rows)))

    def model(self, c, models, text, cwd, name, **kwargs):
        self.calls.append(name)
        if name.startswith("attacker-"):
            context = json.loads(text.split("```json\n")[-1].split("```")[0])
            first = name == "attacker-1"
            if first and self.log_match:
                self.rows.append(self.match)
                self.save_rows()
            pathlib.Path(context["report_path"]).write_text(json.dumps({
                "complete": self.complete if first else True,
                "blocking": ([self.request, *self.extra] if self.report_blocking is None else self.report_blocking) if first else [],
                "freshness_review": (self.requested_urls or [self.match["url"]]) if first else [],
                "non_blocking": ["Inspection is not a gate pass"],
                "cheats_tried": [{"name": "cap-thirteen", "idea": "Hard-coded stock cap", "passed": True}],
                "searches": len(self.rows)}))
        elif name == "reviewer-g2-confirm":
            rows = (json.loads(text.split('results as possible public mentions of the bug:\n\n')[1].split('\n\nOpen each URL.')[0])
                    if text else [self.match])  # metered-call stub tests transport separately
            self.reviewed_rows = rows
            answers = [{"url": row["url"], "resolved": self.same_bug is not None,
                      "same_bug": self.same_bug, "retrieved": self.same_bug is not None,
                      "app_version": "2.19.0", "version_scope": "Synthetic applicability checked",
                      "why": "Synthetic independent evidence"} for row in rows]
            (pathlib.Path(cwd) / "verdict.json").write_text(json.dumps({"hits": answers[:self.answer_limit]}))
        else:
            self.fail("Unexpected call: " + name)
        return 0

    def categories(self, c, number, report, receipt, completed):
        # Category execution has its own durable tests; author one synthetic report
        # here to exercise the real scientific report/freshness checks.
        run.opencode(c, c.models["attacker"], run.stress_request(c, number, report),
                     c.case, f"attacker-{number}")
        completed()

    def loop(self):
        with patch.object(run, "opencode", self.model), \
             patch.object(run, "stress_categories", self.categories):
            self.result = run.engine_stress_round(self.c, 1)
        return self.result

    def assert_feedback(self, expected):
        self.assertEqual(self.result["reason"], "stress:findings")
        problems, report = run._feedback_input(self.c, self.result["feedback"])
        self.assertEqual(problems, expected)
        self.assertEqual(run.attack_report(report)["blocking"], expected)

    def test_exclusion_sends_only_real_blockers_as_writer_feedback(self):
        self.extra = ["Wrong fix passes because every test customer shares one email domain"]
        self.loop()
        self.assertEqual(self.calls, ["attacker-1", "reviewer-g2-confirm"])
        self.assert_feedback(self.extra)
        original = run.attack_report(self.c.work / "attacks/round-1.json")
        self.assertEqual(original["blocking"], [self.request, *self.extra])
        self.assertEqual(self.c.card["loop_freshness"]["outcome"], "excluded")
        self.assertEqual(self.c.card["loop_freshness"]["rows"], 1)

    def test_freshness_only_exclusion_finishes_clean(self):
        self.loop()
        self.assertEqual(self.calls, ["attacker-1", "reviewer-g2-confirm"])
        self.assertEqual(self.c.card["stress_review"]["status"], "completed")
        self.assertEqual(self.result["reason"], "stress:clean")
        self.assertNotIn("feedback", self.result)

    def test_structured_freshness_request_is_checked_without_blockers(self):
        self.report_blocking = []
        self.loop()
        self.assertEqual(self.calls, ["attacker-1", "reviewer-g2-confirm"])

    def test_structured_request_absent_from_search_rows_is_reviewed(self):
        self.report_blocking = []
        self.log_match = False
        self.loop()
        self.assertEqual(self.calls, ['attacker-1', 'reviewer-g2-confirm'])
        self.assertEqual(self.reviewed_rows[0]['url'], self.match['url'])
        self.assertEqual(self.reviewed_rows[0]['app_version'], '2.19.0')
        self.assertEqual(self.c.card['loop_freshness']['rows'], 1)

    def unflagged_requests(self):
        self.log_match = False
        self.requested_urls = ['https://github.com/medusajs/medusa/pull/17431',
                               'https://github.com/medusajs/medusa/issues/12913']
        self.rows += [evidence(who, 'github', i, url=url, app_version='9.99.0',
                               note=f'Non-hit evidence from {who}')
                      for i, (who, url) in enumerate(zip(('builder', 'attacker'), self.requested_urls))]
        self.save_rows()
        self.assertTrue(all(row['hit'] is False and not row.get('ambiguous') for row in self.rows))
        self.extra = ['Wrong fix cap-thirteen passes; vary the stock and customer data']
        self.report_blocking = ['[freshness-review] independent verdict required', *self.extra]

    def test_real_attacker_schema_unflagged_requests_reach_reviewer_then_feedback(self):
        self.unflagged_requests()
        self.loop()
        self.assertEqual(self.calls, ['attacker-1', 'reviewer-g2-confirm'])
        self.assert_feedback(self.extra)
        original = run.attack_report(self.c.work / 'attacks/round-1.json')
        self.assertEqual(set(original), {'complete', 'blocking', 'unfinished_validation', 'non_blocking', 'freshness_review', 'cheats_tried', 'searches'})
        self.assertEqual(original['freshness_review'], self.requested_urls)
        self.assertEqual([row['url'] for row in self.reviewed_rows], self.requested_urls)
        for row, who in zip(self.reviewed_rows, ('builder', 'attacker')):
            self.assertIn(f'Non-hit evidence from {who}', row['note'])
            self.assertIn('stock query', row['query'])
            self.assertEqual(row['app_version'], '2.19.0')  # metadata, not searcher's version
        info = self.c.card['loop_freshness']
        self.assertEqual(info['rows'], 2)
        self.assertEqual(info['requested'], 2)
        self.assertEqual(info['outcome'], 'excluded')
        self.assertEqual(info['reason'], 'all_excluded')
        self.assertTrue((self.c.work / info['verdict_path']).is_file())


    def test_unflagged_requests_confirmed_match_fails_G2(self):
        self.unflagged_requests()
        self.same_bug = True
        self.assertEqual(self.loop()['reason'], 'stress:public_match')
        self.assertNotIn("feedback", self.result)
        self.assertEqual(self.calls, ['attacker-1', 'reviewer-g2-confirm'])
        self.assertEqual(self.c.card['failed_gate'], 'G2')
        self.assertEqual(self.c.card['gates']['G2'], 'fail')

    def test_unflagged_requests_same_family_has_explicit_reason(self):
        self.unflagged_requests()
        self.c.models['reviewers'] = [['deepseek/other']]
        with self.assertRaisesRegex(run.BudgetError, '^freshness_unresolved$'):
            self.loop()
        self.assertEqual(self.calls, ['attacker-1'])
        self.assertEqual(self.c.card['loop_freshness'], {
            'rows': 2, 'requested': 2, 'verdict_path': None, 'outcome': 'unresolved',
            'reason': 'same_family_reviewer'})


    def test_flagged_and_requested_rows_share_one_review(self):
        self.unflagged_requests()
        self.rows.append(self.match)
        self.save_rows()
        # Repeated requests must not duplicate an existing flagged row.
        self.requested_urls += [self.match['url'], self.requested_urls[0]]
        report = self.c.work / 'report.json'
        report.write_text(json.dumps({'complete': True, 'blocking': self.report_blocking,
                                     'freshness_review': self.requested_urls}))
        with patch.object(run, 'opencode', self.model):
            result, _ = run.loop_freshness(self.c, run.attack_report(report), report)
        self.assertEqual(result['blocking'], self.extra)
        self.assertEqual(self.calls.count('reviewer-g2-confirm'), 1)
        self.assertEqual([row['url'] for row in self.reviewed_rows], [self.match['url'], *self.requested_urls[:2]])
        self.assertEqual(self.c.card['loop_freshness']['requested'], 3)

    def test_budget_boundary_records_why_reviewer_cannot_run(self):
        self.unflagged_requests()
        report = self.c.work / 'report.json'
        report.write_text(json.dumps({'complete': True, 'blocking': self.report_blocking,
                                     'freshness_review': self.requested_urls}))
        with patch.object(run, 'case_budget_boundary', side_effect=run.BudgetError('budget_exhausted')), \
             patch.object(run, 'opencode') as model, self.assertRaisesRegex(run.BudgetError, '^budget_exhausted$'):
            run.loop_freshness(self.c, run.attack_report(report), report)
        model.assert_not_called()
        self.assertEqual(self.c.card['loop_freshness']['reason'], 'budget_boundary:budget_exhausted')
        self.assertIsNone(self.c.card['loop_freshness']['verdict_path'])

    def test_tagged_request_is_removed_after_exclusion(self):
        self.request = '[freshness-review] independent verdict required'
        self.loop()
        self.assertEqual(self.calls, ["attacker-1", "reviewer-g2-confirm"])

    def test_incomplete_review_cannot_pass_after_freshness_exclusion(self):
        self.complete = False
        from durable.contract import Outcome
        self.assertEqual(self.loop(), {"outcome": Outcome.INFRA_ERROR,
                                       "reason": "stress:interrupted_review"})
        self.assertNotEqual(self.c.card.get("stress_review", {}).get("status"), "completed")
        self.assertEqual(self.calls, ["attacker-1", "reviewer-g2-confirm"])

    def test_malformed_independent_verdict_is_terminal(self):
        def call(c, models, text, cwd, name, **kwargs):
            if name == 'reviewer-g2-confirm':
                self.calls.append(name)
                (pathlib.Path(cwd) / 'verdict.json').write_text('{"hits": [{"same_bug": false}]}')
                return 0
            return self.model(c, models, text, cwd, name, **kwargs)
        with patch.object(run, 'opencode', call), \
             patch.object(run, 'stress_categories', self.categories), \
             self.assertRaisesRegex(run.BudgetError, '^freshness_unresolved$'):
            run.engine_stress_round(self.c, 1)
        self.assertEqual(self.calls, ["attacker-1", "reviewer-g2-confirm"])

    def test_reviewer_cost_uses_existing_metered_call_path(self):
        c = self.c
        c.ledger = c.work / 'budget.json'
        c.ledger.write_text('{"cost": 0, "events": [], "calls": 0}')
        for name, value in dict(max_cost=10, max_role_calls=20, max_total_calls=50,
                                no_progress_minutes=5, max_zero_tokens=2, case_budget=50).items():
            setattr(c.args, name, value)
        real_opencode = run.opencode
        def budgeted(cmd, cwd, env, transcript, ledger, timeout, **kwargs):
            self.assertEqual(kwargs['role'], 'reviewer')
            self.assertEqual(kwargs['invocation_name'], 'reviewer-g2-confirm')
            self.assertEqual(kwargs['configured_model'], 'minimax/reviewer')
            self.model(c, c.models['reviewers'][0], '', cwd, 'reviewer-g2-confirm')
            ledger.write_text(json.dumps({'cost': 0.25, 'calls': 1, 'events': [{
                'cost': 0.25, 'role': kwargs['role'], 'invocation': kwargs['invocation_name'],
                'configured_model': kwargs['configured_model']}]}))
            return types.SimpleNamespace(returncode=0)
        def call(c, models, text, cwd, name, **kwargs):
            if name == 'reviewer-g2-confirm':
                return real_opencode(c, models, text, cwd, name, **kwargs)
            return self.model(c, models, text, cwd, name, **kwargs)
        with patch.object(run, 'opencode', call), patch.object(model_runtime, 'run_budgeted', budgeted), \
             patch.object(model_runtime, 'opencode_config', return_value=c.work / 'synthetic-config'), \
             patch.object(run, 'public_progress'), \
             patch.object(run, 'stress_categories', self.categories):
            run.engine_stress_round(c, 1)
        self.assertEqual(c.card['case_budget']['spent_usd'], 0.25)
        self.assertEqual(c.card['case_budget']['breakdown_by_role'], {'reviewer': 0.25})

    def test_confirmed_match_fails_G2_without_repair_feedback(self):
        self.same_bug = True
        self.assertEqual(self.loop()['reason'], 'stress:public_match')
        self.assertNotIn("feedback", self.result)
        self.assertEqual(self.calls, ["attacker-1", "reviewer-g2-confirm"])
        self.assertEqual(self.c.card["failed_gate"], "G2")
        self.assertEqual(self.c.card["gates"]["G2"], "fail")


    def test_same_family_reviewer_fails_closed(self):
        for family in ("claude/other", "deepseek/other"):
            with self.subTest(family=family):
                self.c.models["reviewers"] = [[family]]
                self.calls.clear()
                with self.assertRaisesRegex(run.BudgetError, "^freshness_unresolved$"):
                    self.loop()
                self.assertEqual(self.calls, ["attacker-1"])

    def test_budget_boundary_precedes_independent_review(self):
        self.c.ledger = self.c.work / "budget.json"
        self.c.ledger.write_text('{"cost": 50, "events": []}')
        self.rows.append(self.match)
        self.save_rows()
        with patch.object(run, "opencode") as model, self.assertRaisesRegex(run.BudgetError, "budget_exhausted"):
            run.confirm_hits(self.c, [self.match])
        model.assert_not_called()

    def test_later_G2_reuses_only_unchanged_rows_and_disclosure(self):
        self.loop()
        self.assertEqual((self.c.work / "public-search.json").read_bytes(), self.old_receipt)
        with patch.object(run, "opencode", self.model):
            self.assertTrue(run.g2(self.c)[0])
            self.assertEqual(self.calls.count("reviewer-g2-confirm"), 1)
            self.match["note"] += "; new evidence"
            self.save_rows()
            self.assertTrue(run.g2(self.c)[0])
            self.assertEqual(self.calls.count("reviewer-g2-confirm"), 2)
            (self.c.case / "disclosure.md").write_text("Changed disclosure")
            self.assertTrue(run.g2(self.c)[0])
            self.assertEqual(self.calls.count("reviewer-g2-confirm"), 3)

    def test_changed_flagged_row_set_requires_new_verdict(self):
        self.loop()
        extra = {**self.match, 'query': 'Another independent search for the same discussion'}
        self.rows.append(extra)
        self.save_rows()
        # A one-answer verdict cannot resolve two rows, even at the same URL.
        self.answer_limit = 1
        with patch.object(run, 'opencode', self.model):
            ok, info = run.g2(self.c)
        self.assertFalse(ok)
        self.assertEqual(info['unresolved_hits'], 2)
        self.assertEqual(self.calls.count('reviewer-g2-confirm'), 2)

    def test_tampered_retained_verdict_cannot_clear_hits(self):
        self.loop()
        receipt_path = self.c.work / 'freshness-verdict.json'
        receipt = json.loads(receipt_path.read_text())
        receipt['hits'] = [{'same_bug': False}]
        receipt_path.write_text(json.dumps(receipt))
        self.same_bug = None
        with patch.object(run, 'opencode', self.model):
            ok, info = run.g2(self.c)
        self.assertFalse(ok)
        self.assertEqual(info['outcome'], 'review_unresolved')
        self.assertEqual(self.calls.count('reviewer-g2-confirm'), 2)

    def test_mixed_freshness_and_quality_finding_is_retained(self):
        self.request += " Also fix test customers sharing an email domain."
        self.loop()
        self.assert_feedback([self.request])

    def test_optional_report_field_preserves_legacy_schema(self):
        path = self.c.work / "report.json"
        for value, valid in ((None, True), ([], True), ([self.match["url"]], True), ("url", False), ([{}], False)):
            with self.subTest(value=value):
                report = {"complete": True, "blocking": []}
                if value is not None: report["freshness_review"] = value
                path.write_text(json.dumps(report))
                parsed = run.attack_report(path)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed.get('freshness_review_malformed', False), not valid)

    def test_request_note_is_forwarded_for_an_existing_flagged_row(self):
        self.requested_urls = [{'url': self.match['url'], 'note': 'Attacker asks about version-specific cancellation semantics'}]
        self.loop()
        self.assertEqual(self.calls, ['attacker-1', 'reviewer-g2-confirm'])
        self.assertIn('version-specific cancellation semantics', self.reviewed_rows[0]['note'])
        self.assertIn(self.match['note'], self.reviewed_rows[0]['note'])

    def pin_by_sha(self):
        # 1110b: the port stage pins the app by commit SHA with no version field.
        (self.c.case / "case.json").write_text(json.dumps({"app": {
            "repo": "https://github.com/medusajs/medusa", "commit": "0123456789abcdef" * 2 + "01234567",
            "lockfile_sha256": "0" * 64, "image": "synthetic"}}))
        self.log_match = False
        self.extra = ['Wrong fix cap-thirteen passes; vary the stock and customer data']
        self.report_blocking = ['[freshness-review] independent verdict required', *self.extra]

    def test_sha_pinned_case_takes_the_version_its_search_rows_agree_on(self):
        self.pin_by_sha()
        self.loop()
        self.assertEqual(self.calls, ['attacker-1', 'reviewer-g2-confirm'])
        self.assertEqual(self.reviewed_rows[0]['app_version'], '2.19.0')
        self.assert_feedback(self.extra)

    def test_sha_pinned_case_with_disagreeing_rows_stays_unresolved(self):
        self.pin_by_sha()
        self.rows.append(evidence('builder', 'web', 99, app_version='2.18.0'))
        self.save_rows()
        with self.assertRaisesRegex(run.BudgetError, '^freshness_unresolved$'):
            self.loop()
        self.assertEqual(self.calls, ['attacker-1'])
        self.assertEqual(self.c.card['loop_freshness']['reason'], 'pinned_version_unknown')


if __name__ == "__main__":
    unittest.main()
