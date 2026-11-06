"""Scientific entry points survive removal of the legacy case lifecycle."""
import ast
import contextlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import run
from run_validity import InvalidInfra


class EngineRunnerCleanupTests(unittest.TestCase):
    def test_scientific_modules_do_not_import_retired_lifecycle(self):
        retired = {'durable_checkpoint', 'late_recovery', 'restore_ledger', 'founder_ruling',
                   'founder_decisions', 'ttl_continuation', 'job_config', 'job_authority',
                   'factory_waste', 'extension_package', 'diagnosis_dispatch', 'late_rehearsal'}
        for name in ('run.py', 'gate_pipeline.py'):
            tree = ast.parse((ROOT / 'factory' / name).read_text())
            for node in ast.walk(tree):
                imports = ([node.module] if isinstance(node, ast.ImportFrom) else
                           [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                self.assertFalse(retired.intersection(imports), name)
            self.assertNotIn('model_runtime.factory_job', ast.unparse(tree))

    def test_main_refuses_legacy_execution_before_creating_work(self):
        with patch.object(sys, 'argv', ['run.py', '--source', 'port']), \
                contextlib.redirect_stderr(io.StringIO()), patch.object(run, 'bench_manifest') as manifest:
            with self.assertRaises(SystemExit) as caught:
                run.main()
        self.assertEqual(caught.exception.code, 2)
        manifest.assert_not_called()

    def test_engine_gate_infrastructure_failure_can_run_again_on_next_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            c = SimpleNamespace(work=work, case=work / 'case', engine=object(),
                                args=run.argument_parser().parse_args([]),
                                card={'gates': {}}, audit_gates=['G1'])
            c.case.mkdir()
            pipeline = run._gate_pipeline()
            pipeline.case_hash = lambda c: 'synthetic-case'
            pipeline.evaluate = Mock(side_effect=InvalidInfra('synthetic missing evidence'))
            pipeline.publish = pipeline.log = pipeline.budget_boundary = lambda *a: None
            with patch('gate_state.inputs', return_value={}), patch('durable.checkpoints.gate_call', side_effect=lambda c, gate, invoke, binding: invoke()):
                for attempt in range(2):
                    c.card = {'gates': {}}
                    pipeline.run(c)
                    self.assertEqual(c.card['gates'], {'G1': 'invalid-infra'})
                    self.assertNotIn('failed_gate', c.card)
                    self.assertNotIn('G1', c.card.get('gate_results', {}))
            self.assertEqual(pipeline.evaluate.call_count, 2)
            self.assertFalse((work / 'infra-attempts.json').exists())

    def test_gate_rejection_never_triggers_local_writer_repair(self):
        c = SimpleNamespace()
        with patch.object(run, 'run_gates') as gates:
            run.validate_and_repair(c)
        gates.assert_called_once_with(c)


if __name__ == '__main__':
    unittest.main()
