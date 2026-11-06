"""The step executor: one attempt end to end, through the seams the other packages build.

WP1, docs/designs/durable-execution-wp1.md. `Executor.run` is the contract's StepExecutor;
the engine calls it only through `guarded_run`. The other methods are the engine's other
side effects (reserve, settle, cancel, release, sealing). Each is called inside its own
engine step and raises only `SeamError`, whose text is a fixed reason code: the engine
database records every exception, and a seam's own message may hold case content.

Control VM only. Keys exist here only in memory, on their way into `start_frame` or the
Sealer.
"""
from __future__ import annotations

import json
from dataclasses import replace
import time
from typing import Optional

from durable.artifacts import ArtifactError, open_from, scope_for
from durable.contract import (ArtifactKind, ArtifactStore, Grant, KeyService, Ledger, Outcome, Poll,
                              PollState, Ref, Sealer, StepInput, StepKind, StepResult, WorkerChannel, WorkerLease,
                              WorkerPool)
from durable.policy import POLL_GRACE_S, UNCONFIRMED_WORKER_LIMIT_S, settles_as_waste, settles_lost

OUTPUT_REFS = ("snapshot", "receipt", "feedback", "report", "registry", "archive", "diagnostic")


class SeamError(Exception):
    """A seam call failed. The message is a fixed code, never the seam's own text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _call(code, fn, *args, **kwargs):
    """Run a seam call; replace any exception with SeamError(code). The new exception is raised
    outside the handler, so it carries no __context__ pointing at the original."""
    failed = False
    try:
        return fn(*args, **kwargs)
    except SeamError:
        raise
    except Exception:
        failed = True
    if failed:
        raise SeamError(code)


def blob_name(ref: Ref) -> str:
    """Name of an input ciphertext in the worker's blobs/ (contract.attempt_paths)."""
    return f"{ref.digest}.{ref.kind.value}.age"


def scope_of(si: StepInput, ref: Ref) -> str:
    """Use the contract's scope for both input and output references."""
    return scope_for(ref.kind, si.case_id, si.batch_id)


def input_refs(si: StepInput) -> list:
    refs = [si.inputs, si.snapshot, si.feedback, si.registry, si.ruling, *si.evidence]
    return [r for r in refs if r is not None]


class Executor:
    def __init__(self, pool: WorkerPool, channel: WorkerChannel, ledger: Ledger, store: ArtifactStore,
                 sealer: Sealer, keys: KeyService, *, poll_interval_s: float = 30.0,
                 grace_s: float = POLL_GRACE_S, clock=time.time, sleep=time.sleep,
                 pause=lambda: None, unconfirmed_limit_s: float = UNCONFIRMED_WORKER_LIMIT_S):
        self.pool, self.channel, self.ledger, self.store = pool, channel, ledger, store
        self.sealer, self.keys = sealer, keys
        self.poll_interval_s, self.grace_s = poll_interval_s, grace_s
        self.clock, self.sleep = clock, sleep
        self.pause, self.unconfirmed_limit_s = pause, unconfirmed_limit_s

    # ---- the attempt (StepExecutor) ------------------------------------------------------------

    def bound(self, started_at: float, lease: WorkerLease) -> "_Bound":
        """Bind a recorded lease and control-side start time to a replayable attempt."""
        return _Bound(self, started_at, lease)

    def run(self, si: StepInput, *, started_at: Optional[float] = None,
            lease: Optional[WorkerLease] = None) -> StepResult:
        start = self.clock() if started_at is None else started_at
        try:
            if lease is None:
                lease = self.pool.acquire(si.case_id, si.plumbing_version, si.bench_version)
        except Exception:
            return StepResult(Outcome.INFRA_ERROR, "infra:dispatch_failed")
        try:
            keys = {si.case_id: self.keys.scope_key(si.case_id)}
            if si.step.kind is StepKind.ADMIT:
                keys[si.batch_id] = self.keys.scope_key(si.batch_id)
            blobs = {blob_name(r): self.store.get_sealed(scope_of(si, r), r) for r in input_refs(si)}
        except Exception:
            # A replay may have started the worker before the crash. Reconcile it even
            # when inputs cannot currently be fetched; never assume zero spend here.
            keys = blobs = None
        if keys is not None:
            try:
                self.channel.start(lease, si, keys, blobs)
            except Exception:
                pass   # it may have landed; the poll below tells
        del keys, blobs
        # Blob transfer and the start reply can take longer than the worker's
        # deadline. The worker starts its own timer only after transfer; never
        # cancel it early because the control-side clock started beforehand.
        # On replay this may delay a cancellation, but the worker's own deadline
        # remains in force and no second attempt is started meanwhile.
        limit = max(start, self.clock()) + si.deadline_s + self.grace_s
        checkpoint = None
        while True:
            self.pause()   # shutdown: leave the step unrecorded, so a restart reattaches
            poll = self._poll(lease, si)
            if poll.checkpoint is not None:
                checkpoint = poll.checkpoint
            if poll.state is PollState.DONE:
                return self._check_outputs(si, poll.result, checkpoint)
            if self.clock() >= limit + self.unconfirmed_limit_s and self._retire(lease):
                return self._lost(si, "infra:worker_lost", checkpoint)
            if poll.state is PollState.ABSENT:
                # A timed-out start could still arrive late. A tombstone or proven
                # worker death is required before a different attempt can begin.
                done = self._cancel_confirm(lease, si, self.clock() + self.grace_s)
                if done is not None:
                    if done.reason == "infra:cancelled":
                        return self._lost(si, "infra:attempt_absent", checkpoint)
                    return self._check_outputs(si, done)
                if not self._alive(lease):
                    return self._lost(si, "infra:worker_lost", checkpoint)
                continue
            if not self._alive(lease):
                return self._lost(si, "infra:worker_lost", checkpoint)
            if self.clock() >= limit:
                # Input transfer may have used the whole deadline before the worker
                # started. Repeatedly cancel and reconcile; elapsed time is not proof
                # that the worker stopped, and a late DONE result always wins.
                done = self._cancel_confirm(lease, si, self.clock() + self.grace_s)
                if done is not None:
                    return self._check_outputs(si, done)
                if not self._alive(lease):
                    return self._lost(si, "infra:worker_lost", checkpoint)
                continue
            self.sleep(self.poll_interval_s)

    def _poll(self, lease, si) -> Poll:
        try:
            poll = self.channel.poll(lease, si)
            if isinstance(poll, Poll):
                return poll
        except Exception:
            pass
        return Poll(PollState.RUNNING)   # a transport failure is RUNNING, never ABSENT

    def _retire(self, lease) -> bool:
        """Past the limit a worker counts as lost only once it cannot still be running. The guard
        keeps renewing a live worker, so its TTL proves nothing: delete it. If the delete fails,
        keep waiting and ask again on the next round."""
        try:
            self.pool.release(lease)
            return True
        except Exception:
            return False

    def _alive(self, lease) -> bool:
        try:
            return bool(self.pool.alive(lease))
        except Exception:
            return True   # unknown is not gone: never start a second attempt on a guess

    def _verify_ref(self, si, ref) -> str:
        """Retry unavailable seams without discarding a completed result or checkpoint."""
        invalid = {"not_age_ciphertext", "digest_mismatch", "ciphertext_not_bytes",
                   "bad_ref", "bad_scope", "wrong_scope"}
        while True:
            try:
                exists = self.store.exists(scope_of(si, ref), ref)
            except Exception:
                self.sleep(self.poll_interval_s)
                continue
            if not exists:
                return "missing"
            try:
                open_from(self.store, self.keys, self.sealer, ref, case_id=si.case_id, batch_id=si.batch_id)
                return "ok"
            except ArtifactError as error:
                if error.code in invalid:
                    return "invalid"
            except Exception:
                pass
            self.sleep(self.poll_interval_s)

    def _check_outputs(self, si: StepInput, result: StepResult, checkpoint=None) -> StepResult:
        """DONE outputs must exist and authenticate under their prescribed scope."""
        if not isinstance(result, StepResult):
            return StepResult(Outcome.INFRA_ERROR, "engine:executor_bad_result")
        for name in OUTPUT_REFS:
            ref = getattr(result, name)
            if ref is not None:
                state = self._verify_ref(si, ref)
                if state != "ok":
                    return StepResult(Outcome.INFRA_ERROR, f"infra:output_{state}", result.usage)
        if result.snapshot is None and checkpoint is not None and self._verify_ref(si, checkpoint) == "ok":
            result = replace(result, snapshot=checkpoint)
        return result

    def _lost(self, si, reason, checkpoint) -> StepResult:
        snap = checkpoint if checkpoint is not None and self._verify_ref(si, checkpoint) == "ok" else None
        return StepResult(Outcome.INFRA_ERROR, reason, snapshot=snap)

    def _cancel_confirm(self, lease, si, until) -> Optional[StepResult]:
        """cancel() returns nothing, so a cancel counts only once a poll shows a result (the
        attempt's own or infra:cancelled). Retried through transport failures until the worker
        answers, the worker is gone, or `until`."""
        first = True
        while first or self.clock() < until:
            first = False
            try:
                self.channel.cancel(lease, si)
            except Exception:
                pass
            poll = self._poll(lease, si)
            if poll.state is PollState.DONE:
                return self._check_outputs(si, poll.result, poll.checkpoint)
            if not self._alive(lease):
                return None
            self.sleep(self.poll_interval_s)
        return None

    def reconcile(self, si: StepInput, lease: WorkerLease) -> StepResult:
        """After an unexpected executor failure, resolve the exact prior worker.

        The failure may have happened after dispatch. Do not start another attempt
        or settle its unknown spend until the worker returns a result, is gone, or has
        stayed unconfirmed past the limit and been deleted.
        """
        until = self.clock() + self.unconfirmed_limit_s
        while True:
            self.pause()
            done = self._cancel_confirm(lease, si, self.clock() + self.grace_s)
            if done is not None:
                return self._check_outputs(si, done)
            if not self._alive(lease) or (self.clock() >= until and self._retire(lease)):
                return self._lost(si, "infra:worker_lost", None)

    # ---- the engine's other side effects -------------------------------------------------------

    def cancel(self, si: StepInput, started_at: float, worker_id: Optional[str] = None) -> bool:
        """Repeat cancellation for an already-reconciled prior attempt, on its original worker.

        ``run`` has already obtained DONE or proven worker death before a retry reaches
        here. This final cancellation never provisions a replacement for a released worker.
        """
        lease = (WorkerLease(worker_id, si.case_id) if worker_id else
                 _call("engine:pool_failed", self.pool.acquire, si.case_id, si.plumbing_version, si.bench_version))
        until = started_at + si.deadline_s + self.grace_s
        return self._cancel_confirm(lease, si, until) is not None

    def reserve(self, si: StepInput, *, request: int, case_limit: int, draws_case_money: bool) -> Grant:
        grant = _call("engine:ledger_failed", self.ledger.reserve, si.batch_id, si.case_id, si.idempotency_key,
                      request, case_limit, draws_case_money=draws_case_money)
        if not isinstance(grant, Grant):
            raise SeamError("engine:ledger_failed")
        return grant

    def release_unstarted(self, si: StepInput) -> None:
        """An attempt that never started frees its reservation, booking nothing."""
        from durable.contract import Usage
        _call("engine:ledger_failed", self.ledger.settle, si.idempotency_key, Usage(), waste=False)

    def settle(self, si: StepInput, result: StepResult) -> str:
        if settles_lost(result):
            _call("engine:ledger_failed", self.ledger.settle_lost, si.idempotency_key)
            return "lost"
        waste = settles_as_waste(result)
        _call("engine:ledger_failed", self.ledger.settle, si.idempotency_key, result.usage, waste=waste)
        return "waste" if waste else "case"

    def open_batch(self, batch_id: str, bound: int) -> None:
        _call("engine:ledger_failed", self.ledger.open, batch_id, bound)

    def raise_bound(self, batch_id: str, bound: int) -> None:
        _call("engine:ledger_failed", self.ledger.raise_bound, batch_id, bound)

    def release(self, lease: WorkerLease) -> None:
        _call("engine:pool_failed", self.pool.release, lease)

    def lease_alive(self, lease: WorkerLease) -> bool:
        alive = _call("engine:pool_failed", self.pool.alive, lease)
        if type(alive) is not bool:
            raise SeamError("engine:pool_failed")
        return alive

    def lease_for(self, case_id: str, plumbing_version: str, bench_version: str) -> WorkerLease:
        reason = "infra:pool_failed"
        try:
            return self.pool.acquire(case_id, plumbing_version, bench_version)
        except Exception as error:
            # WP2's PoolError contains only a validated, fixed infra reason. Never
            # forward arbitrary exception messages from a provider or its SDK.
            try:
                from durable.workers import PoolError
                if isinstance(error, PoolError):
                    reason = error.reason
            except ImportError:
                pass
        raise SeamError(reason)

    def seal_history(self, case_id: str, history: list) -> Ref:
        """The engine's own stop history (codes and numbers only), sealed with the case key as a
        DIAGNOSTIC for the diagnosis evidence."""
        plaintext = json.dumps(history, sort_keys=True, separators=(",", ":")).encode()
        key = _call("engine:keys_failed", self.keys.scope_key, case_id)
        ref, ciphertext = _call("engine:sealer_failed", self.sealer.seal, key, ArtifactKind.DIAGNOSTIC, plaintext)
        _call("engine:store_failed", self.store.put_sealed, case_id, ref, ciphertext)
        return ref

class _Bound:
    def __init__(self, executor: Executor, started_at: float, lease: WorkerLease):
        self._executor, self._started_at, self._lease = executor, started_at, lease

    def run(self, si: StepInput) -> StepResult:
        return self._executor.run(si, started_at=self._started_at, lease=self._lease)
