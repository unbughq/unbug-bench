"""Diagnosis pilot home: tmpfs set-up, its own teardown window, no leftover mount. Commands are recorded, not run."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin")]
import types
import unittest
from unittest.mock import patch
import processes
import run


class PilotHomeTeardown(unittest.TestCase):
    def setUp(self):
        self.commands, self.mounted, self.deadlines = [], set(), []
        self.c = types.SimpleNamespace(role_cancel=object())
        def sh(c, cmd, check=False, **kw):
            cmd = [str(part) for part in cmd]
            self.commands.append(cmd)
            self.assertIsNone(getattr(c, 'role_cancel', None), 'cancellation must not reach teardown')
            self.deadlines.append(processes._deadline.get())
            if cmd[1] == 'mountpoint': return 0 if cmd[-1] in self.mounted else 32
            if cmd[1] == 'umount' and not self.stuck: self.mounted.discard(cmd[-1])
            if cmd[1] == 'umount' and self.stuck and check: raise RuntimeError('umount: target is busy')
            return 0
        self.stuck = False
        for name, value in (('sh', sh), ('shred_tree', lambda path, sudo=False: self.commands.append(['shred', str(path)])),
                            ('stop_pilot', lambda c, user: True), ('pilot_wall', lambda *a, **k: None)):
            patcher = patch.object(run, name, value); patcher.start(); self.addCleanup(patcher.stop)

    def test_a_mounted_home_is_unmounted_before_removal_in_its_own_window(self):
        home = str(run.pilot_home('pilot'))
        self.mounted.add(home)
        with processes.deadline(1):    # the diagnosis step's deadline is nearly spent
            run.dispose_diagnosis_pilot(self.c)
        steps = [cmd[1] if cmd[0] == 'sudo' else cmd[0] for cmd in self.commands]
        self.assertEqual(steps, ['mountpoint', 'umount', 'shred', 'mountpoint', 'userdel'])
        self.assertTrue(all(end >= processes.time.monotonic() + run.PILOT_TEARDOWN_S - 30 and reset
                            for end, reset in self.deadlines))

    def test_a_home_that_stays_mounted_is_a_named_failure(self):
        self.mounted.add(str(run.pilot_home('pilot'))); self.stuck = True
        with self.assertRaises(RuntimeError) as raised:
            run.dispose_diagnosis_pilot(self.c)
        self.assertEqual((raised.exception.cleanup_stage, raised.exception.cleanup_error), ('pilot_home', 'RuntimeError'))
        self.assertNotIn('userdel', [cmd[1] for cmd in self.commands])

    def test_release_refuses_a_leftover_mount(self):
        home = str(run.pilot_home('pilot'))
        self.mounted.add(home); self.stuck = True
        self.c.role_cancel = None
        with self.assertRaises(RuntimeError):
            run.release_pilot_home(self.c, home)

    def test_a_diagnosis_pilot_gets_a_tmpfs_home_and_others_do_not(self):
        self.c.role_cancel = None
        entry = types.SimpleNamespace(pw_uid=4242, pw_gid=4343)
        for diagnosis in (True, False):
            with self.subTest(diagnosis=diagnosis), patch('pwd.getpwnam', return_value=entry):
                self.commands.clear()
                run.make_pilots(self.c, [('pilot', None)], True, diagnosis=diagnosis)
                mounts = [cmd for cmd in self.commands if cmd[:2] == ['sudo', 'mount']]
                if diagnosis:
                    self.assertEqual(len(mounts), 1)
                    self.assertIn('uid=4242', mounts[0][5]); self.assertIn('mode=0700', mounts[0][5])
                    self.assertEqual(mounts[0][-1], str(run.pilot_home('pilot')))
                    order = [cmd[1] for cmd in self.commands if cmd[0] == 'sudo']
                    self.assertLess(order.index('useradd'), order.index('mount'))
                    self.assertLess(order.index('mount'), order.index('install'))
                else:
                    self.assertEqual(mounts, [])


if __name__ == "__main__":
    unittest.main()
