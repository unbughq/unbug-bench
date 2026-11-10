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
        # Stress tester and easy calibrator share DeepSeek free, but the calibrator never takes the
        # free lane, so its route is checked on its own (#41 review): attacker, reviewer, strong, easy.
        self.assertEqual(call.call_count, 4)
        self.assertTrue(all(item.kwargs["timeout"] == 180 for item in call.call_args_list))
        self.assertNotIn(c.models["builder"], [item.args[1] for item in call.call_args_list])
        self.assertTrue(all(row["status"] == "completed" and row["scope"] == "availability_only"
                            for row in c.card["provider_preflight"]))
        self.assertNotIn("gates", c.card)

    def test_bad_preflight_route_stops_before_other_roles(self):
        self.addCleanup(offline_router()[0].close)
        for reason, stop in (("provider_limit:openrouter/deepseek/deepseek-v4.1-flash",
                              "provider_limit:openrouter/deepseek/deepseek-v4.1-flash"),
                             ("opencode_error", "provider_preflight_failed:stress_tester:opencode_error")):
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

    def test_a_go_account_quota_blocks_that_account_instead_of_one_lane(self):
        # 8 November, 1108a: every MiniMax call retried both exhausted Go accounts (~6 s a call),
        # and router health never recorded either account.
        stack, store = offline_router()
        self.addCleanup(stack.close)
        free, go = 'opencode/minimax-m3.1-flash-free', 'opencode-go/minimax-m3.1-flash'
        tried = []
        def invoke(runtime, context, models, *args, **kwargs):
            tried.append((models[0], context.model_lease.account))
            if context.model_lease.account in ('opencode-go-key', 'opencode-go-key-2'):   # an unstructured usage-limit line
                raise model_runtime.BudgetError('provider_limit:' + models[0])
            return 0
        runtime = model_runtime.ModelRuntime(None, None, None, None, None)
        with mock.patch.object(model_runtime.ModelRuntime, '_invoke', invoke):
            runtime.call(SimpleNamespace(card={}), [free], 't', '.', 'fixture')
            # The chain starts at the Go plan route; the account's quota then also closes its free lane.
            self.assertEqual(tried[:2], [(go, 'opencode-go-key'), (go, 'opencode-go-key-2')])
            fallback = tried[2]   # the chain's OpenRouter route (synthetic maxima bound every route here)
            self.assertEqual((len(tried), fallback[1]), (3, 'openrouter-key'))
            health = store.rpc('status', {})['health']
            self.assertEqual({health[k]['reason'] for k in health if 'opencode-go-key' in k}, {'quota'})
            self.assertTrue(all(any(a in k for k in health) for a in ('opencode-go-key', 'opencode-go-key-2')))
            # The next call goes straight to the fallback: no exhausted account is retried.
            tried.clear()
            runtime.call(SimpleNamespace(card={}), [free], 't', '.', 'fixture')
            self.assertEqual(tried, [fallback])
        # Another route's per-call quota keeps its old, lane-only handling.
        self.assertEqual(model_runtime.call_failure_reason('provider_limit:x', 'openrouter/minimax/minimax-m3.1-flash'), 'quota')

    def test_a_failing_free_account_lane_is_blocked_for_that_route_only(self):
        # 9 November: free MiniMax calls kept retrying both accounts; their refusals did not read as quota.
        stack, store = offline_router()
        self.addCleanup(stack.close)
        free = 'opencode/minimax-m3.1-flash-free'
        tried = []
        def invoke(runtime, context, models, *args, **kwargs):
            tried.append((models[0], context.model_lease.account))
            if models[0] == free:
                raise model_runtime.BudgetError('opencode_error')   # no provider failure: per-call outage
            return 0
        runtime = model_runtime.ModelRuntime(None, None, None, None, None)
        with mock.patch.object(model_runtime.ModelRuntime, '_invoke', invoke):
            runtime.call(SimpleNamespace(card={}), [free], 't', '.', 'fixture')
            self.assertEqual(tried[:2], [(free, 'opencode-go-key'), (free, 'opencode-go-key-2')])
            fallback = tried[2]
            blocked = {k: v['reason'] for k, v in store.rpc('status', {})['health'].items() if v.get('blocked_until')}
            # Route-scoped: the accounts' Go lanes (MiMo, Muse, GLM Go) stay open.
            self.assertEqual(blocked, {'opencode-go-key/' + free: 'outage', 'opencode-go-key-2/' + free: 'outage'})
            tried.clear()
            runtime.call(SimpleNamespace(card={}), [free], 't', '.', 'fixture')
            self.assertEqual(tried, [fallback])
            mimo = model_router.routes('opencode-go/mimo-v2.6-pro')[0]
            self.assertEqual(store.rpc('capacity', {'route': mimo['route']})['slots'], 2)
        # A content refusal stays per-call: it says nothing about the lane.
        stack, store = offline_router()
        self.addCleanup(stack.close)
        def refuse(runtime, context, models, *args, **kwargs):
            if models[0] == free and context.model_lease.account == 'opencode-go-key':
                raise model_runtime.BudgetError('refusal:' + free)
            return 0
        with mock.patch.object(model_runtime.ModelRuntime, '_invoke', refuse):
            runtime.call(SimpleNamespace(card={}), [free], 't', '.', 'fixture')
        self.assertFalse([k for k, v in store.rpc('status', {})['health'].items() if v.get('blocked_until')])

    def test_fallback_is_shared_and_billing_is_explicit(self):
        self.addCleanup(offline_router()[0].close)
        c = SimpleNamespace(work=self.work, card={})
        tried = []
        def invoke(runtime, context, models, *args, **kwargs):
            tried.append(models[0])
            if models[0].startswith('opencode-go/'):
                raise model_runtime.BudgetError('opencode_error', provider_failure=
                    classify_provider_failure('model removed', models[0], status_code=404))
            return 0
        go, paid, free = model_router.CHAINS[-1]
        runtime = model_runtime.ModelRuntime(None, None, None, None, None)
        with mock.patch.object(model_runtime.ModelRuntime, '_invoke', invoke):
            runtime.call(c, [free], 't', '.', 'fixture')
            self.assertEqual(tried, [go, go, paid])   # both Go accounts, then OpenRouter; never the free lane
            other = SimpleNamespace(card={})
            tried.clear()
            runtime.call(other, [free], 't', '.', 'fixture')
            self.assertEqual(tried, [paid])
        self.assertEqual(c.card['route_receipts'][-1]['billing'], 'paid')
        self.assertTrue(c.force_budget_resume)


if __name__ == "__main__": main()
