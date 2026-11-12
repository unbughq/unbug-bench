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
import functools
import hashlib
import json
import os
import threading
import time
from types import SimpleNamespace
from typing import Any, Mapping, Optional

from dbos import DBOS, SetWorkflowID

from durable.contract import (ArtifactKind, BatchSpec, BenchRelease, BoundRaised, ContractError, FounderAction,
                              CASE_ID, FounderReply, Grant, LimitedBy, Outcome, PlumbingRelease, Ref, Step, StepInput, StepKind,
                              StepResult, Topic, Verdict, WorkerLease, assert_no_conductor, batch_spec_from_record,
                              guarded_run, step_input_from_record, step_result_from_record, to_record,
                              wait_seconds)
from durable.classify import CAMPAIGN_WAIT_REASONS, WORKER_POOL_REASONS
from durable.executor import Executor, SeamError
from durable.policy import (DEADLINE_REASON, MAX_WRITER_HANDBACKS, WRITER_HANDBACK, WRITER_HANDBACK_CEILING, POOL_WAIT_CEILING_S, UNCONFIRMED_WORKER_LIMIT_S, ENDS_LINE_OF_WORK, Action, Counters, deadline_s, decide, decide_diagnosis, decide_grant,
                            draws_case_money, is_batch_deadline_stop, is_operational_wait, is_money_stop, is_pause,
                            progressed, request_usd_micros, starts_replacement, gates_money_extension)
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
    degraded_poll_s: float = 15.0      # recheck while the guard has new attempts paused
    admission_backoff_s: float = 300.0     # first wait after admission uses up its infra retries; then doubles
    admission_backoff_max_s: float = 3600.0
    admission_alert_after: int = 4         # backoffs before the status asks for attention, about 75 minutes
    admission_max_backoffs: int = 8        # then the case is held: one failing case must not drain a batch
    reconcile_retry_s: float = 30.0    # after a failed reconcile of an unconfirmed attempt
    unconfirmed_limit_s: float = UNCONFIRMED_WORKER_LIMIT_S  # then it counts as lost
    pool_wait_ceiling_s: float = POOL_WAIT_CEILING_S  # total worker-create waiting per seq before it counts


class _Runtime:
    executor: Optional[Executor] = None
    timing: Timing = Timing()
    admission_paused = staticmethod(lambda: False)
    draining = threading.Event()
    lock = threading.Lock()
    busy = 0     # attempt workflows running in this process
    parked = 0   # of those, held by shutdown at a point where a restart can resume them
    gated = 0    # of those, not started: waiting out a pause before taking money or a worker
    attempt_thread = threading.local()


_RT = _Runtime()


def hold_if_draining() -> None:
    """Shutdown never lets a thread run on past this: the step stays unrecorded and its restart
    attaches to the same worker attempt. The process exit ends the thread."""
    if _RT.draining.is_set():
        if getattr(_RT.attempt_thread, "tracked", False):
            with _RT.lock:
                _RT.parked += 1
        threading.Event().wait()


def draining_sleep(seconds: float) -> None:
    """A wait that shutdown cuts short."""
    _RT.draining.wait(seconds)


def _tracked(workflow):
    """Count an attempt workflow as in flight, so shutdown knows what it is waiting for."""
    @functools.wraps(workflow)
    def run(job: dict) -> dict:
        with _RT.lock:
            _RT.busy += 1
        _RT.attempt_thread.tracked = True
        try:
            return workflow(job)
        finally:
            _RT.attempt_thread.tracked = False
            with _RT.lock:
                _RT.busy -= 1
    return run


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


def _new_attempt_gate() -> None:
    """Before an attempt takes money or a worker: wait out a degraded batch. Attempts already
    running carry on. This only delays a step, so it records nothing and replays the same."""
    hold_if_draining()
    if not _RT.admission_paused():
        return
    tracked = getattr(_RT.attempt_thread, "tracked", False)
    if tracked:
        with _RT.lock:
            _RT.gated += 1
    while _RT.admission_paused():
        time.sleep(_RT.timing.degraded_poll_s)
        if _RT.draining.is_set():
            threading.Event().wait()   # already counted as not running; the process exit ends it
    if tracked:
        with _RT.lock:
            _RT.gated -= 1


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
    _new_attempt_gate()
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
    _new_attempt_gate()
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
    hold_if_draining()
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
        until = time.monotonic() + _RT.timing.unconfirmed_limit_s
        while True:
            hold_if_draining()
            result = guarded_run(reconcile, step_input)
            if result.reason != "engine:executor_raised":
                break
            # The guard keeps no exception text. An unconfirmed worker remains quarantined
            # on the same grant, until the limit passes and it has been deleted.
            if time.monotonic() >= until:
                try:
                    _ex().release(lease)
                    result = StepResult(Outcome.INFRA_ERROR, "infra:worker_lost")
                    break
                except SeamError:
                    pass
            time.sleep(_RT.timing.reconcile_retry_s)
    return to_record(result)


@DBOS.step(**SEAM)
def settle_step(si: dict, result: dict) -> str:
    return _ex().settle(step_input_from_record(si), step_result_from_record(result))


@DBOS.step(**SEAM)
def book_waste_step(keys: list) -> None:
    """A factory_bug diagnosis found these attempts lost to our own bug: their money is waste."""
    for key in keys:
        _ex().book_waste(key, "factory_bug")


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


@DBOS.step()
def recorded_step(idempotency_key: str) -> bool:
    """Whether an attempt with this key was already started (by this case or the one it resumes)."""
    return bool(DBOS.list_workflows(workflow_ids=[idempotency_key], load_input=False, load_output=False))


RESUMABLE_STATUSES = ("held", "retired")
RESUMABLE_OUTCOMES = (Outcome.INFRA_ERROR.value, Outcome.PROVIDER_LIMIT.value)
# A case held by a factory_bug diagnosis resumes at the step that diagnosis looked at, but only
# where that step's stop is a factory check, never a scientific result: re-running a gate or a
# stress review would re-roll a verdict. On 8 November f46dac-2's writer:2 retry took the
# interrupted call's own edits as its starting point and stopped as an unchanged repair.
# On 9 November 22e434-3's round-3 writer reply stopped at the 32k output cap with none of its edits
# applied; writer:output_capped is that stop after the in-round retries are spent.
# A writer or stress step that ran out of the case's own money ("<stage>:money") reached no result
# either: no repair was judged and no stress verdict was given. On 9 November cae763-2 (writer:6)
# and 22e434-3 (writer:4) spent their case money on Go plan calls booked at list price, and their
# diagnoses said factory_bug. Their resume books that step's money as waste (factory_bug_waste_keys)
# and then needs case money left within the ceiling (runtime's resume_money check), so a resume
# never grants the case more than its ceiling. A GATES step that ran out of the case's money
# ("engine:money": GATES reports under the engine stage, classify._STEP_STAGE) gave no failing verdict
# either, since a failing gate ends the step gate_failed. On 11 November 86b100-r9 passed G1-G5 and its
# G16 calibrator call was refused grant_insufficient with $41 of the case unspent (an uncapped Codex
# window), and 2abb0a stopped the same way; both diagnoses said factory_bug. Rerunning that step
# re-rolls no failure (founder 2026-11-12).
FACTORY_BUG_RESUMABLE = {"writer": ("writer:unchanged_repair", "writer:output_capped", "writer:money"),
                         "stress": ("stress:money",), "gates": ("engine:money",)}
# A GATES step whose every attempt ended on our own infrastructure reached no gate verdict, so
# running it again is one more infra retry, not a re-roll. On 9 November 18681d's recertify G16
# failed three times in calibrator setup (the pilot-home teardown fixed by #61), then a diagnosis
# said factory_bug. A step with any other outcome among its attempts is never resumed this way.
# On 10 November 2abb0a and 1110b were held the same way after writer steps whose every attempt
# ended infra:invalid_execution: a writer or stress step that only stopped on infrastructure
# returned no writing and no findings, so it qualifies too. 2abb0a's writer step also met provider
# limits (router:quota, router:credit) among those attempts: a call a provider or our router
# refused returned nothing either, so a provider limit counts as such a stop.
# cae763 on 10 November: its writer:6 ran out of case money once (resumed under the rule above),
# then stopped five times on infrastructure. Each of those attempts returned nothing, so a step
# whose attempts mix the two kinds qualifies; any attempt with another outcome still refuses.
FACTORY_BUG_RESUMABLE_INFRA = ("gates", "writer", "stress")
FACTORY_BUG_INFRA_STOPS = (Outcome.INFRA_ERROR.value, Outcome.PROVIDER_LIMIT.value)
# FACTORY.md 4, founder 2026-11-10: a case is attacked at most this many times. Findings of the
# last attack get one writer fix and the case then goes to GATES, which alone certify quality.
ATTACK_ROUNDS = 2
MAX_FACTORY_BUG_RESUMES = 3   # policy.decide_diagnosis holds at most this many in a lineage


def factory_bug_rerunnable(name: Optional[str], stops: list) -> bool:
    """Whether the step `name` a factory_bug diagnosis looked at may run again, from its attempts'
    results ({"outcome", "reason"}, oldest first): its last stop is a factory check
    (FACTORY_BUG_RESUMABLE), or every attempt returned nothing. It stopped on infrastructure or a
    provider limit, or (an attempt before an earlier factory_bug resume of this step) on one of
    those factory checks: no repair was judged and no verdict given, so running it again is a
    retry, never a re-roll. resume_point and a hold that waits for a release (_Case.diagnose) both
    ask this."""
    kind = name.split(":")[0] if name else None
    stopped = stops[-1] if stops else None
    factory_check = (isinstance(stopped, dict) and stopped.get("outcome") == Outcome.EXHAUSTED.value
                     and stopped.get("reason") in FACTORY_BUG_RESUMABLE.get(kind, ()))

    def returned_nothing(s):
        return isinstance(s, dict) and (
            s.get("outcome") in FACTORY_BUG_INFRA_STOPS or s.get("reason") == WRITER_HANDBACK
            or s.get("outcome") == Outcome.EXHAUSTED.value and s.get("reason") in FACTORY_BUG_RESUMABLE.get(kind, ()))
    return factory_check or (kind in FACTORY_BUG_RESUMABLE_INFRA and bool(stops)
                             and all(returned_nothing(s) for s in stops))


# Founder 2026-11-11: a case killed by a factory bug since fixed may be resumed once more by an
# explicit operator override (`start --resume-case <case> --override-reason <text>`), where the rules
# above refuse it: a factory_bug hold whose diagnosed stops are not all rerunnable, or that reached
# MAX_FACTORY_BUG_RESUMES, or a case held or retired whose last attempt was not an infra stop. Never
# a case that has not finished or sealed, and never a stop _override_refusal names. Once per lineage:
# the override and its reason ride in the resume record (and on the case card), so a later one sees it.
OVERRIDE_REASON_MAX = 200


def _override_refusal(kind: Optional[str], r) -> Optional[str]:
    """Why no override reruns a step of `kind` that stopped with result `r`, or None when it reached
    no result (never started, infra, a provider limit, a handback, or a FACTORY_BUG_RESUMABLE check).
    A scientific judgment: a gate verdict, a founder escalation (NEEDS_FOUNDER, e.g. G8/G9/G16/G17 or
    a stress split) or a stress round's findings. A ceiling: any other EXHAUSTED stop, such as
    writer:rounds_exhausted or a call or cost limit; FACTORY.md: exhausted ceilings need higher
    explicit flags, not a reset, and unchanged repairs still stop."""
    if not isinstance(r, dict):
        return None
    outcome = r.get("outcome")
    if (outcome in (Outcome.GATE_FAILED.value, Outcome.NEEDS_FOUNDER.value)
            or outcome == Outcome.OK.value and r.get("feedback") is not None):
        return "resume:scientific_stop"
    if outcome == Outcome.EXHAUSTED.value and r.get("reason") not in FACTORY_BUG_RESUMABLE.get(kind, ()):
        return "resume:ceiling_stop"
    return None


def _retired_only_by_deadline(latest, attempts: dict, last: tuple, earlier: list, result_of) -> bool:
    """Whether a close_to_passing diagnosis (`last`) was retired only because the batch deadline had
    passed (_Case.diagnose), not by decide_diagnosis: it finished after the deadline, the case had
    extensions left, its last extension (if any) progressed, and it is not a recertified case (never
    rewritten). Progress compares the gates passed when that extension began with those its own
    GATES passed, from the recorded results, as _Case.diagnose does (ext_before, ext_after)."""
    spec = DBOS.list_workflows(workflow_ids=[latest.workflow_id])[0].input["args"][0]["spec"]
    if (attempts[last].updated_at or 0) / 1000 < spec["deadline_epoch"]:
        return False
    card = DBOS.get_event(latest.workflow_id, "card", timeout_seconds=0) or {}
    used = card.get("extensions")
    if type(used) is not int or used >= min(spec.get("max_extensions", 5), 5):
        return False
    rows = sorted(attempts.items(), key=lambda kv: (kv[1].created_at or 0, kv[0]))

    def kind(w):
        return w.workflow_id.split("/")[2].split(":")[0]
    admit = [result_of(w) for _, w in rows if kind(w) == StepKind.ADMIT.value]
    if (any(isinstance(r, dict) and r.get("reason") == "admit:imported_sealed" for r in admit)
            and not any(r.get("recertify_repair") is True for r in earlier)):
        return False
    if used == 0:
        return True
    # The extension began at the last close_to_passing diagnosis before this one.
    started = [i for i, (k, w) in enumerate(rows) if k != last and kind(w) == StepKind.DIAGNOSIS.value
               and (result_of(w) or {}).get("verdict") == Verdict.CLOSE_TO_PASSING.value]
    if not started:
        return False

    def passed(lo, hi):   # the latest GATES result among rows[lo:hi], as _Case.absorb keeps it
        found = [r.get("passed") or [] for _, w in rows[lo:hi] if kind(w) == StepKind.GATES.value
                 for r in [result_of(w)] if isinstance(r, dict)]
        return tuple(found[-1]) if found else None
    end = next(i for i, (k, _) in enumerate(rows) if k == last)
    before = passed(0, started[-1]) or ()
    after = passed(started[-1] + 1, end) or ()
    try:
        return progressed(before, after)
    except ContractError:
        return False


def resume_point(case_id: str, override: Optional[str] = None) -> dict:
    """Where a case stopped by an infrastructure failure continues (_resume_point)."""
    return _resume_point(case_id, override)[0]


def factory_bug_waste_keys(case_id: str, override: Optional[str] = None) -> list:
    """The idempotency keys of the attempts a factory_bug diagnosis found lost to our own bug: every
    recorded attempt of the diagnosed step, when the case resumes after such a diagnosis, else none.
    Their money is waste, never the case's (ledger.book_waste with reason factory_bug)."""
    return _resume_point(case_id, override)[1]


def _resume_point(case_id: str, override: Optional[str] = None) -> tuple:
    """Where a case stopped by an infrastructure failure continues, from its recorded attempts.

    The case keeps its ID, so its key, artifacts, snapshot card and admission binding stay valid;
    only the new workflow ("<case>@<batch>") is new. Its seqs before `seq` replay the recorded
    attempts, and `seq` restarts after them with a fresh retry allowance. A case is resumable only
    when every workflow of it has finished as held or retired and its last attempt ended in an
    infrastructure or provider failure: never after a verdict, a gate, an exhausted limit or a
    founder's decision. One exception is a recertified case retired because a gate asked for a
    repair (see gates_repair below). The other is a case held by a factory_bug diagnosis of a factory
    check or of a writer or stress step that ran out of case money (FACTORY_BUG_RESUMABLE) or of a GATES, writer or stress step that only ever stopped on infrastructure,
    a provider limit or (before an earlier such resume) one of those factory checks (FACTORY_BUG_RESUMABLE_INFRA): it resumes at the diagnosed step, its diagnosis is not replayed,
    and the resume counts against the lineage's factory_bug_resumes."""
    if type(case_id) is not str or not CASE_ID.fullmatch(case_id):
        raise ContractError("resume:bad_case")
    if override is not None and not (type(override) is str and 0 < len(override.strip()) <= OVERRIDE_REASON_MAX
                                     and override.isprintable()):
        raise ContractError("resume:bad_override")
    runs = (DBOS.list_workflows(workflow_ids=[case_id], name=case_workflow.__qualname__, load_input=False)
            + DBOS.list_workflows(workflow_id_prefix=case_id + "@", name=case_workflow.__qualname__))
    if not runs:
        raise ContractError("resume:unknown_case")
    if any(w.status != "SUCCESS" for w in runs):
        raise ContractError("resume:case_not_finished")
    latest = max(runs, key=lambda w: (w.created_at or 0, w.workflow_id))
    if not isinstance(latest.output, dict) or latest.output.get("status") not in RESUMABLE_STATUSES:
        raise ContractError("resume:not_stopped_by_infra")
    attempts = {}
    for w in DBOS.list_workflows(workflow_id_prefix=case_id + "/", name=slot_workflow.__qualname__,
                                 load_input=False):
        parts = w.workflow_id.split("/")
        if len(parts) != 4 or parts[0] != case_id or not (parts[1].isdigit() and parts[3].isdigit()):
            continue
        # After a factory_bug resume the diagnosis seq is reused by the next step: the later one counts.
        key = (int(parts[1]), int(parts[3]))
        if key not in attempts or (w.created_at or 0, w.workflow_id) > (attempts[key].created_at or 0,
                                                                         attempts[key].workflow_id):
            attempts[key] = w
    if not attempts:
        raise ContractError("resume:no_attempts")

    def result_of(w):
        out = w.output
        return out.get("result") if w.status == "SUCCESS" and isinstance(out, dict) else None

    # The case's last attempt is the newest one, not the highest key: a factory_bug resume rewinds to
    # seq - 1, so an older diagnosis can keep a higher seq (18681d, 11 November: its new 2/gates:1/7
    # repair request was read as the old 3/diagnosis/5 and the gates_repair resume refused).
    seq, attempt = max(attempts, key=lambda k: (attempts[k].created_at or 0, k))
    result = result_of(attempts[(seq, attempt)])
    earlier = [(w.input["args"][0].get("resume") or {}) for w in runs if w.workflow_id != case_id]
    if override is not None and any(r.get("override") is not None for r in earlier):
        raise ContractError("resume:override_used")   # once per lineage
    overridden = False
    factory_bug_resumes = max([r.get("factory_bug_resumes", 0) for r in earlier], default=0)
    # Resumes the latest workflow made in place (rerun_after_release), by diagnosis seq. The new
    # workflow replays, and so counts again, those below the seq it resumes at; the rest it is told of.
    reruns = DBOS.get_event(latest.workflow_id, "factory_bug_rerun_seqs", timeout_seconds=0) or []

    def unreplayed(resume_seq):
        return sum(1 for d in reruns if d >= resume_seq)
    renumber = {}
    for r in earlier:
        for k, steps in r.get("renumber", {}).items():
            for name, n in steps.items():
                renumber.setdefault(int(k), {})[name] = max(renumber.get(int(k), {}).get(name, 0), n)
    waste_keys = []
    gates_repair = (latest.output.get("status") == "retired" and isinstance(result, dict)
                    and attempts[(seq, attempt)].workflow_id.split("/")[2].split(":")[0] == StepKind.GATES.value
                    and result.get("outcome") == Outcome.GATE_FAILED.value and result.get("repairable") is True
                    and result.get("feedback") is not None)
    if gates_repair:
        # Founder 2026-11-10: a recertified case retired only because a gate asked for a repair
        # (recertify never rewrites) continues as an ordinary case: the GATES seq replays, its
        # feedback goes to a writer round, then every gate runs again (run.engine_writer_round drops
        # the kept October verdicts; the October case had its attack round then). Only that
        # retirement qualifies. Later resumes of the lineage carry the repaired GATES seq.
        skip = {}
        for r in earlier:
            skip.update({int(k): v for k, v in r.get("skip", {}).items()})
        # Seqs above the repaired GATES belong to steps that no longer follow it (an older diagnosis).
        skip = {k: v for k, v in skip.items() if k <= seq}
        return ({"seq": seq + 1, "skip": {str(k): v for k, v in sorted(skip.items())},
                 "factory_bug_resumes": factory_bug_resumes + unreplayed(seq + 1), "recertify_repair": True,
                 "recertify_repair_seq": seq,
                 "renumber": {str(k): v for k, v in sorted(renumber.items())}}, waste_keys)
    last_step = attempts[(seq, attempt)].workflow_id.split("/")[2]
    diagnosis_ok = (last_step == StepKind.DIAGNOSIS.value and isinstance(result, dict)
                    and result.get("outcome") == Outcome.OK.value)
    if not (diagnosis_ok and result.get("verdict") == Verdict.FACTORY_BUG.value) and not (
            isinstance(result, dict) and result.get("outcome") in RESUMABLE_OUTCOMES):
        # Operator override only: the last attempt reached no scientific result (it never started,
        # or stopped on money or a limit), or a diagnosis said close_to_passing and the batch deadline
        # retired it (no extension starts after it). That step runs again at its seq, as after an
        # infra stop; a diagnosis verdict is asked afresh rather than replayed into an extension.
        if override is None:
            raise ContractError("resume:not_stopped_by_infra")
        if diagnosis_ok:
            if not (result.get("verdict") == Verdict.CLOSE_TO_PASSING.value and latest.output.get("status") == "retired"
                    and _retired_only_by_deadline(latest, attempts, (seq, attempt), earlier, result_of)):
                raise ContractError("resume:scientific_stop")
        elif _override_refusal(last_step.split(":")[0], result):
            raise ContractError(_override_refusal(last_step.split(":")[0], result))
        overridden = True
        factory_bug_resumes += unreplayed(seq)
    elif not (isinstance(result, dict) and result.get("outcome") in RESUMABLE_OUTCOMES):
        # The diagnosed step is the one that ran last at seq - 1. A factory_bug resume can give that
        # seq to a new step while an older diagnosis there kept higher-numbered attempts; those belong
        # to another step and must not decide this one (they still count for skip and renumber).
        before = [w for (s, _), w in attempts.items() if s == seq - 1]
        name = max(before, key=lambda w: (w.created_at or 0, w.workflow_id)).workflow_id.split("/")[2] if before else None
        diagnosed = sorted(a for (s, a), w in attempts.items() if s == seq - 1 and w.workflow_id.split("/")[2] == name)
        stops = [result_of(attempts[(seq - 1, a)]) for a in diagnosed]
        if not (latest.output.get("status") == "held" and factory_bug_rerunnable(name, stops)):
            # The override reruns the diagnosed step whatever its stops, but never a scientific one.
            if override is None:
                raise ContractError("resume:not_stopped_by_infra")
            if not diagnosed:
                raise ContractError("resume:no_diagnosed_step")
            refusal = next(filter(None, (_override_refusal(name.split(":")[0], s) for s in stops)), None)
            if refusal:
                raise ContractError(refusal)
            overridden = True
        factory_bug_resumes += unreplayed(seq - 1)
        if factory_bug_resumes >= MAX_FACTORY_BUG_RESUMES:   # defensive: the policy retires first
            if override is None:
                raise ContractError("resume:factory_bug_resumes_exhausted")
            overridden = True
        # A later diagnosis at that seq numbers its attempts after this one, so its key is new.
        renumber[seq] = {StepKind.DIAGNOSIS.value: max(renumber.get(seq, {}).get(StepKind.DIAGNOSIS.value, 0), attempt)}
        waste_keys = [attempts[(seq - 1, a)].workflow_id for a in diagnosed]
        seq, attempt, factory_bug_resumes = seq - 1, diagnosed[-1], factory_bug_resumes + 1
    else:
        factory_bug_resumes += unreplayed(seq)
    skip = {}
    for r in earlier:
        skip.update({int(k): v for k, v in r.get("skip", {}).items()})
    if seq < max(attempts)[0]:
        # A factory_bug resume rewinds below seqs an earlier resume may have skipped into (its
        # diagnosis after an infra stop): the steps that now take those seqs never ran there.
        skip = {k: v for k, v in skip.items() if k < seq}
    skip[seq] = max(skip.get(seq, 0), attempt)
    # The attack cap governs from the seq an earlier workflow of this case first applied it. A case
    # that only ever ran under the older rule is governed from the seq it resumes at.
    caps = [r["attack_cap_from"] for r in earlier if r.get("attack_cap_from") is not None]
    caps += [c for c in (DBOS.get_event(w.workflow_id, "attack_cap_from", timeout_seconds=0) for w in runs)
             if c is not None]
    point = {"seq": seq, "skip": {str(k): v for k, v in sorted(skip.items())},
             "factory_bug_resumes": factory_bug_resumes, "attack_cap_from": min(caps, default=seq),
             "renumber": {str(k): v for k, v in sorted(renumber.items())}}
    repaired = [r["recertify_repair_seq"] for r in earlier if r.get("recertify_repair_seq") is not None]
    if repaired:   # a repaired recertified case that stopped again replays its repair decision
        point.update(recertify_repair=True, recertify_repair_seq=repaired[0])
    if overridden:   # only when the rules above refused it: an allowed resume spends no override
        point["override"] = override
    return (point, waste_keys)


# ---- the attempt workflow ------------------------------------------------------------------------

@DBOS.workflow(max_recovery_attempts=None)
@_tracked
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
        DBOS.send(si.batch_id, {"kind": "settled", "case": si.case_id}, topic=CASE_EVENT)
        return {"started": False, "action": Action.STOP_ADMISSION.value, "reason": "infra:deadline"}
    early = decide_grant(si.step, grant)
    if early is not None:
        release_unstarted_step(to_record(si))
        # A sub-minimum BATCH grant was everything the batch had left, so it cut no other case's
        # grant: its release wakes nobody (else two capped cases could wake each other forever).
        DBOS.send(si.batch_id, {"kind": "settled", "case": si.case_id,
                                "unstarted": early is Action.WAIT_FOR_BOUND}, topic=CASE_EVENT)
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
        DBOS.send(si.batch_id, {"kind": "settled", "case": si.case_id}, topic=CASE_EVENT)
        return {"started": True, "grant": to_record(grant), "input": to_record(si),
                "result": to_record(StepResult(Outcome.INFRA_ERROR, lease["reason"])),
                "started_at": None, "worker_id": None}
    started_at = now_step()
    result = attempt_step(to_record(si), started_at, worker_id)
    settle_step(to_record(si), result)
    DBOS.send(si.batch_id, {"kind": "settled", "case": si.case_id}, topic=CASE_EVENT)   # wakes the other waiting cases
    return {"started": True, "grant": to_record(grant), "input": to_record(si), "result": result,
            "started_at": started_at, "worker_id": worker_id}


@DBOS.workflow(max_recovery_attempts=None)
@_tracked
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
        self.factory_bug_resumes = 0
        # factory_bug resumes of earlier batches in this lineage (resume_point). Kept apart from the
        # counter the replayed admission recovery reads and increments, so the replay matches.
        self.lineage_factory_bug_resumes = 0
        self.in_extension = False
        self.recertify = False   # a sealed October case re-earning only the gates added since
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
        # A resumed case (resume_point) keeps its case ID and runs under another workflow ID.
        # Seqs below resume_seq replay the attempts already recorded under that case ID, with
        # no worker, wait or message; each seq in skip starts after its recorded attempts.
        self.workflow_id = case_id
        self.resume_seq = 0
        self.skip: dict = {}
        # After a factory_bug resume: {seq: {step name: attempts}} recorded there by a step that
        # is no longer replayed (its diagnosis). A step of that name at that seq numbers after them.
        self.renumber: dict = {}
        # resume_point: the GATES seq at which a recertified case was retired for a repair, when a
        # resume sends it to that repair.
        self.recertify_repair_seq: Optional[int] = None
        # Attack cap (ATTACK_ROUNDS). attack_rounds counts stress rounds that returned findings.
        # attack_cap_from is the first seq the cap governs: a case that began under the older rule
        # (stress had to come back clean) replays its recorded rounds unchanged below it.
        self.attack_rounds = 0
        self.attack_cap_from: Optional[int] = None
        self.final_fix = False          # the next writer round is followed by GATES, not stress
        # The last step run_seq ran (step, feedback) and the (plumbing, bench) its last started
        # attempt ran on: what a factory_bug hold reruns, and the release it waits to change.
        self.ran: Optional[tuple] = None
        self.ran_on: Optional[tuple] = None
        self.rerun_seqs: list = []   # diagnosis seqs of factory_bug resumes in this workflow (rerun_after_release)
        self.override: Optional[str] = None   # the operator's reason, when an override resumed this case

    @property
    def replaying(self) -> bool:
        return self.seq < self.resume_seq

    def attack_capped(self) -> bool:
        """After a step at self.seq: has this case used its attack rounds, so no further stress runs?"""
        if self.attack_rounds < ATTACK_ROUNDS:
            return False
        if self.attack_cap_from is None:
            # A workflow that passed this point before the cap existed keeps looping as recorded.
            if not DBOS.patch("attack_cap"):
                return False
            self.attack_cap_from = self.seq
            DBOS.set_event("attack_cap_from", self.seq)   # resume_point carries it to a later workflow
        return self.seq >= self.attack_cap_from

    def attack_cap_active(self) -> bool:
        return (self.attack_rounds >= ATTACK_ROUNDS and self.attack_cap_from is not None
                and self.seq >= self.attack_cap_from)

    # -- records and messages --

    def counters(self, infra=0, limits=0, free=0, late=0) -> Counters:
        return Counters(step_infra_errors=infra, step_spent_limits=limits, step_free_limits=free,
                        step_deadline_stops=late,
                        writer_rounds_used=self.writer_rounds_used,
                        extensions_used=self.extensions_used, diagnoses_used=self.diagnoses_used,
                        factory_bug_resumes=self.factory_bug_resumes + self.lineage_factory_bug_resumes,
                        in_extension=self.in_extension)

    def card(self) -> None:
        card = {
            "case_id": self.case_id, "replacement_of": self.replacement_of, "status": self.status,
            "stage": self.stage, "reason": self.last_reason, "passed": list(self.passed),
            "failed_gate": self.failed_gate, "writer_rounds": self.writer_rounds_used,
            "attack_rounds": self.attack_rounds,   # stress rounds that returned findings (cap: ATTACK_ROUNDS)
            "extensions": self.extensions_used, "diagnoses": self.diagnoses_used, "verdict": self.verdict,
            "hard": None if self.sealed is None else self.sealed["hard"]}
        if self.override is not None:   # only an override's own workflow: other cards are unchanged
            card["override"] = self.override
        DBOS.set_event("card", card)

    def tell(self, kind: str, *, _idempotency_key: Optional[str] = None, **fields) -> None:
        if self.replaying:
            return   # the original workflow already told its own batch
        DBOS.send(self.batch_id, {"kind": kind, "case": self.workflow_id, **fields}, topic=CASE_EVENT,
                  idempotency_key=_idempotency_key)

    def stop_line(self, action: Action) -> None:
        if action in ENDS_LINE_OF_WORK and not self.line_stopped:
            self.line_stopped = True
            self.tell("line_stopped", action=action.value)

    def finish(self, status: str) -> None:
        if self.replaying:
            raise ContractError("resume:diverged")   # the recorded attempts went on past this point
        self.release_worker()
        if status == "sealed":
            DBOS.set_event("seal_cleanup_complete", True)
        self.status = status
        self.card()
        raise _Stop(status)

    def release_worker(self) -> None:
        if self.replaying:
            self.worker_id = None   # a recorded worker; the original workflow released it
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
        self.ran = (step, feedback, self.in_extension)   # run() clears in_extension after a GATES step
        # A resumed case replays its old GATES bench, and only a GATES step changed it, so its writer
        # and stress steps kept running on that old bench in every later batch (86b100, 11 November:
        # the Nov 5 bench under a spec naming a newer one). Its first live step adopts the batch's
        # bench instead. Nothing retained depends on the old one: SEAL runs only under the versions
        # its GATES passed, and every path from a writer, stress or diagnosis step reaches SEAL
        # through a GATES step, which adopts the current bench anyway.
        if (self.resume_seq and self.seq == self.resume_seq
                and step.kind not in (StepKind.GATES, StepKind.SEAL)
                and DBOS.patch("resume_adopts_bench")):
            self.bench = self.current("bench")
        attempt, infra, limits, free, late, prev = self.renumber.get(self.seq, {}).get(step.name, 0), 0, 0, 0, 0, None
        handbacks = 0
        # A seq where a case stopped (this resume's or an earlier one's) first restores the attempts
        # recorded before that stop: their snapshots, diagnostics and history carry over, and their
        # keys prove the continuation is the same step. Only its infra retry allowance starts afresh.
        recorded = self.skip.get(self.seq, 0)
        pool_since = None
        requested_minimum = 0
        failed_releases = []
        backoffs, admission_waste = 0, 0
        admit = step.kind is StepKind.ADMIT
        admission_started = False
        while True:
            attempt += 1
            pv, bv = versions if versions is not None else (self.current("plumbing"), self.bench)
            snapshot = self.snapshot if (not admit or DBOS.patch("admit_checkpoint_input")) else None
            si = StepInput(self.batch_id, self.case_id, self.seq, step, attempt, pv, bv,
                           inputs=self.spec.inputs if admit else self.inputs,
                           snapshot=snapshot, deadline_s=deadline_s(step, self.spec),
                           money_ceiling_usd_micros=0, feedback=feedback,
                           registry=Ref(**self.initial_registry) if admit else None, ruling=ruling,
                           evidence=tuple(evidence))
            counters = self.counters(infra, limits, free, late)
            job = {"input": to_record(si), "initial_registry": self.initial_registry,
                   "request": max(requested_minimum, request_usd_micros(step, counters, self.spec)),
                   "case_limit": self.spec.case_money_usd_micros, "draws": draws_case_money(step, counters),
                   "prev": prev}
            extension = gates_money_extension(step)
            if extension and DBOS.patch("gates_money_up_front"):
                job["request"] += extension
                job["case_limit"] += extension
            if admit and not admission_started:
                job["admission_deadline"] = self.spec.deadline_epoch
            restoring = attempt <= recorded
            if (self.replaying or restoring) and not recorded_step(si.idempotency_key):
                raise ContractError("resume:diverged")   # never start new work inside the replayed history
            queue = DBOS.retrieve_queue(steps_queue(self.batch_id))
            with SetWorkflowID(si.idempotency_key):
                out = queue.enqueue(slot_workflow, job).get_result()
            if restoring and not out["started"]:
                continue
            if not out["started"]:
                action = Action(out["action"])
                if action is Action.RERUN_GATES:
                    return action, None
                self.history.append({"seq": self.seq, "step": step.name, "attempt": attempt,
                                     "outcome": "not_started", "action": action.value})
                if action is Action.WAIT_FOR_BOUND:
                    if not self.replaying and not self.wait_for_bound(
                            self.spec.deadline_epoch if admit and not admission_started else None):
                        self.last_reason = DEADLINE_REASON
                        return Action.STOP_ADMISSION, None
                    continue
                self.last_reason = out.get("reason", "engine:below_minimum_grant")
                return action, None
            result = step_result_from_record(out["result"])
            grant = Grant(**out["grant"])
            self.ran_on = (out["input"]["plumbing_version"], out["input"]["bench_version"])
            if out["worker_id"] is not None:
                admission_started = True
                prev = {"input": out["input"], "started_at": out["started_at"], "worker_id": out["worker_id"]}
                self.worker_id = out["worker_id"]
            if step.kind is StepKind.GATES:
                self.bench = out["input"]["bench_version"]
                self.gates_versions = (out["input"]["plumbing_version"], self.bench)
            self.absorb(step, attempt, result)
            if restoring:
                prev, self.worker_id = None, None   # its worker is gone; the first live attempt leases one
                continue
            if result.outcome is Outcome.INFRA_ERROR:
                admission_waste += result.usage.paid_usd_micros
                # Checked here so a retry is never funded past either limit.
                if (admit and (admission_waste >= self.spec.case_money_usd_micros
                               or result.reason == "infra:creation_limit")
                        and DBOS.patch('admission_waste_cutoff')):
                    return Action.HOLD, result
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
                # Waiting for a free campaign slot is bounded by the batch deadline, not the ceiling:
                # a slot frees whenever another case finishes. No replay diverges: nothing recorded
                # these reasons before they existed.
                pool_wait = (pool_now - pool_since < _RT.timing.pool_wait_ceiling_s
                             or result.reason in CAMPAIGN_WAIT_REASONS)
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
            if (step.kind is StepKind.WRITER and result.outcome is Outcome.OK and result.reason == WRITER_HANDBACK
                    and DBOS.patch("writer_handback_retry")):
                # The writer stopped between calls to finish its round with fresh time (policy.WRITER_HANDBACK).
                # Unpatched replays keep the ADVANCE they recorded. A handback that keeps returning is infra.
                handbacks += 1
                # The writer bounds its handbacks by the case's own rounds (policy.WRITER_HANDBACK); the
                # engine backstops at the ceiling. Within the old fixed cap no patch is asked, and
                # workflows recorded before the patch keep that cap.
                over = handbacks > MAX_WRITER_HANDBACKS and (
                    handbacks > WRITER_HANDBACK_CEILING or not DBOS.patch("writer_handback_ceiling"))
                if over:
                    infra += 1
                action = (Action.RETRY if not over
                          or infra <= self.spec.max_infra_retries_per_step else Action.DIAGNOSE)
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
                if not self.replaying:
                    DBOS.sleep(max(0.001, _RT.timing.credential_retry_s))
                self.status = "running"
                self.last_reason = None
                self.card()
                continue
            if action is Action.RETRY and (late_stop or is_pause(result) or pool_wait):
                # Wait before the retry, so a stop that repeats does not spin.
                if self.replaying:
                    self.worker_id = None
                    continue
                if _RT.timing.pause_retry_s > self.spec.release_worker_after_sleep_s and self.worker_id is not None:
                    release_step(self.case_id, self.worker_id)
                    self.worker_id = None
                DBOS.sleep(_RT.timing.pause_retry_s)
                continue
            if action is Action.RETRY:
                continue
            if action is Action.SLEEP:
                seconds = wait_seconds(result.retry_at, now_step())
                # A short wait keeps its worker: releasing it made every retry create a new one,
                # and on 8 November the 15-minute rate waits of five cases spent the campaign's
                # whole creation allowance. Only a wait past release_worker_after_sleep_s releases it.
                if (not DBOS.patch('short_sleep_keeps_worker')
                        or seconds > self.spec.release_worker_after_sleep_s):
                    self.release_worker()
                if not self.replaying:
                    DBOS.sleep(seconds)
                continue
            if action is Action.WAIT_FOR_BOUND:
                if not self.replaying and not self.wait_for_bound(
                        self.spec.deadline_epoch if admit and not admission_started else None):
                    return Action.STOP_ADMISSION, result
                continue
            if (admit and action is Action.STOP_ADMISSION and result.outcome is Outcome.INFRA_ERROR
                    and DBOS.patch('admission_release_recovery')):
                if not admission_started and now_step() >= self.spec.deadline_epoch:
                    return Action.STOP_ADMISSION, result
                if DBOS.patch('admission_infra_backoff'):
                    # Infra failures are retried, never scored. Money and the deadline bound this.
                    if now_step() >= self.spec.deadline_epoch:
                        return Action.STOP_ADMISSION, result
                    if backoffs >= _RT.timing.admission_max_backoffs:
                        return Action.HOLD, result
                    backoffs += 1
                    if backoffs > _RT.timing.admission_alert_after:
                        self.status = 'retrying_admission'
                    self.card()
                    # A retry on a fresh worker spends the campaign's creation allowance, and
                    # acquire still checks this one is alive. An idle worker costs cents.
                    if not DBOS.patch('admission_backoff_keeps_worker'):
                        self.release_worker()
                    if not self.replaying:
                        DBOS.sleep(min(_RT.timing.admission_backoff_max_s,
                                       _RT.timing.admission_backoff_s * 2 ** min(backoffs - 1, 16)))
                    if now_step() >= self.spec.deadline_epoch:   # the sleep may have crossed it
                        return Action.STOP_ADMISSION, result
                    infra = self.spec.max_infra_retries_per_step   # one attempt per backoff
                    continue
                if self.factory_bug_resumes >= min(self.spec.max_factory_bug_resumes, 3):
                    return Action.HOLD, result
                # Use the release actually dispatched, including queued release changes.
                failed_releases.append(out['input']['plumbing_version'])
                if not self.replaying:
                    self.wait_for_release(failed_releases)
                self.factory_bug_resumes += 1
                infra = 0
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

    def wait_for_bound(self, deadline: Optional[float] = None) -> bool:
        """Block until the batch wakes this case (a settle that freed money, a bound raise or a
        release). False: the admission deadline passed first. A poll timeout alone never retries:
        with nothing left, each retry's own settle used to wake the case again, and it spun."""
        self.release_worker()
        self.status = "waiting_for_bound"
        self.card()
        self.tell("waiting")
        blocks = DBOS.patch("bound_wait_blocks")
        while DBOS.recv(WAKE, timeout_seconds=_RT.timing.wake_poll_s) is None and blocks:
            if deadline is not None and now_step() >= deadline:
                return False
        self.status = "running"
        return True

    def wait_for_release(self, failed_releases: list) -> None:
        """Park without a worker, slot or hold; a previously failed release cannot retry."""
        self.release_worker()
        self.status = 'waiting_for_release'
        self.card()
        while self.current('plumbing') in failed_releases:
            self.tell('waiting')
            DBOS.recv(WAKE, timeout_seconds=_RT.timing.wake_poll_s)
        self.status = 'running'
        self.card()

    # -- the case --

    def run(self) -> None:
        action, r = self.run_seq(Step(StepKind.ADMIT))
        if action in (Action.STOP_ADMISSION, Action.HOLD):
            self.tell("stop_admission")
            self.finish("held" if action is Action.HOLD else "stopped_admission")
        assert action is Action.ADVANCE, action
        if self.status == "retrying_admission":
            self.status = "running"
        self.card()
        phase, feedback, ruling = "writer", None, None
        if r is not None and r.reason == "admit:imported_written":
            phase = "stress"   # an imported case whose writing passed G1 starts with a stress round
        if r is not None and r.reason == "admit:imported_sealed":
            # A sealed October case keeps its G1-G15 verdicts and reruns only GATES (G3, G16, G10,
            # G17, G11) and SEAL. A gate that asks for a repair retires it; only a resume of that
            # retirement (recertify_repair) rewrites it, and then every gate runs.
            self.recertify, phase = True, "gates"
        while True:
            if phase == "writer":
                action, r = self.run_seq(Step(StepKind.WRITER, self.round), feedback=feedback)
                feedback = None
                if action is Action.ADVANCE:
                    if not self.in_extension:
                        self.writer_rounds_used += 1
                    phase, self.final_fix = ("gates" if self.final_fix else "stress"), False
                else:
                    phase, feedback = self.stopped(action)
            elif phase == "stress":
                step = Step(StepKind.STRESS, self.round)
                action, r = self.run_seq(step, ruling=ruling)
                ruling = None
                findings = (r is not None and r.outcome is Outcome.OK and r.feedback is not None
                            and action in (Action.REPAIR, Action.DIAGNOSE))
                if findings:
                    self.attack_rounds += 1
                if action is Action.ADVANCE:
                    phase = "gates"
                elif findings and self.attack_capped():
                    # The last attack: one writer fix of its findings, then GATES whatever round or
                    # extension this is. The writer's own checks replay every saved cheat first.
                    self.final_fix = True
                    self.round += 1
                    phase, feedback = "writer", r.feedback
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
                elif action is Action.REPAIR and self.recertify and self.seq == self.recertify_repair_seq:
                    self.recertify = False                 # resumed for repair: an ordinary case from here
                    self.round += 1
                    phase, feedback = "writer", r.feedback
                    # The October case had its attack round then. Like any gate repair after the last
                    # attack, this fix goes back to GATES, which now run every gate on it.
                    self.final_fix = True
                elif action is Action.REPAIR and self.recertify:
                    self.stop_line(Action.RETIRE)
                    self.finish("retired")
                elif action is Action.REPAIR:
                    self.round += 1
                    phase, feedback = "writer", r.feedback
                    # A gate repair is not attacked again; a repaired recertified case never is.
                    self.final_fix = self.attack_cap_active() or self.recertify_repair_seq is not None
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
        before = (self.snapshot, list(self.evidence), self.verdict, self.ran, self.ran_on)
        self.diagnoses_used += 1
        self.in_extension = False
        history = seal_history_step(self.case_id, self.history)
        evidence = (*self.evidence, Ref(**history))
        self.card()
        action, r = self.run_seq(Step(StepKind.DIAGNOSIS), evidence=evidence)
        if action is not None:                              # a diagnosis is never diagnosed
            # A diagnosis that never ran (no worker, an outage) holds the case like any other infra
            # stop: on 8 November f46dac was retired, as if judged, when no worker could be created.
            if r.outcome is Outcome.INFRA_ERROR and DBOS.patch('diagnosis_infra_holds'):
                self.stop_line(Action.HOLD)
                self.finish("held")
            self.stop_line(Action.RETIRE)
            self.finish("retired")
        self.verdict = r.verdict.value
        prog = progressed(self.ext_before, self.ext_after) if self.ext_before is not None else False
        decision = decide_diagnosis(r.verdict, progressed=prog, counters=self.counters(), spec=self.spec)
        if decision is Action.EXTEND and now_step() >= self.spec.deadline_epoch:
            decision = Action.RETIRE                        # no extension starts after the deadline
        if decision is Action.EXTEND and self.recertify:
            decision = Action.RETIRE                        # a recertified case is never rewritten
        self.stop_line(decision)
        if decision is Action.HOLD:
            rerun = self.rerun_after_release(before)
            if rerun is not None:
                return rerun
            self.finish("held")
        if decision is Action.RETIRE:
            self.finish("retired")
        assert decision is Action.EXTEND, decision
        self.extensions_used += 1
        self.in_extension = True
        self.ext_before, self.ext_after = self.passed, ()
        self.round += 1
        # An extension of a capped case, or of a repaired recertified case, skips its stress round.
        self.final_fix = self.attack_cap_active() or self.recertify_repair_seq is not None
        return "writer", r.feedback

    def rerun_after_release(self, before: tuple) -> Optional[tuple]:
        """A factory_bug hold of a step that may run again (factory_bug_rerunnable) waits in this
        workflow for the factory to change, instead of ending for a manual `--resume-case` batch
        (86b100 needed three of those on 11 November). It continues as that resume would: the
        diagnosed step runs again at its seq after its recorded attempts, on the releases now
        current, with its money booked as waste and the diagnosis uncounted; only the lineage's
        factory_bug_resumes grows, so the policy's cap still ends the loop. Returns the (phase,
        feedback) that reruns the step, or None to hold as before: another step, a workflow that
        held here before this path existed, or the batch deadline passed while it waited."""
        snapshot, evidence, verdict, ran, ran_on = before
        step, feedback, in_extension = ran
        diagnosed = [h for h in self.history if h["seq"] == self.seq - 1 and h["step"] == step.name]
        if not (ran_on is not None and factory_bug_rerunnable(step.name, diagnosed)
                and DBOS.patch("factory_bug_release_wait")):
            return None
        diagnosis = Step(StepKind.DIAGNOSIS).name
        diagnosis_attempt = max(h["attempt"] for h in self.history if h["seq"] == self.seq and h["step"] == diagnosis)
        if not self.wait_for_fix(ran_on, f"{self.seq}/{diagnosis_attempt}"):
            return None
        self.renumber.setdefault(self.seq, {})[diagnosis] = diagnosis_attempt
        self.renumber.setdefault(self.seq - 1, {})[step.name] = max(h["attempt"] for h in diagnosed)
        book_waste_step([f"{self.case_id}/{self.seq - 1}/{step.name}/{h['attempt']}" for h in diagnosed])
        # The diagnosis seq of every resume on this workflow's path, replayed ones included: a later
        # --resume-case counts those it will not replay (_resume_point), so the cap holds across batches.
        self.rerun_seqs.append(self.seq)
        DBOS.set_event("factory_bug_rerun_seqs", list(self.rerun_seqs))
        self.snapshot, self.evidence, self.in_extension, self.verdict = snapshot, evidence, in_extension, verdict
        self.diagnoses_used -= 1
        self.factory_bug_resumes += 1
        self.bench = self.current("bench")   # GATES adopts it anyway; writer and stress steps too
        self.seq -= 2                        # run_seq numbers the rerun at the diagnosed seq
        return step.kind.value, feedback

    def wait_for_fix(self, failed: tuple, hold: str) -> bool:
        """Park without a worker until the batch's (plumbing, bench) differs from `failed`, the
        releases the diagnosed step ran on, or an operator sends Engine.resume_held for this hold
        (`hold`: diagnosis seq/attempt; a resume left over from an earlier hold is ignored). Never
        on the same releases by itself, so it cannot loop on the same bug. Either release counts,
        whatever the step: a writer or stress step runs on the bench image too (86b100's writer
        crashed on its old bench on 11 November), so a release that fixes nothing costs one of the
        lineage's resumes. False: the batch deadline passed first."""
        if self.replaying:
            return True   # the recorded workflow went on past this hold: it resumed here
        self.release_worker()
        self.status = "held_for_release"
        DBOS.set_event("release_hold", hold)
        self.card()
        while True:
            now = now_step()
            if now >= self.spec.deadline_epoch:
                DBOS.set_event("release_hold", None)
                return False
            if (self.current("plumbing"), self.current("bench")) != failed:
                break
            self.tell("waiting")
            msg = DBOS.recv(WAKE, timeout_seconds=max(0.001, min(_RT.timing.wake_poll_s,
                                                                 self.spec.deadline_epoch - now)))
            if isinstance(msg, dict) and msg.get("kind") == "resume" and msg.get("hold") == hold:
                break
        DBOS.set_event("release_hold", None)
        self.status = "running"
        self.card()
        return True

    def escalate(self) -> Ref:
        """Park until a FOUNDER_REPLY. CONTINUE returns the ruling for the rerun; RETIRE retires."""
        if self.replaying:
            return None   # the rerun that followed the founder's reply is recorded; RETIRE is never resumable
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
    resume = job.get("resume")
    if resume is not None:
        case.workflow_id = DBOS.workflow_id
        case.resume_seq = resume["seq"]
        case.skip = {int(seq): attempt for seq, attempt in resume["skip"].items()}
        # Earlier factory_bug resumes of this lineage: their diagnoses are no longer replayed.
        case.lineage_factory_bug_resumes = resume.get("factory_bug_resumes", 0)
        case.renumber = {int(seq): steps for seq, steps in resume.get("renumber", {}).items()}
        if resume.get("recertify_repair") is True:
            case.recertify_repair_seq = resume.get("recertify_repair_seq", resume["seq"] - 1)
        if resume.get("attack_cap_from") is not None:
            case.attack_cap_from = resume["attack_cap_from"]
            DBOS.set_event("attack_cap_from", case.attack_cap_from)
        case.override = resume.get("override")
    if job.get("import_snapshot") is not None:
        # A legacy import: ADMIT's first attempt restores the rewrapped old checkpoint.
        case.snapshot = Ref(**job["import_snapshot"])
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
    def __init__(self, spec: BatchSpec, initial_registry: dict, import_snapshot: Optional[dict] = None,
                 resume: Optional[dict] = None):
        self.spec, self.initial_registry = spec, initial_registry
        self.import_snapshot = import_snapshot
        self.resume = resume
        self.cases: list = []      # workflow IDs: a resumed case runs as "<case>@<batch>"
        self.case_ids: dict = {}   # workflow ID -> case ID, where they differ
        self.done: dict = {}
        self.sealed: list = []
        self.waiting: list = []
        self.missed: set = set()   # cases that were mid-attempt when a wake went out
        self.blocking_waits = False  # set once in run(): False when replaying an older batch
        self.replaced: list = []
        self.admission_stopped = False

    def admission_open(self) -> bool:
        return (not self.admission_stopped and len(self.sealed) < self.spec.target_sealed
                and now_step() < self.spec.deadline_epoch)

    def start_case(self, replacement_of: Optional[str]) -> None:
        case_id = workflow_id = case_id_for(self.spec.batch_id, len(self.cases) + 1)
        job = {"spec": to_record(self.spec), "case_id": case_id, "initial_registry": self.initial_registry,
               "replacement_of": replacement_of}
        if self.import_snapshot is not None and not self.cases:
            job["import_snapshot"] = self.import_snapshot   # only the first case; replacements select afresh
        if self.resume is not None and not self.cases:
            # Only the first case; replacements select afresh.
            case_id = job["case_id"] = self.resume["case"]
            workflow_id = f"{case_id}@{self.spec.batch_id}"
            job["resume"] = {"seq": self.resume["seq"], "skip": self.resume["skip"],
                             "factory_bug_resumes": self.resume.get("factory_bug_resumes", 0),
                             "renumber": self.resume.get("renumber", {})}
            if self.resume.get("recertify_repair") is True:   # absent otherwise: older jobs replay unchanged
                job["resume"]["recertify_repair"] = True
                job["resume"]["recertify_repair_seq"] = self.resume.get("recertify_repair_seq",
                                                                        self.resume["seq"] - 1)
            if self.resume.get("attack_cap_from") is not None:
                job["resume"]["attack_cap_from"] = self.resume["attack_cap_from"]
            if self.resume.get("override") is not None:   # absent otherwise: older jobs replay unchanged
                job["resume"]["override"] = self.resume["override"]
            self.case_ids[workflow_id] = case_id
        with SetWorkflowID(workflow_id):
            DBOS.start_workflow(case_workflow, job)
        self.cases.append(workflow_id)
        DBOS.set_event("cases", list(self.cases))

    def wake_waiting(self, settled_by: Optional[str] = None) -> None:
        """Wake every waiting case, except the one whose own settle this is."""
        if self.blocking_waits:
            # A case between its reserve and its "waiting" would miss this wake and, now that a
            # bound wait blocks, could wait forever. It gets the wake when it next waits.
            self.missed.update(c for c in self.cases
                               if c not in self.done and c not in self.waiting and c != settled_by)
        else:
            settled_by = None
        for case_id in self.waiting:
            if case_id != settled_by:
                DBOS.send(case_id, {"kind": "wake"}, topic=WAKE)
        self.waiting = [c for c in self.waiting if c == settled_by]

    def handle(self, msg: dict) -> None:
        kind, case_id = msg.get("kind"), msg.get("case")
        if kind == "settled":
            if not (msg.get("unstarted") and self.blocking_waits):
                self.wake_waiting(settled_by=case_id)
        elif kind == "waiting":
            if case_id in self.missed and self.blocking_waits:
                self.missed.discard(case_id)
                DBOS.send(case_id, {"kind": "wake"}, topic=WAKE)
            elif case_id not in self.waiting and case_id not in self.done:
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
                self.sealed.append({"case_id": self.case_ids.get(case_id, case_id), **msg["sealed"]})
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
                        if DBOS.patch('admission_release_recovery'):
                            self.wake_waiting()
                    elif topic is Topic.BENCH_RELEASE:
                        DBOS.set_event("bench", BenchRelease(**msg).bench_version)
                        if DBOS.patch("bench_release_wakes"):
                            self.wake_waiting()   # a case held for a release (wait_for_fix) may resume on it
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
        self.blocking_waits = DBOS.patch("bound_wait_blocks")
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
                    self.sealed.append({"case_id": self.case_ids.get(case_id, case_id), **seal})
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

    def wake_waiting(self, settled_by: Optional[str] = None) -> None:
        self.wake_generation += 1
        for pending in self.pending_cases.values():
            if pending["state"] == "waiting":
                pending["state"], pending["retry_at"] = "eligible", None
        super().wake_waiting(settled_by)

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
        batch = _Batch(spec, job["initial_registry"], job.get("import_snapshot"), job.get("resume"))
    return batch.run()


# ---- the engine process --------------------------------------------------------------------------

class Engine:
    """Construct, check, launch, register queues, then attach to or start batches."""

    def __init__(self, *, system_database_url: str, executor: Executor, timing: Timing = Timing(),
                 environ: Optional[Mapping[str, str]] = None, pool_size: int = 40,
                 admission_paused=lambda: False):
        self.url, self.executor, self.timing = system_database_url, executor, timing
        self.admission_paused = admission_paused
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
        _RT.executor, _RT.timing, _RT.admission_paused = self.executor, self.timing, self.admission_paused
        _RT.draining.clear()
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

    def factory_bug_waste_keys(self, case_id: str, override: Optional[str] = None) -> list:
        """See the module function: what a resume of this case books as waste first."""
        return factory_bug_waste_keys(case_id, override)

    def start_batch(self, spec: BatchSpec, initial_registry: Ref, import_snapshot: Optional[Ref] = None,
                    resume_of: Optional[str] = None, override: Optional[str] = None):
        """Attach to the batch if it exists (rule 3); start it otherwise. initial_registry is the
        batch's first STATEMENT_REGISTRY (BatchSpec has none; contract finding 2). import_snapshot,
        a CASE_SNAPSHOT of the batch's first case, imports a legacy checkpoint as that case.
        resume_of, a case stopped by an infrastructure failure, continues it as the batch's first
        case where it stopped (resume_point). override, the operator's reason, resumes it once where
        resume_point's rules refuse it (founder 2026-11-11)."""
        if not isinstance(initial_registry, Ref) or initial_registry.kind is not ArtifactKind.STATEMENT_REGISTRY:
            raise ContractError("initial_registry must be a registry Ref")
        if import_snapshot is not None and (not isinstance(import_snapshot, Ref)
                                            or import_snapshot.kind is not ArtifactKind.CASE_SNAPSHOT):
            raise ContractError("import_snapshot must be a case snapshot Ref")
        self.register_queues(spec)
        if DBOS.get_workflow_status(spec.batch_id) is not None:
            return DBOS.retrieve_workflow(spec.batch_id)
        if resume_of is not None and import_snapshot is not None:
            raise ContractError("a batch either imports or resumes its first case")
        if override is not None and resume_of is None:
            raise ContractError("an override only resumes a case")
        resume = None if resume_of is None else {"case": resume_of, **resume_point(resume_of, override)}
        with SetWorkflowID(spec.batch_id):
            job = {"spec": to_record(spec), "initial_registry": to_record(initial_registry), "queue_v2": False}
            if import_snapshot is not None:
                job["import_snapshot"] = to_record(import_snapshot)
            if resume is not None:
                job["resume"] = resume
            return DBOS.start_workflow(batch_workflow, job)

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

    def resume_held(self, case_workflow_id: str) -> bool:
        """An operator's go-ahead for a case held for a factory release (status held_for_release):
        it reruns its diagnosed step on the current releases, counted like any factory_bug resume.
        False, and nothing sent, when the case is not waiting so: a stale resume must not later
        free a hold that no release fixed, and the message names its hold."""
        hold = DBOS.get_event(case_workflow_id, "release_hold", timeout_seconds=0)
        if not isinstance(hold, str):
            return False
        DBOS.send(case_workflow_id, {"kind": "resume", "hold": hold}, topic=WAKE)   # wait_for_fix matches the hold
        return True

    def in_flight(self) -> int:
        """Attempts that have started and not yet recorded their result."""
        with _RT.lock:
            return _RT.busy - _RT.parked - _RT.gated

    def drain(self, timeout_s: float) -> None:
        """Start nothing new, and let attempts in flight record or reach a point a restart can
        resume, for at most timeout_s. The caller then ends the process: DBOS.destroy would leave
        workflow threads alive, and one failing just then could record a false terminal error."""
        _RT.draining.set()
        until = time.monotonic() + timeout_s
        while self.in_flight() > 0 and time.monotonic() < until:
            time.sleep(0.05)

    def shutdown(self) -> None:
        DBOS.destroy()
        _RT.executor = None
