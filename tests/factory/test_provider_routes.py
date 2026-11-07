"""Provider-only cutover: synthetic calls, no credentials or case access."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import pathlib
import tempfile
from types import SimpleNamespace
from unittest import TestCase, main, mock

import run
import model_runtime
import model_router
from budget import classify_provider_failure
from router_test_support import offline_router
_ROUTING = offline_router()


class ProviderRoutesTest(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = pathlib.Path(temporary.name)

    def preflight_context(self):
        return SimpleNamespace(case="synthetic-case", card={}, models={
            "builder": ["claude/claude-opus-5-5"],
            "attacker": ["opencode/deepseek-v4.1-flash-free"],
            "reviewers": [["openrouter/xiaomi/mimo-v2.6-pro"]],
            "strong_calibrator": ["codex/gpt-6.1-sol"],
            "easy_calibrator": ["opencode/deepseek-v4.1-flash-free"]})

    def test_preflight_checks_distinct_nonwriter_routes_without_gate_credit(self):
        self.addCleanup(offline_router()[0].close)
        c = self.preflight_context()
        with mock.patch.object(run, "opencode", return_value=0) as call:
            run.provider_preflight(c)
        self.assertEqual(call.call_count, 3)
        self.assertTrue(all(item.kwargs["timeout"] == 180 for item in call.call_args_list))
        self.assertNotIn(c.models["builder"], [item.args[1] for item in call.call_args_list])
        self.assertTrue(all(row["status"] == "completed" and row["scope"] == "availability_only"
                            for row in c.card["provider_preflight"]))
        self.assertNotIn("gates", c.card)

    def test_bad_preflight_route_stops_before_other_roles(self):
        self.addCleanup(offline_router()[0].close)
        for reason, stop in (("provider_limit:openrouter/deepseek/deepseek-v4.1-flash",
                              "provider_limit:openrouter/deepseek/deepseek-v4.1-flash"),
                             ("opencode_error", "provider_preflight_failed")):
            c = self.preflight_context()
            with mock.patch.object(run, "opencode", side_effect=run.BudgetError(reason)) as call:
                with self.assertRaisesRegex(run.BudgetError, "^" + stop + "$"):
                    run.provider_preflight(c)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(c.card["provider_preflight"][0]["status"], "failed")
            self.assertEqual(c.card["provider_preflight"][0]["reason"], reason)
            self.assertNotIn("gates", c.card)

    def test_every_configured_chain_enters_shared_routing(self):
        self.addCleanup(offline_router()[0].close)
        for chain in model_router.CHAINS:
            c = SimpleNamespace(work=self.work, card={})
            with mock.patch.object(model_runtime.ModelRuntime, "_invoke", return_value=0) as call:
                run.model_call(c, [chain[0]], "synthetic", ".", "fixture")
            self.assertEqual(call.call_args.args[1], [chain[0]])
            row = c.card['route_receipts'][-1]
            self.assertEqual((row['route'], row['family'], row['outcome']), (chain[0], model_runtime.family(chain[0]), 'done'))
            self.assertNotIn('routes', c.__dict__)

    def test_fallback_is_shared_and_billing_is_explicit(self):
        self.addCleanup(offline_router()[0].close)
        c = SimpleNamespace(work=self.work, card={})
        tried = []
        def invoke(runtime, context, models, *args, **kwargs):
            tried.append(models[0])
            if models[0].endswith('-free'):
                raise model_runtime.BudgetError('opencode_error', provider_failure=
                    classify_provider_failure('model removed', models[0], status_code=404))
            return 0
        runtime = model_runtime.ModelRuntime(None, None, None, None, None)
        with mock.patch.object(model_runtime.ModelRuntime, '_invoke', invoke):
            runtime.call(c, [model_router.CHAINS[-1][0]], 't', '.', 'fixture')
            self.assertEqual(tried, list(model_router.CHAINS[-1]))
            other = SimpleNamespace(card={})
            tried.clear()
            runtime.call(other, [model_router.CHAINS[-1][0]], 't', '.', 'fixture')
            self.assertEqual(tried, [model_router.CHAINS[-1][1]])
        self.assertEqual(c.card['route_receipts'][-1]['billing'], 'subscription')
        self.assertTrue(c.force_budget_resume)


if __name__ == "__main__": main()
