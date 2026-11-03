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
import runner_supervisor as supervisor


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

    def test_supervisor_prepares_before_runner_and_exports_root(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            home = Path(tmp); marker = home/'environment'
            def prepare(target):
                self.assertEqual(target, home)
                self.assertFalse(marker.exists())
                os.environ['UNBUG_MODEL_CGROUP_ROOT'] = '/authored/delegation'
            with patch.object(processes, 'prepare_model_containment', side_effect=prepare, create=True) as setup:
                code = "import os,pathlib; pathlib.Path(os.environ['FACTORY_RUNNER_READY']).touch(); pathlib.Path(" + repr(str(marker)) + ").write_text(os.environ.get('UNBUG_MODEL_CGROUP_ROOT','MISSING'))"
                self.assertEqual(supervisor.supervise([sys.executable, '-c', code], home, 10), 0)
            setup.assert_called_once_with(home)
            self.assertEqual(marker.read_text(), '/authored/delegation')

    def test_failed_provisioning_never_starts_runner(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            home = Path(tmp)
            with patch.object(processes, 'prepare_model_containment',
                              side_effect=processes.ContainmentError('containment_unavailable'), create=True), \
                    patch.object(supervisor.subprocess, 'Popen') as child:
                self.assertEqual(supervisor.supervise(['must-not-run'], home, 10), 78)
                child.assert_not_called()
            status = json.loads((home/'sealed/runner-status.json').read_text())
            self.assertEqual((status['attempt'], status['phase'], status['reason'], status['exit_status']),
                             (0, 'startup', 'containment_unavailable', 78))


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('O7_TEST_CGROUP_ROOT'),
                     'requires disposable real Linux cgroup v2')
class KernelTests(unittest.TestCase):
    def test_real_supervisor_provisions_and_runner_inherits_usable_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            env = {**os.environ, 'HOME': tmp, 'BENCH': str(ROOT), 'FACTORY_RUNNER_SECONDS': '20'}
            env.pop('UNBUG_MODEL_CGROUP_ROOT', None)
            code = """import os,sys,pathlib
sys.path.insert(0, %r)
import processes
home=pathlib.Path.home()
processes.probe_model_containment(home)
(home/'runner-environment').write_text(os.environ['UNBUG_MODEL_CGROUP_ROOT'])
pathlib.Path(os.environ['FACTORY_RUNNER_READY']).touch()
""" % str(ROOT/'bin')
            result = subprocess.run([sys.executable, str(ROOT/'factory/runner_supervisor.py'), '--',
                                     sys.executable, '-c', code], env=env, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home/'runner-environment').read_text(), '/sys/fs/cgroup/unbug-models-0')
            status = json.loads((home/'sealed/runner-status.json').read_text())
            self.assertEqual(status['reason'], 'finished')

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
