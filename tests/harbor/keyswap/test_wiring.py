"""Launcher configuration checks; no Harbor/container/model execution."""
import sys
from pathlib import Path
_TEST_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_TEST_ROOT / "harbor/keyswap"))
sys.path.insert(0, str(_TEST_ROOT / "tests/harbor/keyswap"))
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import keyswap

spec = importlib.util.spec_from_file_location("audited", Path(__file__).resolve().parents[3] / "harbor/run-audited.py")
audited = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audited)


class Wiring(unittest.TestCase):
    def test_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task"
            task.mkdir()
            (task / "task.toml").write_text('schema_version = "1.4"\nartifacts = []\n')
            secret = root / "real-credential"
            secret.write_text("DO_NOT_UPLOAD_OR_LOG_THIS_CREDENTIAL")
            env = {"KEYSWAP_CLAUDE_TOKEN_FILE": str(secret), "KEYSWAP_CODEX_AUTH_FILE": str(secret),
                   "CLAUDE_CODE_OAUTH_TOKEN": secret.read_text(), "OPENAI_API_KEY": secret.read_text(),
                   "CODEX_AUTH_JSON_PATH": str(secret), "ANTHROPIC_API_KEY": secret.read_text()}
            for agent in ("oracle", "nop", "codex", "claude-code", "arm_b:ArmB", "unbug.agent:UnbugAgent", "unbug.agent:OneShotAgent"):
                with patch.dict(os.environ, env), patch.object(sys, "argv", ["run-audited.py", "--agent", agent,
                        "--job-name", "wiring", "--task", str(task), "--dry-run"]), \
                     patch.object(audited.subprocess, "check_output", return_value="0.24.0"), \
                     patch.object(audited.subprocess, "call", return_value=0) as launch, \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    with self.assertRaises(SystemExit) as result:
                        audited.main()
                    self.assertEqual(result.exception.code, 0)
                stage = Path(json.loads(output.getvalue())["staged_inputs"])
                try:
                    args, child_env = launch.call_args.args[0], launch.call_args.kwargs["env"]
                    self.assertNotIn(secret.read_text(), json.dumps(args) + json.dumps(child_env))
                    self.assertNotIn("boat.dev", json.dumps(args))
                    if agent != "codex":
                        self.assertNotIn("CODEX_AUTH_JSON_PATH", child_env)
                    if agent in ("oracle", "nop"):
                        self.assertFalse((stage / "keyswap.yaml").exists())
                        continue
                    overlay = json.loads((stage / "keyswap.yaml").read_text())["services"]
                    self.assertEqual(set(overlay), {"main", "keyswap"})
                    mounts = overlay["keyswap"]["volumes"]
                    real = [m for m in mounts if isinstance(m, dict)]
                    self.assertEqual(len(real), 1)
                    self.assertEqual(real[0]["source"], str(secret.resolve()))
                    self.assertEqual(real[0]["read_only"], agent != "codex")
                    self.assertNotIn("volumes", overlay["main"])
                    if agent == "codex":
                        dummy = Path(child_env["CODEX_AUTH_JSON_PATH"])
                        self.assertEqual(dummy, stage / "keyswap/placeholder-auth.json")
                        data = json.loads(dummy.read_text())
                        self.assertEqual(data, {"auth_mode": "apikey", "OPENAI_API_KEY": keyswap.PLACEHOLDER})
                        self.assertIn("config=" + str(stage / "keyswap/codex.toml"), args)
                    else:
                        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN=" + keyswap.PLACEHOLDER, args)
                        self.assertEqual(overlay["main"]["environment"]["ANTHROPIC_BASE_URL"], "http://keyswap:8090/anthropic")
                    # Frozen source hashes include the generated relay overlay and dummy config.
                    self.assertIn("keyswap.yaml", json.loads((stage / "inputs.sha256.json").read_text()))
                finally:
                    shutil.rmtree(stage)


if __name__ == "__main__":
    unittest.main()
