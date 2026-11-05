"""Authenticated in-step publication and process-loss replay without providers."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'factory')]

import contextlib
import dataclasses
import json
import os
import select
import shutil
import signal
import tempfile
import types
import unittest
from unittest.mock import patch

import model_runtime
from durable import checkpoints as cp
from durable.artifacts import AgeSealer
from durable.contract import ArtifactKind, Ref, Step, StepInput, StepKind, PollState, WORKER_ROOT
from durable.worker_step import Worker, blob_name, ledger_totals, restore


class Runner:
    @staticmethod
    def retained_paths(c):
        return sorted(p.relative_to(c.work) for p in c.work.iterdir())


def context(work, si):
    return types.SimpleNamespace(work=work, ledger=work / 'continuation-budget.json',
        engine=types.SimpleNamespace(key=si.idempotency_key),
        card=json.loads((work / 'scorecard.json').read_text()))


@unittest.skipUnless(shutil.which('age'), 'requires local age CLI')
class Checkpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.si = StepInput('b-test', 'case-test', 1, Step(StepKind.WRITER, 1), 1,
            'a' * 64, 'b' * 64, Ref('c' * 64, ArtifactKind.INPUTS),
            Ref('d' * 64, ArtifactKind.CASE_SNAPSHOT), 600, 5_000_000)
        self.key = os.urandom(32)
        self.worker = Worker(self.home)
        self.work = self.home / 'work'
        self.work.mkdir()
        (self.work / 'scorecard.json').write_text('{}')
        (self.work / 'continuation-budget.json').write_text('{"calls":0,"events":[],"cost":0}')
        self.c = context(self.work, self.si)
        self.c.engine_checkpoint = lambda: self.worker.publish_checkpoint(
            self.si, self.c, AgeSealer(), self.key, Runner)

    def completed_work(self, c):
        def invoke():
            (c.work / 'answer').write_text('completed model artifact')
            (c.work / 'answer').chmod(0o750)
            (c.work / 'usage-receipts').mkdir(exist_ok=True)
            (c.work / 'usage-receipts/call.json').write_text('{"final_usage_known":true}')
            c.card['route_receipts'] = [{'invocation': 'builder-1', 'outcome': 'done',
                                         'call_id': 'usage-receipts/call.json'}]
            c.ledger.write_text(json.dumps({'calls': 1, 'cost': 0.25, 'events': [
                {'id': 'paid', 'cost': 0.25, 'configured_model': 'local/test'}],
                'invocation_reservations': {'uncertain': {'lease_id': 'uncertain', 'call_name': 'builder-uncertain', 'state': 'pending', 'maximum_usd': 1, 'event_ids': []}}}))
            return 0
        runtime = model_runtime.ModelRuntime(None, None, None, None, None)
        with patch('model_runtime.dispatch', return_value=contextlib.nullcontext()), \
                patch.object(model_runtime.ModelRuntime, '_call', side_effect=lambda *a, **kw: invoke()):
            runtime.call(c, ['local/test'], 'deterministic prompt', c.work, 'builder-1')
        def gate():
            (c.work / 'gate-evidence').write_text('verified')
            return True, {'verified': True}
        cp.gate_call(c, 'G4', gate, 'unchanged-case')
        cp.checkpoint(c)

    def recover(self):
        ref = self.worker.read_checkpoint(self.si.idempotency_key)
        ciphertext = (self.worker.paths(self.si.idempotency_key)['attempt'] / 'out' / blob_name(ref)).read_bytes()
        fresh = self.home / 'fresh-worker'
        fresh.mkdir()
        blob = fresh / WORKER_ROOT / 'blobs' / blob_name(ref)
        blob.parent.mkdir(parents=True)
        blob.write_bytes(ciphertext)
        worker = Worker(fresh)
        recovered = fresh / 'work'
        restore(worker.open_blob(AgeSealer(), self.key, ref), recovered)
        c = context(recovered, dataclasses.replace(self.si, attempt=2))
        # Simulate caller preparing the same workspace before model dispatch.
        (recovered / 'answer').write_text('reset')
        never = lambda: self.fail('completed work repeated')
        self.assertEqual(cp.model_call(c, ['local/test'], recovered, 'builder-1', never), 0)
        self.assertEqual(cp.gate_call(c, 'G4', never, 'unchanged-case'), (True, {'verified': True}))
        self.assertEqual((recovered / 'answer').read_text(), 'completed model artifact')
        self.assertEqual((recovered / 'answer').stat().st_mode & 0o777, 0o750)
        ledger = json.loads(c.ledger.read_text())
        self.assertEqual(ledger['calls'], 1)
        self.assertEqual(ledger['events'][0]['cost'], 0.25)
        self.assertIn('uncertain', ledger['invocation_reservations'])
        self.assertEqual(float(ledger_totals(c.ledger)['total']), 1.25)
        self.assertEqual((recovered / 'gate-evidence').read_text(), 'verified')
        with self.assertRaises(Exception):
            AgeSealer().open(self.key, ref, ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]))

    def test_committed_snapshot_replays_outputs_and_keeps_accounting(self):
        self.completed_work(self.c)
        with patch.object(self.worker, 'processes', return_value={123}):
            poll = self.worker.poll({'key': self.si.idempotency_key})
        self.assertEqual(poll.state, PollState.RUNNING)
        self.assertIsNotNone(poll.checkpoint)
        self.recover()

    def test_failed_blob_publication_cannot_advance_pointer(self):
        self.completed_work(self.c)
        previous = self.worker.read_checkpoint(self.si.idempotency_key)
        (self.work / 'answer').write_text('new state')
        with patch.object(self.worker, '_sync_directory', side_effect=OSError('fault')):
            with self.assertRaises(OSError): self.c.engine_checkpoint()
        self.assertEqual(self.worker.read_checkpoint(self.si.idempotency_key), previous)

    def test_isolated_role_defers_nested_checkpoints_until_joined(self):
        seen = []
        self.c.engine_checkpoint = lambda: seen.append(True)
        external = self.home / 'pilot-home'
        external.mkdir()
        cp.model_call(self.c, ['local/test'], external, 'pilot', lambda: cp.checkpoint(self.c))
        self.assertEqual(seen, [])
        cp.checkpoint(self.c)
        self.assertEqual(seen, [True])

    @unittest.skipUnless(hasattr(os, 'fork'), 'requires POSIX process control; also runs on Linux')
    def test_sigkill_then_restore_on_fresh_worker(self):
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                self.completed_work(self.c)
                os.write(write_fd, b'1')
                while True: signal.pause()
            finally:
                os._exit(1)
        os.close(write_fd)
        try:
            self.assertTrue(select.select([read_fd], [], [], 30)[0], 'checkpoint did not commit')
            self.assertEqual(os.read(read_fd, 1), b'1')
            with patch.object(self.worker, 'processes', return_value={pid}):
                self.assertIsNotNone(self.worker.poll({'key': self.si.idempotency_key}).checkpoint)
        finally:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            os.close(read_fd)
        self.recover()
