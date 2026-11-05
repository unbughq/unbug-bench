"""Model execution contract: CLI policy, credentials, isolation and cleanup."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import model_runtime
import model_router
from router_test_support import offline_router
_ROUTING = offline_router()


class ModelRuntimeTests(unittest.TestCase):
    def test_containment_errors_stop_routing_and_reach_card(self):
        self.addCleanup(offline_router()[0].close)
        for label in ('containment_unavailable', 'cancellation_failed'):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary); (root / 'transcripts').mkdir()
                c = types.SimpleNamespace(work=root, case=root / 'case', card={}, model_env={},
                    ledger=root / 'ledger.json', args=argparse.Namespace(agent_timeout=3,
                    max_cost=5, max_role_calls=10, max_total_calls=20,
                    no_progress_minutes=1, max_zero_tokens=3))
                runtime = model_runtime.ModelRuntime(root, mock.Mock(), mock.Mock(),
                    lambda path, sudo=False: shutil.rmtree(path), mock.Mock())
                with mock.patch.object(model_runtime, 'pinned_cli', return_value='synthetic'), \
                     mock.patch.object(model_runtime, 'run_budgeted',
                                       side_effect=model_runtime.BudgetError(label)) as process:
                    with self.assertRaisesRegex(model_runtime.BudgetError, label):
                        runtime.call(c, ['claude/claude-opus-5-5'], 'synthetic', root, 'builder-1',
                                     user='' if label == 'containment_unavailable' else None)
                self.assertEqual(process.call_count, 1)
                self.assertTrue(process.call_args.kwargs['containment'])
                self.assertIn({'stage': 'model_containment', 'error': label}, c.card['cleanup_errors'])

    def test_subscription_execution_contract(self):
        self.addCleanup(offline_router()[0].close)
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            c = types.SimpleNamespace(work=root, case=root / 'case', card={},
                model_env={"FACTORY_ROUTER_TOKEN":"public-case-router-sentinel"})
            runtime = model_runtime.ModelRuntime(root, mock.Mock(), mock.Mock(),
                lambda path, sudo=False: shutil.rmtree(path), lambda user: root / user)
            # argv/env and isolation only: no CLI or model process starts.
            import os, subprocess
            seen = []
            c.args = argparse.Namespace(agent_timeout=1, max_cost=5, max_role_calls=1, max_total_calls=1, no_progress_minutes=15, max_zero_tokens=3)
            c.ledger = c.work / "ledger.json"; (c.work / "transcripts").mkdir()
            home = c.work / "codex-home"; home.mkdir()  # the boat VM's config shape
            (home / "config.toml").write_text('model_provider = "boat-openai"\n[mcp_servers.computer]\ncommand = "x"\n'
                                              '[model_providers.boat-openai]\nbase_url = "https://relay/v1"\n')
            fake_env = {"FACTORY_ROUTER_TOKEN":"public-router-sentinel", "FACTORY_ROUTER_URL":"https://router.invalid", "FACTORY_ROUTER_CA_FILE":"/public/ca", "OPENAI_API_KEY": "x", "ANTHROPIC_API_KEY": "x", "CODEX_HOME": str(home), "PATH": os.environ["PATH"]}
            def budgeted(cmd, cwd, env, *a, **k):
                self.assertFalse(any(k.startswith("FACTORY_ROUTER_") for k in env))
                self.assertNotIn("public-case-router-sentinel", str(env))
                seen.append((cmd, env, k["driver"], (pathlib.Path(env.get("CODEX_HOME", "/nonexistent")) / "config.toml").read_text() if k["driver"] == "codex" else ""))
                return subprocess.CompletedProcess(cmd, 0)
            with mock.patch.dict(os.environ, fake_env, clear=True), mock.patch.object(model_runtime, "pinned_cli", lambda kind: kind), \
                 mock.patch.object(model_runtime, "run_budgeted", budgeted):
                runtime.call(c, ["codex/gpt-6.1-sol"], "hi", c.work, "builder-1")
                runtime.call(c, ["claude/claude-opus-5-5"], "hi", c.work, "attacker-1")
                runtime.call(c, ["claude/claude-opus-5-5"], "hi", c.work, "reviewer-1")
            (codex, cenv, d1, config), (claude, aenv, d2, _), (claude_reviewer, *_) = seen
            assert (d1, d2) == ("codex", "claude")
            assert "mcp_servers" not in config and 'model_provider = "boat-openai"' in config and "https://relay/v1" in config
            assert codex[:2] == ["codex", "exec"] and 'web_search="disabled"' in codex and 'model_reasoning_effort="high"' in codex
            assert codex[codex.index("-m") + 1] == "gpt-6.1-sol" and "--ephemeral" in codex and "OPENAI_API_KEY" not in cenv
            assert all(f in codex for f in ("multi_agent", "browser_use", "apps", "computer_use")), "no subagents, browser or connectors"
            assert claude[claude.index("--model") + 1] == "claude-opus-5-5" and claude[claude.index("--effort") + 1] == "high"
            assert claude_reviewer[-1] == "Bash,Edit,Read,Write", "no web outside the searching roles"
            assert claude[-1] == "Bash,Edit,Read,Write,WebSearch,WebFetch" and "--no-session-persistence" in claude and "ANTHROPIC_API_KEY" not in aenv
            assert not any(pathlib.Path(e[k]).exists() for e, k in ((cenv, "CODEX_HOME"), (aenv, "CLAUDE_CONFIG_DIR"))), "scratch dirs removed"
            tester_home = c.work / 'tester'; (tester_home / '.cache').mkdir(parents=True)
            fake_sh = lambda c, cmd, **k: (shutil.move(str(cmd[2]), str(cmd[3])) and 0) if list(cmd[:2]) == ['sudo', 'mv'] else 0  # hand_to's move
            runtime = model_runtime.ModelRuntime(root, fake_sh, mock.Mock(),
                lambda path, sudo=False: shutil.rmtree(path), lambda user: tester_home)
            with mock.patch.object(model_runtime, 'pinned_cli', lambda kind: kind), \
                 mock.patch.object(model_runtime, 'run_budgeted', budgeted):
                runtime.call(c, ["claude/claude-opus-5-5"], "hi", c.work, "strong-calibrator-1", user="pilot")
            assert seen[-1][0][0] == 'sudo'
            assert {'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CONFIG_DIR', 'ANTHROPIC_BASE_URL',
                    'CLAUDE_CODE_MAX_OUTPUT_TOKENS', 'CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS'} <= set(seen[-1][0][1].split('=', 1)[1].split(','))
            assert '-u' in seen[-1][0] and 'pilot' in seen[-1][0], 'Claude tester uses the isolated Unix user'
            u = seen[-1][0].index('pilot')  # the isolated user enters its own private dir; the runner never chdirs there
            assert seen[-1][0][u + 1:u + 4] == ['sh', '-c', 'cd "$1" && shift && exec "$@"'], seen[-1][0][:12]

    def test_deepseek_openrouter_fresh_and_restored_execution(self):
        self.addCleanup(offline_router()[0].close)
        import json
        from budget import run_budgeted
        from contextlib import contextmanager
        import model_call_gate
        source = 'opencode/deepseek-v4.1-flash-free'
        target = 'openrouter/deepseek/deepseek-v4.1-flash'
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary); (root / 'transcripts').mkdir()
            roles = {'stress_tester': {'model': source, 'effort': 'default', 'family': 'deepseek'}}
            c = types.SimpleNamespace(work=root, case=root / 'case', case_id='synthetic',
                card={'roles': roles}, ledger=root / 'ledger.json',
                model_env={'FACTORY_ROUTER_TOKEN':'public-case-router-sentinel'},
                args=argparse.Namespace(agent_timeout=3, max_cost=5, max_role_calls=10,
                    max_total_calls=20, no_progress_minutes=1, max_zero_tokens=3, resume=None))
            runtime = model_runtime.ModelRuntime(root, mock.Mock(), mock.Mock(), mock.Mock(), mock.Mock())
            counter = [0]
            @contextmanager
            def config_only(lease, env, cap_used, timeout, cancel=None, *, user=None):
                # Synthetic scheduler caps, real config builder; native proof separately
                # exercises real leases/gate/CLI. No provider traffic in this test.
                if lease.route == target:
                    clean = model_call_gate.openrouter_environment(lease, env,
                        types.SimpleNamespace(server=types.SimpleNamespace(server_port=1), token='synthetic'))
                    env.clear(); env.update(clean)
                yield cancel
            def budgeted(cmd, cwd, env, *args, **kwargs):
                self.assertFalse(any(k.startswith('FACTORY_ROUTER_') for k in env))
                if cmd[cmd.index('-m') + 1] == source:
                    raise model_runtime.BudgetError('provider_limit:' + source)
                counter[0] += 1
                self.assertEqual(cmd[cmd.index('-m') + 1], target)
                self.assertEqual(kwargs['configured_model'], target)
                cfg = json.loads(env['OPENCODE_CONFIG_CONTENT'])
                self.assertEqual(cfg['small_model'], target)
                rates = cfg['provider']['openrouter']['models']['deepseek/deepseek-v4.1-flash']['cost']
                self.assertEqual(rates, {'input': .14, 'output': .42, 'cache_read': .0042, 'cache_write': 0})
                receipt = {'type': 'step_finish', 'sessionID': 'synthetic', 'part': {
                    'id': str(counter[0]), 'messageID': str(counter[0]),
                    'cost': rates['input'] + rates['output'], 'tokens': {
                        'input': 1000000, 'output': 1000000, 'reasoning': 0,
                        'cache': {'read': 0, 'write': 0}}}}
                return run_budgeted([sys.executable, '-c', 'print(' + repr(json.dumps(receipt)) + ')'],
                                    cwd, env, *args, **{**kwargs, 'containment': False})
            with mock.patch.object(model_runtime, '_opencode_flags', return_value=()), \
                 mock.patch.object(model_runtime, 'run_budgeted', side_effect=budgeted), \
                 mock.patch.object(model_call_gate, 'enforce', config_only):
                runtime.call(c, [source], 'synthetic', root, 'attacker-1')
                # A restored context has no in-memory route cache; an old cached Go route also loses.
                c.routes = {source: 'opencode-go/deepseek-v4.1-flash'}
                c.args.resume = 'synthetic'; c.budget_resumed = False
                runtime.call(c, [source], 'synthetic', root, 'attacker-2')
            self.assertEqual(c.card['roles'], roles)
            self.assertNotIn('model_transition', c.card)
            self.assertEqual(c.card['route_receipts'][-1]['route'], target)
            self.assertEqual(c.card['route_receipts'][-1]['billing'], 'paid')
            self.assertEqual(c.card['models_used'], {'attacker-1': target, 'attacker-2': target})
            ledger = json.loads(c.ledger.read_text())
            self.assertAlmostEqual(ledger['cost'], 1.12)
            self.assertEqual(ledger['calls'], 2)
            self.assertTrue(all(e['configured_model'] == target for e in ledger['events']))
            self.assertAlmostEqual(c.card['case_budget']['spent_usd'], 1.12)

    def test_checkpoint_hook_requires_engine_and_callable_binding(self):
        runtime = model_runtime.ModelRuntime(None, None, None, None, None)
        hook = mock.Mock()
        for engine, bound in ((None, hook), (object(), None), (object(), hook)):
            with self.subTest(engine=engine, bound=bound):
                c = types.SimpleNamespace(engine=engine, engine_checkpoint=bound)
                with mock.patch.object(model_runtime.ModelRuntime, '_call', return_value=7) as invoke, \
                     mock.patch('durable.checkpoints.model_call', return_value=8) as checkpoint:
                    result = runtime.call(c, ['synthetic'], 'bound prompt', '/case', 'builder-1')
                    if engine is not None and callable(bound):
                        self.assertEqual(result, 8)
                        self.assertEqual(checkpoint.call_args.kwargs['text'], 'bound prompt')
                        self.assertEqual(checkpoint.call_args.args[:4], (c, ['synthetic'], '/case', 'builder-1'))
                        invoke.assert_not_called()
                    else:
                        self.assertEqual(result, 7)
                        checkpoint.assert_not_called()
                        invoke.assert_called_once()

    def test_import_does_not_probe_or_install_a_cli(self):
        self.addCleanup(offline_router()[0].close)
        code = ("import sys; from unittest.mock import patch; "
                "sys.path.insert(0, sys.argv[1]); "
                "guard=patch('subprocess.run', side_effect=AssertionError('import launched a process')); "
                "guard.start(); import model_runtime")
        result = subprocess.run([sys.executable, '-I', '-c', code, str((pathlib.Path(__file__).resolve().parents[2] / "factory"))],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
