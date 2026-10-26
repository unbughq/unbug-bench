"""A changed judge must stop before scoring; a mid-command change must invalidate the run."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "bin/freeze"
loader = importlib.machinery.SourceFileLoader("freeze", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
freeze = importlib.util.module_from_spec(spec)
loader.exec_module(freeze)


class FreezeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in freeze.INPUTS:
            path = self.root / name
            if name.startswith(".") or name.endswith(".md"):
                path.write_text("fixture\n")
            else:
                path.mkdir()
        self.judge = self.root / "bin/judge"
        self.judge.write_text("approved\n")
        (self.root / "guards/none").mkdir()
        self.out = self.root / "results/frozen"
        self.run_cli("create", str(self.out))
        self.manifest = self.out / "manifest.json"

    def run_cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result

    def test_content_addition_and_executable_drift(self):
        self.run_cli("verify", str(self.manifest))
        self.judge.write_text("changed\n")
        self.run_cli("verify", str(self.manifest), ok=False)
        self.judge.write_text("approved\n")
        extra = self.root / "cases/new.sql"
        extra.write_text("new oracle\n")
        self.run_cli("verify", str(self.manifest), ok=False)
        extra.unlink()
        self.judge.chmod(0o755)
        self.run_cli("verify", str(self.manifest), ok=False)
        self.judge.chmod(0o644)
        self.run_cli("verify", str(self.manifest))
        other = freeze.source_files(self.root)
        self.judge.chmod(0o600)
        self.assertNotEqual(other, freeze.source_files(self.root))

    def test_guarded_command_preflight_and_postflight(self):
        marker = self.root / "results/ran"
        code = f"from pathlib import Path; Path({str(marker)!r}).touch()"
        self.run_cli("run", str(self.manifest), "--", sys.executable, "-c", code)
        self.assertTrue(marker.exists())
        marker.unlink()
        self.judge.write_text("changed\n")
        self.run_cli("run", str(self.manifest), "--", sys.executable, "-c", code, ok=False)
        self.assertFalse(marker.exists())
        self.judge.write_text("approved\n")
        change = f"from pathlib import Path; Path({str(self.judge)!r}).write_text('changed')"
        self.run_cli("run", str(self.manifest), "--", sys.executable, "-c", change, ok=False)

    def test_run_accepts_expected_hash_after_manifest(self):
        digest = freeze.sha(self.manifest)
        self.run_cli("run", str(self.manifest), "--sha256", digest, "--", sys.executable, "-c", "pass")

    def test_archive_cannot_disagree_with_unchanged_live_source(self):
        import tarfile
        tampered = self.out / "tampered.tar.gz"
        self.judge.write_text("tampered\n")
        with tarfile.open(tampered, "w:gz") as archive:
            manifest = json.loads(self.manifest.read_text())
            for name in [*manifest["directories"], *manifest["files"]]:
                archive.add(self.root / name, arcname=name, recursive=False)
        self.judge.write_text("approved\n")
        with self.assertRaises(ValueError):
            freeze.verify_archive(tampered, manifest["files"], manifest["directories"])

    def test_trusted_hash_and_artifacts(self):
        self.run_cli("verify", str(self.manifest), "--sha256", "0" * 64, ok=False)
        (self.out / "source.tar.gz").write_bytes(b"tampered")
        self.run_cli("verify", str(self.manifest), ok=False)

    def test_symlink_source_rejected(self):
        (self.root / "cases/escape").symlink_to(self.root / "README.md")
        self.run_cli("verify", str(self.manifest), ok=False)

    def test_new_root_input_rejected(self):
        (self.root / "unclassified.py").write_text("new build input\n")
        self.run_cli("verify", str(self.manifest), ok=False)

    def test_recorded_source_archive_matches_manifest(self):
        import hashlib
        import tarfile
        manifest = json.loads(self.manifest.read_text())
        with tarfile.open(self.out / "source.tar.gz") as archive:
            self.assertEqual(set(archive.getnames()), set(manifest["files"]) | set(manifest["directories"]))
            self.assertTrue(archive.getmember("guards/none").isdir())
            for item in archive:
                if item.isfile():
                    self.assertEqual(hashlib.sha256(archive.extractfile(item).read()).hexdigest(), manifest["files"][item.name]["sha256"])


if __name__ == "__main__":
    unittest.main()
