"""Offline collector lifecycle regression: synthetic logs, no Docker/cloud access."""

# Keep direct execution independent of the working directory.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools/public-qualification'))

import errno
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import public_collector as collector


class CollectorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        docker = self.root / 'fake-docker'
        docker.write_text('#!' + sys.executable + '\nimport sys\nsys.exit(7 if sys.argv[-1].startswith("b") else 0)\n')
        docker.chmod(0o700)
        self.c = collector.Collector(self.root / 'evidence', docker=str(docker))
        self.addCleanup(self.c.close)

    def test_many_completed_attachments_release_descriptors_and_processes(self):
        # A low FD limit makes the original failure deterministic in an isolated
        # child, without changing the test runner's resource limits.
        probe = r'''
import resource, sys, time
from public_collector import Collector
resource.setrlimit(resource.RLIMIT_NOFILE, (64, resource.getrlimit(resource.RLIMIT_NOFILE)[1]))
c = Collector(sys.argv[1], docker=sys.argv[2])
try:
 for n in range(160):
  c.follow(f'{n:064x}')
  assert not c.errors, 'attachment failed under bounded FD budget'
  a = c.followers[f'{n:064x}'][-1]
  if n < 159:
   deadline = time.monotonic() + 5
   while 'process' in a:
    assert time.monotonic() < deadline, 'completed child not reaped'
    c.collect_completed()
    time.sleep(0.001)
 # Discovery must also clean the last completed attachment while idle.
 c.interval = 0.01
 c.spawn(c.discover)
 deadline = time.monotonic() + 5
 while any('process' in a for aa in c.followers.values() for a in aa):
  assert time.monotonic() < deadline, 'completed process retained'
  time.sleep(0.01)
 report = c.close()
 assert len(report['containers']) == 160
 assert report['log_capture_complete']
 assert all(len(v['captures']) == 1 for v in report['containers'].values())
 assert all(v['captures'][0]['status'] == 'success' for v in report['containers'].values())
finally:
 c.close()
'''
        result = subprocess.run([sys.executable, '-c', probe, str(self.root/'many'), self.c.docker],
                                cwd=pathlib.Path(__file__).resolve().parents[3] / "tools/public-qualification", capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_partial_open_and_spawn_failures_close_handles_and_stay_incomplete(self):
        original = collector.private_open
        handles = []
        def fail_second(path, mode='w'):
            if str(path).endswith('-logs.stderr'):
                raise OSError(errno.EMFILE, 'synthetic descriptor exhaustion')
            f = original(path, mode)
            handles.append(f)
            return f
        with patch.object(collector, 'private_open', fail_second):
            self.c.follow('a'*64)
        self.assertTrue(all(f.closed for f in handles))
        with patch.object(collector.subprocess, 'Popen', side_effect=OSError(errno.EMFILE, 'synthetic spawn failure')):
            self.c.follow('c'*64)
        report = self.c.close()
        self.assertEqual(len(report['errors']), 2)
        self.assertEqual(len(report['missing']), 2)
        self.assertFalse(report['log_capture_complete'])

    def test_failed_exit_is_not_repaired_by_successful_final_snapshot(self):
        self.c.follow('b'*64)
        self.c.followers['b'*64][0]['process'].wait(timeout=5)
        with patch.object(collector.subprocess, 'run', return_value=Mock(returncode=0)):
            report = self.c.close()
        captures = report['containers']['b'*64]['captures']
        self.assertEqual(captures[0]['returncode'], 7)
        self.assertEqual(captures[0]['status'], 'error')
        self.assertEqual(captures[-1]['status'], 'success')
        self.assertFalse(report['containers']['b'*64]['success'])
        self.assertFalse(report['log_capture_complete'])

    def test_shutdown_race_retains_failure_after_successful_final_snapshot(self):
        # close() sees a live follower; reap() then sees its independent exit.
        for polls in ([None, 7], [None, None]):
            with self.subTest(polls=polls), tempfile.TemporaryDirectory() as root:
                c = collector.Collector(root)
                cid = 'a'*64
                for suffix in ('logs.txt', 'logs.stderr'):
                    (c.e / f'{cid}-0-{suffix}').touch()
                p = Mock()
                p.poll.side_effect = polls
                p.wait.return_value = 7
                c.observed.add(cid)
                c.followers[cid] = [dict(process=p)]
                with patch.object(collector.subprocess, 'run', return_value=Mock(returncode=0)):
                    report = c.close()
                captures = report['containers'][cid]['captures']
                self.assertEqual(captures[0]['returncode'], 7)
                self.assertEqual(captures[0]['status'], 'error')
                self.assertFalse(captures[0]['shutdown_interrupted'])
                self.assertEqual(captures[-1]['status'], 'success')
                self.assertFalse(report['containers'][cid]['success'])
                self.assertFalse(report['log_capture_complete'])
                if polls[-1] == 7:
                    p.terminate.assert_not_called()
                else:
                    p.terminate.assert_called_once_with()

    def test_live_attachment_shutdown_and_idempotent_close(self):
        docker = pathlib.Path(self.c.docker)
        docker.write_text('#!' + sys.executable + '\nimport sys,time\nif "--follow" in sys.argv: time.sleep(60)\n')
        self.c.follow('a'*64)
        p = self.c.followers['a'*64][0]['process']
        report = self.c.close()
        self.assertIsNotNone(p.returncode)
        self.assertNotIn('process', self.c.followers['a'*64][0])
        captures = report['containers']['a'*64]['captures']
        self.assertTrue(captures[0]['shutdown_interrupted'])
        self.assertEqual(captures[0]['status'], 'interrupted')
        self.assertEqual(captures[-1]['status'], 'success')
        self.assertTrue(report['containers']['a'*64]['success'])
        self.assertTrue(report['log_capture_complete'])
        receipts = self.c.e / 'capture-receipts.jsonl'
        before = receipts.read_bytes()
        self.assertIs(self.c.close(), report)
        self.assertEqual(receipts.read_bytes(), before)
        self.c.follow('c'*64)
        self.assertNotIn('c'*64, self.c.followers)

    def test_reap_escalates_to_kill_with_bounded_waits(self):
        p = Mock()
        p.poll.return_value = None
        p.wait.side_effect = [subprocess.TimeoutExpired('synthetic', 5), -9]
        self.assertEqual(collector.reap(p), (-9, True))
        p.terminate.assert_called_once_with()
        p.kill.assert_called_once_with()
        self.assertEqual(p.wait.call_count, 2)
        self.assertTrue(all(call.kwargs == {'timeout': 5} for call in p.wait.call_args_list))

if __name__ == '__main__':
    unittest.main()
