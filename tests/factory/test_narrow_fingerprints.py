"""Gate fingerprints and step receipts cover verdict code only, not retry/router plumbing."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'factory'), str(Path(__file__).resolve().parents[2] / 'bin')]
import tempfile
import types
import unittest
from unittest.mock import patch

import gate_state
from durable import checkpoints as cp

SOURCE = '''
class AllowanceSpent(TimeoutError): pass
def g6(c):
    return checkpoint(c)
def checkpoint(c):
    args = ["bin/checkpoint", "--runs", 10]
    return _checkpoint_call(c, args)
def _checkpoint_call(c, args):
    return retry(args, interruption=AllowanceSpent)
'''


class Fingerprints(unittest.TestCase):
    def inputs(self, source):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'run.py'; p.write_text(source)
            return gate_state.source_inputs('g6', path=p)

    def test_plumbing_wrapper_edit_keeps_the_fingerprint(self):
        base = self.inputs(SOURCE)
        self.assertEqual(base, self.inputs(SOURCE.replace('retry(args, interruption=AllowanceSpent)', 'retry(args, 5)')))
        self.assertEqual(base, self.inputs(SOURCE.replace('pass', 'x = 1')))  # AllowanceSpent

    def test_arg_builder_edit_changes_the_fingerprint(self):
        self.assertNotEqual(self.inputs(SOURCE), self.inputs(SOURCE.replace('"--runs", 10', '"--runs", 9')))

    def test_real_gate_roots_hash_verdict_code_but_not_plumbing(self):
        for gate in ('g4', 'g5', 'g6', 'g7', 'g15'):
            found = gate_state.source_inputs(gate)
            self.assertIn('checkpoint', found, gate)
            self.assertNotIn('_checkpoint_call', found, gate)
            self.assertNotIn('AllowanceSpent', found, gate)
            self.assertNotIn('early_cheat_check', found, gate)
        self.assertIn('verdicts', gate_state.source_inputs('g6'))


class Receipts(unittest.TestCase):
    def ctx(self, work):
        return types.SimpleNamespace(work=Path(work), engine=types.SimpleNamespace(key='case/step', source_binding={}))

    def test_model_harness_release_keeps_bench_gate_receipts_only(self):
        with tempfile.TemporaryDirectory() as d:
            c = self.ctx(d)
            def dirs():
                cp._VERDICT_DIGEST.clear()
                return cp.directory(c, model=False), cp.directory(c)
            with patch.object(cp, 'MODEL_CODE', ('model_router.py',)), \
                 patch.object(cp, 'VERDICT_CODE', cp.BENCH_VERDICT_CODE + ('model_router.py',)):
                bench, model = dirs()
            with patch.object(cp, 'MODEL_CODE', ('model_runtime.py',)), \
                 patch.object(cp, 'VERDICT_CODE', cp.BENCH_VERDICT_CODE + ('model_runtime.py',)):
                bench2, model2 = dirs()
            cp._VERDICT_DIGEST.clear()
        self.assertEqual(bench, bench2)
        self.assertNotEqual(model, model2)

    def test_gate_call_keys_bench_gates_without_model_code_and_model_stages_with_it(self):
        with tempfile.TemporaryDirectory() as d:
            c = self.ctx(d)
            cp.gate_call(c, 'G4', lambda: (False, {}), 'b')   # a G4 pass lives in gate-cache alone
            cp.gate_call(c, 'G10', lambda: (True, {}), 'b')
            self.assertTrue((cp.directory(c, model=False) / 'gate-G4.json').is_file())
            self.assertTrue((cp.directory(c) / 'gate-G10.json').is_file())


if __name__ == '__main__':
    unittest.main()
