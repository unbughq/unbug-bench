"""Offline kernel evidence; never a model, credential, cloud worker or network.

Linux: O7_TEST_CGROUP_ROOT=/sys/fs/cgroup python -B this_file.py in a disposable
privileged container with private cgroupns. Mac skips kernel evidence explicitly.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import budget
import processes

EVENT = {'type': 'step_finish', 'sessionID': 'synthetic', 'part': {
    'id': 'p', 'messageID': 'm', 'cost': .1,
    'tokens': {'input': 1, 'output': 1, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}}}
EMIT = f'print({json.dumps(EVENT)!r}, flush=True)\n'


def wait_for(predicate, seconds=15):
    end = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= end: raise AssertionError('readiness/cleanup deadline')
        time.sleep(.01)


def alive(pid):
    try: return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError: return False


def call(work, code, **kw):
    code = code.replace(json.dumps(EVENT), json.dumps({**EVENT, 'sessionID': uuid.uuid4().hex}))
    return budget.run_budgeted([sys.executable, '-c', code], work, dict(os.environ),
        work / ('transcript-' + uuid.uuid4().hex), work / 'ledger.json', kw.pop('timeout', 20),
        concurrent=True, resume=kw.pop('resume', True), **kw)


def daemon(work, natural=False, nested=False):
    return f"""
import os, signal, time
from pathlib import Path
root = Path({str(work)!r})
cli = os.getpid()
(root / 'cli').write_text(str(cli))
if os.fork() == 0:
    os.setsid()
    if os.fork(): os._exit(0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.close(1); os.close(2)
    if {nested!r}:
        group = Path('/sys/fs/cgroup') / Path('/proc/self/cgroup').read_text().strip().split('::')[1].lstrip('/')
        child = group / 'nested'
        child.mkdir()
        (child / 'cgroup.procs').write_text(str(os.getpid()))
    (root / 'escaped').write_text(str(os.getpid()))
    (root / 'group').write_text(str(os.getpgrp()))
    while True:
        (root / 'heartbeat').write_text(str(time.monotonic_ns()))
        if (root / 'next').exists(): (root / 'contamination').touch()
        time.sleep(.01)
os.wait()
while not (root / 'heartbeat').exists(): time.sleep(.01)
{EMIT if natural else 'while True: time.sleep(.02)'}
"""


class RefusalTests(unittest.TestCase):
    def test_missing_delegation_never_starts_command(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {}, clear=True):
            work = Path(d); marker = work / 'executed'; started = []
            with self.assertRaisesRegex(budget.BudgetError, 'containment_unavailable'):
                call(work, f"open({str(marker)!r}, 'w').close()", on_started=lambda: started.append(True))
            self.assertFalse(marker.exists()); self.assertEqual(started, [])

    def test_ordinary_directory_is_not_cgroupfs(self):
        with tempfile.TemporaryDirectory() as d:
            work = Path(d); root = work / 'fake'; root.mkdir()
            with patch.dict(os.environ, UNBUG_MODEL_CGROUP_ROOT=str(root)):
                with self.assertRaisesRegex(budget.BudgetError, 'containment_unavailable'):
                    call(work, "raise AssertionError('must not execute')")

    def test_runtime_requires_containment_for_nonisolated_calls(self):
        tree = ast.parse((ROOT / 'factory/model_runtime.py').read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'run_budgeted']
        self.assertEqual(len(calls), 1)
        value = next(k.value for k in calls[0].keywords if k.arg == 'containment')
        self.assertEqual(ast.unparse(value), 'not user')


@unittest.skipUnless(sys.platform == 'linux' and os.environ.get('O7_TEST_CGROUP_ROOT'),
                     'requires explicitly delegated real Linux cgroup v2')
class KernelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)
        self.root = Path(os.environ['O7_TEST_CGROUP_ROOT']) / ('o7-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.environment = patch.dict(os.environ, UNBUG_MODEL_CGROUP_ROOT=str(self.root))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.recover)

    def recover(self):
        # Independent kernel cleanup also runs when production kill is removed.
        if not self.root.exists(): return
        (self.root / 'cgroup.kill').write_text('1')
        wait_for(lambda: 'populated 0' in (self.root / 'cgroup.events').read_text())
        for directory, _, _ in os.walk(self.root, topdown=False): Path(directory).rmdir()

    def leaves(self):
        return [p for scope in self.root.iterdir() if scope.is_dir()
                for p in scope.iterdir() if p.is_dir()]

    def assert_dead(self):
        cli = int((self.work / 'cli').read_text())
        escaped = int((self.work / 'escaped').read_text())
        self.assertNotEqual(int((self.work / 'group').read_text()), cli)
        self.assertFalse(alive(cli)); self.assertFalse(alive(escaped))
        before = (self.work / 'heartbeat').read_bytes()
        (self.work / 'next').touch()
        call(self.work, EMIT + 'import time; time.sleep(.2)')
        self.assertEqual((self.work / 'heartbeat').read_bytes(), before)
        self.assertFalse((self.work / 'contamination').exists())
        self.assertEqual(self.leaves(), [])

    def test_cancel_double_fork_before_settlement(self):
        cancel = threading.Event()
        with ThreadPoolExecutor() as pool:
            future = pool.submit(call, self.work, daemon(self.work), cancel=cancel)
            try:
                wait_for(lambda: (self.work / 'heartbeat').exists())
                cancel.set()
                with self.assertRaisesRegex(budget.BudgetError, 'cancelled'): future.result(timeout=15)
            finally: cancel.set()
        self.assert_dead()

    def test_timeout_double_fork(self):
        with self.assertRaisesRegex(budget.BudgetError, 'timeout'):
            call(self.work, daemon(self.work), timeout=2)
        self.assert_dead()

    def test_natural_exit_cleans_nested_cgroup(self):
        call(self.work, daemon(self.work, natural=True, nested=True))
        self.assert_dead()

    def test_success_ledger_waits_for_empty_cgroup(self):
        saved = budget._save
        checked = []
        def observe(path, ledger):
            if ledger.get('terminal_stop') == 'complete':
                self.assertEqual(self.leaves(), [])
                self.assertFalse(alive(int((self.work / 'escaped').read_text())))
                checked.append(True)
            return saved(path, ledger)
        with patch.object(budget, '_save', side_effect=observe):
            call(self.work, daemon(self.work, natural=True))
        self.assertTrue(checked)

    def test_concurrent_cases_are_separate(self):
        other = self.work / 'other'; other.mkdir()
        a, b = threading.Event(), threading.Event()
        with ThreadPoolExecutor() as pool:
            first = pool.submit(call, self.work, daemon(self.work), cancel=a)
            second = pool.submit(call, other, daemon(other), cancel=b)
            try:
                wait_for(lambda: (self.work / 'heartbeat').exists() and (other / 'heartbeat').exists())
                a.set()
                with self.assertRaisesRegex(budget.BudgetError, 'cancelled'): first.result(timeout=15)
                self.assertTrue(alive(int((other / 'escaped').read_text())))
                self.assertFalse(second.done())
            finally:
                a.set(); b.set()
                with self.assertRaisesRegex(budget.BudgetError, 'cancelled'): second.result(timeout=15)

    def test_fork_child_same_ledger_and_leftover(self):
        call(self.work, EMIT)
        def child():
            call(self.work, EMIT)
            (self.work / 'child-success').touch()
            abandoned = processes.ContainedCall(self.work / 'ledger.json')
            abandoned.launch([sys.executable, '-c', daemon(self.work)], stdout=subprocess.DEVNULL)
            wait_for(lambda: (self.work / 'heartbeat').exists())
            os._exit(0)
        proc = multiprocessing.get_context('fork').Process(target=child)
        proc.start(); proc.join(15)
        if proc.is_alive(): proc.kill(); proc.join(); self.fail('fork child hung')
        self.assertEqual(proc.exitcode, 0)
        self.assertTrue((self.work / 'child-success').exists())
        self.assertTrue(alive(int((self.work / 'escaped').read_text())))
        for operation in (lambda: call(self.work, EMIT),
                          lambda: call(self.work, EMIT, containment=False),
                          lambda: budget.resume_ledger(self.work / 'ledger.json')):
            with self.assertRaisesRegex(budget.BudgetError, 'containment_unavailable'): operation()

    def test_same_ledger_threads_can_overlap(self):
        def worker(index):
            code = f"""from pathlib import Path
import time
root=Path({str(self.work)!r})
(root / 'ready-{index}').touch()
end=time.monotonic()+10
while len(list(root.glob('ready-*')))!=2:
 if time.monotonic()>end: raise AssertionError('serialized')
 time.sleep(.01)
""" + EMIT
            return call(self.work, code, resume=False)
        with ThreadPoolExecutor() as pool:
            self.assertEqual([r.returncode for r in pool.map(worker, range(2))], [0, 0])
        self.assertEqual(self.leaves(), [])

    def permission_fault(self, enrollment):
        # Real delegated UID and real EACCES, not a fake cgroup filesystem.
        uid = 65534
        self.work.chmod(0o777)
        os.chown(self.work, uid, uid)
        common = Path(os.environ['O7_TEST_CGROUP_ROOT']) / 'cgroup.procs'
        original = common.stat()
        os.chown(common, uid, uid)
        for path in [self.root, *self.root.iterdir()]: os.chown(path, uid, uid)
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).parent)}
        code = f"""import sys;sys.path[:0]={sys.path[:2]!r}
from pathlib import Path
from test_escaped_session_containment import call, daemon, wait_for, EMIT
import budget, processes
work=Path({str(self.work)!r})
class Cancel:
 def is_set(self): return (work/'cancel').exists()
if {enrollment!r}:
 original=processes.ContainedCall.launch
 def delayed(self,*a,**kw):
  (work/'ready').touch()
  wait_for(lambda:(work/'cancel').exists())
  return original(self,*a,**kw)
 processes.ContainedCall.launch=delayed
try:
 call(work, "open({str(self.work / 'sentinel')!r},'w').close()" if {enrollment!r} else daemon(work),
      cancel=None if {enrollment!r} else Cancel(), on_started=lambda:(work/'started').touch())
except budget.BudgetError as e:
 (work/'result').write_text(str(e))
else: raise AssertionError('fault accepted')
if not {enrollment!r}:
 try: call(work, EMIT, containment=False)
 except budget.BudgetError as e: assert str(e)=='containment_unavailable'
 else: raise AssertionError('poison ignored in owner')
"""
        owner = subprocess.Popen([sys.executable, '-c', code], env=env,
                                 user=uid, group=uid, extra_groups=[])
        control = None
        try:
            wait_for(lambda: (self.work / ('ready' if enrollment else 'heartbeat')).exists())
            leaf, = self.leaves()
            control = leaf / ('cgroup.procs' if enrollment else 'cgroup.kill')
            control.chmod(0o400)
            (self.work / 'cancel').touch()
            owner.wait(timeout=15)
            self.assertEqual(owner.returncode, 0)
            self.assertEqual((self.work / 'result').read_text(),
                             'containment_unavailable' if enrollment else 'cancellation_failed')
            if enrollment:
                self.assertFalse((self.work / 'started').exists())
                self.assertFalse((self.work / 'sentinel').exists())
                self.assertEqual(self.leaves(), [])
            else:
                self.assertTrue((leaf / '.poisoned').exists())
                self.assertTrue(alive(int((self.work / 'escaped').read_text())))
                ledger = json.loads((self.work / 'ledger.json').read_text())
                self.assertEqual(ledger['terminal_stop'], 'cancellation_failed')
                self.assertTrue(ledger['cleanup_errors'])
                retry = f"""import sys;sys.path[:0]={sys.path[:2]!r}
from pathlib import Path
import budget
try: budget.resume_ledger(Path({str(self.work / 'ledger.json')!r}))
except budget.BudgetError as e: assert str(e)=='containment_unavailable'
else: raise AssertionError('fresh process ignored poison')
"""
                subprocess.run([sys.executable, '-c', retry], env=env, user=uid, group=uid,
                               extra_groups=[], check=True, timeout=15)
        finally:
            if owner.poll() is None: owner.kill(); owner.wait(timeout=5)
            if control is not None and control.exists(): control.chmod(0o600)
            os.chown(common, original.st_uid, original.st_gid)

    def test_real_permission_failure_before_enrollment(self):
        self.permission_fault(enrollment=True)

    def test_real_permission_failure_poison_survives_owner(self):
        self.permission_fault(enrollment=False)

    def test_owner_sigkill_refuses_fresh_owner(self):
        code = f"""import sys;sys.path[:0]={sys.path[:2]!r}
from pathlib import Path
from test_escaped_session_containment import call, daemon
work=Path({str(self.work)!r})
call(work, daemon(work))
"""
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).parent)}
        owner = subprocess.Popen([sys.executable, '-c', code], env=env)
        try:
            wait_for(lambda: (self.work / 'heartbeat').exists())
            owner.kill(); owner.wait(timeout=5)
            self.assertTrue(alive(int((self.work / 'escaped').read_text())))
            sentinel = self.work / 'sentinel'
            retry = f"""import sys;sys.path[:0]={sys.path[:2]!r}
from pathlib import Path
from test_escaped_session_containment import call
import budget
try: call(Path({str(self.work)!r}), "open({str(sentinel)!r}, 'w').close()")
except budget.BudgetError as e:
 assert str(e)=='containment_unavailable';sys.exit(0)
raise AssertionError('admitted orphan scope')
"""
            subprocess.run([sys.executable, '-c', retry], env=env, check=True, timeout=15)
            self.assertFalse(sentinel.exists())
        finally:
            if owner.poll() is None: owner.kill(); owner.wait(timeout=5)

    def test_isolated_shim_ignores_hostile_pythonpath(self):
        marker = self.work / 'premature'
        (self.work / 'sitecustomize.py').write_text(f"open({str(marker)!r},'w').close()")
        contained = processes.ContainedCall(self.work / 'ledger.json')
        try:
            process = contained.launch([sys.executable, '-I', '-c', 'pass'], cwd=self.work,
                env={**os.environ, 'PYTHONPATH': str(self.work)}, stdout=subprocess.PIPE)
            process.wait(timeout=5)
            self.assertFalse(marker.exists())
        finally:
            contained.stop()
            if 'process' in locals(): process.stdout.close()


if __name__ == '__main__': unittest.main()
