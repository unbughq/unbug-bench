"""A persisted exhausted stress category fails before the bench prepare; an unfinished diagnostic still retries."""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory'), str(ROOT / 'tests/bench')]
import run
from budget import BudgetError
from ordinary_retry import digest
from registry import atomic_json
import test_stress_loop


class ExhaustedStressFailsFast(unittest.TestCase):
    harness = test_stress_loop.StressLoopTests.harness

    def persist(self, h, *, blocking=()):
        directory = h.c.work / 'attacks' / 'round-1-categories' / digest(run.attack_binding(h.c))
        directory.mkdir(parents=True)
        out = directory / 'wrong_fixes-0.json'
        raw = json.dumps({'blocking': list(blocking)}).encode()
        out.write_bytes(raw)
        rows = {'wrong_fixes': {'complete': False, 'done': [], 'exhausted': True,
                                'results': [{'file': out.name, 'sha256': hashlib.sha256(raw).hexdigest()}]}}
        atomic_json(directory / 'state.json', {'version': 1, 'binding': run.attack_binding(h.c), 'categories': rows})

    def test_exhausted_category_raises_before_engine_prepare_bench(self):
        h = self.harness()
        self.persist(h)
        with self.assertRaises(BudgetError) as caught:
            run.engine_stress_round(h.c, 1)
        self.assertEqual(str(caught.exception), 'stress_validation_exhausted')
        h.engine_prepare_bench.assert_not_called()

    def test_exhausted_category_with_findings_in_hand_still_runs(self):
        h = self.harness()
        self.persist(h, blocking=['a real finding'])
        with patch.object(run, 'stress_categories', side_effect=RuntimeError('reached')):
            with self.assertRaises(RuntimeError):
                run.engine_stress_round(h.c, 1)
        h.engine_prepare_bench.assert_called_once()

    def test_unfinished_diagnostic_alone_is_not_failed_early(self):
        h = self.harness()
        budget = h.c.work / 'diagnostic-budgets' / 'attacker-1'
        budget.mkdir(parents=True)
        (budget / 'claimed').write_text('1')
        with patch.object(run, 'stress_categories', side_effect=RuntimeError('reached')):
            with self.assertRaises(RuntimeError):
                run.engine_stress_round(h.c, 1)
        h.engine_prepare_bench.assert_called_once()


if __name__ == '__main__':
    unittest.main()
