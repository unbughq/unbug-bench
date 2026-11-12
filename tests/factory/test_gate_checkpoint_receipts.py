"""A finished gate checkpoint is kept in c.work/gate-checkpoints and skipped on retry; any input change reruns."""
import fnmatch
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin'), str(ROOT / 'tests/factory')]
import run
from checkpoint_evidence import publish
from test_invalid_runs import batch, PRACTICE


class GateCheckpointReceipts(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(run, 'BENCH', ROOT), patch.object(run, 'case_budget_boundary')):
            p.start(); self.addCleanup(p.stop)
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name)
        case = self.work / 'case'; case.mkdir()
        for name, content in PRACTICE['files'].items():
            path = case / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
        self.c = SimpleNamespace(work=self.work, case=case, seed=42, card={'gates': {}}, manifest0='b1',
            args=run.argument_parser().parse_args([]))
        self.out = self.work / 'out'; self.out.mkdir()
        summary, records = batch('reference')
        self.runs = summary['runs']
        for n, row in enumerate(records, 1): (self.out / f'{n:02}.json').write_text(json.dumps(row))
        (self.out / 'checkpoint.json').write_text(json.dumps(summary))
        self.receipt = publish(self.out, summary, self.runs)

    def call(self, slot=None, seed=42, label='g5-reference'):
        return run.checkpoint(self.c, [self.c.case / 'base'], self.c.case / 'guards/reference',
                              self.runs, seed, label, slot=slot)

    def shell(self):
        return patch.object(run, 'sh', side_effect=lambda *a, **k: subprocess.CompletedProcess([], 0, self.receipt, ''))

    def test_finished_checkpoint_is_not_rerun_and_gives_same_result(self):
        with self.shell() as sh:
            first = self.call()
            self.c.args.bench_workers = 4  # worker count is not part of the identity
            again = self.call()
        self.assertEqual(sh.call_count, 1)
        self.assertEqual(first, again)

    def test_survives_a_fresh_worker_that_only_has_the_snapshot(self):
        with self.shell():
            first = self.call()
        for f in self.out.glob('*.json'): f.unlink()  # the bench results are gone with the old worker
        with self.shell() as sh:
            self.assertEqual(self.call(), first)
        sh.assert_not_called()

    def test_any_input_change_reruns(self):
        with self.shell() as sh:
            self.call()
            self.call(seed=43)
            self.call(label='g5-other')
            (self.c.case / 'base/NEW').write_text('x')
            self.call()
        self.assertEqual(sh.call_count, 4)

    def test_saved_batch_with_a_missing_run_is_not_reused(self):
        with self.shell():
            self.call()
        next(self.work.glob('gate-checkpoints/*/01.json')).unlink()
        with self.shell() as sh:
            self.call()
        self.assertEqual(sh.call_count, 1)

    def test_g10_and_rerun_labels_are_never_reused(self):
        with self.shell() as sh:
            self.call(label='g10-x'); self.call(label='g10-x'); self.call(label='g11-rerun'); self.call(label='g11-rerun')
        self.assertEqual(sh.call_count, 4)

    def test_snapshot_keeps_receipts(self):
        for n in ('gate-checkpoints', 'strategy-g15-checkpoints', 'strategy-g14-checkpoints'):
            self.assertTrue(any(fnmatch.fnmatch(n, pat) for pat in run.SNAPSHOT_RETAINED), n)


if __name__ == '__main__':
    unittest.main()
