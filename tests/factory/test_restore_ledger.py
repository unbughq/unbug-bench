"""Worker import against restored PUBLIC practice archives, no age or cloud.

Archive extraction here models the trusted transport's completed decryption. The
real post-extraction worker entry point is exercised in process. These tests do
not qualify model-return/operation-commit recovery or grant legacy allowances.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin"), str(ROOT / "tests/factory")]
import restore_ledger
import run
from test_waste_rereview import waste_ledger


class Killed(BaseException):
    pass


class WorkerLedgerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.case = "case-public-practice"
        self.ledger = {"cost": 0.25, "calls": 1,
                       "events": [{"id": "practice-usage", "cost": 0.25, "calls": 1, "tokens": {"input": 1}}],
                       "terminal_stop": "complete"}
        self.archive(self.ledger)

    def archive(self, ledger, *, case=None, embedded=True, separate=True):
        self.case = case or self.case
        source = self.root / ("source-" + self.case) / self.case
        source.mkdir(parents=True)
        with patch.object(run, "BENCH", ROOT):
            run.build_fixture(SimpleNamespace(case=source / "case"))
        card = {"case": self.case, "source": "public practice fixture", "gates": {"G1": "pass"},
                "sha256": "0" * 64}  # embedded card legitimately names an older generation
        if embedded: card["continuation_budget"] = copy.deepcopy(ledger)
        self.save(source / "scorecard.json", card)
        if separate: self.save(source / "continuation-budget.json", ledger)
        archive = self.root / (self.case + ".tar.gz")
        with tarfile.open(archive, "w:gz") as stream: stream.add(source, arcname=self.case)
        self.generation = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.home = self.root / ("worker-" + self.case)
        (self.home / "work").mkdir(parents=True)
        with tarfile.open(archive) as stream: stream.extractall(self.home / "work", filter="data")
        self.work, self.sealed = self.home / "work" / self.case, self.home / "sealed"
        self.public = {**card, "sha256": self.generation, "status": "stopped", "terminal_stop": "paused",
                       "continuation_budget": copy.deepcopy(ledger)}

    def save(self, path, value): path.write_text(json.dumps(value))

    def install(self):
        return restore_ledger.install(self.work, self.sealed, self.case, self.generation, self.public)

    def target(self): return self.sealed / f"{self.case}.continuation-budget.json"

    def test_real_worker_entry_accepts_newer_public_labels_without_trusting_verdicts(self):
        before = (self.work / "scorecard.json").read_bytes()
        self.public["gates"]["G12"] = "pass"
        self.public["models_used"] = ["untrusted public attribution is not accounting evidence"]
        with patch.object(sys, "argv", ["restore_ledger.py", "--home", str(self.home),
                "--case", self.case, "--generation", self.generation]), \
             patch.object(sys, "stdin", io.StringIO(json.dumps(self.public))), \
             patch.object(sys, "stdout", io.StringIO()) as output:
            self.assertEqual(restore_ledger.main(), 0)
        receipt = json.loads(output.getvalue())
        self.assertTrue(receipt["accounting_authenticated"])
        self.assertFalse(receipt["attempt_allowances_authenticated"])
        self.assertNotIn("gates", receipt)
        self.assertEqual(json.loads(self.target().read_text()), self.ledger)
        self.assertEqual(before, (self.work / "scorecard.json").read_bytes())

    def test_newer_public_usage_or_correction_requires_retained_proof(self):
        for kind in ("event", "cost", "calls", "waste", "resolution", "stop", "numeric_type"):
            with self.subTest(kind=kind):
                changed = copy.deepcopy(self.ledger)
                if kind == "event": changed["events"].append({"id": "new", "cost": 0})
                if kind == "cost": changed["cost"] += 1
                if kind == "calls": changed["calls"] += 1
                if kind == "waste": changed["infrastructure_waste"] = [{"id": "unproved-correction"}]
                if kind == "resolution": changed["resolved_unpriced_invocations"] = [{"original": {"role": "writer"}}]
                if kind == "stop": changed["terminal_stop"] = "timeout"
                if kind == "numeric_type": changed["events"][0]["tokens"]["input"] = True
                self.public["continuation_budget"] = changed
                with self.assertRaisesRegex(restore_ledger.Refused, "authenticated delta/correction receipt required"):
                    self.install()
                self.assertFalse(self.target().exists())

    def test_matching_real_public_waste_records_preserve_every_derivation_field(self):
        for short, name, expected in (("873d7f", "canary6-collected-card.json", 16),
                                      ("c7d405", "c7d405-collected-card.json", 20)):
            with self.subTest(case=short):
                card = json.loads((ROOT / "tests/factory/fixtures" / name).read_text())
                ledger = waste_ledger(card, short)
                # Public practice content only; accounting is real saved public metadata.
                self.archive(ledger, case=card["case"])
                receipt = self.install()
                saved = json.loads(self.target().read_text())
                self.assertEqual(saved, ledger)
                self.assertEqual(receipt["infrastructure_waste_usd"], expected)
                self.assertEqual(saved["infrastructure_waste"], ledger["infrastructure_waste"])
                self.assertEqual(saved["resolved_unpriced_invocations"], ledger["resolved_unpriced_invocations"])

    def test_legacy_card_only_fallback_and_separate_ledger_only(self):
        for embedded, separate in ((True, False), (False, True)):
            with self.subTest(embedded=embedded, separate=separate):
                self.archive(self.ledger, case=f"case-practice-{int(embedded)}", embedded=embedded, separate=separate)
                self.assertTrue(self.install()["accounting_authenticated"])

    def test_wrong_generation_case_or_disagreeing_retained_snapshots_refuse(self):
        original = copy.deepcopy(self.public)
        for key, value in (("case", "case-other"), ("sha256", "f" * 64)):
            with self.subTest(key=key):
                self.public = {**original, key: value}
                with self.assertRaisesRegex(restore_ledger.Refused, "restored generation"): self.install()
                self.assertFalse(self.target().exists())
        self.public = original
        self.save(self.work / "continuation-budget.json", {**self.ledger, "cost": 4})
        with self.assertRaisesRegex(restore_ledger.Refused, "snapshots disagree"): self.install()
        self.assertFalse(self.target().exists())

    def test_mid_call_unknown_usage_cannot_be_cleared_by_public_card(self):
        for kind, extra in (("active", {"active": ["in-flight"], "terminal_stop": "running"}),
                            ("unpriced", {"unpriced_invocations": [{"role": "writer", "model": "unknown"}]})):
            with self.subTest(kind=kind):
                ledger = {**self.ledger, **extra}
                self.archive(ledger, case="case-practice-" + kind)
                with self.assertRaisesRegex(restore_ledger.Refused, "usage is unknown"): self.install()
                self.assertFalse(self.target().exists())
                self.public["continuation_budget"] = self.ledger
                with self.assertRaisesRegex(restore_ledger.Refused, "authenticated delta/correction"): self.install()

    def test_kills_at_import_publication_are_idempotent(self):
        atomic = restore_ledger.atomic_json
        for window in ("before", "after"):
            with self.subTest(window=window):
                self.archive(self.ledger, case="case-practice-import-" + window)
                def kill(path, value):
                    if path == self.target():
                        if window == "after": atomic(path, value)
                        raise Killed()
                    atomic(path, value)
                with patch.object(restore_ledger, "atomic_json", side_effect=kill), self.assertRaises(Killed):
                    self.install()
                self.assertEqual(self.target().exists(), window == "after")
                receipt = self.install()
                self.assertEqual(receipt, self.install())
                self.assertEqual(json.loads(self.target().read_text()), self.ledger)

    def test_worker_owned_newer_ledger_and_symlinks_are_never_replaced(self):
        self.sealed.mkdir()
        newer = {**self.ledger, "cost": 5}
        self.save(self.target(), newer)
        before = self.target().read_bytes()
        with self.assertRaisesRegex(restore_ledger.Refused, "worker ledger already differs"): self.install()
        self.assertEqual(before, self.target().read_bytes())
        self.target().unlink()
        other = self.root / "other.json"; self.save(other, self.ledger)
        self.target().symlink_to(other)
        with self.assertRaisesRegex(restore_ledger.Refused, "missing retained"): self.install()
        self.assertTrue(self.target().is_symlink())

    def test_cli_failure_reports_only_static_reason(self):
        for value in ('{"secret":"do-not-display"}', '{"private":"do-not-display",bad'):
            with self.subTest(value=value), \
                 patch.object(sys, "argv", ["restore_ledger.py", "--home", str(self.home),
                     "--case", self.case, "--generation", self.generation]), \
                 patch.object(sys, "stdin", io.StringIO(value)), \
                 patch.object(sys, "stdout", io.StringIO()) as output:
                self.assertEqual(restore_ledger.main(), 1)
                self.assertNotIn("do-not-display", output.getvalue())
                self.assertFalse(json.loads(output.getvalue())["accounting_authenticated"])

    def test_malformed_retained_usage_fails_with_public_reason(self):
        malformed = {"cost": 0, "calls": 1, "events": [{"id": "bad-shape", "priced": "subscription",
            "configured_model": "codex/gpt-6.1-sol", "tokens": None}]}
        self.save(self.work / "continuation-budget.json", malformed)
        self.save(self.work / "scorecard.json", {"case": self.case, "continuation_budget": malformed})
        self.public["continuation_budget"] = malformed
        with patch.object(sys, "argv", ["restore_ledger.py", "--home", str(self.home),
                "--case", self.case, "--generation", self.generation]), \
             patch.object(sys, "stdin", io.StringIO(json.dumps(self.public))), \
             patch.object(sys, "stdout", io.StringIO()) as output:
            self.assertEqual(restore_ledger.main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {
            "accounting_authenticated": False, "reason": "invalid restore accounting input"})
        self.assertFalse(self.target().exists())

    def test_launcher_restores_frozen_generation_after_originals_are_replaced(self):
        launch = (ROOT / "factory/launch.sh").read_text()
        # Execute the actual launcher's two preflight blocks. No age, credentials,
        # key holder or provider is involved; the archive contains public practice.
        freeze_card = launch.split("  # Freeze public metadata once;", 1)[1].split(
            '  if [ "$audit_g11" = no ]', 1)[0]
        freeze_archive = launch.split("  # A public card may postdate its embedded copy,", 1)[1].split(
            "  purpose=", 1)[0]
        # Include each block's initial comment line in the extracted shell code.
        script = ('set -eu\ncard=$1\nckpt=$2\nrestore=$3\nUNBUG_LAUNCH_STATE=$4\n'
                  + "  # Freeze public metadata once;" + freeze_card
                  + "  # A public card may postdate its embedded copy," + freeze_archive)
        card_path = self.root / "public-card.json"; self.save(card_path, self.public)
        archive = self.root / (self.case + ".tar.gz")
        state = self.root / "launch-state"; state.mkdir()
        result = subprocess.run(["sh", "-c", script, "sh", str(card_path), str(archive), self.case, str(state)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        stale = subprocess.run(["sh", "-c", script, "sh", str(card_path), str(archive), self.case, str(state)],
                               capture_output=True, text=True, env={**os.environ, 'checkpoint_sha': '0' * 64})
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn('requested checkpoint generation changed; no VM created', stale.stderr)
        archive.write_bytes(b"different collected generation after preflight")
        self.save(card_path, {**self.public, "sha256": "f" * 64})
        frozen = state / "restore-input.tar.gz.age"
        self.assertEqual(hashlib.sha256(frozen.read_bytes()).hexdigest(), self.generation)
        public = json.loads((state / "restore-input-scorecard.json").read_text())
        other = self.root / "worker-after-collection"; (other / "work").mkdir(parents=True)
        with tarfile.open(frozen) as stream: stream.extractall(other / "work", filter="data")
        receipt = restore_ledger.install(other / "work" / self.case, other / "sealed",
                                         self.case, self.generation, public)
        self.assertEqual(receipt["generation"], self.generation)
        self.assertTrue(receipt["accounting_authenticated"])
        # A card paired with different selected bytes stops in preflight.
        result = subprocess.run(["sh", "-c", script, "sh", str(card_path), str(archive), self.case, str(state)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generation mismatch; no VM created", result.stderr)


if __name__ == "__main__": unittest.main()
