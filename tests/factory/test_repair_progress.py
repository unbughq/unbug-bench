"""Offline gate feedback, retained evidence and registry regression checks."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

import gate_state
import run
from registry import Registry


class RepairProgressTests(unittest.TestCase):
    def context(self, root):
        c = types.SimpleNamespace(
            work=root / "work", case=root / "work/case", manifest0="trusted", seed=7,
            card={"gates": {}}, models={}, args=types.SimpleNamespace(
                runs=10, scenario_runs=3, dry_run=False, max_repairs=2, rounds=8))
        c.case.mkdir(parents=True)
        (c.work / "logs").mkdir()
        (c.case / "base").mkdir()
        (c.case / "base/judge.py").write_text("synthetic judge")
        (c.case / "promise.md").write_text("synthetic promise")
        return c

    def test_failed_gate_returns_feedback_before_engine_schedules_repair(self):
        from durable.contract import Outcome
        with tempfile.TemporaryDirectory() as tmp:
            c = self.context(pathlib.Path(tmp)); c.stopped = False
            calls = []
            def gates(ctx):
                calls.append(ctx.work)
                failed = (ctx.case / "base/judge.py").read_text() != "repaired judge"
                ctx.card["gates"] = {"G15": "fail" if failed else "pass"}
                ctx.card["failed_gate"] = "G15" if failed else None
                if failed: ctx.card["failed_detail"] = {"wrong": 1}
            with patch.object(run, "run_gates", gates), \
                 patch.object(run, "g1", return_value=(True, {"problems": []})), \
                 patch.object(run, "ensure_freshness"), \
                 patch.object(run, "opencode") as model:
                result = run.engine_gates(c)
                self.assertEqual(result["outcome"], Outcome.GATE_FAILED)
                self.assertEqual(result["gate"], "G15")
                self.assertTrue(result["repairable"])
                feedback = json.loads(result["feedback"])
                self.assertIn("G15", feedback["problems"][0])
                self.assertIn('"wrong": 1', feedback["problems"][0])
                self.assertEqual(calls, [c.work])
                model.assert_not_called()
                (c.case / "base/judge.py").write_text("repaired judge")
                result = run.engine_gates(c)
            self.assertEqual(result["outcome"], Outcome.OK)
            self.assertEqual(result["passed"], ("G15",))
            self.assertEqual(calls, [c.work, c.work])
            self.assertIsNone(c.card["failed_gate"])
            self.assertNotIn("failed_detail", c.card)

    def test_recertify_keeps_october_verdicts_and_reruns_only_its_gates(self):
        from durable.contract import Outcome
        with tempfile.TemporaryDirectory() as tmp:
            c = self.context(pathlib.Path(tmp)); c.stopped = False
            c.card.update(gates={"G1": "pass", "G2": "pass"}, kept_gate_source={"stale": True},
                          recertify={"case": "case-old", "routes": {},
                                     "gate_results": {"G5": {"reference": "solved"}}})
            ran = []
            def gates(ctx, fail=None):
                ran.append((list(ctx.audit_gates), dict(ctx.card["gates"])))
                for gate in ctx.audit_gates:
                    ctx.card["gates"][gate] = "fail" if gate == fail else "pass"
                    if gate == fail:
                        ctx.card["failed_gate"], ctx.card["failed_detail"] = gate, {"labels": {"wrong_fix": 1}}
                        break
            with patch.object(run, "run_gates", gates), \
                 patch.object(run, "g1", return_value=(True, {"problems": []})), \
                 patch.object(run, "ensure_freshness") as freshness:
                result = run.engine_gates(c)
                freshness.assert_called_once()
            self.assertEqual(ran[0][0], ["G2", "G3", "G16", "G10", "G17", "G11"])
            self.assertEqual(set(ran[0][1]), {"G1", "G4", "G5", "G6", "G7", "G8", "G9", "G13", "G14", "G15"})
            self.assertEqual(c.card["gate_results"], {"G5": {"reference": "solved"}})
            self.assertEqual(c.card["kept_gate_source"]["case"], "case-old")
            self.assertEqual(result["outcome"], Outcome.OK)
            self.assertEqual(set(result["passed"]), set(run.GATES))
            with patch.object(run, "run_gates", lambda ctx: gates(ctx, "G17")), \
                 patch.object(run, "g1", return_value=(True, {"problems": []})), \
                 patch.object(run, "ensure_freshness"), patch.object(run, "writer_feedback", return_value=["G17"]):
                result = run.engine_gates(c)
            # The engine retires a recertified case on any repair; this only reports it.
            self.assertEqual((result["outcome"], result["gate"], result["repairable"]), (Outcome.GATE_FAILED, "G17", True))
            # Freshness is judged today: an October G2 pass never outlives a current public match.
            with patch.object(run, "run_gates", lambda ctx: gates(ctx, "G2")), \
                 patch.object(run, "g1", return_value=(True, {"problems": []})), \
                 patch.object(run, "ensure_freshness", return_value=(False, {"outcome": "public_match"})):
                result = run.engine_gates(c)
            self.assertEqual((result["outcome"], result["gate"]), (Outcome.GATE_FAILED, "G2"))
            self.assertEqual(c.card["gates"]["G2"], "fail")

    def test_receipt_requires_unchanged_inputs_and_retained_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            c = self.context(root)
            evidence = root / "results/run.json"
            evidence.parent.mkdir()
            evidence.write_text('{"pass": true}')
            signature = gate_state.fingerprint(c, "G4", root)
            gate_state.save(c, "G4", {"pass": True}, signature, {}, root)
            (c.case / "BUILD-NOTES.md").write_text("typo corrected")
            self.assertEqual(gate_state.load(c, "G4", root), {"pass": True})
            dest = c.work / "bench-results/run.json"
            dest.parent.mkdir()
            evidence.replace(dest)
            self.assertIsNotNone(gate_state.load(c, "G4", root))
            (c.case / "base/judge.py").write_text("changed judge")
            self.assertIsNone(gate_state.load(c, "G4", root))
            (c.case / "base/judge.py").write_text("synthetic judge")
            dest.unlink()
            self.assertIsNone(gate_state.load(c, "G4", root))
            self.assertIsNone(gate_state.load(c, "G7", root))

    def test_registry_order_and_stale_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cipher = root / "statement.age"
            cipher.write_bytes(b"age-encryption.org/v1\nsynthetic encrypted test data")
            registry = Registry(root / "registry")
            registry.import_historical("case-old", cipher)
            a = registry.reserve("case-a", "a" * 64, cipher, expected_revision=1)
            with self.assertRaisesRegex(ValueError, "registry changed"):
                registry.reserve("case-b", "b" * 64, cipher, expected_revision=1)
            b = registry.reserve("case-b", "b" * 64, cipher, expected_revision=2)
            self.assertNotIn("case-b", a["statements"])
            self.assertIn("case-a", b["statements"])
            self.assertIn("case-old", a["statements"])
            registry.export("case-b", root / "snapshot")
            snapshot = json.loads((root / "snapshot/admission.json").read_text())
            self.assertEqual(snapshot["reservation"], b["reservation"])
            with self.assertRaisesRegex(ValueError, "stale reservation"):
                registry.transition("case-a", "wrong-token", "released")
            registry.transition("case-a", a["reservation"], "released")


if __name__ == "__main__":
    unittest.main()
