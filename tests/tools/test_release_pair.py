"""A proposed plumbing/bench pair must accept the calls it will actually make."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "bin/check-release-pair.py"
RUN = ROOT / "factory/run.py"
STRATEGY = ROOT / "bin/strategy"


class ReleasePairTests(unittest.TestCase):
    def preflight(self, strategy=STRATEGY, *options, run=RUN):
        return subprocess.run([sys.executable, str(CHECK),
                               "--plumbing-source", str(run),
                               "--bench-source", str(strategy), *options],
                              capture_output=True, text=True)

    def test_current_pair_accepts_the_runner_call(self):
        result = self.preflight(STRATEGY, "--changed-file", "factory/run.py",
                                "--changed-file", "bin/strategy",
                                "--send", "plumbing", "--send", "bench")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("strategy interface: compatible", result.stdout)

    def test_pr_that_changes_both_channels_cannot_send_only_plumbing(self):
        result = self.preflight(STRATEGY, "--changed-file", "factory/run.py",
                                "--changed-file", "bin/strategy", "--send", "plumbing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing release channel: bench", result.stderr)

    def test_root_markdown_change_warns_without_forcing_a_bench_release(self):
        result = self.preflight(STRATEGY, "--changed-file", "factory/run.py",
                                "--changed-file", "ARCHITECTURE.md", "--send", "plumbing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("changes judge/gate cache bindings", result.stdout)

    def test_files_shipped_on_both_channels_require_both(self):
        for path in ("bin/processes.py", "factory/case_permissions.py"):
            with self.subTest(path=path):
                result = self.preflight(STRATEGY, "--changed-file", path,
                                        "--send", "plumbing")
                self.assertEqual(result.returncode, 1)
                self.assertIn("missing release channel: bench", result.stderr)

    def test_old_bench_source_rejects_the_new_shared_call(self):
        original = STRATEGY.read_text()
        old = original.replace("restored_results_root=None, shared=None,", "restored_results_root=None,")
        self.assertNotEqual(old, original)
        with tempfile.TemporaryDirectory() as directory:
            old_strategy = Path(directory) / "strategy"
            old_strategy.write_text(old)
            result = self.preflight(old_strategy, "--changed-file", "factory/run.py",
                                    "--send", "plumbing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unexpected keyword argument 'shared'", result.stderr)

    def test_bench_without_shared_execution_accepts_the_guarded_runner_call(self):
        # run.py passes **sharing only when the strategy has execute_shared (#99); the Nov 5 bench
        # at 8f63d199 has neither, so the runner calls it without the shared keywords.
        old = subprocess.run(["git", "-C", str(ROOT), "show", "8f63d199:bin/strategy"],
                             capture_output=True, text=True, check=True).stdout
        self.assertNotIn("def execute_shared", old)
        with tempfile.TemporaryDirectory() as directory:
            old_strategy = Path(directory) / "strategy"
            old_strategy.write_text(old)
            result = self.preflight(old_strategy, "--changed-file", "factory/run.py", "--send", "plumbing")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unguarded_or_unknown_keyword_unpacking_stays_dynamic(self):
        strategy_text = "def execute_shared():\n    pass\ndef simulate(case, **kwargs):\n    pass\n"
        for run_text in ("def f(module, extra):\n    module.simulate(None, **extra)\n",
                         "def f(module):\n    extra = {'a': 1} if ready() else {}\n    module.simulate(None, **extra)\n",
                         "def f(module, b):\n    extra = {'a': 1} if hasattr(module, 'execute_shared') else b\n"
                         "    extra = {}\n    module.simulate(None, **extra)\n"):
            with self.subTest(run=run_text), tempfile.TemporaryDirectory() as directory:
                run, strategy = Path(directory) / "run.py", Path(directory) / "strategy"
                run.write_text(run_text)
                strategy.write_text(strategy_text)
                result = self.preflight(strategy, "--changed-file", "bin/strategy", "--send", "bench", run=run)
                self.assertEqual(result.returncode, 1)
                self.assertIn("dynamic keyword arguments", result.stderr)

    def test_a_feature_the_strategy_may_define_dynamically_is_rejected(self):
        # Without the shared keywords, each of these would wrongly take the {} branch while the
        # runtime hasattr(module, "execute_shared") could be true.
        simulate = "def simulate(case, strategy, runs, seed, **kwargs):\n    pass\n"
        for source in ("if True:\n    def execute_shared():\n        pass\n",
                       "try:\n    from shared import execute_shared\nexcept ImportError:\n    pass\n",
                       "from shared import *\n",
                       "def __getattr__(name):\n    raise AttributeError(name)\n",
                       "globals()['execute_' + 'shared'] = print\n",
                       "def install():\n    global execute_shared\n    execute_shared = print\n",
                       "def execute_shared():\n    pass\ndel execute_shared\n"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                strategy = Path(directory) / "strategy"
                strategy.write_text(source + simulate.replace("**kwargs", "factory_workers=1, checkpoint_cache_dir=None, "
                                                                           "checkpoint_binding=None, restored_results_root=None"))
                result = self.preflight(strategy, "--changed-file", "factory/run.py", "--send", "plumbing")
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("cannot be resolved statically", result.stderr)

    def test_full_git_diff_catches_a_missing_bench_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            def git(*args):
                subprocess.run(["git", "-C", str(repo), *args], check=True,
                               capture_output=True, text=True)
            git("init", "-q")
            git("config", "user.name", "Release Test")
            git("config", "user.email", "release-test@example.invalid")
            (repo / "factory").mkdir()
            (repo / "bin").mkdir()
            (repo / "factory/run.py").write_text("old\n")
            (repo / "bin/strategy").write_text("old\n")
            git("add", ".")
            git("commit", "-qm", "base")
            (repo / "factory/run.py").write_text("new\n")
            (repo / "bin/strategy").write_text("new\n")
            git("commit", "-qam", "pair")
            result = self.preflight(STRATEGY, "--base", "HEAD~1", "--repo", str(repo),
                                    "--send", "plumbing")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing release channel: bench", result.stderr)

    def test_required_keyword_only_strategy_parameter_is_checked(self):
        original = STRATEGY.read_text()
        changed = original.replace("shared_binding=None):", "shared_binding=None, *, required_extra):")
        self.assertNotEqual(changed, original)
        with tempfile.TemporaryDirectory() as directory:
            strategy = Path(directory) / "strategy"
            strategy.write_text(changed)
            result = self.preflight(strategy, "--changed-file", "bin/strategy", "--send", "bench")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing a required argument: 'required_extra'", result.stderr)

    def test_required_positional_strategy_parameter_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            strategy = Path(directory) / "strategy"
            strategy.write_text("def simulate(case, strategy, runs, seed, extra, **kwargs):\n    pass\n")
            result = self.preflight(strategy, "--changed-file", "bin/strategy", "--send", "bench")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing a required argument: 'extra'", result.stderr)

    def test_required_positional_only_argument_cannot_be_filled_by_kwargs(self):
        with tempfile.TemporaryDirectory() as directory:
            strategy = Path(directory) / "strategy"
            strategy.write_text("def simulate(case, strategy, runs, seed, extra, /, **kwargs):\n    pass\n")
            result = self.preflight(strategy, "--changed-file", "bin/strategy", "--send", "bench")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing a required argument: 'extra'", result.stderr)

    def test_positional_only_name_can_also_pass_through_kwargs(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run.py"
            strategy = Path(directory) / "strategy"
            run.write_text("def f(module):\n    module.simulate(None, case=None)\n")
            strategy.write_text("def simulate(case, /, **kwargs):\n    pass\n")
            result = self.preflight(strategy, "--changed-file", "bin/strategy",
                                    "--send", "bench", run=run)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
