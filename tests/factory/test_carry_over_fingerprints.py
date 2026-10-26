"""Scoped bindings using real runner source and public-card model metadata only."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin")]
import gate_state
import run


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        factory = self.root / "factory"; factory.mkdir()
        self.runner = factory / "run.py"; self.runner.write_bytes(Path(run.__file__).read_bytes())
        self.work = self.root / "work"; case = self.work / "case"; (case / "base").mkdir(parents=True)
        (case / "base/judge.py").write_text("# public practice stand-in\n")
        card = json.loads((ROOT / "tests/factory/fixtures/e15450-collected-card.json").read_text())
        self.c = SimpleNamespace(work=self.work, case=case, case_id="case-public-contract", seed=7,
            args=SimpleNamespace(**{**card["recovery_config"], "source": "hunt", "dry_run": False, "bench_workers": 1}),
            card={"roles": card["roles"]}, models=card["models"])
        for p in (patch.object(gate_state, "RUNNER", self.runner), patch.object(run, "BENCH", self.root),
                  patch.object(run, "prompt", lambda role, extra: "public recorded " + role + extra)):
            p.start(); self.addCleanup(p.stop)

    def binding(self):
        return run.attack_binding(self.c)

    def calibration(self):
        return run.calibration_identity(self.c, "strong_calibrator", "statement")

    def test_irrelevant_factory_and_orchestration_changes_preserve_reviews(self):
        before = self.binding(); calibration = self.calibration()
        g4 = gate_state.inputs(self.c, "G4", self.root)
        g8 = gate_state.inputs(self.c, "G8", self.root)
        self.runner.write_text(self.runner.read_text() + "\ndef unrelated_carry_over_transport():\n    return 2\n")
        (self.root / "factory/control_resume.py").write_text("# unrelated transport changed\n")
        self.c.manifest0 = "whole-manifest-changed"
        self.assertEqual(self.binding(), before)
        self.assertEqual(self.calibration(), calibration)
        self.assertEqual(gate_state.inputs(self.c, "G4", self.root), g4)
        self.assertEqual(gate_state.inputs(self.c, "G8", self.root), g8)

    def test_judge_prompt_and_model_effort_invalidate_only_dependent_reviews(self):
        before = self.binding(); calibration = self.calibration()
        g4 = gate_state.inputs(self.c, "G4", self.root)
        g8 = gate_state.inputs(self.c, "G8", self.root)
        with patch.object(run, "prompt", lambda role, extra: "changed judging prompt " + role + extra):
            self.assertNotEqual(self.binding(), before)
            self.assertNotEqual(self.calibration(), calibration)
            self.assertNotEqual(gate_state.inputs(self.c, "G8", self.root), g8)
            self.assertEqual(gate_state.inputs(self.c, "G4", self.root), g4)
        self.c.card["roles"]["stress_tester"]["effort"] = "changed"
        self.assertNotEqual(self.binding(), before)
        self.assertEqual(gate_state.inputs(self.c, "G4", self.root), g4)

    def test_specific_parser_case_and_measurement_dependencies_invalidate(self):
        before = self.binding()
        self.runner.write_text(self.runner.read_text().replace('"Partial findings are usable for repair;', '"Changed parser contract;'))
        self.assertNotEqual(self.binding(), before)
        before = self.binding()
        (self.c.case / "case.json").write_text("{}")
        self.assertNotEqual(self.binding(), before)
        before = self.binding(); calibration = self.calibration()
        (self.root / "bin").mkdir()
        (self.root / "bin/diagnostic_budget.py").write_text("# diagnostic allowance contract changed\n")
        self.assertNotEqual(self.binding(), before)
        self.assertNotEqual(self.calibration(), calibration)

    def test_effective_execution_settings_invalidate_stress_contract(self):
        for name in ('runs', 'scenario_runs', 'agent_timeout', 'max_role_calls', 'max_total_calls',
                     'max_cost', 'no_progress_minutes', 'max_zero_tokens'):
            with self.subTest(setting=name):
                before = self.binding()
                original = getattr(self.c.args, name)
                setattr(self.c.args, name, original + 1)
                self.assertNotEqual(self.binding(), before)
                setattr(self.c.args, name, original)


if __name__ == "__main__": unittest.main()
