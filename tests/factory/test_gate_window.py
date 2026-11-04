"""Murphy 42: one monotonic window per G13/G14/G15 gate, across nested units and retries.

The clock is injected at the real processes.py seam; every unit still starts a real child process.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(Path(__file__).parent)]
os.environ['BENCH'] = str(ROOT)
import processes
import run
from test_isolation_timeouts import LOAD, worker_args

HOUR = 3600


class Clock:
    now = 1000.0
    def monotonic(self): return self.now
    def sleep(self, seconds): import time; time.sleep(seconds)


class GateWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name); (self.home / 'logs').mkdir()
        self.clock = Clock()
        patcher = patch.object(processes, 'time', self.clock); patcher.start(); self.addCleanup(patcher.stop)

    def run_gate(self, gate, units, unit_hours=1):
        c = types.SimpleNamespace(args=run.argument_parser().parse_args(worker_args()), work=self.home,
                                  case=self.home / 'case', card=LOAD('scorecard.json'), audit_gates=[gate])
        c.case.mkdir(exist_ok=True)
        c.args.agent_timeout = 4 * HOUR
        c.card['gates'] = {}
        c.case_id = c.card['case']
        started = []
        def evaluate(ctx, name):
            for unit in range(units):  # nested serial scenario/guard checkpoints
                processes.run([sys.executable, '-c', 'pass'])  # the real helper enforces the window
                started.append(unit)
                self.clock.now += unit_hours * HOUR  # mechanical work consumed by this unit
            return True, {'units': units}
        pipeline = run._gate_pipeline()
        pipeline.evaluate = evaluate
        pipeline.budget_boundary = lambda c: None
        pipeline.after_gate = Mock()
        pipeline.publish = lambda *a: None
        pipeline.run(c)
        return c, started

    def test_retry_shares_the_one_gate_window(self):
        for gate in ('G13', 'G14', 'G15'):
            with self.subTest(gate=gate):
                self.clock.now = 1000.0
                c, started = self.run_gate(gate, units=10)
                self.assertEqual(len(started), 4, 'window is 4h: a retry must not buy another one')
                self.assertEqual(c.card['terminal_stop'], 'infrastructure_exhausted')
                self.assertEqual(c.card['gates'][gate], 'invalid-infra')
                self.assertNotIn('failed_gate', c.card)
                (self.home / 'infra-attempts.json').unlink(missing_ok=True)

    def test_work_inside_the_window_passes_normally(self):
        c, started = self.run_gate('G14', units=3)
        self.assertEqual(len(started), 3)
        self.assertEqual(c.card['gates']['G14'], 'pass')


class G14ResumeTests(unittest.TestCase):
    """Real retained case and step order; only bin/checkpoint (docker bench) is replaced."""
    def test_expired_window_redoes_only_the_unit_in_flight(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name in ('bin', 'factory', 'guards', 'scenarios', 'contestants', 'harbor'):
            if (ROOT / name).exists(): (root / name).symlink_to(ROOT / name)
        (root / 'results').mkdir(); (root / 'work').mkdir()
        clock = Clock(); executed = []
        module = run.strategy_module()
        def checkpoint(scenarios, guard, report, runs, seed, label, factory_workers=1):
            processes.run([sys.executable, '-c', 'pass'])  # real window enforcement
            executed.append(label); clock.now += HOUR
            directory = root / 'results/runs' / f'unit-{len(executed)}'; directory.mkdir(parents=True)
            summary = {'runs': runs, 'error_runs': 0, 'invalid_runs': 0, 'paths': {}, 'checks': {}}
            (directory / 'checkpoint.json').write_text(json.dumps(summary))
            return {**summary, '_evidence_path': str(directory / 'checkpoint.json')}
        c = types.SimpleNamespace(args=run.argument_parser().parse_args(worker_args()), work=root / 'work',
                                  case=ROOT / 'cases/medusa-oversell-v2', seed=7, card={})
        c.args.dry_run = False; c.args.scenario_runs = 3
        module.checkpoint = checkpoint
        module.silent_checkpoint = lambda *a, **k: self.fail('unannounced live window is never cached or reached here')
        with patch.object(processes, 'time', clock), patch.object(run, 'BENCH', root), \
                patch.object(run, 'strategy_module', lambda: module):
            pipeline = run._gate_pipeline()
            for window in range(2):
                with self.assertRaises(__import__('subprocess').TimeoutExpired):
                    with processes.deadline(4 * HOUR):  # each window is the real gate allowance
                        run.g14(c)
                self.assertEqual(len(executed), 4 * (window + 1))
        self.assertEqual(len(set(executed)), len(executed), 'a completed unit was redone')
        # A third window against unchanged inputs still reuses all eight and finishes the rest.
        with patch.object(processes, 'time', clock), patch.object(run, 'BENCH', root), \
                patch.object(run, 'strategy_module', lambda: module):
            before = len(executed)
            with self.assertRaises(__import__('subprocess').TimeoutExpired):
                with processes.deadline(4 * HOUR): run.g14(c)
            self.assertEqual(len(executed) - before, 4)
        self.assertEqual(len(set(executed)), len(executed))


if __name__ == '__main__':
    unittest.main()
