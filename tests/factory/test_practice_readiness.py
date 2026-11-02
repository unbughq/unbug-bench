"""Offline contracts with retained collection/creation artifacts; systemd/cloud doubles.

No live account/deployment/cost proof, no Murphy closure. Fault transport uses
retained cards/ciphertexts with authored batch bindings from HolderTests.
"""
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "factory"))
import batch
import batch_holder as holder
import batch_money as money
import batch_service as service
import boat_lifecycle
import practice
import practice_cleanup as cleanup
import practice_preflight as preflight
import key_holder
from test_batch_holder import HolderTests


class PracticeTests(unittest.TestCase):
    setUp = HolderTests.setUp
    setUpBase = HolderTests.setUpBase
    freeze = HolderTests.freeze
    input = HolderTests.input
    write_card = HolderTests.write_card
    answers = HolderTests.answers
    directory = HolderTests.directory
    ops = HolderTests.ops
    money = HolderTests.money
    reserve = HolderTests.reserve
    reconcile = HolderTests.reconcile
    publish = HolderTests.publish
    started = HolderTests.started
    output = HolderTests.output
    retirement = HolderTests.retirement

    def test_role_maxima_and_empty_input_contract(self):
        record = json.loads((ROOT / preflight.MANIFEST).read_text())
        self.assertTrue(practice.matches(record))
        money.check_manifest(record)
        roles = preflight.roles(record)
        self.assertEqual(len(roles), 5)
        self.assertTrue(all(not r["route"].startswith("codex/") and r["max_usd"] for r in roles.values()))
        self.assertEqual(record["practice_admission"]["jobs"]["practice"]["baseline_usd"], "0.000000000")
        self.assertEqual(record["jobs"]["practice"]["initial_accounts"], {"claude": 2})
        changed = deepcopy(record); changed["jobs"]["practice"]["requested_total_usd"] = "20.000000000"
        self.assertFalse(practice.matches(changed))

    def practice_policy(self):
        record = deepcopy(practice.EXPECTED)
        path = self.root / preflight.MANIFEST; path.write_text(json.dumps(record))
        digest = service.digest(path)
        policy = deepcopy(self.policy)
        policy["jobs"] = record["jobs"]
        policy["batch"].update(id=practice.BATCH, manifest_path=preflight.MANIFEST, manifest_sha256=digest)
        (self.release / "source-manifest.json").write_text(json.dumps({"files": {preflight.MANIFEST: digest}}))
        return policy

    def test_authenticated_activation_scope_and_legacy_fallthrough(self):
        policy = self.practice_policy()
        with patch.object(holder, "HOLDER_ENABLED", False), patch.dict(os.environ, {}, clear=True):
            self.assertFalse(holder.active(policy, self.root))
            os.environ["UNBUG_PRACTICE_BATCH"] = "wrong"
            self.assertFalse(holder.active(policy, self.root))
            os.environ["UNBUG_PRACTICE_BATCH"] = practice.BATCH
            self.assertTrue(holder.active(policy, self.root))
            self.assertFalse(holder.active(self.policy, self.root))
            with patch.object(key_holder, "ROOT", self.root):
                self.assertIsNone(key_holder.batch_request(self.policy, dict(op="launch", batch="practice")))
            (self.root / preflight.MANIFEST).write_text("{}")
            with self.assertRaises(ValueError): holder.active(policy, self.root)
        with patch.object(holder, "HOLDER_ENABLED", False), patch.object(key_holder, "ROOT", self.root), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "request_refused"):
                key_holder.batch_request(policy, dict(op="launch", batch=practice.BATCH))

    def test_collection_watchdog_ttl_order_and_invalid_admission(self):
        start = 1730000000
        collect, delete, ttl = practice.deadlines(start)
        self.assertEqual((collect, delete, ttl), (start + 1800, start + 2700, start + 3600))
        self.assertLess(collect, delete); self.assertLess(delete, ttl)
        for grace in (0, 1800, 2000):
            with patch.dict(practice.TIMING, grace_seconds=grace):
                with self.assertRaises(ValueError): practice.admission(practice.EXPECTED)
        with self.assertRaises(money.MoneyWait):
            practice.admission(practice.EXPECTED, datetime(2026, 11, 6, 23, 30, tzinfo=timezone.utc))

    def test_publication_fault_replay_and_child_failure_accounting(self):
        op = self.started(self.reserve()); self.output(op)
        identity = op["operation_id"]
        # Retained fixture uses authored practice bindings. Activation itself is
        # independently exercised with the exact manifest above.
        with patch.object(practice, "active", return_value=True):
            with money.locked(self.home, self.record["id"]): practice.fault(self.policy, self.root, self.home, identity, arm=True)
            with self.assertRaisesRegex(ValueError, "publication_failed"): self.publish(op)
            self.assertFalse(self.objects)
            self.assertEqual(self.money()["jobs"]["j"]["acks"], {})
            self.assertFalse((self.directory / "current" / (op["case"] + ".json")).exists())
            self.assertEqual(service._json(self.directory / "outbox" / (identity + ".json"))["state"], "pending")
            self.assertEqual(holder.record_child(self.policy, self.root, self.home, identity, "publish", 1), 1)
            self.assertIsNone(self.ops()[identity]["incident"])
            with self.assertRaises(ValueError): practice.fault(self.policy, self.root, self.home, identity, arm=True)
            ack = self.publish(op)
            self.assertEqual(self.publish(op), ack)
            self.assertEqual(holder.record_child(self.policy, self.root, self.home, identity, "publish", 0), 0)
            self.assertEqual(self.ops()[identity]["failures"], 0)

    def cleanup_layout(self):
        op = self.started(self.reserve())
        path = self.home / "launches" / op["launch_id"]
        spend = self.root / "results/spend/fixture.json"; spend.parent.mkdir(parents=True)
        (path / "monitor.sh").write_text("spend_file=" + str(spend) + "\nttl_seconds=3600\nretire_at=1800\n")
        (path / (op["worker_id"] + ".started")).write_text("100000\n")
        return op, path, spend

    def test_worker_start_not_reservation_controls_delete_and_restart(self):
        op, path, spend = self.cleanup_layout()
        with patch.object(boat_lifecycle, "delete_receipt") as delete:
            for stamp in (100000, 101800, 102699):
                result = cleanup.step(self.policy, self.root, self.home, op, stamp)
                self.assertEqual(result["deadline"], 102700)
                delete.assert_not_called()
            cleanup.step(self.policy, self.root, self.home, op, 102700)
            delete.assert_called_once_with(self.root, spend, op["worker_id"], path / "ids")
            cleanup.step(self.policy, self.root, self.home, op, 102701)
            self.assertEqual(delete.call_count, 2)  # helper reconciles; it never repeats a POST.

    def test_unknown_creation_start_and_wrong_launch_never_claim_complete(self):
        op, path, spend = self.cleanup_layout()
        with patch.object(boat_lifecycle, "delete_receipt") as delete:
            (path / (op["worker_id"] + ".started")).unlink()
            self.assertEqual(cleanup.step(self.policy, self.root, self.home, op, 104000)["state"], "uncertain")
            (path / "launch.json").write_text("{}")
            self.assertEqual(cleanup.step(self.policy, self.root, self.home, op, 104000)["state"], "uncertain")
            delete.assert_not_called()

    def test_complete_requires_receipt_and_full_inventory_no_pending_creation(self):
        op, path, spend = self.cleanup_layout()
        proof = self.retirement(op)
        # retirement fixture changes monitor; restore timing contract.
        with (path / "monitor.sh").open("a") as out: out.write("ttl_seconds=3600\nretire_at=1800\n")
        for more in (True, False):
            response = subprocess.CompletedProcess([], 0, json.dumps(dict(sandboxes=[], pageInfo=dict(hasMore=more))).encode())
            with patch.object(cleanup.subprocess, "run", return_value=response):
                result = cleanup.step(self.policy, self.root, self.home, op, 102000)
                self.assertEqual(result["state"], "uncertain" if more else "complete")
                (path / "new.2.pending").touch()
                self.assertNotEqual(cleanup.step(self.policy, self.root, self.home, op, 102000)["state"], "complete")
                (path / "new.2.pending").unlink()

    def test_deletion_replay_and_uncertain_attempt_never_post(self):
        op, path, spend = self.cleanup_layout()
        proof = self.retirement(op)
        spend = proof.parent.with_suffix(".json")
        with patch.object(boat_lifecycle.subprocess, "run") as run:
            done = boat_lifecycle.delete_receipt(self.root, spend, op["worker_id"], path / "ids")
            self.assertEqual(done["status"], "completed"); run.assert_not_called()
            (proof / "deletion-request.json").unlink(); (proof / "deletion-completion.json").unlink()
            (path / (op["worker_id"] + ".deletion-attempted")).touch()
            with self.assertRaises(ValueError): boat_lifecycle.delete_receipt(self.root, spend, op["worker_id"], path / "ids")
            run.assert_not_called()

    def test_preflight_no_cloud_unpinned_and_expired(self):
        with patch.object(holder, "HOLDER_ENABLED", False), patch.object(boat_lifecycle, "delete_receipt", side_effect=AssertionError("cloud")):
            report = preflight.check(ROOT)
        self.assertEqual([r["id"] for r in report["offline"] if r["status"] == "fail"], ["pins"])
        self.assertFalse(report["launch_ready"])
        self.assertEqual(preflight.code(report), 1)
        self.assertEqual(sum(float(r["ceiling_usd"]) for r in report["live"]), 24.99)

    def test_unarmed_and_wrong_unit_refuse_before_query(self):
        op = self.reserve()
        with patch.object(practice, "active", return_value=True), patch.object(practice, "admission"), patch.dict(os.environ, UNBUG_CLOUD="boat"), patch.object(cleanup.subprocess, "run") as run:
            with self.assertRaises(money.MoneyWait): cleanup.armed(self.policy, self.root, self.home, op)
            run.assert_not_called()
        with patch.object(practice, "active", return_value=False):
            cleanup.armed(self.policy, self.root, self.home, op)

    def test_unit_pid_and_ready_binding_must_match(self):
        op = self.reserve()
        target = cleanup.location(self.home, op).with_suffix('.ready.json')
        target.parent.mkdir(parents=True)
        service.atomic_json(target, cleanup.ready(self.policy, op, 42))
        response = subprocess.CompletedProcess([], 0, 'ActiveState=active\nSubState=running\nExecMainPID=42\n')
        with patch.object(practice, 'active', return_value=True), patch.object(practice, 'admission'), patch.dict(os.environ, UNBUG_CLOUD='boat'), patch.object(cleanup, 'digest', return_value='a' * 64), patch.object(cleanup.subprocess, 'run', return_value=response):
            cleanup.armed(self.policy, self.root, self.home, op)
            for field, value in [('pid', 43), ('launch_id', 'b' * 32), ('timing', dict(practice.TIMING, grace_seconds=1800)), ('policy_sha256', 'b' * 64)]:
                marker = cleanup.ready(self.policy, op, 42); marker[field] = value
                service.atomic_json(target, marker)
                with self.assertRaises(money.MoneyWait): cleanup.armed(self.policy, self.root, self.home, op)

    def test_pin_command_rejects_stale_dirty_and_existing_output(self):
        spec = importlib.util.spec_from_file_location('practice_pin_test', ROOT / 'tools/pin-practice.py')
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        output = self.root / 'pins'
        with patch.object(preflight, 'git', side_effect=['a' * 40, 'b' * 40]):
            with self.assertRaisesRegex(ValueError, 'clean merged'): tool.build(self.root, output)
        self.assertFalse(output.exists())
        with patch.object(preflight, 'git', side_effect=['a' * 40, 'a' * 40, ' M changed']):
            with self.assertRaisesRegex(ValueError, 'clean merged'): tool.build(self.root, output)
        self.assertFalse(output.exists())
        output.mkdir()
        with self.assertRaisesRegex(ValueError, 'new absolute'): tool.build(self.root, output)

    def test_bundle_hash_and_policy_tamper_refuse(self):
        # Authored release container checks pin format/bindings only. Release
        # verification is covered by the existing real commit-built release exam.
        bundle = self.root / 'bundle'; (bundle / 'release').mkdir(parents=True)
        for name in preflight.files():
            (bundle / name).write_text('{}')
        sha = service.digest(bundle / 'release/batch-release.json')
        batch.save(bundle / 'policy.json', preflight.policy(ROOT, sha))
        (bundle / cleanup.UNIT).write_bytes((ROOT / 'control' / cleanup.UNIT).read_bytes())
        (bundle / 'practice.conf').write_text(preflight.DROPIN)
        batch.save(bundle / 'release/batch-release.json', dict(commit=preflight.git(ROOT, 'rev-parse', 'HEAD')))
        sha = service.digest(bundle / 'release/batch-release.json')
        batch.save(bundle / 'policy.json', preflight.policy(ROOT, sha))
        batch.save(bundle / 'pins.json', preflight.pins(ROOT, bundle))
        preflight.verify_bundle(ROOT, bundle)
        (bundle / 'policy.json').write_text('{}')
        with self.assertRaises(ValueError): preflight.verify_bundle(ROOT, bundle)
        # Even recomputing file hashes cannot authorize a different policy.
        batch.save(bundle / 'pins.json', preflight.pins(ROOT, bundle))
        with self.assertRaises(ValueError): preflight.verify_bundle(ROOT, bundle)
        (bundle / 'INCOMPLETE').touch()
        with self.assertRaises(ValueError): preflight.verify_bundle(ROOT, bundle)


del HolderTests
if __name__ == "__main__": unittest.main()
