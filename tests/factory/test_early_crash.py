"""Offline crash handling with synthetic gates, checkpoints and live windows only."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse, json, pathlib, subprocess, sys, tempfile, types, unittest
from unittest.mock import AsyncMock, Mock, patch
import run
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'bin'))
from test_strategy import strategy


class EarlyCrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        c = self.c = run.Ctx(); c.work = pathlib.Path(self.temp.name)
        c.case = c.work / 'case'; c.case.mkdir(); (c.case / 'answer-key.json').write_text('{}')
        (c.work / 'logs').mkdir()
        c.card = {'gates': {}}; c.case_id = 'synthetic'; c.audit_gates = ['G15']
        c.args = argparse.Namespace(dry_run=False, resume=False)
        for name, value in (('SEALED', c.work / 'progress'), ('EARLY_GATES', ['G3'])):
            p = patch.object(run, name, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(run, 'case_hash', return_value='synthetic'); p.start(); self.addCleanup(p.stop)

    def public(self):
        return json.dumps(self.c.card) + (self.c.work / 'progress/synthetic.progress.json').read_text() + (self.c.work / 'logs/runner.log').read_text()

    def test_crash_then_pass_retries_and_continues(self):
        with patch.object(run.GatePipeline, 'check', side_effect=[RuntimeError('private cause'), (True, {}), (True, {})]) as gate:
            self.assertIsNone(run.early_checks(self.c))
        self.assertEqual([a.args[1] for a in gate.call_args_list], ['G15', 'G15', 'G3'])
        self.assertEqual(set(self.c.early), {'G15', 'G3'})
        self.assertTrue(self.c.card['early_gates']['G15']['ok'])
        self.assertNotIn('private cause', self.public())

    def test_double_crash_stops_without_writer_or_more_automatic_attempts(self):
        from run_validity import InfrastructureExhausted
        with patch.object(run.GatePipeline, 'check', side_effect=RuntimeError('private cause')) as gate:
            with self.assertRaises(InfrastructureExhausted): run.early_checks(self.c)
            with self.assertRaises(InfrastructureExhausted): run.early_checks(self.c)
        self.assertEqual(gate.call_count, 2)
        self.assertEqual(self.c.early, {})
        for attempt in (1, 2):
            detail = json.loads((self.c.work / f'gate-details/G15.crash-{attempt}.json').read_text())
            self.assertEqual(detail['error'], 'RuntimeError')
            self.assertNotIn('private cause', self.public())
        progress = json.loads((self.c.work / 'progress/synthetic.progress.json').read_text())
        self.assertEqual(progress['stages']['early:G15']['status'], 'interrupted')

    def test_normal_failure_still_returns_writer_problems(self):
        with patch.object(run.GatePipeline, 'check', return_value=(False, {'problem': 'synthetic defect'})) as gate:
            problems = run.early_checks(self.c)
        self.assertIn('early check G15 failed:', problems[0]); self.assertIn('synthetic defect', problems[0])
        self.assertEqual(gate.call_count, 1); self.assertEqual(self.c.early, {})
        self.assertFalse((self.c.work / 'gate-details').exists())

    def test_budget_and_interrupt_are_not_retried(self):
        for error in (run.BudgetError('time_limit'), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__), patch.object(run.GatePipeline, 'check', side_effect=error) as gate:
                with self.assertRaises(type(error)): run.early_checks(self.c)
                self.assertEqual(gate.call_count, 1)
        self.assertFalse((self.c.work / 'gate-details').exists())

    def test_full_gate_crash_is_sealed_and_operational(self):
        for resume in (False, True):
            self.c.args.resume = resume
            with patch.object(run.GatePipeline, 'check', side_effect=RuntimeError('private full cause')):
                run.validate_and_repair(self.c)
                self.assertTrue(self.c.stopped)
                self.assertEqual(self.c.card['terminal_stop'], 'infrastructure_exhausted')
                self.assertNotIn('failed_gate', self.c.card)
                self.assertNotIn('failed_detail', self.c.card)
            detail = json.loads((self.c.work / 'gate-details/G15.crash-1.json').read_text())
            self.assertEqual(detail['message'], 'private full cause')
            self.assertNotIn('private full cause', self.public())

    def test_crash_detail_is_bounded(self):
        from run_validity import InfrastructureExhausted
        with patch.object(run.GatePipeline, 'check', side_effect=RuntimeError('x' * 30000)):
            with self.assertRaises(InfrastructureExhausted): run.early_checks(self.c)
        detail = json.loads((self.c.work / 'gate-details/G15.crash-1.json').read_text())
        self.assertEqual(len(detail['message']), 20000)
        self.assertLessEqual(len(detail['traceback']), 20000)


class StrategyCrashTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)

    def checkpoint(self, process):
        with patch.object(strategy.processes, 'run', return_value=process):
            with self.assertRaises(RuntimeError) as error:
                strategy.checkpoint([self.root], self.root, {}, 1, 1, 'synthetic')
        return str(error.exception)

    def test_checkpoint_nonzero_and_missing_receipt_keep_output_tails(self):
        for code in (7, 0):
            with self.subTest(code=code):
                message = self.checkpoint(subprocess.CompletedProcess([], code, 'o' * 5000 + 'stdout cause', 'e' * 5000 + 'stderr cause'))
                for text in (f'returncode={code}', 'stdout cause', 'stderr cause'):
                    self.assertIn(text, message)
                self.assertNotIn('o' * 4001, message); self.assertNotIn('e' * 4001, message)

    def test_checkpoint_invalid_verdict_keeps_counts_and_evidence(self):
        evidence = self.root / 'checkpoint.json'
        evidence.write_text(json.dumps({'runs': 3, 'error_runs': 2, 'invalid_runs': 1}))
        message = self.checkpoint(subprocess.CompletedProcess([], 0, f'stdout cause\nCheckpoint: {evidence}\n', 'stderr cause'))
        for text in ('runs=3', 'error_runs=2', 'invalid_runs=1', str(evidence), 'returncode=0', 'stderr cause', 'stdout cause'):
            self.assertIn(text, message)

    def silent(self, window):
        task = self.root / 'harbor/synthetic'; task.mkdir(parents=True)
        (task / 'task.toml').touch()
        spec = task / 'steps/quiet/window.json'; spec.parent.mkdir(parents=True); spec.write_text('{"synthetic": true}')
        bench = types.SimpleNamespace(reset=Mock(), RESULTS=self.root, load_scenario=Mock())
        with patch.dict(sys.modules, {'bench': bench, 'silent_window': types.SimpleNamespace(run_window=window)}):
            with self.assertRaises(RuntimeError) as error:
                strategy.silent_checkpoint(self.root, {'id': 'quiet', 'name': 'quiet'}, [], self.root, {}, False)
        return str(error.exception)

    def test_silent_invalid_verdict_keeps_counts_and_evidence(self):
        message = self.silent(AsyncMock(return_value={'runs': 3, 'error_runs': 2, 'invalid_runs': 1,
                                                     'errors': [{'message': 'synthetic window cause'}]}))
        for text in ('runs=3', 'error_runs=2', 'invalid_runs=1', 'checkpoint.json', 'synthetic window cause'):
            self.assertIn(text, message)

    def test_silent_command_failure_keeps_both_output_tails(self):
        process = types.SimpleNamespace(returncode=7, communicate=AsyncMock(return_value=(b'stdout cause', b'stderr cause')))
        async def window(environment, spec):
            result = await environment.exec('synthetic')
            if result.return_code: raise RuntimeError(result.stderr or result.stdout)
        with patch.object(strategy.processes, 'shell', AsyncMock(return_value=subprocess.CompletedProcess('synthetic', 7, b'stdout cause', b'stderr cause'))):
            message = self.silent(window)
        for text in ('returncode=7', 'stdout cause', 'stderr cause'):
            self.assertIn(text, message)


if __name__ == '__main__': unittest.main()
