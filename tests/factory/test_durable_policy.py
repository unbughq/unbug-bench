"""Case policy (WP1-owned, factory/durable/policy.py): ENGINEERING section 3 as code.

Design reviews 1 and 2 of docs/designs/durable-execution.md: diagnosis, extensions and
factory-bug limits are enforced in code, a diagnosis is never diagnosed, a case starts at
most one replacement, and an admission that cannot finish stops admission.
"""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory")]
os.environ.setdefault("BENCH", str(ROOT))

from durable.contract import (ArtifactKind as K, BatchSpec, ContractError, Grant, LimitedBy, Outcome, Ref, Step,
                              StepKind, StepResult, Usage, Verdict)
from durable.policy import (Action, Counters, decide, decide_diagnosis, draws_case_money, progressed,
                            settles_as_waste, starts_replacement)

A = "a" * 64


def ref(kind=K.CASE_SNAPSHOT):
    return Ref(A, kind)


SPEC = BatchSpec(batch_id="b-pilot", plumbing_version=A, bench_version=A, app_repo="medusajs/medusa",
                 app_commit="c" * 40, inputs=ref(K.INPUTS), target_sealed=5, money_bound_usd_micros=1,
                 deadline_epoch=2e9, max_cases_started=4)
GATES, STRESS, DIAG, ADMIT = Step(StepKind.GATES, 1), Step(StepKind.STRESS, 1), Step(StepKind.DIAGNOSIS), Step(StepKind.ADMIT)
FB = ref(K.WRITER_FEEDBACK)


def d(step, result, **counts):
    return decide(step, result, Counters(**counts), SPEC)


class Decide(unittest.TestCase):
    def test_table(self):
        self.assertIs(d(GATES, StepResult(Outcome.OK, "g11:pass", snapshot=ref())), Action.ADVANCE)
        self.assertIs(d(STRESS, StepResult(Outcome.OK, "stress:clean", snapshot=ref())), Action.ADVANCE)
        found = StepResult(Outcome.OK, "stress:findings", snapshot=ref(), feedback=FB)
        self.assertIs(d(STRESS, found, writer_rounds_used=7), Action.REPAIR)
        self.assertIs(d(STRESS, found, writer_rounds_used=8), Action.DIAGNOSE)
        limit = StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", retry_at=1.0)
        self.assertIs(d(GATES, limit, step_spent_limits=50), Action.SLEEP)
        self.assertIs(d(GATES, limit, step_spent_limits=51), Action.DIAGNOSE)
        infra = StepResult(Outcome.INFRA_ERROR, "infra:stalled")
        self.assertIs(d(GATES, infra, step_infra_errors=5), Action.RETRY)
        self.assertIs(d(GATES, infra, step_infra_errors=6), Action.DIAGNOSE)
        rep = StepResult(Outcome.GATE_FAILED, "g4:not_real", gate="G4", feedback=FB, repairable=True)
        self.assertIs(d(GATES, rep, writer_rounds_used=7), Action.REPAIR)
        self.assertIs(d(GATES, rep, writer_rounds_used=8), Action.DIAGNOSE)
        self.assertIs(d(GATES, StepResult(Outcome.GATE_FAILED, "g2:public_fix", gate="G2")), Action.RETIRE)
        self.assertIs(d(GATES, StepResult(Outcome.EXHAUSTED, "writer:money")), Action.DIAGNOSE)
        self.assertIs(d(GATES, StepResult(Outcome.NEEDS_FOUNDER, "g16:split_review", gate="G16")), Action.ESCALATE)

    def test_an_extension_never_repairs(self):
        rep = StepResult(Outcome.GATE_FAILED, "g4:not_real", gate="G4", feedback=FB, repairable=True)
        self.assertIs(d(GATES, rep, writer_rounds_used=3, extensions_used=1, in_extension=True), Action.DIAGNOSE)
        found = StepResult(Outcome.OK, "stress:findings", snapshot=ref(), feedback=FB)
        self.assertIs(d(STRESS, found, writer_rounds_used=3, in_extension=True), Action.DIAGNOSE)

    def test_batch_money_waits_case_money_diagnoses(self):
        spent = StepResult(Outcome.EXHAUSTED, "writer:money", Usage(paid_usd_micros=7))
        self.assertIs(decide(GATES, spent, Counters(), SPEC, grant=Grant(7, LimitedBy.BATCH)), Action.WAIT_FOR_BOUND)
        self.assertIs(decide(GATES, spent, Counters(), SPEC, grant=Grant(7, LimitedBy.CASE)), Action.DIAGNOSE)
        self.assertIs(decide(GATES, spent, Counters(), SPEC), Action.DIAGNOSE)
        # A round limit under a batch-limited grant is not a money wait (review 4, N1).
        rounds = StepResult(Outcome.EXHAUSTED, "writer:rounds", Usage(paid_usd_micros=2))
        self.assertIs(decide(GATES, rounds, Counters(), SPEC, grant=Grant(7, LimitedBy.BATCH)), Action.DIAGNOSE)

    def test_diagnosis_and_extensions_never_draw_case_money(self):
        # Review 4, finding 1: a case that ran out of its own money still gets its
        # diagnosis and extension, paid from the batch bound.
        out_of_money = StepResult(Outcome.EXHAUSTED, "writer:money", Usage(paid_usd_micros=5))
        self.assertIs(decide(GATES, out_of_money, Counters(), SPEC, grant=Grant(5, LimitedBy.CASE)), Action.DIAGNOSE)
        self.assertFalse(draws_case_money(DIAG, Counters()))
        self.assertFalse(draws_case_money(Step(StepKind.WRITER, 4), Counters(in_extension=True)))
        self.assertTrue(draws_case_money(Step(StepKind.WRITER, 4), Counters()))

    def test_after_a_diagnosis_nothing_draws_case_money(self):
        # Review 5, N2: the SEAL or GATES rerun after an extension must not need spent case money.
        self.assertFalse(draws_case_money(Step(StepKind.SEAL), Counters(diagnoses_used=1)))
        self.assertFalse(draws_case_money(GATES, Counters(diagnoses_used=1)))

    def test_a_batch_only_step_that_outgrows_its_grant_retries(self):
        # Review 5, N3: a diagnosis or extension that spends its whole grant is plumbing, not a result.
        spent = StepResult(Outcome.EXHAUSTED, "diagnosis:money", Usage(paid_usd_micros=9))
        self.assertIs(decide(DIAG, spent, Counters(), SPEC, grant=Grant(9, LimitedBy.NOTHING)), Action.RETRY)
        self.assertIs(decide(GATES, spent, Counters(in_extension=True, extensions_used=1), SPEC,
                             grant=Grant(9, LimitedBy.NOTHING)), Action.RETRY)
        self.assertIs(decide(DIAG, spent, Counters(), SPEC, grant=Grant(9, LimitedBy.BATCH)), Action.WAIT_FOR_BOUND)
        # A zero grant never counts as used up, so it cannot loop.
        none = StepResult(Outcome.EXHAUSTED, "diagnosis:money")
        self.assertIs(decide(DIAG, none, Counters(), SPEC, grant=Grant(0, LimitedBy.BATCH)), Action.RETIRE)

    def test_broken_runs_settle_as_waste(self):
        self.assertTrue(settles_as_waste(StepResult(Outcome.INFRA_ERROR, "infra:attempt_busy", Usage(paid_usd_micros=3))))
        self.assertTrue(settles_as_waste(StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", Usage(paid_usd_micros=3), retry_at=1.0)))
        self.assertFalse(settles_as_waste(StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", retry_at=1.0)))
        self.assertFalse(settles_as_waste(StepResult(Outcome.OK, "g1:pass", Usage(paid_usd_micros=3), snapshot=ref())))
        self.assertFalse(settles_as_waste(StepResult(Outcome.EXHAUSTED, "writer:money", Usage(paid_usd_micros=3))))

    def test_free_limits_never_end_a_case(self):
        limit = StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", retry_at=1.0)
        self.assertIs(d(GATES, limit), Action.SLEEP)

    def test_a_diagnosis_is_never_diagnosed(self):
        for r, counts in ((StepResult(Outcome.INFRA_ERROR, "diagnosis:malformed"), dict(step_infra_errors=6)),
                          (StepResult(Outcome.EXHAUSTED, "diagnosis:money"), {}),
                          (StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", retry_at=1.0), dict(step_spent_limits=51))):
            self.assertIs(d(DIAG, r, **counts), Action.RETIRE)
        self.assertIs(d(DIAG, StepResult(Outcome.INFRA_ERROR, "diagnosis:malformed"), step_infra_errors=1), Action.RETRY)
        with self.assertRaises(ContractError):
            d(DIAG, StepResult(Outcome.OK, "diagnosis:pass", snapshot=ref(), verdict=Verdict.FACTORY_BUG))

    def test_admission_that_cannot_finish_stops_admission(self):
        self.assertIs(d(ADMIT, StepResult(Outcome.EXHAUSTED, "admit:no_fresh_bug")), Action.STOP_ADMISSION)
        self.assertIs(d(ADMIT, StepResult(Outcome.INFRA_ERROR, "infra:stalled"), step_infra_errors=6), Action.STOP_ADMISSION)

    def test_every_outcome_has_an_action(self):
        samples = {Outcome.OK: dict(snapshot=ref()), Outcome.PROVIDER_LIMIT: dict(retry_at=1.0),
                   Outcome.GATE_FAILED: dict(gate="G5"), Outcome.NEEDS_FOUNDER: dict(gate="G16")}
        for o in Outcome:
            self.assertIsInstance(d(GATES, StepResult(o, "g5:x", **samples.get(o, {}))), Action)


class Diagnosis(unittest.TestCase):
    def dd(self, v, p=False, **c):
        return decide_diagnosis(v, progressed=p, counters=Counters(**c), spec=SPEC)

    def test_limits(self):
        self.assertIs(self.dd(Verdict.FACTORY_BUG, factory_bug_resumes=2), Action.HOLD)
        self.assertIs(self.dd(Verdict.FACTORY_BUG, factory_bug_resumes=3), Action.RETIRE)
        self.assertIs(self.dd(Verdict.CLOSE_TO_PASSING, extensions_used=0), Action.EXTEND)
        self.assertIs(self.dd(Verdict.CLOSE_TO_PASSING, extensions_used=1), Action.RETIRE)
        self.assertIs(self.dd(Verdict.CLOSE_TO_PASSING, True, extensions_used=4), Action.EXTEND)
        self.assertIs(self.dd(Verdict.CLOSE_TO_PASSING, True, extensions_used=5), Action.RETIRE)
        self.assertIs(self.dd(Verdict.NOT_CONVERGING, True), Action.RETIRE)

    def test_progress(self):
        self.assertTrue(progressed(("G1", "G2"), ("G1", "G2", "G3")))
        self.assertFalse(progressed(("G1", "G2"), ("G1", "G2")))
        self.assertFalse(progressed(("G1", "G2"), ("G1", "G3", "G4")))   # G2 broke
        with self.assertRaises(ContractError):
            progressed(("G99",), ())


class Replacements(unittest.TestCase):
    def r(self, action, started=False, cases=1, open_=True):
        return starts_replacement(action, replacement_started=started, cases_started=cases, spec=SPEC, admission_open=open_)

    def test_one_replacement_per_case(self):
        self.assertTrue(self.r(Action.DIAGNOSE))
        # the same case, after its extension fails and is diagnosed again: no second replacement
        self.assertFalse(self.r(Action.DIAGNOSE, started=True))
        self.assertFalse(self.r(Action.RETIRE, started=True))
        for a in (Action.RETIRE, Action.ESCALATE, Action.HOLD):
            self.assertTrue(self.r(a))
        for a in (Action.ADVANCE, Action.RETRY, Action.SLEEP, Action.REPAIR, Action.EXTEND, Action.STOP_ADMISSION,
                  Action.WAIT_FOR_BOUND):
            self.assertFalse(self.r(a))

    def test_bounded_by_cases_started_and_admission(self):
        self.assertFalse(self.r(Action.RETIRE, cases=4))
        self.assertFalse(self.r(Action.RETIRE, open_=False))


if __name__ == "__main__":
    unittest.main()
