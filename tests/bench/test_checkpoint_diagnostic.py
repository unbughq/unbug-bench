"""Synthetic CLI budget tests: no Docker, model calls or case content."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

loader = importlib.machinery.SourceFileLoader('checkpoint_cli', str((_BENCH_ROOT / "bin" / 'checkpoint')))
spec = importlib.util.spec_from_loader(loader.name, loader)
checkpoint = importlib.util.module_from_spec(spec)
loader.exec_module(checkpoint)
import diagnostic_budget


class CheckpointDiagnosticTests(unittest.TestCase):
    def test_direct_checkpoint_uses_same_one_attempt_budget_and_one_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ['checkpoint', '--scenario', 'synthetic', '--guard', 'synthetic-guard',
                    '--runs', '99', '--seed', '11', '--claims', 'synthetic-claims', '--stress']
            process = Mock(pid=99999999, returncode=0)
            process.communicate.return_value = ('Checkpoint: synthetic-output\n', '')
            env = {'FACTORY_STRATEGY_DIAGNOSTIC': directory, 'FACTORY_STRATEGY_WORKERS': '2',
                   'FACTORY_STRATEGY_SECONDS': '3'}
            with patch.dict(os.environ, env), patch.object(checkpoint.sys, 'argv', args), patch.object(diagnostic_budget.subprocess, 'Popen', return_value=process) as launch, patch.object(diagnostic_budget.os, 'killpg'), patch.object(checkpoint.bench, 'run_case') as bench_run, contextlib.redirect_stdout(io.StringIO()) as out:
                checkpoint.main()
                bench_run.assert_not_called()
                command = launch.call_args.args[0]
                self.assertEqual(command[command.index('--runs') + 1], '1')
                self.assertEqual(command[command.index('--seed') + 1], '11')
                self.assertEqual(command[command.index('--factory-workers') + 1], '2')
                self.assertIn('--stress', command)
                child_env = launch.call_args.kwargs['env']
                self.assertFalse(any(k.startswith('FACTORY_STRATEGY_') for k in child_env), 'nested checkpoint must not charge twice')
                self.assertEqual(child_env['UNBUG_DIAGNOSTIC_PROCESS_GROUP'], '1')
                self.assertIn('not gate evidence', out.getvalue())
                # Same helper is used by strategy; another tool entry cannot spend this allowance again.
                with self.assertRaisesRegex(RuntimeError, 'allowance exhausted'):
                    diagnostic_budget.execute(['synthetic-strategy'], directory)
                self.assertEqual(launch.call_count, 1)
            status = json.loads((Path(directory) / 'status.json').read_text())
            self.assertEqual(status['status'], 'completed')
            self.assertFalse(status['gate_evidence'])


if __name__ == '__main__': unittest.main()
