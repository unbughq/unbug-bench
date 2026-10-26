"""Durable stress-review handoff at build/resume; synthetic files and model stubs only."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import datetime
import json
import pathlib
import shlex
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch
import run
import registry


class AttackRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        case = root / "case"
        (case / "scenarios/S1").mkdir(parents=True)
        for name in ("case.json", "answer-key.json", "scenarios/S1/key.json"):
            (case / name).write_text("{}")
        (case / "statement.md").write_text("synthetic selected case")
        self.c = types.SimpleNamespace(work=root, case=case, case_id="synthetic", card={},
            manifest0="synthetic bench revision", models={"builder": ["writer"], "attacker": ["tester"]},
            args=types.SimpleNamespace(resume="synthetic", dry_run=False, source="hunt", rounds=2,
                                       skip_build=False, runs=1, scenario_runs=1))
        (root / "scorecard.json").write_text(json.dumps({"models_used": {"attacker-1": "tester"}}))
        self.flagged_searches(flag=False)
        for target, value in (("g1", (True, {"problems": []})), ("early_checks", None),
                              ("early_review", None), ("freshness_topup", None)):
            mock = patch.object(run, target, return_value=value).start()
            setattr(self, target, mock)
        self.addCleanup(patch.stopall)

    def report_path(self, text):
        return pathlib.Path(json.loads(text.split("```json\n")[-1].split("```")[0])["report_path"])

    def interrupt(self, report=None, claim=False):
        def tester(c, models, text, cwd, name):
            self.assertEqual(name, "attacker-1")
            path = self.report_path(text)
            if report is not None:
                path.write_text(json.dumps(report))
            if claim:
                (c.work / "diagnostic-budgets/attacker-1/claimed").mkdir(parents=True)
                if report and report.get("complete"):
                    (c.work / "diagnostic-budgets/attacker-1/status.json").write_text('{"status": "completed"}')
            if report is None: raise KeyboardInterrupt()
            return 0
        atomic = registry.atomic_json
        def after_completion(path, value):
            atomic(path, value)
            if path.name == 'attack-state.json' and value.get('review_pending') is False:
                raise KeyboardInterrupt()  # completed role, before downstream gates/writer
        with patch.object(run, "opencode", tester), patch.object(registry, 'atomic_json', after_completion), \
             self.assertRaises(KeyboardInterrupt):
            run.build(self.c)

    def assert_unresolved(self, reason):
        with patch.object(run, "opencode") as model, \
             self.assertRaisesRegex(run.BudgetError, "stress_review_unresolved:" + reason):
            run.build(self.c)
        model.assert_not_called()
        self.early_review.assert_not_called()
        self.assertEqual(self.c.card["stress_review"]["status"], "unresolved")

    def test_interrupted_tester_with_exhausted_allowance_never_restarts(self):
        self.interrupt(claim=True)
        self.assert_unresolved("interrupted_review")
        self.assert_unresolved("interrupted_review")
        self.assertTrue((self.c.work / "diagnostic-budgets/attacker-1/claimed").is_dir())

    def test_saved_blocking_finding_is_repaired_before_new_revision_review(self):
        self.interrupt({"complete": False, "blocking": ["review incomplete", "reference misses second writer"]}, claim=True)
        calls = []
        def model(c, models, text, cwd, name):
            calls.append(name)
            if name == "builder-2":
                self.assertIn("reference misses second writer", text)
                self.assertIn("round-1.json", text)
                (c.case / "repair.txt").write_text("second writer fixed")
            else:
                self.assertEqual(name, "attacker-2")
                self.report_path(text).write_text('{"complete": true, "blocking": []}')
            return 0
        with patch.object(run, "opencode", model):
            run.build(self.c)
        self.assertEqual(calls, ["builder-2", "attacker-2"])
        self.early_checks.assert_called_once()
        self.early_review.assert_called_once()
        self.assertEqual(self.c.card["stress_review"]["status"], "completed")
        self.assertTrue((self.c.work / "diagnostic-budgets/attacker-1/claimed").is_dir())

    def test_completed_report_survives_interruption_and_reaches_review(self):
        self.interrupt({"complete": True, "blocking": []}, claim=True)
        with patch.object(run, "opencode") as model:
            run.build(self.c)
        model.assert_not_called()
        self.early_review.assert_called_once()

    def flagged_searches(self, flag=True):
        rows = []
        for who, kind, count in (("builder", "web", 3), ("builder", "github", 3), ("attacker", "web", 2)):
            for n in range(count):
                rows.append({"who": who, "kind": kind, "query": f"{who} {kind} query {n}",
                             "url": f"https://github.com/synthetic-fixture/{who}-{kind}-{n}",
                             "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                             "hit": flag and n == 0, "retrieved": True, "note": "synthetic search evidence",
                             "app_version": "2.19.0", "version_scope": "synthetic applicability"})
        (self.c.case / "freshness.jsonl").write_text("\n".join(json.dumps(row) for row in rows))

    def gate_context(self):
        self.c.card["gates"] = {}
        self.c.audit_gates = ["G1", "G2", "G3"]
        return patch.object(run, "public_progress"), patch.object(run, "log")

    def test_cleared_freshness_cannot_bypass_interrupted_stress_at_gate_seam(self):
        self.interrupt(claim=True)
        self.flagged_searches()
        progress, log = self.gate_context()
        reached = []
        with progress, log, patch.object(run, "confirm_hits", return_value=[]) as confirmation, \
             patch.object(run, "g3", side_effect=lambda c: reached.append("G3") or (True, {})), \
             patch.object(run, "opencode") as model:
            with self.assertRaisesRegex(run.BudgetError, "stress_review_unresolved:interrupted_review"):
                run.build(self.c)
                run.run_gates(self.c)
        confirmation.assert_called_once()
        model.assert_not_called()
        self.assertEqual(reached, [])

    def test_cleared_freshness_reuses_review_then_allows_gates(self):
        self.interrupt({"complete": True, "blocking": []})
        self.flagged_searches()
        progress, log = self.gate_context()
        with progress, log, patch.object(run, "confirm_hits", return_value=[]) as confirmation, \
             patch.object(run, "g3", return_value=(True, {})) as expensive_gate, \
             patch.object(run, "opencode") as model:
            run.build(self.c)
            run.run_gates(self.c)
        confirmation.assert_called_once()
        self.early_review.assert_called_once()
        expensive_gate.assert_called_once()
        model.assert_not_called()
        self.assertEqual(self.c.card["gates"], {"G1": "pass", "G2": "pass", "G3": "pass"})

    def test_rejected_freshness_stops_at_G2_without_review_or_duplicate_confirmation(self):
        self.interrupt(claim=True)
        self.flagged_searches()
        progress, log = self.gate_context()
        def confirmed(c, rows):
            c.freshness_confirmed_hits = len(rows)
            return rows
        with progress, log, patch.object(run, "confirm_hits", side_effect=confirmed) as confirmation, \
             patch.object(run, "g3") as expensive_gate, patch.object(run, "opencode") as model:
            run.build(self.c)
            run.run_gates(self.c)
        confirmation.assert_called_once()
        self.early_review.assert_not_called()
        model.assert_not_called()
        expensive_gate.assert_not_called()
        self.assertEqual(self.c.card["failed_gate"], "G2")

    def test_saved_gate_progress_and_infrastructure_failures_cannot_skip_stress_receipt(self):
        self.interrupt(claim=True)
        for saved in ({"failed_gate": "G2"}, {"failed_gate": "G3"}, {"gates": {"G1": "pass"}}):
            with self.subTest(saved=saved):
                (self.c.work / "scorecard.json").write_text(json.dumps(saved))
                self.assert_unresolved("interrupted_review")

    def test_skip_build_reuses_completed_stress_but_cannot_start_a_new_review(self):
        self.interrupt({"complete": True, "blocking": []})
        self.c.args.skip_build = True
        with patch.object(run, "opencode") as model:
            run.build(self.c)
        model.assert_not_called()
        self.early_review.assert_called_once()
        (self.c.case / "changed.txt").write_text("changed after review")
        self.early_review.reset_mock()
        self.assert_unresolved("review_required")

    def test_missing_malformed_and_incomplete_reports_never_pass(self):
        for content in (None, "not json", "[]", '{"blocking": []}',
                        '{"complete": false, "blocking": []}',
                        '{"complete": true, "blocking": ["review incomplete"]}'):
            with self.subTest(content=content):
                # Establish the runner-owned receipt using a killed synthetic call.
                (self.c.work / "attack-state.json").unlink(missing_ok=True)
                self.interrupt()
                path = self.c.work / "attacks/round-1.json"
                if content is None:
                    path.unlink()
                else:
                    path.write_text(content)
                reason = "interrupted_review" if content and '"complete"' in content else "missing_or_malformed_report"
                self.assert_unresolved(reason)

    def test_case_source_and_case_identity_changes_invalidate_saved_pass(self):
        bench = self.c.work / "public-bench"; (bench / "bin").mkdir(parents=True)
        (bench / "bin/checkpoint").write_text("# original judging dependency\n")
        binding_bench = patch.object(run, "BENCH", bench)
        binding_bench.start(); self.addCleanup(binding_bench.stop)
        for change in ("case", "source", "case_id", "bench", "tester"):
            with self.subTest(change=change):
                (self.c.work / "attack-state.json").unlink(missing_ok=True)
                self.interrupt({"complete": True, "blocking": []})
                if change == "case":
                    (self.c.case / "changed.txt").write_text("new revision")
                elif change == "source": self.c.args.source = "different-source"
                elif change == "case_id": self.c.case_id = "another-case"
                elif change == "bench": (bench / "bin/checkpoint").write_text("# changed judging dependency\n")
                else: self.c.models["attacker"] = ["different tester"]
                calls = []
                def model(c, models, text, cwd, name):
                    calls.append(name)
                    self.assertEqual(name, "attacker-2")
                    self.report_path(text).write_text('{"complete": true, "blocking": []}')
                    return 0
                with patch.object(run, "opencode", model): run.build(self.c)
                self.assertEqual(calls, ["attacker-2"])

    def test_historical_blocker_is_not_replayed_against_changed_case(self):
        self.interrupt({"complete": False, "blocking": ["historical defect already repaired"]})
        (self.c.case / "repair.txt").write_text("external repair after interruption")
        def model(c, models, text, cwd, name):
            self.assertEqual(name, "attacker-2")
            self.assertNotIn("historical defect already repaired", text)
            self.report_path(text).write_text('{"complete": true, "blocking": []}')
            return 0
        with patch.object(run, "opencode", model): run.build(self.c)
        self.early_review.assert_called_once()

    def test_legacy_exhausted_claim_cannot_start_a_fresh_session(self):
        (self.c.work / "diagnostic-budgets/attacker-1/claimed").mkdir(parents=True)
        self.assert_unresolved("diagnostic_allowance_exhausted")

    def test_failed_diagnostic_cannot_be_reported_as_passed(self):
        self.interrupt({"complete": True, "blocking": []}, claim=True)
        (self.c.work / "diagnostic-budgets/attacker-1/status.json").write_text('{"status": "timeout"}')
        self.assert_unresolved("unfinished_diagnostic")

    def test_returning_without_a_completed_report_stops_immediately(self):
        with patch.object(run, "opencode", return_value=0) as model, \
             self.assertRaisesRegex(run.BudgetError, "stress_review_unresolved:interrupted_review"):
            run.build(self.c)
        self.assertEqual([call.args[4] for call in model.call_args_list], ["attacker-1"])
        self.early_review.assert_not_called()

    def test_final_repair_stops_unresolved_and_cannot_repeat(self):
        self.c.args.rounds = 1
        self.interrupt({"complete": False, "blocking": ["reference is wrong"]}, claim=True)
        self.c.args.rounds = 9  # A resume flag cannot enlarge the original ceiling.
        with patch.object(run, "opencode", return_value=0) as model, \
             self.assertRaisesRegex(run.BudgetError, "stress_review_unresolved:rounds_exhausted"):
            run.build(self.c)
        self.assertEqual([call.args[4] for call in model.call_args_list], ["builder-precheck"])
        self.assert_unresolved("rounds_exhausted")

    def test_malformed_receipt_cannot_start_a_new_round(self):
        self.interrupt({"complete": True, "blocking": []})
        path = self.c.work / "attack-state.json"
        receipt = json.loads(path.read_text())
        receipt["binding"] = {}
        path.write_text(json.dumps(receipt))
        self.assert_unresolved("invalid_recovery_receipt")

    def test_unchanged_repair_and_interrupted_repair_cannot_restart_tester(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                (self.c.work / "attack-state.json").unlink(missing_ok=True)
                self.interrupt({"complete": False, "blocking": ["reference misses stock update"]})
                def writer(c, models, text, cwd, name):
                    self.assertEqual(name, "builder-2")
                    if interrupted: raise KeyboardInterrupt()
                    return 0
                error = KeyboardInterrupt if interrupted else run.BudgetError
                with patch.object(run, "opencode", writer), self.assertRaises(error):
                    run.build(self.c)
                self.assert_unresolved("interrupted_repair")

    def test_checkpoint_archive_retains_handoff_report_and_consumed_claim(self):
        # Exercise seal's actual whole-workspace archive command. Replace only the
        # encryption subprocess with a plaintext synthetic tar, never a real key.
        import r2_upload
        self.interrupt(claim=True)
        c = self.c
        c.recipient = "synthetic recipient"
        archives = c.work / "synthetic-archives"
        captured = []
        def synthetic_encrypt(command, **kwargs):
            self.assertIsInstance(command, str)
            tokens = shlex.split(command)
            pipe = tokens.index("|")
            self.assertEqual(tokens[3:pipe], ["tar", "-C", str(c.work.parent), "-czf", "-", c.work.name])
            target = pathlib.Path(tokens[-1])
            # Store outside work so our synthetic archive does not include itself.
            with tarfile.open(target, "w:gz") as archive:
                for path in c.work.iterdir():
                    if path != archives:
                        archive.add(path, arcname=c.work.name + "/" + path.name)
            captured.append(target.read_bytes())
            return types.SimpleNamespace(returncode=0)
        with patch.object(run, "SEALED", archives), patch.object(run, "AGENT_STATE", []), \
             patch.object(run, "pilot_homes", return_value=[]), patch.object(run.RunArtifacts, "results_since", return_value=[]), \
             patch.object(run, "STATEMENTS_RECIPIENT", c.work / "no-recipient"), \
             patch.object(r2_upload, "case_recipient", return_value=None), \
             patch.object(run.subprocess, "run", side_effect=synthetic_encrypt):
            run.seal(c, checkpoint=True)
        archive = archives / "synthetic.checkpoint.tar.gz.age"
        with tarfile.open(archive, "r:gz") as saved:
            names = set(saved.getnames())
        for relative in ("attack-state.json", "attacks/round-1.json", "diagnostic-budgets/attacker-1/claimed"):
            self.assertIn(c.work.name + "/" + relative, names)
        self.assertEqual(len(captured), 1)


if __name__ == "__main__":
    unittest.main()
