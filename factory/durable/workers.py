"""WP2: the worker pool, the release store and the Boat CLI wrapper (control VM only).

Design: docs/designs/durable-execution-wp2.md. Takes over the provisioning half of
factory/launch.sh (bundle upload and checksum, CLI pins, Medusa image, worker release
qualification, bench fingerprint, launch.sh:685-707) and Boat creation and deletion,
under idempotency labels and a per-case journal so a lost response or a control-VM
restart never leaves a duplicate or a forgotten worker.

Release command:
  python3 -B factory/durable/workers.py release --root <tree> --store <dir>
  python3 -B factory/durable/workers.py bench --store <dir> --bench-version <sha> --image <name>
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

_FACTORY = Path(__file__).resolve().parents[1]
if str(_FACTORY) not in sys.path:
    sys.path.insert(0, str(_FACTORY))

from durable.contract import (CASE_ID, DIGEST, REASON, RELEASE_MANIFEST, RELEASE_ROOT, WORKER_COMMAND,  # noqa: E402
                              WORKER_ID, ContractError, WorkerLease, _check, _id)

REPO = _FACTORY.parent
BOAT_CALL = REPO / "bin/boat-call"
MANIFEST_NAME = "worker-release-manifest.json"
FACTORY_MANIFEST_NAME = "worker-release-manifest.factory.json"
WORKER_SCRIPT = WORKER_COMMAND[-1]                  # factory/durable/worker_step.py
RELEASES = "releases"                               # ~/releases/<plumbing_version>/
LABEL_POOL, LABEL_CASE, LABEL_INTENT = "unbug-durable/pool", "unbug-durable/case", "unbug-durable/intent"
LIVE_STATES = frozenset({"init", "provisioning", "provisioned", "cloning", "ready", "idle", "running"})
DEAD_STATES = frozenset({"archived", "stopped", "deleted", "failed", "error"})
DELETE_PENDING = "pending"
BOAT_ID = re.compile(r"bx_[a-z0-9]{8}")
POOL_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
NONCE = re.compile(r"[0-9a-f]{32}")
assert RELEASE_MANIFEST == RELEASE_ROOT + "/RELEASE.json"

# launch.sh's CLI pin, verbatim: fork hydration can replace the baked CLIs.
PIN_SCRIPT = """set -eu
export OPENCODE_DISABLE_AUTOUPDATE=1
cli=/usr/local/bin/opencode
if [ ! -x "$cli" ] || [ "$("$cli" --version)" != 1.19.0 ]; then
  sudo env OPENCODE_DISABLE_AUTOUPDATE=1 npm install -g --force --prefix /usr/local --no-audit --no-fund opencode-ai@1.19.0
fi
[ "$("$cli" --version)" = 1.19.0 ]
codex_cli=/usr/local/bin/codex
if [ ! -x "$codex_cli" ] || [ "$("$codex_cli" --version)" != 'codex-cli 0.162.1' ]; then
  sudo npm install -g --force --prefix /usr/local --no-audit --no-fund @openai/codex@0.162.1
fi
[ "$("$codex_cli" --version)" = 'codex-cli 0.162.1' ]
"""
# launch.sh: fresh images may lack Medusa; build before qualification.
IMAGE_SCRIPT = ("cd ~/unbug-bench; docker image inspect unbug-bench-medusa:latest >/dev/null 2>&1 || "
                "{ docker compose -f projects/medusa/compose.yaml pull postgres redis && "
                "docker compose -f projects/medusa/compose.yaml build medusa; }")
# launch.sh's read-only qualification, on the factory-only manifest (the bench is checked whole below).
QUALIFY_SCRIPT = ("OPENCODE_DISABLE_AUTOUPDATE=1 python3 -B ~/{release}/factory/worker_release.py "
                  "--manifest ~/{release}/" + FACTORY_MANIFEST_NAME + " --root ~/unbug-bench "
                  "--factory-root ~/{release}/factory --drivers opencode,codex")
DEFAULT_STEPS = {"pin": (PIN_SCRIPT, 300.0), "image": (IMAGE_SCRIPT, 1800.0), "qualify": (QUALIFY_SCRIPT, 120.0)}


class PoolError(RuntimeError):
    """A pool failure. Carries only a reason from the contract grammar ("infra:<code>")."""
    def __init__(self, reason: str):
        _check(type(reason) is str and REASON.fullmatch(reason) is not None and reason.startswith("infra:"),
               "pool reasons are infra:<code>")
        super().__init__(reason)
        self.reason = reason


class ReleaseError(ValueError):
    pass


# ---- Boat CLI --------------------------------------------------------------------------------

def lease_worker_id(boat_id: str) -> str:
    """WorkerLease ids are [a-z0-9-]; Boat ids are bx_xxxxxxxx and never hold '-'."""
    _check(type(boat_id) is str and BOAT_ID.fullmatch(boat_id) is not None, "bad provider id")
    return _id(boat_id.replace("_", "-"), WORKER_ID, "worker_id")


def boat_id(worker_id: str) -> str:
    _id(worker_id, WORKER_ID, "worker_id")
    return "bx_" + worker_id[3:] if re.fullmatch(r"bx-[a-z0-9]{8}", worker_id) else worker_id


class BoatCli:
    """Runs bin/boat-call (pinned Boat, BOAT_CMD override). Never raises on provider failure:
    returns (exit status, stdout bytes). stderr is dropped, since a worker command's stderr
    could hold case content."""

    def __init__(self, boat_call: Path = BOAT_CALL, env: dict | None = None):
        self.boat_call = Path(boat_call)
        base = dict(os.environ if env is None else env)
        base.pop("UNBUG_LAUNCH_STATE", None)   # the old launcher's command fence is not ours
        base.pop("BOAT_CAPTURE_OUTPUT", None)
        self.env = base

    def run(self, args, *, stdin: bytes | None = None, timeout: float = 120.0) -> tuple[int, bytes]:
        cmd = [sys.executable, "-B", str(self.boat_call)] + (["--stdin"] if stdin is not None else []) + list(args)
        env = {**self.env, "BOAT_COMMAND_TIMEOUT_SECONDS": str(max(1, int(timeout)))}
        try:
            p = subprocess.run(cmd, input=stdin if stdin is not None else b"", stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, env=env, timeout=timeout + 90)
        except (OSError, subprocess.SubprocessError):
            return 124, b""
        return p.returncode, p.stdout

    def ssh(self, worker: str, command: str, *, stdin: bytes | None = None, timeout: float = 120.0):
        return self.run(["ssh", worker, command], stdin=stdin, timeout=timeout)


def _json(raw: bytes):
    import boat_lifecycle
    return boat_lifecycle.loads(raw.decode("utf-8"))


# ---- release store ---------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(path: Path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _first_wins(path: Path, data: bytes) -> bool:
    """Write data at path once: temp file, fsync, link(). False if path already existed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        _fsync_dir(path.parent)
        return True
    finally:
        os.unlink(tmp)


def _atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _release_files(root: Path) -> list[str]:
    from launch_manifest import worker_files
    names = [n for n in worker_files(root) if n.startswith("factory/")]
    names += [p.relative_to(root).as_posix() for p in sorted((root / "factory/durable").glob("*.py"))
              if not p.name.startswith("test_")]
    return sorted(set(names))


def build_bundle(root) -> bytes:
    """Today's worker bundle (launch_manifest.worker_upload's factory files) plus
    factory/durable/*.py, with the manifest stamped as worker_release.stamp does plus the
    durable files. Deterministic: same tree, same bytes."""
    import worker_release
    root = Path(root)
    names = _release_files(root)
    policy = json.loads((root / "factory/worker-release.json").read_text())
    files = worker_release.source_files(root)
    for name in names:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ReleaseError("missing or symlink release source: " + name)
        files[name] = _sha(path.read_bytes())
    policy["files"] = dict(sorted(files.items()))
    members = [(n, (root / n).read_bytes(), os.access(root / n, os.X_OK)) for n in names]
    members.append((MANIFEST_NAME, (json.dumps(policy, indent=2, sort_keys=True) + "\n").encode(), False))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, filename="") as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.GNU_FORMAT) as tar:
            for name, data, executable in sorted(members):
                info = tarfile.TarInfo(name)
                info.size, info.mtime, info.mode = len(data), 0, 0o755 if executable else 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def check_bundle(data: bytes) -> dict:
    """Refuse a bundle that the worker side could not run or that disagrees with its manifest."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = {}
            for m in tar.getmembers():
                parts = Path(m.name).parts
                if not m.isfile() or not parts or m.name.startswith("/") or ".." in parts:
                    raise ReleaseError("unsafe bundle member")
                if m.name in members:
                    raise ReleaseError("duplicate bundle member")
                members[m.name] = tar.extractfile(m).read()
    except (tarfile.TarError, OSError, EOFError) as error:
        raise ReleaseError("unreadable bundle") from error
    if MANIFEST_NAME not in members or WORKER_SCRIPT not in members:
        raise ReleaseError("bundle lacks its manifest or the worker command")
    manifest = json.loads(members[MANIFEST_NAME])
    if manifest.get("schema") != 1 or not isinstance(manifest.get("files"), dict):
        raise ReleaseError("bad bundle manifest")
    factory = {k: v for k, v in manifest["files"].items() if k.startswith("factory/")}
    shipped = {k for k in members if k != MANIFEST_NAME}
    if shipped != set(factory) or any(_sha(members[k]) != v for k, v in factory.items()):
        raise ReleaseError("bundle members disagree with the manifest")
    return manifest


class ReleaseStore:
    """Each factory bundle once, keyed by its sha256 (bundles/<sha>.tgz), and which image
    serves each bench release (benches/<bench_version>.json). First-wins on both."""

    def __init__(self, root):
        self.root = Path(root)

    def _bundle_path(self, plumbing_version: str) -> Path:
        _id(plumbing_version, DIGEST, "plumbing_version")
        return self.root / "bundles" / (plumbing_version + ".tgz")

    def put_bundle(self, data: bytes) -> str:
        check_bundle(data)
        digest = _sha(data)
        path = self._bundle_path(digest)
        if not _first_wins(path, data):
            self.bundle(digest)   # an existing copy must still be intact
        return digest

    def has_bundle(self, plumbing_version: str) -> bool:
        return self._bundle_path(plumbing_version).is_file()

    def bundle(self, plumbing_version: str) -> bytes:
        data = self._bundle_path(plumbing_version).read_bytes()
        if _sha(data) != plumbing_version:
            raise ReleaseError("stored bundle does not match its digest")
        return data

    def register_bench(self, bench_version: str, image: str):
        _id(bench_version, DIGEST, "bench_version")
        _check(type(image) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", image) is not None,
               "bad image name")
        path = self.root / "benches" / (bench_version + ".json")
        if not _first_wins(path, json.dumps({"image": image}, sort_keys=True).encode()):
            if json.loads(path.read_text()) != {"image": image}:
                raise ReleaseError("bench release already registered with another image")

    def image_for(self, bench_version: str, default: str) -> str:
        path = self.root / "benches" / (_id(bench_version, DIGEST, "bench_version") + ".json")
        return json.loads(path.read_text())["image"] if path.is_file() else default


# ---- the pool --------------------------------------------------------------------------------

class BoatPool:
    """WorkerPool on Boat. One worker per case, created under three labels and a per-case
    journal record {"intent": nonce, "worker": id|null, "deleting": op|null}."""

    def __init__(self, state_dir, store: ReleaseStore, pool_id: str, *, boat: BoatCli | None = None,
                 image: str = "bench-env", vm_type: str | None = None, ttl_seconds: int = 259_200,
                 steps: dict | None = None, ready_timeout: float = 600.0, poll_interval: float = 5.0,
                 delete_timeout: float = 300.0, new_timeout: float = 300.0):
        _check(type(pool_id) is str and POOL_ID.fullmatch(pool_id) is not None, "bad pool id")
        _check(type(ttl_seconds) is int and 1 <= ttl_seconds <= 2_592_000, "bad ttl")
        self.state = Path(state_dir)
        self.state.mkdir(parents=True, exist_ok=True)
        self.store, self.pool_id, self.boat = store, pool_id, boat or BoatCli()
        self.image, self.vm_type, self.ttl = image, vm_type, ttl_seconds
        self.steps = {**DEFAULT_STEPS, **(steps or {})}
        self.ready_timeout, self.poll_interval = ready_timeout, poll_interval
        self.delete_timeout, self.new_timeout = delete_timeout, new_timeout

    # -- journal

    def _record_path(self, case_id: str) -> Path:
        return self.state / (_id(case_id, CASE_ID, "case_id") + ".json")

    def _read(self, case_id: str) -> dict | None:
        try:
            record = json.loads(self._record_path(case_id).read_text())
        except FileNotFoundError:
            return None
        _check(isinstance(record, dict) and set(record) == {"intent", "worker", "deleting"}, "bad pool record")
        return record

    def _write(self, case_id: str, record: dict):
        _atomic_json(self._record_path(case_id), record)

    def _records(self) -> dict:
        out = {}
        for path in sorted(self.state.glob("case-*.json")):
            out[path.stem] = self._read(path.stem)
        return out

    @contextlib.contextmanager
    def _lock(self, case_id: str):
        fd = os.open(self.state / (_id(case_id, CASE_ID, "case_id") + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    # -- inventory

    def _inventory(self) -> list[dict]:
        """Every sandbox, from one complete `boat list --json`, or PoolError."""
        code, out = self.boat.run(["list", "--json"], timeout=120)
        try:
            data = _json(out) if code == 0 else None
            rows = data["sandboxes"]
            complete = data["pageInfo"]["hasMore"] is False
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            raise PoolError("infra:inventory_unavailable") from None
        if (not complete or not isinstance(rows, list)
                or not all(isinstance(r, dict) and isinstance(r.get("id"), str)
                           and BOAT_ID.fullmatch(r["id"]) for r in rows)
                or len({r["id"] for r in rows}) != len(rows)):
            raise PoolError("infra:inventory_unavailable")
        return rows

    def _ours(self, row: dict) -> dict | None:
        labels = row.get("labels")
        if not isinstance(labels, dict) or labels.get(LABEL_POOL) != self.pool_id:
            return None
        return labels

    @staticmethod
    def _live(row: dict) -> bool:
        return row.get("state") in LIVE_STATES

    def _find(self, rows, case_id, *, worker=None, intent=None):
        for row in rows:
            if worker is not None and row.get("id") == worker:
                labels = self._ours(row)
                if labels is None or labels.get(LABEL_CASE) != case_id or row.get("state") not in LIVE_STATES | DEAD_STATES:
                    raise PoolError("infra:inventory_unavailable")
            labels = self._ours(row)
            if (labels is None or labels.get(LABEL_CASE) != case_id or not self._live(row)
                    or not isinstance(row.get("id"), str)):
                continue
            if (worker is not None and row["id"] == worker) or (intent is not None and labels.get(LABEL_INTENT) == intent):
                return row["id"]
        return None

    # -- WorkerPool

    def acquire(self, case_id: str, plumbing_version: str, bench_version: str) -> WorkerLease:
        _id(case_id, CASE_ID, "case_id")
        _id(plumbing_version, DIGEST, "plumbing_version")
        _id(bench_version, DIGEST, "bench_version")
        if not self.store.has_bundle(plumbing_version):
            raise PoolError("infra:release_missing")
        with self._lock(case_id):
            record = self._read(case_id)
            if record is not None and record["deleting"] is not None:
                self._finish_delete(case_id, record)
                record = None
            worker = None
            if record is not None:
                rows = self._inventory()
                worker = (self._find(rows, case_id, worker=record["worker"]) if record["worker"]
                          else self._find(rows, case_id, intent=record["intent"]))
                if worker is None:
                    if record["worker"] is None and record["intent"] is not None:
                        # An empty list response cannot prove that an earlier create
                        # request will not appear later. Keep its original identity.
                        raise PoolError("infra:worker_create_unknown")
                    if record["worker"] is not None and any(r.get("id") == record["worker"] for r in rows):
                        self._delete_locked(case_id, record["worker"])
                    self._write(case_id, {"intent": None, "worker": None, "deleting": None})
                elif record["worker"] != worker:
                    self._write(case_id, {**record, "worker": worker})
            if worker is not None:
                installed = self._installed(worker)
                if installed == {"plumbing_version": plumbing_version, "bench_version": bench_version}:
                    return WorkerLease(lease_worker_id(worker), case_id)
                if installed is not None and installed["bench_version"] != bench_version:
                    # The bench comes from the image: this worker can never serve it.
                    self._delete_locked(case_id, worker)
                    worker = None
            fresh = worker is None
            if fresh:
                worker = self._create(case_id, bench_version)
            try:
                if fresh:
                    self._wait_ready(worker)
                self._install(worker, plumbing_version, bench_version)
            except PoolError as error:
                if fresh or error.reason == "infra:bench_mismatch":
                    with contextlib.suppress(PoolError):
                        self._delete_locked(case_id, worker)
                raise
            return WorkerLease(lease_worker_id(worker), case_id)

    def release(self, lease: WorkerLease) -> None:
        with self._lock(lease.case_id):
            record = self._read(lease.case_id)
            if record is None:
                return
            worker = boat_id(lease.worker_id)
            if record["deleting"] is not None:
                self._finish_delete(lease.case_id, record)
            elif record["worker"] in (worker, None):
                self._delete_locked(lease.case_id, worker)

    def alive(self, lease: WorkerLease) -> bool:
        try:
            record = self._read(lease.case_id)
            if record is None or record["worker"] != boat_id(lease.worker_id):
                return False
            return self._find(self._inventory(), lease.case_id, worker=record["worker"]) is not None
        except (PoolError, ContractError, OSError, ValueError):
            return True   # unknown is never dead (a transport failure is RUNNING)

    def recover(self) -> dict:
        """On engine start: adopt pool-labelled workers a record names (by id or intent),
        delete every other pool-labelled worker, drop records whose worker is gone. Nothing
        is deleted unless the inventory is complete. Workers of other pools are untouched."""
        for path in self.state.glob("deletions/*/intent.json"):
            if not (path.parent / "deletion-completion.json").exists():
                self._delete_raw(path.parent.name)
        rows = self._inventory()
        adopted, deleted = [], []
        records = self._records()
        claimed = set()
        for case_id, record in records.items():
            with self._lock(case_id):
                record = self._read(case_id)
                if record is None:
                    continue
                if record["deleting"] is not None:
                    self._finish_delete(case_id, record)
                    continue
                worker = (self._find(rows, case_id, worker=record["worker"]) if record["worker"]
                          else self._find(rows, case_id, intent=record["intent"]) if record["intent"] else None)
                if worker is None:
                    if record["worker"] is None and record["intent"] is not None:
                        continue  # Keep ownership of an unresolved create across restarts.
                    if record["worker"] is not None and any(r.get("id") == record["worker"] for r in rows):
                        self._delete_locked(case_id, record["worker"])
                        deleted.append(record["worker"])
                    self._record_path(case_id).unlink(missing_ok=True)
                    continue
                claimed.add(worker)
                adopted.append(worker)
                if record["worker"] != worker:
                    self._write(case_id, {**record, "worker": worker})
        for row in rows:
            labels = self._ours(row)
            if labels is None or row.get("id") in claimed or not isinstance(row.get("id"), str):
                continue
            case_id = labels.get(LABEL_CASE)
            if type(case_id) is str and CASE_ID.fullmatch(case_id):
                with self._lock(case_id):
                    current = self._read(case_id)
                    if current is not None and (row["id"] == current["worker"] or (
                            current["worker"] is None and current["intent"] == labels.get(LABEL_INTENT))):
                        continue
                    self._delete_raw(row["id"])
                    deleted.append(row["id"])
            else:
                self._delete_raw(row["id"])
                deleted.append(row["id"])
        return {"adopted": sorted(adopted), "deleted": sorted(deleted)}

    # -- creation

    def _create(self, case_id: str, bench_version: str) -> str:
        nonce = uuid.uuid4().hex
        # Write uncertainty before the provider can see a request.
        self._write(case_id, {"intent": nonce, "worker": None, "deleting": None})
        args = ["new", "--from", self.store.image_for(bench_version, self.image), "--no-env", "--no-monitoring",
                "--no-snapshots", "--ttl", str(self.ttl)]
        if self.vm_type:
            args += ["--type", self.vm_type]
        for key, value in ((LABEL_POOL, self.pool_id), (LABEL_CASE, case_id), (LABEL_INTENT, nonce)):
            args += ["--label", f"{key}={value}"]
        code, out = self.boat.run(args + ["--json"], timeout=self.new_timeout)
        worker = None
        for line in out.decode("utf-8", "replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if (isinstance(event, dict) and event.get("event") == "created" and isinstance(event.get("id"), str)
                    and re.fullmatch(r"[A-Za-z0-9_-]+", event["id"])):
                worker = event["id"]
                break
        if worker is None:
            # A lost response may still have created it: adopt by the intent label.
            worker = self._find(self._inventory(), case_id, intent=nonce)
            if worker is None:
                raise PoolError("infra:worker_create_failed" if code not in (0, 124) else "infra:worker_create_unknown")
        lease_worker_id(worker)
        # A non-zero exit that still names a worker: it exists and the record owns it.
        self._write(case_id, {"intent": nonce, "worker": worker, "deleting": None})
        return worker

    def _wait_ready(self, worker: str):
        deadline = time.monotonic() + self.ready_timeout
        while True:
            code, _ = self.boat.ssh(worker, "true", timeout=60)
            if code == 0:
                return
            if time.monotonic() >= deadline:
                raise PoolError("infra:worker_unreachable")
            time.sleep(self.poll_interval)

    # -- install and verify (launch.sh:685-707)

    def _installed(self, worker: str) -> dict | None:
        code, out = self.boat.ssh(worker, "cat ~/" + RELEASE_MANIFEST + " 2>/dev/null || true", timeout=60)
        if code != 0:
            raise PoolError("infra:worker_unreachable")
        if not out.strip():
            return None
        try:
            value = json.loads(out)
        except ValueError:
            return None
        if (not isinstance(value, dict) or set(value) != {"plumbing_version", "bench_version"}
                or not all(isinstance(v, str) and DIGEST.fullmatch(v) for v in value.values())):
            return None
        return value

    def _step(self, worker, name, script, timeout, *, stdin=None, retry=False):
        for attempt in range(2 if retry else 1):
            code, out = self.boat.ssh(worker, script, stdin=stdin, timeout=timeout)
            if code == 0:
                return out
            if attempt == 0 and retry:
                time.sleep(1)
        raise PoolError(f"infra:{name}")

    def _install(self, worker: str, p: str, b: str):
        data = self.store.bundle(p)
        rel = f"{RELEASES}/{p}"
        q = shlex.quote
        upload = (f"set -eu; umask 077; mkdir -p ~/{RELEASES}; t=~/{rel}.tgz.part; cat > \"$t\"; "
                  f"printf '%s  %s\\n' {p} \"$t\" | sha256sum -c - >/dev/null; mv \"$t\" ~/{rel}.tgz")
        self._step(worker, "release_upload_failed", upload, max(300.0, len(data) / 262_144), stdin=data)
        filter_manifest = ("import json,sys; d=sys.argv[1]; m=json.load(open(d+'/" + MANIFEST_NAME + "')); "
                           "m['files']={k:v for k,v in m['files'].items() if k.startswith('factory/')}; "
                           "json.dump(m,open(d+'/" + FACTORY_MANIFEST_NAME + "','w'),sort_keys=True)")
        unpack = (f"set -eu; umask 077; cd ~/{RELEASES}; "
                  f"[ \"$(readlink ~/{RELEASE_ROOT} 2>/dev/null || true)\" != {rel} ] || exit 3; "
                  f"rm -rf {p}.x {p}; mkdir {p}.x; tar -xzf {p}.tgz -C {p}.x; "
                  f"python3 -B -c {q(filter_manifest)} {p}.x; mv {p}.x {p}; rm -f {p}.tgz")
        self._step(worker, "release_unpack_failed", unpack, 300)
        script, timeout = self.steps["pin"]
        self._step(worker, "cli_pin_failed", script, timeout, retry=True)
        script, timeout = self.steps["image"]
        self._step(worker, "image_prepare_failed", script, timeout)
        script, timeout = self.steps["qualify"]
        self._step(worker, "release_qualify_failed", script.format(release=rel), timeout, retry=True)
        fingerprint = (f"cd ~/{rel}/factory && env -u BENCH OPENCODE_DISABLE_AUTOUPDATE=1 "
                       "python3 -B -c 'import run; print(run.bench_manifest())'")
        out = self._step(worker, "bench_fingerprint_failed", fingerprint, 600).decode("utf-8", "replace").strip()
        if out != b:
            raise PoolError("infra:bench_mismatch" if DIGEST.fullmatch(out) else "infra:bench_fingerprint_failed")
        manifest = json.dumps({"plumbing_version": p, "bench_version": b}, sort_keys=True)
        swap = q(f"import os; os.replace(os.path.expanduser('~/.{RELEASE_ROOT}.tmp'), "
                 f"os.path.expanduser('~/{RELEASE_ROOT}'))")
        commit = (f"set -eu; umask 077; d=~/{rel}; printf '%s' {q(manifest)} > \"$d/RELEASE.json.tmp\"; "
                  f"mv \"$d/RELEASE.json.tmp\" \"$d/RELEASE.json\"; "
                  f"if [ -e ~/{RELEASE_ROOT} ] && [ ! -L ~/{RELEASE_ROOT} ]; then exit 3; fi; "
                  f"ln -sfn {rel} ~/.{RELEASE_ROOT}.tmp; python3 -B -c {swap}")
        self._step(worker, "release_commit_failed", commit, 60)

    # -- deletion

    def _delete_locked(self, case_id: str, worker: str):
        record = self._read(case_id) or {"intent": None, "worker": worker, "deleting": None}
        record = {**record, "worker": worker, "deleting": DELETE_PENDING}
        self._write(case_id, record)
        self._finish_delete(case_id, record)

    def _finish_delete(self, case_id: str, record: dict):
        worker = record["worker"]
        if record["deleting"] != DELETE_PENDING:
            self._await_delete(worker, record["deleting"])
        else:
            self._delete_raw(worker)
        self._record_path(case_id).unlink(missing_ok=True)

    def _delete_raw(self, worker: str):
        self._receipt(worker, "intent.json", {"worker": worker})
        receipt = self.state / "deletions" / worker / "deletion-request.json"
        if receipt.exists():
            try:
                operation = json.loads(receipt.read_text())
                op = self._operation(json.dumps({"operation": operation}).encode(), worker)["id"]
            except (OSError, ValueError, KeyError, TypeError):
                raise PoolError("infra:worker_delete_unconfirmed") from None
        else:
            op = self._request_delete(worker)
        if op is not None:
            self._await_delete(worker, op)
        else:
            self._receipt(worker, "deletion-completion.json", {"worker": worker, "absent": True})

    def _receipt(self, worker: str, name: str, value):
        _atomic_json(self.state / "deletions" / worker / name, value)

    @staticmethod
    def _operation(raw: bytes, worker: str, op_id: str | None = None) -> dict:
        operation = _json(raw)["operation"]
        if (not isinstance(operation, dict) or not isinstance(operation.get("id"), str) or not operation["id"]
                or operation.get("targetId") != worker or operation.get("kind") != "sandbox"
                or (op_id is not None and operation["id"] != op_id)):
            raise ValueError("operation identity mismatch")
        return {k: operation.get(k) for k in ("id", "targetId", "kind", "status", "stage", "completedAt")}

    def _request_delete(self, worker: str) -> str | None:
        """Returns the deletion operation id, or None when the worker is already gone."""
        code, out = self.boat.run(["delete", worker, "--yes", "--json"], timeout=120)
        try:
            if code != 0:
                raise ValueError("delete refused")
            operation = self._operation(out, worker)
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            if not any(r.get("id") == worker for r in self._inventory()):
                return None
            raise PoolError("infra:worker_delete_failed") from None
        self._receipt(worker, "deletion-request.json", operation)
        return operation["id"]

    def _await_delete(self, worker: str, op_id: str):
        import boat_lifecycle
        deadline = time.monotonic() + self.delete_timeout
        while True:
            code, out = self.boat.run(["deletion", "status", op_id, "--json"], timeout=60)
            try:
                operation = self._operation(out, worker, op_id) if code == 0 else None
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                operation = None
            if operation is not None and operation["status"] == "completed":
                try:
                    boat_lifecycle.completion(operation, worker, op_id)
                except ValueError:
                    raise PoolError("infra:worker_delete_failed") from None
                self._receipt(worker, "deletion-completion.json", operation)
                return
            if operation is not None and (operation["status"] not in ("pending", "processing")
                                          or operation["completedAt"] is not None):
                raise PoolError("infra:worker_delete_failed")
            if time.monotonic() >= deadline:
                raise PoolError("infra:worker_delete_unconfirmed")
            time.sleep(self.poll_interval)


# ---- release command -------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rel = sub.add_parser("release", help="build a bundle from a tree and store it; prints plumbing_version")
    rel.add_argument("--root", type=Path, required=True)
    rel.add_argument("--store", type=Path, required=True)
    bench = sub.add_parser("bench", help="register the image that serves a bench release")
    bench.add_argument("--store", type=Path, required=True)
    bench.add_argument("--bench-version", required=True)
    bench.add_argument("--image", required=True)
    args = parser.parse_args(argv)
    store = ReleaseStore(args.store)
    try:
        if args.command == "release":
            print(store.put_bundle(build_bundle(args.root.resolve())))
        else:
            store.register_bench(args.bench_version, args.image)
    except (ReleaseError, ContractError, OSError, ValueError) as error:
        print("release refused: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
