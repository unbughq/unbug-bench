#!/usr/bin/env python3
"""Operator release tool: bench image and plumbing bundle from one git commit, then register and send.

Run on the control VM with the controller's venv python. Every step records its result under
--work (default ~/.unbug-release) and a rerun skips what is recorded, so a failed step is resumed
by running the same command again.

  release.py bake-bench     <commit> --from-image <current image> [--no-image-build]   # bake, snapshot, test
  release.py build-plumbing <commit>                                # bundle into the work store
  release.py register --config C --plumbing <commit> --bench <commit>
  release.py send --config C --batch B --base <ref> --plumbing <commit> --bench <commit> [--channel plumbing] [--channel bench]
  release.py switch --config C --plumbing <commit> --source-current <path>   # prints the root commands

`send` and `switch` refuse unless control/check-drained.py exits 0; `send` also runs
bin/check-release-pair.py. Every Boat call goes through bin/boat-call with BOAT_NO_UPDATE=1:
a Boat self-update breaks the factory's pinned boat-call. Root-only steps (the source-current
symlink, systemd restarts) are printed for the operator, never run.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "factory"))
from durable.workers import IMAGE_SCRIPT, PREPARE_IMAGE_SCRIPT, BoatCli, _atomic_json  # noqa: E402

# ~/bench-source selection, as the 2026-11-05 image (553 files at 8f63d199): tracked files under
# DIRS plus TOP, hashed as git blobs.
DIRS = ("bin", "cases", "factory", "guards", "harbor", "projects", "scenarios", "tools")
TOP = ("AGENTS.md", "ARCHITECTURE.md", "BRIEF-v2.md", "CONTESTANT.md", "DESIGN.md", "FACTORY.md",
       "PROTOCOL.md", "README.md", "SPEC.md", "V2.md")
GENERATED = {"projects/medusa/seed-ids.json"}
KEPT = ("projects/medusa/node_modules", "projects/medusa/.medusa", "projects/medusa/seed-ids.json")
# The reviewed image installer. A changed tools/install_source.py needs review and a new pin here.
INSTALLER_SHA = "d04709fd9d4e4088070dd7b2376e542febb31ea11c992891be1961dfb2049225"
FINGERPRINT = ("cd ~/unbug-bench/factory && env -u BENCH OPENCODE_DISABLE_AUTOUPDATE=1 "
               "python3 -B -c 'import run; print(run.bench_manifest())'")
CHECK_DRAINED = REPO / "control/check-drained.py"
CHECK_PAIR = REPO / "bin/check-release-pair.py"
SANDBOX_TTL = 14400
SANDBOX_PREFIX = "bench-"   # never the pool's unbugd1- ownership names, so no pool claims or sweeps it
# A lost `boat new` may still create its sandbox after Boat first lists nothing under its name: the
# name is cleared only by a second empty lookup at least this long after the first (the first comes
# after the client's 600 s `boat new` timeout, so a create is given 20 min in all).
ABSENT_GRACE = 600


class Refused(Exception):
    pass


def git(repo, *args, text=True) -> str | bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=text).stdout


def resolve(repo, ref) -> str:
    try:
        return git(repo, "rev-parse", "--verify", ref + "^{commit}").strip()
    except subprocess.CalledProcessError:
        raise Refused(f"not a commit: {ref}") from None


def load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def private_json(path: Path, value):
    """An owned 0600 file, as bin/unbug requires of payloads."""
    path.unlink(missing_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
        json.dump(value, f, sort_keys=True)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---- ~/bench-source ---------------------------------------------------------------------------

def bench_source(repo, commit, out: Path) -> dict:
    """source-manifest.json, public-source.tgz, install_source.py and prepare.py for `commit`."""
    rows = {}
    for line in git(repo, "ls-tree", "-r", "-z", commit).split("\0"):
        if not line:
            continue
        meta, name = line.split("\t", 1)
        mode, kind, _ = meta.split()
        if kind != "blob" or name in GENERATED:
            continue
        if name in TOP or "/" in name and name.split("/", 1)[0] in DIRS:
            if mode not in ("100644", "100755"):
                raise Refused(f"unsupported tree entry {mode} {name}")
            rows[name] = mode == "100755"
    files, buf = {}, io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, filename="") as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:   # same commit, same bytes
        for name in sorted(rows):
            data = git(repo, "show", f"{commit}:{name}", text=False)
            files[name] = sha(data)
            info = tarfile.TarInfo("unbug-bench/" + name)
            info.size, info.mode, info.mtime = len(data), 0o755 if rows[name] else 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    installer = git(repo, "show", f"{commit}:tools/install_source.py", text=False)
    if sha(installer) != INSTALLER_SHA:
        raise Refused("tools/install_source.py changed: review it, then pin its sha in INSTALLER_SHA")
    out.mkdir(parents=True, exist_ok=True)
    (out / "public-source.tgz").write_bytes(buf.getvalue())
    (out / "source-manifest.json").write_text(json.dumps({"files": files}, sort_keys=True))
    (out / "install_source.py").write_bytes(installer)
    bound = {"manifest_sha": sha((out / "source-manifest.json").read_bytes()),
             "bundle_sha": sha((out / "public-source.tgz").read_bytes()), "count": len(files)}
    (out / "prepare.py").write_text(f"""from pathlib import Path
import hashlib,importlib.util,json,os,subprocess,sys
s=Path(__file__).resolve().parent
if os.geteuid()!=0:
 subprocess.run(['sudo','-n',sys.executable,'-B',str(s/'prepare.py')],check=True)
 raise SystemExit(0)
p=s/'install_source.py'
assert hashlib.sha256(p.read_bytes()).hexdigest()=='{INSTALLER_SHA}','unqualified image installer'
spec=importlib.util.spec_from_file_location('image_source_installer',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.MANIFEST_SHA='{bound["manifest_sha"]}';m.BUNDLE_SHA='{bound["bundle_sha"]}';m.SOURCE_COUNT={bound["count"]}
files=m.load_manifest(s/'source-manifest.json')
print(json.dumps(m.prune_image(s.parent/'unbug-bench',files,s/'public-source.tgz')),flush=True)
""")
    return bound


def bake_script(bound: dict) -> str:
    """Runs on the sandbox: install the new tree, keep Medusa's generated files, bake, bind."""
    q = shlex.quote
    keep = " ".join(q(p) for p in KEPT)
    return f"""set -eu
n=/tmp/bench-source-new
rm -rf "$n"; mkdir "$n"; tar -xzf /tmp/bench-source-new.tgz -C "$n"
cd ~; sudo -n rm -rf unbug-bench.old; mv unbug-bench unbug-bench.old
python3 -B "$n/install_source.py" --manifest "$n/source-manifest.json" --root ~/unbug-bench --bundle "$n/public-source.tgz" \
  --manifest-sha256 {bound["manifest_sha"]} --bundle-sha256 {bound["bundle_sha"]} --source-count {bound["count"]} >/dev/null
for p in {keep}; do if [ -e "unbug-bench.old/$p" ]; then mv "unbug-bench.old/$p" "unbug-bench/$p"; fi; done
sh ~/unbug-bench/bin/bake-image.sh
sudo -n rm -rf ~/bench-source; mv "$n" ~/bench-source
python3 -B ~/bench-source/prepare.py >/dev/null
echo "PREPARE=$(python3 -B ~/bench-source/prepare.py | tail -1)"
echo "BENCH_VERSION=$({FINGERPRINT})"
sudo -n rm -rf ~/unbug-bench.old /tmp/bench-source-new.tgz ~/.bash_history; sync
"""


def marker(out: bytes, name: str) -> str:
    for line in reversed(out.decode("utf-8", "replace").splitlines()):
        if line.startswith(name + "="):
            return line[len(name) + 1:].strip()
    raise Refused(f"sandbox output lacks {name}")


# ---- Boat -------------------------------------------------------------------------------------

class Sandbox:
    """One Boat sandbox for a stage, recorded in the state file and deleted on exit."""

    def __init__(self, boat, state: dict, save, image: str, name: str):
        self.boat, self.state, self.save, self.image, self.name = boat, state, save, image, name

    def __enter__(self):
        # The name is on record before Boat sees the request: a lost response is found by it.
        self.state["sandbox_name"] = self.name
        self.save()
        args = ["new", "--from", self.image, "--no-env", "--no-monitoring", "--ttl", str(SANDBOX_TTL),
                "--name", self.name, "--json"]
        code, out = self.boat.run(args, timeout=600)
        for line in out.decode("utf-8", "replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("event") == "created" and isinstance(event.get("id"), str):
                self.id = event["id"]
                break
        else:
            try:
                delete(self.boat, self.state, self.save)   # it may exist anyway
            except Refused as error:
                raise Refused(f"boat new failed (exit {code}); {error}") from None
            raise Refused(f"boat new failed (exit {code})")
        self.state["sandbox"] = self.id
        self.save()
        return self

    def ssh(self, script: str, what: str, timeout: float, stdin: bytes | None = None) -> bytes:
        print(f"release: {what} on {self.id} ({time.strftime('%H:%M:%S')})", file=sys.stderr)
        code, out = self.boat.ssh(self.id, script, stdin=stdin, timeout=timeout)
        if code:
            sys.stderr.write(out.decode("utf-8", "replace")[-4000:])
            raise Refused(f"{what} failed on {self.id} (exit {code})")
        return out

    def __exit__(self, *exc):
        delete(self.boat, self.state, self.save)


def delete(boat, state: dict, save):
    """Delete the stage sandbox a state file still names (also one left by a killed run): by its id,
    or, when its create response was lost, every sandbox Boat lists under its unique name. A name is
    cleared once Boat accepts the delete of every sandbox listed under it (Boat deletes asynchronously,
    so an immediate re-list would still show them), or when two lookups ABSENT_GRACE apart list none."""
    sandbox, name = state.get("sandbox"), state.get("sandbox_name")
    if not sandbox and not name:
        return
    ids = [sandbox] if sandbox else named(boat, name)
    if not ids:
        first = state.setdefault("sandbox_absent_at", time.time())
        save()
        if time.time() - first < ABSENT_GRACE:
            raise Refused(f"Boat lists no sandbox {name} yet; it is kept on record: rerun after "
                          f"{time.strftime('%H:%M:%S', time.localtime(first + ABSENT_GRACE))} to look again")
    for worker in ids:
        code, _ = boat.run(["delete", worker, "--yes"], timeout=300)
        if code:
            raise Refused(f"delete boat sandbox {worker} by hand (exit {code})")
    for key in ("sandbox", "sandbox_name", "sandbox_absent_at"):
        state.pop(key, None)
    save()


def named(boat, name: str) -> list:
    code, out = boat.run(["list", "--json"], timeout=120)
    try:
        listing = json.loads(out)
        if code or listing["pageInfo"]["hasMore"] is not False:
            raise ValueError()
        return [row["id"] for row in listing["sandboxes"] if row.get("name") == name]
    except (ValueError, KeyError, TypeError):
        raise Refused(f"cannot list Boat: find sandbox {name} with `boat list`, delete it, rerun") from None


def boat_cli() -> BoatCli:
    return BoatCli(env={**os.environ, "BOAT_NO_UPDATE": "1"})


# ---- subcommands ------------------------------------------------------------------------------

def bake_bench(args, boat) -> dict:
    commit = resolve(args.repo, args.commit)
    work = args.work / f"bench-{commit[:12]}"
    path = work / "state.json"
    state = load(path) or {"commit": commit}
    save = lambda: _atomic_json(path, state)
    source = work / "bench-source"
    if "bound" not in state:
        state["bound"] = bench_source(args.repo, commit, source)
        save()
    delete(boat, state, save)   # a sandbox a killed run left
    if "bench_version" not in state:
        # Unique per bake, kept on resume: a re-bake of the same commit (even with a fresh --work)
        # never lands on an image already registered or serving.
        state.setdefault("image", f"durable-bench-{stamp()}-{commit[:7]}")
        if state["image"] == "bench-env" or state["image"] == args.from_image:
            raise Refused("never overwrite the current image")
        save()
        bundle = io.BytesIO()
        with tarfile.open(fileobj=bundle, mode="w:gz") as tar:
            for name in ("public-source.tgz", "source-manifest.json", "install_source.py", "prepare.py"):
                tar.add(source / name, arcname=name)
        data = bundle.getvalue()
        upload = ("set -eu; umask 077; t=/tmp/bench-source-new.tgz; cat > \"$t\"; "
                  f"printf '%s  %s\\n' {sha(data)} \"$t\" | sha256sum -c - >/dev/null")
        with Sandbox(boat, state, save, args.from_image, f"{SANDBOX_PREFIX}bake-{commit[:7]}-{stamp()}") as box:
            box.ssh(upload, "upload bench source", 600, stdin=data)
            out = box.ssh(bake_script(state["bound"]), "bake", 7200)
            prepared = json.loads(marker(out, "PREPARE"))
            bench_version = marker(out, "BENCH_VERSION")
            if prepared.get("source_files_verified") != state["bound"]["count"] or len(bench_version) != 64:
                raise Refused("bake did not verify its source")
            result = json.dumps(bench_result(commit, bench_version, prepared["source_files_verified"]),
                                sort_keys=True).encode() + b"\n"
            box.ssh("set -eu; cat > ~/bench-source/result.json; sync", "write result.json", 120, stdin=result)
            print(f"release: snapshot {box.id} as {state['image']}", file=sys.stderr)
            code, _ = boat.run(["snapshot", box.id, state["image"]], timeout=3600)
            if code:
                raise Refused(f"boat snapshot failed (exit {code})")
            state.update(bench_version=bench_version, source_files_verified=prepared["source_files_verified"])
            save()   # before the delete, which may fail
    if not state.get("tested") or args.image_build and not state.get("image_built"):
        expected = bench_result(commit, state["bench_version"], state["source_files_verified"])
        with Sandbox(boat, state, save, state["image"], f"{SANDBOX_PREFIX}test-{commit[:7]}-{stamp()}") as box:
            box.ssh(PREPARE_IMAGE_SCRIPT, "prepare.py", 600)
            if box.ssh(FINGERPRINT, "bench fingerprint", 600).decode().strip() != state["bench_version"]:
                raise Refused(f"{state['image']} does not serve bench {state['bench_version']}")
            try:
                found = json.loads(box.ssh("cat ~/bench-source/result.json", "read result.json", 120))
            except ValueError:
                found = None
            if found != expected:
                raise Refused(f"{state['image']} has no matching ~/bench-source/result.json")
            if args.image_build:
                box.ssh(IMAGE_SCRIPT, "Medusa image build (~15 min)", 1800)
        state.update(tested=True, image_built=state.get("image_built") or args.image_build)
        save()
    return state


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def bench_result(commit, bench_version, verified) -> dict:
    """~/bench-source/result.json, as on the 2026-11-05 image."""
    return {"source": commit, "bench_version": bench_version, "source_files_verified": verified,
            "no_model_secrets": True, "model_calls": 0}


def build_plumbing(args, boat=None) -> dict:
    commit = resolve(args.repo, args.commit)
    work = args.work / f"plumbing-{commit[:12]}"
    path = work / "state.json"
    state = load(path) or {"commit": commit}
    if "plumbing_version" not in state:
        tree = work / "source"
        if not tree.is_dir():   # a stable tree: `switch` points source-current at it
            work.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(dir=work))
            archive = git(args.repo, "archive", "--format=tar", commit, text=False)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(stage, filter="tar")
            stage.rename(tree)
        store = work / "releases"
        done = subprocess.run([sys.executable, "-B", str(tree / "factory/durable/workers.py"), "release",
                               "--root", str(tree), "--store", str(store)], capture_output=True, text=True)
        if done.returncode:
            raise Refused(done.stderr.strip() or "bundle build failed")
        version = done.stdout.strip()
        state.update(plumbing_version=version, bundle=str(store / "bundles" / (version + ".tgz")), source=str(tree))
        _atomic_json(path, state)
    return state


def recorded(args, kind, ref) -> dict:
    state = load(args.work / f"{kind}-{resolve(args.repo, ref)[:12]}" / "state.json")
    if kind == "bench" and not state.get("tested"):
        raise Refused(f"bench {ref} is not baked and tested: run bake-bench first")
    if kind == "bench" and not state.get("image_built") and not args.allow_unbuilt:
        raise Refused(f"bench {ref} was tested without its Medusa image build: rerun bake-bench "
                      "without --no-image-build, or pass --allow-unbuilt")
    if kind == "plumbing" and "plumbing_version" not in state:
        raise Refused(f"plumbing {ref} is not built: run build-plumbing first")
    return state


def unbug(args, *rest) -> str:
    done = subprocess.run([*shlex.split(args.unbug), "--config", str(args.config), *rest],
                          capture_output=True, text=True)
    if done.returncode:
        raise Refused(f"unbug {rest[0]} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def register(args, boat=None) -> dict:
    plumbing, bench = recorded(args, "plumbing", args.plumbing), recorded(args, "bench", args.bench)
    print(unbug(args, "install", plumbing["bundle"], bench["bench_version"], bench["image"]))
    return {"plumbing_version": plumbing["plumbing_version"], "bench_version": bench["bench_version"]}


def drained(args):
    if not CHECK_DRAINED.is_file():
        raise Refused(f"{CHECK_DRAINED} is missing (PR #106): cannot prove the controller is drained")
    command = [sys.executable, "-B", str(CHECK_DRAINED), "--config", str(args.config)]
    if args.router_db:
        command += ["--router-db", str(args.router_db)]
    done = subprocess.run(command)
    if done.returncode:
        raise Refused("controller not drained (check-drained exit %d): wait, then rerun" % done.returncode)


def send(args, boat=None) -> dict:
    """--plumbing and --bench name the pair the batch runs after the send; only --channel is sent,
    and only a sent channel needs a recorded build (the other may be a hand-built release)."""
    channels = sorted(set(args.channel))
    commits = {"plumbing": resolve(args.repo, args.plumbing), "bench": resolve(args.repo, args.bench)}
    versions = {c: recorded(args, c, getattr(args, c))[c + "_version"] for c in channels}
    heads = {commits[c] for c in channels}
    if len(heads) != 1:
        raise Refused("sending both channels needs one commit for both")
    with tempfile.TemporaryDirectory() as tmp:   # the release files are their commits' files
        run, strategy = Path(tmp) / "run.py", Path(tmp) / "strategy"
        run.write_bytes(git(args.repo, "show", f"{commits['plumbing']}:factory/run.py", text=False))
        strategy.write_bytes(git(args.repo, "show", f"{commits['bench']}:bin/strategy", text=False))
        pair = subprocess.run([sys.executable, "-B", str(CHECK_PAIR), "--repo", str(args.repo), "--base", args.base,
                               "--head", heads.pop(), *(f"--send={c}" for c in channels),
                               "--plumbing-source", str(run), "--bench-source", str(strategy)])
    if pair.returncode:
        raise Refused("bin/check-release-pair.py refused this pair")
    drained(args)
    sent = {}
    with tempfile.TemporaryDirectory() as tmp:
        for channel in channels:
            payload = Path(tmp) / f"{channel}.json"
            private_json(payload, {channel + "_version": versions[channel]})
            for batch in args.batch:
                unbug(args, channel + "_release", batch, str(payload))
                sent.setdefault(channel, []).append(batch)
                print(f"sent {channel} {versions[channel]} to {batch}", file=sys.stderr)
    return sent


def switch(args, boat=None):
    """Point the controller at a built plumbing tree. Prints root commands; runs none."""
    plumbing = recorded(args, "plumbing", args.plumbing)
    drained(args)
    q = shlex.quote
    print("# drained now; run as root, then confirm with `unbug status`:")
    print(f"sudo ln -sfn {q(plumbing['source'])} {q(str(args.source_current))}")
    for unit in args.unit:
        print(f"sudo systemctl restart {q(unit)}")


def main(argv=None, boat=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=REPO, help="git checkout holding the commits")
    parser.add_argument("--work", type=Path, default=Path.home() / ".unbug-release", help="resumable step records")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("bake-bench", help="bake, snapshot and test a bench image")
    p.add_argument("commit")
    p.add_argument("--from-image", required=True, help="the image to start from (never overwritten)")
    p.add_argument("--no-image-build", dest="image_build", action="store_false",
                   help="test without building unbug-bench-medusa (IMAGE_SCRIPT, ~15 min)")
    sub.add_parser("build-plumbing", help="build the plumbing bundle").add_argument("commit")
    for name in ("register", "send", "switch"):
        p = sub.add_parser(name)
        p.add_argument("--config", type=Path, required=True, help="the controller's config.json")
        p.add_argument("--plumbing", required=True, help="commit built by build-plumbing")
        p.add_argument("--unbug", default=f"{shlex.quote(sys.executable)} -B {shlex.quote(str(REPO / 'bin/unbug'))}")
        p.add_argument("--router-db", type=Path, help="passed to check-drained.py")
        if name != "switch":
            p.add_argument("--bench", required=True, help="commit baked by bake-bench")
            p.add_argument("--allow-unbuilt", action="store_true",
                           help="accept a bench tested with --no-image-build")
    p = sub.choices["send"]
    p.add_argument("--batch", action="append", required=True)
    p.add_argument("--base", required=True, help="the commit the batch runs now, for check-release-pair")
    p.add_argument("--channel", action="append", choices=("plumbing", "bench"), required=True)
    p = sub.choices["switch"]
    p.add_argument("--source-current", type=Path, required=True, help="the controller's source-current symlink")
    p.add_argument("--unit", action="append", default=None, help="systemd unit to restart (repeatable)")
    args = parser.parse_args(argv)
    if args.command == "switch" and not args.unit:
        args.unit = ["unbug-durable-case-campaign.service"]
    command = {"bake-bench": bake_bench, "build-plumbing": build_plumbing, "register": register,
               "send": send, "switch": switch}[args.command]
    try:
        result = command(args, boat or (boat_cli() if args.command == "bake-bench" else None))
    except (Refused, subprocess.CalledProcessError) as error:
        print("release refused: " + str(error), file=sys.stderr)
        return 1
    if result is not None:
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
