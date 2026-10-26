"""Negative controls retain their fault while isolating workflow compensation."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import importlib.machinery
import pathlib
import subprocess
import tempfile
import unittest
import contextlib
import io
import sys
from unittest.mock import patch

ROOT = _BENCH_ROOT
negative = importlib.machinery.SourceFileLoader('verify_negative', str(ROOT / 'bin/verify-negative')).load_module()


class NegativeProbeTests(unittest.TestCase):
    def test_parallel_worker_failure_keeps_the_outcome_marker(self):
        failed = subprocess.CompletedProcess(['worker'], 1,
            stdout='negative-probe outcome=invalid-probe\nEvidence: unused\n', stderr='failed shape\n')
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, patch.object(negative.bench, 'RESULTS', pathlib.Path(tmp)), \
                patch.object(sys, 'argv', ['verify-negative', '--factory-workers', '2']), \
                patch.object(negative.subprocess, 'run', return_value=failed), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                negative.main()
            self.assertFalse(pathlib.Path(tmp, 'negative-tests.json').exists())
        self.assertIn('negative-probe outcome=invalid-probe', output.getvalue())
        self.assertNotIn('outcome=cheat-pass', output.getvalue())

    def test_checkpoint_prerequisite_is_scoped_and_applies(self):
        probes = {name: query for name, query, *_ in negative.PROBES}
        scoped = {'refuse-low-stock', 'off-by-one', 'reservation-sum-only'}
        for name, query in probes.items():
            with self.subTest(probe=name):
                patch = query.get('app.patch', '') if isinstance(query, dict) else ''
                self.assertEqual('reference-checkpoints' in patch, name in scoped)
                if name in scoped:
                    with tempfile.TemporaryDirectory() as tmp:
                        subprocess.run(['git', 'apply', '-'], input=patch, text=True, cwd=tmp, check=True)
                        self.assertIn('import "../reference-checkpoints"', pathlib.Path(tmp, 'src/api/middlewares.ts').read_text())
                        reference = (ROOT / 'guards/reference/app.patch').read_text()
                        module = reference[reference.index('diff --git a/src/reference-checkpoints.ts'):]
                        self.assertIn(module, patch)
                        self.assertNotIn('errorHandler', patch)
        self.assertIn('IF live + owed >= stock', probes['off-by-one']['db.sql'])
        self.assertEqual(probes['reservation-sum-only']['db.sql'], negative.RESERVATION_SUM_ONLY + '\n')

    def test_shape_failure_is_invalid_and_actual_pass_is_separate(self):
        record = {'errors': [], 'checker': {'valid': True, 'sequential_oversold': True,
                  'units_sold_s': 12, 'pass': False}}
        summary = {'pass': 0, 'runs': 1}
        self.assertEqual(negative.probe_outcome(summary, [record], negative.sequential_oversell)[0], 'rejected')
        record['traffic'] = {'response': {'data': {'message': 'Updating Status from "ok" to "temp_failure" is not allowed.'}}}
        self.assertEqual(negative.probe_outcome(summary, [record], negative.sequential_oversell)[0], 'invalid-probe')
        record.pop('traffic')
        record['checker']['units_sold_s'] = 5
        self.assertEqual(negative.probe_outcome(summary, [record], negative.sequential_oversell)[0], 'invalid-probe')
        record['checker']['pass'] = True
        self.assertEqual(negative.probe_outcome(summary, [record], negative.sequential_oversell)[0], 'cheat-pass')


if __name__ == '__main__':
    unittest.main()
