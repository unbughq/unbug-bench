"""Synthetic emitters only: never invoke a model or read a benchmark case."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from budget import BudgetError, run_budgeted


TOKENS = {'input': 10, 'output': 20, 'reasoning': 3, 'cache': {'read': 4, 'write': 5}}


def event(identity='p1', cost=0.2, reason='stop'):
    return {'type': 'step_finish', 'sessionID': 's', 'part': {
        'id': identity, 'messageID': identity, 'cost': cost,
        'tokens': TOKENS, 'reason': reason,
    }}


def emit(value):
    return 'print(' + repr(json.dumps(value)) + ', flush=True)\n'


class BudgetTests(unittest.TestCase):
    def setUp(self):
        import token_prices
        rates = patch.dict(token_prices.CODEX_PRICES, {'codex/test': (2, .1, 10), 'codex/fixture': (2, .1, 10)})
        rates.start(); self.addCleanup(rates.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / 'budget.json'
        self.transcript = self.root / 'sealed.txt'

    def run_script(self, code, **kwargs):
        if kwargs.get('driver') == 'codex': kwargs.setdefault('configured_model', 'codex/fixture')
        return run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
                            self.transcript, self.ledger, kwargs.pop('timeout', 3), **{**kwargs, 'containment': False})

    def data(self):
        return json.loads(self.ledger.read_text())

    def test_accounting_deduplication_tools_and_cumulative_ledger(self):
        code = "print('diagnostic', flush=True)\n" + emit(event()) * 2
        code += emit({'type': 'tool_use', 'part': {'cost': 900}})
        code += emit(event('p2', 0.1, 'tool-calls'))
        self.assertEqual(self.run_script(code).returncode, 0)
        self.run_script(emit(event('p3', 0.1)))
        data = self.data()
        self.assertEqual(data['calls'], 3)
        self.assertAlmostEqual(data['cost'], 0.4)
        self.assertEqual(data['events'][0]['tokens'], TOKENS)
        self.assertEqual(data['terminal_stop'], 'complete')
        self.assertEqual(set(self.root.glob('budget.json.*')),
                         {self.root / 'budget.json.lock', self.root / 'budget.json.activity.lock',
                          self.root / 'budget.json.admission.lock'})

    def test_concurrent_processes_overlap_and_account_exactly(self):
        from concurrent.futures import ThreadPoolExecutor
        # Barrier is inside each emitter process: a whole-session lock deadlocks this.
        def worker(index):
            code = ('import pathlib,time\n'
                    f'root=pathlib.Path({str(self.root)!r})\n'
                    f'(root / "ready-{index}").touch()\n'
                    'deadline=time.monotonic()+3\n'
                    'while len(list(root.glob("ready-*")))<4:\n'
                    ' if time.monotonic()>deadline: raise RuntimeError("serialized emitters")\n'
                    ' time.sleep(.01)\n')
            for step in range(10): code += emit(event(f'{index}-{step}', cost=.01)) * 2
            return run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
                                self.root / f'transcript-{index}', self.ledger, 5,
                                containment=False, concurrent=True, max_cost=10, max_total_calls=1000)
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual([r.returncode for r in pool.map(worker, range(4))], [0]*4)
        data = self.data()
        self.assertEqual(data['calls'], 40)
        self.assertEqual(len(data['events']), 40)
        self.assertAlmostEqual(data['cost'], .4)
        self.assertEqual(data.get('active', []), [])
        self.assertEqual(data['terminal_stop'], 'complete')

    def test_concurrent_stop_cancels_a_silent_peer_and_stays_sticky(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        ready = self.root / 'peer-ready'
        def peer():
            code = f'import pathlib,time; pathlib.Path({str(ready)!r}).touch(); time.sleep(60)'
            with self.assertRaises(BudgetError):
                run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
                             self.root / 'peer-transcript', self.ledger, 5, containment=False, concurrent=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(peer)
            deadline = time.monotonic()+3
            while not ready.exists() and time.monotonic()<deadline: time.sleep(.01)
            self.assertTrue(ready.exists())
            with self.assertRaisesRegex(BudgetError, 'call_limit'):
                self.run_script(emit(event()), concurrent=True, max_calls=1)
            future.result(timeout=2)
        self.assertEqual(self.data()['calls'], 1)
        self.assertEqual(self.data()['terminal_stop'], 'call_limit')
        self.assertEqual(self.data().get('active', []), [])

    def test_own_cancel_does_not_stop_peers_or_later_calls(self):
        # 2abb0a gates:9 (13 November): the early probe's gate hit its per-call cap, its run_budgeted
        # raised 'cancelled' and wrote it as the ledger's stop, and the writer's concurrent repair
        # call then died in shared_stop with BudgetError('cancelled'): ENGINE STOPPED cancelled.
        from concurrent.futures import ThreadPoolExecutor
        import threading
        ready = self.root / 'peer-ready'
        def peer():
            code = f'import pathlib,time; pathlib.Path({str(ready)!r}).touch(); time.sleep(1)\n' + emit(event('peer'))
            return run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
                                self.root / 'peer-transcript', self.ledger, 5, containment=False, concurrent=True)
        own = threading.Event(); own.set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(peer)
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue(ready.exists())
            with self.assertRaisesRegex(BudgetError, '^cancelled$'):
                self.run_script('import time; time.sleep(5)', concurrent=True, cancel=own)
            self.assertEqual(future.result(timeout=5).returncode, 0)
        self.assertEqual(self.data()['terminal_stop'], 'complete')
        self.assertEqual(self.run_script(emit(event('later'))).returncode, 0)  # the next serial call is admitted
        with self.assertRaisesRegex(BudgetError, '^cancelled$'):  # a run-level cancel still stops every call holding it
            self.run_script(emit(event('after-cancel')), concurrent=True, cancel=own)

    def test_own_timeout_does_not_stop_concurrent_peers(self):
        # 2abb0a gates:9/3 (14 November): the early probe's strong tester hit its own 30-minute cap,
        # wrote 'timeout' as the ledger's stop, and the concurrent G8 review then died in shared_stop:
        # ENGINE STOPPED timeout, a 78-minute gate run lost though the probe is only a label.
        from concurrent.futures import ThreadPoolExecutor
        ready = self.root / 'peer-ready'
        def peer():
            code = f'import pathlib,time; pathlib.Path({str(ready)!r}).touch(); time.sleep(1)\n' + emit(event('peer'))
            return run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
                                self.root / 'peer-transcript', self.ledger, 5, containment=False, concurrent=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(peer)
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue(ready.exists())
            with self.assertRaisesRegex(BudgetError, '^timeout$'):
                self.run_script('import time; time.sleep(5)', concurrent=True, timeout=0.2)
            self.assertEqual(future.result(timeout=5).returncode, 0)
        self.assertEqual(self.data()['terminal_stop'], 'complete')

    def test_own_stall_does_not_stop_concurrent_peers(self):
        # 2abb0a gates:9/5 (14 November): G2's search top-up went silent on a rate-limited route and its
        # stall, written as the ledger's stop, ended the concurrent G8/G9 work: ENGINE STOPPED stalled.
        from concurrent.futures import ThreadPoolExecutor
        ready = self.root / 'peer-ready'
        def peer():
            code = f'import pathlib,time; pathlib.Path({str(ready)!r}).touch(); time.sleep(1.5)\n' + emit(event('peer'))
            return run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
                                self.root / 'peer-transcript', self.ledger, 5, containment=False, concurrent=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(peer)
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue(ready.exists())
            with self.assertRaisesRegex(BudgetError, '^stalled$'):
                self.run_script('import time; time.sleep(5)', concurrent=True, timeout=5, progress_timeout=0.3)
            self.assertEqual(future.result(timeout=5).returncode, 0)
        self.assertEqual(self.data()['terminal_stop'], 'complete')

    def test_own_provider_error_does_not_stop_concurrent_peers(self):
        # 18681d gates:5/2 (15 November): G2's attacker-freshness call got OpenCode's "Unexpected server
        # error" on its free route. model_runtime moves such a call to its next route, but run_budgeted had
        # already written 'opencode_error' as the ledger's stop, so the concurrent builder-freshness call
        # was refused (ENGINE STOPPED Budget ledger stopped: opencode_error), ending a 3.5-hour gate run.
        from concurrent.futures import ThreadPoolExecutor
        ready = self.root / 'peer-ready'
        def peer():
            code = f'import pathlib,time; pathlib.Path({str(ready)!r}).touch(); time.sleep(1)\n' + emit(event('peer'))
            return run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
                                self.root / 'peer-transcript', self.ledger, 5, containment=False, concurrent=True)
        failure = {'type': 'error', 'error': {'name': 'UnknownError', 'data': {
            'message': 'Unexpected server error. Check server logs for details.'}}}
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(peer)
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue(ready.exists())
            with self.assertRaisesRegex(BudgetError, '^opencode_error$'):
                self.run_script(emit(failure), concurrent=True)
            self.assertEqual(future.result(timeout=5).returncode, 0)
        self.assertEqual(self.data()['terminal_stop'], 'complete')
        # A later concurrent call (the next route, or a peer starting now) is admitted.
        self.assertEqual(self.run_script(emit(event('next-route')), concurrent=True).returncode, 0)

    def test_serial_provider_error_still_stops_the_ledger(self):
        with self.assertRaisesRegex(BudgetError, '^opencode_error$'):
            self.run_script(emit({'type': 'error', 'error': {'message': 'x'}}))
        self.assertEqual(self.data()['terminal_stop'], 'opencode_error')

    def test_own_cancel_with_failed_kill_stays_sticky(self):
        # An own cancel leaves no ledger stop, but a process it could not kill must still block admission.
        import threading
        import budget
        pid = self.root / 'orphan-pid'
        def reap():
            try: os.kill(int(pid.read_text()), signal.SIGKILL)
            except (OSError, ValueError): pass
        self.addCleanup(reap)
        own = threading.Event()
        code = f'import os,pathlib,time; pathlib.Path({str(pid)!r}).write_text(str(os.getpid())); time.sleep(30)'
        threading.Timer(.5, own.set).start()
        with patch.object(budget.os, 'killpg', side_effect=ProcessLookupError):  # the kill does nothing
            with self.assertRaisesRegex(BudgetError, '^cancelled$'):
                self.run_script(code, concurrent=True, cancel=own, timeout=20)
        reap()
        self.assertEqual(self.data()['terminal_stop'], 'cancellation_failed')
        with self.assertRaisesRegex(BudgetError, 'Budget ledger stopped: cancellation_failed'):
            self.run_script(emit(event('next')))

    def test_concurrent_cap_resume_waits_for_peer_cleanup(self):
        from concurrent.futures import ThreadPoolExecutor
        ready = self.root / 'peer-ready'
        def peer():
            code = f'import pathlib,time; pathlib.Path({str(ready)!r}).touch(); time.sleep(60)'
            with self.assertRaisesRegex(BudgetError, '^call_limit$'):
                run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
                             self.root / 'peer-transcript', self.ledger, 3, containment=False, concurrent=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(peer)
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline: time.sleep(.001)
            self.assertTrue(ready.exists())
            with self.assertRaisesRegex(BudgetError, '^call_limit$'):
                self.run_script(emit(event('capped')), concurrent=True, max_calls=1)
            self.run_script(emit(event('resumed')), concurrent=True, resume=True)
            future.result(timeout=2)
        self.assertEqual(self.data()['terminal_stop'], 'complete')
        self.assertEqual(self.data()['calls'], 2)
        self.assertNotIn('active', self.data())

    def test_resume_joins_live_generation_without_erasing_peer(self):
        from concurrent.futures import ThreadPoolExecutor
        from budget import resume_ledger
        ready, release = self.root / 'peer-ready', self.root / 'peer-release'
        def peer():
            code = ('import pathlib,time\n'
                    f'pathlib.Path({str(ready)!r}).touch()\n'
                    f'while not pathlib.Path({str(release)!r}).exists(): time.sleep(.001)\n'
                    + emit(event('peer')))
            return run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
                                self.root / 'peer-transcript', self.ledger, 3, containment=False, concurrent=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(peer)
            try:
                deadline = time.monotonic() + 2
                while not ready.exists() and time.monotonic() < deadline: time.sleep(.001)
                self.assertTrue(ready.exists())
                active = self.data()['active']
                resume_ledger(self.ledger)
                self.run_script(emit(event('joined')), concurrent=True, resume=True)
                self.assertEqual(self.data()['active'], active)
            finally: release.touch()
            self.assertEqual(future.result(timeout=2).returncode, 0)
        self.assertEqual(self.data()['calls'], 2)
        self.assertEqual(self.data()['terminal_stop'], 'complete')

    def test_resume_admission_protects_nonatomic_shared_lock_conversion(self):
        import fcntl
        import threading
        from concurrent.futures import ThreadPoolExecutor
        original_flock = fcntl.flock
        local = threading.local()
        conversion_gap, second_admission, second_probe = (threading.Event() for _ in range(3))
        def non_atomic_conversion(file, operation):
            name = str(getattr(file, 'name', ''))
            role = getattr(local, 'role', '')
            if name.endswith('.admission.lock') and operation == fcntl.LOCK_EX and role == 'second':
                second_admission.set()
            if name.endswith('.activity.lock'):
                if operation == (fcntl.LOCK_EX | fcntl.LOCK_NB):
                    if role == 'second': second_probe.set()
                    result = original_flock(file, operation)
                    local.exclusive = True
                    return result
                if operation == fcntl.LOCK_SH and role == 'first' and getattr(local, 'exclusive', False):
                    local.exclusive = False
                    original_flock(file, fcntl.LOCK_UN)  # Emulate Linux's conversion gap.
                    conversion_gap.set()
                    self.assertTrue(second_admission.wait(2))
                    self.assertFalse(second_probe.is_set(), 'resumer entered the conversion gap')
            return original_flock(file, operation)
        def worker(role):
            local.role = role
            if role == 'second': self.assertTrue(conversion_gap.wait(2))
            # Both processes must run concurrently: admission must not last a whole invocation.
            code = ('import pathlib,time\n'
                    f'root=pathlib.Path({str(self.root)!r})\n'
                    f'(root / "ready-{role}").touch()\n'
                    'while len(list(root.glob("ready-*"))) < 2: time.sleep(.001)\n'
                    + emit(event(role)))
            return run_budgeted([sys.executable, '-c', code], self.root, os.environ.copy(),
                                self.root / role, self.ledger, 3, containment=False, concurrent=True, resume=True)
        with patch('budget.fcntl.flock', side_effect=non_atomic_conversion):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, role) for role in ('first', 'second')]
                self.assertEqual([f.result(timeout=4).returncode for f in futures], [0, 0])
        self.assertEqual(self.data()['calls'], 2)
        self.assertEqual(self.data()['terminal_stop'], 'complete')
        self.assertNotIn('active', self.data())

    def test_no_process_starts_with_zero_remaining_budget(self):
        marker = self.root / 'started'
        with self.assertRaisesRegex(BudgetError, 'cost_limit'):
            self.run_script(f'open({str(marker)!r}, "w").close()', max_cost=0)
        self.assertFalse(marker.exists())
        self.assertFalse(self.transcript.exists())

    def test_cap_kills_whole_group_and_is_sticky(self):
        marker = self.root / 'child.pid'
        code = ('import subprocess,sys,time\n'
                'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"])\n'
                f'open({str(marker)!r},"w").write(str(child.pid))\n')
        code += emit(event()) + 'time.sleep(60)\n'
        with self.assertRaisesRegex(BudgetError, 'call_limit'):
            self.run_script(code, max_calls=1)
        child = int(marker.read_text())
        # A killed child may briefly remain a zombie until its reaper runs.
        for _ in range(50):
            result = subprocess.run(['ps', '-o', 'stat=', '-p', str(child)], capture_output=True, text=True)
            if not result.stdout.strip() or result.stdout.strip().startswith('Z'):
                break
            time.sleep(0.02)
        else:
            os.kill(child, signal.SIGKILL)
            self.fail('descendant survived process-group cancellation')
        self.assertIn('step_finish', self.transcript.read_text())
        with self.assertRaisesRegex(BudgetError, 'ledger stopped'):
            self.run_script(emit(event('p2')))

    def test_timeout_keeps_transcript(self):
        with self.assertRaisesRegex(BudgetError, 'timeout'):
            self.run_script("import time; print('sealed diagnostic',flush=True); time.sleep(60)", timeout=0.2)
        self.assertEqual(self.data()['terminal_stop'], 'timeout')
        self.assertIn('sealed diagnostic', self.transcript.read_text())

    def test_provider_limits_and_refusals_stop_before_retry(self):
        cases = [('opencode-go/test', 'opencode', {'type': 'error', 'error': {'name': 'GoUsageLimitError', 'limitName': 'weekly'}}, 'provider_limit'),
                 ('openrouter/test', 'opencode', 'HTTP 402 insufficient credits', 'provider_limit'),
                 ('openrouter/deepseek/deepseek-v4.1-flash', 'opencode', {'type': 'error', 'error': {'statusCode': 429}}, 'provider_limit'),
                 ('openrouter/deepseek/deepseek-v4.1-flash', 'opencode', {'type': 'error', 'error': {'statusCode': 402}}, 'provider_limit'),
                 ('claude/test', 'claude', {'type': 'result', 'is_error': True, 'result': 'Usage limit reached'}, 'provider_limit'),
                 ('claude/test', 'claude', {'type': 'assistant', 'error': 'rate_limit', 'message': {'content': []}}, 'provider_limit'),
                 ('claude/test', 'claude', {'type': 'result', 'is_error': True, 'result': "You've hit your limit · resets tomorrow"}, 'provider_limit'),
                 ('codex/test', 'codex', {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Your prompt was flagged for possible cybersecurity risk.'}}, 'refusal')]
        for model, driver, diagnostic, cause in cases:
            with self.subTest(model=model):
                self.ledger.unlink(missing_ok=True)
                code = emit(diagnostic) if isinstance(diagnostic, dict) else f'print({diagnostic!r}, end="", flush=True)\n'
                with self.assertRaisesRegex(BudgetError, cause + ':' + model):
                    self.run_script(code + 'import time; time.sleep(60)', driver=driver, configured_model=model)
                self.assertEqual(self.data()['terminal_stop'], cause + ':' + model)

    def test_rate_limit_must_persist_and_tool_text_is_not_a_provider_error(self):
        retry = {'type': 'error', 'message': 'HTTP 429 rate limit; retrying'}
        self.run_script(emit(retry) + emit(event()))
        self.ledger.unlink()
        with self.assertRaisesRegex(BudgetError, 'provider_limit'):
            self.run_script(emit(retry) * 2 + 'import time; time.sleep(60)')
        self.ledger.unlink()
        self.run_events(self.CODEX[:-1] + [{'type': 'item.completed', 'item': {'type': 'command_execution',
                        'aggregated_output': 'GoUsageLimitError weekly; insufficient credits 402; cybersecurity'}},
                        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Fixed promotion usage limits and cybersecurity risk reporting.'}}] + self.CODEX[-1:], 'codex')

    def test_raw_rate_limit_at_eof_is_only_one_notice(self):
        self.run_script(emit(event()) + "print('HTTP 429 rate limit; retrying', end='', flush=True)")

    def test_no_progress_kills_silent_child_even_after_pipe_closes(self):
        for close in ('', 'os.close(1); os.close(2);'):
            with self.subTest(close=close):
                self.ledger.unlink(missing_ok=True)
                started = time.monotonic()
                with self.assertRaisesRegex(BudgetError, '^stalled$'):
                    self.run_script('import os,time; ' + close + 'time.sleep(60)', progress_timeout=0.15)
                self.assertLess(time.monotonic() - started, 2)
                self.assertEqual(self.data()['terminal_stop'], 'stalled')

    @unittest.skipUnless(os.path.isdir('/proc/self'), 'child CPU is read from /proc (Linux VMs)')
    def test_silent_but_busy_tool_call_is_not_a_stall(self):
        busy = "import subprocess,sys; subprocess.run([sys.executable,'-c','import time\\nt=time.time()\\nwhile time.time()-t<1.5: pass']); "
        self.run_script(busy + emit(event()), progress_timeout=0.3)  # 1.5 s of silent tool work, 0.3 s silence limit
        self.assertEqual(self.data()['terminal_stop'], 'complete')

    def test_zero_token_streak_deduplicates_and_resets_on_progress(self):
        zero = {'input': 0, 'output': 0, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}
        empty = lambda identity: {**event(identity, cost=0), 'part': {**event(identity, cost=0)['part'], 'tokens': zero}}
        self.run_script(emit(empty('z1')) * 2 + emit(event('paid')) + emit(empty('z2')))
        self.run_script(emit(empty('z3')))
        with self.assertRaisesRegex(BudgetError, '^zero_tokens$'):
            self.run_script(emit(empty('z4')) + 'import time; time.sleep(60)')
        self.assertEqual(self.data()['zero_token_streak'], 3)
        self.assertEqual(self.data()['calls'], 5)

    def test_subscription_zero_token_responses(self):
        for driver in ('codex', 'claude'):
            with self.subTest(driver=driver):
                self.ledger.unlink(missing_ok=True)
                if driver == 'codex':
                    events = [{'type': 'thread.started', 'thread_id': 'zero'}]
                    for _ in range(3):
                        events += [{'type': 'turn.started'}, {'type': 'turn.completed', 'usage': {
                            'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0}}]
                else:
                    events = [{'type': 'assistant', 'message': {'id': str(i), 'usage': {
                        'input_tokens': 0, 'output_tokens': 0, 'cache_read_input_tokens': 0,
                        'cache_creation_input_tokens': 0}}} for i in range(3)]
                with self.assertRaisesRegex(BudgetError, '^zero_tokens$'):
                    self.run_events(events, driver)
                self.assertEqual(self.data()['zero_token_streak'], 3)

    def test_resume_preserves_usage_and_cannot_bypass_exhausted_budget(self):
        with self.assertRaisesRegex(BudgetError, '^total_call_limit$'):
            self.run_script(emit(event()), max_total_calls=1)
        marker = self.root / 'started'
        with self.assertRaisesRegex(BudgetError, 'total_call_limit'):
            self.run_script(f'open({str(marker)!r}, "w").close()', max_total_calls=1, resume=True)
        self.assertFalse(marker.exists())
        self.run_script(emit(event('p2')), max_total_calls=3, resume=True)
        self.assertEqual(self.data()['calls'], 2)
        self.assertAlmostEqual(self.data()['cost'], 0.4)
        self.assertEqual(self.data()['previous_stops'], ['total_call_limit', 'total_call_limit'])

    def test_output_resets_no_progress_clock_and_zero_limit_is_configurable(self):
        code = "import time\n" + ("time.sleep(0.06)\nprint('progress', flush=True)\n" * 4) + emit(event())
        self.run_script(code, progress_timeout=0.18)
        self.ledger.unlink()
        zero = event(cost=0)
        zero['part']['tokens'] = {'input': 0, 'output': 0, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}
        with self.assertRaisesRegex(BudgetError, '^zero_tokens$'):
            self.run_script(emit(zero), max_zero_tokens=1)

    def test_missing_usage_empty_stream_and_process_error_fail_closed(self):
        for code, cause in [('', 'missing_usage'),
                            (emit({'type': 'step_finish', 'part': {'id': 'x', 'messageID': 'x'}}), 'missing_usage'),
                            ("print('private failure'); raise SystemExit(7)", 'process_error')]:
            with self.subTest(cause=cause):
                self.ledger.unlink(missing_ok=True)
                with self.assertRaisesRegex(BudgetError, cause):
                    self.run_script(code)
                self.assertEqual(self.data()['terminal_stop'], cause)
                self.assertTrue(self.transcript.exists())

    def test_codex_process_failure_preserves_exit_status_and_partial_usage(self):
        code = ''.join(emit(e) for e in self.CODEX)
        with self.assertRaisesRegex(BudgetError, '^process_error$'):
            self.run_script(code + "print('private diagnostic'); raise SystemExit(7)",
                            driver='codex', configured_model='codex/test')
        data = self.data()
        self.assertEqual(data['terminal_stop'], 'process_error')
        self.assertEqual(data['last_process_error'], {
            'returncode': 7, 'driver': 'codex', 'configured_model': 'codex/test'})
        self.assertEqual((data['calls'], data['cost'], len(data['events'])), (2, 0, 1))
        self.assertEqual(data['events'][0]['tokens']['input_tokens'], 9000)
        self.assertNotIn('private diagnostic', self.ledger.read_text())
        self.assertIn('private diagnostic', self.transcript.read_text())
        marker = self.root / 'unexpected-retry'
        with self.assertRaisesRegex(BudgetError, 'ledger stopped: process_error'):
            self.run_script(f'open({str(marker)!r}, "w").close()', driver='codex')
        self.assertFalse(marker.exists())
        self.assertEqual(self.data(), data)

    def test_unfinished_turn_and_json_error(self):
        for tail, cause in [(emit({'type': 'step_start', 'part': {'messageID': 'unfinished'}}), 'missing_usage'),
                            (emit({'type': 'error', 'error': {'message': 'private'}}), 'opencode_error')]:
            self.ledger.unlink(missing_ok=True)
            with self.assertRaisesRegex(BudgetError, cause):
                self.run_script(emit(event()) + tail)
            self.assertEqual(self.data()['calls'], 1)

    def test_unpriced_paid_usage(self):
        with self.assertRaisesRegex(BudgetError, 'unpriced_usage'):
            self.run_script(emit(event(cost=0)))
        self.assertEqual(self.data()['calls'], 1)

    def test_per_invocation_and_cumulative_call_limits(self):
        self.run_script(emit(event()), max_calls=2, max_total_calls=3)
        self.run_script(emit(event('p2')), max_calls=2, max_total_calls=3)
        with self.assertRaisesRegex(BudgetError, 'total_call_limit'):
            self.run_script(emit(event('p3')), max_calls=2, max_total_calls=3)
        self.assertEqual(self.data()['calls'], 3)

    def test_departed_group_permission_race_preserves_budget_error(self):
        original_popen = subprocess.Popen
        children = []

        def popen(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            children.append(child)
            return child

        def departed_group(pid, signum):
            self.assertEqual(children[0].pid, pid)
            children[0].wait(timeout=3)
            raise PermissionError('departed Darwin process group')

        with patch('budget.subprocess.Popen', side_effect=popen), patch('budget.os.killpg', side_effect=departed_group):
            with self.assertRaisesRegex(BudgetError, '^cost_limit$'):
                self.run_script(emit(event()), max_cost=0.1)
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(children[0].stdout.closed)
        self.assertEqual(self.data()['terminal_stop'], 'cost_limit')

    def test_live_group_permission_error_uses_bounded_privileged_kill(self):
        killpg = os.killpg

        def privileged_kill(cmd, **kwargs):
            self.assertEqual(cmd[:5], ['sudo', '-n', '/bin/kill', '-KILL', '--'])
            self.assertEqual(kwargs['timeout'], 5)
            killpg(-int(cmd[5]), signal.SIGKILL)
            return subprocess.CompletedProcess(cmd, 0)

        with patch('budget.os.killpg', side_effect=PermissionError), patch('budget.subprocess.run', side_effect=privileged_kill) as fallback:
            with self.assertRaisesRegex(BudgetError, '^cost_limit$'):
                self.run_script(emit(event()) + 'import time; time.sleep(60)', max_cost=0.1)
        fallback.assert_called_once()
        self.assertEqual(self.data()['terminal_stop'], 'cost_limit')

    # Shapes from codex-cli 0.162.1 `exec --json` and Claude Code 2.1.299 `-p --output-format
    # stream-json --verbose` (event names checked against the local binaries, no model call).
    CODEX = [{'type': 'thread.started', 'thread_id': 't1'},
             {'type': 'turn.started'},
             {'type': 'error', 'message': 'Reconnecting... 1/5'},
             {'type': 'item.completed', 'item': {'id': 'item_0', 'type': 'reasoning', 'text': 'x'}},
             {'type': 'item.started', 'item': {'id': 'item_1', 'type': 'command_execution', 'status': 'in_progress'}},
             {'type': 'item.completed', 'item': {'id': 'item_1', 'type': 'command_execution', 'exit_code': 0}},
             {'type': 'item.completed', 'item': {'id': 'item_2', 'type': 'agent_message', 'text': 'READY'}},
             {'type': 'turn.completed', 'usage': {'input_tokens': 9000, 'cached_input_tokens': 4000,
                                                  'output_tokens': 7, 'reasoning_output_tokens': 3}}]
    CLAUDE_USAGE = {'input_tokens': 3, 'cache_creation_input_tokens': 900, 'cache_read_input_tokens': 0, 'output_tokens': 5}

    def claude(self, cost=0.0123, is_error=False):
        message = lambda text: {'type': 'assistant', 'session_id': 's1', 'parent_tool_use_id': None, 'message': {
            'id': 'msg_1', 'model': 'claude-opus-5-5', 'role': 'assistant', 'usage': self.CLAUDE_USAGE,
            'content': [{'type': 'text', 'text': text}]}}
        return [{'type': 'system', 'subtype': 'init', 'session_id': 's1', 'tools': ['Bash', 'Edit', 'Read', 'Write']},
                message('thinking'), message('READY'),  # one response, two content-block events
                {'type': 'result', 'subtype': 'success', 'is_error': is_error, 'session_id': 's1', 'num_turns': 1,
                 'result': 'READY', 'total_cost_usd': cost, 'usage': self.CLAUDE_USAGE}]

    def run_events(self, events, driver, **kwargs):
        return self.run_script(''.join(emit(e) for e in events), driver=driver, **kwargs)

    def test_codex_subscription_usage(self):
        self.run_events(self.CODEX, 'codex')
        data = self.data()
        self.assertEqual(data['calls'], 2)  # command + final message; reasoning and retry notices are not responses
        self.assertEqual(data['cost'], 0)
        self.assertEqual(data['terminal_stop'], 'complete')
        [event] = data['events']
        self.assertEqual((event['id'], event['priced'], event['cost'], event['tokens']['input_tokens']),
                         ('t1:turn-1', 'subscription', 0, 9000))

    def test_claude_subscription_usage_records_list_cost(self):
        self.run_events(self.claude(), 'claude')
        data = self.data()
        self.assertEqual((data['calls'], data['cost'], data['list_cost_usd']), (1, 0, 0.0123))
        [event] = data['events']
        self.assertEqual((event['id'], event['priced'], event['list_cost_usd']), ('s1:result', 'subscription', 0.0123))

    def test_claude_repeated_invocation_names_account_and_session_collision_fails_closed(self):
        from budget import case_spending
        options = dict(configured_model='claude/synthetic', role='writer', invocation_name='builder-6')
        self.run_events(self.claude(cost=.79), 'claude', **options)
        fresh = [{**e, 'session_id': 's2'} for e in self.claude(cost=2)]
        self.run_events(fresh, 'claude', **options)
        self.assertAlmostEqual(case_spending(self.data())['spent_usd'], 2.79)
        self.assertEqual(len(self.data()['events']), 2)
        # A replayed session identity must never report successful completion
        # with omitted usage, even when the invocation name also collides.
        with self.assertRaisesRegex(BudgetError, '^missing_usage$'):
            self.run_events(fresh, 'claude', **options)
        self.assertIsNone(case_spending(self.data())['spent_usd'])

    def test_claude_error_result_with_cost_fails_closed(self):
        from budget import case_spending, require_case_budget
        with self.assertRaisesRegex(BudgetError, '^claude_error$'):
            self.run_events(self.claude(cost=2, is_error=True), 'claude',
                            configured_model='claude/synthetic', role='writer', invocation_name='builder-6')
        self.assertIsNone(case_spending(self.data())['spent_usd'])
        with self.assertRaisesRegex(BudgetError, '^budget_exhausted$'):
            require_case_budget(self.data(), 50)

    def test_subscription_missing_usage_and_errors_stop(self):
        codex, claude = self.CODEX, self.claude()
        cases = [('codex', codex[:-1], 'missing_usage'),  # turn never completed
                 ('codex', codex[:-1] + [{'type': 'turn.completed', 'usage': {'input_tokens': 1}}], 'missing_usage'),
                 ('codex', codex[:2] + [{'type': 'turn.failed', 'error': {'message': 'private failure'}}], 'codex_error'),
                 ('claude', claude[:-1], 'missing_usage'),  # no result event
                 ('claude', claude[:-1] + [{**claude[-1], 'total_cost_usd': None}], 'missing_usage'),
                 ('claude', claude[:-1] + [{**claude[-1], 'usage': {}}], 'missing_usage'),
                 ('claude', [{'type': 'assistant', 'message': {'id': 'm'}}], 'missing_usage'),
                 ('claude', self.claude(is_error=True), 'claude_error')]
        for driver, events, cause in cases:
            with self.subTest(driver=driver, cause=cause):
                self.ledger.unlink(missing_ok=True)
                with self.assertRaisesRegex(BudgetError, cause):
                    self.run_events(events, driver)
                self.assertEqual(self.data()['terminal_stop'], cause)

    def test_subscription_call_limits_and_cost_cap_scope(self):
        with self.assertRaisesRegex(BudgetError, '^call_limit$'):
            self.run_events(self.CODEX, 'codex', max_calls=1)
        self.ledger.unlink()
        self.run_events(self.claude(cost=9.0), 'claude', max_cost=0.5)  # list price never trips --max-cost
        with self.assertRaisesRegex(BudgetError, '^total_call_limit$'):
            self.run_events(self.CODEX, 'codex', max_total_calls=2)
        # Both Codex items were already emitted; draining accounts the overshoot.
        self.assertEqual(self.data()['calls'], 3)

    def test_capped_subscription_accounts_buffered_final_usage_and_resumes(self):
        from budget import case_spending
        for driver, events in (('codex', self.CODEX), ('claude', self.claude())):
            with self.subTest(driver=driver):
                self.ledger.unlink(missing_ok=True)
                # One write puts the final receipt behind the cap-triggering item.
                payload = ''.join(json.dumps(e) + '\n' for e in events).encode()
                code = f'import os,time; os.write(1, {payload!r}); time.sleep(60)'
                with self.assertRaisesRegex(BudgetError, '^call_limit$'):
                    self.run_script(code, driver=driver, max_calls=1)
                self.assertIsNotNone(case_spending(self.data())['spent_usd'])
                self.assertNotIn('unpriced_invocations', self.data())
                self.run_script(emit(event('next')), resume=True)
                self.assertEqual(self.data()['terminal_stop'], 'complete')

    def test_cap_on_unterminated_final_event_counts_it_once(self):
        from budget import case_spending
        events = self.CODEX[:2] + [self.CODEX[-2]]
        payload = '\n'.join(json.dumps(e) for e in events).encode()
        with self.assertRaisesRegex(BudgetError, '^call_limit$'):
            self.run_script(f'import os; os.write(1, {payload!r})', driver='codex', max_calls=1)
        self.assertEqual(self.data()['calls'], 1)
        self.assertIsNone(case_spending(self.data())['spent_usd'])

    def test_capped_subscription_without_final_usage_still_blocks_resume(self):
        from budget import case_spending
        for driver, events in (('codex', self.CODEX[:-1]), ('claude', self.claude()[:-1])):
            with self.subTest(driver=driver):
                self.ledger.unlink(missing_ok=True)
                payload = ''.join(json.dumps(e) + '\n' for e in events).encode()
                code = f'import os,time; os.write(1, {payload!r}); time.sleep(60)'
                with self.assertRaisesRegex(BudgetError, '^call_limit$'):
                    self.run_script(code, driver=driver, max_calls=1)
                self.assertIsNone(case_spending(self.data())['spent_usd'])
                with self.assertRaisesRegex(BudgetError, '^budget_exhausted$'):
                    self.run_script(emit(event('next')), resume=True)

    def test_buffered_incomplete_event_keeps_subscription_spending_unknown(self):
        from budget import case_spending
        payload = (''.join(json.dumps(e) + '\n' for e in self.CODEX) + '{"type":"turn.').encode()
        with self.assertRaisesRegex(BudgetError, '^call_limit$'):
            self.run_script(f'import os,time; os.write(1, {payload!r}); time.sleep(60)',
                            driver='codex', max_calls=1)
        self.assertIsNone(case_spending(self.data())['spent_usd'])
        self.assertEqual(len(self.data()['events']), 1)  # known usage is still retained

    def test_malformed_buffered_events_cannot_bypass_failure_bookkeeping(self):
        from budget import case_spending
        malformed = [
            {'type': 'item.completed', 'item': [1]},
            [1],
            {'type': 'turn.completed', 'usage': {'input_tokens': 10 ** 400,
                'cached_input_tokens': 0, 'output_tokens': 1}},
        ]
        for tail in malformed:
            with self.subTest(tail=type(tail).__name__):
                self.ledger.unlink(missing_ok=True)
                payload = ''.join(json.dumps(e) + '\n' for e in [*self.CODEX, tail]).encode()
                with self.assertRaisesRegex(BudgetError, '^call_limit$'):
                    self.run_script(f'import os,time; os.write(1, {payload!r}); time.sleep(60)',
                                    driver='codex', max_calls=1, concurrent=True)
                data = self.data()
                self.assertEqual(data['terminal_stop'], 'call_limit')
                self.assertNotIn('active', data)
                self.assertEqual(len(data['events']), 1)
                self.assertIsNone(case_spending(data)['spent_usd'])
                with self.assertRaisesRegex(BudgetError, '^budget_exhausted$'):
                    self.run_script(emit(event('next')), resume=True)

    def test_peer_stop_after_read_preserves_buffered_turn_start(self):
        import budget
        from budget import case_spending
        ready = self.root / 'first-turn-accounted'
        first = ''.join(json.dumps(e) + '\n' for e in self.CODEX).encode()
        second = ''.join(json.dumps(e) + '\n' for e in
                         [self.CODEX[1], *self.CODEX[-2:]]).encode()
        code = ('import os,pathlib,time\n'
                f'os.write(1, {first!r})\n'
                f'while not pathlib.Path({str(ready)!r}).exists(): time.sleep(.001)\n'
                f'os.write(1, {second!r})\n'
                'time.sleep(60)\n')
        real_read, real_save = os.read, budget._save

        def save(path, ledger):
            real_save(path, ledger)
            if ledger.get('events'): ready.touch()

        def read(fd, size):
            chunk = real_read(fd, size)
            if chunk.startswith(b'{"type": "turn.started"}'):
                ledger = self.data()
                ledger['terminal_stop'] = 'call_limit'
                real_save(self.ledger, ledger)
            return chunk

        with patch('budget._save', side_effect=save), patch('budget.os.read', side_effect=read):
            with self.assertRaisesRegex(BudgetError, '^call_limit$'):
                self.run_script(code, driver='codex', concurrent=True)
        data = self.data()
        self.assertEqual([e['id'] for e in data['events']], ['t1:turn-1', 't1:turn-2'])
        self.assertEqual(data['calls'], 3)
        self.assertAlmostEqual(case_spending(data)['spent_usd'],
                               2 * data['events'][0]['estimated_subscription_cost_usd'])
        self.assertNotIn('unpriced_invocations', data)

    def test_cap_cancellation_failure_records_unknown_usage_before_raising(self):
        from budget import case_spending
        events = self.CODEX + [{'type': 'turn.started'}, self.CODEX[-2]]
        payload = ''.join(json.dumps(e) + '\n' for e in events).encode()
        original_kill = os.killpg
        calls = []
        def fail_first_stop(pid, sig):
            calls.append(pid)
            if len(calls) == 1: raise OSError('synthetic cancellation failure')
            return original_kill(pid, sig)
        with patch('budget.os.killpg', side_effect=fail_first_stop):
            with self.assertRaisesRegex(BudgetError, '^call_limit$'):
                self.run_script(f'import os; os.write(1, {payload!r})',
                                driver='codex', concurrent=True, max_calls=3)
        data = self.data()
        self.assertEqual(len(data['events']), 1)  # Earlier priced turn is preserved.
        self.assertEqual(len(data['unpriced_invocations']), 1)
        self.assertEqual(data['terminal_stop'], 'call_limit')
        self.assertEqual(data['cleanup_errors'], [{'stage':'process_cancellation', 'error':'OSError'}])
        self.assertNotIn('active', data)
        self.assertIsNone(case_spending(data)['spent_usd'])
        with self.assertRaisesRegex(BudgetError, '^budget_exhausted$'):
            self.run_script(emit(event('next')), resume=True)

    def test_cost_cap_records_overshoot(self):
        with self.assertRaisesRegex(BudgetError, 'cost_limit'):
            self.run_script(emit(event(cost=0.3)), max_cost=0.1)
        self.assertEqual(self.data()['cost'], 0.3)
        self.assertEqual(self.data()['calls'], 1)


if __name__ == '__main__':
    unittest.main()
