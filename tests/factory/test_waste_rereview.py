"""Real collected public cards/counters; opaque synthetic bindings and report only."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import budget
import model_runtime
import registry
import run

FIXTURES = Path(__file__).parent / 'fixtures'


def read(name): return json.loads((FIXTURES / name).read_text())


def waste_ledger(card, case):
    ledger = copy.deepcopy(card['continuation_budget'])
    evidence = read('infrastructure-kills.json')[case]
    unknown = ledger.pop('unpriced_invocations')
    record = dict(id=case + ':300s-infrastructure-kill', kind='infrastructure_kill',
        infrastructure_waste_usd=evidence['bound_charge_usd'], derivation=evidence,
        reason='Evidenced flat-300s freshness repair deadline bug; founder excludes our infrastructure waste from the case cap.',
        resolved_unpriced_invocations=unknown)
    ledger.setdefault('infrastructure_waste', []).append(record)
    ledger.setdefault('resolved_unpriced_invocations', []).extend(
        dict(original=item, infrastructure_waste_id=record['id']) for item in unknown)
    return ledger


def replay_rereview(card, *, case_changed=False, malformed=False, partial=False, history=None, rereviews=2,
                    interruptions=0, partial_interrupt=False, reservation_interrupt=False, completed_partial_interrupt=False):
    """Exercise production resume routing up to the attacker, without model or content access."""
    real = read('e15450-attack-receipt-metadata.json')
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp); case = work / 'case'; case.mkdir(); (work / 'attacks').mkdir()
        ledger = work / 'ledger.json'; ledger.write_text(json.dumps(card['continuation_budget']))
        c = types.SimpleNamespace(work=work, case=case, case_id=card['case'], ledger=ledger,
            card=copy.deepcopy(card), models=card['models'], manifest0='new-release-bench',
            args=types.SimpleNamespace(source=card['source'], resume=card['case'], rounds=8,
                case_budget=50, skip_build=False, dry_run=False))
        binding = dict(case='opaque-unchanged-case-hash', case_id=c.case_id, source=c.args.source,
            bench=c.manifest0, models=c.models['attacker'], prompt='opaque-current-prompt-hash')
        saved = {**binding, 'bench': 'previous-release-bench'}
        if case_changed: saved['case'] = 'opaque-previous-case-hash'
        receipt = dict(round=real['round'], report=real['report'], round_limit=real['round_limit'],
            rereviews=rereviews, binding=saved, release_rereviews=history or [])
        assert sorted(receipt['binding']) == real['binding_keys']
        path = work / 'attack-state.json'; path.write_text(json.dumps(receipt))
        report = work / 'attacks' / real['report']
        report.write_text('{bad json' if malformed else
                          '{"complete": false, "blocking": ["recorded partial finding"]}' if partial else
                          '{"complete": true, "blocking": []}')
        calls = []
        class ReachedWriter(Exception): pass
        def attacker(ctx, models, text, cwd, name):
            if completed_partial_interrupt and name == 'builder-8':
                calls.append(name)
                raise ReachedWriter()
            assert name == 'attacker-7', name
            model_runtime.case_budget_boundary(ctx)
            calls.append(name)
            if len(calls) <= interruptions:
                if partial_interrupt: report.write_text('{"complete": false, "blocking": ["partial finding before infrastructure stop"]}')
                raise budget.BudgetError('stalled')
            report.write_text('{"complete": false, "blocking": ["committed partial finding"]}' if completed_partial_interrupt else
                              '{"complete": true, "blocking": []}')
        atomic = registry.atomic_json
        reservation_killed = False
        completion_killed = False
        def publish(target, value):
            nonlocal reservation_killed, completion_killed
            atomic(target, value)
            if (reservation_interrupt and not reservation_killed and target == path and value.get('review_pending') is True):
                reservation_killed = True
                raise budget.BudgetError('stalled')
            if (completed_partial_interrupt and not completion_killed and target == path and value.get('review_pending') is False):
                completion_killed = True
                raise budget.BudgetError('stalled')
        with patch.object(run, 'case_hash', return_value=binding['case']), \
             patch.object(run, 'attack_binding', return_value=binding), \
             patch.object(run, 'g1', return_value=(True, {'problems': []})), \
             patch.object(run, 'prompt', side_effect=lambda role, text: text), \
             patch.object(run, 'run_context', return_value='synthetic metadata-only request'), \
             patch.object(run, 'loop_freshness', side_effect=lambda ctx, result, path: (result, path)), \
             patch.object(run, 'early_review', return_value=None), patch.object(run, 'opencode', attacker), \
             patch.object(registry, 'atomic_json', side_effect=publish):
            if reservation_interrupt or completed_partial_interrupt:
                try: run.write_and_attack(c, {**card, 'terminal_stop': 'stalled'})
                except budget.BudgetError as error:
                    assert str(error) == 'stalled', str(error)
                else: raise AssertionError('expected interruption after binding reservation')
            for _ in range(interruptions):
                try: run.write_and_attack(c, {**card, 'terminal_stop': 'stalled'})
                except budget.BudgetError as error:
                    assert str(error) == 'stalled', str(error)
                else: raise AssertionError('expected interrupted release review')
            try: run.write_and_attack(c, {**card, 'terminal_stop': 'stalled'} if interruptions else card)
            except ReachedWriter:
                if not completed_partial_interrupt: raise
        return c.card, json.loads(path.read_text()), calls


class WasteRereviewTests(unittest.TestCase):
    def test_committed_partial_release_report_hands_findings_to_writer_without_extra_review(self):
        card = read('e15450-collected-card.json')
        _, receipt, calls = replay_rereview(card, rereviews=2, completed_partial_interrupt=True)
        self.assertEqual(calls, ['attacker-7', 'builder-8'])
        self.assertEqual(len(receipt['release_review_attempts']), 1)

    def test_release_reservation_kill_cannot_certify_leftover_completed_report(self):
        card = read('e15450-collected-card.json')
        current, receipt, calls = replay_rereview(card, rereviews=2, reservation_interrupt=True)
        self.assertEqual(calls, ['attacker-7'])
        self.assertEqual(current['stress_review']['status'], 'completed')
        self.assertFalse(receipt['review_pending'])
        self.assertEqual(receipt['review_completed']['attempt'], receipt['review_attempt'])
        self.assertEqual(receipt['rereviews'], 2)

    def test_interrupted_release_partial_findings_resume_reviewer_before_writer(self):
        card = read('e15450-collected-card.json')
        _, receipt, calls = replay_rereview(card, rereviews=2, interruptions=1, partial_interrupt=True)
        self.assertEqual(calls, ['attacker-7', 'attacker-7'])
        self.assertEqual(receipt['rereviews'], 2)
        self.assertEqual(len(receipt['release_review_attempts']), 2)

    def test_interrupted_release_review_keeps_cause_and_separate_finite_bound(self):
        card = read('e15450-collected-card.json')
        _, receipt, calls = replay_rereview(card, rereviews=2, interruptions=7)
        self.assertEqual(calls, ['attacker-7'] * 8)
        self.assertEqual(receipt['rereviews'], 2)
        self.assertEqual(len(receipt['release_rereviews']), 1)
        self.assertEqual(len(receipt['release_review_attempts']), 8)
        self.assertTrue(all(v['cause'] == 'infrastructure' for v in receipt['release_review_attempts']))
        with self.assertRaisesRegex(budget.BudgetError, 'interrupted_review'):
            replay_rereview(card, rereviews=2, interruptions=8)

    def test_release_forces_partial_report_rereview_into_separate_history(self):
        # The public e15450 receipt supplies real round/limit/counter metadata.
        # No claim about its encrypted report contents: exercise the valid partial
        # report branch that previously required complete=True to classify a release.
        card = read('e15450-collected-card.json')
        current, receipt, calls = replay_rereview(card, partial=True, rereviews=1)
        self.assertEqual(calls, ['attacker-7'])
        self.assertEqual(receipt['rereviews'], 1)
        self.assertEqual(len(receipt['release_rereviews']), 1)
        self.assertEqual(current['stress_review']['status'], 'completed')

    def test_real_c7_last_round_rereview_cannot_buy_unreserved_final_writer(self):
        card = read('c7d405-collected-card.json')
        ledger = waste_ledger(card, 'c7d405')
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp); case = work / 'case'; case.mkdir(); (work / 'attacks').mkdir()
            lp = work / 'ledger.json'; lp.write_text(json.dumps(ledger))
            c = types.SimpleNamespace(work=work, case=case, case_id=card['case'], ledger=lp,
                card=copy.deepcopy(card), models=card['models'], manifest0='new-release',
                args=types.SimpleNamespace(source=card['source'], resume=card['case'], rounds=9,
                    case_budget=50, skip_build=False, dry_run=False))
            # Exercise the last-round boundary, without claiming this is the
            # encrypted c7 receipt. Spending and kill evidence are the real card.
            binding = dict(case='opaque-case-hash', case_id=c.case_id, source=c.args.source,
                bench='new-release', models=c.models['attacker'], prompt='opaque-prompt-hash')
            (work / 'attack-state.json').write_text(json.dumps(dict(round=9, round_limit=9,
                report='round-9.json', binding={**binding, 'bench': 'previous-release'}, rereviews=0)))
            report = work / 'attacks/round-9.json'; report.write_text('{"complete": true, "blocking": []}')
            calls = []
            def call(ctx, models, text, cwd, name):
                calls.append(name)
                self.assertEqual(name, 'attacker-9', 'unreserved writer was called')
                report.write_text('{"complete": true, "blocking": ["synthetic new finding"]}')
            with patch.object(run, 'case_hash', return_value=binding['case']), \
                 patch.object(run, 'attack_binding', return_value=binding), \
                 patch.object(run, 'g1', return_value=(True, {'problems': []})), \
                 patch.object(run, 'prompt', side_effect=lambda role, text: text), \
                 patch.object(run, 'run_context', return_value='synthetic metadata-only request'), \
                 patch.object(run, 'loop_freshness', side_effect=lambda ctx, result, path: (result, path)), \
                 patch.object(run, 'opencode', call), self.assertRaisesRegex(budget.BudgetError, '^budget_exhausted$'):
                run.write_and_attack(c, card)
            self.assertEqual(calls, ['attacker-9'])
            self.assertEqual(c.card['case_budget']['spent_usd'], 38.94274723)
            self.assertEqual(round(50 - c.card['case_budget']['spent_usd'], 9), 11.05725277)
            self.assertEqual(c.card['case_budget']['next_round_estimate_usd'], 19.29)
            self.assertEqual(json.loads((work / 'attack-state.json').read_text())['stop_reason'], 'budget_exhausted')

    def test_real_e15450_two_spent_rereviews_reach_attacker(self):
        card = read('e15450-collected-card.json')
        self.assertEqual(card['admission_freshness']['outcome'], 'clear')
        self.assertEqual(card['freshness_reverify']['expired'], 31)
        current, receipt, calls = replay_rereview(card)
        self.assertEqual(calls, ['attacker-7'])
        self.assertEqual(receipt['rereviews'], 2)
        self.assertEqual(len(receipt['release_rereviews']), 1)
        self.assertEqual(current['stress_review'], {'status': 'completed', 'round': 7})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ledger.json'; path.write_text(json.dumps(card['continuation_budget']))
            c = types.SimpleNamespace(ledger=path, card=card, args=types.SimpleNamespace(case_budget=50))
            self.assertEqual(model_runtime.writer_round_estimate(c), 8.0)
            self.assertGreaterEqual(50 - card['case_budget']['spent_usd'], 8.0)
        # Prompt/model changes within this same release cannot buy another exemption.
        with self.assertRaisesRegex(budget.BudgetError, 'binding_changed'):
            replay_rereview(card, history=receipt['release_rereviews'])
        # Switching through another release and back retains the same history.
        with self.assertRaisesRegex(budget.BudgetError, 'binding_changed'):
            replay_rereview(card, history=receipt['release_rereviews'] + ['a' * 64])

    def test_real_receipt_case_change_or_unusable_report_still_hits_cap(self):
        card = read('e15450-collected-card.json')
        for kwargs in [dict(case_changed=True), dict(malformed=True)]:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(budget.BudgetError, 'stress_review_unresolved'):
                replay_rereview(card, **kwargs)

    def test_real_canary_and_c7_waste_budget_and_estimate(self):
        for case, name, spent, waste, estimate, admitted in [
                ('873d7f', 'canary6-collected-card.json', 27.072383602, 16, 15.05, True),
                ('c7d405', 'c7d405-collected-card.json', 38.94274723, 20, 19.29, False)]:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                card = read(name); ledger = waste_ledger(card, case)
                path = Path(temp) / 'ledger.json'; path.write_text(json.dumps(ledger))
                c = types.SimpleNamespace(ledger=path, card=card, args=types.SimpleNamespace(case_budget=50))
                summary = model_runtime.update_case_budget(c)[1]
                self.assertEqual(summary['spent_usd'], spent)
                self.assertEqual(summary['infrastructure_waste_usd'], waste)
                self.assertEqual(summary['total_spent_usd'], round(spent + waste, 9))
                self.assertEqual(model_runtime.writer_round_estimate(c), estimate)
                self.assertEqual(50 - spent >= estimate, admitted)
                budget.require_case_budget(ledger, 50)
                text = run.scorecard_text(card)
                self.assertIn('infrastructure_waste_usd: ' + str(waste), text)
                self.assertIn(str(round(spent + waste, 9)), text)
                self.assertIn('ceil(max(', text)

    def test_unknown_unpriced_usage_still_fails_closed_with_waste(self):
        ledger = waste_ledger(read('canary6-collected-card.json'), '873d7f')
        ledger['unpriced_invocations'] = [dict(role='writer', model='unknown/model')]
        summary = budget.case_spending(ledger)
        self.assertIsNone(summary['spent_usd'])
        self.assertEqual(summary['infrastructure_waste_usd'], 16)
        self.assertEqual(summary['known_total_spent_usd'], 43.072383602)
        with self.assertRaisesRegex(budget.BudgetError, 'budget_exhausted'): budget.require_case_budget(ledger, 50)
        ledger.pop('unpriced_invocations')
        ledger['infrastructure_waste'][0]['derivation'] = {}
        with self.assertRaisesRegex(budget.BudgetError, 'budget_exhausted'): budget.require_case_budget(ledger, 50)


if __name__ == '__main__': unittest.main()
