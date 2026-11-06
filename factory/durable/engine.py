"""The durable engine: one batch workflow, one workflow per case, one per attempt, on DBOS 3.4.0.

WP1, docs/designs/durable-execution-wp1.md and docs/designs/durable-execution.md ("The case,
step by step", "What happens after each outcome", "Engine rules").

DBOS records every workflow argument, step result and exception. Everything recorded here is
a contract record (ids, digests, reason codes, numbers) or a small dict of those.

Engine rules, as built:
1. Workflows are deterministic: the clock only through `now_step`, releases through
   DBOS.get_event, messages through DBOS.recv, and no iteration over sets.
2. Waits are DBOS.sleep(wait_seconds(retry_at, now)) or a recv with a positive timeout.
3. Engine.start_batch attaches to an existing batch ID; it never starts one twice.
4. An attempt's workflow ID is its idempotency key case/seq/step/attempt.
5. The executor runs only through guarded_run (attempt_step).
6. Queues are registered right after launch(), before any batch is started or attached.
7. application_version is pinned; workflows never dead-letter on restarts.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
import time
from types import SimpleNamespace
from typing import Any, Mapping, Optional

from dbos import DBOS, SetWorkflowID

from durable.contract import (ArtifactKind, BatchSpec, BenchRelease, BoundRaised, ContractError, FounderAction,
                              FounderReply, Grant, LimitedBy, Outcome, PlumbingRelease, Ref, Step, StepInput, StepKind,
                              StepResult, Topic, WorkerLease, assert_no_conductor, batch_spec_from_record,
                              guarded_run, step_input_from_record, step_result_from_record, to_record,
                              wait_seconds)
from durable.classify import WORKER_POOL_REASONS
from durable.executor import Executor, SeamError
from durable.policy import (DEADLINE_REASON, POOL_WAIT_CEILING_S, ENDS_LINE_OF_WORK, Action, Counters, deadline_s, decide, decide_diagnosis, decide_grant,
                            draws_case_money, is_batch_deadline_stop, is_operational_wait, is_money_stop, is_pause,
                            progressed, request_usd_micros, starts_replacement)
from durable.report import verified_seal

APP_NAME = "unbug-factory-engine"
APP_VERSION = "factory-engine-1"   # pinned for the life of the database: DBOS recovers only matching versions
CASE_EVENT = "case_event"          # internal topic: case -> batch
WAKE = "wake"                      # internal topic: batch -> a case waiting on the bound
PENDING_ADMISSION = "pending_admission"  # test-only V2 pending-workflow control
PROBE_CONTROL = "probe_control"          # batch -> a V2 admission probe
SEAM = dict(retries_allowed=True, interval_seconds=1.0, max_attempts=12, backoff_rate=2.0)
TERMINAL = ("sealed", "retired", "held", "stopped_admission", "engine_error")


@dataclass(frozen=True)
class Timing:
    """How long the engine's waits poll. None of these changes a decision."""
    batch_poll_s: float = 60.0      # batch: recheck operator topics and failed cases
    wake_poll_s: float = 300.0      # a case waiting on the bound rechecks this often without a wake
    founder_poll_s: float = 3600.0  # an escalated case's recv loop
    queue_poll_s: float = 1.0       # DBOS queue polling interval
    listener_poll_s: float = 1.0    # DBOS notification listener polling interval
    pause_retry_s: float = 900.0    # after an operator pause (infra:paused) or a failed worker create, wait this
                                    # long before the retry
                                    # (WP4's flat backoff); a pause never counts as an infra retry
    credential_retry_s: float = 900.0  # retry a visible credential configuration wait
    pool_wait_ceiling_s: float = POOL_WAIT_CEILING_S  # total worker-create waiting per seq before it counts


class _Runtime:
    executor: Optional[Executor] = None
    timing: Timing = Timing()


_RT = _Runtime()


def admit_queue(batch_id: str) -> str:
    return f"admit-{batch_id}"


def steps_queue(batch_id: str) -> str:
    return f"steps-{batch_id}"


def decision_queue(batch_id: str) -> str:
    return f"decision-{batch_id}"


def case_id_for(batch_id: str, n: int) -> str:
    return f"case-{batch_id[2:]}-{n}"


def _message_key(batch_id: str, operation: str, role: str, kind: str, phase: str, destination: str) -> str:
    parts = (batch_id, operation, role, kind, phase, destination)
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def check_instance(dbos: Any) -> None:
    """After construction and before launch: the instance must not talk to Conductor or run in
    DBOS Cloud mode (assert_no_conductor checks the environment and config before)."""
    from dbos._utils import GlobalParams
    if getattr(dbos, "conductor_key", None) is not None or getattr(dbos, "conductor_url", None) is not None:
        raise ContractError("the constructed engine is configured for Conductor")
    if GlobalParams.dbos_cloud:
        raise ContractError("the engine must not run in DBOS Cloud mode")


# ---- steps ---------------------------------------------------------------------------------------

def _ex() -> Executor:
    if _RT.executor is None:
        raise SeamError("engine:not_configured")
    return _RT.executor


@DBOS.step()
def now_step() -> float:
    return time.time()


@DBOS.step(**SEAM)
def open_ledger_step(batch_id: str, bound: int) -> None:
    _ex().open_batch(batch_id, bound)


@DBOS.step(**SEAM)
def raise_bound_step(batch_id: str, bound: int) -> None:
    _ex().raise_bound(batch_id, bound)


@DBOS.step(**SEAM)
def seal_history_step(case_id: str, history: list) -> dict:
    return to_record(_ex().seal_history(case_id, history))


@DBOS.step(**SEAM)
def lease_step(case_id: str, plumbing_version: str, bench_version: str) -> dict:
    try:
        return {"worker_id": _ex().lease_for(case_id, plumbing_version, bench_version).worker_id, "reason": None}
    except SeamError as error:
        return {"worker_id": None, "reason": error.code}


@DBOS.step(**SEAM)
def release_step(case_id: str, worker_id: str) -> None:
    _ex().release(WorkerLease(worker_id, case_id))


@DBOS.step(**SEAM)
def lease_alive_step(case_id: str, worker_id: str) -> bool:
    return _ex().lease_alive(WorkerLease(worker_id, case_id))


@DBOS.step(**SEAM)
def reserve_step(si: dict, request: int, case_limit: int, draws: bool) -> dict:
    return to_record(_ex().reserve(step_input_from_record(si), request=request, case_limit=case_limit,
                                   draws_case_money=draws))


@DBOS.step(**SEAM)
def release_unstarted_step(si: dict) -> None:
    _ex().release_unstarted(step_input_from_record(si))


@DBOS.step(**SEAM)
def cancel_step(si: dict, started_at: float, worker_id: str) -> bool:
    return _ex().cancel(step_input_from_record(si), started_at, worker_id)


@DBOS.step()
def attempt_step(si: dict, started_at: float, worker_id: str) -> dict:
    """The attempt itself. Rerun after a crash, it attaches to the same worker attempt: the
    worker refuses a second start of the same key, and poll returns the first result."""
    step_input = step_input_from_record(si)
    # A recorded lease may refer to an attempt that ran before a crash. A missing
    # runtime cannot prove it stopped, so keep its grant until a runtime can inspect it.
    while _RT.executor is None:
        time.sleep(30)
    lease = WorkerLease(worker_id, step_input.case_id)
    try:
        result = guarded_run(_RT.executor.bound(started_at, lease), step_input)
    except Exception:
        result = StepResult(Outcome.INFRA_ERROR, "engine:executor_raised")
    if result.reason in ("engine:executor_raised", "engine:executor_bad_result"):
        # The guard cannot know whether dispatch happened before an exception or
        # invalid response. Reconcile the original lease before releasing its grant.
        reconcile = SimpleNamespace(run=lambda si: _RT.executor.reconcile(si, lease))
        while True:
            result = guarded_run(reconcile, step_input)
            if result.reason != "engine:executor_raised":
                break
            # The guard keeps no exception text. An unconfirmed worker remains
            # quarantined on the same grant.
            time.sleep(30)
    return to_record(result)


@DBOS.step(**SEAM)
def settle_step(si: dict, result: dict) -> str:
    return _ex().settle(step_input_from_record(si), step_result_from_record(result))


@DBOS.step()
def latest_registry_step(batch_id: str, initial: dict) -> dict:
    """The newest successful ADMIT output of this batch. ADMIT attempts run one at a time on
    the batch's admit queue (recovery re-enqueues a pending one onto the same queue), so the
    newest finished one is the registry every later ADMIT must build on."""
    best = None
    for w in DBOS.list_workflows(name=attempt_workflow.__qualname__, status="SUCCESS",
                                 workflow_id_prefix=f"case-{batch_id[2:]}-", queue_name=admit_queue(batch_id)):
        out = w.output if isinstance(w.output, dict) else None
        if not out or not out.get("started"):
            continue
        reg = out["result"].get("registry")
        if reg is not None and (best is None or (w.updated_at or 0) > best[0]):
            best = (w.updated_at or 0, reg)
    return initial if best is None else best[1]


@DBOS.step()
def failed_cases_step(case_ids: list) -> list:
    """Cases whose workflow ended without reporting (an exhausted seam step): done, as engine_error."""
    if not case_ids:
        return []
    bad = DBOS.list_workflows(workflow_ids=list(case_ids),
                              status=["ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"], load_output=False,
                              load_input=False)
    return sorted(w.workflow_id for w in bad)


# ---- the attempt workflow ------------------------------------------------------------------------

@DBOS.workflow(max_recovery_attempts=None)
def attempt_workflow(job: dict) -> dict:
    """One attempt, run while holding one queue slot: read the registry (ADMIT), reserve, check
    the minimum grant, cancel attempt n-1, run, settle."""
    si = step_input_from_record(job["input"])
    # Events are read only once this attempt has both of its queue slots. A release
    # received while it was queued must apply to the step that starts afterwards.
    plumbing = DBOS.get_event(si.batch_id, "plumbing", timeout_seconds=5.0) or si.plumbing_version
    bench = si.bench_version
    if si.step.kind in (StepKind.GATES, StepKind.SEAL):
        bench = DBOS.get_event(si.batch_id, "bench", timeout_seconds=5.0) or bench
    if si.step.kind is StepKind.SEAL and (plumbing, bench) != (si.plumbing_version, si.bench_version):
        return {"started": False, "action": Action.RERUN_GATES.value}
    si = replace(si, plumbing_version=plumbing, bench_version=bench)
    if si.step.kind is StepKind.ADMIT:
        si = replace(si, registry=Ref(**latest_registry_step(si.batch_id, job["initial_registry"])))
    grant = Grant(**reserve_step(to_record(si), job["request"], job["case_limit"], job["draws"]))
    # A case waiting for a slot or funding has not yet begun admission. Record
    # the cutoff after reserve (which may block), before provisioning a worker.
    # Retries of an already dispatched ADMIT continue, including provider waits.
    if (si.step.kind is StepKind.ADMIT and job.get("admission_deadline") is not None
            and DBOS.patch("admission_deadline_gate") and now_step() >= job["admission_deadline"]):
        release_unstarted_step(to_record(si))
        DBOS.send(si.batch_id, {"kind": "settled"}, topic=CASE_EVENT)
        return {"started": False, "action": Action.STOP_ADMISSION.value, "reason": "infra:deadline"}
    early = decide_grant(si.step, grant)
    if early is not None:
        release_unstarted_step(to_record(si))
        DBOS.send(si.batch_id, {"kind": "settled"}, topic=CASE_EVENT)
        return {"started": False, "grant": to_record(grant), "action": early.value}
    si = replace(si, money_ceiling_usd_micros=grant.amount_usd_micros)
    if job["prev"] is not None:
        cancel_step(job["prev"]["input"], job["prev"]["started_at"], job["prev"]["worker_id"])
    lease = lease_step(si.case_id, si.plumbing_version, si.bench_version)
    worker_id = lease["worker_id"]
    if worker_id is None:
        # No worker attempt can precede this recorded lease step. Free its grant,
        # then let the case apply the normal infra retry policy to the safe reason.
        release_unstarted_step(to_record(si))
        DBOS.send(si.batch_id, {"kind": "settled"}, topic=CASE_EVENT)
        return {"started": True, "grant": to_record(grant), "input": to_record(si),
                "result": to_record(StepResult(Outcome.INFRA_ERROR, lease["reason"])),
                "started_at": None, "worker_id": None}
    started_at = now_step()
    result = attempt_step(to_record(si), started_at, worker_id)
    settle_step(to_record(si), result)
    DBOS.send(si.batch_id, {"kind": "settled"}, topic=CASE_EVENT)   # waiting cases wake on every settle
    return {"started": True, "grant": to_record(grant), "input": to_record(si), "result": result,
            "started_at": started_at, "worker_id": worker_id}


@DBOS.workflow(max_recovery_attempts=None)
def prepared_attempt_workflow(job: dict) -> dict:
    """Dispatch a previously funded, prepared attempt while holding a model slot.

    Preparation and the ledger hold happen outside this queue. A stale release or
    dead worker returns the same unspent grant to the caller for re-preparation.
    """
    si = step_input_from_record(job["input"])
    grant = Grant(**job["grant"])
    lease = WorkerLease(**job["lease"])
    if (lease.case_id != si.case_id or grant.amount_usd_micros == 0
            or decide_grant(si.step, grant) is not None):
        raise ContractError("invalid prepared attempt")
    plumbing = DBOS.get_event(si.batch_id, "plumbing", timeout_seconds=5.0) or si.plumbing_version
    bench = si.bench_version
    if si.step.kind in (StepKind.GATES, StepKind.SEAL):
        bench = DBOS.get_event(si.batch_id, "bench", timeout_seconds=5.0) or bench
    if si.step.kind is StepKind.SEAL and (plumbing, bench) != (si.plumbing_version, si.bench_version):
        return {"started": False, "action": Action.RERUN_GATES.value}
    if ((plumbing, bench) != (job["lease_plumbing"], job["lease_bench"])
            or not lease_alive_step(si.case_id, lease.worker_id)):
        return {"started": False, "action": "stale_preparation"}
    si = replace(si, plumbing_version=plumbing, bench_version=bench,
                 money_ceiling_usd_micros=grant.amount_usd_micros)
    if si.step.kind is StepKind.ADMIT:
        registry = DBOS.get_event(si.batch_id, "registry", timeout_seconds=5.0)
        if registry is None:
            raise ContractError("missing admission registry")
        si = replace(si, registry=Ref(**registry))
    if job["prev"] is not None:
        cancel_step(job["prev"]["input"], job["prev"]["started_at"], job["prev"]["worker_id"])
    started_at = now_step()
    DBOS.set_event("attempt_context", {"input": to_record(si), "grant": to_record(grant),
                                       "lease": to_record(lease), "key": si.idempotency_key})
    result = attempt_step(to_record(si), started_at, lease.worker_id)
    settle_step(to_record(si), result)
    key = _message_key(si.batch_id, si.idempotency_key, "attempt", "settled", "result", si.batch_id)
    DBOS.send(si.batch_id, {"kind": "settled", "case": si.case_id}, topic=CASE_EVENT, idempotency_key=key)
    return {"started": True, "grant": to_record(grant), "input": to_record(si), "result": result,
            "started_at": started_at, "worker_id": lease.worker_id}


@DBOS.workflow(max_recovery_attempts=None)
def slot_workflow(job: dict) -> dict:
    """Every attempt holds a global slot; ADMIT additionally holds the serial queue."""
    si = step_input_from_record(job["input"])
    if si.step.kind is StepKind.ADMIT:
        queue = DBOS.retrieve_queue(admit_queue(si.batch_id))
        with SetWorkflowID(f"{si.idempotency_key}/admit"):
            return queue.enqueue(attempt_workflow, job).get_result()
    return attempt_workflow(job)


def _probe_reply(operation: str, phase: str) -> dict:
    while True:
        msg = DBOS.recv(PROBE_CONTROL, timeout_seconds=_RT.timing.batch_poll_s)
        if isinstance(msg, dict) and msg.get("operation") == operation and msg.get("phase") == phase:
            return msg


@DBOS.workflow(max_recovery_attempts=None)
def admission_probe_workflow(job: dict) -> dict:
    """A decision-queue probe; it never holds a model slot or starts a worker."""
    si = step_input_from_record(job["input"])
    operation = job["operation"]
    open_key = _message_key(si.batch_id, operation, "probe", "open", "request", si.batch_id)
    DBOS.send(si.batch_id, {"kind": "probe_open", "case": si.case_id, "operation": operation},
              topic=CASE_EVENT, idempotency_key=open_key)
    reply = _probe_reply(operation, "authorization")
    if reply.get("authorized") is not True:
        result = {"kind": "probe_result", "case": si.case_id, "operation": operation, "status": "denied"}
    else:
        DBOS.set_event("reserve_intent", {"input": job["input"], "request": job["request"],
                                          "case_limit": job["case_limit"], "draws": True})
        grant = Grant(**reserve_step(job["input"], job["request"], job["case_limit"], True))
        now = now_step()
        early = decide_grant(si.step, grant)
        if now >= job["deadline"]:
            status = "expired"
        elif early is Action.WAIT_FOR_BOUND:
            status = "waiting"
        elif early is not None or grant.amount_usd_micros == 0:
            status = "not_admitted"
        else:
            status = "admitted"
        # Record the clock-based decision before any zero settlement. A replay after
        # a clock change must never deliver a previously settled key as admitted.
        DBOS.set_event("probe_decision", {"status": status, "grant": to_record(grant), "now": now})
        if status != "admitted":
            release_unstarted_step(job["input"])
        result = {"kind": "probe_result", "case": si.case_id, "operation": operation, "status": status,
                  "attempt": si.attempt, "key": si.idempotency_key, "grant": to_record(grant)}
    result_key = _message_key(si.batch_id, operation, "probe", "result", "report", si.batch_id)
    DBOS.send(si.batch_id, result, topic=CASE_EVENT, idempotency_key=result_key)
    acknowledgement = _probe_reply(operation, "result")
    if acknowledgement.get("cancel") is True and result["status"] == "admitted":
        # STOP or target won before the batch accepted this grant. Only this holder
        # releases it; the decision fence stays closed until the batch sees that fact.
        release_unstarted_step(job["input"])
        DBOS.set_event("cancel_settled", {"key": si.idempotency_key})
        cancel_key = _message_key(si.batch_id, operation, "probe", "cancel", "settled", si.batch_id)
        DBOS.send(si.batch_id, {"kind": "probe_cancelled", "case": si.case_id, "operation": operation},
                  topic=CASE_EVENT, idempotency_key=cancel_key)
        _probe_reply(operation, "cancelled")
    return result


@DBOS.workflow(max_recovery_attempts=None)
def raise_bound_workflow(job: dict) -> None:
    """Apply a bound increase away from the batch actor's message loop."""
    raise_bound_step(job["batch_id"], job["bound"])
    key = _message_key(job["batch_id"], job["operation"], "bound", "raised", "result", job["batch_id"])
    DBOS.send(job["batch_id"], {"kind": "bound_raised", "operation": job["operation"]},
              topic=CASE_EVENT, idempotency_key=key)


# ---- the case workflow ---------------------------------------------------------------------------

class _Stop(Exception):
    """Internal control flow: the case reached a terminal status."""

    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


class _Case:
    def __init__(self, spec: BatchSpec, case_id: str, initial_registry: dict, replacement_of: Optional[str]):
        self.spec, self.case_id, self.replacement_of = spec, case_id, replacement_of
        self.batch_id = spec.batch_id
        self.initial_registry = initial_registry
        self.inputs: Ref = spec.inputs
        self.seq = 0
        self.snapshot: Optional[Ref] = None
        self.bench = spec.bench_version
        self.writer_rounds_used = 0
        self.extensions_used = 0
        self.diagnoses_used = 0
        self.in_extension = False
        self.round = 1
        self.evidence: list = []
        self.history: list = []
        self.passed: tuple = ()
        self.failed_gate: Optional[str] = None
        self.ext_before: Optional[tuple] = None
        self.ext_after: tuple = ()
        self.gates_versions: Optional[tuple] = None
        self.line_stopped = False
        self.worker_id: Optional[str] = None
        self.status = "running"
        self.stage = "admit"
        self.last_reason: Optional[str] = None
        self.verdict: Optional[str] = None
        self.sealed: Optional[dict] = None

    # -- records and messages --

    def counters(self, infra=0, limits=0, free=0, late=0) -> Counters:
        return Counters(step_infra_errors=infra, step_spent_limits=limits, step_free_limits=free,
                        step_deadline_stops=late,
                        writer_rounds_used=self.writer_rounds_used,
                        extensions_used=self.extensions_used, diagnoses_used=self.diagnoses_used,
                        in_extension=self.in_extension)

    def card(self) -> None:
        DBOS.set_event("card", {
            "case_id": self.case_id, "replacement_of": self.replacement_of, "status": self.status,
            "stage": self.stage, "reason": self.last_reason, "passed": list(self.passed),
            "failed_gate": self.failed_gate, "writer_rounds": self.writer_rounds_used,
            "extensions": self.extensions_used, "diagnoses": self.diagnoses_used, "verdict": self.verdict,
            "hard": None if self.sealed is None else self.sealed["hard"]})

    def tell(self, kind: str, *, _idempotency_key: Optional[str] = None, **fields) -> None:
        DBOS.send(self.batch_id, {"kind": kind, "case": self.case_id, **fields}, topic=CASE_EVENT,
                  idempotency_key=_idempotency_key)

    def stop_line(self, action: Action) -> None:
        if action in ENDS_LINE_OF_WORK and not self.line_stopped:
            self.line_stopped = True
            self.tell("line_stopped", action=action.value)

    def finish(self, status: str) -> None:
        self.release_worker()
        if status == "sealed":
            DBOS.set_event("seal_cleanup_complete", True)
        self.status = status
        self.card()
        raise _Stop(status)

    def release_worker(self) -> None:
        if self.worker_id is not None:
            release_step(self.case_id, self.worker_id)
            self.worker_id = None

    def current(self, name: str) -> str:
        value = DBOS.get_event(self.batch_id, name, timeout_seconds=5.0)
        return value if isinstance(value, str) else getattr(self.spec, f"{name}_version")

    # -- one seq, through all its attempts --

    def run_seq(self, step: Step, *, feedback=None, ruling=None, evidence=(), versions=None):
        """Attempts of one seq until it advances, gives up or parks. Returns (action, result);
        action is None for a DIAGNOSIS verdict."""
        self.seq += 1
        self.stage = step.name
        attempt, infra, limits, free, late, prev = 0, 0, 0, 0, 0, None
        pool_since = None
        requested_minimum = 0
        admit = step.kind is StepKind.ADMIT
        admission_started = False
        while True:
            attempt += 1
            pv, bv = versions if versions is not None else (self.current("plumbing"), self.bench)
            si = StepInput(self.batch_id, self.case_id, self.seq, step, attempt, pv, bv,
                           inputs=self.spec.inputs if admit else self.inputs,
                           snapshot=None if admit else self.snapshot, deadline_s=deadline_s(step, self.spec),
                           money_ceiling_usd_micros=0, feedback=feedback,
                           registry=Ref(**self.initial_registry) if admit else None, ruling=ruling,
                           evidence=tuple(evidence))
            counters = self.counters(infra, limits, free, late)
            job = {"input": to_record(si), "initial_registry": self.initial_registry,
                   "request": max(requested_minimum, request_usd_micros(step, counters, self.spec)),
                   "case_limit": self.spec.case_money_usd_micros, "draws": draws_case_money(step, counters),
                   "prev": prev}
            if admit and not admission_started:
                job["admission_deadline"] = self.spec.deadline_epoch
            queue = DBOS.retrieve_queue(steps_queue(self.batch_id))
            with SetWorkflowID(si.idempotency_key):
                out = queue.enqueue(slot_workflow, job).get_result()
            if not out["started"]:
                action = Action(out["action"])
                if action is Action.RERUN_GATES:
                    return action, None
                self.history.append({"seq": self.seq, "step": step.name, "attempt": attempt,
                                     "outcome": "not_started", "action": action.value})
                if action is Action.WAIT_FOR_BOUND:
                    self.wait_for_bound()
                    continue
                self.last_reason = out.get("reason", "engine:below_minimum_grant")
                return action, None
            result = step_result_from_record(out["result"])
            grant = Grant(**out["grant"])
            if out["worker_id"] is not None:
                admission_started = True
                prev = {"input": out["input"], "started_at": out["started_at"], "worker_id": out["worker_id"]}
                self.worker_id = out["worker_id"]
            if step.kind is StepKind.GATES:
                self.bench = out["input"]["bench_version"]
                self.gates_versions = (out["input"]["plumbing_version"], self.bench)
            self.absorb(step, attempt, result)
            # A batch-deadline stop after deadline_epoch (or an operator pause) is never counted as
            # an infra error: the batch deadline stops new cases and extensions, not this step.
            now = now_step() if result.reason == DEADLINE_REASON else None
            # A worker create outage waits like a pause and spends no allowance, up to a total ceiling
            # measured with recorded clock reads: Boat never proves that a failed create left no
            # sandbox, so the pool settles it by time (workers.py).
            pool_wait = (result.outcome is Outcome.INFRA_ERROR and result.reason in WORKER_POOL_REASONS
                         and DBOS.patch("worker_pool_retry_wait"))
            if pool_wait:
                pool_now = now_step()
                pool_since = pool_now if pool_since is None else pool_since
                pool_wait = pool_now - pool_since < _RT.timing.pool_wait_ceiling_s
            else:
                pool_since = None
            late_stop = is_batch_deadline_stop(result, self.spec, now)
            if late_stop:
                late += 1
            elif result.outcome is Outcome.INFRA_ERROR and not (is_pause(result) or is_operational_wait(result) or pool_wait):
                infra += 1
            if result.outcome is Outcome.PROVIDER_LIMIT:
                if result.usage.paid_usd_micros > 0:
                    limits += 1
                else:
                    free += 1
            if step.kind is StepKind.DIAGNOSIS and result.outcome is Outcome.OK:
                return None, result
            action = decide(step, result, self.counters(infra, limits, free, late), self.spec, grant=grant, now=now)
            if pool_wait and admit and not admission_started and pool_now >= self.spec.deadline_epoch:
                action = Action.STOP_ADMISSION   # the batch deadline stops new cases
            if (action is Action.RETRY and is_money_stop(result)
                    and grant.limited_by is LimitedBy.NOTHING and not job["draws"]):
                # A later call may not fit even after earlier calls spent money.
                # Grow only until the ledger applies the batch bound.
                requested_minimum = min(2**63 - 1, max(job["request"] * 2, 1))
            if is_operational_wait(result):
                self.status = ("waiting_for_credentials" if result.reason in (
                    "router:credential_expiring", "infra:credentials_unavailable") else "waiting_for_router")
                self.card()
                self.release_worker()
                DBOS.sleep(max(0.001, _RT.timing.credential_retry_s))
                self.status = "running"
                self.last_reason = None
                self.card()
                continue
            if action is Action.RETRY and (late_stop or is_pause(result) or pool_wait):
                # Wait before the retry, so a stop that repeats does not spin.
                if _RT.timing.pause_retry_s > self.spec.release_worker_after_sleep_s and self.worker_id is not None:
                    release_step(self.case_id, self.worker_id)
                    self.worker_id = None
                DBOS.sleep(_RT.timing.pause_retry_s)
                continue
            if action is Action.RETRY:
                continue
            if action is Action.SLEEP:
                seconds = wait_seconds(result.retry_at, now_step())
                # A sequence of short waits must not monopolize worker capacity.
                self.release_worker()
                DBOS.sleep(seconds)
                continue
            if action is Action.WAIT_FOR_BOUND:
                self.wait_for_bound()
                continue
            return action, result

    def absorb(self, step: Step, attempt: int, r: StepResult) -> None:
        self.history.append({"seq": self.seq, "step": step.name, "attempt": attempt, "outcome": r.outcome.value,
                             "reason": r.reason, "paid_usd_micros": r.usage.paid_usd_micros})
        self.last_reason = r.reason
        if r.snapshot is not None:
            self.snapshot = r.snapshot   # a retry restores the latest snapshot, OK or not
        for ref in (r.receipt, r.diagnostic, r.report):
            if ref is not None and ref not in self.evidence:
                self.evidence.append(ref)
        if step.kind is StepKind.GATES:
            self.passed = r.passed
            self.failed_gate = r.gate if r.outcome is Outcome.GATE_FAILED else None

    def wait_for_bound(self) -> None:
        self.release_worker()
        self.status = "waiting_for_bound"
        self.card()
        self.tell("waiting")
        DBOS.recv(WAKE, timeout_seconds=_RT.timing.wake_poll_s)
        self.status = "running"

    # -- the case --

    def run(self) -> None:
        action, r = self.run_seq(Step(StepKind.ADMIT))
        if action is Action.STOP_ADMISSION:
            self.tell("stop_admission")
            self.finish("stopped_admission")
        assert action is Action.ADVANCE, action
        self.card()
        phase, feedback, ruling = "writer", None, None
        while True:
            if phase == "writer":
                action, r = self.run_seq(Step(StepKind.WRITER, self.round), feedback=feedback)
                feedback = None
                if action is Action.ADVANCE:
                    if not self.in_extension:
                        self.writer_rounds_used += 1
                    phase = "stress"
                else:
                    phase, feedback = self.stopped(action)
            elif phase == "stress":
                step = Step(StepKind.STRESS, self.round)
                action, r = self.run_seq(step, ruling=ruling)
                ruling = None
                if action is Action.ADVANCE:
                    phase = "gates"
                elif action is Action.REPAIR:
                    self.round += 1
                    phase, feedback = "writer", r.feedback
                elif action is Action.ESCALATE:
                    ruling = self.escalate()
                else:
                    phase, feedback = self.stopped(action)
            elif phase == "gates":
                self.bench = self.current("bench")         # a case adopts a bench release at its next GATES
                versions = (self.current("plumbing"), self.bench)
                in_ext = self.in_extension
                action, r = self.run_seq(Step(StepKind.GATES, self.round), ruling=ruling, versions=versions)
                ruling = None
                if action is Action.ESCALATE:
                    ruling = self.escalate()                # the rerun is still the extension's GATES
                    continue
                if in_ext and r is not None:
                    self.ext_after = r.passed               # the extension ends at its GATES result
                self.in_extension = False
                if action is Action.ADVANCE:
                    phase = "seal"
                elif action is Action.REPAIR:
                    self.round += 1
                    phase, feedback = "writer", r.feedback
                else:
                    phase, feedback = self.stopped(action)
            elif phase == "seal":
                current = (self.current("plumbing"), self.current("bench"))
                if current != self.gates_versions:
                    phase = "gates"                          # SEAL runs only under the passing GATES versions
                    continue
                action, r = self.run_seq(Step(StepKind.SEAL), versions=self.gates_versions)
                if action is Action.RERUN_GATES:
                    phase = "gates"
                    continue
                if action is Action.ADVANCE:
                    self.sealed = {"archive": to_record(r.archive), "hard": r.hard}
                    # The attempt has authenticated this archive. Preserve that fact
                    # before release so a cleanup failure cannot erase a valid seal.
                    DBOS.set_event("verified_seal", self.sealed)
                    self.stage = "sealed"
                    self.finish("sealed")
                phase, feedback = self.stopped(action)
            self.card()

    def stopped(self, action: Action):
        """A non-advancing action: diagnose, retire, hold. Returns the next (phase, feedback)."""
        self.stop_line(action)
        if action is Action.RETIRE:
            self.finish("retired")
        if action is not Action.DIAGNOSE:
            raise AssertionError(action)
        return self.diagnose()

    def diagnose(self):
        self.diagnoses_used += 1
        self.in_extension = False
        history = seal_history_step(self.case_id, self.history)
        evidence = (*self.evidence, Ref(**history))
        self.card()
        action, r = self.run_seq(Step(StepKind.DIAGNOSIS), evidence=evidence)
        if action is not None:                              # a diagnosis is never diagnosed
            self.stop_line(Action.RETIRE)
            self.finish("retired")
        self.verdict = r.verdict.value
        prog = progressed(self.ext_before, self.ext_after) if self.ext_before is not None else False
        decision = decide_diagnosis(r.verdict, progressed=prog, counters=self.counters(), spec=self.spec)
        if decision is Action.EXTEND and now_step() >= self.spec.deadline_epoch:
            decision = Action.RETIRE                        # no extension starts after the deadline
        self.stop_line(decision)
        if decision is Action.HOLD:
            self.finish("held")
        if decision is Action.RETIRE:
            self.finish("retired")
        assert decision is Action.EXTEND, decision
        self.extensions_used += 1
        self.in_extension = True
        self.ext_before, self.ext_after = self.passed, ()
        self.round += 1
        return "writer", r.feedback

    def escalate(self) -> Ref:
        """Park until a FOUNDER_REPLY. CONTINUE returns the ruling for the rerun; RETIRE retires."""
        self.stop_line(Action.ESCALATE)
        self.release_worker()
        self.status = "escalated"
        self.card()
        while True:
            msg = DBOS.recv(Topic.FOUNDER_REPLY.value, timeout_seconds=_RT.timing.founder_poll_s)
            if msg is None:
                continue
            try:
                reply = FounderReply(action=msg["action"], ruling=None if msg.get("ruling") is None
                                     else Ref(**msg["ruling"]))
            except (ContractError, KeyError, TypeError):
                continue
            if reply.action is FounderAction.RETIRE:
                self.finish("retired")
            self.status = "running"
            return reply.ruling


@DBOS.workflow(max_recovery_attempts=None)
def case_workflow(job: dict) -> dict:
    spec = batch_spec_from_record(job["spec"])
    case = _Case(spec, job["case_id"], job["initial_registry"], job.get("replacement_of"))
    queue_v2 = job.get("queue_v2", False)
    if type(queue_v2) is not bool:
        raise ContractError("bad internal admission switch")
    if queue_v2:
        # The first V2 increment cannot admit work. Later increments replace this
        # wait with the recorded grant handoff and preparation workflow.
        case.status = "pending_admission"
        case.card()
        prepared_key = None
        while True:
            msg = DBOS.recv(PENDING_ADMISSION, timeout_seconds=_RT.timing.batch_poll_s)
            if not isinstance(msg, dict):
                continue
            if msg.get("kind") == "prepare" and prepared_key is None:
                attempt, key = msg.get("attempt"), msg.get("key")
                if (msg.get("case") != case.case_id or type(attempt) is not int or attempt < 1
                        or key != f"{case.case_id}/1/admit/{attempt}"):
                    continue
                try:
                    grant = Grant(**msg["grant"])
                except (ContractError, KeyError, TypeError, ValueError):
                    continue
                if grant.amount_usd_micros <= 0:
                    continue
                prepared_key = key
                DBOS.set_event("admission_grant", {"key": key, "attempt": attempt, "grant": to_record(grant)})
                case.status = "waiting_for_worker"
                case.card()
            elif msg.get("kind") == "not_admitted" and prepared_key is None:
                case.status = "not_admitted"
                case.card()
                key = _message_key(case.batch_id, case.case_id, "case", "done", "result", case.batch_id)
                case.tell("done", status=case.status, sealed=None, worker_released=True, _idempotency_key=key)
                return {"case_id": case.case_id, "status": case.status, "sealed": None}
    case.card()
    try:
        case.run()
    except _Stop:
        pass
    case.tell("done", status=case.status, sealed=case.sealed)
    return {"case_id": case.case_id, "status": case.status, "sealed": case.sealed}


# ---- the batch workflow --------------------------------------------------------------------------

class _Batch:
    def __init__(self, spec: BatchSpec, initial_registry: dict):
        self.spec, self.initial_registry = spec, initial_registry
        self.cases: list = []
        self.done: dict = {}
        self.sealed: list = []
        self.waiting: list = []
        self.replaced: list = []
        self.admission_stopped = False

    def admission_open(self) -> bool:
        return (not self.admission_stopped and len(self.sealed) < self.spec.target_sealed
                and now_step() < self.spec.deadline_epoch)

    def start_case(self, replacement_of: Optional[str]) -> None:
        case_id = case_id_for(self.spec.batch_id, len(self.cases) + 1)
        job = {"spec": to_record(self.spec), "case_id": case_id, "initial_registry": self.initial_registry,
               "replacement_of": replacement_of}
        with SetWorkflowID(case_id):
            DBOS.start_workflow(case_workflow, job)
        self.cases.append(case_id)
        DBOS.set_event("cases", list(self.cases))

    def wake_waiting(self) -> None:
        for case_id in self.waiting:
            DBOS.send(case_id, {"kind": "wake"}, topic=WAKE)
        self.waiting = []

    def handle(self, msg: dict) -> None:
        kind, case_id = msg.get("kind"), msg.get("case")
        if kind == "settled":
            self.wake_waiting()
        elif kind == "waiting":
            if case_id not in self.waiting and case_id not in self.done:
                self.waiting.append(case_id)
        elif kind == "stop_admission":
            self.admission_stopped = True
        elif kind == "line_stopped":
            if case_id in self.replaced:
                return
            if starts_replacement(Action(msg["action"]), replacement_started=False, cases_started=len(self.cases),
                                  spec=self.spec, admission_open=self.admission_open()):
                self.replaced.append(case_id)
                self.start_case(case_id)
        elif kind == "done":
            if case_id in self.done:
                return
            self.done[case_id] = msg["status"]
            if case_id in self.waiting:
                self.waiting.remove(case_id)
            if msg["status"] == "sealed":
                self.sealed.append({"case_id": case_id, **msg["sealed"]})
        elif kind == "nudge":
            self.operator()

    def operator(self) -> None:
        for topic in (Topic.PLUMBING_RELEASE, Topic.BENCH_RELEASE, Topic.BOUND_RAISED):
            while True:
                msg = DBOS.recv(topic.value, timeout_seconds=0.001)
                if msg is None:
                    break
                try:
                    if topic is Topic.PLUMBING_RELEASE:
                        DBOS.set_event("plumbing", PlumbingRelease(**msg).plumbing_version)
                    elif topic is Topic.BENCH_RELEASE:
                        DBOS.set_event("bench", BenchRelease(**msg).bench_version)
                    else:
                        self.apply_bound_raise(BoundRaised(**msg).money_bound_usd_micros)
                except (ContractError, TypeError):
                    continue

    def apply_bound_raise(self, bound: int) -> None:
        raise_bound_step(self.spec.batch_id, bound)
        self.wake_waiting()

    def has_pending_work(self) -> bool:
        return len(self.done) < len(self.cases)

    def after_initial_cases(self) -> None:
        pass

    def after_event(self) -> None:
        pass

    def after_poll(self) -> None:
        pass

    def run(self) -> dict:
        spec = self.spec
        open_ledger_step(spec.batch_id, spec.money_bound_usd_micros)
        DBOS.set_event("plumbing", spec.plumbing_version)
        DBOS.set_event("bench", spec.bench_version)
        DBOS.set_event("cases", [])
        for _ in range(min(spec.target_sealed, spec.max_cases_started)):
            if not self.admission_open():
                break
            self.start_case(None)
        self.after_initial_cases()
        while self.has_pending_work():
            msg = DBOS.recv(CASE_EVENT, timeout_seconds=_RT.timing.batch_poll_s)
            if isinstance(msg, dict):
                self.handle(msg)
                self.after_event()
                continue
            self.operator()
            pending = [c for c in self.cases if c not in self.done]
            for case_id in failed_cases_step(pending):
                seal = verified_seal(DBOS.get_event(case_id, "verified_seal", timeout_seconds=0.001))
                if seal is None:
                    self.done[case_id] = "engine_error"
                else:
                    self.done[case_id] = "sealed"
                    self.sealed.append({"case_id": case_id, **seal})
            self.after_poll()
        return {"batch_id": spec.batch_id, "sealed": self.sealed, "cases": dict(self.done)}


class _BatchV2(_Batch):
    """Disabled admission bookkeeping; no V2 grant or model dispatch exists yet."""

    def __init__(self, spec: BatchSpec, initial_registry: dict):
        super().__init__(spec, initial_registry)
        self.admitted: set = set()
        self.released: set = set()
        self.replacement_requests: dict = {}
        self.pending_cases: dict = {}
        self.probe_attempts: dict = {}
        self.probe_enabled = False
        self.active_probe: Optional[str] = None
        self.fence: Optional[str] = None
        self.probe_authorizations: dict = {}
        self.applied_probes: set = set()
        self.wake_generation = 0
        self.probe_wake_generation: dict = {}
        self.cancelling_probes: set = set()
        self.bound_sequence = 0
        self.outstanding_bound_ops: set = set()

    def start_case(self, replacement_of: Optional[str]) -> None:
        case_id = case_id_for(self.spec.batch_id, len(self.cases) + 1)
        job = {"spec": to_record(self.spec), "case_id": case_id, "initial_registry": self.initial_registry,
               "replacement_of": replacement_of, "queue_v2": True}
        with SetWorkflowID(case_id):
            DBOS.start_workflow(case_workflow, job)
        self.cases.append(case_id)
        self.pending_cases[case_id] = {"state": "eligible", "replacement_of": replacement_of, "retry_at": None}
        DBOS.set_event("cases", list(self.cases))

    def has_pending_work(self) -> bool:
        # Admitted cases must also account for their worker before the batch ends.
        return super().has_pending_work() or bool(self.admitted - self.released) or bool(self.outstanding_bound_ops)

    def apply_bound_raise(self, bound: int) -> None:
        if not self.probe_enabled:
            return super().apply_bound_raise(bound)
        self.bound_sequence += 1
        operation = f"{self.spec.batch_id}/raise-bound/{self.bound_sequence}"
        self.outstanding_bound_ops.add(operation)
        with SetWorkflowID(operation):
            DBOS.start_workflow(raise_bound_workflow, {"batch_id": self.spec.batch_id, "bound": bound,
                                                       "operation": operation})

    def wake_waiting(self) -> None:
        self.wake_generation += 1
        for pending in self.pending_cases.values():
            if pending["state"] == "waiting":
                pending["state"], pending["retry_at"] = "eligible", None
        super().wake_waiting()

    def after_initial_cases(self) -> None:
        self._schedule_probe()

    def after_event(self) -> None:
        # Traffic must not postpone bounded WAIT retries indefinitely.
        self.after_poll()

    def after_poll(self) -> None:
        if self.probe_enabled and any(p["state"] == "waiting" for p in self.pending_cases.values()):
            now = now_step()
            for pending in self.pending_cases.values():
                if pending["state"] == "waiting" and now >= pending["retry_at"]:
                    pending["state"], pending["retry_at"] = "eligible", None
        self._schedule_probe()

    def _end_pending(self, case_id: str) -> None:
        pending = self.pending_cases[case_id]
        if pending["state"] in ("closing", "admitted"):
            return
        pending["state"] = "closing"
        key = _message_key(self.spec.batch_id, case_id, "batch", "not_admitted", "result", case_id)
        DBOS.send(case_id, {"kind": "not_admitted"}, topic=PENDING_ADMISSION, idempotency_key=key)

    def _schedule_probe(self) -> None:
        if not self.probe_enabled or self.active_probe is not None or self.fence is not None:
            return
        candidates = [c for c in self.cases if c in self.pending_cases
                      and self.pending_cases[c]["state"] in ("eligible", "waiting")]
        if not candidates:
            return
        if not self.admission_open() or len(self.admitted) >= self.spec.max_cases_started:
            for case_id in candidates:
                self._end_pending(case_id)
            return
        eligible = [c for c in candidates if self.pending_cases[c]["state"] == "eligible"]
        if not eligible:
            return
        eligible.sort(key=lambda c: (self.pending_cases[c]["replacement_of"] is None, self.cases.index(c)))
        case_id = eligible[0]
        if self.spec.case_money_usd_micros == 0:
            for candidate in eligible:
                self._end_pending(candidate)
            return
        attempt = self.probe_attempts.get(case_id, 0) + 1
        self.probe_attempts[case_id] = attempt
        step = Step(StepKind.ADMIT)
        si = StepInput(self.spec.batch_id, case_id, 1, step, attempt, self.spec.plumbing_version,
                       self.spec.bench_version, self.spec.inputs, None, deadline_s(step, self.spec), 0,
                       registry=Ref(**self.initial_registry))
        operation = f"{si.idempotency_key}/probe"
        self.active_probe = operation
        self.probe_wake_generation[operation] = self.wake_generation
        self.pending_cases[case_id]["state"] = "probing"
        job = {"input": to_record(si), "operation": operation,
               "request": request_usd_micros(step, Counters(), self.spec),
               "case_limit": self.spec.case_money_usd_micros, "deadline": self.spec.deadline_epoch}
        with SetWorkflowID(operation):
            DBOS.retrieve_queue(decision_queue(self.spec.batch_id)).enqueue(admission_probe_workflow, job)

    def _reply_probe(self, operation: str, phase: str, **fields) -> None:
        key = _message_key(self.spec.batch_id, operation, "batch", "probe", phase, operation)
        DBOS.send(operation, {"operation": operation, "phase": phase, **fields}, topic=PROBE_CONTROL,
                  idempotency_key=key)

    def _open_probe(self, msg: dict) -> None:
        operation, case_id = msg.get("operation"), msg.get("case")
        if operation != self.active_probe or case_id not in self.pending_cases:
            return
        if operation not in self.probe_authorizations:
            authorized = (self.fence is None and self.pending_cases[case_id]["state"] == "probing"
                          and len(self.admitted) < self.spec.max_cases_started and self.admission_open())
            self.probe_authorizations[operation] = authorized
            if authorized:
                self.fence = operation
        self._reply_probe(operation, "authorization", authorized=self.probe_authorizations[operation])

    def _finish_probe(self, msg: dict) -> None:
        operation, case_id, status = msg.get("operation"), msg.get("case"), msg.get("status")
        if operation in self.applied_probes:
            self._reply_probe(operation, "result")
            return
        if operation in self.cancelling_probes:
            self._reply_probe(operation, "result", cancel=True)
            return
        if operation != self.active_probe or case_id not in self.pending_cases:
            return
        authorized = self.probe_authorizations.get(operation)
        if status == "denied":
            if authorized is not False:
                return
            self.pending_cases[case_id]["state"] = "eligible"
        elif status in ("admitted", "waiting", "expired", "not_admitted"):
            if authorized is not True or self.fence != operation:
                return
            attempt, key = msg.get("attempt"), msg.get("key")
            if (type(attempt) is not int or attempt < 1 or key != f"{case_id}/1/admit/{attempt}"
                    or operation != f"{key}/probe"):
                return
            try:
                grant = Grant(**msg["grant"])
            except (ContractError, KeyError, TypeError, ValueError):
                return
            if status == "admitted":
                if grant.amount_usd_micros <= 0:
                    return
                if self.admission_stopped or len(self.sealed) >= self.spec.target_sealed:
                    self.cancelling_probes.add(operation)
                    self.pending_cases[case_id]["state"] = "cancelling"
                    self._reply_probe(operation, "result", cancel=True)
                    return
                self.admitted.add(case_id)
                self.pending_cases[case_id]["state"] = "admitted"
                permit = {"kind": "prepare", "case": case_id, "attempt": attempt, "key": key,
                          "grant": to_record(grant)}
                send_key = _message_key(self.spec.batch_id, operation, "batch", "prepare", "permit", case_id)
                DBOS.send(case_id, permit, topic=PENDING_ADMISSION, idempotency_key=send_key)
            elif status == "waiting":
                if self.wake_generation > self.probe_wake_generation[operation]:
                    self.pending_cases[case_id]["state"] = "eligible"
                    self.pending_cases[case_id]["retry_at"] = None
                else:
                    self.pending_cases[case_id]["state"] = "waiting"
                    self.pending_cases[case_id]["retry_at"] = now_step() + _RT.timing.wake_poll_s
            else:
                self._end_pending(case_id)
        else:
            return
        self.applied_probes.add(operation)
        if self.fence == operation:
            self.fence = None
        self.active_probe = None
        self._reply_probe(operation, "result")

    def _cancelled_probe(self, msg: dict) -> None:
        operation, case_id = msg.get("operation"), msg.get("case")
        if operation in self.applied_probes:
            self._reply_probe(operation, "cancelled")
            return
        if (operation != self.active_probe or operation not in self.cancelling_probes
                or self.fence != operation or case_id not in self.pending_cases):
            return
        self._end_pending(case_id)
        self.cancelling_probes.remove(operation)
        self.applied_probes.add(operation)
        self.fence = None
        self.active_probe = None
        self._reply_probe(operation, "cancelled")

    def _request_replacement(self, case_id: str, value) -> None:
        if case_id not in self.admitted or case_id in self.replaced:
            return
        try:
            action = Action(value)
        except (TypeError, ValueError):
            return
        if action not in ENDS_LINE_OF_WORK:
            return
        self.replacement_requests.setdefault(case_id, action.value)
        if starts_replacement(action, replacement_started=False, cases_started=len(self.admitted),
                              spec=self.spec, admission_open=self.admission_open()):
            self.replaced.append(case_id)
            self.start_case(case_id)

    def handle(self, msg: dict) -> None:
        kind, case_id = msg.get("kind"), msg.get("case")
        if kind == "probe_open":
            self._open_probe(msg)
            return
        if kind == "probe_result":
            self._finish_probe(msg)
            return
        if kind == "probe_cancelled":
            self._cancelled_probe(msg)
            return
        if kind == "bound_raised":
            operation = msg.get("operation")
            if operation in self.outstanding_bound_ops:
                self.outstanding_bound_ops.remove(operation)
                self.wake_waiting()
            return
        if kind in ("line_stopped", "worker_released", "done") and case_id not in self.cases:
            return
        if kind == "line_stopped":
            self._request_replacement(case_id, msg.get("action"))
        elif kind == "worker_released":
            if case_id in self.admitted and case_id not in self.released:
                self.released.add(case_id)
                self.wake_waiting()
        elif kind == "done":
            status = msg.get("status")
            allowed = (("retired", "held", "stopped_admission", "engine_error")
                       if case_id in self.admitted else ("not_admitted",))
            if status not in allowed:
                return
            # Process facts even when an earlier copy already marked the case done.
            if msg.get("worker_released") is True and case_id in self.admitted and case_id not in self.released:
                self.released.add(case_id)
                self.wake_waiting()
            self._request_replacement(case_id, msg.get("replacement_action"))
            # No V2 seal can be established until the terminal-fence increment.
            super().handle(msg)
        else:
            super().handle(msg)


@DBOS.workflow(max_recovery_attempts=None)
def batch_workflow(job: dict) -> dict:
    queue_v2 = job.get("queue_v2", False)
    if type(queue_v2) is not bool:
        raise ContractError("bad internal admission switch")
    spec = batch_spec_from_record(job["spec"])
    if queue_v2:
        probe_enabled = job.get("probe_enabled", False)
        if type(probe_enabled) is not bool:
            raise ContractError("bad internal probe switch")
        batch = _BatchV2(spec, job["initial_registry"])
        batch.probe_enabled = probe_enabled
    else:
        batch = _Batch(spec, job["initial_registry"])
    return batch.run()


# ---- the engine process --------------------------------------------------------------------------

class Engine:
    """Construct, check, launch, register queues, then attach to or start batches."""

    def __init__(self, *, system_database_url: str, executor: Executor, timing: Timing = Timing(),
                 environ: Optional[Mapping[str, str]] = None, pool_size: int = 40):
        self.url, self.executor, self.timing = system_database_url, executor, timing
        self.environ = os.environ if environ is None else environ
        self.pool_size = pool_size
        self.dbos = None

    def config(self) -> dict:
        return {"name": APP_NAME, "system_database_url": self.url, "application_version": APP_VERSION,
                "sys_db_pool_size": self.pool_size,
                "notification_listener_polling_interval_sec": self.timing.listener_poll_s}

    def launch(self) -> None:
        config = self.config()
        assert_no_conductor(self.environ, config)
        self.dbos = DBOS(config=config)
        check_instance(self.dbos)
        _RT.executor, _RT.timing = self.executor, self.timing
        DBOS.launch()
        # Rule 6: register the queues of every unfinished batch before anything is started or
        # attached. Their rows persist from the first launch, so a case recovered by launch()
        # that enqueues first still lands on its concurrency-1 queue.
        for w in DBOS.list_workflows(name=batch_workflow.__qualname__, status=["PENDING", "ENQUEUED"]):
            try:
                job = w.input["args"][0]
                self.register_queues(batch_spec_from_record(job["spec"]), decision=job.get("queue_v2") is True)
            except (ContractError, AttributeError, IndexError, KeyError, TypeError):
                continue

    def register_queues(self, spec: BatchSpec, *, decision: bool = False) -> None:
        DBOS.register_queue(admit_queue(spec.batch_id), global_concurrency=1,
                            polling_interval_sec=self.timing.queue_poll_s, on_conflict="always_update")
        DBOS.register_queue(steps_queue(spec.batch_id), global_concurrency=spec.max_concurrency,
                            polling_interval_sec=self.timing.queue_poll_s, on_conflict="always_update")
        if decision:
            DBOS.register_queue(decision_queue(spec.batch_id), global_concurrency=1,
                                polling_interval_sec=self.timing.queue_poll_s, on_conflict="always_update")

    def start_batch(self, spec: BatchSpec, initial_registry: Ref):
        """Attach to the batch if it exists (rule 3); start it otherwise. initial_registry is the
        batch's first STATEMENT_REGISTRY (BatchSpec has none; contract finding 2)."""
        if not isinstance(initial_registry, Ref) or initial_registry.kind is not ArtifactKind.STATEMENT_REGISTRY:
            raise ContractError("initial_registry must be a registry Ref")
        self.register_queues(spec)
        if DBOS.get_workflow_status(spec.batch_id) is not None:
            return DBOS.retrieve_workflow(spec.batch_id)
        with SetWorkflowID(spec.batch_id):
            return DBOS.start_workflow(batch_workflow, {"spec": to_record(spec),
                                                        "initial_registry": to_record(initial_registry),
                                                        "queue_v2": False})

    def send(self, batch_id: str, topic: Topic, payload) -> None:
        """The operator messages (WP8 wraps this). FOUNDER_REPLY goes to its case; the rest to
        the batch, followed by a nudge so the batch reads them at once."""
        topic = Topic(topic)
        if topic is Topic.FOUNDER_REPLY:
            raise ContractError("a founder reply goes to its case: use reply()")
        expected = {Topic.PLUMBING_RELEASE: PlumbingRelease, Topic.BENCH_RELEASE: BenchRelease,
                    Topic.BOUND_RAISED: BoundRaised}[topic]
        if not isinstance(payload, expected):
            raise ContractError(f"{topic.value} carries a {expected.__name__}")
        DBOS.send(batch_id, to_record(payload), topic=topic.value)
        DBOS.send(batch_id, {"kind": "nudge"}, topic=CASE_EVENT)

    def reply(self, case_id: str, reply: FounderReply) -> None:
        if not isinstance(reply, FounderReply):
            raise ContractError("reply carries a FounderReply")
        DBOS.send(case_id, to_record(reply), topic=Topic.FOUNDER_REPLY.value)

    def shutdown(self) -> None:
        DBOS.destroy()
        _RT.executor = None
