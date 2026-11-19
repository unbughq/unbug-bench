"""Durable-execution contract v4: the frozen seams every work package builds against.

ARCHITECTURE.md. The engine records every step argument, result and
exception, so the contract must refuse case content and round-trip exactly.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin")]
os.environ.setdefault("BENCH", str(ROOT))

from durable.contract import (RELEASE_MANIFEST, ArtifactKind, BatchSpec, BenchRelease, Classified, Grant, LimitedBy,
                              ContractError, FounderAction, FounderReply, Outcome, Poll, PollState, Ref,
                              SealedCase, Step, StepInput, StepKind, StepResult, Usage, Verdict, artifact_digest,
                              assert_no_conductor, attempt_paths, batch_spec_from_record, check_result_for,
                              derive_keys, guarded_run, hkdf_sha256, key_frame, poll_from_record, start_frame,
                              step_input_from_record, step_result_from_record, to_record, wait_seconds)

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
    base = dict(batch_id="b-pilot", case_id="case-x1", seq=7, step=step or Step(StepKind.GATES, 1), attempt=1,
                plumbing_version=A, bench_version=B, inputs=ref(K.INPUTS), snapshot=ref(), deadline_s=3600.0,
                money_ceiling_usd_micros=2_000_000)
    return StepInput(**{**base, **kw})


GATES = Step(StepKind.GATES, 1)
STRESS = Step(StepKind.STRESS, 1)
DIAG = Step(StepKind.DIAGNOSIS)
ADMIT = Step(StepKind.ADMIT)
SEAL = Step(StepKind.SEAL)


class NoCaseContent(unittest.TestCase):
    def test_reason_grammar(self):
        for bad in ("The bug is in reserveInventory", "g5:src/modules/inventory/reserve.ts", "g5:reserve.ts",
                    "g5:order_42", "pass", "opencode_error", "g18:x", "G5:pass", "g5:" + "x" * 33, "g5:"):
            with self.assertRaises(ContractError, msg=bad):
                StepResult(Outcome.INFRA_ERROR, bad)
        for good in ("router:opencode_error", "g5:reference_unsolved", "g17:pass", "engine:executor_raised"):
            StepResult(Outcome.INFRA_ERROR, good)

    def test_record_holds_only_codes_digests_and_numbers(self):
        r = StepResult(Outcome.GATE_FAILED, "g5:reference_unsolved", Usage(3, 10, 2_000_000), snapshot=ref(),
                       gate="G5", receipt=ref(K.GATE_RECEIPT, B), feedback=ref(K.WRITER_FEEDBACK, C), repairable=True)
        strings = []
        def walk(v):
            if isinstance(v, dict): [walk(x) for x in v.values()]
            elif isinstance(v, list): [walk(x) for x in v]
            elif isinstance(v, str): strings.append(v)
        walk(json.loads(json.dumps(to_record(r))))
        allowed = {o.value for o in Outcome} | {k.value for k in K} | {A, B, C, "g5:reference_unsolved", "G5"}
        self.assertTrue(set(strings) <= allowed, set(strings) - allowed)

    def test_executor_exceptions_never_reach_the_engine(self):
        class Leaky:
            def run(self, si):
                raise RuntimeError("patch for src/modules/inventory/reserve.ts failed: <case content>")
        r = guarded_run(Leaky(), step_input())
        self.assertEqual((r.outcome, r.reason), (Outcome.INFRA_ERROR, "engine:executor_raised"))
        self.assertNotIn("reserve", json.dumps(to_record(r)))
        class Wrong:
            def run(self, si): return {"outcome": "ok"}
        self.assertEqual(guarded_run(Wrong(), step_input()).reason, "engine:executor_bad_result")
        class Misfit:  # a gates step may not return a verdict
            def run(self, si): return StepResult(Outcome.OK, "diagnosis:pass", snapshot=ref(), verdict=Verdict.FACTORY_BUG)
        self.assertEqual(guarded_run(Misfit(), step_input()).reason, "engine:executor_bad_result")

    def test_conductor_is_refused(self):
        assert_no_conductor({"PATH": "/bin"}, {"name": "factory"})
        for env in ({"DBOS__CONDUCTOR_KEY": "k"}, {"dbos__conductor_url": "u"}, {"DBOS__CLOUD": "true"}):
            with self.assertRaises(ContractError):
                assert_no_conductor(env, {})
        with self.assertRaises(ContractError):
            assert_no_conductor({}, {"conductor_key": "k"})


class Keys(unittest.TestCase):
    def test_hkdf_matches_rfc5869_case_1(self):
        ikm = bytes.fromhex("0b" * 22)
        salt = bytes.fromhex("000102030405060708090a0b0c")
        info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
        okm = hkdf_sha256(ikm, info, 42, salt)
        self.assertEqual(okm.hex(), "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
                                    "34007208d5b887185865")

    def test_derived_keys_are_distinct_and_stable(self):
        key = bytes(range(32))
        age, mac = derive_keys(key)
        self.assertEqual((age, mac), derive_keys(key))
        self.assertNotEqual(age, mac)
        self.assertEqual(len(age), 32)
        with self.assertRaises(ContractError):
            derive_keys(b"short")
        d = artifact_digest(mac, b"answer key")
        self.assertEqual(d, hmac.new(mac, b"answer key", hashlib.sha256).hexdigest())
        self.assertNotEqual(d, hashlib.sha256(b"answer key").hexdigest())   # not confirmable without the key
        self.assertNotEqual(d, artifact_digest(derive_keys(bytes(32))[1], b"answer key"))   # scopes differ


class Wire(unittest.TestCase):
    def test_attempt_layout_is_path_safe_and_stable(self):
        si = step_input()
        p = attempt_paths(si.idempotency_key)
        self.assertEqual(p, attempt_paths(si.idempotency_key))
        for v in p.values():
            self.assertNotIn(":", v); self.assertNotIn("case-x1", v)
        self.assertTrue(p["unit"].startswith("durable-") and len(p["unit"]) == 24)
        self.assertNotEqual(p, attempt_paths(step_input(attempt=2).idempotency_key))

    def test_start_frame(self):
        si = step_input()
        frame = start_frame(si, {"case-x1": bytes(32)})
        self.assertEqual(step_input_from_record(json.loads(json.dumps(frame))["input"]), si)
        self.assertEqual(base64.b64decode(frame["keys"]["case-x1"]), bytes(32))
        admit = step_input(step=ADMIT, snapshot=None, registry=ref(K.STATEMENT_REGISTRY))
        start_frame(admit, {"case-x1": bytes(32), "b-pilot": bytes(32)})
        for si_, keys in ((si, {}), (admit, {"case-x1": bytes(32)}), (si, {"case-x1": bytes(32), "case-other": bytes(32)}),
                          (si, {"case-x1": b"short"})):
            with self.assertRaises(ContractError, msg=keys):
                start_frame(si_, keys)

    def test_poll(self):
        done = Poll(PollState.DONE, StepResult(Outcome.INFRA_ERROR, "infra:stalled"), checkpoint=ref())
        self.assertEqual(poll_from_record(json.loads(json.dumps(to_record(done)))), done)
        for bad in (dict(state=PollState.DONE), dict(state=PollState.RUNNING, result=StepResult(Outcome.INFRA_ERROR, "infra:x")),
                    dict(state="lost"), dict(state=PollState.ABSENT, checkpoint=ref(K.GATE_RECEIPT))):
            with self.assertRaises(ContractError, msg=bad):
                Poll(**bad)


class Shapes(unittest.TestCase):
    def test_outcome_requirements(self):
        bad = [dict(outcome=Outcome.OK, reason="g1:pass"),
               dict(outcome=Outcome.PROVIDER_LIMIT, reason="router:claude_limit"),
               dict(outcome=Outcome.PROVIDER_LIMIT, reason="router:claude_limit", retry_at=float("inf")),
               dict(outcome=Outcome.GATE_FAILED, reason="g4:not_real", gate="G4", repairable=True),
               dict(outcome=Outcome.GATE_FAILED, reason="g4:not_real"),                      # names no gate
               dict(outcome=Outcome.INFRA_ERROR, reason="infra:stalled", feedback=ref(K.WRITER_FEEDBACK)),
               dict(outcome=Outcome.OK, reason="g1:pass", snapshot=ref(), retry_at=5.0),
               dict(outcome=Outcome.OK, reason="g1:pass", snapshot=ref(K.GATE_RECEIPT)),
               dict(outcome=Outcome.INFRA_ERROR, reason="infra:x", verdict=Verdict.FACTORY_BUG),
               dict(outcome=Outcome.INFRA_ERROR, reason="infra:x", repairable=1),
               dict(outcome=Outcome.OK, reason="seal:pass", snapshot=ref(), archive=ref(K.SEALED_ARCHIVE)),   # no hard
               dict(outcome=Outcome.OK, reason="seal:pass", snapshot=ref(), archive=ref(K.GATE_RECEIPT), hard=False),
               dict(outcome=Outcome.GATE_FAILED, reason="g4:x", gate="G44")]
        for kw in bad:
            with self.assertRaises(ContractError, msg=kw):
                StepResult(**kw)

    def test_rules_that_depend_on_the_step(self):
        ok = lambda **kw: StepResult(Outcome.OK, "g1:pass", snapshot=ref(), **kw)
        fb = ref(K.WRITER_FEEDBACK)
        check_result_for(STRESS, ok(feedback=fb))
        check_result_for(DIAG, ok(verdict=Verdict.CLOSE_TO_PASSING, feedback=fb))          # extension guidance
        check_result_for(ADMIT, ok(registry=ref(K.STATEMENT_REGISTRY)))
        check_result_for(SEAL, ok(archive=ref(K.SEALED_ARCHIVE), hard=True))
        check_result_for(GATES, StepResult(Outcome.NEEDS_FOUNDER, "g16:split_review", gate="G16"))
        check_result_for(STRESS, StepResult(Outcome.NEEDS_FOUNDER, "stress:split_review"))
        for step, result in ((GATES, ok(feedback=fb)),
                             (Step(StepKind.WRITER, 1), ok(feedback=fb)),
                             (DIAG, ok(verdict=Verdict.FACTORY_BUG, feedback=fb)),
                             (GATES, ok(verdict=Verdict.FACTORY_BUG)),
                             (DIAG, ok()),
                             (STRESS, StepResult(Outcome.GATE_FAILED, "stress:x", gate="G4")),
                             (ADMIT, ok()),                                                       # no registry
                             (GATES, ok(registry=ref(K.STATEMENT_REGISTRY))),
                             (SEAL, ok()),                                                        # no archive
                             (SEAL, StepResult(Outcome.NEEDS_FOUNDER, "seal:x")),
                             (Step(StepKind.WRITER, 1), StepResult(Outcome.NEEDS_FOUNDER, "writer:x")),
                             (GATES, StepResult(Outcome.NEEDS_FOUNDER, "g5:x", gate="G5"))):
            with self.assertRaises(ContractError, msg=(step, result)):
                check_result_for(step, result)

    def test_passed_gates(self):
        r = StepResult(Outcome.GATE_FAILED, "g11:fake_pass", gate="G11", passed=("G1", "G2", "G10"))
        check_result_for(GATES, r)
        self.assertEqual(step_result_from_record(json.loads(json.dumps(to_record(r)))), r)
        for bad in (dict(passed=["G1"]), dict(passed=("G1", "G1")), dict(passed=("G99",)),
                    dict(passed=("G11",))):                       # the failed gate did not pass
            with self.assertRaises(ContractError, msg=bad):
                StepResult(Outcome.GATE_FAILED, "g11:fake_pass", gate="G11", **bad)
        with self.assertRaises(ContractError):
            check_result_for(STRESS, StepResult(Outcome.OK, "stress:clean", snapshot=ref(), passed=("G8",)))

    def test_close_to_passing_carries_guidance(self):
        with self.assertRaises(ContractError):
            check_result_for(DIAG, StepResult(Outcome.OK, "diagnosis:pass", snapshot=ref(), verdict=Verdict.CLOSE_TO_PASSING))

    def test_wire_frames_and_release(self):
        self.assertEqual(key_frame("case-x1/7/gates:1/1"), {"key": "case-x1/7/gates:1/1"})
        with self.assertRaises(ContractError):
            key_frame("../etc/passwd")
        self.assertEqual(RELEASE_MANIFEST, "factory-release/RELEASE.json")

    def test_grant(self):
        Grant(5, LimitedBy.CASE)
        for bad in (lambda: Grant(-1, LimitedBy.NOTHING), lambda: Grant(1, "unknown")):
            with self.assertRaises(ContractError):
                bad()

    def test_steps(self):
        self.assertEqual(Step(StepKind.GATES, 2).name, "gates:2")
        self.assertEqual(Step(StepKind.DIAGNOSIS).name, "diagnosis")
        for bad in (dict(kind=StepKind.GATES), dict(kind=StepKind.WRITER), dict(kind=StepKind.SEAL, round=1),
                    dict(kind="rescue"), dict(kind=StepKind.ADMIT, round=-1)):
            with self.assertRaises(ContractError, msg=bad):
                Step(**bad)

    def test_step_input(self):
        self.assertEqual(step_input().idempotency_key, "case-x1/7/gates:1/1")
        admit = dict(step=ADMIT, snapshot=None)
        step_input(**admit, registry=ref(K.STATEMENT_REGISTRY))
        restored = step_input(step=ADMIT, registry=ref(K.STATEMENT_REGISTRY), snapshot=ref())
        self.assertIsNotNone(restored.snapshot)
        step_input(step=DIAG, evidence=(ref(K.GATE_RECEIPT), ref(K.DIAGNOSTIC, B)))
        step_input(ruling=ref(K.FOUNDER_RULING))
        for kw in (dict(**admit), dict(snapshot=None),
                   dict(registry=ref(K.STATEMENT_REGISTRY)), dict(feedback=ref(K.WRITER_FEEDBACK)),
                   dict(step=Step(StepKind.WRITER, 1), feedback=ref(K.GATE_RECEIPT)),
                   dict(snapshot=ref(K.SEALED_ARCHIVE)), dict(step="gates:1"), dict(seq=0),
                   dict(deadline_s=0), dict(deadline_s=float("inf")), dict(money_ceiling_usd_micros=-1),
                   dict(plumbing_version="v2"), dict(inputs=None), dict(inputs=ref(K.CASE_SNAPSHOT)),
                   dict(evidence=(ref(K.GATE_RECEIPT),)), dict(step=DIAG, evidence=[ref(K.GATE_RECEIPT)]),
                   dict(step=DIAG, evidence=(ref(K.CASE_SNAPSHOT),)), dict(step=DIAG, ruling=ref(K.FOUNDER_RULING))):
            with self.assertRaises(ContractError, msg=kw):
                step_input(**kw)

    def test_keys_never_collide_across_repairs(self):
        self.assertNotEqual(step_input(seq=5, snapshot=ref(d=A)).idempotency_key,
                            step_input(seq=19, snapshot=ref(d=B)).idempotency_key)

    def test_spec_and_output(self):
        spec()
        for bad in (dict(target_sealed=0), dict(app_commit="main"), dict(inputs=ref()), dict(inputs=None),
                    dict(deadline_epoch=float("nan")), dict(max_extensions=-1), dict(step_deadline_s=0),
                    dict(max_cases_started=0), dict(case_money_usd_micros=-1)):
            with self.assertRaises(ContractError, msg=bad):
                spec(**bad)
        SealedCase("case-x1", ref(K.SEALED_ARCHIVE), hard=False)
        with self.assertRaises(ContractError):
            SealedCase("case-x1", ref(), hard=False)

    def test_messages(self):
        BenchRelease(A)
        FounderReply(FounderAction.CONTINUE, ref(K.FOUNDER_RULING))
        FounderReply(FounderAction.RETIRE)
        FounderReply(FounderAction.STOP, reason="superseded by r2")
        self.assertEqual(to_record(FounderReply(FounderAction.RETIRE)), {"action": "retire", "ruling": None})
        for bad in (lambda: BenchRelease("v2"), lambda: FounderReply(FounderAction.CONTINUE),
                    lambda: FounderReply(FounderAction.RETIRE, ref(K.FOUNDER_RULING)), lambda: FounderReply("maybe"),
                    lambda: FounderReply(FounderAction.STOP), lambda: FounderReply(FounderAction.STOP, reason=" "),
                    lambda: FounderReply(FounderAction.STOP, reason="x" * 201),
                    lambda: FounderReply(FounderAction.STOP, reason="line\nbreak"),
                    lambda: FounderReply(FounderAction.RETIRE, reason="why")):
            with self.assertRaises(ContractError):
                bad()

    def test_classified_follows_the_result_rules(self):
        Classified(Outcome.PROVIDER_LIMIT, "router:opencode_limit", 1_800_000_000.0)
        for bad in (lambda: Classified(Outcome.PROVIDER_LIMIT, "router:opencode_limit"),
                    lambda: Classified(Outcome.INFRA_ERROR, "provider_limit:opencode-go/mimo-v2.6-pro")):
            with self.assertRaises(ContractError):
                bad()

    def test_wait_is_always_recorded(self):
        self.assertEqual(wait_seconds(100.0, 40.0), 60.0)
        self.assertEqual(wait_seconds(100.0, 500.0), 0.001)   # DBOS skips sleep(<=0) without recording it


class RoundTrip(unittest.TestCase):
    def test_exact(self):
        for r in (StepResult(Outcome.PROVIDER_LIMIT, "router:claude_limit", Usage(1, 0, 5), retry_at=1_800_000_000.5),
                  StepResult(Outcome.OK, "diagnosis:pass", snapshot=ref(), verdict=Verdict.CLOSE_TO_PASSING,
                             report=ref(K.DIAGNOSIS_REPORT, C), feedback=ref(K.WRITER_FEEDBACK)),
                  StepResult(Outcome.OK, "seal:pass", snapshot=ref(), archive=ref(K.SEALED_ARCHIVE), hard=True),
                  StepResult(Outcome.OK, "admit:pass", snapshot=ref(), registry=ref(K.STATEMENT_REGISTRY))):
            self.assertEqual(step_result_from_record(json.loads(json.dumps(to_record(r)))), r)
        for si in (step_input(step=Step(StepKind.WRITER, 3), feedback=ref(K.WRITER_FEEDBACK, B)),
                   step_input(step=ADMIT, snapshot=None, registry=ref(K.STATEMENT_REGISTRY)),
                   step_input(step=DIAG, evidence=(ref(K.GATE_RECEIPT), ref(K.DIAGNOSIS_REPORT, C))),
                   step_input(ruling=ref(K.FOUNDER_RULING))):
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


if __name__ == "__main__":
    unittest.main()
