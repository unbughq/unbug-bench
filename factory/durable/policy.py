"""Case policy: what the engine does after each finished attempt (ENGINEERING section 3).

Owned by WP1 and not part of the frozen contract: only the engine calls it, so WP1 may
change it through its own design note. Pure: no I/O, no engine import.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

from durable.contract import (BatchSpec, ContractError, Grant, LimitedBy, Outcome, Step, StepKind, StepResult,
                              Verdict, _nonneg_int, check_result_for)


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
    WAIT_FOR_BOUND = "wait_for_bound"  # the batch bound ran out under this attempt: wait for any settle or BOUND_RAISED, then RETRY


@dataclass(frozen=True)
class Counters:
    """Per-case counts the engine derives from the journal, never from a worker."""
    step_infra_errors: int = 0     # INFRA_ERROR attempts of this seq, this one included
    step_spent_limits: int = 0     # PROVIDER_LIMIT attempts of this seq that spent money, this one included
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


def decide(step: Step, result: StepResult, counters: Counters, spec: BatchSpec, *,
           grant: Grant = Grant(0, LimitedBy.NOTHING)) -> Action:
    """grant is the attempt's Grant from Ledger.reserve."""
    check_result_for(step, result)
    k, o = step.kind, result.outcome
    # An extension is exactly one writer round, its stress round and the gates: it never repairs.
    rounds_left = counters.writer_rounds_used < spec.max_writer_rounds and not counters.in_extension

    def give_up():
        # Never diagnose a diagnosis (Stream D: a broken diagnosis is infrastructure, and
        # once its retries are spent the case retires); an admission that cannot finish
        # stops admission instead of chaining replacements.
        if k is StepKind.ADMIT:
            return Action.STOP_ADMISSION
        if k is StepKind.DIAGNOSIS:
            return Action.RETIRE
        return Action.DIAGNOSE

    if o is Outcome.OK:
        if k is StepKind.DIAGNOSIS:
            raise ContractError("route a diagnosis verdict through decide_diagnosis")
        if k is StepKind.STRESS and result.feedback is not None:
            return Action.REPAIR if rounds_left else give_up()
        return Action.ADVANCE
    if o is Outcome.PROVIDER_LIMIT:
        # Waiting spends no allowance; only a run of limits that each spent money (a likely
        # misclassification) gives up.
        return Action.SLEEP if counters.step_spent_limits <= spec.max_spent_limits_per_step else give_up()
    if o is Outcome.INFRA_ERROR:
        return Action.RETRY if counters.step_infra_errors <= spec.max_infra_retries_per_step else give_up()
    if o is Outcome.GATE_FAILED:
        if not result.repairable:
            return Action.RETIRE                  # a scored rejection, e.g. the bug is not fresh
        return Action.REPAIR if rounds_left else give_up()
    if o is Outcome.EXHAUSTED:
        # A zero grant is never "used up": the engine does not start attempts below its minimum
        # grant, and treating $0 as spent would retry forever.
        used_grant = grant.amount_usd_micros > 0 and result.usage.paid_usd_micros >= grant.amount_usd_micros
        if grant.limited_by is LimitedBy.BATCH and used_grant:
            return Action.WAIT_FOR_BOUND          # the batch ran out under it, not the case and not a round limit
        if used_grant and not draws_case_money(step, counters):
            return Action.RETRY                   # a batch-only step outgrew its grant: plumbing, not a case result
        return give_up()
    if o is Outcome.NEEDS_FOUNDER:
        return Action.ESCALATE
    raise AssertionError(o)


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
        return Action.HOLD if counters.factory_bug_resumes < spec.max_factory_bug_resumes else Action.RETIRE
    if verdict is Verdict.CLOSE_TO_PASSING:
        allowed = counters.extensions_used < spec.max_extensions
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
