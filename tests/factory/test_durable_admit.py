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

# The checkout's tree, but a private results/: a step moves every new file there into its work dir,
# and other suite scripts write theirs to the checkout's results/ at the same time.
_BENCH = tempfile.TemporaryDirectory()
for _entry in _ROOT.iterdir():
    if _entry.name != "results": (pathlib.Path(_BENCH.name) / _entry.name).symlink_to(_entry)
(pathlib.Path(_BENCH.name) / "results").mkdir()
os.environ["BENCH"] = str(pathlib.Path(_BENCH.name).resolve())  # resolved: see test_calibration_delivery

import run
from durable import worker_step
from durable.artifacts import AgeSealer
from durable.contract import (ArtifactKind, Outcome, Ref, Step, StepInput, StepKind, Usage, check_result_for)
from durable.steps import admit

PLUMBING = hashlib.sha256(b"admit plumbing").hexdigest()
BENCH_V = hashlib.sha256(b"admit bench").hexdigest()
CASE = "case-admit-practice"
BATCH = "b-admit"



import model_router as _router
# These tests stop admission at the table's walled GLM calibrator, before any model call. Its chain
# now ends in OpenRouter's gated route (founder 2026-11-09), so they use the chain without it.
WALLED_GLM_UNBOUNDED = tuple(tuple(r for r in c if r != 'openrouter/z-ai/glm-5.3-flash') for c in _router.CHAINS)

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
        self.second_agrees, self.second_judges = True, []
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
        elif name.endswith("-second-opinion-dedup"):
            self.second_judges.append(models[0])
            target = json.loads(text.rsplit("\n", 1)[-1])["result_path"]
            pathlib.Path(target).write_text(json.dumps({"same_bug": self.second_agrees, "reason": "checked"}))
        elif name.endswith("-second-opinion-idea-realism"):
            self.second_judges.append(models[0])
            target = text.split('Write JSON to ')[1].split(': {')[0]
            pathlib.Path(target).write_text(json.dumps({"approve": not self.second_agrees, "reason": "checked"}))
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

    def test_a_resume_role_swap_survives_the_models_admit_pins(self):
        # Founder 2026-11-12: ADMIT pins its models from INPUTS after context_for_step; a resumed
        # case's role swap (StepInput.roles) applies over them, so its screens use the swapped model.
        import dataclasses
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key,
                           json.dumps({"version": 1, "dry_run": True, "seed": 7}).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        plain, outputs = self.run_admit(self.step(inputs, registry))
        pinned = self.restore(self.step(inputs, registry), plain, outputs)[1].card
        # Another stress tester whose family the pinned selection leaves free.
        used = {pinned["roles"][r]["family"] for r in ("writer", "reviewer", "strong_calibrator", "stress_tester")}
        model = next(m for m in ("opencode-go/deepseek-v4.1-flash", "opencode/minimax-m3.1-flash-free",
                                 "openrouter/xiaomi/mimo-v2.6-pro") if run.family(m) not in used)
        swapped = dataclasses.replace(self.step(inputs, registry, attempt=2), roles={"stress_tester": model})
        result, outputs = self.run_admit(swapped)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:practice"))
        card = self.restore(swapped, result, outputs)[1].card
        self.assertEqual((card["models"]["attacker"], card["roles"]["stress_tester"]["model"]), ([model], model))
        self.assertEqual([(s["role"], s["to"], s["step"]) for s in card["role_swaps"]][:1], [("stress_tester", model, "admit")])
        # A swap the pinned selection refuses holds the case (policy.ROLES_REFUSED), never admit:processing_failed.
        refused = dataclasses.replace(self.step(inputs, registry, attempt=3),
                                      roles={"stress_tester": pinned["roles"]["writer"]["model"]})
        result, _ = self.run_admit(refused)
        self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, "infra:roles_refused"))

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
        self.assertEqual(self.calls, ["builder-provider-preflight", "attacker-provider-preflight", "reviewer-provider-preflight",
            "reviewer-2-provider-preflight", "strong-calibrator-provider-preflight", "easy-calibrator-provider-preflight",
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

    def test_a_retried_admit_reruns_only_the_preflight_checks_that_did_not_pass(self):
        """Nov 6-11: every admit retry re-ran all four "Reply OK" calls and queued for their routes."""
        from dataclasses import replace
        value = self.real_inputs('unused'); value.pop('candidate')
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b'')
        first = self.step(inputs, registry)
        def model(c, models, text, cwd, name, **kwargs):
            if name == 'strong-calibrator-provider-preflight' and self.calls.count(name) == 0:
                self.calls.append(name)
                raise budget.BudgetError('timeout')
            return self.model(c, models, text, cwd, name, **kwargs)
        with patch.object(run, 'opencode', side_effect=model), patch.object(run, 'model_call', side_effect=model):
            failed, blobs = self.run_admit(first)
            self.assertEqual(failed.outcome, Outcome.INFRA_ERROR)
            for name, ciphertext in blobs.items(): (self.home / 'durable/blobs' / name).write_bytes(ciphertext)
            retry = replace(first, attempt=2, snapshot=failed.snapshot)
            done, outputs = self.run_admit(retry)
        self.assertEqual((done.outcome, done.reason), (Outcome.OK, 'admit:selected'))
        preflights = [n for n in self.calls if n.endswith('provider-preflight')]
        self.assertEqual(preflights, ['builder-provider-preflight', 'attacker-provider-preflight', 'reviewer-provider-preflight',
            'reviewer-2-provider-preflight',
            'strong-calibrator-provider-preflight', 'strong-calibrator-provider-preflight',
            'easy-calibrator-provider-preflight'])
        _, c = self.restore(retry, done, outputs)
        self.assertEqual([r.get('reused', False) for r in c.card['provider_preflight']], [True, True, True, True, False, False])
        # A pass older than PREFLIGHT_REUSE_S (a retry after a long wait) is checked again.
        self.calls.clear()
        for row in c.card['provider_preflight']: row['checked_at'] -= run.PREFLIGHT_REUSE_S
        run.provider_preflight(c, step=f'{BATCH}:1')
        self.assertEqual(len(self.calls), 5)
        # Another step checks every route again.
        self.calls.clear()
        run.provider_preflight(c, step=f'{BATCH}:2')
        self.assertEqual(len(self.calls), 5)

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
        with patch.object(model_router, 'routes', side_effect=lambda m, *a: [r for r in routes(m, *a) if r['route'] == m][:1]), \
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
        # The published reason names the screen and its evidence kind, never the idea.
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:dedup_board_duplicate"))
        self.assertIsNone(result.registry)
        check_result_for(second.step, result)
        work, c = self.restore(second, result, outputs)
        self.assertEqual(c.card["dedup"]["duplicate_of"], CASE)
        # The fake builder proposes the same idea again; those tries judged nothing.
        self.assertEqual([r["codes"] for r in c.card["rejected_candidates"]], [
            {"screen": "dedup", "evidence": "board_duplicate", "judge_family": "z-ai",
             "duplicate_of": CASE, "duplicate_status": "screening", "second_family": "xiaomi", "agreed": True}]
            + [{"screen": "other", "evidence": "repeat_candidate"}] * 2)
        self.assertEqual(c.card["admission"]["reason"], "dedup_board_duplicate")
        self.assertIn("easy-calibrator-dedup", self.calls)
        self.assertEqual((work / "statements" / (CASE + ".md")).read_text(), text)
        self.assertEqual(c.card["admission"]["status"], "exhausted")
        self.assertEqual(c.card["candidate_attempts"], 3)

    def legacy_archive(self, old, statement, *, commit="a" * 40, gates=None, writer="opencode-go/minimax-m3", link=False,
                       repo="medusajs/medusa", lockfile=None, card_extra=None, meta=True, statement_inside=True):
        """A pre-durable checkpoint as run_artifacts.seal wrote it, rewrapped to the statement key:
        `tar -C <work parent> -czf - <case id> | age -r <recipient>`, links and caches included."""
        import worker_secrets
        root = pathlib.Path(tempfile.mkdtemp(dir=self.home))
        if not hasattr(self, "statement_key"):   # one worker statement key per test, as on a real worker
            self.statement_key = pathlib.Path(tempfile.mkdtemp(dir=self.home)) / "statements-key"
            subprocess.run(["age-keygen", "-o", str(self.statement_key)], capture_output=True, check=True)
            patch.object(worker_secrets, "SECRETS", self.statement_key.parent).start()
        recipient = subprocess.run(["age-keygen", "-y", str(self.statement_key)], capture_output=True, check=True).stdout.decode().strip()
        work = root / "work" / old
        (work / "case").mkdir(parents=True)
        if statement_inside:   # an October seal kept it beside the archive instead
            (work / "case/statement.md").write_text(statement)
        (work / "case/promise.md").write_text("# Promise\n\nCheckout holds the stock it promised.")
        app = {"repo": repo, "commit": commit}
        if lockfile is not None:
            app["lockfile_sha256"] = lockfile
        if meta:
            # An October writer kept its draft's design in case.json as well.
            (work / "case/case.json").write_text(json.dumps({"source": "port", "app": app, "leak_words": ["oversell"],
                "ingredients": {"unstated_rules": ["old"]}, "promise_checks": ["old-judge-path"]}))
        (work / "case/guards").mkdir()
        (work / "case/guards/reference.py").write_text("print('guard')")
        (work / "scorecard.json").write_text(json.dumps({"case": old, "seed": 3, "source": "port",
            "gates": gates if gates is not None else {"G1": "pass", "G2": "pass"}, "failed_gate": None,
            **({"models": {"builder": [writer]}} if writer else {}),
            "continuation_budget": {"cost": 2.5, "calls": 9, "events": []}, **(card_extra or {})}))
        (work / "continuation-budget.json").write_text(json.dumps({"cost": 2.5, "calls": 9, "events": []}))
        for name in ("gate-cache", "public-search.json", "freshness-verdict.json", "idea-realism.json"):
            (work / name).write_text("old evidence") if "." in name else (work / name).mkdir()
        (work / "gate-cache/G2.json").write_text("old pass")
        (work / "agent-state").mkdir()
        (work / "agent-state/link").symlink_to("/etc/passwd")
        (work / ".casekey").write_text("AGE-SECRET-KEY-OLD")
        if link:
            (work / "case/escape").symlink_to("../..")
        tar = subprocess.run(["tar", "-C", str(work.parent), "-czf", "-", old], capture_output=True, check=True).stdout
        return subprocess.run(["age", "-r", recipient], input=tar, capture_output=True, check=True).stdout

    def import_inputs(self, spent=2_500_000, candidate=False):
        value = self.real_inputs("candidate text", import_spent_usd_micros=spent)
        if not candidate:
            value.pop("candidate")
        return self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())

    def import_step(self, inputs, registry, archive):
        from dataclasses import replace
        snapshot = self.push(ArtifactKind.CASE_SNAPSHOT, self.case_key, archive)
        return replace(self.step(inputs, registry), snapshot=snapshot)

    def admitted_registry(self, *cases):
        """A registry holding each (case, statement), admitted through this same adapter."""
        from dataclasses import replace
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        for case, text in cases:
            inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(self.real_inputs(text)).encode())
            result, blobs = self.run_admit(replace(self.step(inputs, registry), case_id=case))
            self.assertEqual(result.outcome, Outcome.OK)
            (self.home / "durable/blobs" / worker_step.blob_name(result.registry)).write_bytes(blobs[worker_step.blob_name(result.registry)])
            registry = result.registry
        self.calls.clear()
        return registry

    def test_a_second_family_that_disagrees_lets_the_idea_through(self):
        from dataclasses import replace
        text = "# Candidate\n\nOversell under checkout."
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(self.real_inputs(text)).encode())
        empty = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        first, blobs = self.run_admit(self.step(inputs, empty))
        (self.home / "durable/blobs" / worker_step.blob_name(first.registry)).write_bytes(blobs[worker_step.blob_name(first.registry)])
        # GLM calls it a duplicate; the second family (the reviewer, not the writer or GLM) disagrees.
        self.duplicate, self.second_agrees = CASE, False
        self.selected = "# Candidate\n\nA different bug: refunds exceed the order."
        second_input = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(self.real_inputs(self.selected)).encode())
        second = replace(self.step(second_input, first.registry), case_id="case-second")
        result, outputs = self.run_admit(second)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:selected"))
        self.assertEqual(self.second_judges, ["openrouter/xiaomi/mimo-v2.6-pro"])
        work, c = self.restore(second, result, outputs)
        self.assertEqual(c.card["dedup"]["duplicate_of"], CASE)
        self.assertEqual(c.card["dedup"]["second_opinion"], {"second_family": "xiaomi", "agreed": False})
        from durable.admission_reasons import inspect_snapshot
        self.assertEqual(inspect_snapshot(self.output(result.snapshot, outputs))["overturned"], ["dedup"])

    def test_second_opinion_refuses_without_a_separate_family(self):
        c = SimpleNamespace(models={"builder": ["openrouter/minimax/minimax-m3.1-flash"],
                                    "attacker": ["openrouter/z-ai/glm-5.3-flash"],
                                    "reviewers": [["openrouter/minimax/minimax-m3"]],
                                    "easy_calibrator": ["openrouter/z-ai/glm-5.3-flash"]})
        with self.assertRaises(ValueError):
            run.second_opinion_chain(c, c.models["easy_calibrator"], (("reviewers", 0), ("attacker", None)))
        # A free route is preferred among eligible judges, and its invocation names its own role.
        c.models["reviewers"] = [["openrouter/xiaomi/mimo-v2.6-pro"]]
        c.models["attacker"] = ["opencode/deepseek-v4.1-flash-free"]
        self.assertEqual(run.second_opinion_chain(c, c.models["easy_calibrator"], (("reviewers", 0), ("attacker", None))),
                         ("attacker", ["opencode/deepseek-v4.1-flash-free"]))

    def test_second_opinion_passes_the_runtime_role_family_check(self):
        """The real ModelRuntime._call binds an invocation to its role's pinned family; each second
        judge's label must map to the role whose model it uses (review of #48)."""
        import copy
        import model_runtime
        from budget import invocation_role
        models = {"builder": ["openrouter/minimax/minimax-m3.1-flash"], "attacker": ["opencode/deepseek-v4.1-flash-free"],
                  "reviewers": [["openrouter/xiaomi/mimo-v2.6-pro"], ["codex/gpt-6.1-sol"]],
                  "easy_calibrator": ["openrouter/z-ai/glm-5.3-flash"]}
        roles = {"writer": models["builder"][0], "stress_tester": models["attacker"][0],
                 "reviewer": models["reviewers"][0][0], "reviewer2": models["reviewers"][1][0],
                 "easy_calibrator": models["easy_calibrator"][0]}
        runtime = model_runtime.ModelRuntime(pathlib.Path(self.home), None, None, None, None)
        class Dispatched(Exception):
            pass
        cases = [(models["easy_calibrator"], (("reviewers", 0), ("attacker", None)), "-second-opinion-dedup", "stress_tester"),
                 (models["reviewers"][0], (("reviewers", 1), ("easy_calibrator", None)), "-second-opinion-idea-realism", "reviewer2")]
        for first, order, suffix, role in cases:
            for drop in (False, True):
                with self.subTest(suffix=suffix, fallback=drop):
                    chosen = dict(models)
                    if drop:   # the fallback judge (easy calibrator for realism, reviewer for dedup)
                        chosen = {**models, "reviewers": models["reviewers"][:1]} if role == "reviewer2" else \
                                 {**models, "attacker": ["openrouter/minimax/minimax-m3"]}
                    c = SimpleNamespace(models=chosen, card={"roles": {k: {"model": v} for k, v in roles.items()}})
                    prefix, chain = run.second_opinion_chain(c, first, order)
                    label = prefix + suffix
                    self.assertEqual(model_runtime.family(roles[invocation_role(label)]), model_runtime.family(chain[0]))
                    # Real boundary: the family check passes, so the call reaches dispatch.
                    with patch.object(model_runtime.copy, "copy", side_effect=Dispatched):
                        with self.assertRaises(Dispatched):
                            runtime._call(c, chain, "text", self.home, label)

    def test_board_dedup_records_only_groups_and_never_changes_the_board(self):
        from dataclasses import replace
        texts = {"case-a": "# A\n\nOversell when two carts check out at once.",
                 "case-b": "# B\n\nTwo simultaneous checkouts sell the last unit twice.",
                 "case-c": "# C\n\nRefund exceeds the order total."}
        registry = self.admitted_registry(*texts.items())
        original = self.model
        seen = {}
        def model(c, models, text, cwd, name, **kwargs):
            if name != "easy-calibrator-board-dedup":
                return original(c, models, text, cwd, name, **kwargs)
            self.calls.append(name)
            request = json.loads(text.rsplit("\n", 1)[-1])
            seen.update({k: pathlib.Path(v).read_text() for k, v in request["statements"].items()})
            pathlib.Path(request["result_path"]).write_text(json.dumps({"groups": [["case-b", "case-a"]]}))
            if kwargs.get("on_complete"):
                c.model_lease = SimpleNamespace(route=models[0])
                kwargs["on_complete"]()
            return 0
        patch.object(run, "model_call", side_effect=model).start()
        patch.object(run, "opencode", side_effect=model).start()
        value = self.real_inputs("unused", board_dedup=True); value.pop("candidate")
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        step_input = replace(self.step(inputs, registry), case_id="case-board-1")
        result, outputs = self.run_admit(step_input)
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:board_planned"))
        self.assertIsNone(result.registry)   # the board is never changed on the worker
        check_result_for(step_input.step, result)
        self.assertEqual(seen, texts)        # every unreleased statement was compared, in worker RAM
        self.assertEqual(self.calls, ["easy-calibrator-board-dedup"])   # no screen, selection or preflight
        work, c = self.restore(step_input, result, outputs)
        self.assertEqual(c.card["board_dedup"], {"entries": 3, "registry_revision": 3, "judge_family": "z-ai",
                                                 "groups": [["case-a", "case-b"]]})
        card = json.dumps(c.card)
        self.assertTrue(all(t not in card for t in texts.values()))
        from durable.board_cleanup import plan_groups
        self.assertEqual(plan_groups(self.output(result.snapshot, outputs)), [["case-a", "case-b"]])
        # A plan cannot carry a candidate or run on an import.
        with self.assertRaises(admit._Invalid):
            admit._inputs(json.dumps(self.real_inputs("x", board_dedup=True)).encode())

    def test_import_keeps_only_the_old_case_tree_and_reruns_every_screen(self):
        old, text = "case-20261019T061459Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.admitted_registry((old, text), ("case-prior", "# Candidate\n\nRefund exceeds the order."))
        inputs = self.import_inputs()
        requests = []
        original = self.model
        self.model = lambda c, models, text_, *a, **kw: (requests.append(text_), original(c, models, text_, *a, **kw))[1]
        patch.object(run, "model_call", side_effect=self.model).start()
        patch.object(run, "opencode", side_effect=self.model).start()
        step_input = self.import_step(inputs, registry, self.legacy_archive(old, text))
        result, outputs = self.run_admit(step_input)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:imported_written"))
        check_result_for(step_input.step, result)
        # Dedup ran against the other prior idea, never against the case's own old entry; no reselection.
        dedup = json.loads(next(t for t in requests if '"earlier_statements"' in t).rsplit("\n", 1)[-1])
        self.assertEqual(set(dedup["earlier_statements"]), {"case-prior"})
        self.assertIn("reviewer-idea-realism", self.calls)
        self.assertFalse(any(name.startswith("builder-selection") for name in self.calls))
        self.freshness.assert_called()
        work, c = self.restore(step_input, result, outputs)
        self.assertEqual((work / "case/statement.md").read_text(), text)
        self.assertTrue((work / "case/guards/reference.py").is_file())
        for gone in ("gate-cache", "public-search.json", "freshness-verdict.json", "agent-state", ".casekey"):
            self.assertFalse((work / gone).exists(), gone)
        self.assertEqual((c.card["case"], c.card["gates"], c.card["failed_gate"]), (CASE, {}, None))
        self.assertEqual(c.card["imported_from"], {"case": old, "source": "port", "gates": {"G1": "pass", "G2": "pass"},
                                                   "failed_gate": None, "spent_usd": 2.5,
                                                   "writer": "opencode-go/minimax-m3", "written": True})
        self.assertEqual(json.loads((work / "continuation-budget.json").read_text())["calls"], 0)
        entries = self.registry_doc(result, outputs)["registry"]["entries"]
        self.assertEqual(entries[old]["status"], "screening")   # the old entry stays occupied
        self.assertEqual(entries[CASE]["statement_sha256"], hashlib.sha256(text.encode()).hexdigest())

    def test_a_hand_repaired_import_keeps_its_tree_reruns_every_screen_and_goes_to_gates(self):
        # 1bb2ad, 17 November: a person fixed the statement and provenance; no writer may touch it.
        old, text = "case-20261019T061459Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.admitted_registry((old, text), ("case-prior", "# Candidate\n\nRefund exceeds the order."))
        value = self.real_inputs("unused", import_spent_usd_micros=2_500_000, import_mode="hand_repaired")
        value.pop("candidate")
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        step_input = self.import_step(inputs, registry, self.legacy_archive(old, text))
        result, outputs = self.run_admit(step_input)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:imported_hand"))
        check_result_for(step_input.step, result)
        self.assertIn("reviewer-idea-realism", self.calls)
        self.assertFalse(any(name.startswith("builder-selection") for name in self.calls))
        work, c = self.restore(step_input, result, outputs)
        self.assertEqual((work / "case/statement.md").read_text(), text)
        self.assertNotIn("recertify", c.card)        # no verdict is kept: every gate runs
        self.assertEqual(c.card["imported_from"]["mode"], "hand_repaired")
        self.assertIs(c.card["recovery_config"]["no_early_probe"], True)   # the probe only labels a hand case
        # Hand repair never combines with recertification (an otherwise valid recertify input).
        both = {k: v for k, v in value.items() if k != "models"}
        both.update(recertify=True, recovery_config={"runs": 10})
        admit._inputs(json.dumps({**both, "import_mode": None}).encode())
        with self.assertRaises(admit._Invalid):
            admit._inputs(json.dumps(both).encode())
        # Without an archive, a hand repair is refused rather than admitting a case a writer would build.
        self.calls.clear()
        result, _ = self.run_admit(self.step(inputs, registry))
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:import_hand"))
        self.assertEqual(self.calls, [])

    def sealed_card(self, **changes):
        """A sealed October card as 18681d and 86b100 have it: G1-G15 passed, models and role efforts."""
        models = {"builder": ["openrouter/minimax/minimax-m3.1-flash"],
                  "attacker": ["openrouter/deepseek/deepseek-v4.1-flash"],
                  "reviewers": [["openrouter/xiaomi/mimo-v2.6-pro"]],
                  "strong_calibrator": ["claude/claude-opus-5-5"],
                  "easy_calibrator": ["opencode/glm-5.3-flash-free"]}
        roles = {role: {"model": models[key][0] if key != "reviewers" else models[key][0][0], "effort": "default"}
                 for key, role in (("builder", "writer"), ("attacker", "stress_tester"), ("reviewers", "reviewer"),
                                   ("strong_calibrator", "strong_calibrator"), ("easy_calibrator", "easy_calibrator"))}
        roles["strong_calibrator"]["effort"] = "high"
        gates = {f"G{i}": "pass" for i in range(1, 16)}
        card = {"gates": gates, "models": models, "roles": roles, "dry_run": False, "difficulty": "hard",
                "gate_results": {"G5": {"reference": "solved"}, "G10": {"strong": 0}, "G13": {"ok": True}}}
        card.update(changes)
        return card

    def recertify_inputs(self, **more):
        more.setdefault("recertify_routes", {"easy_calibrator": "openrouter/z-ai/glm-5.3-flash"})
        more.setdefault("recovery_config", {"pilot_tries": 3, "pilot_runs": 5, "runs": 10})
        value = self.real_inputs("unused", import_spent_usd_micros=2_500_000, recertify=True, **more)
        value.pop("candidate"); value.pop("models")
        return self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())

    def test_a_sealed_case_is_recertified_with_its_october_models_and_kept_verdicts(self):
        old, text = "case-20261017T125556Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.admitted_registry((old, text), ("case-prior", "# Candidate\n\nRefund exceeds the order."))
        card = self.sealed_card()
        archive = self.legacy_archive(old, text, writer=None, gates=card["gates"], card_extra=card)
        step_input = self.import_step(self.recertify_inputs(), registry, archive)
        result, outputs = self.run_admit(step_input)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:imported_sealed"))
        check_result_for(step_input.step, result)
        # Fresh search evidence here; expired evidence would top up with the writer and stress tester.
        self.assertFalse(any(name.startswith("builder") for name in self.calls))
        # Dedup and freshness still run; idea realism is skipped, since the built case passed G9.
        self.assertNotIn("reviewer-idea-realism", self.calls)
        self.assertFalse(any("second-opinion-idea-realism" in name for name in self.calls))
        work, c = self.restore(step_input, result, outputs)
        self.assertEqual((c.card["gates"], c.card["failed_gate"]), ({}, None))
        self.assertEqual(c.card["models"]["builder"], ["openrouter/minimax/minimax-m3.1-flash"])
        # The same-family route swap, with the October effort.
        self.assertEqual(c.card["models"]["easy_calibrator"], ["openrouter/z-ai/glm-5.3-flash"])
        self.assertEqual(c.card["roles"]["easy_calibrator"], {"model": "openrouter/z-ai/glm-5.3-flash", "effort": "default"})
        self.assertEqual(c.card["roles"]["strong_calibrator"]["effort"], "high")
        self.assertEqual(c.card["recertify"], {"case": old, "routes": {"easy_calibrator": "openrouter/z-ai/glm-5.3-flash"},
                                               "gate_results": {"G5": {"reference": "solved"}, "G13": {"ok": True}}})
        self.assertIs(c.card["imported_from"]["recertify"], True)
        self.assertEqual(c.card["idea_realism"], {"approve": True, "carried_from": "G9"})

    def test_a_sealed_archive_without_its_statement_takes_the_one_the_board_holds(self):
        # 86b100: the October seal stored statement.md beside the archive, so the tar lacks it.
        old, text = "case-20261017T120256Z-old", "# Candidate\n\nOversell when two carts check out at once."
        card = self.sealed_card()
        archive = self.legacy_archive(old, text, writer=None, gates=card["gates"], card_extra=card, statement_inside=False)
        registry = self.admitted_registry((old, text), ("case-prior", "# Candidate\n\nRefund exceeds the order."))
        step_input = self.import_step(self.recertify_inputs(), registry, archive)
        result, outputs = self.run_admit(step_input)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:imported_sealed"))
        work, c = self.restore(step_input, result, outputs)
        self.assertEqual((work / "case/statement.md").read_text(), text)
        # A board without that case's statement still refuses the archive by its fixed code.
        empty = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        result, _ = self.run_admit(self.import_step(self.recertify_inputs(), empty, archive))
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:import_layout_statement"))

    def test_recertify_refuses_an_unsealed_card_a_family_change_or_pinned_models(self):
        old, text = "case-20261017T125556Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        unsealed = self.sealed_card()
        del unsealed["gates"]["G16" if "G16" in unsealed["gates"] else "G15"]
        mismatched = self.sealed_card()
        mismatched["roles"]["reviewer"]["model"] = "openrouter/deepseek/deepseek-v4.1-flash"
        for card, inputs, reason in (
                (unsealed, self.recertify_inputs(), "admit:import_recertify"),
                (mismatched, self.recertify_inputs(), "admit:import_recertify"),
                (self.sealed_card(), self.recertify_inputs(recertify_routes={"easy_calibrator": "claude/claude-opus-5-5"}),
                 "admit:import_recertify")):
            with self.subTest(reason=reason, card=card["roles"]["reviewer"]["model"]):
                archive = self.legacy_archive(old, text, writer=None, gates=card["gates"], card_extra=card)
                result, _ = self.run_admit(self.import_step(inputs, registry, archive))
                self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, reason))
        archive = self.legacy_archive(old, text, writer=None, gates=self.sealed_card()["gates"], card_extra=self.sealed_card())
        pinned = self.real_inputs("unused", import_spent_usd_micros=2_500_000, recertify=True, recovery_config={})
        pinned.pop("candidate")   # still pins models
        unconfigured = self.real_inputs("unused", import_spent_usd_micros=2_500_000, recertify=True)
        unconfigured.pop("candidate"); unconfigured.pop("models")   # the exam needs a recovery_config
        for value in (pinned, unconfigured):
            inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
            result, _ = self.run_admit(self.import_step(inputs, registry, archive))
            self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, "admit:inputs_invalid"))
        # Without a sealed import, recertify is refused rather than admitting a fresh case.
        result, _ = self.run_admit(self.step(self.recertify_inputs(), registry))
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:import_recertify"))
        self.assertEqual(self.calls, [])
        # The writer and stress tester may still be called (freshness top-ups), so they need a bounded route.
        muse = self.sealed_card()
        muse["models"]["builder"] = ["openrouter/meta/muse-spark-1.3-contributor"]
        muse["roles"]["writer"]["model"] = "openrouter/meta/muse-spark-1.3-contributor"
        archive = self.legacy_archive(old, text, writer=None, gates=muse["gates"], card_extra=muse)
        # Muse (86b100's October writer) is capped since 2026-11-09, so an unbounded writer is simulated here.
        import model_router
        bounded = model_router.route_maximum
        with patch.object(model_router, 'route_maximum', lambda r: None if 'muse' in r else bounded(r)):
            result, _ = self.run_admit(self.import_step(self.recertify_inputs(), registry, archive))
        self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, "router:unbounded_route"))

    @patch.object(__import__('model_router'), 'CHAINS', WALLED_GLM_UNBOUNDED)
    def test_unpinned_import_takes_the_first_slot_with_the_october_writer_family(self):
        from model_router import family
        old, text = "case-20261019T061459Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        value = self.real_inputs("unused", import_spent_usd_micros=2_500_000)
        value.pop("candidate"); value.pop("models")
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        for writer, slot in (("claude/claude-opus-5-5", 1), ("opencode-go/deepseek-v4", 7)):
            with self.subTest(writer=writer):
                step_input = self.import_step(inputs, registry, self.legacy_archive(old, text, writer=writer))
                result, outputs = self.run_admit(step_input)
                # Past the family check; the offline router has no bounded route for the table's models.
                self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, "router:unbounded_route"))
                _, c = self.restore(step_input, result, outputs)
                self.assertEqual(c.card["rotation_slot"], slot)
                self.assertEqual(family(c.card["roles"]["writer"]["model"]), family(writer))
                self.assertNotEqual(family(c.card["roles"]["strong_calibrator"]["model"]), family(writer))
                self.assertEqual(self.calls, [])

    def test_the_writer_comes_only_from_the_archive_and_must_agree(self):
        old, text = "case-20261019T061459Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        inputs = self.import_inputs()
        ledger = lambda model: {"continuation_budget": {"cost": 2.5, "events": [
            {"id": "e1", "role": "writer", "invocation": "builder-1", "configured_model": model, "cost": 1.0}]}}
        for card_extra, reason in ((ledger("opencode/minimax-m3.1-flash-free"), "admit:imported_written"),
                                   ({"roles": {"writer": {"model": "opencode/minimax-m3.1-flash-free"}}}, "admit:imported_written"),
                                   (ledger("openrouter/deepseek/deepseek-v4.1-flash"), "admit:import_writer"),
                                   ({}, "admit:import_writer_none"),
                                   # Fixed codes say which structural part an archive lacks.
                                   ({"case": "case-20261019T061459Z-other"}, "admit:import_layout_card_case")):
            with self.subTest(card_extra=card_extra):
                # An October checkpoint card without models.builder (5813be): its ledger's writer
                # calls or writer role name the family; a disagreeing record, or none, refuses.
                archive = self.legacy_archive(old, text, writer=None, card_extra=card_extra)
                result, _ = self.run_admit(self.import_step(inputs, registry, archive))
                self.assertEqual(result.reason, reason)
        # A builder pin that disagrees with the ledger's writer calls refuses too.
        archive = self.legacy_archive(old, text, writer="opencode-go/minimax-m3",
                                      card_extra=ledger("openrouter/deepseek/deepseek-v4.1-flash"))
        result, _ = self.run_admit(self.import_step(inputs, registry, archive))
        self.assertEqual(result.reason, "admit:import_writer_conflict")

    def test_unwritten_import_continues_with_the_writer(self):
        old, text = "case-20261019T061459Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        result, _ = self.run_admit(self.import_step(self.import_inputs(), registry, self.legacy_archive(old, text, gates={})))
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:selected"))

    def test_rejected_import_ends_without_choosing_another_idea(self):
        old, text = "case-20261019T061459Z-old", "# Candidate\n\nOversell when two carts check out at once."
        self.freshness.return_value = (False, {"outcome": "public_match"})
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        step_input = self.import_step(self.import_inputs(), registry, self.legacy_archive(old, text))
        result, outputs = self.run_admit(step_input)
        # No reviewer verdict on disk: the screen is still named, its evidence is "unrecorded".
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:freshness_unrecorded"))
        self.assertFalse(any(name.startswith("builder-selection") for name in self.calls))
        work, c = self.restore(step_input, result, outputs)
        self.assertEqual(len(c.card["rejected_candidates"]), 1)

    def test_freshness_rejection_names_the_confirmed_source_kind_without_urls(self):
        old, text = "case-20261019T061459Z-old", "# Candidate\n\nOversell when two carts check out at once."
        secret = "private-why-sentinel"
        def g2(c):
            hits = [{"url": "https://github.com/medusajs/medusa/releases/tag/v2.19.4", "resolved": True,
                     "same_bug": True, "retrieved": True, "retrieved_from": "live", "app_version": "2.19.0",
                     "version_scope": secret, "why": secret},
                    {"url": "https://github.com/medusajs/medusa/issues/12345", "resolved": True, "same_bug": True,
                     "retrieved": True, "retrieved_from": "archive", "app_version": "2.19.0", "version_scope": secret,
                     "why": secret},
                    {"url": "https://blog.example/" + secret, "resolved": True, "same_bug": False, "retrieved": True,
                     "app_version": "2.19.0", "version_scope": secret, "why": secret}]
            (c.work / "freshness-verdict.json").write_text(json.dumps({"hits": hits}))
            return False, {"outcome": "public_match"}
        self.freshness.side_effect = g2
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        step_input = self.import_step(self.import_inputs(), registry, self.legacy_archive(old, text))
        result, outputs = self.run_admit(step_input)
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:freshness_upstream_fix"))
        from durable.classify import PUBLISHED_REASONS
        self.assertIn(result.reason, PUBLISHED_REASONS)
        work, c = self.restore(step_input, result, outputs)
        codes = c.card["rejected_candidates"][0]["codes"]
        self.assertEqual(codes, {"screen": "freshness", "evidence": "upstream_fix", "confirmed_hits": 2,
                                 "sources": ["upstream_issue", "upstream_release"], "archived_hits": 1,
                                 "pin_version": "2.19.0", "judge_family": "xiaomi",
                                 "fix_releases": [{"version": "2.19.4", "relation": "after_pin"}]})
        self.assertNotIn(secret, json.dumps(codes))
        self.assertNotIn("github.com", json.dumps(codes))

    def test_realism_rejection_names_the_screen_and_judge_family(self):
        statement = "# Candidate\n\nOversell under concurrent checkout."
        original = self.model
        def model(c, models, text, cwd, name, **kwargs):
            if name == "reviewer-idea-realism":
                self.calls.append(name)
                target = text.split('Write JSON to ')[1].split(': {')[0]
                pathlib.Path(target).write_text(json.dumps({"approve": False, "reason": "private-reason-sentinel"}))
                if kwargs.get("on_complete"):
                    c.model_lease = SimpleNamespace(route=models[0])
                    kwargs["on_complete"]()
                return 0
            return original(c, models, text, cwd, name, **kwargs)
        patch.object(run, "model_call", side_effect=model).start()
        patch.object(run, "opencode", side_effect=model).start()
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(self.real_inputs(statement)).encode())
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        step_input = self.step(inputs, registry)
        result, outputs = self.run_admit(step_input)
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:realism_rejected"))
        work, c = self.restore(step_input, result, outputs)
        self.assertEqual(c.card["rejected_candidates"][0]["codes"],
                         {"screen": "realism", "evidence": "rejected", "judge_family": "xiaomi",
                          "second_family": "z-ai", "agreed": True})
        self.assertNotIn("private-reason-sentinel", json.dumps(c.card["rejected_candidates"]))

    def test_import_refuses_another_app_pin_or_an_unreadable_archive(self):
        old, text = "case-20261019T061459Z-old", "# Candidate\n\nOversell."
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        inputs = self.import_inputs()
        wrong_spend, with_candidate = self.import_inputs(spent=2_400_000), self.import_inputs(candidate=True)
        foreign = subprocess.run(["age", "-r", subprocess.run(["age-keygen"], capture_output=True, check=True)
                                  .stdout.decode().split("public key: ")[1].split()[0]],
                                 input=b"not yours", capture_output=True, check=True).stdout
        # Each refusal names its check (fixed codes only), so a real archive's refusal is diagnosable.
        cases = [(inputs, self.legacy_archive(old, text, commit="b" * 40), "import_pin"),
                 (inputs, self.legacy_archive(old, text, commit="v2.18.0"), "import_pin"),
                 (inputs, self.legacy_archive(old, text, writer="opencode-go/deepseek-v4"), "import_writer"),
                 (inputs, self.legacy_archive(old, text, link=True), "import_links"),
                 (wrong_spend, self.legacy_archive(old, text), "import_spend"),
                 (with_candidate, self.legacy_archive(old, text), "import_source"),
                 (inputs, foreign, "import_key")]
        # The worker's environment failing is infrastructure, retried; it never refuses the case.
        import worker_secrets
        archive = self.legacy_archive(old, text)
        with patch.object(worker_secrets, "SECRETS", self.home / "no-key"):
            result, _ = self.run_admit(self.import_step(inputs, registry, archive))
        self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, "admit:processing_failed"))
        from durable.classify import PUBLISHED_REASONS
        self.assertTrue({"admit:" + code for code in admit.IMPORT_REFUSALS} <= PUBLISHED_REASONS)
        for step_inputs, archive, code in cases:
            result, _ = self.run_admit(self.import_step(step_inputs, registry, archive))
            # Deterministic refusals end admission instead of retrying on new workers.
            self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:" + code))
            self.assertEqual(self.calls, [])
        # October trees name the pinned release by tag and the repo by URL, with the lockfile hash;
        # the bench image pins Medusa 2.19.0 (b5521c's real case.json, 7 November).
        lock = hashlib.sha256((pathlib.Path(os.environ["BENCH"]) / "projects/medusa/package-lock.json").read_bytes()).hexdigest()
        for commit, repo, lockfile, reason in (
                ("v2.19.0", "medusajs/medusa", None, "admit:imported_written"),
                ("2.19.0", "medusajs/medusa", None, "admit:imported_written"),
                ("v2.19.0", "https://github.com/medusajs/medusa", lock, "admit:imported_written"),
                ("v2.19.0", "https://github.com/medusajs/medusa", "0" * 64, "admit:import_pin"),
                ("v2.19.0", "https://github.com/someone/medusa", lock, "admit:import_pin")):
            result, _ = self.run_admit(self.import_step(inputs, registry,
                self.legacy_archive(old, text, commit=commit, repo=repo, lockfile=lockfile)))
            self.assertEqual(result.reason, reason, (commit, repo, lockfile))
        # A checkpoint's own card may predate the public card the operator copies: a higher
        # declared spend is accepted and is what the case is charged.
        result, outputs = self.run_admit(self.import_step(self.import_inputs(spent=3_000_000), registry,
                                                          self.legacy_archive(old, text)))
        self.assertEqual(result.reason, "admit:imported_written")

    # Idea-only import (5813be, 25fbfa): only the admitted statement and case metadata survive.
    OCTOBER_5813BE = {"roles": {"writer": {"model": "opencode/minimax-m3.1-flash-free"}},
                      "model_transition": {"kind": "approved-paid-to-free",
                                           "before": {"writer": {"model": "opencode-go/mimo-v2.6-pro"}},
                                           "after": {"writer": {"model": "opencode/minimax-m3.1-flash-free"}}},
                      "continuation_budget": {"cost": 2.5, "events": [
                          {"id": "e1", "role": "writer", "invocation": "builder-1",
                           "configured_model": "opencode-go/mimo-v2.6-pro", "cost": 1.0}]}}

    def idea_value(self):
        value = self.real_inputs("unused", import_spent_usd_micros=2_500_000, import_mode="idea_only")
        value.pop("candidate")
        # The default reviewer is MiMo, an idea author's family, which no judge may share; GLM may.
        # With the writer, stress tester and strong calibrator that leaves OpenAI for the second reviewer.
        value["models"]["reviewers"] = [["openrouter/z-ai/glm-5.3-flash"], ["codex/gpt-6.1-sol"]]
        return value

    def idea_inputs(self, value=None):
        return self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value or self.idea_value()).encode())

    def test_idea_only_import_keeps_the_statement_and_starts_at_writer(self):
        old, text = "case-20261017T212113Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.admitted_registry((old, text), ("case-prior", "# Candidate\n\nRefund exceeds the order."))
        # The October writer moved from MiMo to MiniMax and the draft passed G1: the strict import refuses.
        archive = self.legacy_archive(old, text, writer=None, card_extra=self.OCTOBER_5813BE)
        result, _ = self.run_admit(self.import_step(self.import_inputs(), registry, archive))
        self.assertEqual(result.reason, "admit:import_writer_conflict")
        step_input = self.import_step(self.idea_inputs(), registry, archive)
        result, outputs = self.run_admit(step_input)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:selected"))   # WRITER, not STRESS
        check_result_for(step_input.step, result)
        self.assertIn("reviewer-idea-realism", self.calls)
        self.assertFalse(any(name.startswith("builder-selection") for name in self.calls))
        work, c = self.restore(step_input, result, outputs)
        self.assertEqual(sorted(p.name for p in (work / "case").iterdir()), ["case.json", "promise.md", "statement.md"])
        self.assertEqual((work / "case/statement.md").read_text(), text)
        # The October case.json held the old draft's design: only the batch's metadata remains.
        self.assertEqual(json.loads((work / "case/case.json").read_text()), {
            "source": "port", "app": {"repo": "medusajs/medusa", "commit": "a" * 40},
            "promise_paths": ["store-checkout"], "promise_checks": [], "leak_words": []})
        for gone in ("gate-cache", "public-search.json", "freshness-verdict.json", "agent-state", ".casekey"):
            self.assertFalse((work / gone).exists(), gone)
        self.assertEqual((c.card["gates"], c.card["failed_gate"]), ({}, None))
        self.assertEqual(c.card["imported_from"], {"case": old, "source": "port", "gates": {"G1": "pass", "G2": "pass"},
                                                   "failed_gate": None, "spent_usd": 2.5, "mode": "idea_only",
                                                   "idea_families": ["minimax", "xiaomi"], "case_json": "checked",
                                                   "written": False})
        entries = self.registry_doc(result, outputs)["registry"]["entries"]
        self.assertEqual(entries[CASE]["statement_sha256"], hashlib.sha256(text.encode()).hexdigest())
        # A statement other than the one the old case had admitted is not that idea.
        self.calls.clear()
        edited = self.legacy_archive(old, text + "\nEdited later.", writer=None, card_extra=self.OCTOBER_5813BE)
        result, _ = self.run_admit(self.import_step(self.idea_inputs(), registry, edited))
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:import_idea_statement"))
        self.assertEqual(self.calls, [])

    def test_idea_only_import_keeps_idea_authors_out_of_judging_and_needs_a_supported_writer(self):
        old, text = "case-20261017T212113Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        archive = self.legacy_archive(old, text, writer=None, card_extra=self.OCTOBER_5813BE)
        mimo_reviewer = self.idea_value()
        mimo_reviewer["models"]["reviewers"] = [["openrouter/xiaomi/mimo-v2.6-pro"], ["codex/gpt-6.1-sol"]]
        mimo_dedup = self.idea_value()
        mimo_dedup["models"]["reviewers"] = [["openrouter/z-ai/glm-5.3-flash"], ["codex/gpt-6.1-sol"]]
        mimo_dedup["models"]["easy_calibrator"] = ["openrouter/xiaomi/mimo-v2.6-pro"]
        for value in (mimo_reviewer, mimo_dedup):
            result, _ = self.run_admit(self.import_step(self.idea_inputs(value), registry, archive))
            self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:import_idea_family"))
        # Slot 1's writer is Claude: idea-only hands the statement only to MiniMax or DeepSeek.
        value = self.idea_value(); value.pop("models"); value["rotation_slot"] = 1
        result, _ = self.run_admit(self.import_step(self.idea_inputs(value), registry, archive))
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:import_idea_writer"))
        # No author recorded at all: the family rule cannot be checked, so the import refuses.
        bare = self.legacy_archive(old, text, writer=None)
        result, _ = self.run_admit(self.import_step(self.idea_inputs(), registry, bare))
        self.assertEqual(result.reason, "admit:import_writer_none")
        self.assertEqual(self.calls, [])

    @patch.object(__import__('model_router'), 'CHAINS', WALLED_GLM_UNBOUNDED)
    def test_unpinned_idea_only_import_takes_a_supported_writer_slot(self):
        import model_runtime
        from model_router import family
        old, text = "case-20261020T095024Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        value = self.idea_value(); value.pop("models")
        inputs = self.idea_inputs(value)
        for card_extra, authors in ((self.OCTOBER_5813BE, {"minimax", "xiaomi"}),
                                    ({"roles": {"writer": {"model": "opencode/deepseek-v4.1-flash-free"}}}, {"deepseek"}),
                                    # October ledger events name no role; `models_used` names the builder calls.
                                    ({"roles": {"writer": {"model": "opencode/deepseek-v4.1-flash-free"}},
                                      "models_used": {"builder-1": "opencode-go/mimo-v2.6-pro"}}, {"deepseek", "xiaomi"})):
            with self.subTest(authors=authors):
                archive = self.legacy_archive(old, text, writer=None, card_extra=card_extra)
                step_input = self.import_step(inputs, registry, archive)
                result, outputs = self.run_admit(step_input)
                # Past the family checks; the offline router has no bounded route for the table's models.
                self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, "router:unbounded_route"))
                _, c = self.restore(step_input, result, outputs)
                roles = c.card["roles"]
                self.assertIn(family(roles["writer"]["model"]), authors)   # an author's family, when supported
                self.assertNotIn(family(roles["reviewer"]["model"]), authors)
                self.assertEqual(roles["writer"]["model"], model_runtime.rotation(c.card["rotation_slot"])["writer"]["model"])
        self.assertEqual(self.calls, [])

    def test_idea_only_import_rebuilds_missing_case_metadata_from_the_batch(self):
        old, text = "case-20261020T095024Z-old", "# Candidate\n\nOversell when two carts check out at once."
        registry = self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, b"")
        archive = self.legacy_archive(old, text, writer=None, meta=False, gates={},
                                      card_extra={"roles": {"writer": {"model": "opencode/deepseek-v4.1-flash-free"}}})
        result, _ = self.run_admit(self.import_step(self.import_inputs(), registry, archive))
        self.assertEqual(result.reason, "admit:import_layout_meta")   # the strict import still needs it
        step_input = self.import_step(self.idea_inputs(), registry, archive)
        result, outputs = self.run_admit(step_input)
        self.assertEqual((result.outcome, result.reason), (Outcome.OK, "admit:selected"))
        work, c = self.restore(step_input, result, outputs)
        self.assertEqual(json.loads((work / "case/case.json").read_text()), {
            "source": "port", "app": {"repo": "medusajs/medusa", "commit": "a" * 40},
            "promise_paths": ["store-checkout"], "promise_checks": [], "leak_words": []})
        self.assertEqual((c.card["imported_from"]["case_json"], c.card["imported_from"]["idea_families"]),
                         ("missing", ["deepseek"]))
        # Without case.json only the old card names the source; it must be this batch's.
        hunt = self.legacy_archive(old, text, writer=None, meta=False,
                                   card_extra={"source": "hunt", "roles": {"writer": {"model": "opencode/deepseek-v4.1-flash-free"}}})
        result, _ = self.run_admit(self.import_step(self.idea_inputs(), registry, hunt))
        self.assertEqual((result.outcome, result.reason), (Outcome.EXHAUSTED, "admit:import_source"))
        # An unknown import mode is malformed INPUTS.
        value = self.idea_value(); value["import_mode"] = "draft_only"
        result, _ = self.run_admit(self.import_step(self.idea_inputs(value), registry, archive))
        self.assertEqual(result.reason, "admit:inputs_invalid")

    @patch.object(__import__('model_router'), 'CHAINS', WALLED_GLM_UNBOUNDED)
    def board(self, cases):
        """A registry plaintext whose board already holds `cases` (earlier batches' admissions)."""
        entries, objects = {}, {}
        for i, case in enumerate(cases, 1):
            data = b"age-encryption.org/v1\n" + case.encode()
            digest = hashlib.sha256(data).hexdigest()
            objects[digest] = base64.b64encode(data).decode()
            entries[case] = {"version": 1, "case_id": case, "status": "completed", "complete": True,
                             "reservation": f"r{i}", "registry_revision": i, "statements": {},
                             "cipher_sha256": digest, "statement_sha256": None}
        return json.dumps({"version": 1, "registry": {"revision": len(cases), "entries": entries},
                           "objects": objects, "refs": {}}).encode()

    @patch.object(__import__('model_router'), 'CHAINS', WALLED_GLM_UNBOUNDED)
    def test_campaign_wide_admissions_cycle_the_role_rotation(self):
        # Every durable case is a one-case batch (ordinal 1): the board's earlier cases, carried
        # batch to batch, choose the slot. The case's own entry (a retry) is not counted.
        from dataclasses import replace
        import model_runtime
        value = self.real_inputs("# Candidate\n\nA checkout failure.")
        value.pop('models')
        inputs = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(value).encode())
        for earlier, slot in ((0, 1), (3, 4), (7, 8), (8, 1), (12, 5)):
            case = f"case-b{earlier}-1"
            board = self.board([f"case-b{i}-1" for i in range(earlier)] + [case])
            si = replace(self.step(inputs, self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key, board)),
                         case_id=case)
            result, blobs = self.run_admit(si)
            self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, 'router:unbounded_route'))
            _, c = self.restore(si, result, blobs)
            self.assertEqual(c.card["rotation_slot"], slot)
            self.assertEqual(c.card["roles"]["writer"]["model"], model_runtime.rotation(slot)["writer"]["model"])
        # An explicit slot still wins over the board's count.
        pinned = self.push(ArtifactKind.INPUTS, self.batch_key, json.dumps(dict(value, rotation_slot=6)).encode())
        si = replace(self.step(pinned, self.push(ArtifactKind.STATEMENT_REGISTRY, self.batch_key,
                                                 self.board(["case-a-1", "case-b-1"]))), case_id="case-pin-1")
        result, blobs = self.run_admit(si)
        self.assertEqual(self.restore(si, result, blobs)[1].card["rotation_slot"], 6)
        self.assertEqual(self.calls, [])

    def test_unbounded_strong_or_second_reviewer_stops_before_any_model_spend(self):
        for role in ('strong_calibrator', 'reviewers'):
            value = self.real_inputs('unused')
            # codex/gpt-6.1-sol is bounded now (CODEX_PROFILES); an unpriced Codex model still is not.
            if role == 'strong_calibrator': value['models'][role] = ['codex/gpt-unpriced']
            else: value['models'][role].append(['codex/gpt-unpriced'])
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
        models['reviewers'].append(['opencode-go/glm-5.3-flash'])  # the rotation would add a second reviewer
        roles = {'writer': models['builder'][0], 'stress_tester': models['attacker'][0],
                 'reviewer': models['reviewers'][0][0], 'reviewer2': models['reviewers'][1][0],
                 'strong_calibrator': models['strong_calibrator'][0],
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
