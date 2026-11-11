"""control/release.py with a fake Boat and fake operator commands: no network, VM or controller."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
REAL_RUN = subprocess.run
spec = importlib.util.spec_from_file_location("release_under_test", ROOT / "control/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
BENCH = "b" * 64


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class FakeBoat:
    """Records every Boat call; the bake prints its markers, the image serves BENCH."""

    def __init__(self, fail=None):
        self.calls, self.fail, self.n = [], fail, 0

    def run(self, args, *, stdin=None, timeout=120.0):
        self.calls.append(args)
        if self.fail and self.fail in args[0]:
            return 1, b""
        if args[0] == "new":
            self.n += 1
            return 0, json.dumps({"event": "created", "id": f"bx_0000000{self.n}"}).encode() + b"\n"
        return 0, b""

    def ssh(self, worker, command, *, stdin=None, timeout=120.0):
        self.calls.append(["ssh", worker, command[:40]])
        if self.fail and self.fail in command:
            return 1, b"boom\n"
        if "bake-image.sh" in command:
            count = int(command.split("--source-count ")[1].split()[0])
            return 0, f"PREPARE={json.dumps({'source_files_verified': count})}\nBENCH_VERSION={BENCH}\n".encode()
        if command == release.FINGERPRINT:
            return 0, BENCH.encode() + b"\n"
        return 0, b""


class Release(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()   # the installer refuses symlinked parents (macOS /var)
        self.repo, self.work = self.dir / "repo", self.dir / "work"
        self.repo.mkdir()
        for name in ("tools/install_source.py", "factory/run.py", "factory/durable/workers.py", "bin/strategy",
                     "bin/check-release-pair.py", "AGENTS.md"):
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, self.repo / name)
        (self.repo / "projects/medusa").mkdir(parents=True)
        (self.repo / "projects/medusa/seed-ids.json").write_text("{}")
        (self.repo / "PLAN.md").write_text("not bench source")
        git(self.repo, "init", "-q")
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
        self.commit = git(self.repo, "rev-parse", "HEAD")
        drained = self.dir / "check-drained.py"   # PR #106's script; faked by `operator` below
        drained.write_text("")
        patcher = mock.patch.object(release, "CHECK_DRAINED", drained)
        patcher.start()
        self.addCleanup(patcher.stop)

    def main(self, *argv, boat=None):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(err):
            code = release.main(["--repo", str(self.repo), "--work", str(self.work), *argv], boat=boat)
        return code, out.getvalue(), err.getvalue()

    def state(self, kind):
        return json.loads((self.work / f"{kind}-{self.commit[:12]}" / "state.json").read_text())

    def test_bench_source_selects_binds_and_installs(self):
        out = self.dir / "bs"
        bound = release.bench_source(self.repo, self.commit, out)
        manifest = json.loads((out / "source-manifest.json").read_text())["files"]
        self.assertEqual(set(manifest), {"tools/install_source.py", "factory/run.py", "factory/durable/workers.py",
                                         "bin/strategy", "bin/check-release-pair.py", "AGENTS.md"})
        self.assertEqual(bound["count"], len(manifest))
        with tarfile.open(out / "public-source.tgz") as tar:
            modes = {m.name: m.mode for m in tar.getmembers()}
        self.assertEqual(modes["unbug-bench/bin/strategy"], 0o755)
        self.assertEqual(modes["unbug-bench/AGENTS.md"], 0o644)
        prepare = (out / "prepare.py").read_text()
        self.assertIn(f"m.MANIFEST_SHA='{bound['manifest_sha']}'", prepare)
        self.assertIn(release.INSTALLER_SHA, prepare)
        # The bound installer accepts exactly this manifest and bundle and installs the tree.
        done = subprocess.run([sys.executable, "-B", str(out / "install_source.py"), "--manifest",
                               str(out / "source-manifest.json"), "--root", str(self.dir / "installed"),
                               "--bundle", str(out / "public-source.tgz"), "--manifest-sha256", bound["manifest_sha"],
                               "--bundle-sha256", bound["bundle_sha"], "--source-count", str(bound["count"])],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_changed_installer_is_refused(self):
        (self.repo / "tools/install_source.py").write_text("# changed\n")
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "x")
        with self.assertRaisesRegex(release.Refused, "INSTALLER_SHA"):
            release.bench_source(self.repo, git(self.repo, "rev-parse", "HEAD"), self.dir / "bs")

    def test_bake_snapshots_a_new_name_tests_it_and_resumes_without_boat(self):
        boat = FakeBoat()
        code, out, err = self.main("bake-bench", self.commit, "--from-image", "bench-env", boat=boat)
        self.assertEqual(code, 0, err)
        state = self.state("bench")
        image = state["image"]
        self.assertRegex(image, r"^durable-bench-\d{8}-" + self.commit[:7] + "$")
        self.assertEqual((state["bench_version"], state["tested"], "sandbox" in state), (BENCH, True, False))
        news = [c for c in boat.calls if c[0] == "new"]
        self.assertEqual([c[2] for c in news], ["bench-env", image])    # bake from current, test the new one
        self.assertTrue(all("--no-env" in c and "--no-monitoring" in c for c in news))
        self.assertIn(["snapshot", "bx_00000001", image], boat.calls)
        self.assertEqual([c[1] for c in boat.calls if c[0] == "delete"], ["bx_00000001", "bx_00000002"])
        result = json.loads((self.work / f"bench-{self.commit[:12]}" / "result.json").read_text())
        self.assertEqual(result, {"source": self.commit, "bench_version": BENCH, "image": image,
                                  "source_files_verified": state["bound"]["count"],
                                  "no_model_secrets": True, "model_calls": 0})
        again = FakeBoat()
        self.assertEqual(self.main("bake-bench", self.commit, "--from-image", "bench-env", boat=again)[0], 0)
        self.assertEqual(again.calls, [])

    def test_a_failed_test_deletes_its_sandbox_and_resumes_at_the_test(self):
        boat = FakeBoat(fail="docker image inspect")
        code, _, err = self.main("bake-bench", self.commit, "--from-image", "bench-env", boat=boat)
        self.assertEqual(code, 1)
        self.assertIn("Medusa image failed", err)
        self.assertEqual(self.state("bench").get("tested"), None)
        self.assertNotIn("sandbox", self.state("bench"))
        again = FakeBoat()
        self.assertEqual(self.main("bake-bench", self.commit, "--from-image", "bench-env", boat=again)[0], 0)
        self.assertEqual([c[0] for c in again.calls if c[0] != "ssh"], ["new", "delete"])   # no rebake
        self.assertNotIn("snapshot", [c[0] for c in again.calls])

    def test_a_sandbox_left_by_a_killed_run_is_deleted_first(self):
        path = self.work / f"bench-{self.commit[:12]}" / "state.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"commit": self.commit, "sandbox": "bx_deadbeef"}))
        boat = FakeBoat()
        self.assertEqual(self.main("bake-bench", self.commit, "--from-image", "bench-env", boat=boat)[0], 0)
        self.assertEqual(boat.calls[0], ["delete", "bx_deadbeef", "--yes"])

    def test_the_current_image_is_never_the_snapshot_name(self):
        name = f"durable-bench-{release.time.strftime('%Y%m%d', release.time.gmtime())}-{self.commit[:7]}"
        boat = FakeBoat()
        code, _, err = self.main("bake-bench", self.commit, "--from-image", name, boat=boat)
        self.assertEqual(code, 1)
        self.assertIn("never overwrite", err)
        self.assertEqual(boat.calls, [])

    def test_real_boat_calls_never_self_update(self):
        with mock.patch.dict(os.environ, {"BOAT_NO_UPDATE": "0"}):
            self.assertEqual(release.boat_cli().env["BOAT_NO_UPDATE"], "1")
        self.assertIn("'BOAT_NO_UPDATE': '1'", (ROOT / "bin/boat-call").read_text())

    def test_build_plumbing_stores_the_commit_bundle_once(self):
        built = []

        def run(cmd, **kw):   # the tree's own workers.py builds the bundle; a stand-in here
            if cmd[0] == "git":
                return REAL_RUN(cmd, **kw)
            built.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "e" * 64 + "\n", "")
        with mock.patch.object(release.subprocess, "run", run):
            code, out, err = self.main("build-plumbing", self.commit)
        self.assertEqual(code, 0, err)
        cmd = built[0]
        tree = self.work / f"plumbing-{self.commit[:12]}" / "source"
        self.assertEqual(cmd[2:5], [str(tree / "factory/durable/workers.py"), "release", "--root"])
        self.assertTrue((tree / "factory/run.py").is_file())
        self.assertFalse((tree / ".git").exists())
        self.assertEqual(self.state("plumbing")["plumbing_version"], "e" * 64)
        with mock.patch.object(release.subprocess, "run", run):
            self.assertEqual(self.main("build-plumbing", self.commit)[0], 0)
        self.assertEqual(len(built), 1)   # recorded: not rebuilt

    def operator(self, drained_code=0, pair_code=0):
        """Records ready for register/send, and a subprocess.run that fakes the three helpers."""
        for kind, extra in (("bench", {"bench_version": BENCH, "image": "durable-bench-x", "tested": True}),
                            ("plumbing", {"plumbing_version": "e" * 64, "bundle": "/b.tgz", "source": "/t"})):
            path = self.work / f"{kind}-{self.commit[:12]}" / "state.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"commit": self.commit, **extra}))
        calls = []

        def run(cmd, **kw):
            if cmd[0] == "git":
                return REAL_RUN(cmd, **kw)
            name = Path(cmd[2]).name
            if name == "unbug":
                payload = json.loads(Path(cmd[-1]).read_text()) if cmd[5].endswith("_release") else None
                mode = os.stat(cmd[-1]).st_mode & 0o777 if payload else None
                calls.append(("unbug", cmd[5:], payload, mode))
                return subprocess.CompletedProcess(cmd, 0, "{}", "")
            calls.append((name, cmd[3:]))
            return subprocess.CompletedProcess(cmd, {"check-drained.py": drained_code,
                                                     "check-release-pair.py": pair_code}[name])
        return calls, run

    def test_register_installs_the_recorded_pair(self):
        calls, run = self.operator()
        with mock.patch.object(release.subprocess, "run", run):
            code, out, err = self.main("register", "--config", "/c.json", "--plumbing", self.commit,
                                       "--bench", self.commit)
        self.assertEqual(code, 0, err)
        self.assertEqual(calls, [("unbug", ["install", "/b.tgz", BENCH, "durable-bench-x"], None, None)])

    def test_send_checks_the_pair_then_drained_then_sends_each_batch(self):
        calls, run = self.operator()
        with mock.patch.object(release.subprocess, "run", run):
            code, out, err = self.main("send", "--config", "/c.json", "--plumbing", self.commit, "--bench",
                                       self.commit, "--base", "HEAD~0", "--channel", "plumbing",
                                       "--batch", "b-one", "--batch", "b-two")
        self.assertEqual(code, 0, err)
        self.assertEqual([c[0] for c in calls], ["check-release-pair.py", "check-drained.py", "unbug", "unbug"])
        self.assertIn("--send=plumbing", calls[0][1])
        self.assertEqual(calls[1][1], ["--config", "/c.json"])
        self.assertEqual([(c[1][:2], c[2], c[3]) for c in calls[2:]],
                         [(["plumbing_release", "b-one"], {"plumbing_version": "e" * 64}, 0o600),
                          (["plumbing_release", "b-two"], {"plumbing_version": "e" * 64}, 0o600)])

    def test_send_refuses_unless_drained_and_paired(self):
        for drained_code, pair_code, said in ((1, 0, "not drained"), (2, 0, "not drained"),
                                              (0, 1, "check-release-pair")):
            with self.subTest(drained=drained_code, pair=pair_code):
                calls, run = self.operator(drained_code, pair_code)
                with mock.patch.object(release.subprocess, "run", run):
                    code, _, err = self.main("send", "--config", "/c.json", "--plumbing", self.commit, "--bench",
                                             self.commit, "--base", "HEAD", "--channel", "bench", "--batch", "b-one")
                self.assertEqual(code, 1)
                self.assertIn(said, err)
                self.assertNotIn("unbug", [c[0] for c in calls])

    def test_send_and_switch_fail_clearly_without_check_drained(self):
        calls, run = self.operator()
        with mock.patch.object(release, "CHECK_DRAINED", self.dir / "absent.py"), \
                mock.patch.object(release.subprocess, "run", run):
            for argv in (("send", "--base", "HEAD", "--channel", "bench", "--batch", "b-one", "--bench", self.commit),
                         ("switch", "--source-current", "/s")):
                code, _, err = self.main(*argv, "--config", "/c.json", "--plumbing", self.commit)
                self.assertEqual(code, 1)
                self.assertIn("#106", err)
        self.assertNotIn("unbug", [c[0] for c in calls])

    def test_switch_prints_root_commands_and_runs_none(self):
        calls, run = self.operator()
        with mock.patch.object(release.subprocess, "run", run):
            code, out, err = self.main("switch", "--config", "/c.json", "--plumbing", self.commit,
                                       "--source-current", "/home/user/x/source-current")
        self.assertEqual(code, 0, err)
        self.assertEqual([c[0] for c in calls], ["check-drained.py"])
        self.assertIn("sudo ln -sfn /t /home/user/x/source-current\n", out)
        self.assertIn("sudo systemctl restart unbug-durable-case-campaign.service\n", out)

    def test_unbuilt_releases_are_refused(self):
        code, _, err = self.main("register", "--config", "/c.json", "--plumbing", self.commit, "--bench", self.commit)
        self.assertEqual(code, 1)
        self.assertIn("build-plumbing first", err)


if __name__ == "__main__":
    unittest.main()
