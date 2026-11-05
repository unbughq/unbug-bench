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

from durable.contract import (ArtifactKind as K, BatchSpec, ContractError, Outcome, Ref, Step, StepKind,
                              StepResult, Verdict)
from durable.policy import Action, Counters, decide, decide_diagnosis, progressed, starts_replacement

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
        for a in (Action.ADVANCE, Action.RETRY, Action.SLEEP, Action.REPAIR, Action.EXTEND, Action.STOP_ADMISSION):
            self.assertFalse(self.r(a))

    def test_bounded_by_cases_started_and_admission(self):
        self.assertFalse(self.r(Action.RETIRE, cases=4))
        self.assertFalse(self.r(Action.RETIRE, open_=False))


if __name__ == "__main__":
    unittest.main()
