#!/usr/bin/env python3
"""Worker side of the durable-execution wire protocol (WP5a).

    python3 -B factory/durable/worker_step.py start|poll|cancel     (cwd RELEASE_ROOT)

The control side (WP2's WorkerChannel) runs this over `boat ssh`. The rules are in the
RELEASE_MANIFEST docstring of factory/durable/contract.py; the layout is attempt_paths(),
relative to the worker user's home. Design: docs/designs/durable-execution-wp5a.md.

- start: under a per-case lock, create the attempt marker (O_EXCL), refuse with
  infra:attempt_busy while another attempt of the case is live, then detach a supervisor
  (fork + setsid). The supervisor enforces the deadline; its step process checks the
  release, restores the snapshot, runs the step through run.py's hooks, seals the outputs
  into out/, and writes the result last, first-wins (link()).
- poll: DONE with the result, RUNNING while the attempt is live, otherwise ABSENT.
- cancel: tombstone, stop the attempt's processes, write infra:cancelled if no result.

Scope keys reach the worker only inside the start frame and stay in memory: the detached
processes inherit them through fork, never through a file.
"""
from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import io
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
from decimal import Decimal, ROUND_CEILING

FACTORY = pathlib.Path(__file__).resolve().parents[1]
if str(FACTORY) not in sys.path:
    sys.path.insert(0, str(FACTORY))

from durable.contract import (CASE_ID, RELEASE_MANIFEST, WORKER_ROOT, ArtifactKind, ContractError, Outcome, Poll,
                              PollState, StepKind, StepResult, Usage, attempt_id, attempt_paths, check_result_for,
                              step_input_from_record, step_result_from_record, Ref, to_record)

MAX_FRAME = 1 << 20
TAG = "DURABLE_ATTEMPT"       # environment tag carried by every process of an attempt
KILL_GRACE_S = 5.0
POLL_INTERVAL_S = 0.2
LOG_TAIL = 20_000


class FrameError(ValueError):
    """The frame cannot be answered: a transport failure for the control side."""


def blob_name(ref) -> str:
    return f"{ref.digest}.{ref.kind.value}.age"


def _micros_up(usd) -> int:
    return int((Decimal(str(usd)) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


# ---- processes -------------------------------------------------------------------------------

def _stat(pid):
    """(state, ppid, starttime) of a process, or None."""
    try:
        text = pathlib.Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    fields = text.rsplit(")", 1)[1].split()
    return fields[0], int(fields[1]), int(fields[19])


def _alive(pid, starttime=None):
    info = _stat(pid)
    return info is not None and info[0] not in ("Z", "X") and (starttime is None or info[2] == starttime)


def _tagged(aid):
    """Processes whose environment carries this attempt's tag (readable: our own user's)."""
    marker = f"{TAG}={aid}".encode()
    found = set()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            environ = pathlib.Path(f"/proc/{entry}/environ").read_bytes()
        except OSError:
            continue
        if marker in environ.split(b"\0"):
            found.add(int(entry))
    return found


def _descendants(roots):
    children = {}
    for entry in os.listdir("/proc"):
        if entry.isdigit() and (info := _stat(entry)) is not None:
            children.setdefault(info[1], []).append(int(entry))
    found, pending = set(), list(roots)
    while pending:
        pid = pending.pop()
        for child in children.get(pid, ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def _signal(pid, sig):
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Isolated calibrator users run under sudo; the worker user has passwordless sudo.
        subprocess.run(["sudo", "-n", "kill", f"-{int(sig)}", str(pid)], capture_output=True)


# ---- the worker ------------------------------------------------------------------------------

class Worker:
    """One worker home. sealer: contract.Sealer (WP3). classifier: contract.Classifier (WP4).
    runner: the module with context_for_step, run_step and retained_paths (factory/run.py)."""

    def __init__(self, home=None, *, sealer=None, classifier=None, runner=None, clock=time.time):
        self.home = pathlib.Path(home) if home is not None else pathlib.Path.home()
        self._sealer, self._classifier, self._runner, self.clock = sealer, classifier, runner, clock

    # layout
    def paths(self, key):
        p = attempt_paths(key)
        return {name: (value if name == "unit" else self.home / value) for name, value in p.items()}

    def _case_dir(self, case_id):
        return self.home / WORKER_ROOT / "cases" / hashlib.sha256(case_id.encode()).hexdigest()[:32]

    @contextlib.contextmanager
    def case_lock(self, case_id):
        path = self.home / WORKER_ROOT / "locks" / (hashlib.sha256(case_id.encode()).hexdigest()[:32] + ".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield fd
        finally:
            os.close(fd)

    def _index(self, case_id, key):
        directory = self._case_dir(case_id)
        directory.mkdir(parents=True, exist_ok=True)
        entry = directory / attempt_id(key)
        if not entry.exists():
            entry.write_text(key)

    # liveness
    def unit(self, key):
        try:
            value = json.loads((self.paths(key)["attempt"] / "unit.json").read_text())
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None

    def processes(self, key):
        """Every live process of the attempt: its supervisor, the supervisor's descendants, and tagged ones."""
        unit, found = self.unit(key), set()
        if unit and _alive(unit.get("pid"), unit.get("starttime")):
            found.add(unit["pid"])
            found |= _descendants([unit["pid"]])
        tagged = _tagged(attempt_id(key))
        found |= tagged | _descendants(tagged)
        return {pid for pid in found if pid != os.getpid() and _alive(pid)}

    def live(self, key):
        """Keep the case busy until every process of the attempt has exited."""
        return bool(self.processes(key))

    def busy(self, case_id, key):
        directory = self._case_dir(case_id)
        for entry in sorted(directory.iterdir()) if directory.is_dir() else ():
            if entry.name == attempt_id(key):
                continue
            try:
                other = entry.read_text()
            except OSError:
                continue
            if self.live(other):
                return True
        return False

    # results
    def write_result(self, key, result):
        """First-wins: a complete record is linked into place; an existing result is never replaced."""
        path = self.paths(key)["result"]
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(to_record(result), sort_keys=True))
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(tmp, path)
            except FileExistsError:
                return False
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return True
        finally:
            os.unlink(tmp)

    def read_result(self, key):
        path = self.paths(key)["result"]
        return step_result_from_record(json.loads(path.read_text())) if path.exists() else None

    # commands
    def start(self, frame):
        if not isinstance(frame, dict) or set(frame) != {"input", "keys"}:
            raise FrameError("bad start frame")
        try:
            step_input = step_input_from_record(frame["input"])
        except (ContractError, TypeError, KeyError) as error:
            raise FrameError("bad step input") from error
        keys = self._keys(frame["keys"], step_input)
        key = step_input.idempotency_key
        p = self.paths(key)
        with self.case_lock(step_input.case_id) as lock:
            p["attempt"].parent.mkdir(parents=True, exist_ok=True)
            try:
                os.mkdir(p["attempt"], 0o700)
            except FileExistsError:
                return  # an earlier start, or a cancel tombstone
            self._index(step_input.case_id, key)
            if keys is None:
                self.write_result(key, StepResult(Outcome.INFRA_ERROR, "infra:bad_frame"))
                return
            if self.busy(step_input.case_id, key):
                self.write_result(key, StepResult(Outcome.INFRA_ERROR, "infra:attempt_busy"))
                return
            (p["attempt"] / "out").mkdir()
            self._detach(step_input, keys, lock)

    def poll(self, frame):
        key = self._key(frame)
        result = self.read_result(key)
        if result is not None and not self.processes(key):
            return Poll(PollState.DONE, result, checkpoint=self.read_checkpoint(key))
        return Poll(PollState.RUNNING if self.processes(key) else PollState.ABSENT,
                    checkpoint=self.read_checkpoint(key))

    def read_checkpoint(self, key):
        path = self.paths(key)["attempt"] / "checkpoint.json"
        try:
            ref = Ref(**json.loads(path.read_text()))
            return ref if ref.kind is ArtifactKind.CASE_SNAPSHOT else None
        except (FileNotFoundError, ValueError, TypeError):
            return None

    def bind_checkpoint(self, step_input, c, sealer, case_key, runner):
        from durable.checkpoints import checkpoint
        def prepare_models():
            import processes
            processes.prepare_model_containment(self.home)
        c.engine.prepare_models = prepare_models
        c.engine_checkpoint = lambda: self.publish_checkpoint(step_input, c, sealer, case_key, runner)
        c.stress_checkpoint = lambda: checkpoint(c)

    def publish_checkpoint(self, step_input, c, sealer, case_key, runner):
        """Publish durable ciphertext before exposing its authenticated reference."""
        from registry import atomic_json
        atomic_json(c.work / "scorecard.json", c.card)
        ref, ciphertext = sealer.seal(case_key, ArtifactKind.CASE_SNAPSHOT, snapshot_bytes(c, runner))
        attempt = self.paths(step_input.idempotency_key)["attempt"]
        out = attempt / "out"
        out.mkdir(parents=True, exist_ok=True)
        self._atomic_bytes(out / blob_name(ref), ciphertext)
        self._atomic_bytes(attempt / "checkpoint.json", json.dumps(to_record(ref)).encode())
        return True

    def _atomic_bytes(self, path, value):
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".checkpoint-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._sync_directory(path.parent)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def cancel(self, frame):
        key = self._key(frame)
        case_id = key.split("/", 1)[0]
        with self.case_lock(case_id):
            attempt = self.paths(key)["attempt"]
            attempt.mkdir(parents=True, exist_ok=True)  # tombstone: a late start does nothing
            self._index(case_id, key)
            self.stop(key)
            self.write_result(key, self._failure_result(key, "infra:cancelled"))

    def stop(self, key):
        """SIGTERM every process of the attempt, then SIGKILL what is left after the grace period."""
        pids = self.processes(key)
        for pid in pids:
            _signal(pid, signal.SIGTERM)
        deadline = time.monotonic() + KILL_GRACE_S
        while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
            time.sleep(0.1)
        for pid in self.processes(key) | {pid for pid in pids if _alive(pid)}:
            _signal(pid, signal.SIGKILL)

    @staticmethod
    def _key(frame):
        if not isinstance(frame, dict) or set(frame) != {"key"} or type(frame["key"]) is not str:
            raise FrameError("bad key frame")
        key = frame["key"]
        parts = key.split("/")
        if len(parts) != 4 or CASE_ID.fullmatch(parts[0]) is None:
            raise FrameError("bad idempotency key")
        return key

    @staticmethod
    def _keys(value, step_input):
        """Scope keys, or None when the keys object is unusable (answered as infra:bad_frame)."""
        if not isinstance(value, dict) or step_input.case_id not in value:
            return None
        if not set(value) <= {step_input.case_id, step_input.batch_id}:
            return None
        if step_input.step.kind is StepKind.ADMIT and step_input.batch_id not in value:
            return None
        keys = {}
        for scope, text in value.items():
            try:
                raw = base64.b64decode(text, validate=True)
            except (ValueError, TypeError):
                return None
            if len(raw) != 32:
                return None
            keys[scope] = raw
        return keys

    # the detached attempt
    def _publish_unit(self, step_input, pid):
        p = self.paths(step_input.idempotency_key)
        info = _stat(pid)
        unit = {"unit": p["unit"], "pid": pid, "starttime": info[2] if info else None}
        staged = p["attempt"] / "unit.json.tmp"
        with staged.open("w") as stream:
            json.dump(unit, stream)
            stream.flush()
            os.fsync(stream.fileno())
        staged.replace(p["attempt"] / "unit.json")
        self._sync_directory(p["attempt"])

    @staticmethod
    def _sync_directory(path):
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _detach(self, step_input, keys, lock):
        aid = attempt_id(step_input.idempotency_key)
        log_path = self.paths(step_input.idempotency_key)["attempt"] / "supervisor.log"
        sys.stdout.flush()
        sys.stderr.flush()
        reader, writer = os.pipe()
        pid = os.fork()
        if pid:
            os.close(reader)
            try:
                self._publish_unit(step_input, pid)
                os.write(writer, b"1")
            finally:
                os.close(writer)
            return pid
        code = 1
        try:
            os.close(writer)
            # EOF means the start command died before committing the unit record.
            # No supervisor or step may run in that case.
            ready = os.read(reader, 1)
            os.close(reader)
            if ready != b"1":
                os._exit(1)
            os.setsid()
            os.close(lock)  # the lock belongs to the start command
            log = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            null = os.open(os.devnull, os.O_RDONLY)
            os.dup2(null, 0)
            os.dup2(log, 1)
            os.dup2(log, 2)
            os.closerange(3, 65536)
            sys.stdout = os.fdopen(1, "w", buffering=1)
            sys.stderr = os.fdopen(2, "w", buffering=1)
            os.environ[TAG] = aid
            code = self.supervise(step_input, keys)
        except BaseException:
            traceback.print_exc()
        finally:
            os._exit(code)

    def supervise(self, step_input, keys):
        from worker_secrets import router_environment
        os.environ.update(router_environment())
        key = step_input.idempotency_key
        deadline = time.monotonic() + step_input.deadline_s
        os.environ["UNBUG_DURABLE_DEADLINE_EPOCH"] = str(self.clock() + step_input.deadline_s)
        os.environ["UNBUG_PROVIDER_WAIT"] = "1"
        pid = os.fork()
        if pid == 0:
            code = 1
            try:
                self.run_attempt(step_input, keys)
                code = 0
            except BaseException:
                traceback.print_exc()
            finally:
                sys.stdout.flush()
                os._exit(code)
        while True:
            done, _ = os.waitpid(pid, os.WNOHANG)
            if done:
                break
            if time.monotonic() >= deadline:
                self.stop(key)
                with contextlib.suppress(ChildProcessError):
                    os.waitpid(pid, 0)
                self.write_result(key, self._failure_result(key, "infra:deadline"))
                return 0
            time.sleep(POLL_INTERVAL_S)
        if not self.paths(key)["result"].exists():
            self.write_result(key, self._failure_result(key, "infra:step_crashed"))
        return 0

    def run_attempt(self, step_input, keys):
        try:
            result, outputs = self.execute(step_input, keys)
        except BaseException:
            traceback.print_exc()
            result, outputs = self._failure_result(step_input.idempotency_key, "infra:worker_error"), {}
        out = self.paths(step_input.idempotency_key)["out"]
        for name, ciphertext in outputs.items():
            staged = out / (name + ".tmp")
            with open(staged, "wb") as f:
                f.write(ciphertext)
                f.flush()
                os.fsync(f.fileno())
            staged.replace(out / name)
        self._sync_directory(out)
        self.write_result(step_input.idempotency_key, result)

    # one step
    def version_check(self, step_input):
        try:
            release = json.loads((self.home / RELEASE_MANIFEST).read_text())
        except (OSError, ValueError):
            return "infra:release_unreadable"
        if not isinstance(release, dict) or set(release) != {"plumbing_version", "bench_version"}:
            return "infra:release_unreadable"
        if (release["plumbing_version"] != step_input.plumbing_version
                or release["bench_version"] != step_input.bench_version):
            return "infra:version_mismatch"
        return None

    def sealer(self):
        if self._sealer is None:
            from durable.artifacts import AgeSealer   # WP3
            self._sealer = AgeSealer()
        return self._sealer

    def classifier(self):
        if self._classifier is None:
            from durable.classify import classify      # WP4
            self._classifier = classify
        return self._classifier

    def runner(self):
        if self._runner is None:
            import run
            self._runner = run
        return self._runner

    def _save_baseline(self, step_input, ledger, before):
        """The ledger position at the attempt's start, so a deadline or cancel can report usage so far."""
        path = self.paths(step_input.idempotency_key)["attempt"] / "baseline.json"
        staged = path.with_suffix(".tmp")
        staged.write_text(json.dumps({"ledger": str(ledger), "ceiling": step_input.money_ceiling_usd_micros,
                                      **{k: str(v) if isinstance(v, Decimal) else v for k, v in before.items()}}))
        staged.replace(path)

    def usage_so_far(self, key):
        """Usage of a killed attempt from its ledger, or Usage() if the step never reached the ledger."""
        try:
            saved = json.loads((self.paths(key)["attempt"] / "baseline.json").read_text())
            before = {"calls": saved["calls"], "total": saved["total"], "known": saved["known"],
                      "list": Decimal(saved["list"])}
            return usage_since(before, saved["ledger"], saved["ceiling"])
        except FileNotFoundError:
            if not (self.paths(key)["attempt"] / "baseline.json").exists():
                return Usage()  # Model execution cannot precede baseline publication.
            raise FrameError("usage unavailable") from None
        except Exception:
            raise FrameError("usage unavailable") from None

    def _failure_result(self, key, reason):
        try:
            usage = self.usage_so_far(key)
        except Exception:
            return StepResult(Outcome.INFRA_ERROR, "infra:usage_unknown")
        return StepResult(Outcome.INFRA_ERROR, reason, usage=usage)

    def open_blob(self, sealer, scope_key, ref):
        if ref is None:
            return None
        ciphertext = (self.home / WORKER_ROOT / "blobs" / blob_name(ref)).read_bytes()
        return sealer.open(scope_key, ref, ciphertext)

    def execute(self, step_input, keys):
        """(StepResult, {blob name: ciphertext}). The result is checked against the contract."""
        fail = lambda reason: (StepResult(Outcome.INFRA_ERROR, reason), {})
        reason = self.version_check(step_input)
        if reason:
            return fail(reason)
        kind = step_input.step.kind
        if kind is StepKind.ADMIT:
            from durable.steps.admit import run
            return run(self, step_input, keys)
        if kind is StepKind.DIAGNOSIS:
            from durable.steps.diagnosis import run
            return run(self, step_input, keys)
        try:
            sealer = self.sealer()
        except ImportError:
            return fail("infra:sealer_unavailable")
        try:
            classifier = self.classifier()
        except ImportError:
            return fail("infra:classifier_unavailable")
        case_key = keys[step_input.case_id]
        try:
            snapshot = self.open_blob(sealer, case_key, step_input.snapshot)
            feedback = self.open_blob(sealer, case_key, step_input.feedback)
            ruling = self.open_blob(sealer, case_key, step_input.ruling)
        except Exception:
            traceback.print_exc()
            return fail("infra:blob_unavailable")
        work = self.home / "work" / step_input.case_id
        try:
            restore(snapshot, work)
        except Exception:
            traceback.print_exc()
            return fail("infra:restore_failed")
        runner = self.runner()
        try:
            c = runner.context_for_step(step_input, work)
        except Exception:
            traceback.print_exc()
            return fail("infra:context_failed")
        before = ledger_totals(c.ledger)
        self._save_baseline(step_input, c.ledger, before)
        if before["total"] is None:
            return fail("infra:usage_unknown")
        self.bind_checkpoint(step_input, c, sealer, case_key, runner)
        out = runner.run_step(c, step_input, feedback=feedback, ruling=ruling)
        usage = usage_since(before, c.ledger, step_input.money_ceiling_usd_micros)
        if ledger_totals(c.ledger)["total"] is None:
            out = {"outcome": Outcome.INFRA_ERROR, "reason": "infra:usage_unknown"}
        return self.result(step_input, c, out, usage, sealer, case_key, classifier, runner)

    def result(self, step_input, c, out, usage, sealer, case_key, classifier, runner):
        outputs = {}

        def seal(kind, plaintext):
            ref, ciphertext = sealer.seal(case_key, kind, plaintext)
            outputs[blob_name(ref)] = ciphertext
            return ref

        kind = step_input.step.kind
        stop = out.get("stop")
        fields = {"usage": usage}
        if "outcome" in out and stop is None:
            outcome = Outcome(out["outcome"])
            fields.update(outcome=outcome, reason=out["reason"])
            if out.get("gate") is not None: fields["gate"] = out["gate"]
            if out.get("repairable"): fields["repairable"] = True
            if out.get("feedback") is not None: fields["feedback"] = seal(ArtifactKind.WRITER_FEEDBACK, out["feedback"])
            if out.get("archive") is not None:
                fields["archive"] = seal(ArtifactKind.SEALED_ARCHIVE, out["archive"])
                fields["hard"] = bool(out.get("hard"))
        else:
            arguments = {"step": kind, "now": self.clock()}
            if out.get("reset_at") is not None:
                arguments["reset_at"] = out["reset_at"]
            classified = classifier(stop if isinstance(stop, str) else "", **arguments)
            outcome = classified.outcome
            fields.update(outcome=outcome, reason=classified.reason, retry_at=classified.retry_at)
        if kind is StepKind.GATES:
            fields["passed"] = tuple(out.get("passed") or ())
            if out.get("receipt") is not None: fields["receipt"] = seal(ArtifactKind.GATE_RECEIPT, out["receipt"])
        try:
            fields["snapshot"] = seal(ArtifactKind.CASE_SNAPSHOT, snapshot_bytes(c, runner))
        except Exception:
            traceback.print_exc()
            if outcome is Outcome.OK:
                return StepResult(Outcome.INFRA_ERROR, "infra:snapshot_failed", usage=usage), outputs
        if outcome is not Outcome.OK:
            fields["diagnostic"] = seal(ArtifactKind.DIAGNOSTIC, diagnostic(c, out))
        try:
            result = StepResult(**fields)
            check_result_for(step_input.step, result)
        except ContractError:
            traceback.print_exc()
            keep = {k: fields[k] for k in ("snapshot", "diagnostic") if k in fields}
            result = StepResult(Outcome.INFRA_ERROR, "infra:bad_result", usage=usage, **keep)
        return result, outputs


# ---- snapshot, restore, usage ------------------------------------------------------------------

def snapshot_bytes(c, runner):
    """tar.gz of the runner's retained subset of c.work, member names relative to c.work."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        for relative in runner.retained_paths(c):
            tar.add(c.work / relative, arcname=pathlib.PurePath(relative).as_posix())
    return buffer.getvalue()


def restore(snapshot, work):
    """Replace the work tree with exactly the snapshot. The data filter refuses links or paths outside it."""
    work = pathlib.Path(work)
    if work.exists() or work.is_symlink():
        if work.is_symlink() or not work.is_dir():
            work.unlink()
        else:
            shutil.rmtree(work)
    work.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(snapshot), mode="r:*") as tar:
        tar.extractall(work, filter="data")


def ledger_totals(path):
    from budget import _event_components, case_spending, outstanding_reservations
    try:
        ledger = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {"calls": 0, "total": None, "known": 0, "list": Decimal(0)}
    summary = case_spending(ledger)
    events = {e["id"]: e for e in ledger.get("events", []) if isinstance(e, dict) and isinstance(e.get("id"), str)}
    listed = Decimal(0)
    for event in events.values():
        try:
            listed += sum(Decimal(str(v)) for v in _event_components(event)[1:])
        except Exception:
            pass
    calls = ledger.get("calls", 0)
    # A hard death can prevent the call's final receipt from being written. Keep
    # its unspent authorization held; an absent receipt is never evidence of $0.
    pending = outstanding_reservations(ledger)
    total = summary.get("total_spent_usd")
    known = summary.get("known_total_spent_usd", total) or 0
    return {"calls": calls if type(calls) is int else 0,
            "total": None if total is None else Decimal(str(total)) + pending,
            "known": Decimal(str(known)) + pending, "list": listed}


def usage_since(before, path, ceiling_micros):
    json.loads(pathlib.Path(path).read_text())  # Missing or corrupt usage is never zero spend.
    after = ledger_totals(path)
    calls = max(0, after["calls"] - before["calls"])
    if after["total"] is None or before["total"] is None:
        paid = max(_micros_up(max(0, Decimal(str(after["known"])) - Decimal(str(before["known"])))), ceiling_micros)
    else:
        paid = _micros_up(max(Decimal(0), Decimal(str(after["total"])) - Decimal(str(before["total"]))))
    listed = _micros_up(max(Decimal(0), after["list"] - before["list"]))
    return Usage(calls=calls, paid_usd_micros=paid, list_usd_micros=listed)


def diagnostic(c, out):
    """DIAGNOSTIC plaintext: the stop, its traceback and the tail of the runner log (sealed, never recorded)."""
    log = c.work / "logs" / "runner.log"
    try:
        tail = log.read_bytes()[-LOG_TAIL:].decode(errors="replace")
    except OSError:
        tail = ""
    return json.dumps({"stop": out.get("stop"), "reason": out.get("reason"),
                       "traceback": out.get("traceback"), "runner_log_tail": tail}, sort_keys=True).encode()


# ---- command line ------------------------------------------------------------------------------

def main(argv=None, *, worker=None, stdin=None, stdout=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if len(argv) != 1 or argv[0] not in ("start", "poll", "cancel"):
        print("usage: worker_step.py start|poll|cancel", file=sys.stderr)
        return 2
    raw = (stdin if stdin is not None else sys.stdin.buffer).read(MAX_FRAME + 1)
    if len(raw) > MAX_FRAME:
        return 2
    try:
        frame = json.loads(raw)
    except ValueError:
        return 2
    worker = worker or Worker()
    try:
        if argv[0] == "start":
            worker.start(frame)
        elif argv[0] == "poll":
            line = json.dumps(to_record(worker.poll(frame)), sort_keys=True)
            out = stdout if stdout is not None else sys.stdout
            out.write(line + "\n")
            out.flush()
        else:
            worker.cancel(frame)
    except (FrameError, ContractError, OSError, ValueError, KeyError, TypeError):
        traceback.print_exc()
        return 2
    return 0


if __name__ == "__main__":
    # Factory code is installed separately from the qualified baked bench.
    os.environ.setdefault("BENCH", str(pathlib.Path.home() / "unbug-bench"))
    sys.exit(main())
