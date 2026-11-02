"""Saved practice/5813be and saved HTTP bytes; authored transport/reviewer controls."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'factory'), str(ROOT/'bin'), str(ROOT/'tests/factory')]
import budget
import diagnosis
import extension_compare as comparison
import extension_evaluator
import extension_package as package
import extension_public_match as public
import extensions
import freshness_retrieval
import gate_state
import registry
import run
import test_scientific_receipts as artifacts
import test_stream_d_execution as execution
import test_stream_d_runtime as runtime

REAL_FRESHNESS = run.loop_freshness


class PublicMatchTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    snapshot = execution.ExecutionTests.snapshot
    diagnosis = execution.ExecutionTests.diagnosis

    def setUp(self):
        execution.ExecutionTests.setUp(self)
        # Real admitted writer/stress round, external output controls are inherited.
        run.write_and_attack(self.c, self.prev, extension_id=1)
        self.report = self.work/'attacks/round-9.json'
        self.http = artifacts.fixture('invalid-runs-http.json.gz')
        self.assertEqual(hashlib.sha256(self.http['body'].encode()).hexdigest(), self.http['sha256'])
        rows = [json.loads(line) for line in (self.case/'freshness.jsonl').read_text().splitlines() if line]
        for row in rows: row.update(at=datetime.now(timezone.utc).isoformat(), hit=False, ambiguous=False)
        rows[0].update(url=self.http['url'], hit=True)
        (self.case/'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        self.rows = rows
        self.matches = True
        self.fetches, self.reviews = [], []
        def fetch(url, **kwargs):
            self.fetches.append(url)
            return {'url':url, 'final_url':url, 'status':200}, self.http['body'].encode()
        def review(c, chain, text, directory, name, out, *args, **kwargs):
            self.reviews.append(name)
            hits = [dict(url=row['url'], app_version=row['app_version'], resolved=True,
                retrieved=True, same_bug=self.matches, version_scope='Authored pinned-release applicability',
                why='Authored independent same-bug judgment') for row in self.rows if row['hit']]
            registry.atomic_json(out, {'hits':hits})
        self.patch(freshness_retrieval, 'fetch', fetch)
        self.patch(run, 'retained_answer', review)
        self.before = budget.case_spending(json.loads(self.ledger.read_text()))['total_spent_usd']

    def confirm(self):
        with public.capture(self.c, run, self.row):
            with self.assertRaisesRegex(budget.BudgetError, '^freshness_public_match$'):
                REAL_FRESHNESS(self.c, run.attack_report(self.report), self.report)
        self.assertFalse(hasattr(self.c, 'extension_public_match_recorder'))
        self.assertEqual(len(self.reviews), 1)

    def complete(self):
        self.assertTrue(public.complete(self.c, run, self.row))
        row = extensions.read(self.c)[-1]
        self.assertTrue(public.verified(self.c, run, row))
        self.assertEqual(row['outcome']['stages'][0]['status'], 'fail')
        self.assertTrue(all(stage['status']=='unreached' for stage in row['outcome']['stages'][1:]))
        self.assertEqual(row['outcome']['frontier'], 0)
        self.assertEqual(budget.case_spending(json.loads(self.ledger.read_text()))['total_spent_usd'], self.before)
        return row

    def test_confirmed_http_proof_completes_and_replays_without_any_execution(self):
        self.confirm(); row = self.complete()
        retained = extensions.tree(self.work/'extension-snapshots/1/outcome')
        bodies = [self.work/'extension-snapshots/1/outcome/evidence'/name
                  for name in row['outcome']['evidence'] if name.endswith('.body')]
        self.assertTrue(bodies)
        self.assertTrue(all(path.read_bytes()==self.http['body'].encode() for path in bodies))
        calls, ledger = list(self.calls), self.ledger.read_bytes()
        with patch.object(run, 'write_and_attack', side_effect=AssertionError('writer/stress replay')), \
             patch.object(run, 'run_gates', side_effect=AssertionError('gates replay')), \
             patch.object(run, 'retained_answer', side_effect=AssertionError('review replay')), \
             patch.object(freshness_retrieval, 'fetch', side_effect=AssertionError('retrieval replay')):
            for _ in range(2):
                self.assertTrue(public.verified(self.c, run, row))
                with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'): public.stop(self.c, row)
                self.assertEqual(self.c.card['gates'], {'G2':'fail'})
                self.assertEqual(self.c.card['loop_freshness']['outcome'], 'public_match')
        self.assertEqual(self.calls, calls); self.assertEqual(self.ledger.read_bytes(), ledger)
        self.assertEqual(extensions.tree(self.work/'extension-snapshots/1/outcome'), retained)

    def test_package_recovers_and_next_diagnosis_retires_without_evaluator(self):
        self.confirm()
        calls, ledger = list(self.calls), self.ledger.read_bytes()
        with patch.object(run, 'write_and_attack', side_effect=AssertionError('paid writer/stress')), \
             patch.object(run, 'run_gates', side_effect=AssertionError('gates')), \
             patch.object(extension_evaluator, 'Evaluator', side_effect=AssertionError('paid comparison')), \
             patch.object(freshness_retrieval, 'fetch', side_effect=AssertionError('retrieval')):
            for _ in range(2):
                with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'):
                    package.run(self.c, run, self.prev, 1)
                package.completed_route(self.c, extensions.read(self.c)[-1])
            self.c.stopped = True
            self.c.exhaustion_occurred = True
            self.c.card['terminal_stop'] = 'extension_incomplete'
            run.finalize_accounting(self.c)
            state = copy.deepcopy(self.c.card['diagnosis_state'])
            run.finalize_accounting(self.c)
            self.assertEqual(self.c.card['diagnosis_state'], state)
            self.assertEqual(state['status'], 'pending')
            self.diagnosis()
            with self.assertRaisesRegex(budget.BudgetError, '^retired_no_progress$'):
                package.subsequent_entry(self.c, run)
        self.assertEqual(self.calls, calls)
        # finalize_accounting may publish accounting, but replays bought no work.
        self.assertEqual(budget.case_spending(json.loads(self.ledger.read_text()))['total_spent_usd'], self.before)

    def test_live_confirmation_is_captured_by_package_before_terminal_stop(self):
        # Resume directly at the real freshness callback after the saved stress
        # receipt; this controls only the writer/stress handoff timing.
        def handoff(*args, **kwargs):
            return REAL_FRESHNESS(self.c, run.attack_report(self.report), self.report)
        self.c.card['gate_continuation'] = {'stale': True}
        registry.atomic_json(self.work/'gate-continuation.json', {'stale': True})
        with patch.object(run, 'write_and_attack', side_effect=handoff), \
             patch.object(run, 'run_gates', side_effect=AssertionError('gates after match')):
            with self.assertRaisesRegex(budget.BudgetError, '^extension_incomplete$'):
                package.run(self.c, run, self.prev, 1)
        row = extensions.read(self.c)[-1]
        self.assertTrue(public.verified(self.c, run, row))
        self.assertNotIn('gate_continuation', self.c.card)
        self.assertFalse((self.work/'gate-continuation.json').exists())
        self.assertEqual(len(self.reviews), 1)

    def test_intent_before_confirmation_kill_reuses_completed_reviewer_receipt(self):
        original = registry.atomic_json
        def killed(path, value):
            if path == self.work/'freshness-verdict.json': raise runtime.Killed()
            return original(path, value)
        with public.capture(self.c, run, self.row), patch.object(registry, 'atomic_json', side_effect=killed):
            with self.assertRaises(runtime.Killed):
                REAL_FRESHNESS(self.c, run.attack_report(self.report), self.report)
        self.assertFalse(public.complete(self.c, run, self.row))
        self.assertEqual(len(self.reviews), 1)
        # The normal interrupted-call checkpoint retains the verdict location.
        registry.atomic_json(self.work/'scorecard.json', self.c.card)
        self.confirm()
        self.complete()
        self.assertEqual(len(self.reviews), 1)

    def test_intent_without_confirmation_stays_open(self):
        with public.capture(self.c, run, self.row):
            self.c.extension_public_match_recorder(self.c, [self.rows[0]], self.report)
        self.assertFalse(public.complete(self.c, run, self.row))
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        self.assertEqual(self.reviews, [])

    def test_cache_before_package_completion_recovers_without_confirming_again(self):
        self.confirm()
        with patch.object(run, 'loop_freshness', side_effect=AssertionError('confirmation rerun')):
            self.complete()
        self.assertEqual(len(self.reviews), 1)

    def test_source_model_slot_seed_and_card_drift_preserve_proof(self):
        self.confirm()
        self.c.factory_slot=7; self.c.seed=93
        self.c.models={'builder':['other/writer'], 'attacker':['other/stress'], 'reviewers':[['other/reviewer']]}
        self.c.card.update(stress_review={'status':'unresolved'}, loop_freshness={'changed':True})
        with patch.object(gate_state, 'scientific_version', side_effect=AssertionError('new versions')):
            self.complete()

    def test_outcome_rename_before_history_retries_identical_bytes_on_new_slot(self):
        self.confirm()
        original = extensions._write
        def killed(c, history):
            if history[-1]['outcome'] is not None: raise runtime.Killed()
            return original(c, history)
        with patch.object(extensions, '_write', side_effect=killed):
            with self.assertRaises(runtime.Killed): public.complete(self.c, run, self.row)
        root=self.work/'extension-snapshots/1/outcome'; retained=extensions.tree(root)
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        self.c.factory_slot=11; self.c.seed=911; self.c.card['loop_freshness']={'new':True}
        with patch.dict('os.environ', UNBUG_FACTORY_SLOT='new-slot'):
            self.complete()
        self.assertEqual(extensions.tree(root), retained)
        self.assertEqual(len(self.reviews), 1)

    def test_absent_and_superseded_intent_do_not_score(self):
        self.assertFalse(public.complete(self.c, run, self.row))
        self.confirm()
        self.report.rename(self.report.with_name('round-9-superseded-authored.json'))
        self.report.write_text('{"complete":false,"blocking":["review incomplete"]}')
        self.assertFalse(public.complete(self.c, run, self.row))
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_report_case_receipt_and_intent_tampering_refuse(self):
        self.confirm()
        paths=[self.report, self.case/'freshness.jsonl', self.work/'attack-state.json',
               self.report.with_suffix('.public-match.json')]
        for path in paths:
            saved=path.read_bytes(); path.write_bytes(saved+b'\n ' if path==self.case/'freshness.jsonl' else b'{}')
            with self.subTest(path=path):
                with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
                    public.complete(self.c, run, self.row)
            path.write_bytes(saved)
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_missing_completion_and_changed_http_body_never_reroll(self):
        self.confirm()
        confirmation=json.loads((self.work/'freshness-verdict.json').read_text())
        root=self.work/Path(confirmation['verdict_path']).parent
        for path in (root/'review-completed.json', next((root/'retrieval').glob('*.body')), root/'verdict.json'):
            saved=path.read_bytes(); path.unlink()
            with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
                public.complete(self.c, run, self.row)
            path.write_bytes(saved)
        self.assertEqual(len(self.reviews),1)
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_exclusion_is_not_a_public_match_terminal(self):
        self.matches=False
        with public.capture(self.c, run, self.row):
            REAL_FRESHNESS(self.c, run.attack_report(self.report), self.report)
        self.assertFalse(public.complete(self.c, run, self.row))
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])

    def test_mixed_confirmed_and_unresolved_rows_preserve_open_history(self):
        self.rows[1].update(hit=True, url='https://example.com/unresolved-public-reference')
        (self.case/'freshness.jsonl').write_text('\n'.join(map(json.dumps, self.rows)))
        def mixed(c, chain, text, directory, name, out, *args, **kwargs):
            self.reviews.append(name)
            hits = [dict(url=row['url'], app_version=row['app_version'], resolved=index == 0,
                retrieved=True, same_bug=True if index == 0 else None,
                version_scope='Authored applicability control', why='Authored mixed judgment')
                for index, row in enumerate(row for row in self.rows if row['hit'])]
            registry.atomic_json(out, {'hits': hits})
        with patch.object(run, 'retained_answer', side_effect=mixed):
            self.confirm()
        self.assertFalse((self.work/'freshness-verdict.json').exists())
        self.assertFalse(public.complete(self.c, run, self.row))
        self.assertIsNone(extensions.read(self.c)[-1]['outcome'])
        self.assertEqual(self.c.card['loop_freshness']['outcome'], 'public_match')

    def test_capture_is_scoped_and_different_rows_cannot_rewrite_intent(self):
        with public.capture(self.c, run, self.row):
            self.c.extension_public_match_recorder(copy.copy(self.c), [self.rows[0]], self.report)
            self.assertFalse(self.report.with_suffix('.public-match.json').exists())
            self.c.extension_public_match_recorder(self.c, [self.rows[0]], self.report)
            saved=self.report.with_suffix('.public-match.json').read_bytes()
            with self.assertRaisesRegex(budget.BudgetError,'^extension_snapshot_changed$'):
                self.c.extension_public_match_recorder(self.c, [{**self.rows[0],'note':'different'}], self.report)
        self.assertEqual(self.report.with_suffix('.public-match.json').read_bytes(), saved)

    def test_retained_proof_tamper_and_symlinks_refuse(self):
        self.confirm(); row=self.complete()
        root=self.work/'extension-snapshots/1/outcome/evidence'
        name='comparison-support/stress/'+public.marker(row)
        target=root/name; saved=target.read_bytes(); target.write_text('{}')
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
            public.verified(self.c, run, row)
        target.write_bytes(saved)
        target.unlink(); target.symlink_to(self.report)
        with self.assertRaisesRegex(budget.BudgetError, '^extension_snapshot_changed$'):
            public.verified(self.c, run, row)


if __name__=='__main__': unittest.main()
