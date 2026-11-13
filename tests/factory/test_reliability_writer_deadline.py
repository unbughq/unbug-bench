"""A writer repair cycle is not started when the longest cycle so far would not fit before the step deadline."""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory'), str(ROOT / 'tests/bench')]
import run
import test_stress_loop


class WriterDeadline(unittest.TestCase):
    harness = test_stress_loop.StressLoopTests.harness

    def test_next_cycle_is_sized_by_the_longest_cycle_not_the_last(self):
        from durable.policy import WRITER_HANDBACK
        h = self.harness()
        h.c.args.rounds = 4
        now = [1000.0]
        MIN = 60.0
        durations = iter([100 * MIN, 30 * MIN, 100 * MIN])   # cycle 1 long, cycle 2 short, cycle 3 long
        calls = []
        def model(c, models, text, cwd, name):
            calls.append(name)
            now[0] += next(durations)
            (c.case / 'repair.txt').write_text(name)
        h.early_checks.return_value = ['early check G4 failed: synthetic']
        # 4 h 5 min of the attempt are left at the start; cycle 1 leaves 145 min, enough for another. After
        # cycle 2 (130 min in), 115 min remain:
        # more than 1.25 x the last cycle (30 min) plus the 15 min reserve, less than 1.25 x the 100 min one.
        h.c.engine = types.SimpleNamespace(deadline_monotonic=now[0] + 245 * MIN, source_binding={'feedback': 'f'})
        with patch.object(run.time, 'monotonic', lambda: now[0]), patch.object(run, 'opencode', model):
            result = run.engine_writer_round(h.c, 2, run._feedback('stress', ['A synthetic defect.']))
        self.assertEqual(result['reason'], WRITER_HANDBACK)
        self.assertEqual(calls, ['builder-2', 'builder-2-fix-1'])   # no third cycle that could not finish


if __name__ == '__main__':
    unittest.main()
