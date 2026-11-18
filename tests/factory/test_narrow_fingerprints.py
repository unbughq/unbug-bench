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


class WordingScope(unittest.TestCase):
    """gate_state.comparable leaves gate_state.NOT_MEASURED out of G4-G7 and G13-G15 reuse."""
    ROOT = Path(__file__).resolve().parents[2]
    # Reviewed mentions, none on a measurement path: a docstring; G10's helper try context; the
    # calibrators' contestant workspace (G10/G16), which withholds the private files and copies a
    # service project's own README.
    ALLOWED = {('bin/bench.py', 'load_scenario'), ('factory/durable/helper_link.py', '_try_context'),
               ('factory/calibration.py', '_PRIVATE_NAMES'), ('factory/calibration.py', 'prepare_delivery')}
    WORDING = [name for name in gate_state.NOT_MEASURED if name not in gate_state.UNREAD]

    def test_gate_identities_keep_every_case_file_they_recorded(self):
        """Gate checkpoints, step receipts and sealed audits bind gate_state.inputs: it is unchanged."""
        import run
        with tempfile.TemporaryDirectory() as d:
            c = types.SimpleNamespace(work=Path(d), seed=7, args=types.SimpleNamespace(), card={}, models={})
            c.case = c.work / 'case'
            for rel in ('BUILD-NOTES.md', 'freshness.jsonl', 'statement.md', 'README.md', 'case.json', 'promise.md',
                        'base/judge.py', 'services/a/x.py', 'docs/BUILD-NOTES.md', 'fact-sheet.md'):
                (c.case / rel).parent.mkdir(parents=True, exist_ok=True); (c.case / rel).write_text(rel)
            with patch.object(gate_state, 'RUNNER', Path(run.__file__)):
                for gate in gate_state.STAGE_DEPENDENCIES:
                    old = sorted(rel for rel in (p.relative_to(c.case).as_posix() for p in c.case.rglob('*') if p.is_file())
                                 if (gate in {'G8', 'G9'} or rel not in {'BUILD-NOTES.md', 'freshness.jsonl'})
                                 and (gate != 'G4' or rel.startswith(('base/', 'services/', 'projects/')) or rel in {'case.json', 'promise.md'}))
                    with self.subTest(gate=gate):
                        self.assertEqual([rel for rel, _ in gate_state.inputs(c, gate, c.work)['case']], old)

    def mentions(self, path, text):
        import ast
        try: tree = ast.parse(text)
        except SyntaxError: tree = None
        for node in tree.body if tree else ():
            segment = ast.get_source_segment(text, node) or ''
            name = getattr(node, 'name', None) or next((t.id for t in ast.walk(node) if isinstance(t, ast.Name)), None)
            if any(w in segment for w in self.WORDING): yield (path, name)
        if tree is None and any(w in text for w in self.WORDING): yield (path, None)

    def test_no_measurement_code_names_the_wording_files(self):
        found = set()
        for gate in ('G5', 'G6', 'G7', 'G13', 'G14', 'G15'):
            for pattern in gate_state.DEPENDENCIES[gate]:
                if not pattern.startswith(('bin/', 'factory/')): continue
                for p in gate_state.source_paths(self.ROOT, pattern):
                    if p.is_file(): found |= set(self.mentions(p.relative_to(self.ROOT).as_posix(), p.read_text(errors='replace')))
        self.assertLessEqual(found, self.ALLOWED)
        import ast
        def closure(roots, path):   # the source of every top-level name source_inputs hashes
            text, names = path.read_text(), gate_state.source_inputs(*roots, path=path)
            for node in ast.parse(text).body:
                own = {node.name} if hasattr(node, 'name') else {
                    t.id for t in ast.walk(node) if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)}
                if own & names.keys(): yield ast.get_source_segment(text, node)
        sources = [s for gate in ('G5', 'G6', 'G7', 'G13', 'G14', 'G15')
                   for s in closure((gate.lower(), *gate_state.EXTRA_ROOTS.get(gate, ())), self.ROOT / 'factory/run.py')]
        sources += closure(('ingredient_problems',), self.ROOT / 'factory/case_contract.py')
        for segment in sources:
            self.assertFalse([w for w in self.WORDING if w in segment], segment[:200])


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
            cp.gate_call(c, 'G4', lambda: (True, {}), 'b')
            cp.gate_call(c, 'G10', lambda: (True, {}), 'b')
            self.assertTrue((cp.directory(c, model=False) / 'gate-G4.json').is_file())
            self.assertTrue((cp.directory(c) / 'gate-G10.json').is_file())


if __name__ == '__main__':
    unittest.main()
