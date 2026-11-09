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
            if cmd[1] == 'test': return 0 if self.remains else 1
            if cmd[1] == 'sh' and self.slow: raise processes.subprocess.TimeoutExpired(cmd, 1)
            if cmd[1] == 'umount' and not self.stuck: self.mounted.discard(cmd[-1])
            if cmd[1] == 'umount' and self.stuck and check: raise RuntimeError('umount: target is busy')
            return 0
        self.stuck = self.remains = self.slow = False
        for name, value in (('sh', sh), ('stop_pilot', lambda c, user: True), ('pilot_wall', lambda *a, **k: None)):
            patcher = patch.object(run, name, value); patcher.start(); self.addCleanup(patcher.stop)

    def test_a_mounted_home_is_unmounted_before_removal_in_its_own_window(self):
        home = str(run.pilot_home('pilot'))
        self.mounted.add(home)
        with processes.deadline(1):    # the diagnosis step's deadline is nearly spent
            run.dispose_diagnosis_pilot(self.c)
        steps = [cmd[1] if cmd[0] == 'sudo' else cmd[0] for cmd in self.commands]
        self.assertEqual(steps, ['mountpoint', 'umount', 'sh', 'mountpoint', 'test', 'userdel'])
        removal = next(cmd for cmd in self.commands if cmd[1] == 'sh')
        # Only the copied credentials are shredded; the rest is deleted on this file system only.
        self.assertIn('auth.json', removal[3]); self.assertIn('rm -rf --one-file-system', removal[3])
        self.assertEqual(removal[-1], home)
        self.assertTrue(all(end >= processes.time.monotonic() + run.PILOT_TEARDOWN_S - 30 and reset
                            for end, reset in self.deadlines))
        removal_end = self.deadlines[[cmd[1] for cmd in self.commands].index('sh')][0]
        self.assertGreater(removal_end, processes.time.monotonic() + run.PILOT_HOME_REMOVAL_S - 30)

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

    def test_a_home_that_cannot_be_removed_is_refused_by_name(self):
        # 18681d-r: G16 failed three times in pilot set-up; the card now records PilotHomeError.
        self.c.role_cancel = None
        home = str(run.pilot_home('pilot'))
        for setting, cause in (('remains', None), ('slow', 'TimeoutExpired')):
            with self.subTest(setting=setting):
                self.remains = setting == 'remains'; self.slow = setting == 'slow'
                with self.assertRaises(run.PilotHomeError) as raised:
                    run.release_pilot_home(self.c, home)
                self.assertEqual(getattr(raised.exception, 'cleanup_error', None), cause)
                with self.assertRaises(run.PilotHomeError):
                    run.make_pilots(self.c, [('pilot', 0)], False)
                self.assertNotIn('useradd', [cmd[1] for cmd in self.commands if cmd[0] == 'sudo'])
                self.commands.clear()

    def test_a_diagnosis_teardown_timeout_keeps_its_cause(self):
        self.slow = True
        with self.assertRaises(RuntimeError) as raised:
            run.dispose_diagnosis_pilot(self.c)
        self.assertEqual((raised.exception.cleanup_stage, raised.exception.cleanup_error), ('pilot_home', 'TimeoutExpired'))


if __name__ == "__main__":
    unittest.main()
