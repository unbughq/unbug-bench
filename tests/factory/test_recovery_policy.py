"""Public recovery decisions only; no keys, archives, workers or model calls."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy
import unittest

import recovery


class RecoveryPolicyTests(unittest.TestCase):
    def card(self, stop='stalled', ledger='stalled'):
        return {'status': 'stopped', 'terminal_stop': stop,
                'continuation_budget': {'terminal_stop': ledger, 'events': [],
                                        'cost': 0, 'calls': 0, 'list_cost_usd': 1}}

    def test_public_crash_needs_consistent_gate_and_stop_labels(self):
        card = self.card('runner_error:RuntimeError')
        card.update(failed_gate='G15', failed_detail={'error': 'RuntimeError'},
                    gates={'G15': 'fail'}, gate_results={'G15': {'error': 'RuntimeError'}})
        self.assertEqual(recovery.recoverable_crash(card), {'gate': 'G15', 'error_type': 'RuntimeError'})
        self.assertFalse(recovery.require_restart_stop(card, []))
        self.assertFalse(recovery.require_holder_stop(card, [], 'case'))
        # The adopter does not have the crash authentication route.
        self.assertIn('needs a repair decision', recovery.adopter_stop_reason(card))
        for changes in ({'terminal_stop': 'cost_limit'}, {'gates': {'G15': 'pass'}},
                        {'gate_results': {'G15': {'problems': ['case defect']}}},
                        {'failed_detail': {'error': 'RuntimeError', 'message': 'not public'}},
                        {'failed_gate': 'G12'}):
            with self.subTest(changes=changes):
                modified = {**card, **changes}
                self.assertIsNone(recovery.recoverable_crash(modified))
                with self.assertRaises(ValueError): recovery.require_restart_stop(modified, [])

    def test_explicit_pause_and_ttl_are_distinct(self):
        for stop, ledger, want in [('paused', 'complete', True), ('stalled', 'paused', True),
                                   ('stalled', 'PauseRequested', True),
                                   ('ttl_retired', 'PauseRequested', False),
                                   ('stalled', 'complete', False)]:
            with self.subTest(stop=stop, ledger=ledger):
                self.assertEqual(recovery.explicit_pause(self.card(stop, ledger)), want)
        card = self.card('paused', 'PauseRequested')
        with self.assertRaisesRegex(ValueError, 'deliberate resume'):
            recovery.require_restart_stop(card, [])
        # Preserve the existing paid-worker adopter policy, not a new authorization.
        self.assertIsNone(recovery.adopter_stop_reason(card))

    def test_ledger_reconciliation_matrix_preserves_transport_rules(self):
        # public stop, ledger stop, restart, holder (case mode)
        rows = [('stalled', 'stalled', True, True),
                ('stalled', 'complete', True, True),
                ('stalled', 'cost_limit', False, False),
                ('runner_error:RuntimeError', 'timeout', True, True),
                ('paused', 'PauseRequested', False, True),
                ('ttl_retired', 'PauseRequested', False, True),
                ('usage_monitor:timeout', 'timeout', False, True),
                ('Budget ledger stopped: timeout', 'timeout', False, True),
                ('codex_cli_not_0.162.1', 'cancelled', False, True),
                ('time_limit', 'timeout', False, False)]
        for stop, ledger, restart, holder in rows:
            card = self.card(stop, ledger)
            original = copy.deepcopy(card)
            with self.subTest(stop=stop, ledger=ledger):
                self.assertEqual(recovery.ledger_agrees(card, route='restart'), restart)
                self.assertEqual(recovery.ledger_agrees(card, route='holder'), holder)
                self.assertEqual(card, original, 'decisions must never clear a ledger stop')
        self.assertTrue(recovery.ledger_agrees(self.card('time_limit', 'timeout'), route='holder', mode='review'))
        self.assertTrue(recovery.ledger_agrees(self.card('paused', 'PauseRequested'), route='restart', model_cutover=True))
        with self.assertRaises(ValueError): recovery.ledger_agrees(self.card(), route='unknown')

    def test_rereview_cannot_mask_gate_failure_or_exhausted_budget(self):
        card = self.card(recovery.REREVIEW_STOP, 'timeout')
        self.assertTrue(recovery.rereview_stop(card))
        self.assertTrue(recovery.ledger_agrees(card, route='restart'))
        self.assertTrue(recovery.require_holder_stop(card, [], 'case'))
        for changes in ({'gates': {'G5': 'fail'}}, {'failed_gate': 'G5'},
                        {'checkpoint_error': 'error'}):
            with self.subTest(changes=changes):
                modified = {**card, **changes}
                self.assertFalse(recovery.rereview_stop(modified))
                with self.assertRaises(ValueError): recovery.require_holder_stop(modified, [], 'case')
        card['continuation_budget']['list_cost_usd'] = 50
        with self.assertRaises(ValueError): recovery.require_holder_stop(card, [], 'case')

    def test_budget_reopen_requires_explicit_remaining_allowance(self):
        card = self.card('budget_exhausted', 'budget_exhausted')
        card.update(case_budget={'limit_usd': 50}, recovery_config={'rounds': 8})
        card['continuation_budget']['list_cost_usd'] = 50
        with self.assertRaises(ValueError): recovery.require_restart_stop(card, [])
        self.assertFalse(recovery.require_restart_stop(card, ['--case-budget', '60']))
        self.assertFalse(recovery.require_holder_stop(card, ['--case-budget=60'], 'case'))
        # Stop eligibility is separate from cumulative ledger/limit authorization.
        self.assertEqual(card['continuation_budget']['list_cost_usd'], 50)


if __name__ == '__main__': unittest.main()
