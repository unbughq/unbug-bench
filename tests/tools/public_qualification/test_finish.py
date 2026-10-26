"""Synthetic deletion metadata only; subprocesses never reach a provider."""

# Keep direct execution independent of the working directory.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools/public-qualification'))

import json
import fcntl
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import finish


class FinishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.e = Path(self.tmp.name)
        self.now = 0
        self.calls = []
        self.operation = dict(id='operation-synthetic', targetId='worker-synthetic',
                              kind='sandbox', status='pending', stage='removing', completedAt=None)
        self.done = dict(self.operation, status='completed', stage='completed',
                         completedAt='2026-10-21T18:05:32Z')
        self.write('monitor-status.json', dict(collection_verified=True, worker_deleted=True,
                                             worker_id='worker-synthetic', case='case-synthetic'))
        self.write('deletion.json', dict(returncode=0, stdout=json.dumps({'operation': self.operation})))
        self.write('case-synthetic.scorecard.json', dict(gates={'G12': 'pass'}))
        self.write('spend.json', dict(provider='boat', actual_spend_usd=None))
        (self.e / 'worker-ids.txt').write_text('worker-synthetic\n')
        self.replies = [self.done]
        self.patchers = [patch.object(finish.subprocess, 'run', side_effect=self.run_command),
                         patch.object(finish.time, 'monotonic', side_effect=lambda: self.now),
                         patch.object(finish.time, 'sleep', side_effect=self.sleep)]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def write(self, name, value):
        (self.e / name).write_text(json.dumps(value))

    def sleep(self, seconds):
        self.now += seconds

    def run_command(self, argv, **kwargs):
        self.calls.append(argv)
        if Path(argv[0]).name == 'boat-call':
            self.assertEqual(argv[1:], ['deletion', 'status', self.operation['id'], '--json'])
            self.assertGreater(kwargs['timeout'], 0)
            reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
            if isinstance(reply, Exception):
                raise reply
            return subprocess.CompletedProcess(argv, 0, json.dumps({'operation': reply}), '')
        self.assertEqual(Path(argv[0]).name, 'boat-spend')
        self.assertEqual(argv[1], '--finish')
        self.write('spend.json', dict(provider='boat', finished_at='2026-10-21T18:06:00Z',
                                     actual_spend_usd=.02845, ids=['worker-synthetic'], exit_code=0))
        return subprocess.CompletedProcess(argv, 0, '', '')

    def spend_calls(self):
        return [a for a in self.calls if Path(a[0]).name == 'boat-spend']

    def test_delayed_success_then_retry_finishes_spend_once(self):
        self.replies = [self.operation, dict(self.operation, status='processing'), self.done]
        finish.finish(self.e)
        self.assertEqual(self.now, 4)
        self.assertEqual(json.loads((self.e / 'deletion-completion.json').read_text()), self.done)
        finish.finish(self.e)
        self.assertEqual(len(self.spend_calls()), 1)

    def test_timeout_never_finishes_spend(self):
        self.replies = [self.operation]
        with self.assertRaises(TimeoutError):
            finish.finish(self.e, timeout=5)
        self.assertEqual(self.now, 5)
        self.assertEqual(len(self.calls), 3)
        self.assertFalse(self.spend_calls())

    def test_failure_and_malformed_completion_fail_closed(self):
        for reply in (dict(self.operation, status='failed'), dict(self.operation, stage='failed'),
                      dict(self.done, completedAt=None), dict(self.done, stage='removing'),
                      dict(self.done, completedAt='invalid'), dict(self.done, kind='volume'),
                      dict(self.done, status='unknown')):
            with self.subTest(reply=reply):
                self.replies = [reply]
                with self.assertRaises(ValueError):
                    finish.finish(self.e)
                self.assertFalse(self.spend_calls())

    def test_wrong_operation_or_target_fail_closed(self):
        for reply in (dict(self.done, targetId='other-worker'), dict(self.done, id='other-operation')):
            with self.subTest(reply=reply):
                self.replies = [reply]
                with self.assertRaises(ValueError):
                    finish.finish(self.e)
                self.assertFalse(self.spend_calls())

    def test_wrong_initial_target_never_queries(self):
        self.write('deletion.json', dict(returncode=0, stdout=json.dumps({
            'operation': dict(self.operation, targetId='other-worker')})))
        with self.assertRaises(ValueError):
            finish.finish(self.e)
        self.assertEqual(self.calls, [])

    def test_provider_timeout_fails_closed(self):
        self.replies = [subprocess.TimeoutExpired('synthetic', 1)]
        with self.assertRaises(subprocess.TimeoutExpired):
            finish.finish(self.e)
        self.assertFalse(self.spend_calls())

    def test_query_error_or_response_after_deadline_fails_closed(self):
        for response in (subprocess.CompletedProcess([], 1, '', ''),
                         subprocess.CompletedProcess([], 0, json.dumps({'operation': self.done}), '')):
            with self.subTest(returncode=response.returncode):
                def query(*args, **kwargs):
                    self.now += kwargs['timeout']
                    return response
                with patch.object(finish.subprocess, 'run', side_effect=query):
                    with self.assertRaises((ValueError, TimeoutError)):
                        finish.finish(self.e, timeout=5)
                self.assertFalse(self.spend_calls())

    def test_spend_timeout_cannot_trigger_a_second_finish(self):
        original = self.run_command
        def command(argv, **kwargs):
            if Path(argv[0]).name == 'boat-spend':
                self.calls.append(argv)
                raise subprocess.TimeoutExpired('synthetic', 130)
            return original(argv, **kwargs)
        with patch.object(finish.subprocess, 'run', side_effect=command):
            with self.assertRaises(subprocess.TimeoutExpired):
                finish.finish(self.e)
            with self.assertRaises(ValueError):
                finish.finish(self.e)
        self.assertEqual(len(self.spend_calls()), 1)

    def test_incomplete_or_wrong_worker_spend_is_not_recalculated(self):
        for update in ({'actual_spend_usd': None}, {'ids': ['other-worker']}, {'exit_code': 1}):
            with self.subTest(update=update):
                self.run_command(['boat-spend', '--finish'])
                data = json.loads((self.e / 'spend.json').read_text())
                self.write('spend.json', dict(data, **update))
                self.calls.clear()
                with self.assertRaises(ValueError):
                    finish.finish(self.e)
                self.assertFalse(self.spend_calls())

    def test_concurrent_finish_is_rejected_before_provider_query(self):
        with (self.e / 'finish.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                finish.finish(self.e)
        self.assertFalse(self.calls)

    def test_historical_single_query_reproduces_processing_race(self):
        source = (Path(__file__).parent / 'fixtures/historical_finish.py').read_text()
        collector = types.ModuleType('collector')
        collector.save = finish.save
        self.replies = [dict(self.operation, status='processing')]
        with patch.dict('sys.modules', {'collector': collector}):
            with self.assertRaises(AssertionError):
                exec(compile(source, 'historical-finish.py', 'exec'),
                     {'__file__': str(self.e / 'finish.py')})
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.spend_calls())

    def test_existing_final_spend_is_unchanged(self):
        self.run_command(['boat-spend', '--finish'])
        self.calls.clear()
        before = (self.e / 'spend.json').read_bytes()
        finish.finish(self.e)
        self.assertFalse(self.spend_calls())
        self.assertEqual((self.e / 'spend.json').read_bytes(), before)

    def test_ambiguous_previous_spend_attempt_is_not_repeated(self):
        self.write('spend-finish-attempt.json', {'started': True})
        with self.assertRaises(ValueError):
            finish.finish(self.e)
        self.assertFalse(self.spend_calls())


if __name__ == '__main__':
    unittest.main()
