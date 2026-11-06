"""Offline qualified-path replays over saved practice bytes and the 5813be ledger.

Authority envelopes, model answers and gate failures are authored controls.
No live qualification or Murphy closure is claimed.
"""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import budget
import free_models
import model_runtime
import registry
import run
import test_stream_d_runtime as runtime


class QualifiedAllowanceTests(unittest.TestCase):
    patch = runtime.RuntimeTests.patch
    setUp = runtime.RuntimeTests.setUp


    def test_model_selection_never_consults_cohort_for_batch(self):
        with patch.object(free_models, 'apply', side_effect=AssertionError('legacy cohort')):
            selected = model_runtime.select_models(self.c, log=lambda *a: None)
        self.assertEqual(len(selected['builder']), 1)
        self.assertNotIn('model_transition', self.c.card)



if __name__ == '__main__': unittest.main()
