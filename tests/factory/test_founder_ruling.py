"""Real collected public accounting; opaque synthetic reports/evidence on worker seam.

Never decrypt real archives. The generation is the real ciphertext SHA. Only the
worker can validate the actual retained stress receipt/finding at founder launch.
"""
import copy
import datetime
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(Path(__file__).parent)]
import founder_ruling
import model_runtime
import restore_ledger
import run
from test_admission import evidence

FIXTURES = Path(__file__).parent / 'fixtures'


def read(path): return json.loads(path.read_text())
def save(path, value): path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def make_record(card):
    case = card['case']; short = case.rsplit('-', 1)[1]
    budget, rounds, feedback_round, findings = founder_ruling.ALLOWANCES[case]
    summary = restore_ledger.case_spending(card['continuation_budget'])
    return dict(version=1, authority='founder-2026-10-25', case=case, generation=card['sha256'],
        public_card_sha256=restore_ledger.digest(card), ledger_sha256=restore_ledger.digest(card['continuation_budget']),
        case_spent_usd=summary['spent_usd'], infrastructure_waste_usd=summary['infrastructure_waste_usd'],
        allowances=dict(case_budget_usd=budget, round_limit=rounds, freshness_repair_attempts=0,
                        rereviews=0, release_rereviews=[], release_review_attempts=[]),
        feedback=dict(round=feedback_round, findings=findings, reask_unresolved_freshness=True),
        ruling_verbatim=read(FIXTURES / 'last-legacy-founder-rulings.json')[short])


class ReachedWriter(Exception): pass


def replay(card, *, verify=None, cached_success=False, feedback_only=False, expired_unflagged=False):
    """Actual post-extraction CLI -> worker allowance install -> freshness -> writer."""
    with tempfile.TemporaryDirectory() as temp:
        home = Path(temp); work = home / 'work' / card['case']; work.mkdir(parents=True)
        case = work / 'case'; case.mkdir(); (work / 'attacks').mkdir()
        (case / 'statement.md').write_text('Synthetic pinned bug in 2.19.0')
        (case / 'case.json').write_text('{"app":{"commit":"v2.19.0"}}')
        (case / 'answer-key.json').write_text('{}')
        statement_sha = hashlib.sha256((case / 'statement.md').read_bytes()).hexdigest()
        rows_count = (card.get('loop_freshness') or {}).get('rows') or 5
        rows = [evidence('attacker', 'github', i, ambiguous=not expired_unflagged,
            url=f'https://github.com/example/project/issues/{i}') for i in range(rows_count)]
        # Supply a full valid synthetic evidence set, plus the public row count.
        rows += [evidence('builder', kind, i + 100) for kind in ('web', 'github') for i in range(3)]
        rows += [evidence('attacker', 'web', i + 200) for i in range(2)]
        if expired_unflagged:
            for row in rows:
                row['at'] = (datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=2)).isoformat()
        (case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        retained = copy.deepcopy(card['continuation_budget']); retained['terminal_stop'] = 'archived-before-public-stop'
        save(work / 'scorecard.json', {**card, 'continuation_budget': retained})
        save(work / 'continuation-budget.json', retained)
        record = make_record(card); ruling = home / 'founder-ruling.json'; save(ruling, record)
        pin = hashlib.sha256(ruling.read_bytes()).hexdigest()
        limits = record['allowances']; n = record['feedback']['round']
        binding = dict(case='opaque-unchanged-case', case_id=card['case'], source=card['source'],
            bench='current-release', models=card['models']['attacker'], prompt='opaque-prompt')
        attack = dict(round=n, round_limit=limits['round_limit'], report=f'round-{n}.json',
            rereviews=2, release_rereviews=['a' * 64], release_review_attempts=[],
            binding={**binding, 'bench': 'old-release'})
        save(work / 'attack-state.json', attack)
        save(work / 'freshness-repair.json', dict(version=1, attempts=2, statement_sha256=statement_sha))
        report = work / 'attacks' / attack['report']
        finding = '[freshness-review] independent verdict required' if feedback_only else 'Synthetic retained case finding'
        save(report, dict(complete=True, blocking=[finding],
                         freshness_review=[rows[0]['url']]))
        before_report = report.read_bytes()
        if cached_success:
            from admission import search_binding, search_receipt
            seed = SimpleNamespace(work=work, case=case, case_id=card['case'], models=card['models'])
            verdict_path = 'g2-confirm-123/verdict.json'
            answers = [dict(url=row['url'], resolved=True, same_bug=False, retrieved=True,
                app_version='2.19.0', version_scope='Synthetic prior release', why='Synthetic exclusion')
                for row in rows[:rows_count]]
            review = work / 'g2-confirm-123'; review.mkdir(); shutil.copytree(case, review / 'case')
            binding_old = {**search_binding(seed, rows[:rows_count]), 'confirmation_contract': 1}
            save(review / 'verdict.json', {'hits': answers})
            save(review / 'review-completed.json', {'binding': binding_old})
            save(work / 'freshness-verdict.json', dict(binding=binding_old, hits=answers, verdict_path=verdict_path))
            save(work / 'public-search.json', search_receipt(search_binding(seed, rows), True,
                dict(searches=len(rows), hits=0, flagged_hits=rows_count, invalid_evidence=0,
                     counted=dict(builder_web=3, builder_github=3, attacker=rows_count+2))))
            previous = read(work / 'scorecard.json')
            previous['loop_freshness'] = {'verdict_path': verdict_path, 'outcome': 'excluded'}
            save(work / 'scorecard.json', previous)
        if verify is not None:
            return verify(home, work, ruling, pin, record, card)
        argv = ['restore_ledger.py', '--home', str(home), '--case', card['case'], '--generation', card['sha256'],
                '--founder-ruling', str(ruling), '--founder-ruling-sha256', pin]
        with patch.object(sys, 'argv', argv), patch.object(sys, 'stdin', io.StringIO(json.dumps(card))), \
             patch.object(sys, 'stdout', io.StringIO()) as output:
            assert restore_ledger.main() == 0, output.getvalue()
        imported = json.loads(output.getvalue())
        assert imported['attempt_allowances_authenticated'] is True
        assert imported['founder_ruling']['authorization']['sha256'] == pin
        assert read(work / 'attack-state.json')['rereviews'] == 0
        assert read(work / 'freshness-repair.json')['attempts'] == 0
        assert report.read_bytes() == before_report
        if cached_success:
            for path in [work / 'public-search.json', work / 'freshness-verdict.json',
                         work / 'g2-confirm-123/review-completed.json']:
                assert not path.exists() and path.with_name(path.name+'.pre-founder-ruling').is_file()
        # Same pinned import is idempotent; it does not reset counters a second time.
        reset = read(work / 'freshness-repair.json'); reset['attempts'] = 1
        save(work / 'freshness-repair.json', reset)
        restore_ledger.install(work, home / 'sealed', card['case'], card['sha256'], card,
                               ruling_path=ruling, ruling_sha256=pin)
        assert read(work / 'freshness-repair.json')['attempts'] == 1
        c = SimpleNamespace(case_id=card['case'], case=case, work=work, card=copy.deepcopy(card),
            ledger=home / 'sealed' / (card['case'] + '.continuation-budget.json'), models=card['models'],
            args=SimpleNamespace(resume=card['case'], source=card['source'], dry_run=False, skip_build=False,
                case_budget=limits['case_budget_usd'], rounds=limits['round_limit'], agent_timeout=14400,
                runs=10, scenario_runs=3))
        calls = []; deadlines = []
        def model(ctx, models, text, cwd, name, **kwargs):
            calls.append(name)
            if name in ('builder-freshness', 'attacker-freshness') and expired_unflagged:
                assert 300 < kwargs['timeout'] <= min(1200, 60*len(rows))
                current_rows = run.freshness_lines(ctx)
                for row in current_rows:
                    if row['who'] == name.split('-')[0]:
                        row['at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                (ctx.case / 'freshness.jsonl').write_text('\n'.join(map(json.dumps,current_rows)))
                return 0
            if name == 'reviewer-g2-confirm':
                confirm_rows = 1 if expired_unflagged else rows_count
                assert kwargs['timeout'] == min(1800, ctx.args.agent_timeout, 300 + 120 * confirm_rows)
                assert kwargs['timeout'] > 300
                assert kwargs['deadline'] > run.time.monotonic()
                deadlines.append(kwargs['timeout'])
                answers = [dict(url=row['url'], resolved=True, same_bug=False, retrieved=True,
                    app_version='2.19.0', version_scope='Synthetic pinned version excluded', why='Synthetic different bug')
                    for row in rows[:confirm_rows]]
                save(Path(cwd) / 'verdict.json', {'hits': answers}); return 0
            if feedback_only and name == f'attacker-{n}':
                save(report, dict(complete=True, blocking=[]))
                return 0
            assert name == f'builder-{n + 1}', name
            assert 'Synthetic retained case finding' in text
            assert ctx.card['founder_ruling']['authorization']['sha256'] == pin
            raise ReachedWriter()
        with patch.object(run, 'g1', return_value=(True, {'problems': []})), \
             patch.object(run, 'early_review', return_value=None), \
             patch.object(run, 'attack_binding', return_value=binding), \
             patch.object(run, 'prompt', side_effect=lambda role, text: text), \
             patch.object(run, 'run_context', side_effect=lambda ctx, **kw: json.dumps(kw)), \
             patch.object(run, 'opencode', side_effect=model):
            # Enter the actual resumed construction entry point, including its
            # G2-before-writer ordering and retained attack-state recovery.
            try: run.build(c)
            except ReachedWriter:
                assert not feedback_only
            else:
                assert feedback_only and c.card['stress_review'] == {'status': 'completed', 'round': n}
        if expired_unflagged:
            assert calls[:3] == ['builder-freshness','attacker-freshness','reviewer-g2-confirm'], calls
        else:
            assert calls[0] == 'reviewer-g2-confirm', calls
        if feedback_only:
            assert calls[-1] == f'attacker-{n}', calls
        else:
            assert calls[-1] == f'builder-{n + 1}', calls
            assert not any(name.startswith('attacker-') and name != 'attacker-freshness' for name in calls), calls
        assert read(work / 'attack-state.json')['round_limit'] == limits['round_limit']
        estimate = model_runtime.writer_round_estimate(c)
        return dict(case=card['case'], case_spent_usd=imported['case_spent_usd'],
            infrastructure_waste_usd=imported['infrastructure_waste_usd'], limit_usd=c.args.case_budget,
            remaining_usd=round(c.args.case_budget-imported['case_spent_usd'], 9),
            writer_estimate_usd=estimate, admitted=c.args.case_budget-imported['case_spent_usd'] >= estimate,
            calls=calls, reviewer_deadlines=deadlines, round_limit=c.args.rounds,
            reset_allowances=limits, real_collected_card=True, synthetic_sealed_state=True,
            receipt_accepted_and_recorded=True)


class FounderRulingTests(unittest.TestCase):
    def cards(self):
        for name in ('e15450', 'canary6'):
            yield read(FIXTURES / (name + '-last-legacy-card.json'))

    def test_real_cards_reach_scaled_confirmation_then_writer(self):
        for card in self.cards():
            with self.subTest(case=card['case']):
                result = replay(card)
                self.assertTrue(result['admitted'])
                self.assertEqual(result['writer_estimate_usd'], 8 if card['case'].endswith('e15450') else 15.05)
                if card['case'].endswith('e15450'):
                    self.assertLess(50-result['case_spent_usd'], 8)
                    self.assertEqual(result['calls'][-1], 'builder-9')
                else:
                    self.assertEqual(result['case_spent_usd'], 27.166938577)
                    self.assertEqual(result['infrastructure_waste_usd'], 16)
                    self.assertEqual(result['remaining_usd'], 22.833061423)

    def test_missing_tampered_wrong_generation_and_unknown_usage_refuse(self):
        for card in self.cards():
            def check(home, work, path, pin, record, public):
                def install(**kw):
                    return restore_ledger.install(work, home / 'sealed', public['case'], public['sha256'], public, **kw)
                with self.assertRaisesRegex(restore_ledger.Refused, 'receipt required'): install()
                changed = copy.deepcopy(record); changed['allowances']['case_budget_usd'] += 1
                save(path, changed)
                with self.assertRaisesRegex(restore_ledger.Refused, 'hash mismatch'):
                    install(ruling_path=path, ruling_sha256=pin)
                with self.assertRaisesRegex(restore_ledger.Refused, 'allowances differ'):
                    install(ruling_path=path, ruling_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                changed = copy.deepcopy(record); changed['generation'] = '0' * 64; save(path, changed)
                with self.assertRaisesRegex(restore_ledger.Refused, 'generation/accounting'):
                    install(ruling_path=path, ruling_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                public['continuation_budget']['unpriced_invocations'] = [{'role': 'reviewer', 'model': 'unknown'}]
                changed = make_record(public); save(path, changed)
                with self.assertRaisesRegex(restore_ledger.Refused, 'monetary facts'):
                    install(ruling_path=path, ruling_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertFalse((work / 'founder-ruling-applied.json').exists())
                self.assertFalse((home / 'sealed').exists())
            replay(card, verify=check)

    def test_legacy_success_caches_cannot_skip_new_release_confirmation(self):
        for card in self.cards():
            self.assertEqual(replay(card, cached_success=True)['calls'][0], 'reviewer-g2-confirm')

    def test_canary_cleared_freshness_only_feedback_requires_current_stress(self):
        card = read(FIXTURES / 'canary6-last-legacy-card.json')
        self.assertEqual(replay(card, feedback_only=True)['calls'], ['reviewer-g2-confirm', 'attacker-4'])

    def test_expired_unflagged_rows_research_before_confirmation_and_writer(self):
        for card in self.cards():
            result = replay(card, expired_unflagged=True)
            self.assertEqual(result['calls'][:3], ['builder-freshness','attacker-freshness','reviewer-g2-confirm'])
            self.assertEqual(result['reviewer_deadlines'], [420])

    def test_archived_marker_alone_cannot_grant_allowances(self):
        for card in self.cards():
            def check(home, work, path, pin, record, public):
                accepted = founder_ruling.authenticate(path, pin, public['case'], public['sha256'], public)
                founder_ruling.apply(work, accepted)
                c = SimpleNamespace(work=work, case_id=public['case'], card={},
                    ledger=home / 'sealed' / (public['case'] + '.continuation-budget.json'))
                self.assertIsNone(founder_ruling.context(c))
                self.assertNotIn('founder_ruling', c.card)
            replay(card, verify=check)

    def test_deadline_formula_cap_and_agent_timeout(self):
        c = SimpleNamespace(args=SimpleNamespace(agent_timeout=14400))
        for rows, agent, seconds in ((1,14400,420),(5,14400,900),(20,14400,1800),(10,600,600)):
            c.args.agent_timeout = agent
            self.assertEqual(run.confirm_timeout(c, rows), seconds)


if __name__ == '__main__': unittest.main()
