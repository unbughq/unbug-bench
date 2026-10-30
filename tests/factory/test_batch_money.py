"""Authored batch limits; no cases/models/cloud, and no lifecycle row closures."""
import hashlib
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'factory'))
import batch
import batch_money as money


class MoneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.home = self.root / 'control'
        self.factory = self.root / 'factory'; (self.factory / 'batches').mkdir(parents=True)
        recipient = (ROOT / 'factory/control-recipient.txt').read_text().strip()
        (self.factory / 'control-recipient.txt').write_text(recipient)
        jobs = {name: dict(mode='batch', case='case-practice-' + name, max_calls=100,
                          requested_total_usd='10.000000000',
                          args=['1', '--source', 'port', '--rotation-slot', '1']) for name in ('a', 'b')}
        self.record = dict(schema=1, id='practice', money_limit_usd='15.000000000',
                           batch_deadline='2099-01-01T00:00:00Z', target_slots=2,
                           max_concurrency=2, restore_recipient=recipient, jobs=jobs)
        self.path = self.factory / 'batches/practice.json'
        self.path.write_text(json.dumps(self.record))
        self.release = self.root / 'release'; self.release.mkdir()
        pin = hashlib.sha256(self.path.read_bytes()).hexdigest()
        (self.release / 'source-manifest.json').write_text(json.dumps({'files': {'factory/batches/practice.json': pin}}))
        self.policy = dict(batch=dict(id='practice', release=str(self.release), sha256='a' * 64,
                                      manifest_path='factory/batches/practice.json', manifest_sha256=pin,
                                      max_concurrency=2), jobs=jobs)
        # Release cryptography/worker import is exercised by test_batch_launch.
        # This suite isolates money admission from that independent verifier.
        self.verify = patch.object(batch, 'verify'); self.verify.start(); self.addCleanup(self.verify.stop)

    def authorize(self, name='a', source=None, **kwargs):
        return money.authorize(self.policy, name, source, self.root, self.home, **kwargs)

    def test_fresh_replay_capacity_and_source_refusals(self):
        first = self.authorize()
        self.assertEqual(self.authorize(), first)
        self.assertEqual(first['revision'], 1)
        self.assertIsNone(first['source_generation'])
        with self.assertRaises(money.MoneyWait): self.authorize('b')
        with self.assertRaises(money.MoneyWait): self.authorize('a', 'c' * 64)
        self.assertEqual(self.authorize(), first)
        projected = json.loads((self.home / 'batch-money/practice/jobs/a.json').read_text())
        self.assertEqual(projected, first)
        path, digest = money.configuration(self.policy, 'a', first, self.home)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(money.configuration(self.policy, 'a', first, self.home), (path, digest))

    def test_expired_or_changed_manifest_has_no_authority(self):
        with self.assertRaisesRegex(money.MoneyWait, 'retired_batch_bound'):
            self.authorize(now=money.deadline(self.record['batch_deadline']) + 1)
        self.assertFalse((self.home / 'batches/practice/money.json').exists())
        self.path.write_bytes(self.path.read_bytes() + b' ')
        with self.assertRaises(money.MoneyWait): self.authorize()
        self.assertFalse((self.home / 'batches/practice/money.json').exists())

    def test_projection_failure_retains_and_repairs_one_reservation(self):
        real = money.atomic_json
        def interrupted(path, value):
            if 'batch-money' in path.parts: raise OSError('authored transfer failure')
            return real(path, value)
        with patch.object(money, 'atomic_json', interrupted), self.assertRaises(OSError):
            self.authorize()
        state = json.loads((self.home / 'batches/practice/money.json').read_text())
        first = state['jobs']['a']['authority']
        with self.assertRaises(money.MoneyWait): self.authorize('b')
        self.assertEqual(self.authorize(), first)
        self.assertEqual(json.loads((self.home / 'batch-money/practice/jobs/a.json').read_text()), first)

    def test_processes_cannot_both_take_the_same_batch_headroom(self):
        context = multiprocessing.get_context('fork')
        children, receivers = [], []
        def reserve(name, sender):
            try:
                self.authorize(name); sender.send('authorized')
            except money.MoneyWait:
                sender.send('queued')
            finally:
                sender.close()
        try:
            for name in ('a', 'b'):
                receiver, sender = context.Pipe(duplex=False)
                process = context.Process(target=reserve, args=(name, sender))
                process.start(); sender.close(); children.append(process); receivers.append(receiver)
            results = []
            for receiver in receivers:
                self.assertTrue(receiver.poll(10)); results.append(receiver.recv())
            self.assertEqual(sorted(results), ['authorized', 'queued'])
        finally:
            for process in children:
                process.join(5)
                if process.is_alive(): process.kill(); process.join()
            for receiver in receivers: receiver.close()


if __name__ == '__main__': unittest.main()
