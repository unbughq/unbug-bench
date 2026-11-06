"""Real collected public accounting: observed prices and infrastructure waste."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import budget
import model_runtime
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


class WasteRereviewTests(unittest.TestCase):
    def test_real_e15450_observed_writer_estimate(self):
        card = read('e15450-collected-card.json')
        self.assertEqual(card['admission_freshness']['outcome'], 'clear')
        self.assertEqual(card['freshness_reverify']['expired'], 31)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ledger.json'; path.write_text(json.dumps(card['continuation_budget']))
            c = types.SimpleNamespace(ledger=path, card=card, args=types.SimpleNamespace(case_budget=50))
            self.assertEqual(model_runtime.writer_round_estimate(c), 8.0)
            self.assertGreaterEqual(50 - card['case_budget']['spent_usd'], 8.0)

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
