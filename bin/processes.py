"""Owned foreground subprocesses with one remaining-time deadline (stdlib only)."""
import asyncio
import contextlib
import contextvars
import fcntl
import hashlib
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

_deadline = contextvars.ContextVar('process_deadline', default=(math.inf, False))


class Cancelled(RuntimeError):
    pass


class ContainmentError(RuntimeError):
    """Safe labels only; never include a command or its environment."""


@contextlib.contextmanager
def _containment_scope(ledger):
    root = os.environ.get('UNBUG_MODEL_CGROUP_ROOT')
    if sys.platform != 'linux' or not root:
        raise ContainmentError('containment_unavailable')
    ledger = Path(ledger).resolve()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    scope = Path(root) / hashlib.sha256(os.fsencode(ledger)).hexdigest()
    with open(str(ledger) + '.containment.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        scope.mkdir(exist_ok=True)
        yield scope


def _check_calls(scope):
    for call in scope.iterdir():
        if not call.is_dir(): continue  # cgroup control files
        if (call / '.poisoned').exists():
            raise ContainmentError('containment_unavailable')
        fd = os.open(call, os.O_RDONLY | os.O_DIRECTORY)
        try:
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: continue  # another live call, possibly in another process
            raise ContainmentError('containment_unavailable')
        finally:
            os.close(fd)


def check_containment(ledger):
    """Also guard isolated calls and resume against abandoned non-isolated work."""
    if not os.environ.get('UNBUG_MODEL_CGROUP_ROOT'): return
    try:
        with _containment_scope(ledger) as scope: _check_calls(scope)
    except OSError:
        raise ContainmentError('containment_unavailable') from None


class ContainedCall:
    """Kernel-owned membership; fork only while no calls are live.

    Directory locks outlive membership and are closed only after removal (or
    poisoning). The short scope lock orders enrollment against leftover checks.
    No PID/session scans, shared process owner, or unsafe fallback.
    """
    def __init__(self, ledger):
        self.ledger, self.fd, self.path = ledger, None, None
        self.failed = False
        try:
            with _containment_scope(ledger) as scope:
                _check_calls(scope)
                self.path = scope / uuid.uuid4().hex
                self.path.mkdir()
                # Fresh cgroupfs directories create these files themselves.
                if not all((self.path / name).exists() for name in
                           ('cgroup.kill', 'cgroup.events', 'cgroup.procs')):
                    self.path.rmdir()
                    raise ContainmentError('containment_unavailable')
                self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if self.fd is not None: os.close(self.fd); self.fd = None
            raise ContainmentError('containment_unavailable') from None

    def launch(self, command, **kwargs):
        read_fd, write_fd = os.pipe()
        process = None
        try:
            process = subprocess.Popen(
                [sys.executable, '-I', str(Path(__file__).resolve()), str(read_fd), '--', *command],
                pass_fds=(read_fd,), close_fds=True, start_new_session=True, **kwargs)
            (self.path / 'cgroup.procs').write_text(str(process.pid))
            os.write(write_fd, b'1')
            return process
        except BaseException:
            # This shim has not been admitted. It cannot have CLI descendants.
            if process is not None:
                process.kill()
                process.wait(timeout=5)
                if process.stdout is not None: process.stdout.close()
            raise ContainmentError('containment_unavailable') from None
        finally:
            os.close(read_fd); os.close(write_fd)

    def stop(self):
        if self.failed: raise ContainmentError('cancellation_failed')
        if self.fd is None: return
        end = time.monotonic() + 5
        try:
            (self.path / 'cgroup.kill').write_text('1')
            while True:
                events = dict(line.split() for line in (self.path / 'cgroup.events').read_text().splitlines())
                if events.get('populated') == '0': break
                if time.monotonic() >= end: raise TimeoutError()
                time.sleep(.01)
            with _containment_scope(self.ledger):
                for directory, children, _ in os.walk(self.path, topdown=False):
                    if time.monotonic() >= end: raise TimeoutError()
                    Path(directory).rmdir()
                os.close(self.fd); self.fd = None
        except BaseException:
            self.failed = True
            try:
                with _containment_scope(self.ledger):
                    try: (self.path / '.poisoned').mkdir(exist_ok=True)
                    finally:
                        if self.fd is not None: os.close(self.fd); self.fd = None
            except OSError:
                pass  # The unlocked directory itself is the durable refusal.
            finally:
                # An unlocked leftover is also durable if marker creation fails.
                if self.fd is not None: os.close(self.fd); self.fd = None
            raise ContainmentError('cancellation_failed') from None


@contextlib.contextmanager
def deadline(seconds, *, independent=False):
    end = time.monotonic() + positive(seconds)
    previous, reset = _deadline.get()
    token = _deadline.set((end if independent else min(end, previous), independent or reset))
    try:
        yield
    finally:
        _deadline.reset(token)


def positive(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('process timeout must be positive and finite')
    return value


def envelope(timeout=None, end=None, env=None):
    current, reset = _deadline.get()
    environment = dict(os.environ if env is None else env)
    inherited = math.inf if reset else float(environment.get('UNBUG_PROCESS_DEADLINE', math.inf))
    if math.isnan(inherited): raise ValueError('invalid inherited process deadline')
    limit = min(current, inherited, math.inf if end is None else float(end))
    if timeout is not None: limit = min(limit, time.monotonic() + positive(timeout))
    if limit == math.inf: limit = time.monotonic() + 120
    if not math.isfinite(limit): raise ValueError('invalid process deadline')
    environment['UNBUG_PROCESS_DEADLINE'] = str(limit)
    return limit, environment


def _killpg(group):
    # Ignore group EPERM to tolerate macOS zombie-only groups. Cross-user model
    # processes still require the caller's privileged per-user pkill cleanup.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(group, signal.SIGKILL)


def kill_tree(pid, *, owned_group=True, alive=True):
    """Nested owners have distinct sessions. Snapshot numeric ancestry before killing.

    Never inspect argv/environment, and never signal our own session/group.
    Docker daemon-owned services intentionally are not local descendants.
    """
    descendants = []
    group_present = True
    killed_groups = set()
    probe = subprocess.Popen(['ps', '-axo', 'pid=,ppid=,pgid='], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, start_new_session=True, text=True)
    try:
        # On a loaded host ps is slow, not hung; a short bound would skip every descendant.
        rows, _ = probe.communicate(timeout=60)
        entries = [tuple(map(int, row.split())) for row in rows.splitlines() if len(row.split()) == 3]
        group_present = any(group == pid for _, _, group in entries)
        pairs = [(child, parent) for child, parent, _ in entries]
        owned = {pid}
        while True:
            found = {child for child, parent in pairs if parent in owned} - owned
            if not found: break
            descendants.extend(found); owned.update(found)
    except subprocess.TimeoutExpired:
        _killpg(probe.pid); probe.communicate()
    finally:
        probe.wait(timeout=2)
    for child in [*reversed(descendants), *([pid] if alive else [])]:
        try:
            group = os.getpgid(child)
            if ((child != pid or owned_group) and group == child and
                    group != os.getpgrp() and group != os.getsid(0)):
                _killpg(group)
                killed_groups.add(group)
            else:
                os.kill(child, signal.SIGKILL)
        except ProcessLookupError:
            pass
    # The leader may already have exited while its group still has descendants.
    if owned_group and group_present and pid not in killed_groups and pid not in (os.getpgrp(), os.getsid(0)):
        _killpg(pid)


def run(args, *, timeout=None, deadline=None, cancel=None, input=None,
        capture_output=False, check=False, **kwargs):
    end, kwargs['env'] = envelope(timeout, deadline, kwargs.get('env'))
    if end <= time.monotonic(): raise subprocess.TimeoutExpired(args, 0)
    if cancel is not None and cancel.is_set(): raise Cancelled('cancelled')
    if input is not None: kwargs['stdin'] = subprocess.PIPE
    if capture_output: kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # Nested commands stay in the outer owned group, so a dead intermediate
    # shell cannot reparent a new session beyond the outer deadline.
    owned = not any(kwargs['env'].get(k) == '1' for k in
                    ('UNBUG_DIAGNOSTIC_PROCESS_GROUP', 'UNBUG_PROCESS_GROUP_OWNED'))
    kwargs['env']['UNBUG_PROCESS_GROUP_OWNED'] = '1'
    kwargs['start_new_session'] = owned
    process = subprocess.Popen(args, **kwargs)
    try:
        first = input
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0: raise subprocess.TimeoutExpired(args, timeout)
            if cancel is not None and cancel.is_set(): raise Cancelled('cancelled')
            try:
                stdout, stderr = process.communicate(first, timeout=min(.2, remaining))
                break
            except subprocess.TimeoutExpired:
                first = None
        result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        if check: result.check_returncode()
        return result
    finally:
        try:
            kill_tree(process.pid, owned_group=owned, alive=process.poll() is None)
        finally:
            # A detached, reparented process may retain a pipe: never drain forever.
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None: stream.close()
            process.wait(timeout=2)


async def shell(command, *, timeout=120, cwd=None):
    end, env = envelope(timeout)
    owned = not any(env.get(k) == '1' for k in
                    ('UNBUG_DIAGNOSTIC_PROCESS_GROUP', 'UNBUG_PROCESS_GROUP_OWNED'))
    env['UNBUG_PROCESS_GROUP_OWNED'] = '1'
    if end <= time.monotonic(): raise TimeoutError()
    process = await asyncio.create_subprocess_shell(command, cwd=cwd, env=env,
        start_new_session=owned, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    communication = asyncio.create_task(process.communicate())
    try:
        out, err = await asyncio.wait_for(asyncio.shield(communication), max(0, end - time.monotonic()))
        return subprocess.CompletedProcess(command, process.returncode, out, err)
    finally:
        try:
            kill_tree(process.pid, owned_group=owned, alive=process.returncode is None)
        finally:
            try:
                await asyncio.wait_for(asyncio.shield(communication), 2)
                await asyncio.wait_for(process.wait(), 2)
            finally:
                if not communication.done(): communication.cancel()


if __name__ == "__main__":
    # Isolated Python startup and a private pipe prevent pre-enrollment execution.
    descriptor = int(sys.argv[1])
    admitted = os.read(descriptor, 1) == b"1"
    os.close(descriptor)
    if not admitted: sys.exit(125)
    os.execvpe(sys.argv[3], sys.argv[3:], os.environ)
