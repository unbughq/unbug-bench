"""Durable-execution contract v2: the frozen types every work package builds against.

docs/designs/durable-execution.md. The engine records every step argument, result and
exception, so the contract must refuse case content and round-trip exactly.
"""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin")]
os.environ.setdefault("BENCH", str(ROOT))

from durable.contract import (GATES, STARTS_REPLACEMENT, Action, ArtifactKind, BatchSpec, ContractError, Counters,
                              Outcome, Ref, SealedCase, Step, StepInput, StepKind, StepResult, Usage, Verdict,
                              assert_no_conductor, batch_spec_from_record, check_result_for, decide,
                              decide_diagnosis, guarded_run, progressed, step_input_from_record,
                              step_result_from_record, to_record, wait_seconds)

A, B, C = "a" * 64, "b" * 64, "c" * 64
K = ArtifactKind


def ref(kind=K.CASE_SNAPSHOT, d=A):
    return Ref(d, kind)


def spec(**kw):
    base = dict(batch_id="b-pilot", plumbing_version=A, bench_version=B, app_repo="medusajs/medusa",
                app_commit="c" * 40, inputs=ref(K.INPUTS), target_sealed=5,
                money_bound_usd_micros=50_000_000, deadline_epoch=2_000_000_000.0)
    return BatchSpec(**{**base, **kw})


def step_input(step=None, **kw):
    step = step or Step(StepKind.GATE, "G1")
    base = dict(batch_id="b-pilot", case_id="case-x1", seq=7, step=step, attempt=1, plumbing_version=A,
                bench_version=B, snapshot=ref(), deadline_s=3600.0, money_ceiling_usd_micros=2_000_000)
    return StepInput(**{**base, **kw})


GATE = Step(StepKind.GATE, "G5")
STRESS = Step(StepKind.STRESS, round=1)
DIAG = Step(StepKind.DIAGNOSIS)


class GateOrder(unittest.TestCase):
    def test_matches_runner(self):
        import run
        self.assertEqual(GATES, tuple(run.GATES))
        self.assertNotIn("G12", GATES)  # sealing is the SEAL step


class NoCaseContent(unittest.TestCase):
    def test_reason_grammar(self):
        for bad in ("The bug is in reserveInventory", "g5:src/modules/inventory/reserve.ts", "g5:reserve.ts",
                    "g5:order_42", "pass", "opencode_error", "g18:x", "G5:pass", "g5:" + "x" * 33, "g5:"):
            with self.assertRaises(ContractError, msg=bad):
                StepResult(Outcome.INFRA_ERROR, bad)
        for good in ("router:opencode_error", "g5:reference_unsolved", "g17:pass", "engine:executor_raised"):
            StepResult(Outcome.INFRA_ERROR, good)

    def test_refs_are_keyed_digests_of_a_known_kind(self):
        with self.assertRaises(ContractError):
            Ref("not-a-digest", K.CASE_SNAPSHOT)
        with self.assertRaises(ContractError):
            Ref(A, "promise-text")

    def test_record_holds_only_codes_digests_and_numbers(self):
        r = StepResult(Outcome.GATE_FAILED, "g5:reference_unsolved", Usage(3, 10, 2_000_000), snapshot=ref(),
                       receipt=ref(K.GATE_RECEIPT, B), feedback=ref(K.WRITER_FEEDBACK, C), repairable=True)
        strings = []
        def walk(v):
            if isinstance(v, dict): [walk(x) for x in v.values()]
            elif isinstance(v, str): strings.append(v)
        walk(json.loads(json.dumps(to_record(r))))
        allowed = {o.value for o in Outcome} | {k.value for k in K} | {A, B, C, "g5:reference_unsolved"}
        self.assertTrue(set(strings) <= allowed, set(strings) - allowed)

    def test_executor_exceptions_never_reach_the_engine(self):
        class Leaky:
            def run(self, si):
                raise RuntimeError("patch for src/modules/inventory/reserve.ts failed: <case content>")
        r = guarded_run(Leaky(), step_input())
        self.assertEqual((r.outcome, r.reason), (Outcome.INFRA_ERROR, "engine:executor_raised"))
        self.assertNotIn("reserve", json.dumps(to_record(r)))
        class Wrong:
            def run(self, si):
                return {"outcome": "ok"}
        self.assertEqual(guarded_run(Wrong(), step_input()).reason, "engine:executor_bad_result")
        class Misfit:  # a passing gate with feedback breaks check_result_for
            def run(self, si):
                return StepResult(Outcome.OK, "g1:pass", snapshot=ref(), feedback=ref(K.WRITER_FEEDBACK))
        self.assertEqual(guarded_run(Misfit(), step_input()).reason, "engine:executor_bad_result")

    def test_conductor_is_refused(self):
        assert_no_conductor({"PATH": "/bin"}, {"name": "factory"})
        for env in ({"DBOS__CONDUCTOR_KEY": "k"}, {"dbos__conductor_url": "u"}):
            with self.assertRaises(ContractError):
                assert_no_conductor(env, {})
        with self.assertRaises(ContractError):
            assert_no_conductor({}, {"conductor_key": "k"})


class Shapes(unittest.TestCase):
    def test_outcome_requirements(self):
        bad = [dict(outcome=Outcome.OK, reason="g1:pass"),                                    # no snapshot
               dict(outcome=Outcome.PROVIDER_LIMIT, reason="router:claude_limit"),            # no retry_at
               dict(outcome=Outcome.PROVIDER_LIMIT, reason="router:claude_limit", retry_at=float("inf")),
               dict(outcome=Outcome.GATE_FAILED, reason="g4:not_real", repairable=True),      # no feedback
               dict(outcome=Outcome.INFRA_ERROR, reason="infra:stalled", feedback=ref(K.WRITER_FEEDBACK)),
               dict(outcome=Outcome.OK, reason="g1:pass", snapshot=ref(), retry_at=5.0),
               dict(outcome=Outcome.OK, reason="g1:pass", snapshot=ref(K.GATE_RECEIPT)),     # wrong kind
               dict(outcome=Outcome.GATE_FAILED, reason="g4:x", receipt=ref(K.DIAGNOSTIC)),
               dict(outcome=Outcome.INFRA_ERROR, reason="infra:x", verdict=Verdict.FACTORY_BUG),
               dict(outcome=Outcome.INFRA_ERROR, reason="infra:x", repairable=1)]
        for kw in bad:
            with self.assertRaises(ContractError, msg=kw):
                StepResult(**kw)

    def test_rules_that_depend_on_the_step(self):
        ok = lambda **kw: StepResult(Outcome.OK, "g1:pass", snapshot=ref(), **kw)
        check_result_for(STRESS, ok(feedback=ref(K.WRITER_FEEDBACK)))                    # stress findings
        for step, result in ((GATE, ok(feedback=ref(K.WRITER_FEEDBACK))),                 # passing gate + feedback
                             (Step(StepKind.WRITER, round=1), ok(feedback=ref(K.WRITER_FEEDBACK))),
                             (GATE, ok(verdict=Verdict.FACTORY_BUG)),
                             (DIAG, ok()),                                                # diagnosis needs a verdict
                             (STRESS, StepResult(Outcome.GATE_FAILED, "stress:x"))):
            with self.assertRaises(ContractError, msg=(step, result)):
                check_result_for(step, result)

    def test_steps(self):
        self.assertEqual(Step(StepKind.GATE, "G16").name, "gate:G16")
        self.assertEqual(Step(StepKind.WRITER, round=2).name, "writer:2")
        self.assertEqual(Step(StepKind.DIAGNOSIS).name, "diagnosis")
        for bad in (dict(kind=StepKind.GATE), dict(kind=StepKind.GATE, gate="G12"), dict(kind=StepKind.WRITER),
                    dict(kind=StepKind.SEAL, round=1), dict(kind=StepKind.ADMIT, gate="G1"), dict(kind="rescue")):
            with self.assertRaises(ContractError, msg=bad):
                Step(**bad)

    def test_step_input(self):
        si = step_input()
        self.assertEqual(si.idempotency_key, "case-x1/7/gate:G1/1")
        admit = dict(step=Step(StepKind.ADMIT), snapshot=None)
        step_input(**admit, registry=ref(K.STATEMENT_REGISTRY))
        for kw in (dict(**admit),                                                # admit needs the registry
                   dict(step=Step(StepKind.ADMIT), registry=ref(K.STATEMENT_REGISTRY)),   # admit has no snapshot
                   dict(registry=ref(K.STATEMENT_REGISTRY)),                     # registry only for admit
                   dict(feedback=ref(K.WRITER_FEEDBACK)),                        # feedback only for writer
                   dict(step=Step(StepKind.WRITER, round=1), feedback=ref(K.GATE_RECEIPT)),
                   dict(snapshot=ref(K.SEALED_ARCHIVE)), dict(step="gate:G1"), dict(seq=0),
                   dict(deadline_s=0), dict(deadline_s=float("inf")), dict(money_ceiling_usd_micros=-1),
                   dict(plumbing_version="v2")):
            with self.assertRaises(ContractError, msg=kw):
                step_input(**kw)

    def test_keys_never_collide_across_repairs(self):
        # The same gate, attempt 1, before and after a repair: seq differs, so the key differs.
        first = step_input(seq=5, snapshot=ref(d=A))
        after_repair = step_input(seq=19, snapshot=ref(d=B))
        self.assertNotEqual(first.idempotency_key, after_repair.idempotency_key)

    def test_spec_and_output(self):
        spec()
        for bad in (dict(target_sealed=0), dict(app_commit="main"), dict(inputs=ref()), dict(inputs=None),
                    dict(deadline_epoch=float("nan")), dict(max_extensions=-1), dict(step_deadline_s=0)):
            with self.assertRaises(ContractError, msg=bad):
                spec(**bad)
        SealedCase("case-x1", ref(K.SEALED_ARCHIVE), hard=False)
        with self.assertRaises(ContractError):
            SealedCase("case-x1", ref(), hard=False)

    def test_wait_is_always_recorded(self):
        self.assertEqual(wait_seconds(100.0, 40.0), 60.0)
        self.assertEqual(wait_seconds(100.0, 500.0), 0.001)   # DBOS skips sleep(<=0) without recording it


class RoundTrip(unittest.TestCase):
    def test_exact(self):
        for r in (StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", Usage(1, 0, 5), retry_at=1_800_000_000.5),
                  StepResult(Outcome.OK, "diagnosis:pass", snapshot=ref(), verdict=Verdict.CLOSE_TO_PASSING,
                             report=ref(K.DIAGNOSIS_REPORT, C))):
            self.assertEqual(step_result_from_record(json.loads(json.dumps(to_record(r)))), r)
        for si in (step_input(step=Step(StepKind.WRITER, round=3), feedback=ref(K.WRITER_FEEDBACK, B)),
                   step_input(step=Step(StepKind.ADMIT), snapshot=None, registry=ref(K.STATEMENT_REGISTRY))):
            self.assertEqual(step_input_from_record(json.loads(json.dumps(to_record(si)))), si)
        s = spec(max_concurrency=3)
        self.assertEqual(batch_spec_from_record(json.loads(json.dumps(to_record(s)))), s)

    def test_rejects_extra_fields_at_any_depth(self):
        rec = to_record(StepResult(Outcome.INFRA_ERROR, "infra:stalled"))
        for mutate in (lambda d: d.__setitem__("notes", "the writer said..."),
                       lambda d: d["usage"].__setitem__("notes", "x")):
            d = json.loads(json.dumps(rec)); mutate(d)
            with self.assertRaises(ContractError):
                step_result_from_record(d)
        d = to_record(step_input()); d["snapshot"]["path"] = "/home/case"
        with self.assertRaises(ContractError):
            step_input_from_record(d)


class Policy(unittest.TestCase):
    def d(self, step, result, **counts):
        return decide(step, result, Counters(**counts), spec())

    def test_table(self):
        fb = ref(K.WRITER_FEEDBACK)
        ok = StepResult(Outcome.OK, "g5:pass", snapshot=ref())
        self.assertIs(self.d(GATE, ok), Action.ADVANCE)
        self.assertIs(self.d(STRESS, StepResult(Outcome.OK, "stress:clean", snapshot=ref())), Action.ADVANCE)
        found = StepResult(Outcome.OK, "stress:findings", snapshot=ref(), feedback=fb)
        self.assertIs(self.d(STRESS, found, writer_rounds_used=7), Action.REPAIR)
        self.assertIs(self.d(STRESS, found, writer_rounds_used=8), Action.DIAGNOSE)
        limit = StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", retry_at=1.0)
        self.assertIs(self.d(GATE, limit, step_spent_limits=50), Action.SLEEP)
        self.assertIs(self.d(GATE, limit, step_spent_limits=51), Action.DIAGNOSE)
        infra = StepResult(Outcome.INFRA_ERROR, "infra:stalled")
        self.assertIs(self.d(GATE, infra, step_infra_errors=5), Action.RETRY)
        self.assertIs(self.d(GATE, infra, step_infra_errors=6), Action.DIAGNOSE)
        rep = StepResult(Outcome.GATE_FAILED, "g4:not_real", feedback=fb, repairable=True)
        self.assertIs(self.d(GATE, rep, writer_rounds_used=7), Action.REPAIR)
        self.assertIs(self.d(GATE, rep, writer_rounds_used=8), Action.DIAGNOSE)   # rounds ran out
        self.assertIs(self.d(GATE, StepResult(Outcome.GATE_FAILED, "g2:public_fix")), Action.RETIRE)
        self.assertIs(self.d(GATE, StepResult(Outcome.EXHAUSTED, "writer:money")), Action.DIAGNOSE)
        self.assertIs(self.d(GATE, StepResult(Outcome.NEEDS_FOUNDER, "g16:split_review")), Action.ESCALATE)
        with self.assertRaises(ContractError):
            self.d(DIAG, StepResult(Outcome.OK, "diagnosis:pass", snapshot=ref(), verdict=Verdict.FACTORY_BUG))

    def test_limits_without_spend_never_end_a_case(self):
        # Hundreds of free provider limits on one step only sleep (the Oct 14-20 failure mode).
        limit = StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", retry_at=1.0)
        self.assertIs(self.d(GATE, limit, step_spent_limits=0, step_infra_errors=0), Action.SLEEP)

    def test_diagnosis_limits(self):
        s = spec()
        dd = lambda v, p=False, **c: decide_diagnosis(v, progressed=p, counters=Counters(**c), spec=s)
        self.assertIs(dd(Verdict.FACTORY_BUG, factory_bug_resumes=2), Action.RESUME_AFTER_FIX)
        self.assertIs(dd(Verdict.FACTORY_BUG, factory_bug_resumes=3), Action.RETIRE)
        self.assertIs(dd(Verdict.CLOSE_TO_PASSING, extensions_used=0), Action.EXTEND)          # first needs no progress
        self.assertIs(dd(Verdict.CLOSE_TO_PASSING, extensions_used=1), Action.RETIRE)          # further needs progress
        self.assertIs(dd(Verdict.CLOSE_TO_PASSING, True, extensions_used=4), Action.EXTEND)
        self.assertIs(dd(Verdict.CLOSE_TO_PASSING, True, extensions_used=5), Action.RETIRE)    # at most 5
        self.assertIs(dd(Verdict.NOT_CONVERGING, True), Action.RETIRE)

    def test_progress(self):
        self.assertTrue(progressed(("G1", "G2"), ("G1", "G2", "G3")))
        self.assertFalse(progressed(("G1", "G2"), ("G1", "G2")))
        self.assertFalse(progressed(("G1", "G2"), ("G1", "G3", "G4")))   # G2 broke
        with self.assertRaises(ContractError):
            progressed(("G12",), ())

    def test_replacements(self):
        self.assertEqual(STARTS_REPLACEMENT, {Action.DIAGNOSE, Action.RETIRE, Action.ESCALATE})

    def test_every_outcome_has_an_action(self):
        samples = {Outcome.OK: dict(snapshot=ref()), Outcome.PROVIDER_LIMIT: dict(retry_at=1.0)}
        for o in Outcome:
            self.assertIsInstance(self.d(GATE, StepResult(o, "g5:x", **samples.get(o, {}))), Action)


if __name__ == "__main__":
    unittest.main()
