"""Resume reuse: a passed G7, the early probe and finished G10 tries (synthetic, no runtime workloads)."""
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

import calibration
import gate_state
import run


class G7ReuseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.c = c = types.SimpleNamespace(work=self.root / 'work', seed=7, manifest0='m',
            args=types.SimpleNamespace(runs=10, scenario_runs=3, dry_run=False, resume=True, bench_workers=1),
            card={'gates': {}}, models={})
        c.case = c.work / 'case'; (c.case / 'base').mkdir(parents=True); (c.case / 'base/judge.py').write_text('judge')
        self.runner = self.root / 'run.py'
        self.runner.write_text('SEED = 7919\ndef g7(c):\n    return SEED\n')
        p = patch.object(gate_state, 'RUNNER', self.runner, create=True); p.start(); self.addCleanup(p.stop)
        self.info = {'seed': 7926, 'plain_app_broke': '10/10', 'reference_fix': '10/10', 'cheats_passed': '0/38'}

    def save(self):
        evidence = self.root / 'results/g7.json'; evidence.parent.mkdir(exist_ok=True); evidence.write_text('{}')
        gate_state.save(self.c, 'G7', self.info, gate_state.fingerprint(self.c, 'G7', self.root), {}, self.root)

    def test_identical_inputs_reuse_and_restore_the_card(self):
        self.save()
        with patch.object(run, 'BENCH', self.root), patch.object(run, 'g7') as gate:
            ok, info = run.checked_gate(self.c, 'G7')
        self.assertTrue(ok); gate.assert_not_called()
        self.assertTrue(info['reused_verified_evidence'])
        self.assertEqual(self.c.card['flakiness_rerun'], self.info)

    def test_verdict_relevant_changes_rerun(self):
        def bench_file(): (self.root / 'bin').mkdir(exist_ok=True); (self.root / 'bin/bench.py').write_text('x')
        def guard_file(): (self.root / 'guards').mkdir(exist_ok=True); (self.root / 'guards/g.sql').write_text('x')
        changes = {
            'case file': lambda: (self.c.case / 'base/judge.py').write_text('other'),
            'bench judge': bench_file,
            'judge source': lambda: self.runner.write_text('SEED = 1\ndef g7(c):\n    return SEED\n'),
            'seed': lambda: setattr(self.c, 'seed', 8),
            'runs': lambda: setattr(self.c.args, 'runs', 11),
            'guards': guard_file,
        }
        for name, change in changes.items():
            with self.subTest(name):
                self.setUp(); self.save(); change()
                self.assertIsNone(gate_state.load(self.c, 'G7', self.root))


class TesterSlotTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.work = pathlib.Path(tmp.name)
        self.path = self.work / "strong_calibrator/results.json"

    def series(self, slot, tries=2, model="m"):
        return calibration.AttemptSeries(self.path, {"version": 4, "model": model, "slot": slot}, self.work, tries, "m")

    def finish_one(self, series):
        ws = series.workspace(1); (ws / "guard").mkdir(parents=True); (ws / "guard/db.sql").write_text("-- guard")
        series.commit({"try": 1, "solved": True, "guard_submitted": True, "guard": str(ws / "guard"), "stop_reason": "completed"}, ws)

    def test_finished_try_survives_another_worker_size(self):
        self.finish_one(self.series(4))                            # 4 bench workers: tester on slot 4
        self.assertEqual(list(self.series(8).remaining()), [2])    # 8 workers: slot 8
        self.assertEqual(list(self.series(0).remaining()), [2])    # serial: slot 0

    def test_other_changes_still_invalidate(self):
        self.finish_one(self.series(4))
        self.assertEqual(list(self.series(4, model="other").remaining()), [1, 2])

    def test_unfinished_attempt_stays_on_its_slot(self):
        series = self.series(4)
        ws = series.path.parent / "try-1"; (ws / "guard").mkdir(parents=True); (ws / "guard/db.sql").write_text("g")
        series.save_pending(1, ws, "timeout")
        self.assertIsNotNone(self.series(4).pending(1))
        self.assertIsNone(self.series(8).pending(1))


class EarlyProbeResumeTests(unittest.TestCase):
    def gate(self, exists):
        c = types.SimpleNamespace(args=types.SimpleNamespace(dry_run=False))
        with patch.object(run, 'early_probe') as probe, patch.object(run, 'strong_attempts_exist', return_value=exists), \
                patch.object(run, 'update_case_budget'), patch.object(run, 'under_engine', return_value=False), patch.object(run, 'log'):
            run._gate_completed(c, 'G5', True, True)
        return probe

    def test_probe_skipped_when_strong_attempts_exist(self):
        self.gate(True).assert_not_called()

    def test_probe_runs_otherwise(self):
        self.gate(False).assert_called_once()

    def test_strong_attempts_exist_reads_receipts_under_the_current_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp); c = types.SimpleNamespace(work=work, args=types.SimpleNamespace(pilot_runs=5))
            self.assertFalse(run.strong_attempts_exist(c))
            (work / "strong_calibrator").mkdir(); (work / "strong_calibrator/results.json").write_text("[]")
            with patch.object(run, 'calibration_identity', return_value={"slot": 0}), \
                    patch('calibration.completed_attempts', return_value=[{"try": 1}]) as kept:
                self.assertTrue(run.strong_attempts_exist(c))
            kept.assert_called_once()


if __name__ == "__main__":
    unittest.main()
