"""Real public execution/card replays; no Docker, providers, SSH, Boat or decryption."""
import argparse
import copy
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import run
import calibration
import freshness_retrieval as retrieval
import gate_attempt
import admission
import fairness
from run_validity import classify, require_valid, retry, InvalidInfra, InfrastructureExhausted

FIXTURES = ROOT / 'tests/factory/fixtures'
def fixture(name): return json.loads(gzip.decompress((FIXTURES / name).read_bytes()))
REAL = fixture('invalid-runs-real.json.gz')
PRACTICE = fixture('invalid-runs-practice.json.gz')


def batch(label):
    files = REAL[label]['files']
    return files['checkpoint.json'], [files[n] for n in sorted(files) if Path(n).stem.isdigit()]


class InvalidRunsTests(unittest.TestCase):
    def setUp(self):
        bench = patch.object(run, 'BENCH', ROOT); bench.start(); self.addCleanup(bench.stop)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        case = self.work / 'case'; case.mkdir()
        for name, content in PRACTICE['files'].items():
            path = case / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
        self.c = SimpleNamespace(work=self.work, case=case, seed=42, case_id='case-practice', batch_deadline='2999-01-01T00:00:00Z',
            card={'gates': {}}, args=run.argument_parser().parse_args([]), stopped=False,
            models={'builder': ['claude/writer'], 'strong_calibrator': ['codex/solver'],
                    'easy_calibrator': ['glm/easy'], 'reviewers': [['deepseek/reviewer']]})
        self.c.args.runs = 3

    def test_rows_22_23_38_real_invalid_batches_never_produce_a_verdict(self):
        for label in ('reset-invalid', 'g11-mixed', 'guard-traffic-error', 'window-invalid'):
            summary, records = batch(label)
            self.assertEqual(classify(summary), 'invalid-infra', label)
            with self.assertRaises(InvalidInfra): require_valid(summary)
            if records:
                with self.assertRaises(InvalidInfra): run.verdicts(self.c, records)
        summary, records = batch('reset-invalid')
        with patch.object(run, 'checkpoint', return_value=(summary, records)):
            for tag in ('g6', 'g7'):
                with self.assertRaises(InvalidInfra):
                    run.cheat_runs(self.c, 42, tag, guards=[self.c.case / 'guards/reference'])
        with self.assertRaises(InvalidInfra):
            calibration.attempt_summary([{'solved': False, 'errors': 1, 'guard': 'public-practice'}])

    def test_valid_saved_scientific_results_do_not_change(self):
        (self.c.case / 'case.json').write_text(json.dumps(REAL['suffix-case']['files']['case.json']))
        # Old evaluator, replayed on identical public case metadata and raw trials.
        def old(records):
            meta = json.loads((self.c.case / 'case.json').read_text())
            rows = []
            for record in records:
                judge = record['judge']; clean = not record['errors'] and record['checker']['valid'] and not judge.get('invalid')
                violated = any(judge['paths'].get(p) for p in meta.get('promise_paths', []))
                broken = violated or any(not judge['checks'].get(k) for k in meta.get('promise_checks', []))
                rows.append({'clean': bool(clean), 'broken': bool(clean and broken),
                             'solved': bool(clean and not violated and all(judge['checks'].values()))})
            return rows
        for label in ('plain', 'reference', 'cheat'):
            summary, records = batch(label)
            self.assertEqual(classify(summary, records), 'valid')
            self.assertEqual(run.verdicts(self.c, records), old(records))

    def test_persistent_retry_bound_and_no_nested_retry_multiplication(self):
        journal = self.work / 'infra.json'; call = Mock(side_effect=InvalidInfra('private reset cause'))
        for _ in range(2):
            with self.assertRaises(InfrastructureExhausted): retry(journal, {'guard': 'same', 'seed': 42}, call)
        self.assertEqual(call.call_count, 2)
        outer = Mock(side_effect=InfrastructureExhausted('inner exhausted'))
        with self.assertRaises(InfrastructureExhausted): retry(journal, {'gate': 'G6'}, outer)
        self.assertEqual(outer.call_count, 1)
        self.assertNotIn('private reset cause', journal.read_text())

    def test_provider_waits_and_budget_interruptions_do_not_consume_infrastructure_retries(self):
        journal = self.work / 'infra.json'
        for _ in range(4):
            with self.assertRaises(run.BudgetError):
                retry(journal, {'gate':'G10'}, lambda: (_ for _ in ()).throw(run.BudgetError('provider_wait')),
                      interruption=run.BudgetError)
        self.assertEqual(retry(journal, {'gate':'G10'}, lambda: 'valid', interruption=run.BudgetError), 'valid')
        self.assertTrue(all(row['invalid_attempts'] == 0 for row in json.loads(journal.read_text()).values()))

    def test_checkpoint_retries_identical_real_execution_then_accepts_valid_evidence(self):
        from checkpoint_evidence import publish
        bad = self.work / 'bad'; bad.mkdir(); good = self.work / 'good'; good.mkdir()
        for directory, label in ((bad, 'reset-invalid'), (good, 'reference')):
            summary, records = batch(label)
            for number, row in enumerate(records, 1): (directory / f'{number:02}.json').write_text(json.dumps(row))
            (directory / 'checkpoint.json').write_text(json.dumps(summary))
        # The invalid batch's own receipt requests three runs; the valid operation
        # requests one, so the first receipt cannot authorize the current execution.
        processes = [subprocess.CompletedProcess([], 0, publish(bad, batch('reset-invalid')[0], 3), ''),
                     subprocess.CompletedProcess([], 0, publish(good, batch('reference')[0], 1), '')]
        with patch.object(run, 'sh', side_effect=processes) as shell, patch.object(run, 'case_budget_boundary'):
            result = run.checkpoint(self.c, [self.c.case / 'base'], self.c.case / 'guards/reference', 1, 42, 'replay')
        self.assertEqual(result[0]['error_runs'], 0)
        self.assertEqual(shell.call_args_list[0], shell.call_args_list[1])


    def test_pending_submission_survives_invalid_checkpoint_without_another_paid_call(self):
        import bench
        (self.c.case / 'case.json').write_text(json.dumps(REAL['suffix-case']['files']['case.json']))
        self.c.args.pilot_tries = self.c.args.pilot_runs = 1
        self.c.args.resume = None; self.c.pilot_passes = []
        home = self.work / 'pilot'; home.mkdir()
        def delivery(case, bench_root, ws, **kwargs):
            ws.mkdir(parents=True); (ws / 'promise.md').write_text(PRACTICE['files']['promise.md'])
        def shell(c, argv, **kwargs):
            if argv[:3] == ['sudo', 'cp', '-a'] and Path(argv[3]).exists(): shutil.copytree(argv[3], argv[4])
        def model(c, chain, text, dest, name, **kwargs):
            shutil.copytree(self.c.case / 'guards/reference', dest / 'guard')
        with patch.object(run, 'prepare_delivery', side_effect=delivery), patch.object(run, 'pilot_home', return_value=home), \
             patch.object(run, 'sh', side_effect=shell), patch.object(run, 'shred_tree', side_effect=lambda p, **kw: shutil.rmtree(p) if p.exists() else None), \
             patch.object(bench, 'reset'), patch.object(bench, 'load_scenario', return_value={}), \
             patch.object(run, 'model_call', side_effect=model) as paid, \
             patch.object(run, 'calibration_identity', return_value={'seed':42,'runs':1}):
            with patch.object(run, 'checkpoint', return_value=batch('reset-invalid')):
                with self.assertRaises(InvalidInfra): run.calibrate(self.c, 'easy_calibrator')
            self.assertFalse((self.work / 'easy_calibrator/results.json').exists())
            with patch.object(run, 'checkpoint', return_value=batch('reference')):
                result = run.calibrate(self.c, 'easy_calibrator')
            self.assertEqual(paid.call_count, 1)
            self.assertEqual(result['tries'], 1)
            self.assertEqual(result['solved'], 1)

    def test_g2_requires_real_retained_bytes_and_refuses_claim_only_answers(self):
        http = fixture('invalid-runs-http.json.gz')
        row = {'url': http['url'], 'app_version': '2.19.0'}
        answer = dict(url=row['url'], app_version='2.19.0', resolved=True, retrieved=True,
                      same_bug=False, version_scope='pinned public practice release', why='Different behavior')
        self.c.freshness_confirmed_hits = 0
        self.assertEqual(run.checked_freshness_verdict(self.c, [row], [answer]), [row])
        def fetched(url):
            return {'url':url, 'final_url':http['final_url'], 'status':200}, http['body'].encode()
        with patch.object(retrieval, 'fetch', side_effect=fetched): retrieval.retrieve([row], self.work / 'retrieval')
        self.c.freshness_retrieval = retrieval.load(self.work / 'retrieval', [row])
        self.assertEqual(run.checked_freshness_verdict(self.c, [row], [answer]), [])
        (self.work / 'retrieval/0-0.body').write_text('changed by reviewer')
        with self.assertRaises(InvalidInfra): retrieval.load(self.work / 'retrieval', [row])

    def test_g2_docs_shell_page_keeps_its_markdown_twin(self):
        # 1110a (18 Nov): docs.medusajs.com renders client-side; the reviewer needs the page's text twin.
        page = 'https://docs.medusajs.com/resources/references/medusa-workflows/createAndCompleteReturnOrderWorkflow'
        twin = page + '/index.html.md'
        answers = {page: (200, page, b'<div>Loading...</div>'), twin: (200, twin, b'# createAndCompleteReturnOrderWorkflow'),
                   'https://github.com/medusajs/medusa/issues/1': (200, 'https://github.com/medusajs/medusa/issues/1', b'issue')}
        def fetched(url, **kwargs):
            status, final, body = answers[url]
            return {'url': url, 'final_url': final, 'status': status}, body
        def urls(directory, row_url=page):
            receipt, = retrieval.retrieve([{'url': row_url}], self.work / directory, archive=False, access=True)
            self.assertEqual(receipt['retrieved_from'], 'live')
            return receipt, [r['url'] for r in receipt['responses']]
        with patch.object(retrieval, 'fetch', side_effect=fetched) as fetch:
            receipt, got = urls('docs')
            self.assertEqual(got, [page, twin])
            self.assertEqual([c['url'] for c in retrieval.judgment_projection([receipt])[0]['content']], [page, twin])
            self.assertFalse(retrieval.missing_twin(receipt))
            # An error body, a redirected twin or an HTML 200 is never kept as the page's text.
            for name, answer in (('wall', (403, twin, b'denied')), ('moved', (200, page + '/other.md', b'# other')),
                                 ('challenge', (200, twin, b'\xef\xbb\xbf <html>Checking your browser</html>'))):
                answers[twin] = answer
                receipt, got = urls(name)
                self.assertEqual(got, [page], name)
                self.assertFalse(retrieval.missing_twin(receipt), name)   # tried once; not refetched every cycle
                receipt.pop('twin_tried')   # a receipt saved before twins existed is refetched once
                self.assertTrue(retrieval.missing_twin(receipt), name)
            fetch.reset_mock()   # other hosts are fetched once, as before
            receipt, got = urls('gh', 'https://github.com/medusajs/medusa/issues/1')
            self.assertEqual(fetch.call_count, 1)
            self.assertFalse(retrieval.missing_twin(receipt))

    def test_g2_unflagged_model_retrieval_claims_cannot_clear_failed_fetches(self):
        rows = [json.loads(line) for line in PRACTICE['files']['freshness.jsonl'].splitlines() if line]
        for row in rows:
            row['at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            row['hit'] = row['ambiguous'] = False
        (self.c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        with patch.object(retrieval, 'fetch', side_effect=InvalidInfra('public transport failed')), \
             patch.object(run, 'opencode') as paid:
            ok, info = run.g2(self.c)
            self.assertFalse(ok)
            self.assertEqual(info['outcome'], 'evidence_incomplete')
            self.assertEqual(info['counted'], {'builder_web':0, 'builder_github':0, 'attacker':0})
            self.assertGreater(info['unfetched_searches'], 0)
        paid.assert_not_called()
        self.assertFalse((self.work / 'public-search.json').exists())

    def test_g2_unfetchable_unflagged_result_can_be_replaced_without_losing_history(self):
        rows = [json.loads(line) for line in PRACTICE['files']['freshness.jsonl'].splitlines() if line]
        for row in rows:
            row.update(at=datetime.datetime.now(datetime.timezone.utc).isoformat(), hit=False, ambiguous=False)
        path = self.c.case / 'freshness.jsonl'
        path.write_text('\n'.join(map(json.dumps, rows)))
        blocked = rows[0]['url']
        def fetch(url):
            if url == blocked: raise InvalidInfra('HTTP 403')
            return {'url':url, 'final_url':url, 'status':200}, b'public page'
        def topup(c, **kwargs):
            with path.open('a') as out:
                for index, row in enumerate(rows):
                    if row['url'] == blocked:
                        alternative = {**row, 'query':row['query'] + ' alternative',
                                       'url':f'https://github.com/medusajs/medusa/issues/{index + 100}'}
                        out.write('\n' + json.dumps(alternative))
        with patch.object(retrieval, 'fetch', side_effect=fetch), patch.object(run, 'freshness_topup', side_effect=topup) as repair:
            ok, info = run.ensure_freshness(self.c)
        self.assertTrue(ok); repair.assert_called_once()
        self.assertGreater(info['unfetched_searches'], 0)
        self.assertEqual(json.loads(path.read_text().splitlines()[0]), rows[0])

    def test_dead_unflagged_results_with_no_archive_never_count_as_searches(self):
        rows = [json.loads(line) for line in PRACTICE['files']['freshness.jsonl'].splitlines() if line]
        for row in rows:
            row.update(at=datetime.datetime.now(datetime.timezone.utc).isoformat(), hit=False, ambiguous=False)
        (self.c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        def fetch(url):
            status, body = (200, b'{"archived_snapshots":{}}') if url.startswith('https://archive.org/') else (404, b'')
            return {'url':url, 'final_url':url, 'status':status}, body
        with patch.object(retrieval, 'fetch', side_effect=fetch), patch.object(run, 'opencode') as paid:
            ok, info = run.g2(self.c)
        self.assertFalse(ok); self.assertEqual(info['outcome'], 'evidence_incomplete')
        self.assertEqual(info['counted'], {'builder_web':0, 'builder_github':0, 'attacker':0})
        self.assertEqual(info['unfetched_searches'], len(rows)); paid.assert_not_called()
        self.assertFalse((self.work / 'public-search.json').exists())

    def test_dead_flagged_result_clears_the_hit_but_never_fills_a_search_minimum(self):
        rows = [json.loads(line) for line in PRACTICE['files']['freshness.jsonl'].splitlines() if line]
        for row in rows:
            row.update(at=datetime.datetime.now(datetime.timezone.utc).isoformat(), hit=False, ambiguous=False)
        dead = rows[4]; dead['hit'] = True
        (self.c.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        # The real practice log contains exactly 3 builder web, 3 GitHub and 2
        # attacker queries. This unique dead GitHub URL cannot fill the third.
        self.assertEqual(run.freshness_counts(self.c), {'builder_web':3, 'builder_github':3, 'attacker':2})
        def fetch(url):
            if url == dead['url']: status, body = 404, b''
            elif url.startswith('https://archive.org/'): status, body = 200, b'{"archived_snapshots":{}}'
            else: status, body = 200, b'captured public response'
            return {'url':url, 'final_url':url, 'status':status}, body
        answer = dict(url=dead['url'], resolved=True, retrieved=False, same_bug=None,
            retrieved_from='none', archive_checked=True, archive_available=False,
            archive_snapshot_url=None, live_failure='http_404', app_version=dead['app_version'],
            version_scope='Pinned version checked', why='Runner verified HTTP 404 and no archive snapshot')
        def reviewer(c, chain, text, cwd, name, **kwargs):
            (Path(cwd) / 'verdict.json').write_text(json.dumps({'hits':[answer]}))
            return 0
        with patch.object(retrieval, 'fetch', side_effect=fetch), patch.object(run, 'opencode', side_effect=reviewer):
            ok, info = run.g2(self.c)
        self.assertFalse(ok); self.assertEqual(info['outcome'], 'evidence_incomplete')
        self.assertEqual(info['unreachable_hits'], 1); self.assertEqual(info['hits'], 0)
        self.assertEqual(info['counted'], {'builder_web':3, 'builder_github':2, 'attacker':2})
        self.assertEqual(info['unfetched_searches'], 1)
        self.assertFalse((self.work / 'public-search.json').exists())

    def test_missing_promised_observations_are_structural_writer_problems(self):
        (self.c.case / 'answer-key.json').unlink(missing_ok=True)
        for field, gate in (('promise_paths', 'G4'), ('promise_checks', 'G5')):
            meta = copy.deepcopy(REAL['suffix-case']['files']['case.json'])
            meta[field].append('writer_misspelled_observation')
            (self.c.case / 'case.json').write_text(json.dumps(meta))
            pipeline = run._gate_pipeline(); pipeline.early_gates = (gate,)
            pipeline.publish = Mock(); pipeline.log = Mock(); pipeline.saved_cheat_check = Mock()
            with patch.object(run, 'checkpoint', return_value=batch('reference')) as execute:
                problems = pipeline.early_checks(self.c)
            self.assertIn('writer_misspelled_observation', problems[0])
            execute.assert_called_once(); pipeline.saved_cheat_check.assert_not_called()
            self.assertFalse(self.c.stopped); self.assertNotIn('terminal_stop', self.c.card)
            with self.assertRaises(InvalidInfra): run.verdicts(self.c, batch('reset-invalid')[1])
        if not list((self.c.case / 'guards/cheats').glob('*')):
            shutil.copytree(ROOT / 'guards/refuse-all', self.c.case / 'guards/cheats/public-control')
        with patch.object(run, 'g3', return_value=(True, {})), \
             patch.object(run, 'checkpoint', return_value=batch('reference')) as execute:
            ok, info = admission.prototype(run, self.c)
        self.assertFalse(ok); self.assertIn('writer_misspelled_observation', info['problems'][0])
        execute.assert_called_once()


    def test_all_public_card_projections_change_only_explicit_silent_wrong_result(self):
        rows = fixture('invalid-runs-public-cards.json.gz') + fixture('20261029-real-public-cards.json.gz')
        changed = set()
        for row in rows:
            card = row['card']; before = copy.deepcopy(card)
            try:
                for summary in card.get('calibrators', {}).values(): calibration.require_summary_valid(summary)
            except InvalidInfra:
                changed.add(card['case'])
                self.assertEqual(card.get('gates', {}).get('G10'), 'pass')
                self.assertEqual(card.get('difficulty'), 'hard')
            self.assertEqual(card, before)  # no old card is rewritten
        self.assertEqual(changed, {'case-20261017T125556Z-18681d'})

    def test_practice_s11_patch_preserves_declared_deadline_agreement(self):
        subprocess.run(['patch', '-p1', '-i', str(FIXTURES / 'invalid-runs-practice-s11.patch')],
                       cwd=self.c.case, check=True, capture_output=True)
        scenario = json.loads((self.c.case / 'scenarios/S11-monitor-blind/scenario.json').read_text())
        descriptor = json.loads((self.c.case / 'harbor/practice/steps/S11/window.json').read_text())
        self.assertEqual(scenario['window']['duration_sec'], 120)
        self.assertEqual(scenario['window']['duration_sec'], descriptor['duration_sec'])
        self.assertEqual(scenario['window']['interval_sec'], descriptor['interval_sec'])
        self.assertEqual(classify(batch('window-invalid')[0]), 'invalid-infra')

    def test_row_36_real_prototype_invalidity_does_not_select_or_repair(self):
        guard = self.c.case / 'guards/cheats/public-control'
        if not list((self.c.case / 'guards/cheats').glob('*')):
            shutil.copytree(ROOT / 'guards/refuse-all', guard)
        self.c.card.update(candidate_attempts=2, builder_rounds=3)
        with patch.object(run, 'g3', return_value=(True, {})), \
             patch.object(run, 'checkpoint', return_value=batch('reset-invalid')) as checkpoint, \
             patch.object(run, 'opencode') as writer:
            with self.assertRaises(InfrastructureExhausted): admission.prototype(run, self.c)
            with self.assertRaises(InfrastructureExhausted): admission.prototype(run, self.c)
        self.assertEqual(checkpoint.call_count, 2)
        writer.assert_not_called()
        self.assertEqual((self.c.card['candidate_attempts'], self.c.card['builder_rounds']), (2, 3))

    def test_real_invalid_generic_probe_is_operational_and_valid_security_controls_stay_verified(self):
        stdout = REAL['negative-invalid']['files']['targeted-green.log']
        with patch.object(run, 'cheat_runs', return_value=(0, 1)), \
             patch.object(run, 'sh', return_value=subprocess.CompletedProcess([], 1, stdout, '')):
            with self.assertRaises(InvalidInfra): run.g6(self.c)
        self.assertNotIn('cheats_passed', self.c.card)
        controls = REAL['negative-controls']['files']['negative-tests.json']
        for name in ('raise-stock', 'checker-role-tamper', 'view-swap'):
            row = next(row for row in controls if row['probe'] == name)
            self.assertEqual(row['outcome'], 'rejected'); self.assertTrue(row['verified'])

    def test_negative_probe_cannot_claim_a_cheat_pass_from_a_mixed_invalid_batch(self):
        import runpy
        outcome = runpy.run_path(str(ROOT / 'bin/verify-negative'))['probe_outcome']
        summary, records = batch('g11-mixed')
        self.assertTrue(any(row['checker']['pass'] for row in records))
        self.assertEqual(outcome(summary, records, 'invalid')[0], 'invalid-probe')
        summary, records = batch('reference')
        self.assertEqual(outcome(summary, records, 'invalid')[0], 'cheat-pass')
        records[0]['traffic'] = {'message':'Updating Status from "ok" to "temp_failure" is not allowed.'}
        self.assertEqual(outcome(summary, records, 'invalid')[0], 'cheat-pass')

    def test_row_40_real_g11_runtime_failure_is_unknown(self):
        report = copy.deepcopy(next(iter(REAL['fake-pass-report']['files'].values())))
        guard = ROOT / 'guards/reference'; report['guards'][0]['guard'] = str(guard)
        path = self.work / 'fake-pass.json'; path.write_text(json.dumps(report))
        self.c.pilot_passes = [guard]
        (self.c.case / 'case.json').write_text(json.dumps(REAL['suffix-case']['files']['case.json']))
        with patch.object(run, 'sh', return_value=subprocess.CompletedProcess([], 0, 'Evidence: ' + str(path), '')), \
             patch.object(run, 'checkpoint', return_value=batch('g11-mixed')):
            with self.assertRaises(InvalidInfra): run.g11(self.c)
        self.assertNotIn('fake_pass', self.c.card)

    def test_g11_scanner_suspicion_requires_an_independent_runtime_adjudication(self):
        # Replay the real scanner's module-state finding as forbidden, reproducing
        # the old false-positive route. The scanner is not the adjudicator.
        report = copy.deepcopy(next(iter(REAL['fake-pass-report']['files'].values())))
        for name, content in REAL['suffix-case']['files'].items():
            path = self.c.case / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(content) if name == 'case.json' else content)
        guard = self.c.case / 'guards/reference'
        report['guards'][0]['guard'] = str(guard)
        report['guards'][0]['findings'][0]['severity'] = 'forbidden'
        path = self.work / 'fake-pass.json'; path.write_text(json.dumps(report))
        self.c.pilot_passes = [guard]; calls = []
        def reviewer(c, chain, text, cwd, name):
            calls.append(chain[0])
            Path(text.split('Write the JSON verdict to ')[1].removesuffix('.')).write_text(json.dumps(
                {'fixes':[{'classification':'checker_false_positive', 'findings_reviewed':[0],
                           'evidence':'The retained reference patch uses workflow state; case traffic and legitimate checks pass.'}]}))
            return 0
        with patch.object(run, 'sh', return_value=subprocess.CompletedProcess([], 0, 'Evidence: ' + str(path), '')), \
             patch.object(run, 'checkpoint', return_value=batch('g11-valid')), \
             patch.object(run, 'model_call', side_effect=reviewer):
            self.assertTrue(run.g11(self.c)[0])
            for batch_row in report['guards'][0]['runs']: batch_row['results_directory'] = '/different/generated/path'
            path.write_text(json.dumps(report))
            self.assertTrue(run.g11(self.c)[0])
        self.assertEqual(calls, ['deepseek/reviewer'])

    def attempt(self, folder='strong_calibrator'):
        (self.c.case / 'case.json').write_text(json.dumps(REAL['suffix-case']['files']['case.json']))
        workspace = self.work / folder / 'try-1'; workspace.mkdir(parents=True)
        shutil.copytree(ROOT / 'guards/refuse-all', workspace / 'guard')
        summary, records = batch('cheat')
        (workspace / 'execution.json').write_text(json.dumps({'summary':summary, 'records':records, 'seed':43, 'runs':1}))
        row = {'try':1, 'workspace':str(workspace), 'guard':str(workspace / 'guard'),
               'guard_submitted':True, 'solved':False, 'errors':0, 'checked_runs':1, 'solved_runs':0,
               'stop_reason':'completed',  # authored completion metadata on the real saved execution
               'identity':{'seed':42, 'runs':1}, 'artifacts':calibration.tree_digest(workspace)}
        calibration.atomic_results(workspace.parent / 'results.json', [row])
        self.c.args.runs = self.c.args.pilot_runs = 1
        self.c.card['calibrators'] = {'strong': {'solved':0, 'tries':1}}
        return workspace

    def test_row_41_repairs_execution_before_independent_review_without_rebuying_solver(self):
        workspace = self.attempt(); execution = json.loads((workspace / 'execution.json').read_text())
        execution['summary'], execution['records'] = batch('reset-invalid')
        (workspace / 'execution.json').write_text(json.dumps(execution))
        calls = []
        def reviewer(c, chain, text, cwd, name):
            calls.append(chain[0])
            out = Path(text.split('Write the JSON verdict to ')[1].removesuffix('.'))
            out.write_text(json.dumps({'tries':[{'try':1,'label':'wrong_fix',
                'finding':'Refuse-all rejects legitimate business operations', 'evidence':'attempts/try-1/execution.json'}]}))
            return 0
        with patch.object(run, 'model_call', side_effect=reviewer), \
             patch.object(run, 'calibrate') as paid_solver, patch.object(run, 'checkpoint', return_value=batch('cheat')) as execution_call:
            self.assertTrue(fairness.diagnose(self.c, run)[0])
        execution_call.assert_called_once(); paid_solver.assert_not_called()
        self.assertEqual(calls, ['deepseek/reviewer']); self.assertEqual(self.c.card['difficulty'], 'hard')

    def test_row_41_uses_next_independent_family_and_does_not_repeat_inconclusive_evidence(self):
        self.attempt()
        self.c.models['reviewers'].append(['minimax/reviewer'])
        calls = []
        def reviewer(c, chain, text, cwd, name):
            calls.append(chain[0])
            Path(text.split('Write the JSON verdict to ')[1].removesuffix('.')).write_text(
                json.dumps({'inconclusive':True, 'reason':'Cannot establish a concrete fix error'}))
            return 0
        with patch.object(run, 'model_call', side_effect=reviewer):
            for _ in range(2):
                with self.assertRaises(InfrastructureExhausted): fairness.diagnose(self.c, run)
        self.assertEqual(calls, ['deepseek/reviewer', 'minimax/reviewer'])
        self.assertNotIn('difficulty', self.c.card)

    def test_g16_independent_fallback_can_complete_a_valid_scientific_review(self):
        self.attempt('judge_breadth'); self.c.models['reviewers'].append(['minimax/reviewer'])
        calls = []
        def reviewer(c, chain, text, cwd, name):
            calls.append(chain[0])
            payload = ({'inconclusive':True, 'reason':'Need another independent assessment'} if len(calls) == 1 else
                {'tries':[{'try':1,'label':'wrong_fix','finding':'Refuse-all blocks legitimate operations',
                           'evidence':'attempts/try-1/execution.json'}]})
            Path(text.split('Write the JSON verdict to ')[1].removesuffix('.')).write_text(json.dumps(payload))
            return 0
        with patch.object(run, 'model_call', side_effect=reviewer), patch.object(run, 'make_pilots'), \
             patch.object(run, 'calibrate', return_value={'solved':0, 'tries':1}):
            self.assertTrue(fairness.breadth(self.c, run)[0])
            self.assertTrue(fairness.breadth(self.c, run)[0])
        self.assertEqual(calls, ['deepseek/reviewer', 'minimax/reviewer'])

    def test_g17_missing_fix_obtains_evidence_before_any_wrong_fix_review(self):
        workspace = self.attempt()
        path = workspace.parent / 'results.json'
        row = json.loads(path.read_text())[0]
        later = workspace.parent / 'try-2'; shutil.copytree(workspace, later)
        row2 = {**row, 'try':2, 'workspace':str(later), 'guard':str(later / 'guard'),
                'artifacts':calibration.tree_digest(later)}
        shutil.rmtree(workspace / 'guard')
        row.update(guard_submitted=False, stop_reason='time_limit')
        calibration.atomic_results(path, [row, row2])
        self.c.card['calibrators']['strong']['tries'] = 2
        def replacement(c, role, **kwargs):
            self.assertEqual(role, 'strong_calibrator'); self.assertEqual(kwargs['tries'], 1)
            target = self.work / kwargs['name'] / 'try-1'
            shutil.copytree(later, target)
            fixed = {**row2, 'try':1, 'workspace':str(target), 'guard':str(target / 'guard')}
            calibration.atomic_results(target.parent / 'results.json', [fixed])
            return {'solved':0, 'tries':1}
        def reviewer(c, chain, text, cwd, name):
            self.assertTrue((cwd / 'try-1/guard').is_dir())
            self.assertEqual(calibration.tree_digest(cwd / 'try-2'), calibration.tree_digest(later))
            Path(text.split('Write the JSON verdict to ')[1].removesuffix('.')).write_text(json.dumps(
                {'tries':[{'try':i, 'label':'wrong_fix', 'finding':'Refuse-all blocks legitimate operations',
                           'evidence':f'try-{i}/execution.json'} for i in (1, 2)]}))
            return 0
        with patch.object(run, 'calibrate', side_effect=replacement) as obtain, \
             patch.object(run, 'make_pilots'), patch.object(run, 'model_call', side_effect=reviewer) as review:
            self.assertTrue(fairness.diagnose(self.c, run)[0])
            migrated = json.loads(path.read_text()); migrated[0]['identity'] = {'migrated_policy': True}
            calibration.atomic_results(path, migrated)
            self.assertTrue(fairness.diagnose(self.c, run)[0])
        obtain.assert_called_once(); review.assert_called_once()
        self.assertEqual(json.loads(path.read_text())[1], row2)
        self.assertFalse(json.loads(path.read_text())[0]['guard_submitted'])

    def test_missing_replacement_is_retained_and_not_bought_again(self):
        workspace = self.attempt(); shutil.rmtree(workspace / 'guard')
        def no_fix(c, role, **kwargs):
            row = json.loads((workspace.parent / 'results.json').read_text())[0]
            row.update(guard_submitted=False, stop_reason='time_limit')
            calibration.atomic_results(self.work / kwargs['name'] / 'results.json', [row])
            return {'solved':0, 'tries':1}
        with patch.object(run, 'calibrate', side_effect=no_fix) as obtain, \
             patch.object(run, 'make_pilots'), patch.object(run, 'model_call') as review:
            for _ in range(2):
                ok, info = fairness.diagnose(self.c, run)
                self.assertFalse(ok); self.assertTrue(info['review_inconclusive'])
        obtain.assert_called_once(); review.assert_not_called()
        self.assertNotIn('difficulty', self.c.card)

    def test_early_probe_workspace_and_owner_transcripts_are_bound_to_review(self):
        workspace = self.attempt(); source = self.work / 'early_probe/try-1'
        source.parent.mkdir(); shutil.move(workspace, source)
        path = workspace.parent / 'results.json'
        row = json.loads(path.read_text())[0]
        row.update(workspace=str(source), guard=str(source / 'guard'), source='early_probe')
        calibration.atomic_results(path, [row])
        transcripts = self.work / 'transcripts'; transcripts.mkdir()
        transcript = transcripts / 'strong-calibrator-early_probe-1.jsonl'
        transcript.write_text(json.dumps({'supplied_promise': REAL['suffix-case']['files']['promise.md']}))
        def reviewer(c, chain, text, cwd, name):
            self.assertEqual(calibration.tree_digest(cwd / 'try-1'), calibration.tree_digest(source))
            self.assertEqual((cwd / 'attempts/transcripts' / transcript.name).read_bytes(), transcript.read_bytes())
            Path(text.split('Write the JSON verdict to ')[1].removesuffix('.')).write_text(json.dumps(
                {'tries':[{'try':1,'label':'wrong_fix','finding':'Refuse-all blocks legitimate operations',
                           'evidence':'try-1/execution.json'}]}))
            return 0
        with patch.object(run, 'model_call', side_effect=reviewer):
            self.assertTrue(fairness.diagnose(self.c, run)[0])
        # A missing retained workspace invalidates validation before any verdict.
        with patch('independent_review.review', side_effect=lambda c,r,g,inputs,text,validate:
                   (shutil.rmtree(source), validate({}))[1]):
            with self.assertRaises(InvalidInfra): fairness.review_attempts(self.c, run, 'G17', 'strong_calibrator')

    def test_independent_review_provider_waits_preserve_the_reviewer(self):
        self.attempt(); calls = []
        def reviewer(c, chain, text, cwd, name):
            calls.append(chain[0])
            output = Path(text.split('Write the JSON verdict to ')[1].removesuffix('.'))
            self.assertFalse(output.exists())
            if len(calls) < 3:
                output.write_text('{"inconclusive":true}')
                raise run.BudgetError('provider_wait')
            output.write_text(json.dumps({'tries':[{'try':1,'label':'wrong_fix',
                'finding':'Refuse-all blocks legitimate operations','evidence':'try-1/execution.json'}]}))
            return 0
        with patch.object(run, 'model_call', side_effect=reviewer):
            for _ in range(2):
                with self.assertRaises(run.BudgetError): fairness.diagnose(self.c, run)
                self.assertNotIn('difficulty', self.c.card)
            self.assertTrue(fairness.diagnose(self.c, run)[0])
        self.assertEqual(calls, ['deepseek/reviewer'] * 3)

    def test_gate_exhaustion_retains_one_diagnostic_per_invalid_execution(self):
        recorded = []
        def invoke():
            summary, records = batch('reset-invalid')
            require_valid(summary, records)
        outcome = gate_attempt.execute(invoke, publish=Mock(), record_crash=recorded.append,
            interruption=run.BudgetError, attempts=2, journal=self.work / 'gate.json', identity={'gate':'G5'})
        self.assertTrue(outcome.crashed)
        self.assertEqual(len(recorded), 2)

    def test_valid_saved_cheat_counterexample_survives_invalid_generic_probes(self):
        output = REAL['negative-invalid']['files']
        stdout = next(value for name, value in output.items() if name.endswith('.log'))
        with patch.object(run, 'cheat_runs', return_value=(1, 1)), \
             patch.object(run, 'sh', return_value=subprocess.CompletedProcess([], 1, stdout, '')):
            ok, info = run.g6(self.c)
        self.assertFalse(ok); self.assertTrue(info['cheats_passed'].startswith('1/'))

    def test_completed_units_receive_a_fresh_retry_allowance(self):
        journal = self.work / 'infra.json'
        for _ in range(2):
            calls = iter([InvalidInfra('reset invalid'), 'valid'])
            def invoke():
                result = next(calls)
                if isinstance(result, Exception): raise result
                return result
            self.assertEqual(retry(journal, {'gate':'G4'}, invoke), 'valid')
        self.assertTrue(all(row['invalid_attempts'] == 0 for row in json.loads(journal.read_text()).values()))

    def test_real_invalid_early_g4_g5_never_return_writer_problems(self):
        for gate in ('G4', 'G5'):
            self.c.early = {}
            pipeline = run._gate_pipeline(); pipeline.early_gates = (gate,)
            # No answer key means only the requested early gate is exercised.
            (self.c.case / 'answer-key.json').unlink(missing_ok=True)
            pipeline.saved_cheat_check = Mock(); pipeline.publish = Mock(); pipeline.log = Mock()
            pipeline.budget_boundary = Mock()
            with patch.object(run, 'checkpoint', return_value=batch('reset-invalid')):
                with self.assertRaises(InfrastructureExhausted): pipeline.early_checks(self.c)
            pipeline.saved_cheat_check.assert_not_called()
            self.assertEqual(self.c.early, {})
            self.assertNotIn('failed_gate', self.c.card)

    def test_pinned_policy_migration_keeps_valid_attempts_and_panels_only(self):
        import gate_state
        policy = json.loads((ROOT / 'factory/invalid-runs-compat.json').read_text())
        actual = run.calibration_identity(self.c, 'easy_calibrator', 'blind')
        current = copy.deepcopy(actual)
        # This historical migration authorizes exactly C's recorded target,
        # not every later revision of these source files.
        for section in ('runner', 'files'):
            for name, value in policy['current_' + section].items():
                if value is None: current['bench'][section].pop(name, None)
                else: current['bench'][section][name] = value
        old = copy.deepcopy(current)
        for section in ('runner', 'files'):
            for name, value in policy['base_' + section].items():
                if value is None: old['bench'][section].pop(name, None)
                else: old['bench'][section][name] = value
        self.assertTrue(calibration.compatible_identity(old, current))
        self.assertNotEqual(actual, current)
        self.assertFalse(calibration.compatible_identity(old, actual))
        changed = copy.deepcopy(old); changed['seed'] += 1
        self.assertFalse(calibration.compatible_identity(changed, current))
        changed = copy.deepcopy(old); changed['bench']['files']['bin/bench.py'] = '0' * 64
        self.assertFalse(calibration.compatible_identity(changed, current))
        actual_panel = json.loads(json.dumps(gate_state.inputs(self.c, 'G8', ROOT)))
        panel = copy.deepcopy(actual_panel)
        panel['cache'] = policy['current_files']['factory/gate_state.py']
        for name, value in policy['current_files'].items():
            if name in panel['bench']: panel['bench'][name] = value
        old_panel = copy.deepcopy(panel); old_panel['cache'] = policy['base_files']['factory/gate_state.py']
        for name, value in policy['base_files'].items():
            if name in old_panel['bench']: old_panel['bench'][name] = value
        self.assertTrue(calibration.compatible_panel(old_panel, panel))
        self.assertNotEqual(actual_panel, panel)
        self.assertFalse(calibration.compatible_panel(old_panel, actual_panel))
        old_panel['seed'] += 1
        self.assertFalse(calibration.compatible_panel(old_panel, panel))


if __name__ == '__main__': unittest.main()
