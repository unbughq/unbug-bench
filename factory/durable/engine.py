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
import os
import time
from typing import Any, Mapping, Optional

from dbos import DBOS, SetWorkflowID

from durable.contract import (ArtifactKind, BatchSpec, BenchRelease, BoundRaised, ContractError, FounderAction,
                              FounderReply, Grant, Outcome, PlumbingRelease, Ref, Step, StepInput, StepKind,
                              StepResult, Topic, WorkerLease, assert_no_conductor, batch_spec_from_record,
                              guarded_run, step_input_from_record, step_result_from_record, to_record,
                              wait_seconds)
from durable.executor import Executor, SeamError
from durable.policy import (DEADLINE_REASON, ENDS_LINE_OF_WORK, Action, Counters, deadline_s, decide, decide_diagnosis, decide_grant,
                            draws_case_money, is_batch_deadline_stop, is_pause, progressed, request_usd_micros, starts_replacement)

APP_NAME = "unbug-factory-engine"
APP_VERSION = "factory-engine-1"   # pinned for the life of the database: DBOS recovers only matching versions
CASE_EVENT = "case_event"          # internal topic: case -> batch
WAKE = "wake"                      # internal topic: batch -> a case waiting on the bound
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
    pause_retry_s: float = 900.0    # after an operator pause (infra:paused), wait this long before the retry
                                    # (WP4's flat backoff); a pause never counts as an infra retry


class _Runtime:
    executor: Optional[Executor] = None
    timing: Timing = Timing()


_RT = _Runtime()


def admit_queue(batch_id: str) -> str:
    return f"admit-{batch_id}"


def steps_queue(batch_id: str) -> str:
    return f"steps-{batch_id}"


def case_id_for(batch_id: str, n: int) -> str:
    return f"case-{batch_id[2:]}-{n}"


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
def rescope_inputs_step(batch_id: str, case_id: str, inputs: dict) -> dict:
    return to_record(_ex().rescope_inputs(batch_id, case_id, Ref(**inputs)))


@DBOS.step(**SEAM)
def seal_history_step(case_id: str, history: list) -> dict:
    return to_record(_ex().seal_history(case_id, history))


@DBOS.step(**SEAM)
def lease_step(case_id: str, plumbing_version: str, bench_version: str) -> str:
    return _ex().lease_for(case_id, plumbing_version, bench_version).worker_id


@DBOS.step(**SEAM)
def release_step(case_id: str, worker_id: str) -> None:
    _ex().release(WorkerLease(worker_id, case_id))


@DBOS.step(**SEAM)
def reserve_step(si: dict, request: int, case_limit: int, draws: bool) -> dict:
    return to_record(_ex().reserve(step_input_from_record(si), request=request, case_limit=case_limit,
                                   draws_case_money=draws))


@DBOS.step(**SEAM)
def release_unstarted_step(si: dict) -> None:
    _ex().release_unstarted(step_input_from_record(si))


@DBOS.step(**SEAM)
def cancel_step(si: dict, started_at: float) -> bool:
    return _ex().cancel(step_input_from_record(si), started_at)


@DBOS.step()
def attempt_step(si: dict, started_at: float) -> dict:
    """The attempt itself. Rerun after a crash, it attaches to the same worker attempt: the
    worker refuses a second start of the same key, and poll returns the first result."""
    step_input = step_input_from_record(si)
    if _RT.executor is None:
        return to_record(StepResult(Outcome.INFRA_ERROR, "engine:executor_raised"))
    return to_record(guarded_run(_RT.executor.bound(started_at), step_input))


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
    if si.step.kind is StepKind.ADMIT:
        si = replace(si, registry=Ref(**latest_registry_step(si.batch_id, job["initial_registry"])))
    grant = Grant(**reserve_step(to_record(si), job["request"], job["case_limit"], job["draws"]))
    early = decide_grant(si.step, grant)
    if early is not None:
        release_unstarted_step(to_record(si))
        return {"started": False, "grant": to_record(grant), "action": early.value}
    si = replace(si, money_ceiling_usd_micros=grant.amount_usd_micros)
    if job["prev"] is not None:
        cancel_step(job["prev"]["input"], job["prev"]["started_at"])
    worker_id = lease_step(si.case_id, si.plumbing_version, si.bench_version)
    started_at = now_step()
    result = attempt_step(to_record(si), started_at)
    settle_step(to_record(si), result)
    DBOS.send(si.batch_id, {"kind": "settled"}, topic=CASE_EVENT)   # waiting cases wake on every settle
    return {"started": True, "grant": to_record(grant), "input": to_record(si), "result": result,
            "started_at": started_at, "worker_id": worker_id}


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

    def tell(self, kind: str, **fields) -> None:
        DBOS.send(self.batch_id, {"kind": kind, "case": self.case_id, **fields}, topic=CASE_EVENT)

    def stop_line(self, action: Action) -> None:
        if action in ENDS_LINE_OF_WORK and not self.line_stopped:
            self.line_stopped = True
            self.tell("line_stopped", action=action.value)

    def finish(self, status: str) -> None:
        self.status = status
        self.card()
        raise _Stop(status)

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
        admit = step.kind is StepKind.ADMIT
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
                   "request": request_usd_micros(step, counters, self.spec),
                   "case_limit": self.spec.case_money_usd_micros, "draws": draws_case_money(step, counters),
                   "prev": prev}
            queue = DBOS.retrieve_queue(admit_queue(self.batch_id) if admit else steps_queue(self.batch_id))
            with SetWorkflowID(si.idempotency_key):
                out = queue.enqueue(attempt_workflow, job).get_result()
            if not out["started"]:
                action = Action(out["action"])
                self.history.append({"seq": self.seq, "step": step.name, "attempt": attempt,
                                     "outcome": "not_started", "action": action.value})
                if action is Action.WAIT_FOR_BOUND:
                    self.wait_for_bound()
                    continue
                self.last_reason = "engine:below_minimum_grant"
                return action, None
            result = step_result_from_record(out["result"])
            grant = Grant(**out["grant"])
            prev = {"input": out["input"], "started_at": out["started_at"]}
            self.worker_id = out["worker_id"]
            self.absorb(step, attempt, result)
            # A batch-deadline stop after deadline_epoch (or an operator pause) is never counted as
            # an infra error: the batch deadline stops new cases and extensions, not this step.
            now = now_step() if result.reason == DEADLINE_REASON else None
            late_stop = is_batch_deadline_stop(result, self.spec, now)
            if late_stop:
                late += 1
            elif result.outcome is Outcome.INFRA_ERROR and not is_pause(result):
                infra += 1
            if result.outcome is Outcome.PROVIDER_LIMIT:
                if result.usage.paid_usd_micros > 0:
                    limits += 1
                else:
                    free += 1
            if step.kind is StepKind.DIAGNOSIS and result.outcome is Outcome.OK:
                return None, result
            action = decide(step, result, self.counters(infra, limits, free, late), self.spec, grant=grant, now=now)
            if action is Action.RETRY and (late_stop or is_pause(result)):
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
                if seconds > self.spec.release_worker_after_sleep_s and self.worker_id is not None:
                    release_step(self.case_id, self.worker_id)
                    self.worker_id = None
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
        self.inputs = Ref(**rescope_inputs_step(self.batch_id, self.case_id, to_record(self.spec.inputs)))
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
                    self.gates_versions = versions
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
                if action is Action.ADVANCE:
                    self.sealed = {"archive": to_record(r.archive), "hard": r.hard}
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
                        raise_bound_step(self.spec.batch_id, BoundRaised(**msg).money_bound_usd_micros)
                        self.wake_waiting()
                except (ContractError, TypeError):
                    continue

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
        while len(self.done) < len(self.cases):
            msg = DBOS.recv(CASE_EVENT, timeout_seconds=_RT.timing.batch_poll_s)
            if isinstance(msg, dict):
                self.handle(msg)
                continue
            self.operator()
            pending = [c for c in self.cases if c not in self.done]
            for case_id in failed_cases_step(pending):
                self.done[case_id] = "engine_error"
        return {"batch_id": spec.batch_id, "sealed": self.sealed, "cases": dict(self.done)}


@DBOS.workflow(max_recovery_attempts=None)
def batch_workflow(job: dict) -> dict:
    return _Batch(batch_spec_from_record(job["spec"]), job["initial_registry"]).run()


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
                self.register_queues(batch_spec_from_record(w.input["args"][0]["spec"]))
            except (ContractError, AttributeError, IndexError, KeyError, TypeError):
                continue

    def register_queues(self, spec: BatchSpec) -> None:
        DBOS.register_queue(admit_queue(spec.batch_id), global_concurrency=1,
                            polling_interval_sec=self.timing.queue_poll_s, on_conflict="always_update")
        DBOS.register_queue(steps_queue(spec.batch_id), global_concurrency=spec.max_concurrency,
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
                                                        "initial_registry": to_record(initial_registry)})

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
