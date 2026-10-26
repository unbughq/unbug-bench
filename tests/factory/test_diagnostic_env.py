"""The model subprocess receives diagnostic limits; reviewers never inherit them."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import pathlib
import types
import unittest
import tempfile
import run
import model_runtime


class DiagnosticEnvironmentTests(unittest.TestCase):
    def test_resume_reports_consumed_allowance_even_without_status_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            c = types.SimpleNamespace(work=pathlib.Path(temp))
            self.assertIn('AVAILABLE', run.attack_diagnostic_context(c, 'attacker-1'))
            claim = c.work / 'diagnostic-budgets' / 'attacker-1' / 'claimed'
            claim.mkdir(parents=True)
            message = run.attack_diagnostic_context(c, 'attacker-1')
            self.assertIn('EXHAUSTED', message)
            self.assertIn('Record unexecuted checks in unfinished_validation', message)
            self.assertTrue(claim.is_dir())
            self.assertIn('AVAILABLE', run.attack_diagnostic_context(c, 'attacker-2'))

    def test_author_allowance_is_stable_and_role_scoped(self):
        c = types.SimpleNamespace(work=pathlib.Path('/synthetic/work'),
                                  args=types.SimpleNamespace(bench_workers=2))
        original = {'PATH': '/bin', 'FACTORY_STRATEGY_SECONDS': '99999'}
        writer = model_runtime.diagnostic_env(c, 'builder-2', 'writer', original)
        self.assertEqual(writer['FACTORY_STRATEGY_SECONDS'], '300')
        self.assertEqual(writer['FACTORY_STRATEGY_WORKERS'], '2')
        self.assertEqual(writer, model_runtime.diagnostic_env(c, 'builder-2', 'writer', original))
        attacker = model_runtime.diagnostic_env(c, 'attacker-2', 'stress_tester', original)
        self.assertNotEqual(writer['FACTORY_STRATEGY_DIAGNOSTIC'], attacker['FACTORY_STRATEGY_DIAGNOSTIC'])
        self.assertEqual(model_runtime.diagnostic_env(c, 'reviewer-1', 'reviewer', writer), {'PATH': '/bin'})
        self.assertEqual(original['FACTORY_STRATEGY_SECONDS'], '99999')


if __name__ == '__main__':
    unittest.main()
