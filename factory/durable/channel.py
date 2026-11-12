"""WP2: the control side of the worker wire protocol (WorkerChannel over `boat ssh`).

Design: docs/designs/durable-execution-wp2.md; the protocol is frozen in contract.py
(RELEASE_MANIFEST docstring, attempt_paths, start_frame, key_frame, Poll).

A transport failure (ssh error, timeout, any exit status but 0, output that is not one
`to_record(Poll)` line) is RUNNING, never ABSENT. DONE is returned only once every
output blob is in the ArtifactStore. No method raises on worker errors; bad caller input
is a ContractError before any transport.
"""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import time
from typing import Mapping

from durable.artifacts import ArtifactError

from durable.contract import (BATCH_SCOPED, RELEASE_ROOT, WORKER_COMMAND, ArtifactKind, ArtifactStore, Outcome, Poll,
                              PollState, Ref, StepInput, StepKind, StepResult, WorkerLease, _check, attempt_paths, key_frame,
                              poll_from_record, start_frame)
from durable.workers import BoatCli, boat_id

BLOB_NAME = re.compile(r"([0-9a-f]{64})\.(" + "|".join(k.value for k in ArtifactKind) + r")\.age")
OUTPUT_FIELDS = ("snapshot", "receipt", "feedback", "report", "registry", "archive", "diagnostic")
RUNNING = Poll(PollState.RUNNING)


def blob_name(ref: Ref) -> str:
    """attempt_paths naming of one ciphertext: <digest>.<kind>.age."""
    _check(isinstance(ref, Ref), "a Ref is required")
    return f"{ref.digest}.{ref.kind.value}.age"


def scope_of(step_input: StepInput, ref: Ref) -> str:
    """Batch-scoped kinds live under the batch, everything else under the case."""
    return step_input.batch_id if ref.kind in BATCH_SCOPED else step_input.case_id


def output_refs(result: StepResult) -> list[Ref]:
    return [r for r in (getattr(result, f) for f in OUTPUT_FIELDS) if r is not None]


def worker_command(verb: str) -> str:
    _check(verb in ("start", "poll", "cancel"), "bad worker verb")
    return f"cd ~/{RELEASE_ROOT} && exec {shlex.join(WORKER_COMMAND)} {verb}"


class BoatChannel:
    """WorkerChannel on Boat. Workers hold no R2 credentials: blobs move over ssh here."""

    def __init__(self, store: ArtifactStore, *, keys, sealer, boat: BoatCli | None = None,
                 command_timeout: float = 120.0, blob_timeout: float = 600.0,
                 output_retry_s: float = 60.0, clock=time.monotonic, helpers=None):
        self.store, self.boat = store, boat or BoatCli()
        self.helpers = helpers   # helper_link.Broker, or None: GATES attempts get no helper machines
        self.keys, self.sealer = keys, sealer
        self.command_timeout, self.blob_timeout = command_timeout, blob_timeout
        self.output_retry_s, self.clock = output_retry_s, clock
        self._missing_since = {}

    # -- WorkerChannel

    def start(self, lease: WorkerLease, step_input: StepInput, keys: Mapping[str, bytes],
              blobs: Mapping[str, bytes]) -> None:
        _check(isinstance(lease, WorkerLease) and lease.case_id == step_input.case_id, "lease is for another case")
        for name, data in blobs.items():
            _check(type(name) is str and BLOB_NAME.fullmatch(name) is not None, "blob names are <digest>.<kind>.age")
            _check(type(data) is bytes, "blob ciphertext must be bytes")
        frame = json.dumps(start_frame(step_input, keys)).encode()
        worker = boat_id(lease.worker_id)
        try:
            blob_dir = attempt_paths(step_input.idempotency_key)["blobs"]
            for name in sorted(blobs):
                if not self._push(worker, blob_dir, name, blobs[name]):
                    return   # no frame: the next poll is ABSENT and the engine retries
            if self.helpers is not None and step_input.step.kind is StepKind.GATES:
                self.helpers.prepare(worker, step_input)   # a failure only leaves this attempt without helpers
            self.boat.ssh(worker, worker_command("start"), stdin=frame, timeout=self.command_timeout)
        except Exception:   # noqa: BLE001 - never raise on worker errors
            return

    def poll(self, lease: WorkerLease, step_input: StepInput) -> Poll:
        _check(isinstance(lease, WorkerLease) and lease.case_id == step_input.case_id, "lease is for another case")
        try:
            worker = boat_id(lease.worker_id)
            key = step_input.idempotency_key
            code, out = self.boat.ssh(worker, worker_command("poll"), stdin=json.dumps(key_frame(key)).encode(),
                                      timeout=self.command_timeout)
            if code != 0:
                return RUNNING
            lines = out.decode("utf-8").split("\n")
            if lines[-1] == "":
                lines.pop()
            if len(lines) != 1:
                return RUNNING
            poll = poll_from_record(json.loads(lines[0]))
            if self.helpers is not None and step_input.step.kind is StepKind.GATES:
                if poll.state is PollState.RUNNING: self.helpers.watch(worker, step_input)
                elif poll.state is PollState.DONE: self.helpers.finish(step_input)
            out_dir = attempt_paths(key)["out"]
            if poll.state is PollState.DONE:
                for ref in output_refs(poll.result):
                    if not self._fetch(worker, out_dir, scope_of(step_input, ref), ref):
                        identity = (lease.worker_id, key)
                        since = self._missing_since.setdefault(identity, self.clock())
                        if self.clock() - since >= self.output_retry_s:
                            # The worker explicitly confirmed completion. A missing
                            # blob is infrastructure failure, not a live attempt.
                            result = StepResult(Outcome.INFRA_ERROR, "infra:output_unavailable",
                                                usage=poll.result.usage)
                            return Poll(PollState.DONE, result)
                        return RUNNING
                self._missing_since.pop((lease.worker_id, key), None)
            if poll.checkpoint is not None and not self._fetch(worker, out_dir, step_input.case_id, poll.checkpoint):
                return Poll(poll.state, poll.result)
            return poll
        except Exception:   # noqa: BLE001 - transport or parse failure is RUNNING
            return RUNNING

    def cancel(self, lease: WorkerLease, step_input: StepInput) -> None:
        _check(isinstance(lease, WorkerLease) and lease.case_id == step_input.case_id, "lease is for another case")
        if self.helpers is not None:
            self.helpers.finish(step_input)
        try:
            self.boat.ssh(boat_id(lease.worker_id), worker_command("cancel"),
                          stdin=json.dumps(key_frame(step_input.idempotency_key)).encode(),
                          timeout=self.command_timeout)
        except Exception:   # noqa: BLE001 - the next poll shows whether the cancel landed
            return

    # -- blobs

    def _push(self, worker: str, blobs: str, name: str, data: bytes) -> bool:
        digest = hashlib.sha256(data).hexdigest()
        script = (f"set -eu; umask 077; d=~/{blobs}; mkdir -p \"$d\"; t=\"$d/.{name}.$$\"; cat > \"$t\"; "
                  f"if printf '%s  %s\\n' {digest} \"$t\" | sha256sum -c - >/dev/null; "
                  f"then mv \"$t\" \"$d/{name}\"; else rm -f \"$t\"; exit 1; fi")
        code, _ = self.boat.ssh(worker, script, stdin=data, timeout=max(self.blob_timeout, len(data) / 262_144))
        return code == 0

    def _fetch(self, worker: str, out_dir: str, scope: str, ref: Ref) -> bool:
        key = self.keys.scope_key(scope)
        if self.store.exists(scope, ref):
            data = self.store.get_sealed(scope, ref)
            try:
                self.sealer.open(key, ref, data)
            except ArtifactError:
                return False
            return True
        name = blob_name(ref)
        script = f"set -eu; f=~/{out_dir}/{name}; test -f \"$f\"; sha256sum < \"$f\" | cut -c1-64; cat \"$f\""
        code, out = self.boat.ssh(worker, script, timeout=self.blob_timeout)
        if code != 0 or len(out) < 65 or out[64:65] != b"\n":
            return False
        digest, data = out[:64].decode("ascii", "replace"), out[65:]
        if hashlib.sha256(data).hexdigest() != digest:
            return False
        # The worker's checksum is only a transport check. Authenticate before
        # first-wins publication, so bad ciphertext cannot poison a valid Ref.
        try:
            self.sealer.open(key, ref, data)
        except ArtifactError:
            return False
        self.store.put_sealed(scope, ref, data)
        stored = self.store.get_sealed(scope, ref)
        try:
            self.sealer.open(key, ref, stored)
        except ArtifactError:
            return False
        return True
