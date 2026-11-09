"""Synthetic contestant delivery and real artifact routing; no models or containers."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse
import json
import shutil
from contextlib import ExitStack, contextmanager
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path[:0] = [str((pathlib.Path(__file__).resolve().parents[2] / "factory")), str(pathlib.Path(__file__).resolve().parents[2] / "bin")]
import bench
import run
import exam_responder
from calibration import GUARD_FILES, atomic_results, completed_attempts, guard_submitted, prepare_delivery, tree_digest


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.case = self.root / "case"
        self.base = self.case / "base"; self.base.mkdir(parents=True)
        self.source = self.case / "services/channel"; self.source.mkdir(parents=True)
        self.bench = self.root / "bench"
        app = self.bench / "projects/medusa"; app.mkdir(parents=True)
        (app / "source.js").write_text("const old = true;\n")
        (self.base / "scenario.json").write_text(json.dumps({"id": "BASE", "inventory_services": [
            {"name": "channel", "project": "../services/channel", "host_ports": [9010]}]}))
        for name in ("compose.yaml", "adapter.py", "Dockerfile"):
            (self.source / name).write_text("synthetic immutable infrastructure")
        (self.source / "service.py").write_text('PORT = "http://127.0.0.1:9010"\n')
        (self.source / "README.md").write_text("API http://127.0.0.1:9010; see projects/channel/service.py\n")
        (self.case / "promise.md").write_text("Preserve fitting business.\n")
        (self.case / "contestant.md").write_text(
            "Read projects/channel/README.md and projects/medusa/integrations/channel/service.py. "
            "Use services.patch, paths channel/service.py.\n")
        (self.case / "statement.md").write_text("synthetic statement")
        for name in ("fact-sheet.md", "answer-key.json"):
            (self.case / name).write_text("PRIVATE_SENTINEL")
        (self.base / "admin.sql").write_text("-- synthetic baseline\n")
        visible = self.case / "harbor/synthetic/steps/establish/workdir/services/store/admin.sql"
        visible.parent.mkdir(parents=True)
        visible.write_bytes((self.base / "admin.sql").read_bytes())

    def test_delivery_paths_wall_and_source_bytes(self):
        for exposure in ("blind", "exam", "statement"):
            ws = self.root / exposure
            receipt = prepare_delivery(self.case, self.bench, ws, exposure=exposure, slot=2)
            self.assertEqual(receipt["guard_files"], list(bench.GUARD_FILES))
            self.assertEqual((ws / "services/channel/service.py").read_bytes(), (self.source / "service.py").read_bytes())
            self.assertEqual((ws / "services/channel/README.md").read_bytes(), (self.source / "README.md").read_bytes())
            self.assertIn("9010 -> 9210", (ws / "DELIVERY.md").read_text())
            contract = (ws / "contestant.md").read_text()
            self.assertIn("services/channel/README.md", contract)
            self.assertIn("services/channel/service.py", contract)
            self.assertEqual((ws / "statement.md").exists(), exposure == "statement")
            for forbidden in ("fact-sheet.md", "answer-key.json", "services/channel/adapter.py", "services/channel/compose.yaml"):
                self.assertFalse((ws / forbidden).exists())
            self.assertFalse(any("PRIVATE_SENTINEL" in p.read_text() for p in ws.rglob("*") if p.is_file()))

    def test_missing_or_private_material_fails_before_delivery(self):
        for damage in ("readme", "promised", "symlink", "private"):
            with self.subTest(damage=damage):
                saved = self.source / "README.md"
                original = saved.read_text()
                if damage == "readme": saved.unlink()
                if damage == "promised": saved.write_text("See services/channel/missing.py")
                if damage == "symlink": (self.source / "escape.py").symlink_to(self.case / "fact-sheet.md")
                if damage == "private": saved.write_text("The answer key is unavailable")
                ws = self.root / ("missing-" + damage)
                with self.assertRaises(ValueError): prepare_delivery(self.case, self.bench, ws)
                self.assertFalse(ws.exists(), "preflight must complete before preparation/model spend")
                saved.write_text(original)
                (self.source / "escape.py").unlink(missing_ok=True)

    def test_case_material_defects_are_case_problems_not_infrastructure(self):
        # 18681d (9 November): its baseline SQL differed from the copy the exam delivers, and the
        # plain ValueError was retried six times as infrastructure. A case defect fails the gate.
        from case_contract import CaseProblem
        visible = self.case / "harbor/synthetic/steps/establish/workdir/services/store/admin.sql"
        visible.write_text("-- a different contestant baseline\n")
        with self.assertRaises(CaseProblem): prepare_delivery(self.case, self.bench, self.root / "mismatch")
        self.assertFalse((self.root / "mismatch").exists())
        visible.write_bytes((self.base / "admin.sql").read_bytes())
        (self.source / "README.md").unlink()
        with self.assertRaises(CaseProblem): prepare_delivery(self.case, self.bench, self.root / "no-readme")
        (self.source / "README.md").write_text("API http://127.0.0.1:9010\n")
        # The permitted application and the factory's own state stay outside the case contract.
        (self.bench / "projects/medusa/credentials.json").write_text("SYNTHETIC_CREDENTIAL")
        with self.assertRaises(ValueError) as caught: prepare_delivery(self.case, self.bench, self.root / "bench")
        self.assertNotIsInstance(caught.exception, CaseProblem)
        (self.bench / "projects/medusa/credentials.json").unlink()
        (self.root / "exists").mkdir()
        with self.assertRaises(ValueError) as caught: prepare_delivery(self.case, self.bench, self.root / "exists")
        self.assertNotIsInstance(caught.exception, CaseProblem)

    def test_application_contract_and_private_content_all_exposures(self):
        app = self.bench / "projects/medusa"
        dependencies = app / "node_modules/.bin"
        dependencies.mkdir(parents=True)
        (dependencies / "tool").symlink_to(app / "source.js")
        for exposure in ("blind", "exam", "statement"):
            (app / ".env").write_text("OPENAI_API_KEY=SYNTHETIC_PROVIDER_SECRET")
            (app / "credentials.json").write_text("SYNTHETIC_CREDENTIAL")
            with self.assertRaises(ValueError):
                prepare_delivery(self.case, self.bench, self.root / exposure, exposure=exposure)
            (app / "credentials.json").unlink()
            ws = self.root / exposure
            prepare_delivery(self.case, self.bench, ws, exposure=exposure)
            self.assertFalse((ws / "app/.env").exists())
            shutil.rmtree(ws)
            (app / "source.js").write_text("// reference fix: SYNTHETIC_PRIVATE_ANSWER")
            with self.assertRaises(ValueError): prepare_delivery(self.case, self.bench, ws, exposure=exposure)
            self.assertFalse(ws.exists())
            (app / "source.js").write_text("const old = true;\n")
        # Case-authored leak indicators apply to the permitted application source too.
        (self.case / "case.json").write_text(json.dumps({"leak_words": ["SYNTHETIC_CASE_ANSWER"]}))
        (app / "source.js").write_text("// SYNTHETIC_CASE_ANSWER")
        with self.assertRaises(ValueError): prepare_delivery(self.case, self.bench, self.root / "leak")

    def test_application_baseline_cannot_add_hidden_state_or_follow_links(self):
        app = self.bench / "projects/medusa"
        (self.base / "app.patch").write_text(
            "--- /dev/null\n+++ b/.env\n@@ -0,0 +1 @@\n+SYNTHETIC_PROVIDER_SECRET=1\n")
        with self.assertRaises(ValueError): prepare_delivery(self.case, self.bench, self.root / "hidden-patch")
        self.assertFalse((self.root / "hidden-patch").exists())
        (self.base / "app.patch").unlink()
        (app / "linked.js").symlink_to(app / "source.js")
        with self.assertRaises(ValueError): prepare_delivery(self.case, self.bench, self.root / "linked-app")
        (app / "linked.js").unlink()
        moved = self.root / "moved-app"
        app.rename(moved); app.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError): prepare_delivery(self.case, self.bench, self.root / "app-root")

    def test_service_root_ancestor_child_and_absolute_escape(self):
        outside = self.root / "outside"
        self.source.rename(outside)
        self.source.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError): prepare_delivery(self.case, self.bench, self.root / "rootlink")
        self.source.unlink()
        self.source.parent.rmdir()
        self.source.parent.symlink_to(self.root, target_is_directory=True)
        outside.rename(self.root / "channel")
        with self.assertRaises(ValueError): prepare_delivery(self.case, self.bench, self.root / "ancestor")
        self.source.parent.unlink()
        self.source.parent.mkdir()
        (self.root / "channel").rename(self.source)
        (self.source / "child.py").symlink_to(self.source / "service.py")
        with self.assertRaises(ValueError): prepare_delivery(self.case, self.bench, self.root / "child")
        (self.source / "child.py").unlink()
        scenario = json.loads((self.base / "scenario.json").read_text())
        scenario["inventory_services"][0]["project"] = str(self.source)
        (self.base / "scenario.json").write_text(json.dumps(scenario))
        prepare_delivery(self.case, self.bench, self.root / "absolute-allowed")
        self.source.rename(outside)
        scenario["inventory_services"][0]["project"] = str(outside)
        (self.base / "scenario.json").write_text(json.dumps(scenario))
        with self.assertRaises(ValueError): prepare_delivery(self.case, self.bench, self.root / "absolute-outside")

    def test_case_projects_delivery_uses_the_same_private_material_wall(self):
        project = self.case / 'projects/channel'; project.parent.mkdir()
        self.source.rename(project)
        scenario = json.loads((self.base / 'scenario.json').read_text())
        scenario['inventory_services'][0]['project'] = '../projects/channel'
        (self.base / 'scenario.json').write_text(json.dumps(scenario))
        ws = self.root / 'case-projects'
        prepare_delivery(self.case, self.bench, ws)
        self.assertEqual((ws / 'services/channel/service.py').read_bytes(), (project / 'service.py').read_bytes())
        self.assertFalse((ws / 'services/channel/adapter.py').exists())
        (project / 'answer-key.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'private material'):
            prepare_delivery(self.case, self.bench, self.root / 'case-projects-private')

    def test_service_document_line_endings_are_preserved(self):
        (self.source / "README.md").write_bytes(b"API http://127.0.0.1:9010\r\n")
        ws = self.root / "crlf"
        prepare_delivery(self.case, self.bench, ws, slot=2)
        self.assertEqual((ws / "services/channel/README.md").read_bytes(), (self.source / "README.md").read_bytes())

    def test_readme_patch_matches_local_and_runtime_copy(self):
        ws = self.root / "readme"
        prepare_delivery(self.case, self.bench, ws, slot=2)
        guard = ws / "guard"; guard.mkdir()
        original = (self.source / "README.md").read_text()
        (guard / "services.patch").write_text("--- a/channel/README.md\n+++ b/channel/README.md\n@@ -1 +1 @@\n-" + original + "+" + original.replace("API ", "Updated API "))
        subprocess.run([sys.executable, str(ws / "bin/check-patches")], check=True, capture_output=True)
        seen = []
        def command(argv, cwd=None, **kwargs):
            if argv[0] == "git": return subprocess.check_output(argv, cwd=cwd, text=True)
            if "build" in argv:
                config = json.loads((self.root / "readme-override.json").read_text())
                context = pathlib.Path(config["services"]["channel"]["build"]["context"])
                seen.append((context / "README.md").read_text()); return ""
            raise AssertionError(argv)
        with mock.patch.object(bench, "command", command):
            bench.build_inventory_services(bench.inventory_services([bench.load_scenario(self.base)]),
                guard, (), ["docker", "compose"], self.root / "readme-override.json")
        self.assertEqual(seen, [original.replace("API ", "Updated API ")])

    def test_checked_g16_cache_uses_effective_attempt_identity(self):
        import gate_state
        c = self.calibration_context("cache")
        c.manifest0 = "synthetic"; c.args.runs = 2; c.args.scenario_runs = 1
        def gate(ctx):
            target = ctx.work / "judge_breadth/evidence.json"
            target.parent.mkdir(exist_ok=True)
            target.write_text(str(len(calls)))
            calls.append(True)
            return True, {"accepted": True}
        calls = []
        with mock.patch.object(run, "BENCH", self.bench), mock.patch.object(run, "g16", gate), \
                mock.patch.object(run, "prompt", return_value="synthetic pilot instructions"):
            self.assertTrue(run.checked_gate(c, "G16")[0])
            self.assertTrue(run.checked_gate(c, "G16")[1]["reused_verified_evidence"])
            mutations = [lambda: setattr(c.args, "calibrator_minutes", 1),
                         lambda: setattr(c, "factory_slot", 3),
                         lambda: c.models.update(strong_calibrator=["synthetic/new"]),
                         lambda: setattr(c.args, "max_total_calls", 4),
                         lambda: (self.bench / "projects/medusa/source.js").write_text("const changed = true;")]
            for mutate in mutations:
                mutate(); before = len(calls)
                run.checked_gate(c, "G16")
                self.assertEqual(len(calls), before + 1)
            before = len(calls)
            (self.bench / "orchestration.py").write_text("unrelated orchestration")
            self.assertTrue(run.checked_gate(c, "G16")[1]["reused_verified_evidence"])
            self.assertEqual(len(calls), before)
            with mock.patch.object(run, "prompt", return_value="changed pilot instructions"):
                before = len(calls); run.checked_gate(c, "G16")
                self.assertEqual(len(calls), before + 1)

    def test_pinned_project_delivery_and_baseline_patch(self):
        pinned = self.bench / "projects/channel"
        self.source.rename(pinned)
        scenario = json.loads((self.base / "scenario.json").read_text())
        scenario["inventory_services"][0]["project"] = "projects/channel"
        (self.base / "scenario.json").write_text(json.dumps(scenario))
        (self.base / "app.patch").write_text(
            "--- a/source.js\n+++ b/source.js\n@@ -1 +1 @@\n-const old = true;\n+const old = false;\n")
        ws = self.root / "pinned"
        with mock.patch.object(bench, "ROOT", self.bench):
            prepare_delivery(self.case, self.bench, ws)
        self.assertEqual((ws / "app/source.js").read_text(), "const old = false;\n")
        self.assertEqual((self.bench / "projects/medusa/source.js").read_text(), "const old = true;\n")
        self.assertEqual((ws / "services/channel/service.py").read_bytes(), (pinned / "service.py").read_bytes())

    def test_service_only_receipt_and_real_application_routing(self):
        ws = self.root / "attempt"
        prepare_delivery(self.case, self.bench, ws)
        guard = ws / "guard"; guard.mkdir()
        patch = guard / "services.patch"
        patch.write_text('--- a/channel/service.py\n+++ b/channel/service.py\n@@ -1 +1 @@\n-PORT = "http://127.0.0.1:9010"\n+PORT = "http://127.0.0.1:9011"\n')
        subprocess.run([sys.executable, str(ws / "bin/check-patches"), "guard"], cwd=ws,
                       check=True, capture_output=True)
        self.assertTrue(guard_submitted(guard))
        self.assertEqual(GUARD_FILES, bench.GUARD_FILES)
        path = self.root / "results.json"
        row = {"try": 1, "identity": {"synthetic": True}, "workspace": str(ws), "guard": str(guard),
               "guard_submitted": True, "solved": True, "artifacts": tree_digest(ws)}
        atomic_results(path, [row])
        self.assertEqual(completed_attempts(path, row["identity"], self.root), [row])
        # Use the production service copy/apply seam; only the final Docker build is replaced.
        seen = []
        def command(argv, cwd=None, **kwargs):
            if argv[0] == "git":
                return subprocess.check_output(argv, cwd=cwd, text=True)
            if "build" in argv:
                config = json.loads((self.root / "override.json").read_text())
                source = pathlib.Path(config["services"]["channel"]["build"]["context"]) / "service.py"
                seen.append(source.read_text())
                return ""
            raise AssertionError(argv)
        services = bench.inventory_services([bench.load_scenario(self.base)])
        with mock.patch.object(bench, "command", command):
            bench.build_inventory_services(services, guard, (), ["docker", "compose"], self.root / "override.json")
        self.assertEqual(seen, ['PORT = "http://127.0.0.1:9011"\n'])
        self.assertIn(":9010", (self.source / "service.py").read_text())
        patch.unlink()
        self.assertEqual(completed_attempts(path, row["identity"], self.root), [])

    def calibration_context(self, exposure):
        c = run.Ctx()
        c.case = self.case
        c.work = self.root / ("work-" + exposure); c.work.mkdir()
        c.args = argparse.Namespace(pilot_tries=1, pilot_runs=2, calibrator_minutes=30, resume=None)
        c.models = {"strong_calibrator": ["synthetic/strong"], "easy_calibrator": ["synthetic/easy"],
                    "reviewers": [["synthetic/owner"]]}
        c.seed = 7; c.card = {}; c.pilot_passes = []; c.factory_slot = 2
        protocol = self.bench / "harbor/responder"; protocol.mkdir(parents=True, exist_ok=True)
        for name in ("responder.py", "ask-human"): (protocol / name).write_text("synthetic protocol")
        return c

    def test_real_calibrate_delivery_submission_owner_and_recovery(self):
        for exposure, role in (("blind", "easy_calibrator"), ("exam", "strong_calibrator"),
                               ("statement", "strong_calibrator")):
            with self.subTest(exposure=exposure), ExitStack() as stack:
                c = self.calibration_context(exposure)
                for name in ("judge.py", "key.json"):
                    (self.base / name).write_text('{"private": "PRIVATE_SENTINEL"}')
                home = self.root / ("pilot-" + exposure); home.mkdir()
                calls, owners, applied = [], [], []
                def shell(ctx, argv, **kwargs):
                    if argv[:3] == ["sudo", "cp", "-a"]:
                        shutil.copytree(argv[3], argv[4])
                    return 0
                @contextmanager
                def owner(*args):
                    owners.append(args)
                    yield "SYNTHETIC_OWNER_CHANNEL"
                def model(ctx, models, text, dest, name, **kwargs):
                    calls.append(name)
                    self.assertEqual(kwargs["user"], "pilot")
                    self.assertEqual(kwargs["timeout"], 1800)
                    self.assertEqual("SYNTHETIC_OWNER_CHANNEL" in text, exposure == "exam")
                    self.assertEqual((dest / "statement.md").exists(), exposure == "statement")
                    self.assertEqual((dest / "services/channel/README.md").read_bytes(), (self.source / "README.md").read_bytes())
                    self.assertIn("services/channel/service.py", (dest / "contestant.md").read_text())
                    self.assertTrue((dest / "app/source.js").is_file())
                    self.assertTrue((dest / "baseline/admin.sql").is_file())
                    for path in dest.rglob("*"):
                        if path.is_file(): self.assertNotIn("PRIVATE_SENTINEL", path.read_text())
                    self.assertFalse((dest / "services/channel/adapter.py").exists())
                    guard = dest / "guard"; guard.mkdir()
                    (guard / "services.patch").write_text(
                        '--- a/channel/service.py\n+++ b/channel/service.py\n@@ -1 +1 @@\n'
                        '-PORT = "http://127.0.0.1:9010"\n+PORT = "http://127.0.0.1:9011"\n')
                    subprocess.run([sys.executable, str(dest / "bin/check-patches")], cwd=dest,
                                   check=True, capture_output=True)
                def command(argv, cwd=None, **kwargs):
                    if argv[0] == "git": return subprocess.check_output(argv, cwd=cwd, text=True)
                    if "build" in argv:
                        config = json.loads((c.work / "override.json").read_text())
                        source = pathlib.Path(config["services"]["channel"]["build"]["context"]) / "service.py"
                        applied.append(source.read_text()); return ""
                    raise AssertionError(argv)
                def checkpoint(ctx, scenarios, guard, runs, seed, label):
                    self.assertEqual(runs, 2)
                    self.assertEqual(seed, 8)
                    self.assertEqual({p.name for p in guard.iterdir()}, {"services.patch"})
                    services = bench.inventory_services([bench.load_scenario(self.base)])
                    # Production service source copy, patch validation, and git application.
                    bench.build_inventory_services(services, guard, (), ["docker", "compose"], c.work / "override.json")
                    return {}, [{}, {}]
                for obj, name, value in ((run, "BENCH", self.bench), (run, "pilot_home", lambda _: home),
                        (run, "sh", shell), (run, "shred_tree", lambda p, **kw: shutil.rmtree(p) if p.exists() else None),
                        (run, "model_call", model), (run, "checkpoint", checkpoint),
                        (run, "verdicts", lambda ctx, rows: [{"clean": True, "solved": True}] * len(rows)),
                        (exam_responder, "owner_channel", owner), (bench, "command", command)):
                    stack.enter_context(mock.patch.object(obj, name, value))
                result = run.calibrate(c, role, exposure=exposure)
                self.assertEqual(result["solved"], 1)
                self.assertEqual(len(owners), int(exposure == "exam"))
                self.assertEqual(applied, ['PORT = "http://127.0.0.1:9011"\n'])
                self.assertEqual(run.calibrate(c, role, exposure=exposure), {**result, "kept": True})
                self.assertEqual(len(calls), 1)
                # Delivery code is bound independently of the case/bench (factory is excluded).
                receipt = c.work / role / "results.json"
                rows = json.loads(receipt.read_text())
                rows[0]["identity"]["checker"] = "pre-integration-delivery"
                atomic_results(receipt, rows)
                run.calibrate(c, role, exposure=exposure)
                self.assertEqual(len(calls), 2)
                self.assertTrue(list(receipt.parent.glob("results-unverified-*.json")))
                # Pinned-source changes also invalidate evidence, even when case bytes agree.
                (self.bench / "projects/medusa/source.js").write_text("const updated = true;\n")
                run.calibrate(c, role, exposure=exposure)
                self.assertEqual(len(calls), 3)
                (self.bench / "projects/medusa/source.js").write_text("const old = true;\n")

    def test_exam_admission_authenticates_portable_completed_receipts(self):
        import hashlib
        import copy
        import sealed_audit
        c = self.calibration_context("proof")
        # The production archive keeps the case beneath its work root.
        shutil.copytree(c.case, c.work / "case"); c.case = c.work / "case"
        config = dict(runs=2, scenario_runs=1, pilot_runs=2, pilot_tries=1,
            calibrator_minutes=30, max_role_calls=400, max_cost=5.0,
            max_total_calls=1000, no_progress_minutes=45, max_zero_tokens=3)
        c.args = argparse.Namespace(**config)
        c.case_id = "synthetic-proof"
        c.card = {"case": c.case_id, "seed": c.seed, "roles": {
            role: {"model": c.models[role][0], "effort": "high"}
            for role in ("strong_calibrator", "easy_calibrator")},
            "recovery_config": config, "gates": {f"G{i}": "pass" for i in range(1, 18)}}
        c.card["roles"]["reviewer"] = {"model": c.models["reviewers"][0][0], "effort": "high"}
        c.card["owner_contract"] = exam_responder.contract(pathlib.Path(run.__file__).resolve().parents[1], c.card["roles"]["reviewer"])
        from calibration import attempt_summary
        c.card["calibrators"] = {}
        with mock.patch.object(run, "BENCH", self.bench):
            for folder, role, exposure in (("judge_breadth", "strong_calibrator", "statement"),
                    ("strong_calibrator", "strong_calibrator", "exam"),
                    ("easy_calibrator", "easy_calibrator", "blind")):
                ws = c.work / folder / "try-1"
                prepare_delivery(c.case, self.bench, ws, exposure=exposure, slot=2)
                guard = ws / "guard"; guard.mkdir(); (guard / "db.sql").write_text("-- synthetic")
                row = {"try": 1, "solved": True, "guard_submitted": True, "guard": str(guard),
                    "workspace": str(ws), "artifacts": tree_digest(ws),
                    "identity": run.calibration_identity(c, role, exposure, runs=2)}
                atomic_results(c.work / folder / "results.json", [row])
                if folder != "judge_breadth":
                    c.card["calibrators"]["strong" if role == "strong_calibrator" else "easy"] = attempt_summary([row])
            # Authenticate the completed delivery artifacts carried by the worker snapshot.
            sealed_audit.retain_delivery(c, run)
            archive = self.root / "synthetic.age"; archive.write_bytes(b"synthetic authenticated ciphertext stand-in")
            c.card["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
            restored = self.root / "restored"
            shutil.copytree(c.work, restored)
            shutil.rmtree(c.work)
            before = copy.deepcopy(c.card)
            self.assertIs(sealed_audit.verify_exam(c.card, c.case_id, restored_work=restored, archive=archive), c.card)
            self.assertEqual(c.card, before)
            with self.assertRaises(ValueError): sealed_audit.verify_exam(c.card, c.case_id)
            # Public metadata cannot invent or upgrade evidence inside the ciphertext.
            proof_path = restored / "delivery-provenance.json"
            original = proof_path.read_bytes()
            proof_path.write_bytes(original + b" ")
            with self.assertRaises(ValueError): sealed_audit.verify_exam(c.card, c.case_id, restored_work=restored, archive=archive)
            proof_path.write_bytes(original)
            (restored / "easy_calibrator/try-1/app/source.js").write_text("tampered")
            with self.assertRaises(ValueError): sealed_audit.verify_exam(c.card, c.case_id, restored_work=restored, archive=archive)
            (restored / "easy_calibrator/try-1/app/source.js").write_text("const old = true;\n")
            c.card["recovery_config"]["calibrator_minutes"] = 1
            with self.assertRaises(ValueError): sealed_audit.verify_exam(c.card, c.case_id, restored_work=restored, archive=archive)

    def test_fairness_audit_easy_summary_cannot_bypass_receipts(self):
        c = self.calibration_context("audit")
        c.audit_keep_easy = True
        c.card["calibrators"] = {"easy": {"tries": 3, "solved": 0, "legacy": True}}
        c.models["easy_calibrator"] = ["synthetic/easy"]
        c.args.concurrent_roles = False
        with mock.patch.object(run, "parallel_calibrators", return_value=False), \
             mock.patch.object(run, "make_pilots"), \
             mock.patch.object(run, "calibrate", return_value={"tries": 1, "solved": 0}) as calibrate, \
             mock.patch.object(exam_responder, "contract", return_value={}):
            self.assertTrue(run.g10(c)[0])
        self.assertEqual([call.args[1] for call in calibrate.call_args_list],
                         ["strong_calibrator", "easy_calibrator"])
        self.assertNotIn("legacy", c.card["calibrators"]["easy"])

    def test_real_calibrate_missing_material_never_calls_model(self):
        c = self.calibration_context("blind")
        (self.source / "README.md").unlink()
        with mock.patch.object(run, "BENCH", self.bench), mock.patch.object(run, "sh"), \
             mock.patch.object(run, "model_call") as model:
            with self.assertRaisesRegex(ValueError, "missing service documentation"):
                run.calibrate(c, "easy_calibrator")
            model.assert_not_called()
        self.assertFalse((c.work / "easy_calibrator/try-1").exists())

    def test_documented_installation_order_matches_reset(self):
        (self.case / "contestant.md").write_text("The baseline is services/store/admin.sql. Read services/channel/README.md.")
        ws = self.root / "ordered"
        prepare_delivery(self.case, self.bench, ws)
        self.assertIn("baseline/admin.sql", (ws / "contestant.md").read_text())
        guard = ws / "guard"; guard.mkdir()
        (guard / "db.sql").write_text("-- synthetic guard")
        events = []
        def sql(text, **kwargs):
            if text.startswith("-- synthetic"): events.append(text.strip())
            return "1"
        with mock.patch.object(bench, "resolve_guard", return_value=guard), \
             mock.patch.object(bench, "stop_inventory_services"), mock.patch.object(bench, "dc"), \
             mock.patch.object(bench, "sql", sql), mock.patch.object(bench, "checker", return_value=bench.EXPECTED_BASELINE), \
             mock.patch.object(bench, "start_app", side_effect=lambda *a: events.append("app")), \
             mock.patch.object(bench, "start_inventory_services", side_effect=lambda *a: events.append("services")):
            bench.reset(guard, scenarios=[bench.load_scenario(self.base)], app_prepared=True)
        self.assertEqual(events, ["-- synthetic guard", "-- synthetic baseline", "app", "services"])
        notes = (ws / "DELIVERY.md").read_text()
        self.assertLess(notes.index("guard/db.sql;"), notes.index("baseline/admin.sql (if supplied)"))


if __name__ == "__main__": unittest.main()
