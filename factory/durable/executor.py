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

from durable.artifacts import ArtifactError, ArtifactMissing, open_from, scope_for
from durable.contract import (ArtifactKind, ArtifactStore, Grant, KeyService, Ledger, Outcome, Poll,
                              PollState, Ref, Sealer, StepInput, StepKind, StepResult, WorkerChannel, WorkerLease,
                              WorkerPool, UNANSWERED, Usage)
from durable.policy import (LOST_MISSES, LOST_WINDOW_S, POLL_GRACE_S, SILENT_WORKER_LIMIT_S, UNCONFIRMED_WORKER_LIMIT_S,
                             settles_as_waste, settles_lost)

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
    """The step's own input refs. Evidence is fetched apart (Executor._inputs)."""
    refs = [si.inputs, si.snapshot, si.feedback, si.registry, si.ruling]
    return [r for r in refs if r is not None]


class Executor:
    def __init__(self, pool: WorkerPool, channel: WorkerChannel, ledger: Ledger, store: ArtifactStore,
                 sealer: Sealer, keys: KeyService, *, poll_interval_s: float = 30.0,
                 grace_s: float = POLL_GRACE_S, clock=time.time, sleep=time.sleep,
                 pause=lambda: None, unconfirmed_limit_s: float = UNCONFIRMED_WORKER_LIMIT_S,
                 renewing=None, silent_limit_s: float = SILENT_WORKER_LIMIT_S, lost_window_s: float = LOST_WINDOW_S):
        self.pool, self.channel, self.ledger, self.store = pool, channel, ledger, store
        self.sealer, self.keys = sealer, keys
        self.poll_interval_s, self.grace_s = poll_interval_s, grace_s
        self.clock, self.sleep = clock, sleep
        self.pause, self.unconfirmed_limit_s = pause, unconfirmed_limit_s
        # renewing(lease) -> False only when the worker's lease renewal is known to have stopped
        # (guard.renewing). None, or any other answer, never retires a worker early.
        self.renewing, self.silent_limit_s = renewing, silent_limit_s
        self.lost_window_s = lost_window_s   # _Presence: how long LOST_MISSES misses in a row must span

    # ---- the attempt (StepExecutor) ------------------------------------------------------------

    def bound(self, started_at: float, lease: WorkerLease, stopped=lambda: False) -> "_Bound":
        """Bind a recorded lease and control-side start time to a replayable attempt."""
        return _Bound(self, started_at, lease, stopped)

    def run(self, si: StepInput, *, started_at: Optional[float] = None,
            lease: Optional[WorkerLease] = None, stopped=lambda: False) -> StepResult:
        """stopped() true: the founder stopped the case. The attempt is not started, or is cancelled on its
        worker (a tombstone and infra:cancelled with the usage so far), and ends with that result."""
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
            sent, blobs = self._inputs(si, keys[si.case_id])
        except Exception:
            # A replay may have started the worker before the crash. Reconcile it even
            # when inputs cannot currently be fetched; never assume zero spend here.
            keys = blobs = None
        if keys is not None and not stopped():
            try:
                self.channel.start(lease, sent, keys, blobs)
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
        last_answer = self.clock()
        presence = _Presence(self, lease)
        while True:
            self.pause()   # shutdown: leave the step unrecorded, so a restart reattaches
            if stopped():
                try:
                    self.channel.cancel(lease, si)   # the poll below shows whether it landed
                except Exception:
                    pass
            poll = self._poll(lease, si)
            if poll is not UNANSWERED:
                last_answer = self.clock()
            elif self._silent_and_unrenewed(lease, last_answer) and self._retire(lease):
                return self._lost(si, "infra:worker_lost", checkpoint)
            if poll.checkpoint is not None:
                checkpoint = poll.checkpoint
            if poll.state is PollState.DONE:
                return self._check_outputs(si, poll.result, checkpoint)
            if self.clock() >= limit + self.unconfirmed_limit_s and self._retire(lease):
                return self._lost(si, "infra:worker_lost", checkpoint)
            if poll.state is PollState.ABSENT:
                # A timed-out start could still arrive late. A tombstone or proven
                # worker death is required before a different attempt can begin.
                done = self._cancel_confirm(lease, si, self.clock() + self.grace_s, presence)
                if done is not None:
                    if done.reason == "infra:cancelled":
                        return self._lost(si, "infra:attempt_absent", checkpoint)
                    return self._check_outputs(si, done)
                if presence.lost:
                    return self._lost(si, "infra:worker_lost", checkpoint)
                continue
            if presence.gone(poll is not UNANSWERED):
                return self._lost(si, "infra:worker_lost", checkpoint)
            if self.clock() >= limit:
                # Input transfer may have used the whole deadline before the worker
                # started. Repeatedly cancel and reconcile; elapsed time is not proof
                # that the worker stopped, and a late DONE result always wins.
                done = self._cancel_confirm(lease, si, self.clock() + self.grace_s, presence)
                if done is not None:
                    return self._check_outputs(si, done)
                if presence.lost:
                    return self._lost(si, "infra:worker_lost", checkpoint)
                continue
            self.sleep(self.poll_interval_s)

    def _inputs(self, si: StepInput, case_key: bytes):
        """(the step input the worker starts on, {blob name: ciphertext}). Any input ref the store
        cannot return raises, as does any store error. The one exception is an evidence ref the
        store answers is gone (ArtifactMissing, a 404): R2 deletes every object 7 days after
        upload (lifecycle rule expire-7d), and a case's evidence outlives that. On 16 November
        case-import-1bb2ad-2-1 could never diagnose again: 12 of its 18 evidence refs were gone.
        The worker starts without them, and a DIAGNOSTIC note (codes and numbers only, a JSON
        object so diagnosis._history never takes it for the stop history) says what was lost.
        The attempt's identity is its idempotency key, which evidence is no part of."""
        blobs = {blob_name(r): self.store.get_sealed(scope_of(si, r), r) for r in input_refs(si)}
        kept, lost = [], {}
        for i, r in enumerate(si.evidence):
            try:
                blobs[blob_name(r)] = self.store.get_sealed(scope_of(si, r), r)
                kept.append(r)
            except ArtifactMissing:
                if i == len(si.evidence) - 1:
                    # The engine's stop history (engine.py: evidence ends with it). Without it the
                    # code-decided factory_bug verdict cannot fire and a paid agent guesses: fail as before.
                    raise
                lost[r.kind.value] = lost.get(r.kind.value, 0) + 1
        if not lost:
            return si, blobs
        note = {"lost_evidence": {"reason": "artifact_missing", "count": sum(lost.values()), "kinds": lost}}
        ref, ciphertext = self.sealer.seal(case_key, ArtifactKind.DIAGNOSTIC,
                                           json.dumps(note, sort_keys=True, separators=(",", ":")).encode())
        blobs[blob_name(ref)] = ciphertext
        return replace(si, evidence=(*kept, ref)), blobs

    def _poll(self, lease, si) -> Poll:
        try:
            poll = self.channel.poll(lease, si)
            if isinstance(poll, Poll):
                return poll
        except Exception:
            pass
        return UNANSWERED   # a transport failure is RUNNING, never ABSENT

    def _silent_and_unrenewed(self, lease, last_answer: float) -> bool:
        if self.renewing is None or self.clock() - last_answer < self.silent_limit_s:
            return False
        try:
            return self.renewing(lease) is False
        except Exception:
            return False   # unknown renewal is not stopped renewal

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

    def _cancel_confirm(self, lease, si, until, presence=None) -> Optional[StepResult]:
        """cancel() returns nothing, so a cancel counts only once a poll shows a result (the
        attempt's own or infra:cancelled). Retried through transport failures until the worker
        answers, the worker is gone (presence.lost), or `until`."""
        presence = presence or _Presence(self, lease, misses=1, window_s=0.0)
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
            if presence.gone(poll is not UNANSWERED):
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
        presence = _Presence(self, lease)
        while True:
            self.pause()
            done = self._cancel_confirm(lease, si, self.clock() + self.grace_s, presence)
            if done is not None:
                return self._check_outputs(si, done)
            if presence.lost or (self.clock() >= until and self._retire(lease)):
                return self._lost(si, "infra:worker_lost", None)

    # ---- the engine's other side effects -------------------------------------------------------

    def cancel(self, si: StepInput, started_at: float, worker_id: Optional[str] = None) -> bool:
        """Repeat cancellation for an already-reconciled prior attempt, on its original worker.

        ``run`` has already obtained DONE or proven worker death before a retry reaches
        here. This final cancellation never provisions a replacement for a released worker.
        One inventory miss ends it, as before: the prior attempt is already settled, its worker is most
        often one the engine released (a park, a pause), and waiting out _Presence's window would delay
        every such retry by two minutes. A live leftover is caught by the start's attempt_busy wait.
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

    def settle(self, si: StepInput, result: StepResult, credit_park: bool = False) -> str:
        if settles_lost(result):
            # Spend unknown: the whole grant stays charged, G10 authority included (G10 may have spent it).
            _call("engine:ledger_failed", self.ledger.settle_lost, si.idempotency_key)
            return "lost"
        waste = settles_as_waste(result, credit_park=credit_park)
        _call("engine:ledger_failed", self.ledger.settle, si.idempotency_key, result.usage, waste=waste)
        return "waste" if waste else "case"

    def book_waste(self, idempotency_key: str, reason: str) -> None:
        _call("engine:ledger_failed", self.ledger.book_waste, idempotency_key, reason)

    def money_allows(self, batch_id: str, case_id: str, case_limit: int, minimum: int) -> bool:
        """Whether a case held after a money stop has money for another call as booked now: the
        case's own money under its limit and the batch bound both hold at least `minimum`. Read-only."""
        case = _call("engine:ledger_failed", self.ledger.case_balance, batch_id, case_id, case_limit)
        batch = _call("engine:ledger_failed", self.ledger.balance, batch_id)
        return case["remaining"] >= minimum and batch["remaining"] >= minimum

    def batch_left(self, batch_id: str) -> int:
        """What the batch bound has left, holds and spend taken out (as Ledger.reserve counts it). Read-only."""
        return _call("engine:ledger_failed", self.ledger.balance, batch_id)["remaining"]

    def call_hold(self, si: StepInput) -> int:
        """Micro-USD one request of this step's dearest gated model holds before it is forwarded
        (runtime.largest_call_hold), 0 when nothing is gated. Read-only."""
        from durable.runtime import largest_call_hold
        key = _call("engine:keys_failed", self.keys.scope_key, si.batch_id)
        blob = _call("engine:store_failed", self.store.get_sealed, si.batch_id, si.inputs)
        plaintext = _call("engine:sealer_failed", self.sealer.open, key, si.inputs, blob)
        return largest_call_hold(plaintext, (si.roles or {}).values(), si.step.kind.value) or 0

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

class _Presence:
    """Whether one attempt's worker is gone. A poll the worker answers is proof of life and needs no inventory
    read. Otherwise the pool is asked, and the worker is gone only after policy.LOST_MISSES misses in a row,
    spanning policy.LOST_WINDOW_S, with no answer since the first miss. A single `boat list` that missed a live
    box is not proof (cb5e26 11-19 and 11-20, 1108c 11-20: the box was live and the next lookup found it)."""

    def __init__(self, executor: Executor, lease: WorkerLease, misses: int = LOST_MISSES, window_s=None):
        self._executor, self._lease = executor, lease
        self._limit = misses
        self._window = executor.lost_window_s if window_s is None else window_s
        self.first_miss, self.misses, self.lost = None, 0, False

    def gone(self, answered: bool) -> bool:
        if answered or self._executor._alive(self._lease):
            self.first_miss, self.misses, self.lost = None, 0, False
            return False
        now = self._executor.clock()
        if self.first_miss is None:
            self.first_miss = now
        self.misses += 1
        self.lost = self.misses >= self._limit and now - self.first_miss >= self._window
        return self.lost


class _Bound:
    def __init__(self, executor: Executor, started_at: float, lease: WorkerLease, stopped=lambda: False):
        self._executor, self._started_at, self._lease, self._stopped = executor, started_at, lease, stopped

    def run(self, si: StepInput) -> StepResult:
        return self._executor.run(si, started_at=self._started_at, lease=self._lease, stopped=self._stopped)
