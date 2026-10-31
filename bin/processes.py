"""Owned foreground subprocesses with one remaining-time deadline (stdlib only)."""
import asyncio
import contextlib
import contextvars
import math
import os
import signal
import subprocess
import time

_deadline = contextvars.ContextVar('process_deadline', default=(math.inf, False))


class Cancelled(RuntimeError):
    pass


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
