"""Real offline pool/channel/worker/ledger/artifacts handoff; Boat transport is local.

No provider or model calls. Uses the explicit practice path through ADMIT, WRITER,
STRESS and GATES (up to its Docker boundary), then reattaches after control recovery.
The DBOS kill/replay exam separately exercises workflow scheduling.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(Path(__file__).resolve().parent)]
os.environ.setdefault('BENCH', str(ROOT))

from durable import workers
from durable.contract import ArtifactKind, Outcome, Step, StepInput, StepKind, Usage, guarded_run
from durable.runtime import Runtime
from durable.engine import APP_VERSION
import test_durable_workers as support


@unittest.skipUnless(sys.platform == 'linux' and shutil.which('age'), 'Linux worker protocol and age required')
class VerticalTests(unittest.TestCase):
    def test_real_practice_handoff_and_completed_attempt_reattachment(self):
        h = support.Harness(self)
        # Only the external Boat transport and image qualification use stand-ins.
        # The worker command, release bundle, runner and baked benchmark are real.
        baked = h.boat_dir / 'images/bench-env/unbug-bench'
        shutil.rmtree(baked)
        baked.symlink_to(ROOT, target_is_directory=True)
        plumbing = h.store.put_bundle(workers.build_bundle(ROOT))
        bench = support.bench_manifest(ROOT)
        identity = h.tmp / 'restore-key'
        subprocess.run(['age-keygen', '-o', str(identity)], capture_output=True, check=True)
        identity.chmod(0o600)
        recipient = subprocess.run(['age-keygen', '-y', str(identity)], capture_output=True, check=True).stdout.decode().strip()
        runtime = Runtime(dict(database_url='sqlite:///' + str(h.tmp / 'db'),
            state_dir=str(h.tmp / 'runtime'), pool_id='vertical', restore_identity=str(identity),
            restore_recipient=recipient, founder_recipient=recipient, local_objects=str(h.tmp / 'objects'),
            application_version=APP_VERSION))
        self.addCleanup(runtime.close)
        pool = h.pool('vertical')
        runtime.executor.pool = pool
        runtime.channel.boat = h.boat
        runtime.executor.poll_interval_s = .05
        batch, case = 'b-vertical', support.CASE
        inputs = runtime.prepare(batch, ArtifactKind.INPUTS, json.dumps(dict(version=1, dry_run=True, seed=7)).encode())
        registry = runtime.prepare(batch, ArtifactKind.STATEMENT_REGISTRY, b'')
        runtime.ledger.open(batch, 10_000_000)
        snapshot = None
        for seq, kind in enumerate((StepKind.ADMIT, StepKind.WRITER, StepKind.STRESS, StepKind.GATES), 1):
            si = StepInput(batch, case, seq, Step(kind, 1 if kind.numbered else 0), 1,
                plumbing, bench, inputs, snapshot, 60, 1_000_000,
                registry=registry if kind is StepKind.ADMIT else None)
            runtime.ledger.reserve(batch, case, si.idempotency_key, 1_000_000, 10_000_000)
            result = guarded_run(runtime.executor, si)
            if kind is StepKind.GATES:
                # No Docker in this exercise: preserve the completed cheap gate/receipt.
                self.assertIn('G1', result.passed, result)
                self.assertIsNotNone(result.receipt)
            else:
                self.assertEqual(result.outcome, Outcome.OK, result)
            self.assertEqual(result.usage, Usage())
            self.assertIsNotNone(result.snapshot)
            runtime.sealer.open(runtime.keys.scope_key(case), result.snapshot,
                runtime.store.get_sealed(case, result.snapshot))
            snapshot = result.snapshot
            runtime.ledger.settle(si.idempotency_key, result.usage)
            if kind is StepKind.ADMIT:
                registry = result.registry
        # New control-side pool/channel attach to the persisted worker and completed key.
        from durable.channel import BoatChannel
        from durable.executor import Executor
        recovered = h.pool('vertical')
        self.assertEqual(len(recovered.recover()['adopted']), 1)
        channel = BoatChannel(runtime.store, keys=runtime.keys, sealer=runtime.sealer, boat=h.boat)
        executor = Executor(recovered, channel, runtime.ledger, runtime.store, runtime.sealer, runtime.keys,
                            poll_interval_s=.05)
        self.assertEqual(guarded_run(executor, si), result)
        self.assertEqual(runtime.ledger.balance(batch)['held'], 0)
        self.assertEqual(len([c for c in h.calls() if c[0] == 'new']), 1)
        recovered.release(recovered.acquire(case, plumbing, bench))
        self.assertEqual(h.inventory(), [])


if __name__ == '__main__':
    unittest.main()
