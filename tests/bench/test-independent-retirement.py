#!/usr/bin/env python3
"""Independent per-worker retirement (Murphy row 16, queueing half; the row stays open).

Drives the real guard_wait/guard_exit in bin/boat-launch-guards.sh through the real
bin/boat-call. Timing (ttl_seconds, retire_at) and one worker id come from the real
saved launch layout tests/factory/fixtures/isolation-timeouts/. The Boat transport,
collection seam and cards are authored, so this is NOT real-artifact closure evidence.
Barriers are files with bounded waits: event-driven, not timing-sensitive.
GUARD=<path> runs the same checks against another guard (the base-guard mutation check).
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
GUARD = Path(os.environ.get('GUARD', ROOT / 'bin/boat-launch-guards.sh')).resolve()
FIXTURE = ROOT / 'tests/factory/fixtures/isolation-timeouts'
MONITOR = json.loads((FIXTURE / 'monitor.json').read_text())
REAL_ID = json.loads((FIXTURE / 'created.json').read_text())['id']
TTL, RETIRE_AT = int(MONITOR['ttl_seconds']), int(MONITOR['retire_at'])
WAIT = 20  # bound for every barrier; the base guard reaches it, the fixed guard never does

FAKE = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
ev = pathlib.Path(os.environ['ROW16_EV']); a = sys.argv[1:]
with (ev / 'calls').open('a') as f: f.write(json.dumps(a) + '\n')
if a[0] == 'ssh':
    worker, command = a[1], a[2]
    if 'ROW16PROBE' in command:
        reply = ev / (worker + '.reply')
        text = reply.read_text().strip() if reply.exists() else '5'
        if text == 'FAIL': sys.exit(255)
        print(text); sys.exit(0)
    if command == 'row16-pause':
        blocked = ev / (worker + '.pause-blocked')
        if not blocked.exists():
            blocked.touch()
            while True: time.sleep(1)
        sys.exit(0)
    home = ev / 'remote' / worker
    sys.exit(subprocess.run(['/bin/sh', '-c', command], env={**os.environ, 'HOME': str(home)}).returncode)
if a[0] == 'delete':
    with (ev / 'deletes').open('a') as f: f.write(a[1] + '\n')
    (ev / ('deleted-' + a[1])).touch()
    print('{}'); sys.exit(0)
if a[0] == 'list':
    print(json.dumps({'sandboxes': [], 'pageInfo': {'hasMore': False}})); sys.exit(0)
sys.exit('unexpected boat call ' + a[0])
'''

HELPER = r'''import json, os, pathlib, signal, subprocess, sys, time
ev = pathlib.Path(os.environ['ROW16_EV']); action, worker = sys.argv[1:3]; WAIT = int(os.environ['ROW16_WAIT'])
def event(text):
    with (ev / 'events').open('a') as f: f.write(text + '\n')
def wait_for(predicate):
    end = time.monotonic() + WAIT
    while time.monotonic() < end:
        if predicate(): return True
        time.sleep(.02)
    return False
spec_path = ev / (worker + ('.mode' if action == 'collect' else '.resume'))
spec = json.loads(spec_path.read_text()) if spec_path.exists() else {}
if action == 'collect':
    (ev / (worker + '.collect-started')).touch()
    for other, reply in spec.get('set_reply', {}).items(): (ev / (other + '.reply')).write_text(reply)
    if spec.get('kill_task'): os.kill(os.getppid(), signal.SIGKILL); sys.exit(0)
    if spec.get('fail'): sys.exit(1)
    if spec.get('boatcall_pause'):
        sys.exit(subprocess.run([os.environ['ROW16_CALL'], 'ssh', worker, 'row16-pause']).returncode)
    if 'barrier' in spec:
        if not wait_for(lambda: len(list(ev.glob('*.collect-started'))) >= spec['barrier']):
            event('barrier-timeout ' + worker); sys.exit(1)
    if 'wait_for' in spec:
        if not wait_for(lambda: (ev / spec['wait_for']).exists()):
            event('timeout ' + worker); sys.exit(1)
    sys.exit(0)
# resume: one return code per call, consumed in order
count = ev / (worker + '.resume-count'); n = int(count.read_text()) if count.exists() else 0
count.write_text(str(n + 1))
if 'wait_for' in spec:
    (ev / (worker + '.resume-waiting')).touch()
    if wait_for(lambda: (ev / spec['wait_for']).exists()): event('resume-saw ' + worker)
    else: event('resume-timeout ' + worker)
returns = spec.get('returns', [1])
sys.exit(returns[min(n, len(returns) - 1)])
'''

SHELLS = [['/bin/sh']] + ([[shutil.which('bash'), '--posix']] if shutil.which('bash') else [])


class Launch:
    """One authored launch: real guard and boat-call, fixture timing, authored transport."""

    def __init__(self, base, shell, workers, label='exam', root=ROOT, trap=False):
        self.base, self.shell, self.label, self.root, self.trap = base, shell, label, root, trap
        self.ev = base / 'ev'; self.state = base / 'state'
        for path in (self.ev / 'remote', self.state): path.mkdir(parents=True)
        self.fake = base / 'fake-boat'; self.fake.write_text(FAKE); self.fake.chmod(0o755)
        self.helper = base / 'helper.py'; self.helper.write_text(HELPER)
        now = int(time.time())
        (self.state / 'ids').write_text(''.join(w + '\n' for w in workers))
        for worker, due in workers.items():
            # A TTL-due worker has run for exactly retire_at seconds of the real fixture TTL.
            (self.state / (worker + '.started')).write_text(str(now - RETIRE_AT if due else now) + '\n')
            (self.ev / 'remote' / worker).mkdir()

    def mode(self, worker, **spec): (self.ev / (worker + '.mode')).write_text(json.dumps(spec))
    def resume(self, worker, **spec): (self.ev / (worker + '.resume')).write_text(json.dumps(spec))
    def reply(self, worker, text): (self.ev / (worker + '.reply')).write_text(text)

    def script(self, body, extra=''):
        lines = ['set -eu', 'root=' + shlex.quote(str(self.root)), 'label=' + self.label,
                 'state=' + shlex.quote(str(self.state)), 'spend_file=""; bundle=""',
                 '. ' + shlex.quote(str(GUARD)),
                 f'ttl_seconds={TTL}; retire_at={RETIRE_AT}; margin={TTL - RETIRE_AT}',
                 'poll=0.2; stall_seconds=100000; stall_minutes=1667; unreachable=100000',
                 'probe_python="print(\'ROW16PROBE\')"',
                 'EV=' + shlex.quote(str(self.ev)), 'HELPER=' + shlex.quote(str(self.helper))]
        if self.trap:  # exactly what guard_init installs
            lines += ["trap 'guard_exit $?' 0", "trap 'exit 130' INT", "trap 'exit 143' TERM"]
        lines.append(extra or (
            'collect_vm() {\n'
            '  mkdir "$EV/$1.collecting" 2>/dev/null || echo "overlap $1" >> "$EV/events"\n'
            '  echo "collect-start $1" >> "$EV/events"\n'
            '  c=0; python3 "$HELPER" collect "$1" || c=$?\n'
            '  echo "collect-end $1 $c" >> "$EV/events"\n'
            '  rmdir "$EV/$1.collecting"; return "$c"\n'
            '}'))
        lines.append('factory_auto_resume() {\n'
                     '  echo "resume-start $1" >> "$EV/events"\n'
                     '  r=0; python3 "$HELPER" resume "$1" || r=$?\n'
                     '  echo "resume-after $1 $r" >> "$EV/events"; return "$r"\n'
                     '}' if self.label == 'factory' else ':')
        lines.append(body)
        return '\n'.join(lines) + '\n'

    def env(self):
        inherited = {k: v for k, v in os.environ.items()
                     if k not in ('UNBUG_CLOUD', 'UNBUG_LAUNCH_STATE', 'UNBUG_RESUME_LAUNCH', 'UNBUG_BATCH_OPERATION')}
        return {**inherited, 'BOAT_CMD': str(self.fake), 'ROW16_EV': str(self.ev),
                'ROW16_WAIT': str(WAIT), 'ROW16_CALL': str(self.root / 'bin/boat-call'),
                'BOAT_COLLECT_RETRY_SECONDS': '0', 'BOAT_COMMAND_TIMEOUT_SECONDS': '60'}

    def start(self, body, extra=''):
        return subprocess.Popen([*self.shell, '-c', self.script(body, extra)], env=self.env(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                start_new_session=True)

    def run(self, body, extra=''):
        process = self.start(body, extra)
        out, err = process.communicate(timeout=240)
        return process.returncode, err

    def events(self):
        path = self.ev / 'events'
        return path.read_text().splitlines() if path.exists() else []

    def calls(self):
        path = self.ev / 'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def deletes(self):
        path = self.ev / 'deletes'
        return path.read_text().split() if path.exists() else []

    def until(self, name):
        end = time.monotonic() + 60
        while not (self.ev / name).exists():
            if time.monotonic() > end: raise AssertionError('never reached ' + name)
            time.sleep(.02)


STATUS = 'st=0; guard_wait || st=$?; echo "status $st" >> "$EV/events"'


class IndependentRetirementTests(unittest.TestCase):
    def launch(self, shell, workers, **kw):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        return Launch(Path(temp.name), shell, workers, **kw)

    def assertNoOverlap(self, launch):
        self.assertFalse([e for e in launch.events() if e.startswith('overlap')], launch.events())

    def test_fixture_timing(self):
        self.assertEqual(TTL - RETIRE_AT, int(MONITOR['margin']))
        self.assertEqual((TTL, RETIRE_AT), (57600, 55800))

    def test_simultaneous_ttl_margin_retirements_overlap(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                workers = {REAL_ID: True, 'bx_row16b': True, 'bx_row16c': True}
                launch = self.launch(shell, workers, label='factory')
                for worker in workers: launch.mode(worker, barrier=3)
                code, err = launch.run(STATUS, extra=self.ttl_collect())
                events = launch.events()
                self.assertEqual(code, 0, err)
                self.assertFalse([e for e in events if 'timeout' in e], 'not all collections overlapped: %s' % events)
                self.assertIn('status 1', events)  # a TTL-margin retirement is a stop, as before
                self.assertEqual(sorted(launch.deletes()), sorted(workers))
                for worker in workers:
                    self.assertTrue((launch.state / (worker + '.retired')).exists())
                    # factory_ttl_retire runs inside the worker's own task, before its collection.
                    self.assertLess(events.index('attest ' + worker), events.index('collect-start ' + worker))
                self.assertFalse(list(launch.state.glob('*.retirement-exit.*')))
                self.assertNoOverlap(launch)

    @staticmethod
    def ttl_collect():
        return ('factory_ttl_retire() { echo "attest $1" >> "$EV/events"; }\n'
                'collect_vm() {\n'
                '  mkdir "$EV/$1.collecting" 2>/dev/null || echo "overlap $1" >> "$EV/events"\n'
                '  echo "collect-start $1" >> "$EV/events"\n'
                '  c=0; python3 "$HELPER" collect "$1" || c=$?\n'
                '  echo "collect-end $1 $c" >> "$EV/events"\n'
                '  rmdir "$EV/$1.collecting"; return "$c"\n'
                '}')

    def test_unreachable_ttl_margin_retires_without_attestation(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                # 'a-ttl' (numeric reply) sorts first, so retire_kind must be reset for the next worker.
                launch = self.launch(shell, {'a-ttl': True, REAL_ID: True}, label='factory')
                launch.reply(REAL_ID, 'FAIL')  # the probe SSH fails: unreachable-or-TTL branch
                code, err = launch.run(STATUS, extra=self.ttl_collect())
                events = launch.events()
                self.assertEqual(code, 0, err)
                self.assertIn('UNREACHABLE', err)
                self.assertIn('attest a-ttl', events)
                self.assertNotIn('attest ' + REAL_ID, events)  # only the numeric TTL-margin branch attests
                self.assertEqual(sorted(launch.deletes()), sorted(['a-ttl', REAL_ID]))
                self.assertEqual(events[-1], 'status 1')

    def test_reaped_failure_alone_sets_status_and_cleanup_failure(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                # A DONE exam worker sets no status itself: only its reaped failure can make guard_wait 1.
                launch = self.launch(shell, {'bx_row16a': False}, trap=True)
                launch.reply('bx_row16a', 'DONE')
                launch.mode('bx_row16a', fail=True)
                code, err = launch.run(STATUS + '\nexit 0')
                events = launch.events()
                # guard_wait returned 1 after the task's three attempts, before the exit pass's three.
                self.assertEqual(events.index('status 1'), 6, events)
                self.assertNotIn('status 0', events)
                # The exit pass retries, fails again, and that failure is the launcher's cleanup failure.
                self.assertEqual(code, 1, err)
                self.assertIn('unfinished launch evidence retained', err)
                self.assertEqual(events.count('collect-start bx_row16a'), 6)
                self.assertEqual(launch.deletes(), [])

    def test_later_due_worker_is_not_queued_and_failure_is_isolated(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                launch = self.launch(shell, {'bx_row16a': True, 'bx_row16b': False})
                # A's collection blocks until B, which becomes DONE only after A started, is deleted.
                launch.mode('bx_row16a', set_reply={'bx_row16b': 'DONE'}, wait_for='deleted-bx_row16b')
                code, err = launch.run(STATUS)
                events = launch.events()
                self.assertEqual(code, 0, err)
                self.assertNotIn('timeout bx_row16a', events, events)
                self.assertLess(events.index('collect-end bx_row16b 0'), events.index('collect-end bx_row16a 0'))
                self.assertEqual(events[-1], 'status 1')
                self.assertEqual(launch.deletes(), ['bx_row16b', 'bx_row16a'])
            with self.subTest(shell=shell[0], variant='failure isolated'):
                launch = self.launch(shell, {'bx_row16a': True, 'bx_row16b': False})
                launch.mode('bx_row16a', fail=True, set_reply={'bx_row16b': 'DONE'})
                code, err = launch.run(STATUS)
                self.assertEqual(code, 0, err)
                self.assertEqual(launch.events()[-1], 'status 1')
                self.assertEqual(launch.deletes(), ['bx_row16b'])  # A is kept: never deleted uncollected
                self.assertEqual(launch.events().count('collect-start bx_row16a'), 3)
                self.assertIn('KEEPING it running', err)

    def test_once_returns_without_joining(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                launch = self.launch(shell, {'bx_row16a': True})
                launch.mode('bx_row16a', wait_for='release')
                body = ('o=0; guard_wait once || o=$?; echo "once-returned $o" >> "$EV/events"; touch "$EV/release"\n'
                        + STATUS)
                code, err = launch.run(body)
                events = launch.events()
                self.assertEqual(code, 0, err)
                # The TTL-margin stop status belongs to the once pass; the later call only reaps a success.
                self.assertLess(events.index('once-returned 1'), events.index('collect-end bx_row16a 0'))
                self.assertEqual(launch.deletes(), ['bx_row16a'])
                self.assertEqual(events[-1], 'status 0')

    def test_inline_auto_resume_runs_after_same_pass_peer_tasks_start(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                # 'a-done' sorts before the TTL-due real fixture id in this pass.
                launch = self.launch(shell, {'a-done': False, REAL_ID: True}, label='factory')
                launch.reply('a-done', 'DONE')
                launch.resume('a-done', wait_for=REAL_ID + '.collect-started', returns=[1])
                code, err = launch.run(STATUS)
                events = launch.events()
                self.assertEqual(code, 0, err)
                self.assertIn('resume-saw a-done', events, 'auto-resume delayed a due peer: %s' % events)
                self.assertEqual(sorted(launch.deletes()), sorted(['a-done', REAL_ID]))
                self.assertNoOverlap(launch)

    def test_auto_resume_zero_keeps_worker_pending(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                launch = self.launch(shell, {'a-done': False}, label='factory')
                launch.reply('a-done', 'DONE')
                launch.resume('a-done', returns=[0, 1])
                code, err = launch.run(STATUS)
                events = launch.events()
                self.assertEqual(code, 0, err)
                self.assertEqual(events.count('resume-start a-done'), 2)
                # No retirement task until auto-resume declines; then exactly one.
                self.assertLess(events.index('resume-after a-done 1'), events.index('collect-start a-done'))
                self.assertEqual(events.count('collect-start a-done'), 1)
                self.assertEqual(launch.deletes(), ['a-done'])
                self.assertEqual(events[-1], 'status 0')

    def test_task_death_is_a_failed_retirement(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                launch = self.launch(shell, {'bx_row16a': True})
                launch.mode('bx_row16a', kill_task=True)
                (launch.state / 'bx_row16a.retirement-exit.1.1.1').write_text('0\n')  # stale, never read
                code, err = launch.run(STATUS)
                events = launch.events()
                self.assertEqual(code, 0, err)
                self.assertEqual(events[-1], 'status 1')
                self.assertIn('ended without a status', err)
                self.assertEqual(events.count('collect-start bx_row16a'), 1)  # never re-classified
                probes = [c for c in launch.calls() if c[:2] == ['ssh', 'bx_row16a'] and 'ROW16PROBE' in c[2]]
                self.assertEqual(len(probes), 1)  # never probed again after its task died
                self.assertEqual(launch.deletes(), [])  # never deleted uncollected
                self.assertTrue((launch.state / 'bx_row16a.retired').exists())
                self.assertFalse(list(launch.state.glob('*.retirement-exit.*')))

    def test_term_joins_in_flight_retirement_then_exit_pass(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                launch = self.launch(shell, {'bx_row16a': True, 'bx_row16p': False}, trap=True)
                launch.mode('bx_row16a', wait_for='release')
                process = launch.start('guard_wait')
                launch.until('bx_row16a.collect-started')
                os.kill(process.pid, signal.SIGTERM)
                time.sleep(.5)
                (launch.ev / 'release').touch()
                out, err = process.communicate(timeout=240)
                events = launch.events()
                self.assertEqual(process.returncode, 143, err)
                self.assertEqual(events.count('collect-start bx_row16a'), 1)
                self.assertIn('collect-end bx_row16a 0', events)
                self.assertEqual(sorted(launch.deletes()), ['bx_row16a', 'bx_row16p'])  # exit pass retired the peer
                self.assertNoOverlap(launch)

    def test_ctrl_c_to_group_retries_in_task_without_overlap(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                launch = self.launch(shell, {'bx_row16a': True}, trap=True)
                launch.mode('bx_row16a', boatcall_pause=True)
                process = launch.start('guard_wait')
                launch.until('bx_row16a.pause-blocked')
                os.killpg(process.pid, signal.SIGINT)
                out, err = process.communicate(timeout=240)
                events = launch.events()
                self.assertEqual(process.returncode, 130, err)
                ends = [e for e in events if e.startswith('collect-end bx_row16a')]
                self.assertEqual(len(ends), 2, events)  # interrupted pause, then guard_retire's own retry
                self.assertNotEqual(ends[0], 'collect-end bx_row16a 0')
                self.assertEqual(ends[1], 'collect-end bx_row16a 0')
                self.assertEqual(launch.deletes(), ['bx_row16a'])
                self.assertNoOverlap(launch)

    def test_term_during_inline_auto_resume_joins_peer_task(self):
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                launch = self.launch(shell, {'a-done': False, REAL_ID: True}, label='factory', trap=True)
                launch.reply('a-done', 'DONE')
                launch.resume('a-done', wait_for='resume-go', returns=[1])
                launch.mode(REAL_ID, wait_for='release')
                process = launch.start('guard_wait')
                launch.until(REAL_ID + '.collect-started')
                launch.until('a-done.resume-waiting')
                os.kill(process.pid, signal.SIGTERM)
                time.sleep(.3)
                (launch.ev / 'resume-go').touch()
                time.sleep(.3)
                (launch.ev / 'release').touch()
                out, err = process.communicate(timeout=240)
                events = launch.events()
                self.assertEqual(process.returncode, 143, err)
                self.assertFalse([e for e in events if e.startswith('resume-after')], events)  # trap fired between commands
                self.assertIn('collect-end %s 0' % REAL_ID, events)
                self.assertEqual(events.count('collect-start ' + REAL_ID), 1)  # joined, not killed and redone
                self.assertEqual(sorted(launch.deletes()), sorted(['a-done', REAL_ID]))
                self.assertNoOverlap(launch)

    def test_real_collector_under_parallel_retirement_tasks(self):
        # Integration only: overlap of the two collections is likely but not asserted.
        for shell in SHELLS:
            with self.subTest(shell=shell[0]):
                temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
                root = Path(temp.name) / 'host'
                for name in ('bin/boat-call', 'bin/processes.py', 'factory/collect.sh', 'factory/collection.py',
                             'factory/transfer.py', 'factory/boat_lifecycle.py'):
                    (root / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / name, root / name)
                workers = {'bx_row16a': False, 'bx_row16b': False}
                launch = Launch(Path(temp.name), shell, workers, root=root)
                digests = {}
                for worker in workers:
                    sealed = launch.ev / 'remote' / worker / 'sealed'; sealed.mkdir()
                    case = 'case-row16-' + worker[-1]
                    archive = sealed / (case + '.checkpoint.tar.gz.age')
                    archive.write_bytes(b'age-encryption.org/v1\n' + os.urandom(3 * 1024 * 1024))
                    digests[case] = hashlib.sha256(archive.read_bytes()).hexdigest()
                    (sealed / (case + '.scorecard.json')).write_text(json.dumps(
                        {'case': case, 'status': 'stopped', 'sha256': digests[case]}))
                    (sealed / 'DONE').write_text(case + '\n')
                    launch.reply(worker, 'DONE')
                env = {'COLLECT_CHUNK_BYTES': str(1024 * 1024)}
                process = subprocess.run([*shell, '-c', launch.script(
                    STATUS, extra='collect_vm() { /bin/sh "$root/factory/collect.sh" "$1"; }')],
                    env={**launch.env(), **env}, capture_output=True, text=True, timeout=240)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(launch.events()[-1], 'status 0', process.stderr)
                for case, want in digests.items():
                    got = root / 'sealed' / (case + '.checkpoint.tar.gz.age')
                    self.assertEqual(hashlib.sha256(got.read_bytes()).hexdigest(), want)
                self.assertEqual(sorted(launch.deletes()), sorted(workers))


if __name__ == '__main__':
    unittest.main()
