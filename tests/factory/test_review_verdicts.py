"""Reviewer decisions must be actual booleans before they can certify a case."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

import run


class ReviewVerdictTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.c = types.SimpleNamespace(work=pathlib.Path(temporary.name), card={})

    def test_boolean_approval_and_rejection_keep_their_meaning(self):
        for gate, part in ((run.g8, 'fairness'), (run.g9, 'realism')):
            for approvals, passed in (([True], True), ([True, True], True),
                                      ([False], False), ([True, False], False)):
                with self.subTest(gate=part, approvals=approvals), patch.object(
                        run, 'review', return_value=[{part: {'approve': value}} for value in approvals]):
                    ok, info = gate(self.c)
                    self.assertEqual(ok, passed)
                    self.assertEqual(info['approve'], f'{sum(approvals)}/{len(approvals)}')

    def test_malformed_votes_never_become_scored_approvals_or_rejections(self):
        for gate, part in ((run.g8, 'fairness'), (run.g9, 'realism')):
            votes = [None, {}, [], [None], ['false'], [{}], [{part: []}],
                     *[[{part: {'approve': value}}] for value in
                       ('false', 'true', 0, 1, None, [], {}, [False])]]
            for vote in votes:
                with self.subTest(gate=part, vote=vote), patch.object(run, 'review', return_value=vote):
                    with self.assertRaisesRegex(ValueError, 'invalid reviewer'):
                        gate(self.c)

    def test_invalid_later_vote_cannot_be_hidden_by_an_approval(self):
        for gate, part in ((run.g8, 'fairness'), (run.g9, 'realism')):
            with self.subTest(gate=part), patch.object(run, 'review', return_value=[
                    {part: {'approve': True}}, {part: {'approve': 'false'}}]):
                with self.assertRaises(ValueError):
                    gate(self.c)


if __name__ == '__main__':
    unittest.main()
