"""Synthetic Boat restart policy: no credentials, servers or case contents."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy
import hashlib
import json
import pathlib
import os
import subprocess
import sys
import tempfile
import unittest

from restart import plan


class RestartTests(unittest.TestCase):
    def test_freshness_stop_without_verdict_restores_without_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            path = root / 'case-test.scorecard.json'
            archive = root / 'case-test.checkpoint.tar.gz.age'
            archive.write_bytes(b'synthetic ciphertext')
            card = {'case': 'case-test', 'seed': 42, 'status': 'stopped',
                    'terminal_stop': 'freshness_unresolved',
                    'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                    'loop_freshness': {'rows': 0, 'verdict_path': None, 'outcome': 'unresolved'},
                    'case_budget': {'limit_usd': 50}, 'recovery_config': {'rounds': 8},
                    'continuation_budget': {'cost': .1, 'calls': 20, 'list_cost_usd': 30,
                                            'events': [], 'terminal_stop': 'complete'}}
            def check(value):
                path.write_text(json.dumps(value))
                return plan(path, 0, 7200, '--case-budget 50 --rounds 8')
            self.assertEqual(check(card), ('case-test', 60, 42))
            for changes in ({'failed_gate': 'G2'}, {'gates': {'G2': 'fail'}},
                            {'checkpoint_error': 'OSError'}, {'loop_freshness': None},
                            {'loop_freshness': {'outcome': 'unresolved'}},
                            {'loop_freshness': {'rows': 2, 'outcome': 'unresolved',
                                                'verdict_path': 'g2-confirm-1/verdict.json',
                                                'reason': 'reviewer_unresolved'}},
                            {'continuation_budget': {**card['continuation_budget'], 'list_cost_usd': 50}},
                            {'continuation_budget': {**card['continuation_budget'], 'terminal_stop': 'budget_exhausted'}}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    check({**card, **changes})

    def test_verified_transient_stops_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            path = root / "case-test.scorecard.json"
            archive = root / "case-test.checkpoint.tar.gz.age"
            archive.write_bytes(b"synthetic ciphertext")
            card = {"case": "case-test", "seed": 42, "status": "stopped", "terminal_stop": "stalled",
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "continuation_budget": {"cost": 1, "calls": 20, "events": [], "terminal_stop": "stalled"}}
            def check(data=card, retries=0, remaining=7200, args="--source hunt --max-total-calls 30 --max-cost 2", *, handoff=False):
                path.write_text(json.dumps(data))
                return plan(path, retries, remaining, args, claude_account_handoff=handoff)
            self.assertEqual(check(), ("case-test", 60, 42))
            self.assertEqual(check(retries=2), ("case-test", 240, 42))
            provider = copy.deepcopy(card)
            provider["terminal_stop"] = provider["continuation_budget"]["terminal_stop"] = "provider_limit:claude/x"
            self.assertEqual(check(provider), ("case-test", 900, 42))
            import time  # Claude names its reset: resume two minutes after it, not on a guessed backoff
            provider["continuation_budget"]["claude_resets_at"] = time.time() + 1800
            self.assertAlmostEqual(check(provider, retries=2)[1], 1920, delta=5)
            provider["continuation_budget"]["claude_resets_at"] = time.time() + 5 * 3600
            self.assertEqual(check(provider, retries=1, handoff=True)[1], 60)
            self.assertAlmostEqual(check(provider, remaining=86400)[1], 5 * 3600 + 120, delta=5)
            with self.assertRaises(ValueError): check(provider, retries=1, remaining=120, handoff=True)
            self.assertEqual(check(provider, retries=1, remaining=121, handoff=True)[1], 60)
            other = copy.deepcopy(provider)
            other["terminal_stop"] = other["continuation_budget"]["terminal_stop"] = "provider_limit:codex/x"
            self.assertEqual(check(other, retries=1, handoff=True)[1], 1800)
            with self.assertRaises(ValueError): check(provider, retries=3, handoff=True)
            for change in ({"failed_gate": "G8"}, {"checkpoint_error": "OSError"}, {"terminal_stop": "cost_limit"},
                           {"terminal_stop": "call_limit"}, {"status": "complete"}, {"sha256": "0" * 64},
                           {"terminal_stop": "paused"},
                           {"sha256": None},
                           {"continuation_budget": None}):
                with self.subTest(change=change), self.assertRaises(ValueError): check({**card, **change})
            for kwargs in ({"retries": 3}, {"remaining": 120}, {"remaining": float("nan")},
                           {"args": "--max-cost=1"}, {"args": "--max-total-calls 20"}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): check(**kwargs)
            mismatch = copy.deepcopy(card)
            mismatch["continuation_budget"]["terminal_stop"] = "total_call_limit"
            with self.assertRaises(ValueError): check(mismatch)
            archive.unlink()
            with self.assertRaises(ValueError): check()

    def test_uncertain_checkpoint_types_keep_the_vm(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "case-test.scorecard.json"
            for card in ([], {"case": None}, {"case": "case-test", "sha256": None}):
                path.write_text(json.dumps(card))
                result = subprocess.run([sys.executable, str((pathlib.Path(__file__).resolve().parents[2] / "factory" / "restart.py")),
                                         str(path), "0", "7200", ""], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_live_runner_guard_aborts_under_posix_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "sealed").mkdir()
            fake = root / "pgrep"; fake.write_text("#!/bin/sh\nexit 0\n"); fake.chmod(0o755)
            script = (pathlib.Path(__file__).resolve().parents[2] / "factory" / "launch.sh").read_text().split("mkdir ~/sealed/.factory-restart.lock\n", 1)[1].split("test -d ~/work/", 1)[0]
            result = subprocess.run(["/bin/sh", "-ec", script + "\necho STARTED"],
                                    env={**os.environ, "HOME": str(root), "PATH": str(root) + os.pathsep + os.environ["PATH"]},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("STARTED", result.stdout)


if __name__ == "__main__": unittest.main()
