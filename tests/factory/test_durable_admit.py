"""ADMIT adapter: practice handoff through the real sealer, restore and runner context.

The practice card and tree are the ones `run.build_fixture` lays out; the snapshot is
opened with a real AgeSealer and restored by `worker_step.restore`, then handed to
`run.context_for_step` exactly as a later step receives it. The real path uses the
version-1 INPUTS/registry JSON described in durable/steps/admit.py; its candidate is
the existing admission path's output, and registry.Registry is the conflict rule.
"""
import sys
from pathlib import Path as _TestPath

_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_TestPath(__file__).resolve().parent)]

import base64
import hashlib
import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("BENCH", str(_ROOT))

import run
from durable import worker_step
from durable.artifacts import AgeSealer
from durable.contract import (ArtifactKind, Outcome, Ref, Step, StepInput, StepKind, check_result_for)
from durable.steps import admit

PLUMBING = hashlib.sha256(b"admit plumbing").hexdigest()
BENCH_V = hashlib.sha256(b"admit bench").hexdigest()
CASE = "case-admit-practice"
BATCH = "b-admit"


class AdmitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = pathlib.Path(temporary.name)
        (self.home / "durable/blobs").mkdir(parents=True)
        self.worker = worker_step.Worker(self.home, sealer=AgeSealer(), runner=run)
        self.case_key, self.batch_key = os.urandom(32), os.urandom(32)

    def push(self, kind, key, plaintext):
        ref, ciphertext = self.worker.sealer().seal(key, kind, plaintext)
        (self.home / "durable/blobs" / worker_step.blob_name(ref)).write_bytes(ciphertext)
        return ref

    def step(self, inputs, registry, attempt=1):
        return StepInput(BATCH, CASE, 1, Step(StepKind.ADMIT), attempt, PLUMBING, BENCH_V,
                         inputs, None, 600.0, 10_000_000, registry=registry)

    def run_admit(self, step_input):
        return admit.run(self.worker, step_input, {CASE: self.case_key, BATCH: self.batch_key})

    def output(self, ref, outputs):
        return self.worker.sealer().open(
            self.batch_key if ref.kind is ArtifactKind.STATEMENT_REGISTRY else self.case_key,
            ref, outputs[worker_step.blob_name(ref)])

    def registry_doc(self, result, outputs):
        return json.loads(self.output(result.registry, outputs))

    def restore(self, step_input, result, outputs):
        snapshot = self.output(result.snapshot, outputs)
        work = self.home / f"restored-{step_input.attempt}"
        worker_step.restore(snapshot, work)
        return work, run.context_for_step(step_input, work)

    def test_practice_dry_run_hands_over_a_runner_context(self):
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key,
                           json.dumps({"version": 1, "dry_run": True, "seed": 7}).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        step_input = self.step(inputs, registry)
        result, outputs = self.run_admit(step_input)

        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:practice"))
        self.assertIsNotNone(result.snapshot)
        self.assertIsNotNone(result.registry)
        check_result_for(step_input.step, result)

        work, c = self.restore(step_input, result, outputs)
        self.assertTrue(c.args.dry_run)
        self.assertEqual((c.card["case"], c.card["seed"]), (CASE, 7))
        self.assertTrue((work / "continuation-budget.json").is_file())
        self.assertTrue((work / "case/base/scenario.json").is_file())
        self.assertTrue((work / "case/guards/reference").is_dir())
        self.assertIn("practice", c.card["admission"]["status"])

        # The practice case never reserves anything.
        self.assertEqual(self.registry_doc(result, outputs), {
            "version": 1, "registry": {"revision": 0, "entries": {}}, "objects": {}, "refs": {}})

    def real_inputs(self, statement, **more):
        value = {"version": 1, "dry_run": False, "seed": 11, "source": "port",
                 "app_repo": "medusajs/medusa", "app_commit": "a" * 40,
                 "promise": "# Promise\n\nCheckout holds the stock it promised.",
                 "promise_paths": ["store-checkout"], "promise_checks": [],
                 "candidate": {"statement": statement,
                               "statement_sha256": hashlib.sha256(statement.encode()).hexdigest()}}
        value.update(more)
        return value

    def test_selected_candidate_is_reserved_once_and_retries_are_idempotent(self):
        statement = "# Candidate\n\nOversell under concurrent checkout."
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(self.real_inputs(statement)).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        first = self.step(inputs, registry)
        result, outputs = self.run_admit(first)

        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:selected"))
        check_result_for(first.step, result)
        doc = self.registry_doc(result, outputs)
        entry = doc["registry"]["entries"][CASE]
        self.assertEqual(doc["registry"]["revision"], 1)
        self.assertEqual((entry["status"], entry["registry_revision"]), ("screening", 1))
        self.assertEqual(entry["statement_sha256"], hashlib.sha256(statement.encode()).hexdigest())
        ciphertext = base64.b64decode(doc["objects"][entry["cipher_sha256"]])
        self.assertTrue(ciphertext.startswith(b"age-encryption.org/v1"))
        # The stored digest lets a later worker open the statement with the batch key.
        stored = Ref(doc["refs"][entry["cipher_sha256"]], ArtifactKind.STATEMENT_REGISTRY)
        self.assertEqual(self.worker.sealer().open(self.batch_key, stored, ciphertext), statement.encode())

        work, c = self.restore(first, result, outputs)
        self.assertFalse(c.args.dry_run)
        self.assertEqual(c.card["source"], "port")
        self.assertEqual((work / "case/statement.md").read_text(), statement)
        self.assertEqual(json.loads((work / "case/case.json").read_text())["app"]["commit"], "a" * 40)
        self.assertIn("passed", c.card["admission"]["status"])

        # A retry restores the same registry snapshot: the same case, statement and revision.
        retry_registry = result.registry
        (self.home / "durable/blobs" / worker_step.blob_name(retry_registry)).write_bytes(
            outputs[worker_step.blob_name(retry_registry)])
        retry = self.step(inputs, retry_registry, attempt=2)
        again, again_outputs = self.run_admit(retry)
        self.assertEqual((again.outcome, again.reason), (Outcome.OK, "admit:selected"))
        again_doc = self.registry_doc(again, again_outputs)
        self.assertEqual(again_doc, doc)
        self.assertEqual(list(again_doc["registry"]["entries"]), [CASE])
        self.assertEqual(again.registry, result.registry)

        # A conflicting statement for the reserved case is refused, not silently replaced.
        other = "# Candidate\n\nA different bug for the same case."
        conflict_inputs = self.push(ArtifactKind.INPUTS, self.batch_key,
                                    json.dumps(self.real_inputs(other)).encode())
        conflict = self.step(conflict_inputs, retry_registry, attempt=3)
        refused, refused_outputs = self.run_admit(conflict)
        self.assertEqual((refused.outcome, refused.reason), (Outcome.EXHAUSTED, "admit:conflict"))
        self.assertIsNone(refused.snapshot)
        self.assertIsNone(refused.registry)
        self.assertEqual(refused_outputs, {})
        check_result_for(conflict.step, refused)

    def test_real_inputs_without_a_candidate_never_fall_back_to_practice(self):
        value = self.real_inputs("# Candidate\n\nUnused.")
        value.pop("candidate")
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        step_input = self.step(inputs, registry)
        result, outputs = self.run_admit(step_input)
        self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, "admit:selection_required"))
        self.assertEqual(outputs, {})


if __name__ == "__main__":
    unittest.main()
