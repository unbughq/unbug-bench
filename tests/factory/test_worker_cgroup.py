"""Worker startup wiring; synthetic preparation edge, no live worker/model."""
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'factory'), str(ROOT/'bin')]
import processes


class StartupTests(unittest.TestCase):
    def test_missing_root_refuses_nonisolated_call_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(processes.ContainmentError, '^containment_unavailable$'):
                processes.ContainedCall(Path(tmp)/'ledger.json')

    def test_nonroot_setup_uses_bounded_noninteractive_privileged_helper(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), \
                patch.object(processes.sys, 'platform', 'linux'), \
                patch.object(processes.os, 'geteuid', return_value=1000), \
                patch.object(processes.os, 'getuid', return_value=1000), \
                patch.object(processes.os, 'getgid', return_value=1000), \
                patch.object(processes.subprocess, 'run') as provision, \
                patch.object(processes, 'probe_model_containment') as probe:
            processes.prepare_model_containment(Path(tmp))
            args, kwargs = provision.call_args
            self.assertEqual(args[0][:4], ['sudo', '-n', sys.executable, '-I'])
            self.assertEqual(args[0][-4:], ['--delegate-model-cgroup', str(os.getpid()), '1000', '1000'])
            self.assertEqual(kwargs['timeout'], 10); self.assertTrue(kwargs['check'])
            self.assertEqual(os.environ['UNBUG_MODEL_CGROUP_ROOT'], '/sys/fs/cgroup/unbug-models-1000')
            probe.assert_called_once_with(Path(tmp))
            provision.side_effect = subprocess.CalledProcessError(1, ['sudo'], stderr='private diagnostic')
            with self.assertRaisesRegex(processes.ContainmentError, '^containment_unavailable$'):
                processes.prepare_model_containment(Path(tmp))




class LeftoverCallTests(unittest.TestCase):
    """Simulated cgroupfs: control files are plain files, removed with their directory."""
    def scope(self, tmp):
        ledger = Path(tmp) / 'ledger.json'
        scope = Path(tmp) / 'root' / processes.hashlib.sha256(os.fsencode(ledger.resolve())).hexdigest()
        return ledger, scope

    def call(self, scope, name, populated='0'):
        call = scope / name; call.mkdir(parents=True)
        (call / 'cgroup.kill').write_text('')
        (call / 'cgroup.events').write_text(f'populated {populated}\nfrozen 0\n')
        return call

    def check(self, tmp, ledger, killed):
        real = processes._remove_cgroup
        def remove(path, end):  # cgroupfs drops control files itself on rmdir
            killed.append((path.name, (path / 'cgroup.kill').read_text()))
            for f in path.iterdir():
                if f.is_file(): f.unlink()
            real(path, end)
        with patch.dict(os.environ, {'UNBUG_MODEL_CGROUP_ROOT': str(Path(tmp) / 'root')}), \
                patch.object(processes.sys, 'platform', 'linux'), patch.object(processes, '_remove_cgroup', remove):
            processes.check_containment(ledger)

    def test_dead_call_left_by_deadline_kill_is_reaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, scope = self.scope(tmp)
            dead = self.call(scope, 'dead')
            live = self.call(scope, 'live')
            fd = os.open(live, os.O_RDONLY | os.O_DIRECTORY)
            try:
                processes.fcntl.flock(fd, processes.fcntl.LOCK_EX | processes.fcntl.LOCK_NB)
                killed = []
                self.check(tmp, ledger, killed)
            finally:
                os.close(fd)
            self.assertEqual(killed, [('dead', '1')])  # killed before removal
            self.assertFalse(dead.exists())
            self.assertTrue(live.exists())  # another live call is never touched

    def test_poisoned_call_still_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, scope = self.scope(tmp)
            poisoned = self.call(scope, 'poisoned'); (poisoned / '.poisoned').mkdir()
            killed = []
            with self.assertRaisesRegex(processes.ContainmentError, '^containment_unavailable$'):
                self.check(tmp, ledger, killed)
            self.assertEqual(killed, []); self.assertTrue(poisoned.exists())

    def state(self, tmp, ledger, call, mounted):
        """Simulated mount table: the recorded tmpfs, and a sibling tmpfs that must survive."""
        mount = Path(tmp) / f'factory-tester-state-{call}'; mount.mkdir()
        other = Path(tmp) / 'factory-tester-state-other'; other.mkdir()
        processes._mount_record(ledger, call).write_text(str(mount))
        table = {str(other)} | ({str(mount)} if mounted else set())
        def run(cmd, **kw):
            self.assertEqual(cmd[:4], ['sudo', '-n', 'umount', '--'])
            table.remove(cmd[4])
        return mount, other, table, [patch.object(processes.os.path, 'ismount', lambda p: str(p) in table),
                                     patch.object(processes.subprocess, 'run', side_effect=run)]

    def test_dead_call_tmpfs_is_unmounted_once_emptied(self):
        for mounted in (True, False):  # False: already unmounted before the reap
            with self.subTest(mounted=mounted), tempfile.TemporaryDirectory() as tmp:
                ledger, scope = self.scope(tmp)
                dead = self.call(scope, 'dead')
                mount, other, table, patches = self.state(tmp, ledger, 'dead', mounted)
                with patches[0], patches[1] as run:
                    self.check(tmp, ledger, [])
                self.assertEqual(run.call_count, int(mounted))
                self.assertEqual(table, {str(other)})  # never by name pattern
                self.assertFalse(mount.exists()); self.assertTrue(other.exists())
                self.assertFalse(processes._mount_record(ledger, 'dead').exists())
                self.assertFalse(dead.exists())

    def test_live_and_poisoned_call_tmpfs_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, scope = self.scope(tmp)
            poisoned = self.call(scope, 'poisoned'); (poisoned / '.poisoned').mkdir()
            mount, _, table, patches = self.state(tmp, ledger, 'poisoned', True)
            with patches[0], patches[1] as run, \
                    self.assertRaisesRegex(processes.ContainmentError, '^containment_unavailable$'):
                self.check(tmp, ledger, [])
            run.assert_not_called(); self.assertIn(str(mount), table)
            self.assertTrue(processes._mount_record(ledger, 'poisoned').exists())

    def test_failed_unmount_keeps_cgroup_for_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, scope = self.scope(tmp)
            dead = self.call(scope, 'dead')
            self.state(tmp, ledger, 'dead', True)
            failure = processes.subprocess.CalledProcessError(32, 'umount')
            with patch.object(processes.os.path, 'ismount', return_value=True), \
                    patch.object(processes.subprocess, 'run', side_effect=failure), \
                    self.assertRaisesRegex(processes.ContainmentError, '^containment_unavailable$'):
                self.check(tmp, ledger, [])
            self.assertTrue(dead.exists()); self.assertTrue(processes._mount_record(ledger, 'dead').exists())

    def test_dead_call_that_will_not_empty_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, scope = self.scope(tmp)
            stuck = self.call(scope, 'stuck', populated='1')
            clock = iter([0.0, 0.0, 10.0, 10.0])
            killed = []
            with patch.object(processes.time, 'monotonic', lambda: next(clock)), \
                    self.assertRaisesRegex(processes.ContainmentError, '^containment_unavailable$'):
                self.check(tmp, ledger, killed)
            self.assertEqual(killed, []); self.assertTrue(stuck.exists())


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('O7_TEST_CGROUP_ROOT'),
                     'requires disposable real Linux cgroup v2')
class KernelTests(unittest.TestCase):

    def test_real_delegation_allows_nonroot_membership_and_kill(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); os.chown(home, 1000, 1000)
            code = """import os,sys,pathlib
sys.path.insert(0, %r)
import processes
os.setgid(1000); os.setuid(1000)
print('ready',flush=True); sys.stdin.readline()
os.environ['UNBUG_MODEL_CGROUP_ROOT']='/sys/fs/cgroup/unbug-models-1000'
processes.probe_model_containment(pathlib.Path(%r))
call=processes.ContainedCall(pathlib.Path(%r)/'ledger')
child=call.launch([sys.executable,'-I','-c','import time; time.sleep(60)'])
call.stop()
assert child.wait(timeout=5) == -9
""" % (str(ROOT/'bin'), tmp, tmp)
            child = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                processes.delegate_model_cgroup(child.pid, 1000, 1000)
                out, err = child.communicate('\n', timeout=15)
                self.assertEqual(child.returncode, 0, err)
            finally:
                if child.poll() is None: child.kill()
                child.wait(timeout=5)


if __name__ == '__main__': unittest.main()
