"""Founder 2026-11-12: `start --resume-case <case> --roles stress_tester=<model>[,strong_calibrator=<model>]`
gives a held case another stress tester or strong calibrator. The CLI and contract check the shape;
the worker (run.context_for_step) rewrites the case card's models and refuses a swapped selection that
breaks select_models' rules, has no bounded route, or changes the strong calibrator after G10 ran.
The engine side (the resume record carries and inherits the swap) is test_durable_engine.ResumeRoleSwap."""
import sys
from pathlib import Path as _TestPath

_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_ROOT / "bin"), str(_TestPath(__file__).resolve().parent)]

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
from test_durable_worker_step import BATCH, BENCH_V, CASE, PLUMBING, practice_card, practice_tree

FLASH = "opencode-go/deepseek-v4.1-flash"
CLAUDE = "claude/claude-opus-5-5"     # stands in for claude/claude-mythos-5-2, not on main
SOL = "codex/gpt-6.1-sol"             # the rotation's Codex strong calibrator
# 22e434's rotation.json slot 8: writer deepseek, stress tester openai, strong calibrator anthropic, reviewer minimax.
SLOT8 = {"writer": "opencode/deepseek-v4.1-flash-free", "stress_tester": SOL, "strong_calibrator": CLAUDE,
         "reviewer": "opencode/minimax-m3.1-flash-free", "easy_calibrator": "openrouter/xiaomi/mimo-v2.6-pro"}


def slot8_card(**more):
    roles = {r: {"model": m, "effort": run.model_effort(m), "family": run.family(m)} for r, m in SLOT8.items()}
    models = {"builder": [SLOT8["writer"]], "attacker": [SLOT8["stress_tester"]], "reviewers": [[SLOT8["reviewer"]]],
              "strong_calibrator": [SLOT8["strong_calibrator"]], "easy_calibrator": [SLOT8["easy_calibrator"]]}
    return practice_card(CASE, models=models, roles=roles, **more)


def step_input(roles=None, kind=StepKind.STRESS):
    return StepInput(BATCH, CASE, 3, Step(kind, 1), 1, PLUMBING, BENCH_V, Ref("1" * 64, ArtifactKind.INPUTS),
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

    def context(self, roles, card=None):
        work = practice_tree(tempfile.mkdtemp(dir=self.tmp.name), CASE, card=card or slot8_card())
        return run.context_for_step(step_input(roles), work)

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

    def test_a_deepseek_flash_attacker_is_refused_where_deepseek_wrote_the_case(self):
        with self.assertRaisesRegex(ValueError, "four different families"):
            self.context({"stress_tester": FLASH})
        # and swaps in where it did not (the practice card's writer is Anthropic).
        card = practice_card(CASE)
        card["roles"]["stress_tester"]["model"] = card["models"]["attacker"][0] = "opencode/minimax-m3.1-flash-free"
        c = self.context({"stress_tester": FLASH}, card)
        self.assertEqual(c.models["attacker"], [FLASH])
        self.assertEqual(c.card["roles"]["stress_tester"]["family"], "deepseek")

    def test_the_strong_calibrator_stays_on_a_subscription_and_every_model_needs_a_bounded_route(self):
        card = practice_card(CASE)   # writer anthropic, stress deepseek, strong openai, reviewer xiaomi
        with self.assertRaisesRegex(ValueError, "Claude or Codex subscription"):
            self.context({"strong_calibrator": "openrouter/z-ai/glm-5.3-flash"}, card)
        with self.assertRaisesRegex(ValueError, "openrouter/unknown/model-x has no bounded route"):
            self.context({"stress_tester": "openrouter/unknown/model-x"}, card)

    def test_the_strong_calibrator_never_changes_after_g10(self):
        card = slot8_card(gates={"G10": "pass"})
        with self.assertRaisesRegex(ValueError, "G10 already ran"):
            self.context({"stress_tester": CLAUDE, "strong_calibrator": SOL}, card)
        # The stress tester alone may still change after G10.
        card = practice_card(CASE, gates={"G10": "pass"})
        card["roles"]["stress_tester"]["model"] = card["models"]["attacker"][0] = "opencode/minimax-m3.1-flash-free"
        self.assertEqual(self.context({"stress_tester": FLASH}, card).models["attacker"], [FLASH])

    def test_a_card_already_swapped_is_left_alone(self):
        # A later step of the swapped lineage restores the swapped card: G10 ran on that calibrator.
        swap = {"strong_calibrator": SOL, "stress_tester": CLAUDE}
        card = self.context(swap).card
        card["gates"] = {"G10": "pass"}
        c = self.context(swap, card)
        self.assertEqual(c.models["strong_calibrator"], [SOL])
        self.assertFalse((c.work / "logs/runner.log").exists())   # nothing swapped, nothing logged


if __name__ == "__main__":
    unittest.main()
