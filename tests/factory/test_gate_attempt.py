"""One lifecycle contract for early and full gate callers; no external workloads."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import unittest
from unittest.mock import Mock
import gate_attempt


class BudgetStop(Exception):
    pass


class AttemptTests(unittest.TestCase):
    def run_attempt(self, effects, **options):
        invoke, publish, crash = Mock(side_effect=effects), Mock(), Mock()
        result = gate_attempt.execute(invoke, publish=publish, record_crash=crash,
                                      interruption=BudgetStop, **options)
        return result, invoke, publish, crash

    def test_rejection_is_not_retried(self):
        result, invoke, publish, crash = self.run_attempt([(False, {'wrong': 1})], attempts=2)
        self.assertFalse(result.ok)
        self.assertFalse(result.crashed)
        self.assertEqual(invoke.call_count, 1)
        crash.assert_not_called()
        self.assertEqual(publish.call_args.args[0], 'failed')

    def test_retry_success_has_one_lifecycle_and_retains_crash(self):
        error = RuntimeError('private detail')
        result, invoke, publish, crash = self.run_attempt([error, (True, {})], attempts=2)
        self.assertTrue(result.ok)
        self.assertEqual(invoke.call_count, 2)
        crash.assert_called_once_with(error)
        self.assertEqual([c.args[0] for c in publish.call_args_list], ['running', 'completed'])

    def test_exhausted_crash_contains_only_type(self):
        result, _, publish, crash = self.run_attempt([ValueError('private'), ValueError('secret')], attempts=2)
        self.assertTrue(result.crashed)
        self.assertEqual(result.info, {'error': 'ValueError'})
        self.assertEqual(crash.call_count, 2)
        self.assertNotIn('secret', str(publish.call_args_list))

    def test_interruptions_never_retry_or_become_rejections(self):
        for error in (BudgetStop('limit'), KeyboardInterrupt(), SystemExit(2)):
            invoke, publish, crash = Mock(side_effect=error), Mock(), Mock()
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                gate_attempt.execute(invoke, publish=publish, record_crash=crash,
                                     interruption=BudgetStop, attempts=2)
            self.assertEqual(invoke.call_count, 1)
            crash.assert_not_called()
            self.assertEqual(publish.call_args.args[0], 'interrupted')

    def test_early_review_policy_preserves_raised_crash(self):
        with self.assertRaisesRegex(RuntimeError, 'private'):
            self.run_attempt([RuntimeError('private')], raise_crash=True)

    def test_reused_evidence_is_published(self):
        for flag in ('reused_verified_evidence', 'reused_from_early_check'):
            result, _, publish, _ = self.run_attempt([(True, {flag: True})])
            self.assertTrue(result.ok)
            self.assertTrue(publish.call_args.args[2])


if __name__ == '__main__':
    unittest.main()
