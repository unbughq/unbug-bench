"""The actual launcher must stage all imports needed by its live-window judge."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("audited_launcher", ROOT / "harbor/run-audited.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LiveRuntimeStagingTests(unittest.TestCase):
    def test_dry_run_stages_importable_live_judge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            harbor = source / "harbor"
            harbor.mkdir(parents=True)
            # Minimal input tree, with real judge code and no prepared shop required.
            (source / "bin").symlink_to(ROOT / "bin", target_is_directory=True)
            (source / "factory").symlink_to(ROOT / "factory", target_is_directory=True)
            (source / "cases").symlink_to(ROOT / "cases", target_is_directory=True)
            (harbor / "phase2").symlink_to(ROOT / "harbor/phase2", target_is_directory=True)
            for name in ("webproxy", "responder", "keyswap"):
                (harbor / name).mkdir()
            seed = source / "projects/medusa/seed-ids.json"
            seed.parent.mkdir(parents=True)
            seed.write_text("{}")
            task = root / "task"
            window = task / "steps/01"
            window.mkdir(parents=True)
            (window / "window.json").write_text('{"probe_kind": "medusa"}')
            (window / "instruction.md").write_text("")
            (task / "task.toml").write_text("artifacts = []\n")
            executable = root / "harbor-cli"
            executable.write_text("#!" + sys.executable + "\n")
            stage = root / "stage"
            stage.mkdir()
            args = ["run-audited.py", "--agent", "oracle", "--job-name", "staging-test",
                    "--task", str(task), "--jobs-dir", str(root / "jobs"),
                    "--harbor", str(executable), "--dry-run"]
            with patch.object(launcher, "HERE", harbor), patch.object(sys, "argv", args), \
                    patch.object(launcher.tempfile, "mkdtemp", return_value=str(stage)), \
                    patch.object(launcher.subprocess, "check_output", return_value="0.24.0\n"), \
                    patch.object(launcher.subprocess, "call", return_value=0) as invoke, \
                    patch.object(launcher.subprocess, "run") as docker, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as exited:
                    launcher.main()
                self.assertEqual(exited.exception.code, 0)
                docker.assert_not_called()
                command = invoke.call_args.args[0]
                self.assertIn(str(stage / "runtime/harbor/phase2/run.py"), command)
                self.assertIn("--dry-run", command)
            runtime = stage / "runtime/bin"
            # -I excludes repository/PYTHONPATH imports that could conceal an omitted file.
            result = subprocess.run([sys.executable, "-I", "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); import silent_window, processes; "
                "from checkpoint_evidence import record_paths", str(runtime)],
                cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            module = runtime / "checkpoint_evidence.py"
            manifest = json.loads((stage / "inputs.sha256.json").read_text())
            self.assertEqual(manifest["runtime/bin/checkpoint_evidence.py"],
                             hashlib.sha256(module.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
