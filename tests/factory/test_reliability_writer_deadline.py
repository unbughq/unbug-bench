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

    def test_freshness_runs_in_the_stress_step_not_the_writer_window(self):
        # 1bb2ad, 15 November: writer round 6 validated with too little of its 4 h left for the freshness
        # check that followed, which no handback estimate counted; the step hit its deadline ($13.22 lost).
        from durable.contract import Outcome
        h = self.harness()
        now = [1000.0]
        MIN = 60.0
        durations = iter([90 * MIN, 120 * MIN])   # 150 min left after cycle 1: enough for cycle 2
        def model(c, models, text, cwd, name):
            now[0] += next(durations)
            (c.case / 'repair.txt').write_text(name)
        def freshness(c):   # searches, retrieval and review: longer than the 30 min the writer has left
            now[0] += 45 * MIN
            return True, {}
        h.ensure_freshness.side_effect = freshness
        h.early_checks.side_effect = [['early check G4 failed: synthetic'], None]
        deadline = now[0] + 240 * MIN
        h.c.engine = types.SimpleNamespace(deadline_monotonic=deadline, source_binding={'feedback': 'f'})
        with patch.object(run.time, 'monotonic', lambda: now[0]), patch.object(run, 'opencode', model):
            result = run.engine_writer_round(h.c, 6, run._feedback('stress', ['A synthetic defect.']))
        self.assertEqual(result, {'outcome': Outcome.OK, 'reason': 'writer:validated'})
        h.ensure_freshness.assert_not_called()
        self.assertLessEqual(now[0], deadline)
        # The next step, STRESS, runs it in its own timed window before any attack.
        order = []
        h.ensure_freshness.side_effect = lambda c: order.append('freshness')
        def attack(c, n, report, receipt, completed):
            order.append('attack')
            report.write_text('{}')
        with patch.object(run, 'stress_categories', attack), patch.object(run, 'attack_report', return_value=None):
            run.engine_stress_round(h.c, 6)
        self.assertEqual(order, ['freshness', 'attack'])
        self.assertEqual([(r['step'], r['status']) for r in h.c.card['phase_times'] if r['phase'] == 'freshness'],
                         [('stress', 'completed')])
        # A public match still skips the attack (GATES then fails G2).
        order.clear()
        h.ensure_freshness.side_effect = lambda c: (order.append('freshness'),
            c.card.__setitem__('admission_freshness', {'outcome': 'public_match'}))[-1]
        with patch.object(run, 'stress_categories', lambda *a: order.append('attack')):
            self.assertEqual(run.engine_stress_round(h.c, 6), {'outcome': Outcome.OK, 'reason': 'stress:public_match'})
        self.assertEqual(order, ['freshness'])


if __name__ == '__main__':
    unittest.main()
