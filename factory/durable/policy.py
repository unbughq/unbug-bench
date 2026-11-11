"""Case policy: what the engine does after each finished attempt (ENGINEERING section 3).

Owned by WP1 and not part of the frozen contract: only the engine calls it, so WP1 may
change it through its own design note. Pure: no I/O, no engine import.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

from typing import Optional

from durable.contract import (BatchSpec, ContractError, Grant, LimitedBy, Outcome, Step, StepKind, StepResult, Usage,
                              Verdict, _nonneg_int, check_result_for)

# ---- figures settled in docs/designs/durable-execution-wp1.md --------------------------------

# A GATES attempt runs the whole gate pipeline. The slowest observed minutes per gate on the 52
# non-dry-run cards in sealed/ sum to 363 min with G10 serial; 12 h is twice that.
GATES_DEADLINE_S = 43_200.0
# The control side polls until deadline_s plus this, then cancels (the worker kills at deadline_s).
POLL_GRACE_S = 900.0
# Below this an attempt does not start. The cheapest identified writer round is $0.4463424.
MIN_GRANT_USD_MICROS = 1_000_000
# A batch-only step requests at least this: Stream D's ceiling of the largest authenticated CLI
# aggregate observed ($32.6137984). Finite, so one step never holds the whole bound.
BATCH_ONLY_FLOOR_USD_MICROS = 33_000_000
# An operator pause (WP4 classify.py maps PauseRequested and paused to it). Not a fault of
# the step: it retries without using the infra-retry allowance, after the engine's pause wait.
PAUSE_REASONS = frozenset({"infra:paused"})
# WP4 maps the runner's batch-deadline stop (provider_wait_deadline) to
# this code, which a worker's own deadline kill also uses. After deadline_epoch the two cannot be
# told apart; the batch deadline only stops new cases and extensions, so after it such a stop
# retries outside the infra allowance and must not be diagnosed as a case defect.
DEADLINE_REASON = "infra:deadline"
# A writer attempt that stopped between writer calls because the next call and its checks would
# likely outlive the attempt (run.engine_writer_round). Its snapshot holds the findings for the next
# call: the round continues in a new attempt with fresh time. Not a fault, so no infra allowance.
# The engine (run_seq, under the writer_handback_retry patch) retries it, not decide: a workflow that
# recorded ADVANCE for one must replay ADVANCE. Past MAX_WRITER_HANDBACKS per seq (the writer's call
# cap, run.py --rounds) a handback counts as an infra error.
WRITER_HANDBACK = "writer:handback"
MAX_WRITER_HANDBACKS = 8
# A failed worker create or Boat outage waits like a pause, for at most this long in total per seq; after
# that it counts against max_infra_retries_per_step like any infra error. Six hours rides out a provider
# quota or a Boat incident; a bad image or a lasting outage still ends instead of holding the batch.
POOL_WAIT_CEILING_S = 21_600.0
USAGE_STOP_REASONS = frozenset({"infra:usage_unknown", "infra:missing_usage", "infra:unpriced_usage",
                                "infra:usage_monitor", "infra:usage_reservation_exceeded",
                                "infra:reservation_spend_unknown", "infra:reservation_event_missing"})
# How long past its deadline an attempt may stay unconfirmed before its worker is deleted and the
# attempt counts as lost, so a controller recovering an unanswering worker never waits forever.
UNCONFIRMED_WORKER_LIMIT_S = 9000.0
# Results whose usage the engine cannot know: they book the whole grant as waste (settle_lost).
LOST_REASONS = frozenset({"infra:cancelled", "infra:worker_lost", "infra:attempt_absent",
                          "engine:executor_raised", "engine:executor_bad_result"})


class Action(str, Enum):
    ADVANCE = "advance"                # next step, with result.snapshot
    RETRY = "retry"                    # same seq, attempt + 1
    SLEEP = "sleep"                    # DBOS.sleep(wait_seconds(result.retry_at, now())), then RETRY
    REPAIR = "repair"                  # next writer round with result.feedback
    DIAGNOSE = "diagnose"              # run a DIAGNOSIS step
    EXTEND = "extend"                  # one writer round + stress round + gates, with the diagnosis feedback
    HOLD = "hold"                      # factory bug: stop unscored as factory_bug_held (Stream D); a later
                                       # batch release may resume it, up to max_factory_bug_resumes in all
    RETIRE = "retire"                  # stop this case
    ESCALATE = "escalate"              # park and wait for FOUNDER_REPLY
    STOP_ADMISSION = "stop_admission"  # ADMIT cannot find a bug: retire this case and start no new cases
    WAIT_FOR_BOUND = "wait_for_bound"  # usage reached a BATCH grant, or a BATCH grant was below the minimum:
                                       # wait for any settle or BOUND_RAISED, then RETRY
    RERUN_GATES = "rerun_gates"        # a release changed before a queued SEAL could start


@dataclass(frozen=True)
class Counters:
    """Per-case counts the engine derives from the journal, never from a worker."""
    step_infra_errors: int = 0     # INFRA_ERROR attempts of this seq, this one included
    step_spent_limits: int = 0     # PROVIDER_LIMIT attempts of this seq that spent money, this one included
    step_free_limits: int = 0      # PROVIDER_LIMIT attempts of this seq that spent nothing, this one included
    step_deadline_stops: int = 0   # infra:deadline attempts of this seq after the batch deadline, this one included
    writer_rounds_used: int = 0    # ordinary writer rounds; extension rounds are counted separately
    extensions_used: int = 0
    factory_bug_resumes: int = 0   # carried across batches in the case's lineage
    diagnoses_used: int = 0
    in_extension: bool = False     # the step belongs to an extension (one writer round + stress + gates)

    def __post_init__(self):
        for f in fields(self):
            if f.name == "in_extension":
                if type(self.in_extension) is not bool: raise ContractError("in_extension must be a bool")
            else:
                _nonneg_int(getattr(self, f.name), f"Counters.{f.name}")


def is_operational_wait(result: StepResult) -> bool:
    return result.outcome is Outcome.INFRA_ERROR and result.reason in (
        "router:credential_expiring", "infra:credentials_unavailable", "router:unbounded_route",
        "infra:router_unavailable", "router:outage")


def decide(step: Step, result: StepResult, counters: Counters, spec: BatchSpec, *,
           grant: Grant = Grant(0, LimitedBy.NOTHING), now: Optional[float] = None) -> Action:
    """grant is the attempt's Grant from Ledger.reserve. now (from a step) is needed only to
    recognise a batch-deadline stop; without it an infra:deadline counts as an ordinary infra error."""
    check_result_for(step, result)
    k, o = step.kind, result.outcome
    # An extension is exactly one writer round, its stress round and the gates: it never repairs.
    rounds_left = counters.writer_rounds_used < spec.max_writer_rounds and not counters.in_extension

    def give_up():
        return _give_up(k)

    if o is Outcome.OK:
        if k is StepKind.DIAGNOSIS:
            raise ContractError("route a diagnosis verdict through decide_diagnosis")
        if k is StepKind.STRESS and result.feedback is not None:
            return Action.REPAIR if rounds_left else give_up()
        return Action.ADVANCE
    if is_operational_wait(result):
        return Action.RETRY
    if o is Outcome.PROVIDER_LIMIT:
        # A real capacity limit never turns into a case result. The ledger still
        # bounds paid attempts and the batch waits when its bound is exhausted.
        return Action.SLEEP
    if o is Outcome.INFRA_ERROR:
        if is_pause(result):
            return Action.RETRY                   # never scored, never counted, never diagnosed
        if is_batch_deadline_stop(result, spec, now):
            # The batch deadline stops new cases and extensions, not a running case's step.
            return Action.RETRY
        return Action.RETRY if counters.step_infra_errors <= spec.max_infra_retries_per_step else give_up()
    if o is Outcome.GATE_FAILED:
        if not result.repairable:
            return Action.RETIRE                  # a scored rejection, e.g. the bug is not fresh
        return Action.REPAIR if rounds_left else give_up()
    if o is Outcome.EXHAUSTED:
        # A zero grant is never "used up": the engine does not start attempts below its minimum
        # grant, and treating $0 as spent would retry forever.
        money_stop = grant.amount_usd_micros > 0 and is_money_stop(result)
        if grant.limited_by is LimitedBy.BATCH and money_stop:
            # The batch ran out under it, not the case and not a round limit. A money stop counts
            # even below the grant: the runner refuses a call whose route maximum does not fit what
            # is left (budget.py usage_reservation_exceeded), so usage never reaches a grant smaller than one call.
            return Action.WAIT_FOR_BOUND
        if money_stop and not draws_case_money(step, counters):
            return Action.RETRY                   # a batch-only step outgrew its grant: plumbing, not a case result
        return give_up()
    if o is Outcome.NEEDS_FOUNDER:
        return Action.ESCALATE
    raise AssertionError(o)


def _give_up(k: StepKind) -> Action:
    # Never diagnose a diagnosis (Stream D: a broken diagnosis is infrastructure, and once its
    # retries are spent the case retires); an admission that cannot finish stops admission
    # instead of chaining replacements.
    if k is StepKind.ADMIT:
        return Action.STOP_ADMISSION
    if k is StepKind.DIAGNOSIS:
        return Action.RETIRE
    return Action.DIAGNOSE


def request_usd_micros(step: Step, counters: Counters, spec: BatchSpec) -> int:
    """What the engine asks Ledger.reserve for. An ordinary step asks for the case's money and
    the ledger caps it at what is left; a batch-only step asks for a finite figure."""
    if draws_case_money(step, counters):
        return spec.case_money_usd_micros
    return max(spec.case_money_usd_micros, BATCH_ONLY_FLOOR_USD_MICROS)


def decide_grant(step: Step, grant: Grant, *, minimum: int = MIN_GRANT_USD_MICROS) -> Optional[Action]:
    """Before an attempt starts. None: start it. A sub-minimum CASE grant gives up without
    starting, because the case's own money never comes back; a sub-minimum BATCH grant waits
    for a settle or BOUND_RAISED; a NOTHING grant is the whole request and always starts."""
    if grant.amount_usd_micros >= minimum or grant.limited_by is LimitedBy.NOTHING:
        return None
    if grant.limited_by is LimitedBy.BATCH:
        return Action.WAIT_FOR_BOUND
    return _give_up(step.kind)


def deadline_s(step: Step, spec: BatchSpec) -> float:
    """StepInput.deadline_s. GATES runs the whole pipeline, so it gets its own figure."""
    if step.kind is StepKind.GATES:
        return max(spec.step_deadline_s, GATES_DEADLINE_S)
    return spec.step_deadline_s


def is_pause(result: StepResult) -> bool:
    """An operator pause. The engine waits Timing.pause_retry_s, then retries the same seq, and
    does not count it in Counters.step_infra_errors. It still settles as waste."""
    return result.outcome is Outcome.INFRA_ERROR and result.reason in PAUSE_REASONS


def is_batch_deadline_stop(result: StepResult, spec: BatchSpec, now: Optional[float]) -> bool:
    return (result.outcome is Outcome.INFRA_ERROR and result.reason == DEADLINE_REASON and now is not None
            and now >= spec.deadline_epoch)


def is_money_stop(result: StepResult) -> bool:
    """EXHAUSTED because money ran out (WP4: "<stage>:money"), not a round limit."""
    return result.outcome is Outcome.EXHAUSTED and result.reason.split(":", 1)[1] == "money"


def settles_lost(result: StepResult) -> bool:
    """Every infra:cancelled result, and every result the executor made for an attempt whose
    usage it cannot know, settles with settle_lost (design review 5, N6)."""
    return result.reason in LOST_REASONS or (result.reason in USAGE_STOP_REASONS and result.usage == Usage())


def draws_case_money(step: Step, counters: Counters) -> bool:
    """Ordinary steps draw on the case's own money. DIAGNOSIS, extensions, and every step
    after a case's first diagnosis (its SEAL, a GATES rerun) draw on the batch only."""
    return step.kind is not StepKind.DIAGNOSIS and not counters.in_extension and counters.diagnoses_used == 0


def settles_as_waste(result: StepResult) -> bool:
    """Broken runs are booked to the batch's waste line, never to the case's money."""
    return result.outcome is Outcome.INFRA_ERROR or (
        result.outcome is Outcome.PROVIDER_LIMIT and result.usage.paid_usd_micros > 0)


def decide_diagnosis(verdict: Verdict, *, progressed: bool, counters: Counters, spec: BatchSpec) -> Action:
    """What a diagnosis verdict allows. Code enforces the limits; the agent only proposes."""
    verdict = Verdict(verdict)
    if verdict is Verdict.FACTORY_BUG:
        return Action.HOLD if counters.factory_bug_resumes < min(spec.max_factory_bug_resumes, 3) else Action.RETIRE
    if verdict is Verdict.CLOSE_TO_PASSING:
        allowed = counters.extensions_used < min(spec.max_extensions, 5)
        needs_progress = counters.extensions_used >= 1   # a further extension needs progress
        return Action.EXTEND if allowed and (progressed or not needs_progress) else Action.RETIRE
    return Action.RETIRE


ENDS_LINE_OF_WORK = frozenset({Action.DIAGNOSE, Action.RETIRE, Action.ESCALATE, Action.HOLD})


def starts_replacement(action: Action, *, replacement_started: bool, cases_started: int, spec: BatchSpec,
                       admission_open: bool) -> bool:
    """A case starts at most one replacement over its whole life, the first time its own
    line of work stops (the first DIAGNOSE, or a RETIRE, ESCALATE or HOLD without one)."""
    return (action in ENDS_LINE_OF_WORK and not replacement_started and admission_open
            and cases_started < spec.max_cases_started)


def progressed(before: tuple, after: tuple) -> bool:
    """Gates passed before and after an extension. Progress means the case passes at least
    one more gate and nothing it had already passed broke."""
    from durable.contract import GATE
    for g in (*before, *after):
        if not (type(g) is str and GATE.fullmatch(g)):
            raise ContractError(f"unknown gate {g!r} in progress check")
    return set(before) < set(after)
