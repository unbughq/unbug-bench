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
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import budget

os.environ.setdefault("BENCH", str(_ROOT))

import run
from durable import worker_step
from durable.artifacts import AgeSealer
from durable.contract import (ArtifactKind, Outcome, Ref, Step, StepInput, StepKind, Usage, check_result_for)
from durable.steps import admit

PLUMBING = hashlib.sha256(b"admit plumbing").hexdigest()
BENCH_V = hashlib.sha256(b"admit bench").hexdigest()
CASE = "case-admit-practice"
BATCH = "b-admit"


class AdmitTests(unittest.TestCase):
    def test_failure_cause_is_specific_and_original_traceback_stays_encrypted(self):
        from durable.contract import to_record
        error = budget.BudgetError('admission_registry_unavailable:private-error-sentinel')
        value = self.real_inputs('unused'); value.pop('candidate')
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b'')
        with patch.object(run, 'statement_precheck', side_effect=error):
            result, outputs = self.run_admit(self.step(inputs, registry))
        self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, 'admit:registry_unavailable'))
        details = json.loads(self.output(result.diagnostic, outputs))
        self.assertEqual(details['stop'], str(error))
        self.assertIn('private-error-sentinel', details['traceback'])
        self.assertNotIn('private-error-sentinel', json.dumps(to_record(result)))
        self.assertTrue(all(b'private-error-sentinel' not in blob for blob in outputs.values()))

    def test_structured_wait_preserves_cause_reset_and_private_operational_receipt(self):
        from model_router import ProviderWait, Wait
        self.model_error = ProviderWait('writer', Wait('credential_expiring', self.worker.clock() + 120,
            route='claude/claude-opus-5-5:small', account='claude-factory-token-2',
            lease_id='a' * 32, call_id='usage-receipts/' + 'a' * 32 + '.json'))
        value = self.real_inputs('unused'); value.pop('candidate')
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b'')
        result, outputs = self.run_admit(self.step(inputs, registry))
        self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, 'router:credential_expiring'))
        self.assertEqual(result.usage.paid_usd_micros, 750_000)
        self.assertIsNotNone(result.diagnostic)
        details = json.loads(self.worker.sealer().open(self.case_key, result.diagnostic,
                          outputs[worker_step.blob_name(result.diagnostic)]))
        self.assertEqual(details['provider_wait']['waits'][-1]['lease_id'], 'a' * 32)

    def test_legacy_registry_is_rewrapped_only_on_the_worker(self):
        from registry import Registry
        import worker_secrets
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); identity = root / 'statements-key'
            subprocess.run(['age-keygen', '-o', str(identity)], capture_output=True, check=True)
            public = subprocess.run(['age-keygen', '-y', str(identity)], capture_output=True, check=True).stdout.decode().strip()
            old = Registry(root / 'old')
            for i in range(2):
                plaintext = ('private prior statement ' + str(i)).encode()
                cipher = subprocess.run(['age', '-r', public], input=plaintext, capture_output=True, check=True).stdout
                old.import_historical('case-prior-' + str(i), cipher, hashlib.sha256(plaintext).hexdigest())
            state = json.loads((old.root / 'registry.json').read_text())
            original = (old.root / 'registry.json').read_bytes()
            legacy = json.dumps({'version': 1, 'legacy': True, 'registry': state,
                'objects': {p.stem: base64.b64encode(p.read_bytes()).decode() for p in (old.root / 'objects').glob('*.age')}}).encode()
            sealer, key = AgeSealer(), os.urandom(32)
            with patch.object(worker_secrets, 'SECRETS', root):
                upgraded = admit._upgrade_registry(legacy, sealer, key)
            registry, revision, refs = admit._load_registry(root / 'new', upgraded)
            self.assertEqual(revision, state['revision'])
            self.assertEqual((old.root / 'registry.json').read_bytes(), original)
            for case, entry in json.loads((registry.root / 'registry.json').read_text())['entries'].items():
                digest = entry['cipher_sha256']
                plaintext = sealer.open(key, Ref(refs[digest], ArtifactKind.STATEMENT_REGISTRY),
                                       (registry.root / 'objects' / (digest + '.age')).read_bytes())
                self.assertEqual(hashlib.sha256(plaintext).hexdigest(), entry['statement_sha256'])
                self.assertNotIn(plaintext, upgraded)
            with patch.object(worker_secrets, 'SECRETS', root / 'missing'):
                with self.assertRaises(admit._Invalid): admit._upgrade_registry(legacy, sealer, key)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = pathlib.Path(temporary.name)
        (self.home / "durable/blobs").mkdir(parents=True)
        self.worker = worker_step.Worker(self.home, sealer=AgeSealer(), runner=run)
        self.case_key, self.batch_key = os.urandom(32), os.urandom(32)
        self.calls, self.duplicate, self.model_error = [], None, None
        # External search/model boundaries only; statement_precheck and idea_realism are real.
        self.freshness = patch.object(run, "_g2", return_value=(True, {"outcome": "fresh"})).start()
        self.addCleanup(patch.stopall)
        patch.object(run, "model_call", side_effect=self.model).start()
        patch.object(run, "opencode", side_effect=self.model).start()
        self.selected = "# Candidate\n\nA selected checkout failure."

    def model(self, c, models, text, cwd, name, **kwargs):
        self.calls.append(name)
        if self.model_error is not None:
            with budget.ledger_transaction(c.ledger) as ledger:
                ledger["calls"] = ledger.get("calls", 0) + 1
                ledger.setdefault("events", []).append({"id": name, "cost": .75,
                    "configured_model": models[0], "role": "writer"})
            raise self.model_error
        if name.endswith('provider-preflight'):
            return 0
        if name.startswith("builder-selection"):
            (c.case / "statement.md").write_text(self.selected)
        elif name == "easy-calibrator-dedup":
            target = json.loads(text.rsplit("\n", 1)[-1])["result_path"]
            pathlib.Path(target).write_text(json.dumps({"duplicate_of": self.duplicate, "reason": "same bug" if self.duplicate else "distinct"}))
        elif name == "reviewer-idea-realism":
            target = text.split('Write JSON to ')[1].split(': {')[0]
            pathlib.Path(target).write_text(json.dumps({"approve": True, "reason": "plausible"}))
        else:
            raise AssertionError("unexpected model invocation: " + name)
        if kwargs.get("on_complete"):
            c.model_lease = SimpleNamespace(route=models[0])
            kwargs["on_complete"]()
        return 0

    def push(self, kind, key, plaintext):
        ref, ciphertext = self.worker.sealer().seal(key, kind, plaintext)
        (self.home / "durable/blobs" / worker_step.blob_name(ref)).write_bytes(ciphertext)
        return ref

    def step(self, inputs, registry, attempt=1):
        return StepInput(BATCH, CASE, 1, Step(StepKind.ADMIT), attempt, PLUMBING, BENCH_V,
                         inputs, None, 600.0, 10_000_000, registry=registry)

    def run_admit(self, step_input):
        self.worker.paths(step_input.idempotency_key)["attempt"].mkdir(parents=True, exist_ok=True)
        return admit.run(self.worker, step_input, {step_input.case_id: self.case_key, BATCH: self.batch_key})

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
                 "models": {"builder": ["openrouter/minimax/minimax-m3.1-flash"],
                            "attacker": ["openrouter/deepseek/deepseek-v4.1-flash"],
                            "reviewers": [["openrouter/xiaomi/mimo-v2.6-pro"]],
                            "strong_calibrator": ["claude/claude-opus-5-5"],
                            "easy_calibrator": ["openrouter/z-ai/glm-5.3-flash"]},
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
        self.assertEqual(c.admission_binding, {k: entry[k] for k in ("reservation", "registry_revision")})

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
        self.assertIsNone(refused.registry)
        self.assertIsNotNone(refused.snapshot)
        check_result_for(conflict.step, refused)

    def test_real_inputs_select_and_run_existing_screens(self):
        value = self.real_inputs("unused")
        value.pop("candidate")
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        si = self.step(inputs, registry)
        result, outputs = self.run_admit(si)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:selected"))
        self.assertEqual(self.calls, ["attacker-provider-preflight", "reviewer-provider-preflight",
            "strong-calibrator-provider-preflight", "easy-calibrator-provider-preflight",
            "builder-selection", "reviewer-idea-realism"])
        self.freshness.assert_called_once()
        work, c = self.restore(si, result, outputs)
        self.assertEqual((work / "case/statement.md").read_text(), self.selected)
        self.assertEqual(c.card["admission"]["status"], "passed")
        self.assertEqual(len({c.card["roles"][r]["family"] for r in
            ("writer", "stress_tester", "reviewer", "strong_calibrator")}), 4)

    def test_selection_then_wait_restores_receipt_and_usage_on_fresh_worker(self):
        from dataclasses import replace
        import shutil
        import time
        from durable import checkpoints
        from model_router import ProviderWait, Wait
        value = self.real_inputs('unused'); value.pop('candidate')
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b'')
        first = self.step(inputs, registry)
        interrupted = False
        def model(c, models, text, cwd, name, **kwargs):
            nonlocal interrupted
            if name == 'reviewer-idea-realism' and not interrupted:
                interrupted = True
                raise ProviderWait('reviewer', Wait('quota', time.time()+120))
            if name != 'builder-selection': return self.model(c, models, text, cwd, name, **kwargs)
            def invoke():
                result = self.model(c, models, text, cwd, name, **kwargs)
                with budget.ledger_transaction(c.ledger) as ledger:
                    ledger.update(cost=.25, calls=1)
                    ledger['events'].append({'id': 'completed-selection', 'cost': .25, 'calls': 1})
                receipt = 'usage-receipts/' + 'c'*32 + '.json'
                (c.work / 'usage-receipts').mkdir(exist_ok=True)
                (c.work / receipt).write_text(json.dumps({'final_usage_known': True}))
                c.card.setdefault('route_receipts', []).append({'invocation': name,
                    'call_id': receipt, 'outcome': 'done'})
                return result
            return checkpoints.model_call(c, models, cwd, name, invoke, text=text)
        with patch.object(run, 'opencode', side_effect=model), patch.object(run, 'model_call', side_effect=model):
            result, blobs = self.run_admit(first)
            self.assertEqual(result.outcome, Outcome.PROVIDER_LIMIT)
            self.assertEqual(result.usage.paid_usd_micros, 250000)
            self.home = self.home / 'replacement'
            shutil.copytree(self.worker.home / 'durable/blobs', self.home / 'durable/blobs')
            for name, ciphertext in blobs.items(): (self.home / 'durable/blobs' / name).write_bytes(ciphertext)
            self.worker = worker_step.Worker(self.home, sealer=AgeSealer(), runner=run)
            retry = replace(first, attempt=2, snapshot=result.snapshot)
            completed, outputs = self.run_admit(retry)
        self.assertEqual(completed.outcome, Outcome.OK)
        self.assertEqual(self.calls.count('builder-selection'), 1)
        self.assertEqual(completed.usage, Usage())
        work, _ = self.restore(retry, completed, outputs)
        self.assertTrue(list((work / 'engine-checkpoints').rglob('*.json')))
        self.assertEqual(json.loads((work / 'continuation-budget.json').read_text())['cost'], .25)

    def test_malformed_dedup_retries_on_fresh_worker_without_reselecting_or_erasing_spend(self):
        from dataclasses import replace
        import shutil
        import model_router
        from registry import Registry
        value = self.real_inputs('unused'); value.pop('candidate')
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        prior = b'Public synthetic predecessor statement'
        ref, cipher = self.worker.sealer().seal(self.batch_key, ArtifactKind.STATEMENT_REGISTRY, prior)
        registry_root = self.home/'synthetic-registry'
        Registry(registry_root).reserve('case-prior', hashlib.sha256(prior).hexdigest(), cipher)
        payload = admit._dump_registry(registry_root, {hashlib.sha256(cipher).hexdigest():ref.digest})
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, payload)
        first = self.step(inputs, registry); dedup_calls = 0
        routes = model_router.routes
        def model(c, models, text, cwd, name, **kwargs):
            nonlocal dedup_calls
            if name == 'easy-calibrator-dedup':
                dedup_calls += 1
                with budget.ledger_transaction(c.ledger) as ledger:
                    ledger['cost'] += .01; ledger['calls'] += 1
                    ledger['events'].append({'id':f'dedup-{dedup_calls}', 'cost':.01,
                                            'configured_model':models[0], 'role':'easy_calibrator'})
                if dedup_calls == 1:
                    self.calls.append(name); c.model_lease = SimpleNamespace(route=models[0])
                    kwargs['on_complete']()  # Completed CLI, missing/undecodable answer.
                    return 0
            return self.model(c, models, text, cwd, name, **kwargs)
        with patch.object(model_router, 'routes', side_effect=lambda *a: routes(*a)[:1]), \
                patch.object(run, 'opencode', side_effect=model), patch.object(run, 'model_call', side_effect=model):
            result, blobs = self.run_admit(first)
            self.assertEqual((result.outcome,result.reason), (Outcome.INFRA_ERROR,'infra:malformed_output_exhausted'))
            self.assertEqual(result.usage.paid_usd_micros,10000)
            self.home = self.home/'replacement'
            shutil.copytree(self.worker.home/'durable/blobs', self.home/'durable/blobs')
            for name, ciphertext in blobs.items(): (self.home/'durable/blobs'/name).write_bytes(ciphertext)
            self.worker = worker_step.Worker(self.home, sealer=AgeSealer(), runner=run)
            retry = replace(first, attempt=2, snapshot=result.snapshot)
            completed, outputs = self.run_admit(retry)
        self.assertEqual((completed.outcome,completed.reason), (Outcome.OK,'admit:selected'))
        self.assertEqual(completed.usage.paid_usd_micros,10000)
        self.assertEqual(dedup_calls,2)
        self.assertEqual(self.calls.count('builder-selection'),1)
        work, _ = self.restore(retry, completed, outputs)
        self.assertEqual(json.loads((work/'continuation-budget.json').read_text())['cost'],.02)
        self.assertEqual(set(self.registry_doc(completed,outputs)['registry']['entries']),{'case-prior',CASE})

    def test_second_case_screens_against_authenticated_prior_statement(self):
        from dataclasses import replace
        text = "# Candidate\n\nOversell under checkout."
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(self.real_inputs(text)).encode())
        empty = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        first, blobs = self.run_admit(self.step(inputs, empty))
        (self.home / "durable/blobs" / worker_step.blob_name(first.registry)).write_bytes(blobs[worker_step.blob_name(first.registry)])
        self.duplicate = CASE
        self.selected = "# Candidate\n\nDifferent words for the same underlying checkout bug."
        second_input = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(self.real_inputs(self.selected)).encode())
        second = replace(self.step(second_input, first.registry), case_id="case-second")
        result, outputs = self.run_admit(second)
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:exhausted"))
        self.assertIsNone(result.registry)
        check_result_for(second.step, result)
        work, c = self.restore(second, result, outputs)
        self.assertEqual(c.card["dedup"]["duplicate_of"], CASE)
        self.assertIn("easy-calibrator-dedup", self.calls)
        self.assertEqual((work / "statements" / (CASE + ".md")).read_text(), text)
        self.assertEqual(c.card["admission"]["status"], "exhausted")
        self.assertEqual(c.card["candidate_attempts"], 3)

    def test_batch_ordinals_follow_existing_role_rotation(self):
        from dataclasses import replace
        import model_runtime
        value = self.real_inputs("# Candidate\n\nA checkout failure.")
        value.pop('models')
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        empty = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        for ordinal in (1, 4, 8, 9):
            si = replace(self.step(inputs, empty), case_id=f"case-cohort-{ordinal}")
            result, blobs = self.run_admit(si)
            self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, 'router:unbounded_route'))
            _, c = self.restore(si, result, blobs)
            slot = (ordinal - 1) % 8 + 1
            self.assertEqual(c.card["rotation_slot"], slot)
            self.assertEqual(c.card["roles"]["writer"]["model"], model_runtime.rotation(slot)["writer"]["model"])
        self.assertEqual(self.calls, [])

    def test_unbounded_strong_or_second_reviewer_stops_before_any_model_spend(self):
        for role in ('strong_calibrator', 'reviewers'):
            value = self.real_inputs('unused')
            if role == 'strong_calibrator': value['models'][role] = ['codex/gpt-6.1-sol']
            else: value['models'][role].append(['codex/gpt-6.1-sol'])
            inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
            registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b'')
            result, _ = self.run_admit(self.step(inputs, registry))
            self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, 'router:unbounded_route'))
            self.assertEqual(result.usage, Usage())
            self.assertIsNotNone(result.diagnostic)
        self.assertEqual(self.calls, [])

    def test_paid_failure_and_snapshot_failure_preserve_usage(self):
        from budget import BudgetError
        value = self.real_inputs("unused")
        value.pop("candidate")
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        self.model_error = BudgetError("provider_wait")
        si = self.step(inputs, registry)
        result, _ = self.run_admit(si)
        self.assertEqual(result.outcome, Outcome.PROVIDER_LIMIT)
        self.assertEqual((result.usage.calls, result.usage.paid_usd_micros), (1, 750000))
        self.assertIsNotNone(result.snapshot)
        self.assertEqual(self.worker.usage_so_far(si.idempotency_key), result.usage)
        self.model_error = RuntimeError("post-payment model failure")
        with patch.object(worker_step, "snapshot_bytes", side_effect=OSError("disk full")):
            result, _ = self.run_admit(self.step(inputs, registry, attempt=2))
        self.assertEqual(result.outcome, Outcome.INFRA_ERROR)
        self.assertEqual(result.usage.paid_usd_micros, 750000)
        self.assertIsNone(result.snapshot)

    def test_explicit_models_keep_efforts_and_reject_overlapping_families(self):
        import model_runtime
        value = self.real_inputs("# Candidate\n\nA bug.")
        models = value['models']
        roles = {'writer': models['builder'][0], 'stress_tester': models['attacker'][0],
                 'reviewer': models['reviewers'][0][0], 'strong_calibrator': models['strong_calibrator'][0],
                 'easy_calibrator': models['easy_calibrator'][0]}
        value['roles'] = {role: {'model': model, 'effort': model_runtime.model_effort(model),
                                'family': model_runtime.family(model)} for role, model in roles.items()}
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        si = self.step(inputs, registry)
        result, blobs = self.run_admit(si)
        self.assertEqual(result.outcome, Outcome.OK)
        _, c = self.restore(si, result, blobs)
        self.assertEqual(c.models, value["models"])
        self.assertEqual(c.card["roles"], value["roles"])
        value["models"]["attacker"] = value["models"]["builder"]
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        self.assertEqual(self.run_admit(self.step(inputs, registry, attempt=2))[0].outcome, Outcome.INFRA_ERROR)


if __name__ == "__main__":
    unittest.main()
