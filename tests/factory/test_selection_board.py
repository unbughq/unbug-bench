"""The writer sees occupied mechanisms before selecting; admission stays separate."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse
import json
import subprocess
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import admission
import registry
import run


class SelectionBoardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.case = self.root / 'case'; self.case.mkdir()
        self.old = self.root / 'occupied.md'; self.old.write_text('Synthetic occupied mechanism')
        self.c = types.SimpleNamespace(work=self.root, case=self.case, case_id='case-new', card={},
            models={'builder': ['claude/writer']},
            args=argparse.Namespace(source='hunt', runs=10, scenario_runs=3, statement_only=True))

    def test_board_contains_active_history_but_cannot_authorize_construction(self):
        r = registry.Registry(self.root / 'registry')
        cipher = self.root / 'old.age'; cipher.write_bytes(b'age-encryption.org/v1\nsynthetic')
        r.import_historical('case-old', cipher, statement_sha256='a' * 64)
        released = r.reserve('case-released', 'b' * 64, cipher)
        r.transition('case-released', released['reservation'], 'released')
        pending = r.reserve('case-pending', 'c' * 64, cipher)
        revision = json.loads((r.root / 'registry.json').read_text())['revision']
        board = self.root / 'board'
        r.export_board(board)
        self.assertEqual(set(admission.selection_snapshot(board, 'case-new')), {'case-old', 'case-pending'})
        self.assertEqual(json.loads((board / 'selection-board.json').read_text())['registry_revision'], revision)
        self.assertFalse((board / 'admission.json').exists())
        with self.assertRaises((OSError, ValueError)):
            admission.registry_snapshot(board, 'case-new', 'unreserved candidate')
        self.assertEqual(json.loads((r.root / 'registry.json').read_text())['entries']['case-pending'], pending)
        (board / 'case-old.statement.age').write_bytes(b'changed')
        with self.assertRaises(ValueError): admission.selection_snapshot(board, 'case-new')

    def test_first_selection_receives_board_before_model_and_still_publishes(self):
        calls = []
        def select(c, chain, text, cwd, name):
            calls.append(name)
            context = json.loads(text.split('```json\n')[-1].split('```')[0])
            self.assertEqual(context['occupied_statement_paths'], {'case-old': str(self.old)})
            self.assertIn('Read occupied_bug_board BEFORE', text)
            self.assertIn(self.old.read_text(), Path(context['occupied_bug_board']).read_text())
            (c.case / 'statement.md').write_text('Synthetic distinct candidate')
            return 0
        with patch.object(run, 'selection_statements', return_value={'case-old': str(self.old)}), \
             patch.object(run, 'opencode', select), \
             patch.object(run, 'prior_statements', side_effect=AssertionError('premature admission')):
            self.assertTrue(run.statement_precheck(self.c))
        self.assertEqual(calls, ['builder-selection'])
        self.assertEqual(self.c.card['admission']['status'], 'awaiting_shared_reservation')

    def test_missing_board_never_spends_on_first_selection(self):
        with patch.object(run, 'STATEMENTS', self.root / 'missing'), patch.object(run, 'opencode') as model:
            with self.assertRaisesRegex(run.BudgetError, 'selection_board_unavailable'):
                run.statement_precheck(self.c)
            model.assert_not_called()

    def test_actual_encrypted_board_is_opened_before_writer_selection(self):
        key = self.root / 'throwaway-key'
        subprocess.run(['age-keygen', '-o', str(key)], check=True, capture_output=True)
        recipient = subprocess.run(['age-keygen', '-y', str(key)], check=True, capture_output=True, text=True).stdout.strip()
        cipher = self.root / 'old.age'
        subprocess.run(['age', '-r', recipient, '-o', str(cipher)], input=self.old.read_bytes(), check=True, capture_output=True)
        r = registry.Registry(self.root / 'registry'); r.import_historical('case-old', cipher, 'a' * 64)
        board = self.root / 'encrypted-board'; r.export_board(board)
        def select(c, chain, text, cwd, name):
            context = json.loads(text.split('```json\n')[-1].split('```')[0])
            self.assertIn(self.old.read_text(), Path(context['occupied_bug_board']).read_text())
            self.assertEqual(Path(context['occupied_statement_paths']['case-old']).read_text(), self.old.read_text())
            (c.case / 'statement.md').write_text('Synthetic new mechanism')
            return 0
        with patch.object(run, 'STATEMENTS', board), patch.object(run, 'STATEMENTS_KEY', key), \
             patch.object(run, 'opencode', select), patch.object(run, 'prior_statements', side_effect=AssertionError('unreserved admission')):
            self.assertTrue(run.statement_precheck(self.c))
        self.assertEqual(self.c.card['selection_board']['statements'], 1)



if __name__ == '__main__': unittest.main()
