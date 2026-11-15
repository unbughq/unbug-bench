"""A prompt over Linux's 128 KiB one-argument limit reaches the CLI on stdin (14-15 Nov, case 2abb0a)."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import argparse
from contextlib import contextmanager
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock
import model_call_gate
import model_runtime
from budget import run_budgeted
from router_test_support import offline_router

PROMPT = 'x' * (2 * model_runtime.ARG_LIMIT)


class PromptOverStdin(unittest.TestCase):
    def test_run_budgeted_writes_the_prompt_to_the_childs_stdin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary); seen = root / 'seen'
            # The child prints before it reads: the write must not deadlock against our reader.
            receipt = {'type': 'step_finish', 'sessionID': 's', 'part': {'id': 'p', 'messageID': 'p', 'cost': 0.1,
                       'tokens': {'input': 1, 'output': 1, 'reasoning': 0, 'cache': {'read': 0, 'write': 0}}}}
            child = ("import sys; print('x' * 200000, flush=True); "
                     "open(sys.argv[1], 'w').write(str(len(sys.stdin.buffer.read()))); print(sys.argv[2])")
            run_budgeted([sys.executable, '-c', child, str(seen), json.dumps(receipt)], root, dict(os.environ),
                         root / 'transcript', root / 'ledger.json', 30, containment=False,
                         concurrent=True, prompt=PROMPT.encode())
            self.assertEqual(seen.read_text(), str(len(PROMPT)))

    def test_no_driver_puts_the_prompt_in_argv(self):
        self.addCleanup(offline_router()[0].close)
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary); (root / 'transcripts').mkdir()
            home = root / 'codex-home'; home.mkdir()
            c = types.SimpleNamespace(work=root, case=root / 'case', case_id='synthetic', card={}, model_env={},
                ledger=root / 'ledger.json', args=argparse.Namespace(agent_timeout=3, max_cost=5,
                max_role_calls=10, max_total_calls=20, no_progress_minutes=1, max_zero_tokens=3, resume=None))
            runtime = model_runtime.ModelRuntime(root, mock.Mock(), mock.Mock(),
                lambda path, sudo=False: shutil.rmtree(path), mock.Mock())
            seen = {}
            def budgeted(cmd, cwd, env, *args, **kwargs):
                seen[kwargs['driver']] = (cmd, kwargs.get('prompt'))
                return subprocess.CompletedProcess(cmd, 0)
            @contextmanager
            def no_gate(lease, env, cap_used, timeout, cancel=None, *, user=None): yield cancel
            with mock.patch.dict(os.environ, {'CODEX_HOME': str(home)}), \
                 mock.patch.object(model_runtime, 'pinned_cli', lambda kind: kind), \
                 mock.patch.object(model_runtime, '_opencode_flags', return_value=()), \
                 mock.patch.object(model_call_gate, 'enforce', no_gate), \
                 mock.patch.object(model_runtime, 'run_budgeted', budgeted):
                for model in ('codex/gpt-6.1-sol', 'claude/claude-opus-5-5', 'opencode/deepseek-v4.1-flash-free'):
                    runtime.call(c, [model], PROMPT, root, 'easy-calibrator-1')
        self.assertEqual(set(seen), {'codex', 'claude', 'opencode'})
        for driver, (cmd, prompt) in seen.items():
            with self.subTest(driver=driver):
                self.assertNotIn(PROMPT, cmd)
                self.assertEqual(prompt, PROMPT.encode())
        self.assertEqual(seen['codex'][0][-1], '-')  # codex exec reads `-` from stdin


if __name__ == '__main__':
    unittest.main()
