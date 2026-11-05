"""Durable-execution contract: the frozen types every work package builds against.

docs/designs/durable-execution.md. The engine records every step argument and result,
so the contract must refuse case content and round-trip exactly.
"""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin")]
os.environ.setdefault("BENCH", str(ROOT))

from durable.contract import (GATES, Action, ArtifactKind, BatchSpec, Outcome, Ref, SealedCase, Step,
                              StepInput, StepKind, StepResult, Usage, decide, step_input_from_record,
                              step_result_from_record, to_record)

A = "a" * 64
B = "b" * 64


def ref(kind=ArtifactKind.CASE_SNAPSHOT, sha=A):
    return Ref(sha, kind)


def spec(**kw):
    base = dict(batch_id="b-pilot", release_digest=A, app_repo="medusajs/medusa", app_commit="c" * 40,
                inputs=ref(ArtifactKind.INPUTS), target_sealed=5, money_bound_usd_micros=50_000_000,
                deadline_epoch=2_000_000_000.0)
    return BatchSpec(**{**base, **kw})


class GateOrder(unittest.TestCase):
    def test_matches_runner(self):
        import run
        self.assertEqual(GATES, tuple(run.GATES))
        self.assertNotIn("G12", GATES)  # sealing is the SEAL step


class NoCaseContent(unittest.TestCase):
    def test_reason_must_be_a_code(self):
        for bad in ("The bug is in reserveInventory", "x" * 81, "", "Pass", "a b"):
            with self.assertRaises(ValueError):
                StepResult(Outcome.INFRA_ERROR, bad)
        StepResult(Outcome.INFRA_ERROR, "opencode_error:exit-1")

    def test_refs_are_hashes(self):
        with self.assertRaises(ValueError):
            Ref("not-a-hash", ArtifactKind.CASE_SNAPSHOT)
        with self.assertRaises(ValueError):
            Ref(A, "promise-text")

    def test_record_holds_only_codes_hashes_and_numbers(self):
        r = StepResult(Outcome.GATE_FAILED, "g5:reference_unsolved", Usage(3, 10, 2_000_000), snapshot=ref(),
                       receipt=ref(ArtifactKind.GATE_RECEIPT, B), feedback=ref(ArtifactKind.WRITER_FEEDBACK),
                       repairable=True)
        blob = json.dumps(to_record(r))
        strings = []
        def walk(v):
            if isinstance(v, dict): [walk(x) for x in v.values()]
            elif isinstance(v, str): strings.append(v)
        walk(json.loads(blob))
        allowed = {o.value for o in Outcome} | {k.value for k in ArtifactKind} | {A, B, "g5:reference_unsolved"}
        self.assertTrue(set(strings) <= allowed, set(strings) - allowed)


class Shapes(unittest.TestCase):
    def test_outcome_requirements(self):
        with self.assertRaises(ValueError):
            StepResult(Outcome.OK, "pass")                                  # no snapshot
        with self.assertRaises(ValueError):
            StepResult(Outcome.PROVIDER_LIMIT, "claude_limit")             # no retry_at
        with self.assertRaises(ValueError):
            StepResult(Outcome.PROVIDER_LIMIT, "claude_limit", retry_at=float("inf"))
        with self.assertRaises(ValueError):
            StepResult(Outcome.GATE_FAILED, "g4", repairable=True)          # no feedback
        with self.assertRaises(ValueError):
            StepResult(Outcome.INFRA_ERROR, "stalled", feedback=ref(ArtifactKind.WRITER_FEEDBACK))
        with self.assertRaises(ValueError):
            StepResult(Outcome.OK, "pass", snapshot=ref(), retry_at=5.0)

    def test_steps(self):
        self.assertEqual(Step(StepKind.GATE, "G16").name, "gate:G16")
        self.assertEqual(Step(StepKind.WRITER, round=2).name, "writer:2")
        for bad in (dict(kind=StepKind.GATE), dict(kind=StepKind.GATE, gate="G12"),
                    dict(kind=StepKind.WRITER), dict(kind=StepKind.SEAL, round=1),
                    dict(kind=StepKind.ADMIT, gate="G1")):
            with self.assertRaises(ValueError, msg=bad):
                Step(**bad)

    def test_step_input(self):
        si = StepInput("b-pilot", "case-x1", Step(StepKind.GATE, "G1"), 2, A, ref())
        self.assertEqual(si.idempotency_key, "case-x1/gate:G1/2")
        with self.assertRaises(ValueError):
            StepInput("b-pilot", "case-x1", Step(StepKind.ADMIT), 1, A, ref())   # admit has no snapshot
        with self.assertRaises(ValueError):
            StepInput("b-pilot", "case-x1", Step(StepKind.GATE, "G1"), 1, A, ref(),
                      feedback=ref(ArtifactKind.WRITER_FEEDBACK))

    def test_spec_and_output(self):
        spec()
        for bad in (dict(target_sealed=0), dict(app_commit="main"), dict(inputs=ref()), dict(deadline_epoch=float("nan"))):
            with self.assertRaises(ValueError, msg=bad):
                spec(**bad)
        SealedCase("case-x1", ref(ArtifactKind.SEALED_ARCHIVE), ref(ArtifactKind.SCORECARD), hard=False)
        with self.assertRaises(ValueError):
            SealedCase("case-x1", ref(), ref(ArtifactKind.SCORECARD), hard=False)


class RoundTrip(unittest.TestCase):
    def test_exact(self):
        r = StepResult(Outcome.PROVIDER_LIMIT, "claude:limit", Usage(1, 0, 5), retry_at=1_800_000_000.5)
        self.assertEqual(step_result_from_record(json.loads(json.dumps(to_record(r)))), r)
        si = StepInput("b-pilot", "case-x1", Step(StepKind.WRITER, round=3), 1, A, ref(),
                       feedback=ref(ArtifactKind.WRITER_FEEDBACK, B))
        self.assertEqual(step_input_from_record(json.loads(json.dumps(to_record(si)))), si)

    def test_rejects_extra_fields(self):
        rec = to_record(StepResult(Outcome.INFRA_ERROR, "stalled"))
        rec["notes"] = "the writer said..."
        with self.assertRaises(ValueError):
            step_result_from_record(rec)


class Policy(unittest.TestCase):
    def d(self, result, infra=0, rounds=1, **kw):
        return decide(result, step_infra_errors=infra, writer_rounds_used=rounds, spec=spec(**kw))

    def test_table(self):
        fb = ref(ArtifactKind.WRITER_FEEDBACK)
        self.assertIs(self.d(StepResult(Outcome.OK, "pass", snapshot=ref())), Action.ADVANCE)
        self.assertIs(self.d(StepResult(Outcome.PROVIDER_LIMIT, "limit", retry_at=1.0)), Action.SLEEP)
        self.assertIs(self.d(StepResult(Outcome.INFRA_ERROR, "stalled"), infra=5), Action.RETRY)
        self.assertIs(self.d(StepResult(Outcome.INFRA_ERROR, "stalled"), infra=6), Action.DIAGNOSE)
        self.assertIs(self.d(StepResult(Outcome.GATE_FAILED, "g4", feedback=fb, repairable=True), rounds=5), Action.REPAIR)
        self.assertIs(self.d(StepResult(Outcome.GATE_FAILED, "g4", feedback=fb, repairable=True), rounds=6), Action.RETIRE)
        self.assertIs(self.d(StepResult(Outcome.GATE_FAILED, "g2:public_fix")), Action.RETIRE)
        self.assertIs(self.d(StepResult(Outcome.EXHAUSTED, "money")), Action.RETIRE)
        self.assertIs(self.d(StepResult(Outcome.NEEDS_FOUNDER, "g16:split_review")), Action.ESCALATE)

    def test_limits_never_spend_allowance(self):
        # Hundreds of provider limits on one step still only sleep (the Oct 14-20 failure mode).
        r = StepResult(Outcome.PROVIDER_LIMIT, "limit", retry_at=1.0)
        self.assertIs(self.d(r, infra=10_000), Action.SLEEP)

    def test_every_outcome_has_an_action(self):
        samples = {Outcome.OK: dict(snapshot=ref()), Outcome.PROVIDER_LIMIT: dict(retry_at=1.0)}
        for o in Outcome:
            self.assertIsInstance(self.d(StepResult(o, "x", **samples.get(o, {}))), Action)


if __name__ == "__main__":
    unittest.main()
