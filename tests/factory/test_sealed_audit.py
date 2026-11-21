"""Synthetic source preservation and selective-check dispatch."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import os
import pathlib
import tempfile
import types
import unittest
import subprocess
import sys
from unittest.mock import Mock

import sealed_audit


class AuditTests(unittest.TestCase):
    def test_the_delivery_contract_is_the_one_sealed_cases_carry(self):
        """verify_exam_metadata refuses a sealed card whose delivery contract differs from the current code's,
        so an edit of any file below makes every sealed case unexaminable (the seal freeze; 2026-11-18 the
        hand-repair gate reuse first changed gate_state.py). Change these only with a reviewed contract pin."""
        self.assertEqual(sealed_audit.delivery_contract(), {
            "run.py": "e9e5e71b886e448735a024d052e7db3c8ec9e1e2d53eafbe060a5b375667752c",
            "gate_state.py": "85ff257e30d745bd4d93636d85431b94f584d32ecfe1606c89f94eeae26325eb",
            "calibration.py": "5917db73149f23731be48430c9665e957a33afb4ff08cd15ca81862660b52270",
            "sealed_audit.py": "681286c25638d981f13b5090b21be5d0da365ba0669072d3df52f7ac2be198b7",
            "prompts/pilot.md": "5c8d1c8db27f95a4e4ac3b6abbdf91877da654899f006c8c8f43be5f1281b840"})

    def test_exam_rejects_legacy_and_failed_fairness(self):
        card = {"case": "synthetic", "sha256": "a" * 64,
                "gates": {f"G{i}": "pass" for i in range(1, 16)}}
        with self.assertRaises(ValueError):
            sealed_audit.verify_exam(card, "synthetic")
        card["gates"].update(G16="pass", G17="fail")
        with self.assertRaises(ValueError):
            sealed_audit.verify_exam(card, "synthetic")
        card["gates"]["G17"] = "pass"
        from exam_responder import contract
        card["roles"] = {"reviewer": {"model": "synthetic/reviewer", "effort": "high"}}
        card["owner_contract"] = contract(pathlib.Path(__file__).resolve().parents[2], card["roles"]["reviewer"])
        with self.assertRaisesRegex(ValueError, "authenticated delivery receipts"):
            sealed_audit.verify_exam(card, "synthetic")
        # A current-version flag is not a substitute for the encrypted proof.
        card["delivery_provenance"] = {"contract": sealed_audit.delivery_contract(), "sha256": "b" * 64}
        with self.assertRaisesRegex(ValueError, "authenticated restored archive"):
            sealed_audit.verify_exam(card, "synthetic")

    def test_copy_preserves_source_and_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp); work = root / "case-synthetic"
            case = work / "case"; case.mkdir(parents=True)
            (case / "promise.md").write_text("synthetic promise")
            sealed = root / "sealed"; sealed.mkdir()
            card = {"case": work.name, "gates": {f"G{i}": "pass" for i in range(1, 16)},
                    "roles": {}, "sha256": "a" * 64, "seed": 7,
                    "continuation_budget": {"calls": 42, "cost": 1.2}}
            (work / "scorecard.json").write_text(json.dumps(card))
            (sealed / (work.name + ".source-scorecard.json")).write_text(json.dumps(card))
            runner = types.SimpleNamespace(SEALED=sealed, jload=lambda p, d: json.loads(p.read_text()))
            def context():
                return types.SimpleNamespace(work=work, case=case, case_id=work.name,
                    args=types.SimpleNamespace(rehearse_only=False))
            c = context()
            before = (work / "scorecard.json").read_bytes()
            sealed_audit.prepare(c, runner)
            self.assertEqual(c.case_id, "case-synthetic-fairness")
            (c.case / "promise.md").write_text("edited audit copy")
            self.assertEqual((case / "promise.md").read_text(), "synthetic promise")
            self.assertEqual((work / "scorecard.json").read_bytes(), before)
            self.assertEqual(json.loads((c.work / "continuation-budget.json").read_text())["calls"], 42)
            c.case.joinpath("promise.md").write_text("synthetic promise")
            del c.audit_previous
            sealed_audit.recover(c, runner)
            self.assertTrue(c.args.audit_fairness)
            self.assertEqual(c.audit_previous["sha256"], card["sha256"])
            with self.assertRaises(ValueError):
                sealed_audit.prepare(context(), runner)

    def test_only_new_checks_and_fresh_runtime(self):
        source = {"roles": {}, "gates": {f"G{i}": "pass" for i in range(1, 16)},
                  "calibrators": {"easy": {"tries": 3, "solved": 0}}}
        c = types.SimpleNamespace(card={"roles": {}}, audit_source={"case": "synthetic"},
                                  audit_previous=source, args=types.SimpleNamespace(rehearse_only=False))
        runner = types.SimpleNamespace(g3=Mock(return_value=(True, {})), validate_and_repair=Mock())
        sealed_audit.run(c, runner)
        self.assertEqual(c.audit_gates, ["G16", "G10", "G17", "G11"])
        self.assertNotIn("G12", c.card["gates"])
        self.assertEqual(c.card["gates"]["G4"], "pass")
        self.assertTrue(c.audit_keep_easy)
        runner.g3.assert_called_once_with(c)
        runner.validate_and_repair.assert_called_once_with(c)

    def test_runner_dispatch_seals_a_copy_without_building(self):
        script = r'''
import json, pathlib, sys
from unittest.mock import patch
import run, worker_release
root = pathlib.Path(sys.argv[1]); mode = sys.argv[2]
source = root / "work/case-synthetic"; (source / "case").mkdir(parents=True)
(source / "logs").mkdir(); (source / "case/promise.md").write_text("synthetic")
sealed = root / "sealed"; sealed.mkdir()
card = {"case": source.name, "seed": 7, "sha256": "a" * 64, "roles": {},
        "gates": {f"G{i}": "pass" for i in range(1, 16)},
        "calibrators": {"easy": {"tries": 3, "solved": 0}},
        "continuation_budget": {"calls": 42, "cost": 1.2, "events": []}}
(source / "scorecard.json").write_text(json.dumps(card))
(sealed / (source.name + ".source-scorecard.json")).write_text(json.dumps(card))
run.HOME = root; run.SEALED = sealed; run.BENCH = root / "bench"
run.sh = lambda *a, **kw: 0; run.bench_manifest = lambda: "trusted"
run.pilot_homes = lambda: []
def forbidden(*a, **kw): raise AssertionError("audit must not build")
run.engine_writer_round = forbidden
def pick(c): c.card["roles"] = {}; return {}
run.pick_models = pick
worker_release.verify_selected_drivers = lambda *a, **kw: {}
run.g3 = lambda c: (True, {})
def gates(c):
    expected = ["G3", "G4", "G5"] if mode == "--rehearse-only" else ["G16", "G10", "G17", "G11"]
    assert c.audit_gates == expected
    for gate in c.audit_gates: c.card["gates"][gate] = "pass"
    (root / "checked").touch()
run.run_gates = gates
def seal(c, **kw):
    assert c.work != source and c.card["audit_source"]["case"] == source.name
    (root / "sealed-copy").touch()
run.seal = seal
with patch.object(sys, "argv", ["run.py", "--source", "port", "--resume", source.name,
                              "--resume-bench-sha", "trusted", mode]):
    run.main()
assert (root / "checked").exists() and (root / "sealed-copy").exists()
assert json.loads((source / "scorecard.json").read_text()) == card
'''
        for mode in ("--audit-fairness", "--rehearse-only"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run([sys.executable, "-c", script, tmp, mode],
                                        cwd=(pathlib.Path(__file__).resolve().parents[2] / "factory"),
                                        env={**os.environ, "PYTHONPATH": str(_TEST_ROOT / "factory") + os.pathsep + str(_TEST_ROOT / "bin")},
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
