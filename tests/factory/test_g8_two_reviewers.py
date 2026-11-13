"""G8/G9 run two independent reviewers of distinct families; both must approve (founder 2026-11-12)."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse
import hashlib
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

import gate_state
import model_runtime
import run
from model_router import family

TABLES = ("rotation-3writers.json", "rotation.json")
ROLES = ("builder", "attacker", "reviewer1", "reviewer2", "strong_calibrator", "easy_calibrator")


def args(**more):
    base = dict(rotation_slot=1, rotation_table="rotation-3writers.json", builder=None, attacker=None, reviewer1=None,
                reviewer2=None, strong_calibrator=None, easy_calibrator="opencode/glm-5.3-flash-free",
                **{k + "_effort": None for k in ROLES})
    return argparse.Namespace(**{**base, **more})


class FamilyRuleTests(unittest.TestCase):
    def test_every_slot_has_a_second_reviewer_of_a_fifth_family(self):
        for name in TABLES:
            for slot in range(1, 9):
                try:
                    roles = model_runtime.rotation(slot, name)
                except ValueError:
                    continue  # refused writer family, not a runnable slot
                fams = {role: family(row["model"]) for role, row in roles.items()}
                second = family(model_runtime.second_reviewer(set(fams.values()), name)["model"])
                with self.subTest(table=name, slot=slot):
                    self.assertNotIn(second, fams.values())

    def test_select_models_pins_two_reviewers(self):
        c = types.SimpleNamespace(args=args(), card={}, engine=object())
        models = model_runtime.select_models(c, log=lambda *a: None)
        self.assertEqual(len(models["reviewers"]), 2)
        self.assertNotEqual(family(models["reviewers"][0][0]), family(models["reviewers"][1][0]))
        self.assertIn("reviewer2", c.card["roles"])

    def test_second_reviewer_may_not_share_a_family_with_any_other_role(self):
        for role_model in ("claude/claude-opus-5-5", "codex/gpt-6.1-sol", "opencode/minimax-m3.1-flash-free",
                           "opencode/deepseek-v4.1-flash-free"):
            c = types.SimpleNamespace(args=args(reviewer2=role_model), card={}, engine=object())
            with self.subTest(reviewer2=role_model), self.assertRaises(ValueError):
                model_runtime.select_models(c, log=lambda *a: None)

    def test_an_explicit_reviewer_in_the_preferred_family_moves_the_default_to_the_next(self):
        c = types.SimpleNamespace(args=args(reviewer1="openrouter/xiaomi/mimo-v2.6-pro"), card={}, engine=object())
        models = model_runtime.select_models(c, log=lambda *a: None)
        self.assertEqual(family(models["reviewers"][1][0]), "z-ai")

    def test_in_flight_single_reviewer_case_adopts_the_second(self):
        c = types.SimpleNamespace(args=args(), card={}, engine=object())
        two = model_runtime.select_models(c, log=lambda *a: None)
        one = {**two, "reviewers": two["reviewers"][:1]}
        c.card = {"models": one, "roles": {k: v for k, v in c.card["roles"].items() if k != "reviewer2"}}
        self.assertTrue(model_runtime.with_second_reviewer(c, "rotation-3writers.json"))
        self.assertEqual(c.card["models"]["reviewers"], two["reviewers"])
        self.assertEqual(c.card["roles"]["reviewer2"]["family"], family(two["reviewers"][1][0]))
        self.assertFalse(model_runtime.with_second_reviewer(c, "rotation-3writers.json"))

    def test_in_flight_adoption_keeps_imported_idea_families_out(self):
        base = types.SimpleNamespace(args=args(), card={}, engine=object())
        two = model_runtime.select_models(base, log=lambda *a: None)
        default = family(two["reviewers"][1][0])
        c = types.SimpleNamespace(card={"models": {**two, "reviewers": two["reviewers"][:1]}, "roles": {},
                                        "imported_from": {"idea_families": [default]}})
        model_runtime.with_second_reviewer(c, "rotation-3writers.json")
        self.assertNotEqual(family(c.card["models"]["reviewers"][1][0]), default)


class PanelTests(unittest.TestCase):
    def test_one_reviewer_is_not_a_panel(self):
        c = types.SimpleNamespace(models={"reviewers": [["a/x"]]}, card={}, work=pathlib.Path("."))
        with self.assertRaisesRegex(ValueError, "two independent reviewers"):
            run.review(c)

    def test_both_must_approve_and_each_gets_the_key_cross_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "case").mkdir()
            seen = []
            verdicts = iter([True, False])

            def fake_opencode(c, chain, text, d, name, **kw):
                seen.append((chain, text))
                ok = next(verdicts)
                (d / "verdict.json").write_text(json.dumps({"fairness": {"approve": ok, "findings": []},
                                                            "realism": {"approve": True, "findings": []}}))
                return 0
            c = types.SimpleNamespace(models={"reviewers": [["opencode/a"], ["opencode-go/b"]]}, card={}, work=root,
                                      case=root / "case", args=types.SimpleNamespace(source=None, runs=1, scenario_runs=1))
            with patch.object(run, "opencode", fake_opencode), patch.object(run, "under_engine", lambda c: False):
                ok, info = run.g8(c)
            self.assertFalse(ok)
            self.assertEqual(info["approve"], "1/2")
            self.assertEqual([chain for chain, _ in seen], [["opencode/a"], ["opencode-go/b"]])
            for _, text in seen:
                self.assertIn("correct_responses", text)
                self.assertIn("bin/claims.py", text)

    def test_engine_path_calls_both_reviewers_and_g9_needs_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "case").mkdir()
            idents, verdicts = [], iter([True, False])

            def fake_answer(c, chain, text, d, name, out, identity, kind, schema, validate, **kw):
                idents.append(identity)
                ok = next(verdicts)
                return {"fairness": {"approve": True, "findings": []}, "realism": {"approve": ok, "findings": []}}
            c = types.SimpleNamespace(models={"reviewers": [["opencode/a"], ["opencode-go/b"]]}, card={}, work=root,
                                      case=root / "case", args=types.SimpleNamespace(source=None, runs=1, scenario_runs=1))
            with patch.object(run, "retained_answer", fake_answer), patch.object(run, "under_engine", lambda c: True):
                ok, info = run.g9(c)
            self.assertFalse(ok)
            self.assertEqual(info["approve"], "1/2")
            self.assertEqual([i["index"] for i in idents], [1, 2])
            self.assertTrue(all("bin/claims.py" in i["keys"] for i in idents))


class ContextHookTests(unittest.TestCase):
    def adopted(self, **card_more):
        from test_durable_worker_step import practice_card, practice_tree, PLUMBING, BENCH_V, BATCH, CASE
        from durable.contract import ArtifactKind, Ref, Step, StepInput, StepKind
        with tempfile.TemporaryDirectory() as tmp, patch.object(run, "BENCH", _TEST_ROOT):
            work = practice_tree(pathlib.Path(tmp), CASE, card=practice_card(CASE, **card_more))
            si = StepInput(BATCH, CASE, 1, Step(StepKind.WRITER, 1), 1, PLUMBING, BENCH_V, Ref("1" * 64, ArtifactKind.INPUTS),
                           Ref("2" * 64, ArtifactKind.CASE_SNAPSHOT), 600.0, 5_000_000)
            c = run.context_for_step(si, work)
            self.card = c.card
            return c.models["reviewers"]

    def test_next_step_of_a_single_reviewer_case_pins_a_second_reviewer(self):
        reviewers = self.adopted()
        self.assertEqual(len(reviewers), 2)
        self.assertNotEqual(family(reviewers[0][0]), family(reviewers[1][0]))

    def test_an_idea_covering_every_second_family_stops_gates_for_the_founder(self):
        from durable.contract import Outcome
        reviewers = self.adopted(imported_from={"idea_families": ["xiaomi", "z-ai"]})   # the step still starts
        self.assertEqual(len(reviewers), 1)
        c = types.SimpleNamespace(models={"reviewers": reviewers}, card=self.card)
        out = run.engine_gates(c)
        self.assertEqual((out["outcome"], out["reason"], out["gate"]), (Outcome.NEEDS_FOUNDER, "g8:no_eligible_reviewer", "G8"))

    def test_a_recovered_case_drops_the_old_reviewer_failure(self):
        reviewers = self.adopted(reviewer2_unavailable="no family was free")   # a family is free now
        self.assertEqual(len(reviewers), 2)
        self.assertNotIn("reviewer2_unavailable", self.card)


class CacheIdentityTests(unittest.TestCase):
    def identity(self, gate, reviewers, root):
        c = types.SimpleNamespace(work=root / "work", seed=7, manifest0="m", case=root / "work/case",
            args=types.SimpleNamespace(runs=10, scenario_runs=3, dry_run=False, resume=True, max_repairs=2, bench_workers=1),
            card={"gates": {}, "roles": {"reviewer": {"model": "a/x"}, "reviewer2": {"model": "b/y"} if len(reviewers) > 1 else None}},
            models={"reviewers": reviewers})
        (c.case / "base").mkdir(parents=True, exist_ok=True)
        (c.case / "base/judge.py").write_text("judge")
        return gate_state.inputs(c, gate, root)

    def test_single_reviewer_g8_pass_is_not_a_two_reviewer_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for gate in ("G8", "G9"):
                one = self.identity(gate, [["a/x"]], root)
                two = self.identity(gate, [["a/x"], ["b/y"]], root)
                self.assertNotEqual(one, two, gate)
            # And load() refuses a record saved under one reviewer when two are now pinned.
            c = types.SimpleNamespace(work=root / "work", seed=7, manifest0="m", case=root / "work/case",
                args=types.SimpleNamespace(runs=10, scenario_runs=3, dry_run=False, resume=True, max_repairs=2, bench_workers=1),
                card={"gates": {}, "roles": {"reviewer": {"model": "a/x"}}}, models={"reviewers": [["a/x"]]})
            (c.work / "gate-cache").mkdir(parents=True, exist_ok=True)
            (c.work / "review-1").mkdir()
            (c.work / "review-1/verdict.json").write_text("{}")
            signature = hashlib.sha256(json.dumps(gate_state.inputs(c, "G8", root), sort_keys=True).encode()).hexdigest()
            gate_state.save(c, "G8", {"approve": "1/1"}, signature, {}, root)
            self.assertEqual(gate_state.load(c, "G8", root), {"approve": "1/1"})
            c.models = {"reviewers": [["a/x"], ["b/y"]]}
            self.assertIsNone(gate_state.load(c, "G8", root))
            # Gates that never use the second reviewer keep their identity, so they are not rerun.
            for gate in ("G10", "G11"):
                self.assertEqual(self.identity(gate, [["a/x"]], root)["models"]["reviewers"],
                                 self.identity(gate, [["a/x"], ["b/y"]], root)["models"]["reviewers"])


if __name__ == "__main__":
    unittest.main()
