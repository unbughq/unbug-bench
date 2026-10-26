"""Provider-only cutover: synthetic calls, no credentials or case access."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
from types import SimpleNamespace
from unittest import TestCase, main, mock

import run
import model_runtime


class ProviderRoutesTest(TestCase):
    def preflight_context(self):
        return SimpleNamespace(case="synthetic-case", card={}, models={
            "builder": ["claude/claude-opus-5-5"],
            "attacker": ["opencode/deepseek-v4.1-flash-free"],
            "reviewers": [["openrouter/xiaomi/mimo-v2.6-pro"]],
            "strong_calibrator": ["codex/gpt-6.1-sol"],
            "easy_calibrator": ["opencode/deepseek-v4.1-flash-free"]})

    def test_preflight_checks_distinct_nonwriter_routes_without_gate_credit(self):
        c = self.preflight_context()
        with mock.patch.object(run, "opencode", return_value=0) as call:
            run.provider_preflight(c)
        self.assertEqual(call.call_count, 3)
        self.assertTrue(all(item.kwargs["timeout"] == 60 for item in call.call_args_list))
        self.assertNotIn(c.models["builder"], [item.args[1] for item in call.call_args_list])
        self.assertTrue(all(row["status"] == "completed" and row["scope"] == "availability_only"
                            for row in c.card["provider_preflight"]))
        self.assertNotIn("gates", c.card)

    def test_bad_preflight_route_stops_before_other_roles(self):
        c = self.preflight_context()
        with mock.patch.object(run, "opencode", side_effect=run.BudgetError("provider_limit:opencode/deepseek-v4.1-flash-free")) as call:
            with self.assertRaisesRegex(run.BudgetError, "^provider_preflight_failed$"):
                run.provider_preflight(c)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(c.card["provider_preflight"][0]["status"], "failed")
        self.assertTrue(c.card["provider_preflight"][0]["reason"].startswith("provider_limit:"))
        self.assertNotIn("gates", c.card)

    def test_direct_routes_preserve_roles_and_do_not_spill_to_other_models(self):
        roles = {"stress_tester": {"model": "opencode-go/mimo-v2.6-pro", "family": "xiaomi"}}
        ledger = {"calls": 526, "cost": .995370312}
        c = SimpleNamespace(card={"roles": roles, "continuation_budget": ledger})
        paths = []
        try:
            with mock.patch.object(model_runtime.ModelRuntime, "_invoke", return_value=0) as call:
                for source, target in model_runtime.PROVIDER_ROUTES.items():
                    run.model_call(c, [source], "synthetic", ".", "attacker-fixture")
                    self.assertEqual(call.call_args.args[1], [target])
                    self.assertEqual(run.family(source), run.family(target))
                    p = model_runtime.opencode_config(target)
                    paths.append(p)
                    self.assertEqual(json.loads(p.read_text())["small_model"], target)
                self.assertEqual(len(set(paths)), 2)
                for source in ["opencode-go/muse-spark-1.3-contributor", "opencode/deepseek-v4.1-flash-free",
                               "opencode/glm-5.3-flash-free", "codex/gpt-6.1-sol", "claude/claude-opus-5-5"]:
                    run.opencode(c, [source], "synthetic", ".", "fixture")
                    self.assertEqual(call.call_args.args[1], [source])
            self.assertEqual(c.card["provider_routes"], model_runtime.PROVIDER_ROUTES)
            self.assertIs(c.card["roles"], roles)
            self.assertEqual(c.card["continuation_budget"], {"calls": 526, "cost": .995370312})
            self.assertFalse(any(v.startswith("openrouter/") for v in model_runtime.FREE_FALLBACK.values()))
            for source in [*model_runtime.PROVIDER_ROUTES, "opencode-go/muse-spark-1.3-contributor"]:
                with mock.patch.object(model_runtime.ModelRuntime, "_invoke", side_effect=run.BudgetError("provider_limit")) as call:
                    with self.assertRaises(run.BudgetError):
                        run.opencode(c, [source], "synthetic", ".", "fixture")
                    self.assertEqual(call.call_count, 1)  # no paid MiniMax or unrelated provider fallback
        finally:
            for p in paths:
                p.unlink(missing_ok=True)


    def test_free_route_fallback_is_recorded_and_reused_without_paid_spillover(self):
        c = SimpleNamespace(card={}, force_budget_resume=False)
        tried = []
        def invoke(runtime, context, models, *args, **kwargs):
            tried.append(models[0])
            if models[0].endswith("-free") or "paid" in models[0]:
                raise model_runtime.BudgetError("opencode_error")
            return 0
        runtime = model_runtime.ModelRuntime(None, None, None, None, None)
        with mock.patch.object(model_runtime.ModelRuntime, "_invoke", invoke):
            self.assertEqual(runtime.call(c, ["opencode/glm-5.3-flash-free"], "t", ".", "fixture"), 0)
            self.assertEqual(tried, ["opencode/glm-5.3-flash-free", "opencode-go/glm-5.3-flash"])
            self.assertTrue(c.card["free_model_fallback"])
            self.assertTrue(c.force_budget_resume)
            tried.clear()
            self.assertEqual(runtime.call(c, ["opencode/glm-5.3-flash-free"], "t", ".", "fixture"), 0)
            self.assertEqual(tried, ["opencode-go/glm-5.3-flash"])
            with self.assertRaises(model_runtime.BudgetError):
                runtime.call(c, ["opencode-go/paid-model"], "t", ".", "fixture")


if __name__ == "__main__":
    main()
    unittest.main()
