"""Replay collected canary metadata; never reconstruct or read real search rows."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import budget


class RepairTimeoutTests(unittest.TestCase):
    def test_real_canary_counts_and_budget(self):
        card = json.loads((Path(__file__).parent / 'fixtures/canary6-collected-card.json').read_text())
        info = card['admission_freshness']
        self.assertEqual((info['searches'], info['invalid_evidence'], info['unresolved_hits']), (49, 44, 1))
        self.assertEqual(info['invalid_evidence_reasons'], {'evidence_expired': 27, 'invalid_app_version': 17})
        self.assertEqual(info['counted'], {'builder_web': 0, 'builder_github': 0, 'attacker': 5})
        ledger = card['continuation_budget']
        with self.assertRaisesRegex(budget.BudgetError, 'budget_exhausted'): budget.require_case_budget(ledger, 50)
        self.assertEqual(budget.case_spending(ledger)['known_spent_usd'], 27.072383602)

    def stream(self, driver, events, model, **kwargs):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); ledger = root / 'ledger.json'
            code = ''.join('print(' + repr(json.dumps(e)) + ', flush=True)\n' for e in events)
            code += 'import time; time.sleep(60)\n'
            # Allow interpreter startup under concurrent suites before timing out the sleeping child.
            with self.assertRaisesRegex(budget.BudgetError, '^timeout$'):
                budget.run_budgeted([sys.executable, '-c', code], root, os.environ.copy(),
                    root / 'synthetic-stream', ledger, 1, containment=False, driver=driver, configured_model=model,
                    role='writer', **kwargs)
            return json.loads(ledger.read_text())

    def test_claude_partial_usage_deduplicates_and_prices_latest_blocks(self):
        usage = dict(input_tokens=100, output_tokens=5, cache_read_input_tokens=200, cache_creation_input_tokens=50)
        message = lambda u: dict(type='assistant', message=dict(id='m', usage=u))
        data = self.stream('claude', [dict(type='system', subtype='init', session_id='s'),
            message(usage), message({**usage, 'output_tokens': 10})], 'claude/claude-opus-5-5')
        [event] = data['events']
        self.assertEqual(event['tokens']['output_tokens'], 10)
        self.assertTrue(event['estimated_from_partial_usage'])
        self.assertEqual(data['calls'], 1)
        self.assertNotIn('unpriced_invocations', data)
        self.assertGreater(budget.case_spending(data)['spent_usd'], 0)
        budget.require_case_budget(data, 50)

    def test_codex_observed_usage_is_retained_but_no_usage_blocks(self):
        start = [dict(type='thread.started', thread_id='t'), dict(type='turn.started')]
        item = dict(type='item.completed', item=dict(type='agent_message', id='a'),
                    usage=dict(input_tokens=100, cached_input_tokens=20, output_tokens=10))
        data = self.stream('codex', start + [item], 'codex/gpt-6.1-sol')
        self.assertTrue(data['events'][0]['estimated_from_partial_usage'])
        self.assertNotIn('unpriced_invocations', data)
        for driver, events, model in [('codex', start, 'codex/gpt-6.1-sol'),
                                      ('claude', [], 'claude/claude-opus-5-5')]:
            data = self.stream(driver, events, model)
            self.assertIsNone(budget.case_spending(data)['spent_usd'])
            with self.assertRaisesRegex(budget.BudgetError, 'budget_exhausted'): budget.require_case_budget(data, 50)

    def test_valid_claude_usage_cannot_hide_a_later_unknown_response(self):
        good = dict(type='assistant', message=dict(id='good', usage=dict(
            input_tokens=100, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0)))
        for bad in [dict(type='assistant', message=dict(id='bad')),
                    dict(type='assistant', message=dict(id='bad', usage=dict(input_tokens=1))),
                    dict(type='result', total_cost_usd=1, usage={})]:
            with self.subTest(event=bad), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); ledger = root / 'ledger.json'
                events = [dict(type='system', subtype='init', session_id='s'), good, bad]
                code = ''.join('print(' + repr(json.dumps(e)) + ', flush=True)\n' for e in events)
                with self.assertRaisesRegex(budget.BudgetError, '^missing_usage$'):
                    budget.run_budgeted([sys.executable, '-c', code], root, os.environ.copy(),
                        root / 'synthetic-stream', ledger, 3, containment=False, driver='claude',
                        configured_model='claude/claude-opus-5-5', role='writer')
                data = json.loads(ledger.read_text())
                self.assertTrue(data['events'][0]['estimated_from_partial_usage'])
                self.assertGreater(budget.case_spending(data)['known_spent_usd'], 0)
                with self.assertRaisesRegex(budget.BudgetError, 'budget_exhausted'): budget.require_case_budget(data, 50)


if __name__ == '__main__': unittest.main()
