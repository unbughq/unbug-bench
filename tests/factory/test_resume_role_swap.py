"""Founder 2026-11-12: `start --resume-case <case> --roles stress_tester=<model>[,strong_calibrator=<model>]`
gives a held case another stress tester or strong calibrator. The CLI and contract check the shape;
the worker (run.context_for_step) rewrites the case card's models and refuses a swapped selection that
breaks select_models' rules, has no bounded route, or changes the strong calibrator after G10 ran.
The engine side (the resume record carries and inherits the swap) is test_durable_engine.ResumeRoleSwap."""
import sys
from pathlib import Path as _TestPath

_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_ROOT / "bin"), str(_TestPath(__file__).resolve().parent)]

import copy
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("BENCH", str(_ROOT))

import run
from durable.cli import main, parse_roles
from durable.contract import (ArtifactKind, ContractError, Ref, Step, StepInput, StepKind, step_input_from_record,
                              to_record)
from durable.runtime import RuntimeErrorCode
from test_durable_worker_step import BATCH, BENCH_V, CASE, PLUMBING, WorkerHome, practice_card, practice_tree

FLASH = "opencode-go/deepseek-v4.1-flash"
CLAUDE = "claude/claude-opus-5-5"     # stands in for claude/claude-mythos-5-2, not on main
SOL = "codex/gpt-6.1-sol"             # the rotation's Codex strong calibrator
MINIMAX = "opencode/minimax-m3.1-flash-free"
# 22e434's rotation.json slot 8: writer deepseek, stress tester openai, strong calibrator anthropic, reviewer minimax.
SLOT8 = {"writer": "opencode/deepseek-v4.1-flash-free", "stress_tester": SOL, "strong_calibrator": CLAUDE,
         "reviewer": "opencode/minimax-m3.1-flash-free", "easy_calibrator": "openrouter/xiaomi/mimo-v2.6-pro"}


def slot8_card(**more):
    roles = {r: {"model": m, "effort": run.model_effort(m), "family": run.family(m)} for r, m in SLOT8.items()}
    models = {"builder": [SLOT8["writer"]], "attacker": [SLOT8["stress_tester"]], "reviewers": [[SLOT8["reviewer"]]],
              "strong_calibrator": [SLOT8["strong_calibrator"]], "easy_calibrator": [SLOT8["easy_calibrator"]]}
    return copy.deepcopy(practice_card(CASE, models=models, roles=roles, **more))


def step_input(roles=None, kind=StepKind.STRESS):
    step = Step(kind, 1) if kind in (StepKind.WRITER, StepKind.STRESS, StepKind.GATES) else Step(kind)
    return StepInput(BATCH, CASE, 3, step, 1, PLUMBING, BENCH_V, Ref("1" * 64, ArtifactKind.INPUTS),
                     Ref("2" * 64, ArtifactKind.CASE_SNAPSHOT), 600.0, 5_000_000, roles=roles)


class Cli(unittest.TestCase):
    def test_parses_one_or_both_swappable_roles(self):
        self.assertEqual(parse_roles("stress_tester=" + FLASH), {"stress_tester": FLASH})
        self.assertEqual(parse_roles(f"stress_tester={CLAUDE},strong_calibrator={SOL}"),
                         {"stress_tester": CLAUDE, "strong_calibrator": SOL})

    def test_rejects_other_roles_and_malformed_lists(self):
        for bad in ("writer=" + FLASH, "reviewer=" + FLASH, "stress_tester", "stress_tester=", "stress_tester=flash",
                    f"stress_tester={FLASH},stress_tester={CLAUDE}", f"stress_tester={FLASH},", ""):
            with self.assertRaisesRegex(RuntimeErrorCode, "roles_invalid", msg=bad):
                parse_roles(bad)

    def test_roles_need_a_resumed_case_and_never_reach_the_controller_when_bad(self):
        for argv, code in ((["--roles", "stress_tester=" + FLASH], "roles_need_resume_case"),
                           (["--resume-case", "case-import-22e434-5-1", "--roles", "writer=" + FLASH], "roles_invalid")):
            with patch("durable.cli.load_config", return_value={"state_dir": "/nonexistent"}), \
                    patch("sys.stderr", new_callable=io.StringIO) as err, patch("socket.socket") as sock:
                self.assertEqual(main(["--config", "x", "start", "spec.json", "registry.json", *argv]), 1)
                sock.assert_not_called()
            self.assertEqual(err.getvalue(), code + "\n")


class Contract(unittest.TestCase):
    def test_a_step_input_without_roles_records_no_roles_field(self):
        si = step_input()
        record = to_record(si)
        self.assertNotIn("roles", record)   # what older workers and recorded inputs hold
        self.assertEqual(step_input_from_record(json.loads(json.dumps(record))), si)

    def test_a_step_input_with_roles_round_trips(self):
        si = step_input({"stress_tester": CLAUDE, "strong_calibrator": SOL})
        self.assertEqual(step_input_from_record(json.loads(json.dumps(to_record(si)))), si)

    def test_bad_roles_are_refused(self):
        for bad in ({}, {"writer": FLASH}, {"stress_tester": 7}, {"stress_tester": "flash"}, [("stress_tester", FLASH)]):
            with self.assertRaises(ContractError, msg=repr(bad)):
                step_input(bad)
        record = to_record(step_input())
        with self.assertRaises(ContractError):   # absent, never null
            step_input_from_record({**record, "roles": None})


class Worker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def context(self, roles, card=None, kind=StepKind.STRESS):
        work = practice_tree(tempfile.mkdtemp(dir=self.tmp.name), CASE, card=card or slot8_card())
        return run.context_for_step(step_input(roles, kind), work)

    def practice(self, **more):
        """writer anthropic, stress minimax, strong openai, reviewer xiaomi."""
        card = copy.deepcopy(practice_card(CASE, **more))
        card["roles"]["stress_tester"]["model"] = card["models"]["attacker"][0] = MINIMAX
        return card

    def test_two_roles_swap_together_and_the_family_rules_see_the_whole_set(self):
        # 22e434: DeepSeek wrote it, so the attacker moves to Anthropic; that only holds once the strong
        # calibrator has left Anthropic too.
        c = self.context({"stress_tester": CLAUDE, "strong_calibrator": SOL})
        self.assertEqual((c.models["attacker"], c.models["strong_calibrator"]), ([CLAUDE], [SOL]))
        self.assertIs(c.card["models"], c.models)
        self.assertEqual(c.card["roles"]["stress_tester"], {"model": CLAUDE, "effort": "high", "family": "anthropic"})
        self.assertEqual(c.card["roles"]["strong_calibrator"], {"model": SOL, "effort": "high", "family": "openai"})
        self.assertIn("resume swap", (c.work / "logs/runner.log").read_text())
        for alone in ({"stress_tester": CLAUDE}, {"strong_calibrator": SOL}):
            with self.assertRaisesRegex(ValueError, "four different families", msg=repr(alone)):
                self.context(alone)

    def test_the_card_keeps_every_replaced_model(self):
        c = self.context({"stress_tester": CLAUDE, "strong_calibrator": SOL})
        self.assertEqual([{k: v for k, v in s.items() if k != "at"} for s in c.card["role_swaps"]], [
            {"role": "stress_tester", "from": SOL, "to": CLAUDE, "step": "stress:1", "seq": 3},
            {"role": "strong_calibrator", "from": CLAUDE, "to": SOL, "step": "stress:1", "seq": 3}])
        # A later swap of the lineage adds to the history.
        later = self.context({"stress_tester": "openrouter/xiaomi/mimo-v2.6-pro"}, c.card)
        self.assertEqual([(s["from"], s["to"]) for s in later.card["role_swaps"]],
                         [(SOL, CLAUDE), (CLAUDE, SOL), (CLAUDE, "openrouter/xiaomi/mimo-v2.6-pro"),
                          ("opencode-go/mimo-v2.6-pro", later.card["roles"]["reviewer2"]["model"])])
        # The attacker moved into the second reviewer's family, so the rotation re-picked a fifth family.
        fams = {r: later.card["roles"][r]["family"] for r in ("writer", "stress_tester", "reviewer", "strong_calibrator", "reviewer2")}
        self.assertEqual(len(set(fams.values())), 5, fams)
        self.assertEqual(later.models["reviewers"][1], [later.card["roles"]["reviewer2"]["model"]])

    def test_a_former_stress_tester_family_never_becomes_reviewer2(self):
        # Slot 8 adopts Xiaomi as reviewer2. The stress tester moves to z-ai, then to Xiaomi: the
        # re-pick may not land on z-ai, whose findings the case was repaired against, so it is refused.
        glm, mimo = "opencode-go/glm-5.3-flash", "openrouter/xiaomi/mimo-v2.6-pro"
        c = self.context({"stress_tester": glm})
        self.assertEqual(c.card["roles"]["reviewer2"]["family"], "xiaomi")
        with self.assertRaisesRegex(run.RoleSwapRefused, "No second reviewer family"):
            self.context({"stress_tester": mimo}, c.card)
        # Initial adoption skips a former role holder's family the same way.
        card = slot8_card(role_swaps=[{"role": "stress_tester", "from": "opencode-go/mimo-v2.6-pro", "to": SOL,
                                       "step": "stress:1", "seq": 2}])
        self.assertEqual(self.context(None, card).card["roles"]["reviewer2"]["family"], "z-ai")

    def test_a_deepseek_flash_attacker_is_refused_where_deepseek_wrote_the_case(self):
        with self.assertRaisesRegex(ValueError, "four different families"):
            self.context({"stress_tester": FLASH})
        c = self.context({"stress_tester": FLASH}, self.practice())   # Anthropic wrote this one
        self.assertEqual(c.models["attacker"], [FLASH])
        self.assertEqual(c.card["roles"]["stress_tester"]["family"], "deepseek")

    def test_explicit_models_are_not_held_to_the_rotation_refused_list(self):
        # rotation-3writers.json refuses openai as writer/stress_tester for its own rows only (as on main):
        # an explicit attacker flag, and a swap like it, may name Codex where the families allow it.
        import model_runtime
        c = run.Ctx()
        c.args, c.card = run.argument_parser().parse_args(["--source", "port", "--attacker", SOL]), {}
        c.args.rotation_slot, c.args.reviewer1 = 7, "openrouter/xiaomi/mimo-v2.6-pro"
        self.assertEqual(model_runtime.select_models(c, log=lambda *_: None)["attacker"], [SOL])
        model_runtime.check_role_families({r: {"model": m} for r, m in SLOT8.items()})   # 22e434's own selection
        card = copy.deepcopy(practice_card(CASE))
        card["roles"]["writer"]["model"] = card["models"]["builder"][0] = "opencode/deepseek-v4.1-flash-free"
        card["roles"]["stress_tester"]["model"] = card["models"]["attacker"][0] = MINIMAX
        card["roles"]["strong_calibrator"]["model"] = card["models"]["strong_calibrator"][0] = CLAUDE
        self.assertEqual(self.context({"stress_tester": SOL}, card).models["attacker"], [SOL])
        # Family separation still applies to an explicit flag.
        c.args.attacker = CLAUDE
        with self.assertRaisesRegex(ValueError, "four different families"):
            model_runtime.select_models(c, log=lambda *_: None)

    def test_a_swapped_model_needs_a_bounded_route_on_the_case_router_accounts(self):
        # FLASH has a bounded route on the default accounts (above), none on a case with no account.
        c = run.Ctx()
        c.router_accounts = ()
        work = practice_tree(tempfile.mkdtemp(dir=self.tmp.name), CASE, card=self.practice())
        with patch.object(run, "Ctx", lambda: c), self.assertRaisesRegex(run.RoleSwapRefused, "no bounded route"):
            run.context_for_step(step_input({"stress_tester": FLASH}), work)

    def test_no_role_changes_on_a_seal_step(self):
        # The sealed card must name the stress tester whose G2 and stress rounds it holds.
        with self.assertRaisesRegex(run.RoleSwapRefused, "no role changes at SEAL"):
            self.context({"stress_tester": FLASH}, self.practice(), kind=StepKind.SEAL)
        # Before SEAL a swapped stress tester is fine: its G2 identity names it, so GATES reruns G2.
        self.assertEqual(self.context({"stress_tester": FLASH}, self.practice(), kind=StepKind.GATES).models["attacker"],
                         [FLASH])
        # An unchanged role at SEAL is no swap.
        self.assertEqual(self.context({"stress_tester": SOL}, kind=StepKind.SEAL).models["attacker"], [SOL])

    def test_a_refused_swap_holds_the_case_on_its_first_attempt(self):
        # Every refusal is a RoleSwapRefused, the same on each attempt: the worker reports
        # infra:roles_refused and the policy holds the case without a retry or a diagnosis.
        from durable.contract import BatchSpec, Outcome, StepResult
        from durable.policy import Action, Counters, decide
        for roles, card in (({"stress_tester": CLAUDE}, None), ({"strong_calibrator": "openrouter/z-ai/glm-5.3-flash"},
                            self.practice()), ({"stress_tester": "openrouter/unknown/model-x"}, self.practice())):
            with self.assertRaises(run.RoleSwapRefused, msg=repr(roles)):
                self.context(roles, card)
        spec = BatchSpec.__new__(BatchSpec)
        object.__setattr__(spec, "max_infra_retries_per_step", 3)
        for step in (Step(StepKind.ADMIT), Step(StepKind.WRITER, 1), Step(StepKind.STRESS, 1),
                     Step(StepKind.GATES, 1), Step(StepKind.SEAL)):
            result = StepResult(Outcome.INFRA_ERROR, "infra:roles_refused")
            self.assertIs(decide(step, result, Counters(step_infra_errors=1), spec), Action.HOLD, step)

    def test_the_worker_reports_a_refused_swap_as_roles_refused(self):
        import dataclasses
        from durable.contract import Outcome
        from durable.worker_step import Worker
        h = WorkerHome(self)   # writer anthropic: an anthropic stress tester breaks the family rule
        si = dataclasses.replace(h.step(StepKind.STRESS, 1, snapshot=h.push_practice()), roles={"stress_tester": CLAUDE})
        result, _ = Worker(h.home, sealer=h.sealer, runner=run).execute(si, h.keys(si))
        self.assertEqual((result.outcome, result.reason), (Outcome.INFRA_ERROR, "infra:roles_refused"))

    def test_the_strong_calibrator_stays_on_a_subscription_and_swapped_models_need_a_bounded_route(self):
        with self.assertRaisesRegex(ValueError, "Claude or Codex subscription"):
            self.context({"strong_calibrator": "openrouter/z-ai/glm-5.3-flash"}, self.practice())
        with self.assertRaisesRegex(ValueError, "openrouter/unknown/model-x has no bounded route"):
            self.context({"stress_tester": "openrouter/unknown/model-x"}, self.practice())
        # Only the swapped roles are judged: an unswapped role's route is not this swap's business.
        card = self.practice()
        card["roles"]["reviewer"]["model"] = card["models"]["reviewers"][0][0] = "openrouter/unknown/model-x"
        self.assertEqual(self.context({"stress_tester": FLASH}, card).models["attacker"], [FLASH])

    def test_the_strong_calibrator_changes_only_before_the_first_gates_step(self):
        swap = {"stress_tester": CLAUDE, "strong_calibrator": SOL}
        for gates in ({"G10": "pass"}, {"G1": "pass"}):   # G10, or a GATES step that stopped before it
            with self.assertRaisesRegex(ValueError, "only before the case's first GATES step", msg=gates):
                self.context(swap, slot8_card(gates=gates))
        with self.assertRaisesRegex(ValueError, "only before the case's first GATES step"):
            self.context(swap, kind=StepKind.GATES)   # a GATES step empties card["gates"] as it starts
        # The stress tester alone may still change after G10.
        self.assertEqual(self.context({"stress_tester": FLASH}, self.practice(gates={"G10": "pass"})).models["attacker"],
                         [FLASH])

    def test_diagnosis_never_applies_a_swap(self):
        # Diagnosis runs on the case's own models.
        c = self.context({"stress_tester": FLASH}, kind=StepKind.DIAGNOSIS)
        self.assertEqual((c.models["attacker"], "role_swaps" in c.card), ([SOL], False))

    def test_a_card_already_swapped_is_left_alone(self):
        # A later step of the swapped lineage restores the swapped card, even after a GATES step.
        swap = {"strong_calibrator": SOL, "stress_tester": CLAUDE}
        card = self.context(swap).card
        card["gates"] = {"G10": "pass"}
        c = self.context(swap, card, kind=StepKind.GATES)
        self.assertEqual((c.models["strong_calibrator"], len(c.card["role_swaps"])), ([SOL], 2))
        self.assertFalse((c.work / "logs/runner.log").exists())   # nothing swapped, nothing logged


class StartTime(unittest.TestCase):
    def test_parse_refuses_what_needs_no_case_card(self):
        for bad in ("stress_tester=openrouter/unknown/model-x", "strong_calibrator=" + FLASH,
                    "stress_tester=claude/claude-mythos-5-2"):   # unbounded on main until its prices land
            with self.assertRaisesRegex(RuntimeErrorCode, "roles_invalid", msg=bad):
                parse_roles(bad)

    def test_the_call_hold_check_counts_swapped_models(self):
        from durable.runtime import largest_call_hold
        cheap = json.dumps({"dry_run": False, "models": {"builder": [FLASH], "attacker": [MINIMAX]}}).encode()
        self.assertGreater(largest_call_hold(cheap, [CLAUDE]), largest_call_hold(cheap) or 0)


if __name__ == "__main__":
    unittest.main()
