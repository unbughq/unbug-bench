"""Next-run public qualification telemetry; standalone, no benchmark/cloud imports.

Derived from the 2026-10-21 combined qualification harness. Historical
evidence copies are immutable; use this file as collector.py in future harnesses.
"""
import json
import os
import pathlib
import queue
import re
import subprocess
import threading
import time

PROJECTS = ('unbug-bench', 'unbug-factory-1')


def private_open(path, mode='w'):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode == 'a' else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, mode)


def save(path, data):
    path = pathlib.Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with private_open(tmp) as f:
        json.dump(data, f, indent=2)
        f.write('\n')
    tmp.replace(path)


def run(args, timeout=5):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, umask=0o022)
        return dict(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except subprocess.TimeoutExpired as exc:
        decode = lambda value: value.decode(errors='replace') if isinstance(value, bytes) else (value or '')
        return dict(returncode=None, error=str(exc), timeout=True,
                    stdout=decode(exc.stdout), stderr=decode(exc.stderr))
    except OSError as exc:
        return dict(returncode=None, error=str(exc))


def reap(p):
    termination_requested = p.poll() is None
    if termination_requested:
        p.terminate()
    try:
        rc = p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        rc = p.wait(timeout=5)
    return rc, termination_requested


class Collector:
    def __init__(self, evidence, docker='docker', interval=2, queue_size=256):
        self.e = pathlib.Path(evidence)
        self.e.mkdir(mode=0o700, exist_ok=True)
        self.e.chmod(0o700)
        self.docker = docker
        self.interval = interval
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.states = queue.Queue(maxsize=queue_size)
        self.threads = []
        self.streams = []
        self.shutdown_streams = set()
        self.followers = {}
        self.observed = set()
        self.errors = []
        self.started = time.time()
        self.report = None

    def record(self, name, data):
        with self.lock, private_open(self.e / name, 'a') as f:
            f.write(json.dumps(dict(at=time.time(), **data)) + '\n')

    def error(self, kind, **data):
        with self.lock:
            self.errors.append(dict(kind=kind, **data))
        self.record('collector-errors.jsonl', dict(kind=kind, **data))

    def follow(self, cid, restart=False):
        # Popen only; no inspect, stats, or wait on the event-draining thread.
        if not re.fullmatch('[a-f0-9]{64}', cid):
            self.error('invalid_container_id', id=cid)
            return
        with self.lock:
            if self.stop.is_set():
                return
            self.collect_completed()
            self.observed.add(cid)
            old = self.followers.get(cid)
            if old and not restart:
                return
            n = len(old or [])
            try:
                # Popen duplicates these descriptors into the child. The parent
                # must release its copies immediately, including partial opens.
                with private_open(self.e / f'{cid}-{n}-logs.txt') as out, private_open(self.e / f'{cid}-{n}-logs.stderr') as err:
                    p = subprocess.Popen([self.docker, 'logs', '--timestamps', '--follow', cid],
                                         stdout=out, stderr=err, umask=0o022)
            except OSError as exc:
                self.error('log_spawn', id=cid, error=str(exc))
                return
            self.followers.setdefault(cid, []).append(dict(process=p, started=time.time()))
            self.record('capture-receipts.jsonl', dict(id=cid, attempt=n, status='attached', pid=p.pid))

    def finish_capture(self, cid, n, attempt, interrupted=False):
        p = attempt['process']
        rc, termination_requested = reap(p)
        # A shutdown request cannot excuse an independent failure (e.g. exit 7).
        interrupted = interrupted and termination_requested and rc in (0, -15, 143, -9, 137)
        receipt = dict(id=cid, attempt=n, returncode=rc, shutdown_interrupted=interrupted,
                       status='success' if rc == 0 and not interrupted else ('interrupted' if interrupted else 'error'),
                       stdout_bytes=(self.e / f'{cid}-{n}-logs.txt').stat().st_size,
                       stderr_bytes=(self.e / f'{cid}-{n}-logs.stderr').stat().st_size)
        self.record('capture-receipts.jsonl', receipt)
        attempt['receipt'] = receipt
        del attempt['process']
        return receipt

    def collect_completed(self):
        # poll() reaps exited children without waiting on the event reader.
        # Retain receipts, not Popen objects, throughout a long qualification.
        with self.lock:
            for cid, attempts in self.followers.items():
                for n, a in enumerate(attempts):
                    if 'process' in a and a['process'].poll() is not None:
                        self.finish_capture(cid, n, a)

    def consume(self, line):
        try:
            event = json.loads(line)
            if event.get('Type') != 'container':
                return
            cid = event.get('Actor', {}).get('ID') or event.get('id')
            action = event.get('Action', event.get('status'))
            if action not in ('create', 'start', 'die', 'stop', 'kill', 'oom', 'destroy'):
                return
            # Attach on creation/start, retaining output before a removal race.
            # Other lifecycle events also discover containers present at startup.
            self.follow(cid, restart=action == 'start')
            try:
                self.states.put_nowait((cid, action))
            except queue.Full:
                self.error('state_queue_full', id=cid, event=action)
        except (ValueError, TypeError) as exc:
            self.error('event_parse', error=str(exc))

    def events(self, project, p, err):
        try:
            with private_open(self.e / (project + '-events.jsonl')) as f:
                for line in p.stdout:
                    f.write(line)
                    f.flush()
                    self.consume(line)
        except Exception as exc:
            self.error('event_reader', project=project, error=str(exc))
        finally:
            p.stdout.close()
            rc, _ = reap(p)
            requested = p.pid in self.shutdown_streams
            if not requested or rc not in (0, -15, 143):
                self.error('event_stream_exit', project=project, returncode=rc)
            self.record('event-receipts.jsonl', dict(project=project, returncode=rc,
                                                   shutdown_requested=requested))
            err.close()

    def inspect(self):
        while not self.stop.is_set():
            try:
                cid, action = self.states.get(timeout=0.1)
            except queue.Empty:
                continue
            r = run([self.docker, 'inspect', '--format', '{{json .State}}|{{.RestartCount}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.Image}}', cid])
            self.record('states.jsonl', dict(id=cid, event=action, **r))
            self.states.task_done()

    def discover(self):
        while not self.stop.is_set():
            self.collect_completed()
            for project in PROJECTS:
                r = run([self.docker, 'container', 'ls', '-a', '-q', '--no-trunc',
                         '--filter', 'label=com.docker.compose.project=' + project])
                self.record('discovery.jsonl', dict(project=project, **r))
                for cid in r.get('stdout', '').split():
                    self.follow(cid)
            self.stop.wait(self.interval)

    def sample(self):
        while not self.stop.is_set():
            self.record('resource-samples.jsonl', dict(host=run(['free', '-b']),
                containers=run([self.docker, 'stats', '--no-stream', '--format', '{{json .}}'])))
            self.stop.wait(self.interval)

    def start(self):
        # Launch event subprocesses synchronously before the factory starts.
        for project in PROJECTS:
            err = private_open(self.e / (project + '-events.stderr'))
            try:
                p = subprocess.Popen([self.docker, 'events', '--since', str(int(self.started)),
                    '--format', '{{json .}}', '--filter', 'label=com.docker.compose.project=' + project],
                    stdout=subprocess.PIPE, stderr=err, text=True, umask=0o022)
            except OSError:
                err.close()
                self.close()
                raise
            self.streams.append(p)
            self.spawn(self.events, project, p, err)
        self.spawn(self.inspect)
        self.spawn(self.discover)
        self.spawn(self.sample)

    def spawn(self, target, *args):
        def guarded():
            try:
                target(*args)
            except Exception as exc:
                self.error('thread_failure', target=target.__name__, error=str(exc))
        t = threading.Thread(target=guarded)
        self.threads.append(t)
        t.start()

    def close(self):
        if self.report is not None:
            return self.report
        self.stop.set()
        for p in self.streams:
            if p.poll() is None:
                self.shutdown_streams.add(p.pid)
            reap(p)
        # Stop discovery/readers before taking the final follower snapshot.
        for t in self.threads:
            t.join(timeout=15)
        alive = [t.name for t in self.threads if t.is_alive()]
        if alive:
            # Do not archive files while writers are live or claim a clean shutdown.
            raise RuntimeError('collector threads still alive: ' + str(alive))
        if not self.states.empty():
            self.error('state_queue_shutdown_pending', count=self.states.qsize())
        coverage = {}
        for cid, attempts in self.followers.items():
            captures = []
            for n, a in enumerate(attempts):
                if 'receipt' in a:
                    receipt = a['receipt']
                else:
                    receipt = self.finish_capture(cid, n, a, interrupted=a['process'].poll() is None)
                captures.append(receipt)
            # For a live follower, a finite snapshot gives an actual exit status;
            # terminating a follow process is never treated as successful capture.
            if any(c['shutdown_interrupted'] for c in captures) or not all(c['status'] == 'success' for c in captures):
                with private_open(self.e / f'{cid}-final-logs.txt') as out, private_open(self.e / f'{cid}-final-logs.stderr') as err:
                    try:
                        r = subprocess.run([self.docker, 'logs', '--timestamps', cid],
                            stdout=out, stderr=err, timeout=5, umask=0o022)
                        rc = r.returncode
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        rc = None
                        self.error('final_logs', id=cid, error=str(exc))
                receipt = dict(id=cid, attempt='final', returncode=rc,
                               status='success' if rc == 0 else 'error',
                               stdout_bytes=(self.e / f'{cid}-final-logs.txt').stat().st_size,
                               stderr_bytes=(self.e / f'{cid}-final-logs.stderr').stat().st_size)
                self.record('capture-receipts.jsonl', receipt)
                captures.append(receipt)
            coverage[cid] = dict(success=all(c['status'] == 'success' or
                (c.get('shutdown_interrupted') and captures[-1]['status'] == 'success')
                for c in captures), captures=captures)
        report = dict(containers=coverage, missing=sorted(self.observed - coverage.keys()),
                      errors=self.errors, threads_joined=True,
                      log_capture_complete=bool(self.observed) and not self.errors and
                          all(c['success'] for c in coverage.values()) and self.observed == coverage.keys(),
                      limitation='Capture receipts cover observed containers only; event presence or log bytes alone do not prove lifecycle completeness. State errors and sample gaps remain in raw records.')
        save(self.e / 'telemetry-summary.json', report)
        self.report = report
        return report
