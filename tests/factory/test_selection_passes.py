"""The idea-picker runs in bounded passes and continues from its own notes (7 November)."""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'factory'), str(Path(__file__).resolve().parents[2] / 'bin')]
import run
from budget import BudgetError


class SelectionPasses(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        work = Path(self.tmp.name)
        self.c = types.SimpleNamespace(work=work, case=work / 'case', models={'builder': ['m']},
                                       args=types.SimpleNamespace(max_role_calls=400))
        self.c.case.mkdir()
        self.calls = []

    def selection(self, outcomes):
        def call(c, models, text, cwd, name, **kw):
            self.calls.append((name, c.args.max_role_calls, 'selection_progress_path' in text))
            outcome = outcomes.pop(0)
            if outcome == 'cap':
                (c.case / 'selection.json').write_text('{"sketches": ["mechanism A, rejected: public"]}')
                raise BudgetError('call_limit')
            (c.case / 'statement.md').write_text('statement')
            return 0
        prompts = patch.object(run, 'prompt', lambda role, extra: str(extra))
        context = patch.object(run, 'selection_context', lambda c, occupied, **more: more)
        with patch.object(run, 'opencode', call), prompts, context:
            return run.select_candidate(self.c, {})

    def test_a_capped_pass_continues_from_its_notes(self):
        self.assertEqual(self.selection(['cap', 'done']), 0)
        self.assertEqual(self.calls, [('builder-selection', 40, False), ('builder-selection-pass-2', 40, True)])
        self.assertEqual(self.c.args.max_role_calls, 400)   # the cap applies to selection alone

    def test_a_retried_attempt_resumes_from_retained_notes(self):
        (self.c.case / 'selection.json').write_text('{"sketches": []}')
        self.assertEqual(self.selection(['done']), 0)
        self.assertEqual(self.calls, [('builder-selection-pass-1', 40, True)])

    def test_passes_are_bounded(self):
        with self.assertRaisesRegex(BudgetError, 'call_limit'):
            self.selection(['cap', 'cap', 'cap'])
        self.assertEqual(len(self.calls), run.SELECTION_PASSES)

    def test_a_cap_with_no_notes_is_not_retried(self):
        def call(c, models, text, cwd, name, **kw):
            self.calls.append(name)
            raise BudgetError('call_limit')
        with patch.object(run, 'opencode', call), patch.object(run, 'prompt', lambda r, e: ''), \
                patch.object(run, 'selection_context', lambda c, o, **m: m):
            with self.assertRaises(BudgetError):
                run.select_candidate(self.c, {})
        self.assertEqual(self.calls, ['builder-selection'])

    def test_the_prompt_tells_the_model_to_continue(self):
        text = (Path(run.__file__).parent / 'prompts' / 'selection.md').read_text()
        self.assertIn('selection_progress_path', text)
        self.assertIn('do not repeat that exploration', text)


if __name__ == '__main__':
    unittest.main()
