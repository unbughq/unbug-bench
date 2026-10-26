"""Synthetic repeated G10 setup: no real users, firewall, cloud, or model calls."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse
import pathlib
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

import run


class PilotRecoveryTests(unittest.TestCase):
    def test_second_g10_recreates_disposable_identity_and_retains_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            home = root / 'pilot'
            work = root / 'work'; work.mkdir()
            receipt = work / 'strong_calibrator/results.json'
            receipt.parent.mkdir(); receipt.write_text('synthetic retained receipt')
            c = types.SimpleNamespace(work=work, card={}, args=argparse.Namespace(
                resume=None, concurrent_roles=False))
            users, events = set(), []
            def shell(ctx, args, **kwargs):
                events.append(tuple(args))
                if args[:2] == ['sudo', 'useradd']:
                    self.assertNotIn(args[-1], users, 'second G10 must delete the old identity first')
                    users.add(args[-1]); home.mkdir()
                if args[:2] == ['sudo', 'userdel']:
                    users.discard(args[-1])
            def shred(path, **kwargs):
                events.append(('shred', path))
                if path.exists(): shutil.rmtree(path)
            def wall(ctx, user, slot, remove=False):
                events.append(('wall', user, slot, remove))
            def calibrate(ctx, role):
                self.assertEqual(receipt.read_text(), 'synthetic retained receipt')
                self.assertFalse((home / 'stale-session').exists())
                (home / 'stale-session').write_text('synthetic session')
                return {'tries': 1, 'solved': int(role == 'strong_calibrator')}
            with patch.object(run, 'HOME', root), patch.object(run, 'pilot_home', return_value=home), \
                 patch.object(run, 'sh', shell), patch.object(run, 'shred_tree', shred), \
                 patch.object(run, 'pilot_wall', wall), \
                 patch.object(run, 'parallel_calibrators', return_value=False):
                # Only the strong role checks for a stale session; the easy role
                # shares this serial identity within one G10 by design.
                def roles(ctx, role):
                    if role == 'strong_calibrator': return calibrate(ctx, role)
                    return {'tries': 1, 'solved': 0}
                with patch.object(run, 'calibrate', roles):
                    self.assertTrue(run.g10(c)[0])
                    self.assertTrue(run.g10(c)[0])
            kills = [i for i, event in enumerate(events) if event[:3] == ('sudo', 'pkill', '-KILL')]
            adds = [i for i, event in enumerate(events) if event[:2] == ('sudo', 'useradd')]
            shreds = [i for i, event in enumerate(events) if event[0] == 'shred']
            removes = [i for i, event in enumerate(events) if event == ('wall', 'pilot', 0, True)]
            self.assertEqual(len(adds), 2)
            self.assertTrue(all(kill < remove < shred < add for kill, remove, shred, add
                                in zip(kills, removes, shreds, adds)))
            self.assertEqual(receipt.read_text(), 'synthetic retained receipt')


if __name__ == '__main__': unittest.main()
