"""Offline composition checks; SQLite is not PostgreSQL qualification."""
import base64
from contextlib import nullcontext
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "factory"))
from durable.runtime import Runtime, RuntimeErrorCode, private_bytes, load_config
from durable.engine import APP_VERSION
from durable.artifacts import AgeSealer, LocalObjects
from durable.contract import ArtifactKind, Ref, BatchSpec, to_record
from durable.cli import dispatch, backup, main
from durable.workers import BoatPool, PoolError, ReleaseStore, ownership_name


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        identity = self.root / "identity"
        subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
        identity.chmod(0o600)
        recipient = subprocess.run(["age-keygen", "-y", str(identity)], check=True, capture_output=True).stdout.decode().strip()
        self.config = dict(database_url="sqlite:///" + str(self.root / "db"),
                           state_dir=str(self.root / "state"), pool_id="offline",
                           restore_identity=str(identity), restore_recipient=recipient,
                           founder_recipient=recipient, local_objects=str(self.root / "objects"),
                           application_version=APP_VERSION)

    def runtime(self):
        runtime = Runtime(self.config)
        self.addCleanup(runtime.close)
        return runtime

    def test_real_composition_exports_recoverable_scope_key(self):
        runtime = self.runtime()
        self.assertEqual(runtime.channel.output_retry_s, 60)
        ref = runtime.prepare("b-offline", ArtifactKind.INPUTS, b"opaque secret inputs")
        wrapped = runtime.store.objects.get("durable/b-offline/scope-key.age")
        opened = subprocess.run(["age", "-d", "-i", self.config["restore_identity"]], input=wrapped, check=True, capture_output=True).stdout
        key = base64.b64decode(opened.strip().split()[-1])
        self.assertEqual(AgeSealer().open(key, ref, runtime.store.get_sealed("b-offline", ref)), b"opaque secret inputs")
        self.assertNotIn(b"opaque secret inputs", runtime.store.get_sealed("b-offline", ref))
        self.assertIs(runtime.executor.ledger, runtime.ledger)
        self.assertIs(runtime.channel.keys, runtime.keys)

    def test_export_failure_prevents_artifact_acknowledgment(self):
        runtime = self.runtime()
        with patch.object(runtime.store.objects, "put", side_effect=OSError("secret")):
            with self.assertRaises(OSError):
                runtime.prepare("b-offline", ArtifactKind.INPUTS, b"secret")
        self.assertEqual(list((self.root / "objects").glob("**/*.inputs.age")), [])

    def test_recovery_precedes_launch_and_failure_retains_journal(self):
        runtime = self.runtime()
        record = runtime.pool.state / "case-one.json"
        record.write_text("ownership")
        with patch.object(runtime.pool, "recover", side_effect=ValueError("transport")), patch.object(runtime.engine, "launch") as launch:
            with self.assertRaises(ValueError):
                runtime.launch()
            launch.assert_not_called()
        self.assertEqual(record.read_text(), "ownership")
        order = []
        with patch.object(runtime.pool, "recover", side_effect=lambda: order.append("recover")), patch.object(runtime.engine, "launch", side_effect=lambda: order.append("launch")):
            runtime.launch()
        runtime.launched = False
        self.assertEqual(order, ["recover", "launch"])

    def test_real_recover_inventory_failure_keeps_ownership(self):
        runtime = self.runtime()
        runtime.pool._write("case-one", dict(worker="bx_12345678", intent=None, deleting=None))
        path = runtime.pool._record_path("case-one")
        original = path.read_bytes()
        with patch.object(runtime.pool.boat, "run", return_value=(1, b"")), patch.object(runtime.engine, "launch") as launch:
            with self.assertRaises(Exception):
                runtime.launch()
            launch.assert_not_called()
        self.assertEqual(path.read_bytes(), original)

    def test_restored_ownership_resolves_only_saved_case_hashes(self):
        runtime = self.runtime()
        (runtime.state / "restored.json").write_text("{}")
        nonce = "1" * 32
        record = dict(worker=None, intent=nonce, deleting=None)
        runtime.pool._write("case-one", record)
        owned = dict(id="bx_12345678", state="idle", name=ownership_name("offline", "case-one", nonce))
        unknown = dict(id="bx_87654321", state="idle", name=ownership_name("offline", "case-newer", nonce))
        (runtime.state / "restored.json").write_text('{"quarantined": true}')
        with patch.object(runtime.pool, "_inventory", return_value=[unknown]), patch.object(runtime.engine, "launch") as launch:
            with self.assertRaisesRegex(RuntimeErrorCode, "restore_unclaimed_worker"):
                runtime.launch()
            launch.assert_not_called()
        self.assertEqual(runtime.pool._read("case-one"), record)
        # A restore of a stopped source has no newer inventory: its stray sandbox is deleted, no human needed.
        (runtime.state / "restored.json").write_text("{}")
        with patch.object(runtime.pool, "_inventory", return_value=[unknown]), patch.object(runtime.pool, "_delete_raw") as delete, patch.object(runtime.engine, "launch") as launch:
            runtime.launch()
            launch.assert_called_once()
            delete.assert_called_once_with(unknown["id"])
        self.assertTrue((runtime.state / "restored.json").exists())   # the restore's attestation is never removed
        runtime.launched = False
        (runtime.state / "restored.json").write_text("{}")
        with patch.object(runtime.pool, "_inventory", return_value=[owned]), patch.object(runtime.pool, "recover") as recover, patch.object(runtime.engine, "launch") as launch:
            runtime.launch()
            launch.assert_called_once()
            recover.assert_not_called()
        runtime.launched = False
        self.assertEqual(runtime.pool._read("case-one"), {**record, "worker": owned["id"]})
        for name in [None, ownership_name("offline", "case-one", "2" * 32)]:
            with patch.object(runtime.pool, "_inventory", return_value=[{**owned, "name": name}]), patch.object(runtime.engine, "launch") as launch:
                with self.assertRaises(PoolError):
                    runtime.launch()
                launch.assert_not_called()

    def test_quarantine_then_reconcile_then_launch_keeps_the_attestation_and_the_refusal(self):
        stray = dict(id="bx_87654321", state="idle", name=ownership_name("offline", "case-newer", "1" * 32))
        attested = {"quarantined": True, "reconciled": {"at": "2026-11-06T00:00:00+00:00", "ownership": True,
                                                         "spending": True, "cleared": []}}
        state = Path(self.config["state_dir"])
        state.mkdir(mode=0o700)
        (state / "restored.json").write_text(json.dumps({"quarantined": True}))
        (state / "cold-backup.json").write_text('{"retired": true}')
        with self.assertRaisesRegex(RuntimeErrorCode, "source_fenced_resume_or_restore_required"):
            Runtime(self.config)   # not reconciled: it can never launch
        # backup.reconcile saves the attestation, then removes the fence.
        (state / "restored.json").write_text(json.dumps(attested))
        (state / "cold-backup.json").unlink()
        runtime = self.runtime()
        # An unexplained sandbox refuses the first launch, and keeps the attestation.
        with patch.object(runtime.pool, "_inventory", return_value=[stray]), patch.object(runtime.pool, "recover") as recover, \
                patch.object(runtime.pool, "_delete_raw") as delete, patch.object(runtime.engine, "launch") as launch:
            with self.assertRaisesRegex(RuntimeErrorCode, "restore_unclaimed_worker"):
                runtime.launch()
            recover.assert_not_called(); delete.assert_not_called(); launch.assert_not_called()
        self.assertEqual(json.loads((runtime.state / "restored.json").read_text()), attested)
        with patch.object(runtime.pool, "_inventory", return_value=[]), patch.object(runtime.engine, "launch"):
            runtime.launch()
        runtime.launched = False
        self.assertEqual(json.loads((runtime.state / "restored.json").read_text()), {**attested, "launched": True})
        # After a clean launch a reboot needs no human: a stray is a late create of ours.
        with patch.object(runtime.pool, "_inventory", return_value=[stray]), patch.object(runtime.pool, "_delete_raw") as delete, \
                patch.object(runtime.engine, "launch") as launch:
            runtime.launch()
            delete.assert_called_once_with(stray["id"]); launch.assert_called_once()
        runtime.launched = False
        self.assertEqual(json.loads((runtime.state / "restored.json").read_text()), {**attested, "launched": True})

    def test_a_failing_sweep_logs_a_fixed_code_and_keeps_running(self):
        import durable.runtime as runtime_module
        runtime = self.runtime()
        with patch.object(runtime_module, "SWEEP_INTERVAL_S", 0.05), patch.object(runtime.pool, "recover"), \
                patch.object(runtime.engine, "launch"), patch.object(runtime.pool, "sweep", side_effect=OSError("/private/case")) as sweep, \
                self.assertLogs("durable.runtime", "WARNING") as logs:
            runtime.launch()
            for _ in range(100):
                if sweep.call_count >= 2:
                    break
                time.sleep(0.05)
            runtime.launched = False
            runtime.close()
        self.assertGreaterEqual(sweep.call_count, 2)
        self.assertEqual(set(logs.output), {"WARNING:durable.runtime:pool sweep failed: infra:sweep_failed"})

    def test_launch_sweeps_the_pool_periodically_until_close(self):
        import durable.runtime as runtime_module
        runtime = self.runtime()
        with patch.object(runtime_module, "SWEEP_INTERVAL_S", 0.05), patch.object(runtime.pool, "recover"), \
                patch.object(runtime.engine, "launch"), patch.object(runtime.pool, "sweep", side_effect=[OSError("outage"), None, None, None]) as sweep:
            runtime.launch()
            for _ in range(100):
                if sweep.call_count >= 3:
                    break
                time.sleep(0.05)
            self.assertGreaterEqual(sweep.call_count, 3)   # a failed pass does not end the loop
            runtime.launched = False
            runtime.close()
            settled = sweep.call_count
            time.sleep(0.3)
            self.assertLessEqual(sweep.call_count, settled + 1)

    def test_real_recover_empty_inventory_before_launch(self):
        runtime = self.runtime()
        with patch.object(runtime.pool.boat, "run", return_value=(0, b'{"sandboxes": [], "pageInfo": {"hasMore": false}}')) as transport, patch.object(runtime.engine, "launch") as launch:
            runtime.launch()
            transport.assert_called()
            launch.assert_called_once()
        runtime.launched = False

    def test_opaque_start_records_only_refs(self):
        runtime = self.runtime()
        inputs = runtime.prepare("b-offline", ArtifactKind.INPUTS, b"arbitrary admission payload")
        registry = runtime.prepare("b-offline", ArtifactKind.STATEMENT_REGISTRY, b"opaque registry")
        spec = BatchSpec(batch_id="b-offline", plumbing_version="a" * 64,
                         bench_version="b" * 64, app_repo="medusajs/medusa", app_commit="c" * 40,
                         inputs=inputs, target_sealed=1, money_bound_usd_micros=100,
                         deadline_epoch=4e9, max_concurrency=1)
        with patch("dbos.DBOS.get_workflow_status", return_value=None), patch.object(runtime.releases, "bundle", return_value=b"bundle"), patch.object(runtime.engine, "start_batch") as start:
            self.assertEqual(runtime.start(to_record(spec), to_record(registry)), {"batch_id": "b-offline"})
            start.assert_called_once_with(spec, registry, None, None)
            self.assertNotIn("arbitrary admission payload", repr(start.call_args))
        for state in ("SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"):
            with patch("dbos.DBOS.get_workflow_status", return_value=SimpleNamespace(status=state)), patch.object(runtime.engine, "start_batch") as start:
                with self.assertRaisesRegex(RuntimeErrorCode, "batch_already_finished"):
                    runtime.start(to_record(spec), to_record(registry))
                start.assert_not_called()

    def test_resume_counts_the_earlier_spend_against_one_case_ceiling(self):
        from durable.contract import Usage
        runtime = self.runtime()
        old_inputs = runtime.prepare("b-old", ArtifactKind.INPUTS, b'{"import_spent_usd_micros": 5000000}')
        old = BatchSpec(batch_id="b-old", plumbing_version="a" * 64, bench_version="b" * 64,
                        app_repo="medusajs/medusa", app_commit="c" * 40, inputs=old_inputs, target_sealed=1,
                        money_bound_usd_micros=100, deadline_epoch=4e9, max_concurrency=1)
        # $10 in the original batch and $20 in an earlier resume of the same case, plus $5 imported.
        for batch, paid in (("b-old", 10_000_000), ("b-mid", 20_000_000)):
            runtime.ledger.open(batch, 100_000_000)
            key = f"case-old-1/{paid}/writer:1/1"
            runtime.ledger.reserve(batch, "case-old-1", key, paid, 50_000_000)
            runtime.ledger.settle(key, Usage(paid_usd_micros=paid))
        inputs = runtime.prepare("b-new", ArtifactKind.INPUTS, b"{}")
        registry = runtime.prepare("b-new", ArtifactKind.STATEMENT_REGISTRY, b"opaque registry")
        def spec(**kw):
            return BatchSpec(**{**dict(batch_id="b-new", plumbing_version="a" * 64, bench_version="b" * 64,
                                       app_repo="medusajs/medusa", app_commit="c" * 40, inputs=inputs,
                                       target_sealed=1, money_bound_usd_micros=100, deadline_epoch=4e9,
                                       max_concurrency=1, max_cases_started=1), **kw})
        def workflows(workflow_ids=None, workflow_id_prefix=None, **_):
            if workflow_ids == ["b-old"]:
                return [SimpleNamespace(input={"args": [{"spec": to_record(old)}]})]
            if workflow_ids == ["b-new"]:
                return []   # not started yet
            assert workflow_id_prefix == "case-old-1@"
            return [SimpleNamespace(workflow_id="case-old-1@b-mid", created_at=1, input={"args": [{"resume": {}}]})]
        with patch("dbos.DBOS.get_workflow_status", return_value=None), patch("dbos.DBOS.list_workflows", side_effect=workflows), \
                patch.object(runtime.releases, "bundle", return_value=b"bundle"), patch.object(runtime.engine, "start_batch") as start, \
                patch.object(runtime.engine, "factory_bug_waste_keys", return_value=[]):
            for bad, code in ((spec(max_cases_started=2, case_money_usd_micros=1), "resume_invalid"),
                              (spec(case_money_usd_micros=15_000_001), "resume_money")):
                with self.assertRaisesRegex(RuntimeErrorCode, code):
                    runtime.start(to_record(bad), to_record(registry), None, "case-old-1")
            start.assert_not_called()
            ok = spec(case_money_usd_micros=15_000_000)   # $35 earlier + $15 = the $50 ceiling
            runtime.start(to_record(ok), to_record(registry), None, "case-old-1")
            start.assert_called_once_with(ok, registry, None, "case-old-1")

    def test_an_override_reason_reaches_the_engine_only_with_a_resumed_case(self):
        # Founder 2026-11-11: `start --resume-case <case> --override-reason <text>`.
        runtime = self.runtime()
        old_inputs = runtime.prepare("b-old", ArtifactKind.INPUTS, b"{}")
        old = BatchSpec(batch_id="b-old", plumbing_version="a" * 64, bench_version="b" * 64,
                        app_repo="medusajs/medusa", app_commit="c" * 40, inputs=old_inputs, target_sealed=1,
                        money_bound_usd_micros=100, deadline_epoch=4e9, max_concurrency=1)
        runtime.ledger.open("b-old", 100_000_000)
        inputs = runtime.prepare("b-new", ArtifactKind.INPUTS, b"{}")
        registry = runtime.prepare("b-new", ArtifactKind.STATEMENT_REGISTRY, b"opaque registry")
        ok = BatchSpec(batch_id="b-new", plumbing_version="a" * 64, bench_version="b" * 64,
                       app_repo="medusajs/medusa", app_commit="c" * 40, inputs=inputs, target_sealed=1,
                       money_bound_usd_micros=100, deadline_epoch=4e9, max_concurrency=1, max_cases_started=1)
        def workflows(workflow_ids=None, workflow_id_prefix=None, **_):
            if workflow_ids == ["b-old"]:
                return [SimpleNamespace(input={"args": [{"spec": to_record(old)}]})]
            return []
        why = "factory bug fixed in #122"
        with patch("dbos.DBOS.get_workflow_status", return_value=None), patch("dbos.DBOS.list_workflows", side_effect=workflows), \
                patch.object(runtime.releases, "bundle", return_value=b"bundle"), patch.object(runtime.engine, "start_batch") as start, \
                patch.object(runtime.engine, "factory_bug_waste_keys", return_value=[]) as named:
            with self.assertRaisesRegex(RuntimeErrorCode, "resume_invalid"):
                runtime.start(to_record(ok), to_record(registry), None, None, why)
            start.assert_not_called()
            dispatch(runtime, {"op": "start", "spec": to_record(ok), "registry": to_record(registry),
                               "resume": "case-old-1", "override_reason": why})
            named.assert_called_once_with("case-old-1", override=why)
            start.assert_called_once_with(ok, registry, None, "case-old-1", override=why)
        # The CLI refuses a reason without a case before it contacts the controller.
        with patch("durable.cli.load_config", return_value=self.config), patch("sys.stderr", new_callable=io.StringIO) as err, \
                patch("socket.socket") as sock:
            self.assertEqual(main(["--config", "x", "start", "spec.json", "registry.json", "--override-reason", why]), 1)
            sock.assert_not_called()
        self.assertEqual(err.getvalue(), "override_needs_resume_case\n")

    def test_a_role_swap_reaches_the_engine_only_with_a_resumed_case(self):
        # Founder 2026-11-12: `start --resume-case <case> --roles stress_tester=<model>`.
        runtime = self.runtime()
        old_inputs = runtime.prepare("b-old", ArtifactKind.INPUTS, b"{}")
        old = BatchSpec(batch_id="b-old", plumbing_version="a" * 64, bench_version="b" * 64,
                        app_repo="medusajs/medusa", app_commit="c" * 40, inputs=old_inputs, target_sealed=1,
                        money_bound_usd_micros=100, deadline_epoch=4e9, max_concurrency=1)
        runtime.ledger.open("b-old", 100_000_000)
        inputs = runtime.prepare("b-new", ArtifactKind.INPUTS, b"{}")
        registry = runtime.prepare("b-new", ArtifactKind.STATEMENT_REGISTRY, b"opaque registry")
        ok = BatchSpec(batch_id="b-new", plumbing_version="a" * 64, bench_version="b" * 64,
                       app_repo="medusajs/medusa", app_commit="c" * 40, inputs=inputs, target_sealed=1,
                       money_bound_usd_micros=100, deadline_epoch=4e9, max_concurrency=1, max_cases_started=1)
        def workflows(workflow_ids=None, workflow_id_prefix=None, **_):
            if workflow_ids == ["b-old"]:
                return [SimpleNamespace(input={"args": [{"spec": to_record(old)}]})]
            return []
        roles = {"stress_tester": "opencode-go/deepseek-v4.1-flash"}
        from durable.workers import build_bundle
        release = build_bundle(ROOT)
        with patch("dbos.DBOS.get_workflow_status", return_value=None), patch("dbos.DBOS.list_workflows", side_effect=workflows), \
                patch.object(runtime.releases, "bundle", return_value=release) as bundle, patch.object(runtime.engine, "start_batch") as start, \
                patch.object(runtime.engine, "factory_bug_waste_keys", return_value=[]) as named:
            # A release from before role swaps would refuse every step that names them: refused here.
            old_release = io.BytesIO()
            with tarfile.open(fileobj=old_release, mode="w:gz") as tar:
                body = (ROOT / "factory/durable/contract.py").read_bytes().replace(b"SWAPPABLE_ROLES", b"OTHER")
                info = tarfile.TarInfo("factory/durable/contract.py"); info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
            bundle.return_value = old_release.getvalue()
            with self.assertRaisesRegex(RuntimeErrorCode, "roles_need_newer_release"):
                runtime.start(to_record(ok), to_record(registry), None, "case-old-1", None, roles)
            runtime.start(to_record(ok), to_record(registry), None, "case-old-1")   # no swap: any release
            start.reset_mock(); named.reset_mock()
            bundle.return_value = release
            with self.assertRaisesRegex(RuntimeErrorCode, "resume_invalid"):
                runtime.start(to_record(ok), to_record(registry), None, None, None, roles)
            # What needs no case card is refused at start, before the lineage records it.
            for bad in ({"stress_tester": "openrouter/unknown/model-x"}, {"strong_calibrator": roles["stress_tester"]},
                        {"writer": roles["stress_tester"]}):
                with self.assertRaisesRegex(RuntimeErrorCode, "roles_invalid"):
                    runtime.start(to_record(ok), to_record(registry), None, "case-old-1", None, bad)
            start.assert_not_called()
            dispatch(runtime, {"op": "start", "spec": to_record(ok), "registry": to_record(registry),
                               "resume": "case-old-1", "roles": roles})
            named.assert_called_once_with("case-old-1")
            start.assert_called_once_with(ok, registry, None, "case-old-1", roles=roles)

    def test_extra_case_money_raises_one_lineage_ceiling(self):
        # Founder 2026-11-13: fresh-1109a-1 used its whole $50; `start --resume-case <case>
        # --extra-case-money <usd_micros> --case-money-reason <text>` lets it finish.
        from durable.contract import Usage
        runtime = self.runtime()
        old_inputs = runtime.prepare("b-old", ArtifactKind.INPUTS, b"{}")
        old = BatchSpec(batch_id="b-old", plumbing_version="a" * 64, bench_version="b" * 64,
                        app_repo="medusajs/medusa", app_commit="c" * 40, inputs=old_inputs, target_sealed=1,
                        money_bound_usd_micros=100, deadline_epoch=4e9, max_concurrency=1)
        runtime.ledger.open("b-old", 100_000_000)
        runtime.ledger.reserve("b-old", "case-old-1", "case-old-1/1/writer:1/1", 50_000_000, 50_000_000)
        runtime.ledger.settle("case-old-1/1/writer:1/1", Usage(paid_usd_micros=50_000_000))
        inputs = runtime.prepare("b-new", ArtifactKind.INPUTS, b"{}")
        registry = runtime.prepare("b-new", ArtifactKind.STATEMENT_REGISTRY, b"opaque registry")
        ok = BatchSpec(batch_id="b-new", plumbing_version="a" * 64, bench_version="b" * 64,
                       app_repo="medusajs/medusa", app_commit="c" * 40, inputs=inputs, target_sealed=1,
                       money_bound_usd_micros=100, deadline_epoch=4e9, max_concurrency=1, max_cases_started=1,
                       case_money_usd_micros=45_000_000)
        def workflows(workflow_ids=None, workflow_id_prefix=None, **_):
            if workflow_ids == ["b-old"]:
                return [SimpleNamespace(input={"args": [{"spec": to_record(old)}]})]
            if workflow_ids == ["b-new"]:
                return started
            assert workflow_id_prefix == "case-old-1@"
            return earlier
        earlier, started = [], []
        why = "founder 2026-11-13: let it finish"
        grant = {"usd_micros": 45_000_000, "reason": why}
        with patch("dbos.DBOS.get_workflow_status", return_value=None), patch("dbos.DBOS.list_workflows", side_effect=workflows), \
                patch.object(runtime.releases, "bundle", return_value=b"bundle"), patch.object(runtime.engine, "start_batch") as start, \
                patch.object(runtime.engine, "factory_bug_waste_keys", return_value=[]):
            with self.assertRaisesRegex(RuntimeErrorCode, "resume_money"):   # today's ceiling, unchanged
                runtime.start(to_record(ok), to_record(registry), None, "case-old-1")
            with self.assertRaisesRegex(RuntimeErrorCode, "resume_money"):   # $50 + $44.99 is short
                runtime.start(to_record(ok), to_record(registry), None, "case-old-1",
                              extra_case_money=44_999_999, case_money_reason=why)
            for amount, reason in ((0, why), (-1, why), (True, why), (1.5, why), ("45000000", why),
                                   (200_000_001, why), (45_000_000, None), (45_000_000, " "),
                                   (45_000_000, "x" * 201), (45_000_000, "x" + " " * 200), (45_000_000, "a\nb"),
                                   (None, why)):
                with self.subTest(amount=amount, reason=reason), \
                        self.assertRaisesRegex(RuntimeErrorCode, "case_money_extra_invalid"):
                    runtime.start(to_record(ok), to_record(registry), None, "case-old-1",
                                  extra_case_money=amount, case_money_reason=reason)
            with self.assertRaisesRegex(RuntimeErrorCode, "resume_invalid"):
                runtime.start(to_record(ok), to_record(registry), None, None,
                              extra_case_money=45_000_000, case_money_reason=why)
            start.assert_not_called()
            dispatch(runtime, {"op": "start", "spec": to_record(ok), "registry": to_record(registry),
                               "resume": "case-old-1", "extra_case_money": 45_000_000, "case_money_reason": why})
            start.assert_called_once_with(ok, registry, None, "case-old-1", case_money_extra=grant)
            # Once b-new runs, a retried start attaches: the same grant is not counted twice, and
            # another grant, which the attached batch would drop, is refused.
            runtime.ledger.open("b-new", 100_000_000)   # its batch, which has spent nothing yet
            started.append(SimpleNamespace(input={"args": [{"resume": {"case_money_extra": grant}}]}))
            earlier.append(SimpleNamespace(workflow_id="case-old-1@b-new", created_at=1,
                                           input={"args": [{"resume": {"case_money_extra": grant}}]}))
            for amount in (45_000_000, None):
                runtime.start(to_record(ok), to_record(registry), None, "case-old-1",
                              extra_case_money=amount, case_money_reason=amount and why)
            with self.assertRaisesRegex(RuntimeErrorCode, "case_money_extra_invalid"):
                runtime.start(to_record(ok), to_record(registry), None, "case-old-1",
                              extra_case_money=46_000_000, case_money_reason=why)
            started.clear(); earlier.clear()
            # A later resume of the lineage keeps the raised ceiling without naming it again, and a
            # further grant adds to it, up to $200 in all.
            start.reset_mock()
            runtime.ledger.open("b-mid", 100_000_000)   # that resume's batch, which spent nothing
            earlier.append(SimpleNamespace(workflow_id="case-old-1@b-mid", created_at=1,
                                           input={"args": [{"resume": {"case_money_extra": grant}}]}))
            runtime.start(to_record(ok), to_record(registry), None, "case-old-1")
            start.assert_called_once_with(ok, registry, None, "case-old-1")
            with self.assertRaisesRegex(RuntimeErrorCode, "case_money_extra_invalid"):
                runtime.start(to_record(ok), to_record(registry), None, "case-old-1",
                              extra_case_money=155_000_001, case_money_reason=why)
        # The CLI refuses an amount without a case or a reason before it contacts the controller.
        for argv, code in ((["--extra-case-money", "45000000", "--case-money-reason", why], "case_money_needs_resume_case"),
                           (["--resume-case", "case-old-1", "--extra-case-money", "45000000"], "case_money_extra_invalid"),
                           (["--resume-case", "case-old-1", "--case-money-reason", why], "case_money_extra_invalid")):
            with patch("durable.cli.load_config", return_value=self.config), patch("sys.stderr", new_callable=io.StringIO) as err, \
                    patch("socket.socket") as sock:
                self.assertEqual(main(["--config", "x", "start", "spec.json", "registry.json", *argv]), 1)
                sock.assert_not_called()
            self.assertEqual(err.getvalue(), code + "\n")

    def test_resume_books_factory_bug_losses_as_waste_before_counting_case_money(self):
        # 22e434-3 on 9 November: a writer step that stopped on our own bug had settled $45 as the
        # case's money. Once a factory_bug diagnosis names it, it is waste, and the resume gets the
        # case's money back; the batch still counts it as spent.
        from durable.contract import Usage
        from durable.contract import ContractError
        runtime = self.runtime()
        old_inputs = runtime.prepare("b-old", ArtifactKind.INPUTS, b"{}")
        old = BatchSpec(batch_id="b-old", plumbing_version="a" * 64, bench_version="b" * 64,
                        app_repo="medusajs/medusa", app_commit="c" * 40, inputs=old_inputs, target_sealed=1,
                        money_bound_usd_micros=100, deadline_epoch=4e9, max_concurrency=1)
        runtime.ledger.open("b-old", 100_000_000)
        for n, paid in ((1, 3_000_000), (2, 45_000_000)):
            key = f"case-old-1/{n}/writer:1/1"
            runtime.ledger.reserve("b-old", "case-old-1", key, paid, 50_000_000)
            runtime.ledger.settle(key, Usage(paid_usd_micros=paid))
        lost = "case-old-1/2/writer:1/1"
        inputs = runtime.prepare("b-new", ArtifactKind.INPUTS, b"{}")
        registry = runtime.prepare("b-new", ArtifactKind.STATEMENT_REGISTRY, b"opaque registry")
        ok = BatchSpec(batch_id="b-new", plumbing_version="a" * 64, bench_version="b" * 64,
                       app_repo="medusajs/medusa", app_commit="c" * 40, inputs=inputs, target_sealed=1,
                       money_bound_usd_micros=100, deadline_epoch=4e9, max_concurrency=1, max_cases_started=1,
                       case_money_usd_micros=47_000_000)   # $50 less the $3 the case itself used
        def workflows(workflow_ids=None, workflow_id_prefix=None, **_):
            if workflow_ids == ["b-old"]:
                return [SimpleNamespace(input={"args": [{"spec": to_record(old)}]})]
            return []
        with patch("dbos.DBOS.get_workflow_status", return_value=None), patch("dbos.DBOS.list_workflows", side_effect=workflows), \
                patch.object(runtime.releases, "bundle", return_value=b"bundle"), patch.object(runtime.engine, "start_batch") as start:
            # Without the diagnosis naming it, the $45 stays the case's and the resume is refused.
            with patch.object(runtime.engine, "factory_bug_waste_keys", side_effect=ContractError("resume:x")):
                with self.assertRaisesRegex(RuntimeErrorCode, "resume_money"):
                    runtime.start(to_record(ok), to_record(registry), None, "case-old-1")
            with patch.object(runtime.engine, "factory_bug_waste_keys", return_value=[lost]) as named:
                runtime.start(to_record(ok), to_record(registry), None, "case-old-1")
                runtime.start(to_record(ok), to_record(registry), None, "case-old-1")   # idempotent
            named.assert_called_with("case-old-1")
            start.assert_called_with(ok, registry, None, "case-old-1")
        self.assertEqual(runtime.ledger.case_balance("b-old", "case-old-1", 50_000_000)["used"], 3_000_000)
        bal = runtime.ledger.balance("b-old")
        self.assertEqual((bal["spent"], bal["waste"]), (48_000_000, 45_000_000))
        self.assertEqual(runtime.ledger.rows()["rebooked"], [(lost, "factory_bug")])

    def test_private_socket_client_prepare(self):
        import socketserver
        import threading
        from durable.cli import Handler
        runtime = self.runtime()
        config_path = self.root / "config"
        config_path.write_text("{}")
        config_path.chmod(0o600)
        content_path = self.root / "content"
        content_path.write_bytes(b"opaque socket payload")
        content_path.chmod(0o600)
        with socketserver.UnixStreamServer(str(runtime.state / "operator.sock"), Handler) as server:
            server.runtime = runtime
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            try:
                with patch("durable.cli.load_config", return_value=self.config), patch("sys.stdout", new_callable=io.StringIO) as output:
                    self.assertEqual(main(["--config", str(config_path), "prepare", "b-offline", "registry", str(content_path)]), 0)
                    record = json.loads(output.getvalue())
                    self.assertEqual(record["kind"], "registry")
                    self.assertNotIn("opaque socket payload", output.getvalue())
            finally:
                thread.join(timeout=5)
        self.assertEqual(runtime.sealer.open(runtime.keys.scope_key("b-offline"), Ref(**record), runtime.store.get_sealed("b-offline", Ref(**record))), b"opaque socket payload")

    def test_legacy_import_is_prepared_from_a_host_path_and_starts_a_one_case_batch(self):
        import socketserver
        import threading
        from dataclasses import replace
        from durable.cli import Handler
        runtime = self.runtime()
        config_path = self.root / "config"
        config_path.write_text("{}")
        config_path.chmod(0o600)
        archive = self.root / "case-old.import.age"
        archive.write_bytes(b"age-encryption.org/v1\n-> X25519 opaque legacy ciphertext")
        archive.chmod(0o600)
        with socketserver.UnixStreamServer(str(runtime.state / "operator.sock"), Handler) as server:
            server.runtime = runtime
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            try:
                with patch("durable.cli.load_config", return_value=self.config), patch("sys.stdout", new_callable=io.StringIO) as output:
                    self.assertEqual(main(["--config", str(config_path), "prepare", "case-offline-1", "case", str(archive)]), 0)
                    record = json.loads(output.getvalue())
            finally:
                thread.join(timeout=5)
        imported = Ref(**record)
        self.assertEqual(runtime.store.get_sealed("case-offline-1", imported)[:21], b"age-encryption.org/v1")
        self.assertEqual(runtime.sealer.open(runtime.keys.scope_key("case-offline-1"), imported,
                         runtime.store.get_sealed("case-offline-1", imported)), archive.read_bytes())
        # Only real age ciphertext is accepted: the controller never receives a plaintext case.
        from durable.cli import dispatch
        plain = self.root / "plain"
        plain.write_bytes(b"case plaintext")
        plain.chmod(0o600)
        with self.assertRaisesRegex(RuntimeErrorCode, "import_invalid"):
            dispatch(runtime, {"op": "prepare", "scope": "case-offline-1", "kind": "case", "content_path": str(plain)})
        inputs = runtime.prepare("b-offline", ArtifactKind.INPUTS, json.dumps({"import_spent_usd_micros": 2_500_000}).encode())
        registry = runtime.prepare("b-offline", ArtifactKind.STATEMENT_REGISTRY, b"registry")
        spec = BatchSpec(batch_id="b-offline", plumbing_version="a" * 64, bench_version="b" * 64,
                         app_repo="medusajs/medusa", app_commit="c" * 40, inputs=inputs, target_sealed=1,
                         money_bound_usd_micros=100, deadline_epoch=4e9, max_cases_started=1,
                         case_money_usd_micros=47_500_000)
        runtime.config = {**runtime.config, "worker_credentials": {"legacy_registry": True}}
        with patch("dbos.DBOS.get_workflow_status", return_value=None), patch.object(runtime.releases, "bundle", return_value=b"bundle"), patch.object(runtime.engine, "start_batch") as start:
            runtime.start(to_record(spec), to_record(registry), to_record(imported))
            start.assert_called_once_with(spec, registry, imported, None)
            # One case only, the legacy statement key delivered, and old + new case money within $50.
            for bad_spec, config in ((replace(spec, max_cases_started=2), runtime.config), (spec, {**runtime.config, "worker_credentials": {}}),
                                     (replace(spec, case_money_usd_micros=47_500_001), runtime.config)):
                runtime.config = config
                with self.assertRaisesRegex(RuntimeErrorCode, "import_invalid"):
                    runtime.start(to_record(bad_spec), to_record(registry), to_record(imported))
                runtime.config = {**runtime.config, "worker_credentials": {"legacy_registry": True}}

    def test_start_refuses_money_that_cannot_hold_one_request(self):
        # b5521c, 7 November: $3 and $9 could never hold one Claude request ($9.52), so every
        # admission attempt was cut off. Start now refuses such a batch by name.
        runtime = self.runtime()
        models = {"builder": ["openrouter/minimax/minimax-m3.1-flash"], "attacker": ["openrouter/deepseek/deepseek-v4.1-flash"],
                  "reviewers": [["openrouter/xiaomi/mimo-v2.6-pro"]], "strong_calibrator": ["claude/claude-opus-5-5"],
                  "easy_calibrator": ["openrouter/z-ai/glm-5.3-flash"]}
        inputs = runtime.prepare("b-offline", ArtifactKind.INPUTS, json.dumps({"dry_run": False, "models": models}).encode())
        registry = runtime.prepare("b-offline", ArtifactKind.STATEMENT_REGISTRY, b"registry")
        spec = lambda bound, case: BatchSpec(batch_id="b-offline", plumbing_version="a" * 64, bench_version="b" * 64,
            app_repo="medusajs/medusa", app_commit="c" * 40, inputs=inputs, target_sealed=1,
            money_bound_usd_micros=bound, deadline_epoch=4e9, case_money_usd_micros=case)
        with patch("dbos.DBOS.get_workflow_status", return_value=None), patch.object(runtime.releases, "bundle", return_value=b"bundle"), patch.object(runtime.engine, "start_batch") as start:
            for bound, case in ((9_000_000, 50_000_000), (50_000_000, 9_520_896)):
                with self.assertRaisesRegex(RuntimeErrorCode, "bound_below_call_hold"):
                    runtime.start(to_record(spec(bound, case)), to_record(registry))
            start.assert_not_called()
            runtime.start(to_record(spec(9_520_897, 9_520_897)), to_record(registry))
            start.assert_called_once()
        from durable.runtime import largest_call_hold
        # Empty models mean the rotation (as ADMIT reads them); opaque and dry-run inputs have nothing to check.
        self.assertEqual(largest_call_hold(json.dumps({"dry_run": False, "models": {}})), 9_520_896)
        self.assertEqual(largest_call_hold(json.dumps({"dry_run": False})), 9_520_896)
        self.assertIsNone(largest_call_hold(b"opaque"))
        self.assertIsNone(largest_call_hold(json.dumps({"dry_run": True, "models": models})))

    def test_second_owner_rejected(self):
        self.runtime()
        with self.assertRaises(RuntimeErrorCode):
            Runtime(self.config)

    def test_explicit_configuration_and_dsn_sources(self):
        path = self.root / "config.json"
        dsn = self.root / "dsn"
        dsn.write_text("postgresql://user:private@localhost/factory\n")
        dsn.chmod(0o600)
        path.write_text(json.dumps({"database_url_file": str(dsn)}))
        path.chmod(0o600)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_config(path)["database_url"], dsn.read_text().strip())
        with patch.dict(os.environ, {"UNBUG_DURABLE_DSN": "postgresql://localhost/override"}):
            self.assertEqual(load_config(path)["database_url"], "postgresql://localhost/override")
        self.config["application_version"] = "wrong"
        with self.assertRaises(RuntimeErrorCode):
            Runtime(self.config)
        self.assertFalse((self.root / "state").exists())

    def test_private_files_and_symlinks(self):
        path = self.root / "secret"
        path.write_bytes(b"secret")
        path.chmod(0o644)
        with self.assertRaises(RuntimeErrorCode):
            private_bytes(path)
        path.chmod(0o600)
        self.assertEqual(private_bytes(path), b"secret")
        link = self.root / "link"
        link.symlink_to(path)
        with self.assertRaises(OSError):
            private_bytes(link)

    def test_four_messages_and_report_dispatch(self):
        runtime = Mock()
        for op, payload in (("bench_release", {"bench_version": "a" * 64}),
                            ("plumbing_release", {"plumbing_version": "b" * 64}),
                            ("bound_raised", {"money_bound_usd_micros": 123}),
                            ("founder_reply", {"action": "retire", "ruling": None})):
            dispatch(runtime, dict(op=op, destination="case-one" if op == "founder_reply" else "b-offline", payload=payload))
        self.assertEqual(runtime.engine.send.call_count, 3)
        runtime.engine.reply.assert_called_once()

    def test_operator_status_and_report_show_only_approved_fixed_reasons(self):
        card = dict(case_id='case-one', status='waiting_for_release', stage='admit', passed=[],
                    failed_gate=None, writer_rounds=0, extensions=0, replacement_of=None)
        for op in ('status', 'report'):
            for reason, expected in (('admit:registry_unavailable', 'admit:registry_unavailable'),
                                     ('infra:private_error_sentinel', None), ('router:refusal', None)):
                with self.subTest(op=op, reason=reason), \
                        patch('durable.report.load_cards', return_value=[dict(card,reason=reason)]):
                    report = dispatch(Mock(), dict(op=op,batch='b-offline'))
                    self.assertEqual(report['cases'][0]['reason'], expected)
                    self.assertNotIn('sentinel', json.dumps(report))

    def test_publish_writes_only_the_allowlisted_scorecard_once(self):
        objects = LocalObjects(self.root / "published")
        runtime = Mock(store=Mock(objects=objects))
        card = dict(case_id="case-one", status="stopped_admission", stage="writer:1", passed=[], failed_gate=None,
                    writer_rounds=1, extensions=0, replacement_of=None, reason="router:refusal",
                    secret="CASE-MATERIAL")
        ok = dict(card, case_id="case-two", reason="infra:deadline")
        with patch("durable.report.load_cards", return_value=[card, ok]):
            first = dispatch(runtime, dict(op="publish", batch="b-offline"))
            again = dispatch(runtime, dict(op="publish", batch="b-offline"))
        self.assertEqual(first, again)
        text = objects.get(first["published"]).decode()
        published = json.loads(text)
        self.assertEqual([c["reason"] for c in published["cases"]], [None, "infra:deadline"])
        self.assertNotIn("CASE-MATERIAL", text)
        self.assertTrue(first["published"].startswith("scorecards/b-offline/"))
        with self.assertRaises(RuntimeErrorCode):
            dispatch(runtime, dict(op="publish", batch="../escape"))

    def quarantined(self, *, fence=True, quarantined=True, **extra):
        from durable.workers import _atomic_json
        state = Path(self.config["state_dir"])
        state.mkdir(mode=0o700, exist_ok=True)
        os.chmod(state, 0o700)
        if fence:
            _atomic_json(state / "cold-backup.json", {"retired": True})
        _atomic_json(state / "restored.json", {"token": "t" * 32, "quarantined": quarantined, **extra})
        return state

    def test_reconcile_exits_only_a_quarantined_restore_and_is_idempotent(self):
        from durable.backup import reconcile
        from durable.workers import _atomic_json
        state = self.quarantined()
        with self.assertRaises(RuntimeErrorCode):          # an operator must attest both
            reconcile(self.config, ownership=True)
        with self.assertRaises(RuntimeErrorCode):
            reconcile(self.config, spending=True)
        self.assertTrue((state / "cold-backup.json").exists())
        pool = BoatPool(state / "pool", ReleaseStore(state / "releases"), "offline")
        pool._write("case-one", dict(intent="1" * 32, worker=None, deleting=None))
        with self.assertRaisesRegex(RuntimeErrorCode, "case-one"):
            reconcile(self.config, ownership=True, spending=True)
        self.assertTrue((state / "cold-backup.json").exists())
        with self.assertRaises(RuntimeErrorCode):          # still fenced for startup
            Runtime(self.config)
        pool._write("case-one", dict(intent="1" * 32, worker="bx_12345678", deleting=None))
        # A crash after the attestation but before the fence is removed completes on retry.
        done = reconcile(self.config, ownership=True, spending=True)
        self.assertTrue(done["reconciled"])
        self.assertFalse((state / "cold-backup.json").exists())
        record = json.loads((state / "restored.json").read_text())
        self.assertEqual(record["token"], "t" * 32)
        self.assertEqual(set(record["reconciled"]) - {"at"}, {"ownership", "spending", "cleared"})
        at = record["reconciled"]["at"]
        _atomic_json(state / "cold-backup.json", {"retired": True})   # crash before unlink
        self.assertTrue(reconcile(self.config, ownership=True, spending=True)["reconciled"])
        self.assertEqual(json.loads((state / "restored.json").read_text())["reconciled"]["at"], at)
        self.assertFalse((state / "cold-backup.json").exists())
        self.assertTrue(reconcile(self.config, ownership=True, spending=True)["reconciled"])
        self.runtime()   # starts like a normal restored start

    def test_reconcile_clears_only_named_uncertain_records(self):
        from durable.backup import reconcile
        state = self.quarantined()
        pool = BoatPool(state / "pool", ReleaseStore(state / "releases"), "offline")
        pool._write("case-one", dict(intent="1" * 32, worker=None, deleting=None))
        pool._write("case-two", dict(intent="2" * 32, worker="bx_12345678", deleting="delete-1"))
        pool._write("case-fine", dict(intent=None, worker="bx_87654321", deleting=None))
        both = dict(ownership=True, spending=True)
        with self.assertRaisesRegex(RuntimeErrorCode, "case-one,case-two"):
            reconcile(self.config, **both)
        with self.assertRaisesRegex(RuntimeErrorCode, "case-two"):      # an unnamed record still refuses
            reconcile(self.config, cleared=["case-one"], **both)
        for bad in (["case-one", "case-two", "case-fine"], ["case-one", "case-two", "case-absent"]):
            with self.assertRaises(RuntimeErrorCode):                   # only records the refusal listed
                reconcile(self.config, cleared=bad, **both)
        with self.assertRaises(RuntimeErrorCode):                       # never without the attestation
            reconcile(self.config, cleared=["case-one", "case-two"], ownership=True)
        self.assertEqual(set(pool._records()), {"case-one", "case-two", "case-fine"})
        self.assertTrue((state / "cold-backup.json").exists())
        self.assertNotIn("reconciled", json.loads((state / "restored.json").read_text()))
        # Crash after the attestation is saved, before the records and fence are removed.
        real = Path.unlink
        calls = []
        def crash(path, *args, **kwargs):
            calls.append(path.name)
            raise OSError("crash")
        with patch.object(Path, "unlink", crash), self.assertRaises(RuntimeErrorCode):
            reconcile(self.config, cleared=["case-one", "case-two"], **both)
        saved = json.loads((state / "restored.json").read_text())["reconciled"]
        self.assertEqual(saved["cleared"], ["case-one", "case-two"])
        self.assertTrue((state / "cold-backup.json").exists())
        reconcile(self.config, **both)                                  # the repeat finishes from the saved list
        self.assertEqual(set(pool._records()), {"case-fine"})
        self.assertFalse((state / "cold-backup.json").exists())
        self.assertEqual(json.loads((state / "restored.json").read_text())["reconciled"], saved)
        reconcile(self.config, cleared=["case-one"], **both)            # idempotent, nothing re-cleared
        self.runtime()

    def test_reconcile_refuses_sources_and_handover_restores(self):
        from durable.backup import reconcile
        from durable.workers import _atomic_json
        state = Path(self.config["state_dir"])
        state.mkdir(mode=0o700)
        os.chmod(state, 0o700)
        _atomic_json(state / "cold-backup.json", {"token": "t" * 32, "retired": False})   # merely fenced
        with self.assertRaises(RuntimeErrorCode):
            reconcile(self.config, ownership=True, spending=True)
        _atomic_json(state / "cold-backup.json", {"token": "t" * 32, "retired": True})    # handed-over source
        with self.assertRaises(RuntimeErrorCode):
            reconcile(self.config, ownership=True, spending=True)
        (state / "cold-backup.json").unlink()
        self.quarantined(fence=False, quarantined=False)                                   # normal restore
        with self.assertRaises(RuntimeErrorCode):
            reconcile(self.config, ownership=True, spending=True)
        self.quarantined(quarantined=False)
        with self.assertRaises(RuntimeErrorCode):
            reconcile(self.config, ownership=True, spending=True)
        self.assertTrue((state / "cold-backup.json").exists())
        self.quarantined()
        from durable.runtime import runtime_lock
        with runtime_lock(state), self.assertRaises(RuntimeErrorCode):                     # a live controller
            reconcile(self.config, ownership=True, spending=True)

    def test_reconcile_command_requires_both_attestations(self):
        self.quarantined()
        for flags in ([], ["--ownership-reconciled"], ["--spending-reconciled"]):
            with patch("durable.cli.load_config", return_value=self.config), patch("sys.stderr", new_callable=io.StringIO), \
                    self.assertRaises(SystemExit):
                main(["--config", "x", "reconcile", *flags])
        self.assertTrue((Path(self.config["state_dir"]) / "cold-backup.json").exists())
        with patch("durable.cli.load_config", return_value=self.config), patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(main(["--config", "x", "reconcile", "--ownership-reconciled", "--spending-reconciled"]), 0)
        self.assertTrue(json.loads(out.getvalue())["reconciled"])
        with patch("durable.cli.reconcile", return_value={}) as call, patch("durable.cli.load_config", return_value=self.config), \
                patch("sys.stdout", new_callable=io.StringIO):
            main(["--config", "x", "reconcile", "--ownership-reconciled", "--spending-reconciled",
                  "--cleared-record", "case-a", "--cleared-record", "case-b"])
        self.assertEqual(call.call_args.kwargs["cleared"], ["case-a", "case-b"])


    def test_cli_sanitizes_secret_failure(self):
        with patch("durable.cli.load_config", side_effect=ValueError("secret content")), patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(main(["--config", "unused", "status", "b-offline"]), 1)
            self.assertEqual(err.getvalue(), "durable_operator_failed\n")

    def test_encrypted_backup_uses_existing_objects_and_no_dsn_argv(self):
        self.config["database_url"] = "postgresql://operator:secret@localhost/factory"
        real_run = subprocess.run
        def run(argv, **kwargs):
            if argv[0] == "pg_dump":
                self.assertEqual(argv, ["pg_dump", "--format=custom"])
                self.assertEqual(kwargs["env"]["PGPASSWORD"], "secret")
                return subprocess.CompletedProcess(argv, 0, stdout=b"database plaintext")
            return real_run(argv, **kwargs)
        with patch("durable.backup.subprocess.run", side_effect=run), patch("durable.backup.database_lock", return_value=nullcontext()):
            result = backup(self.config)
        data = LocalObjects(self.config["local_objects"]).get(result["backup"])
        self.assertTrue(data.startswith(b"age-encryption.org/v1"))
        self.assertNotIn(b"database plaintext", data)
        opened = real_run(["age", "-d", "-i", self.config["restore_identity"]], input=data, capture_output=True, check=True).stdout
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(opened)) as archive:
            self.assertEqual(archive.extractfile("database.dump").read(), b"database plaintext")


if __name__ == "__main__":
    unittest.main()
