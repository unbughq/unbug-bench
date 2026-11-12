"""A silent writer route costs minutes at admission, not a 45-minute attempt (12 Nov, case 1110a-2)."""
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory")]
os.environ.setdefault("BENCH", str(ROOT))
import model_runtime  # noqa: E402

FREE = 'opencode/deepseek-v4.1-flash-free'


class SilentWriterRoute(unittest.TestCase):
    def test_a_stalled_selection_call_moves_to_the_next_route(self):
        for label in ('stalled', 'timeout'):
            self.assertEqual(model_runtime.call_failure_reason(label, FREE, 'builder-selection-1'), 'outage')
            self.assertEqual(model_runtime.call_failure_reason(label, FREE, 'builder-provider-preflight'), 'outage')

    def test_other_calls_keep_stopping_on_a_stall(self):
        # A tester's stall is a scored result (calibration no_progress_limit), a writer round is long work.
        for name in ('builder-1', 'strong-calibrator-1', 'attacker-1', 'reviewer-provider-preflight'):
            self.assertIsNone(model_runtime.call_failure_reason('stalled', FREE, name))
        self.assertIsNone(model_runtime.call_failure_reason('stalled', FREE))

    def test_selection_gets_a_ten_minute_no_progress_limit(self):
        self.assertEqual(model_runtime.SHORT_CALL_NO_PROGRESS_MINUTES, 10)
        self.assertTrue(model_runtime.short_call('builder-selection-3'))
        self.assertFalse(model_runtime.short_call('builder-1'))

    def test_the_writer_route_is_preflighted_first(self):
        import run
        names = []
        c = SimpleNamespace(card={}, case='/', models={'builder': [FREE], 'attacker': ['claude/claude-opus-5-5'],
                                                      'strong_calibrator': ['claude/claude-opus-5-5'],
                                                      'easy_calibrator': ['openrouter/z-ai/glm-5.3-flash'],
                                                      'reviewers': [['opencode/glm-5.3-flash-free']]})
        saved = run.opencode
        run.opencode = lambda c, chain, text, cwd, name, **kw: names.append((name, chain)) or 0
        try:
            run.provider_preflight(c)
        finally:
            run.opencode = saved
        self.assertEqual(names[0], ('builder-provider-preflight', [FREE]))

    def test_a_case_with_a_statement_never_calls_the_writer_so_it_is_not_preflighted(self):
        import run, tempfile
        names = []
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "statement.md").write_text("x")
            c = SimpleNamespace(card={}, case=Path(t), models={'builder': [FREE], 'attacker': ['claude/claude-opus-5-5'],
                                                              'strong_calibrator': ['claude/claude-opus-5-5'],
                                                              'easy_calibrator': ['openrouter/z-ai/glm-5.3-flash'],
                                                              'reviewers': [['opencode/glm-5.3-flash-free']]})
            saved = run.opencode
            run.opencode = lambda c, chain, text, cwd, name, **kw: names.append(name) or 0
            try:
                run.provider_preflight(c)
            finally:
                run.opencode = saved
        self.assertNotIn('builder-provider-preflight', names)


if __name__ == "__main__":
    unittest.main()
