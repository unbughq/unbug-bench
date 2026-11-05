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
