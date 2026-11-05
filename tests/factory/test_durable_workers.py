"""WP2 worker pool and release store (docs/designs/durable-execution-wp2.md).

Provider answers are real saved Boat CLI outputs (tests/factory/fixtures): the `created`
event (isolation-timeouts/created.json), the inventory envelope (isolation-timeouts/
list.json), inventory row fields from the saved readiness observation, and the saved
deletion request and completion operations (isolation-settlement-cloud/). Real worker ids
come from the saved fixtures. The row `labels` field is the documented one in the saved
provider contract (docs/reports/stream-b-provider-contract-20261031/create.md); no live
capture of a labelled row exists. `boat ssh` runs the command locally with HOME set to one
directory per worker. The CLI pin, Medusa image and worker_release.py qualification steps
need /usr/local/bin, Docker and a bench image, so they run as stand-ins here.
"""
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin")]
os.environ.setdefault("BENCH", str(ROOT))

from durable.contract import RELEASE_MANIFEST, WORKER_ID, WorkerLease   # noqa: E402
from durable import workers as W   # noqa: E402

FIXTURES = ROOT / "tests/factory/fixtures"
CREATED = FIXTURES / "isolation-timeouts/created.json"
LIST = FIXTURES / "isolation-timeouts/list.json"
READINESS = FIXTURES / "isolation-settlement-cloud/20261029T095210Z-99393-factory-bx_d6dzvjbc.readiness.json"
DELETE_REQUEST = FIXTURES / "isolation-settlement-cloud/deletion-request.json"
DELETE_DONE = FIXTURES / "isolation-settlement-cloud/deletion-completion.json"
WORKER_RELEASE = FIXTURES / "isolation-timeouts/worker-release.json"
# Real Boat sandbox ids from the saved fixtures and decision records.
REAL_IDS = ["bx_d6dzvjbc", "bx_sk2p68qq", "bx_z4wktrbn", "bx_bykfqbyn"]

FAKE_BOAT = r'''#!/usr/bin/env python3
"""Stand-in Boat CLI: answers from the saved real outputs; ssh runs locally per worker home."""
import json, os, pathlib, shutil, subprocess, sys, time
base = pathlib.Path(os.environ["FAKE_BOAT"]); fx = json.loads(os.environ["FAKE_BOAT_FIXTURES"])
args = sys.argv[1:]
stdin = sys.stdin.buffer.read()
flags = json.loads((base / "flags.json").read_text()) if (base / "flags.json").exists() else {}
with (base / "calls.jsonl").open("a") as log:
    log.write(json.dumps({"args": args, "stdin_bytes": len(stdin)}) + "\n")
def load(name, default):
    p = base / name
    return json.loads(p.read_text()) if p.exists() else default
def save(name, value):
    (base / name).write_text(json.dumps(value))
def fixture(name):
    return json.loads(pathlib.Path(fx[name]).read_text())
rows = load("inventory.json", [])
if args[0] == "new":
    if "new-fail" in flags: sys.exit(1)
    ids = load("ids.json", []); wid = ids.pop(0); save("ids.json", ids)
    labels = dict(args[i + 1].split("=", 1) for i, a in enumerate(args) if a == "--label")
    image = args[args.index("--from") + 1]; ttl = int(args[args.index("--ttl") + 1])
    observed = fixture("readiness")["observed"]
    rows.append({**observed, "id": wid, "ttlSeconds": ttl, "labels": labels}); save("inventory.json", rows)
    images = load("images.json", {}); images[wid] = image; save("images.json", images)
    shutil.copytree(base / "images" / image, base / "homes" / wid, symlinks=True)
    if "new-lost" in flags: sys.exit(124)
    event = fixture("created"); event["id"] = wid; event["ttlSeconds"] = ttl
    print(json.dumps(event))
    sys.exit(1 if "new-exit-1" in flags else 0)
if args[0] == "list":
    if "list-fail" in flags: sys.exit(1)
    envelope = fixture("list"); envelope["sandboxes"] = rows
    if "list-more" in flags: envelope["pageInfo"]["hasMore"] = True
    print(json.dumps(envelope)); sys.exit(0)
if args[0] == "delete":
    wid = args[1]
    if "delete-fail" in flags or not any(r["id"] == wid for r in rows):
        print('{"error":{"code":"not_found","status":404}}', file=sys.stderr); sys.exit(1)
    save("inventory.json", [r for r in rows if r["id"] != wid])
    shutil.rmtree(base / "homes" / wid, ignore_errors=True)
    op = fixture("delete_request"); op["targetId"] = wid
    ops = load("ops.json", {}); ops[op["id"]] = wid; save("ops.json", ops)
    print(json.dumps({"operation": op})); sys.exit(0)
if args[:2] == ["deletion", "status"]:
    wid = load("ops.json", {})[args[2]]
    op = fixture("delete_request" if "deletion-pending" in flags else "delete_done"); op["targetId"] = wid
    print(json.dumps({"operation": op})); sys.exit(0)
if args[0] == "ssh":
    wid, cmd = args[1], args[2]
    if not any(r["id"] == wid and r["state"] == "idle" for r in rows): sys.exit(255)
    for name, value in flags.items():
        if name.startswith("ssh-fail") and value in cmd: sys.exit(255)
        if name.startswith("ssh-exit") and value in cmd: sys.exit(3)
        if name.startswith("ssh-garbage") and value in cmd: print("not json"); sys.exit(0)
        if name.startswith("ssh-extra") and value in cmd:
            r = subprocess.run(["sh", "-c", cmd], input=stdin, capture_output=True, cwd=base / "homes" / wid,
                               env={"HOME": str(base / "homes" / wid), "PATH": os.environ["PATH"]})
            sys.stdout.buffer.write(r.stdout + r.stdout); sys.exit(r.returncode)
        if name.startswith("ssh-hang") and value in cmd: time.sleep(60)
        if name.startswith("ssh-corrupt") and value in cmd and stdin: stdin = stdin[:-1] + bytes([stdin[-1] ^ 1])
        if name.startswith("ssh-truncate") and value in cmd:
            r = subprocess.run(["sh", "-c", cmd], input=stdin, capture_output=True, cwd=base / "homes" / wid,
                               env={"HOME": str(base / "homes" / wid), "PATH": os.environ["PATH"]})
            sys.stdout.buffer.write(r.stdout[:-3]); sys.exit(r.returncode)
    home = base / "homes" / wid
    r = subprocess.run(["sh", "-c", cmd], input=stdin, cwd=home,
                       env={"HOME": str(home), "PATH": os.environ["PATH"], "LANG": "C.UTF-8"})
    sys.exit(r.returncode)
sys.exit(99)
'''

# Written from the contract's RELEASE_MANIFEST docstring and attempt_paths, never from WP5a's code.
STANDIN_WORKER = r'''#!/usr/bin/env python3
"""Test stand-in for the worker side of the wire protocol (contract.py RELEASE_MANIFEST)."""
import base64, fcntl, json, os, pathlib, signal, subprocess, sys, time
FACTORY = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FACTORY))
from durable.contract import (Outcome, Poll, PollState, StepResult, attempt_id, attempt_paths, step_input_from_record,
                              step_result_from_record, to_record)
from durable.channel import blob_name
HOME = pathlib.Path.home()
ROOT = HOME / "durable"

def first_wins(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".%d" % os.getpid())
    tmp.write_text(json.dumps(record))
    try: os.link(tmp, path)
    except FileExistsError: pass
    finally: tmp.unlink()

def unit_live(attempt):
    try: pid = int((attempt / "pid").read_text())
    except (OSError, ValueError): return False
    try:
        state = pathlib.Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()[0]
    except OSError: return False
    return state != "Z"

def live(key):
    p = attempt_paths(key)
    return unit_live(HOME / p["attempt"]) and not (HOME / p["result"]).exists()

verb = sys.argv[1]
if verb == "run":   # the detached unit's body
    key = sys.argv[2]; p = attempt_paths(key); attempt = HOME / p["attempt"]
    plan = json.loads((attempt / "plan.json").read_text())
    time.sleep(plan.get("sleep", 0))
    (HOME / p["out"]).mkdir(parents=True, exist_ok=True)
    for name, data in plan.get("outputs", {}).items():
        (HOME / p["out"] / name).write_bytes(base64.b64decode(data))
    first_wins(HOME / p["result"], plan["result"]); sys.exit(0)
frame = json.loads(sys.stdin.read())
if verb == "start":
    si = step_input_from_record(frame["input"]); key = si.idempotency_key; p = attempt_paths(key)
    for d in ("attempts", "results", "cases/" + si.case_id): (ROOT / d).mkdir(parents=True, exist_ok=True)
    with open(ROOT / "cases" / si.case_id / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try: os.mkdir(HOME / p["attempt"])   # O_EXCL marker; a tombstone or a repeat start does nothing
        except FileExistsError: sys.exit(0)
        others = [json.loads(f.read_text()) for f in (ROOT / "cases" / si.case_id).glob("*.json")]
        (ROOT / "cases" / si.case_id / (attempt_id(key) + ".json")).write_text(json.dumps(key))
        if any(live(k) for k in others):
            first_wins(HOME / p["result"], to_record(StepResult(Outcome.INFRA_ERROR, "infra:attempt_busy"))); sys.exit(0)
        attempt = HOME / p["attempt"]
        installed = json.loads((pathlib.Path.cwd() / "RELEASE.json").read_text())
        plans = json.loads((HOME / "standin-plan.json").read_text()) if (HOME / "standin-plan.json").exists() else {}
        plan = plans.get(key, {"result": to_record(StepResult(Outcome.INFRA_ERROR, "infra:no_plan"))})
        refs = [r for r in (si.inputs, si.snapshot, si.feedback, si.registry, si.ruling, *si.evidence) if r is not None]
        if installed != {"plumbing_version": si.plumbing_version, "bench_version": si.bench_version}:
            plan = {"result": to_record(StepResult(Outcome.INFRA_ERROR, "infra:version_mismatch"))}
        elif any(not (HOME / p["blobs"] / blob_name(r)).is_file() for r in refs):
            plan = {"result": to_record(StepResult(Outcome.INFRA_ERROR, "infra:blob_missing"))}
        (attempt / "keys-seen.json").write_text(json.dumps(sorted(frame["keys"])))
        (attempt / "plan.json").write_text(json.dumps(plan))
        unit = subprocess.Popen([sys.executable, "-B", __file__, "run", key], start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (attempt / "pid").write_text(str(unit.pid))
    sys.exit(0)
key = frame["key"]; p = attempt_paths(key)
if verb == "poll":
    result = HOME / p["result"]
    if result.exists():
        poll = Poll(PollState.DONE, step_result_from_record(json.loads(result.read_text())))
    elif (HOME / p["attempt"]).exists() and unit_live(HOME / p["attempt"]):
        poll = Poll(PollState.RUNNING)
    else:
        poll = Poll(PollState.ABSENT)
    print(json.dumps(to_record(poll))); sys.exit(0)
if verb == "cancel":
    (ROOT / "attempts").mkdir(parents=True, exist_ok=True)
    attempt = HOME / p["attempt"]
    attempt.mkdir(exist_ok=True)   # tombstone
    if live(key):
        os.killpg(int((attempt / "pid").read_text()), signal.SIGKILL)
    first_wins(HOME / p["result"], to_record(StepResult(Outcome.INFRA_ERROR, "infra:cancelled"))); sys.exit(0)
sys.exit(2)
'''

QUALIFY_STANDIN = (
    "python3 -B -c 'import hashlib,json,pathlib,sys; r=pathlib.Path(sys.argv[1]); "
    "m=json.load(open(r/\"worker-release-manifest.factory.json\")); "
    "assert m[\"files\"] and all(k.startswith(\"factory/\") for k in m[\"files\"]); "
    "assert all(hashlib.sha256((r/k).read_bytes()).hexdigest()==v for k,v in m[\"files\"].items())' ~/{release} "
    "&& cat " + str(WORKER_RELEASE))
TEST_STEPS = {"pin": ("true", 30.0), "image": ("true", 30.0), "qualify": (QUALIFY_STANDIN, 60.0)}


def bench_manifest(path):
    import run
    return run.bench_manifest(path)


def release_tree(dest: Path) -> Path:
    """The real worker release file set from this checkout, plus the stand-in worker command."""
    from launch_manifest import worker_files
    for name in worker_files(ROOT) + [p.relative_to(ROOT).as_posix() for p in (ROOT / "factory/durable").glob("*.py")]:
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    (dest / "factory/durable/worker_step.py").write_text(STANDIN_WORKER)
    return dest


class Harness:
    """A stand-in Boat, two baked images, a release store and a pool state directory."""

    def __init__(self, testcase):
        self.tmp = Path(tempfile.mkdtemp(prefix="wp2-"))
        testcase.addCleanup(shutil.rmtree, self.tmp, True)
        testcase.addCleanup(self.reap)
        self.boat_dir = self.tmp / "boat"
        (self.boat_dir / "homes").mkdir(parents=True)
        self.exe = self.tmp / "fake-boat"
        self.exe.write_text(FAKE_BOAT); self.exe.chmod(0o755)
        self.ids(REAL_IDS)
        self.benches = {}
        for image, extra in (("bench-env", "one"), ("bench-env-2", "two")):
            tree = self.boat_dir / "images" / image / "unbug-bench"
            from launch_manifest import WORKER_BENCH
            for name in WORKER_BENCH:   # the real bench files a worker image carries
                (tree / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, tree / name)
            (tree / "README.md").write_text("bench " + extra + "\n")
            (tree / "results").mkdir()
            (tree / "results/ignored.txt").write_text("excluded from the fingerprint\n")
            self.benches[image] = bench_manifest(tree)
        self.env = {**os.environ, "BOAT_CMD": str(self.exe), "FAKE_BOAT": str(self.boat_dir),
                    "FAKE_BOAT_FIXTURES": json.dumps({"created": str(CREATED), "list": str(LIST),
                                                      "readiness": str(READINESS), "delete_request": str(DELETE_REQUEST),
                                                      "delete_done": str(DELETE_DONE)}),
                    "UNBUG_LAUNCH_STATE": str(self.tmp / "must-not-be-used")}
        self.boat = W.BoatCli(env=self.env)
        self.store = W.ReleaseStore(self.tmp / "store")
        self.tree = release_tree(self.tmp / "tree")
        self.plumbing = self.store.put_bundle(W.build_bundle(self.tree))
        self.store.register_bench(self.benches["bench-env-2"], "bench-env-2")

    def reap(self):
        subprocess.run(["pkill", "-KILL", "-f", str(self.boat_dir)], check=False)

    def pool(self, pool_id="wp2-test", **kw):
        return W.BoatPool(self.tmp / ("state-" + pool_id), self.store, pool_id, boat=self.boat, steps=TEST_STEPS,
                          ready_timeout=5, poll_interval=0.05, delete_timeout=5, **kw)

    def ids(self, ids):
        (self.boat_dir / "ids.json").write_text(json.dumps(ids))

    def flag(self, name, value=True):
        path = self.boat_dir / "flags.json"
        flags = json.loads(path.read_text()) if path.exists() else {}
        if value is None:
            flags.pop(name, None)
        else:
            flags[name] = value
        path.write_text(json.dumps(flags))

    def calls(self):
        path = self.boat_dir / "calls.jsonl"
        return [json.loads(l)["args"] for l in path.read_text().splitlines()] if path.exists() else []

    def inventory(self):
        path = self.boat_dir / "inventory.json"
        return json.loads(path.read_text()) if path.exists() else []

    def home(self, worker):
        return self.boat_dir / "homes" / worker

    def add_row(self, worker, labels, image="bench-env"):
        """An inventory row made only of the saved readiness fields, plus labels."""
        rows = self.inventory()
        rows.append({**json.loads(READINESS.read_text())["observed"], "id": worker, "labels": labels})
        (self.boat_dir / "inventory.json").write_text(json.dumps(rows))
        shutil.copytree(self.boat_dir / "images" / image, self.home(worker), symlinks=True)

    def second_plumbing(self):
        (self.tree / "factory/durable/policy.py").write_text((self.tree / "factory/durable/policy.py").read_text()
                                                             + "\n# second release\n")
        return self.store.put_bundle(W.build_bundle(self.tree))


CASE = "case-20261105T000000Z-abc123"


class ReleaseStoreTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(self)

    def test_bundle_is_stored_once_by_sha256_and_rebuilds_identically(self):
        data = self.h.store.bundle(self.h.plumbing)
        self.assertEqual(hashlib.sha256(data).hexdigest(), self.h.plumbing)
        self.assertEqual(W.build_bundle(self.h.tree), data)          # deterministic
        self.assertEqual(self.h.store.put_bundle(data), self.h.plumbing)
        self.assertEqual([p.name for p in (self.h.tmp / "store/bundles").iterdir()], [self.h.plumbing + ".tgz"])

    def test_bundle_carries_the_durable_package_and_its_manifest(self):
        manifest = W.check_bundle(self.h.store.bundle(self.h.plumbing))
        for name in ("factory/durable/worker_step.py", "factory/durable/contract.py", "factory/run.py",
                     "factory/worker_release.py", "bin/processes.py"):
            self.assertIn(name, manifest["files"])
        self.assertEqual(manifest["release"], json.loads((ROOT / "factory/worker-release.json").read_text())["release"])

    def test_store_refuses_bad_bundles_and_detects_corruption(self):
        (self.h.tree / "factory/durable/worker_step.py").unlink()
        with self.assertRaises(W.ReleaseError):
            self.h.store.put_bundle(W.build_bundle(self.h.tree))
        with self.assertRaises(W.ReleaseError):
            self.h.store.put_bundle(b"not a tarball")
        path = self.h.tmp / "store/bundles" / (self.h.plumbing + ".tgz")
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(W.ReleaseError):
            self.h.store.bundle(self.h.plumbing)

    def test_release_command_fills_the_store(self):
        store = self.h.tmp / "cli-store"
        p = subprocess.run([sys.executable, "-B", str(ROOT / "factory/durable/workers.py"), "release", "--root",
                            str(self.h.tree), "--store", str(store)], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), self.h.plumbing)
        bench = self.h.benches["bench-env"]
        args = [sys.executable, "-B", str(ROOT / "factory/durable/workers.py"), "bench", "--store", str(store),
                "--bench-version", bench]
        self.assertEqual(subprocess.run(args + ["--image", "bench-env"], timeout=60).returncode, 0)
        self.assertEqual(subprocess.run(args + ["--image", "bench-env"], timeout=60).returncode, 0)
        self.assertEqual(subprocess.run(args + ["--image", "other"], stderr=subprocess.DEVNULL, timeout=60).returncode, 1)
        self.assertEqual(W.ReleaseStore(store).image_for(bench, "x"), "bench-env")


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(self)
        self.bench = self.h.benches["bench-env"]

    def acquire(self, pool, plumbing=None, bench=None, case=CASE):
        return pool.acquire(case, plumbing or self.h.plumbing, bench or self.bench)

    def test_worker_ids_map_both_ways(self):
        for real in REAL_IDS:
            lease_id = W.lease_worker_id(real)
            self.assertIsNotNone(WORKER_ID.fullmatch(lease_id))
            self.assertEqual(W.boat_id(lease_id), real)
        self.assertEqual(W.boat_id("12345678"), "12345678")   # a Hetzner id is unchanged

    def test_fresh_acquire_creates_under_labels_and_installs_the_exact_release(self):
        pool = self.h.pool()
        lease = self.acquire(pool)
        self.assertEqual(lease, WorkerLease("bx-d6dzvjbc", CASE))
        new = [c for c in self.h.calls() if c[0] == "new"]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0][:2], ["new", "--from"])
        for flag in ("--no-env", "--no-monitoring", "--no-snapshots", "--json"):
            self.assertIn(flag, new[0])
        labels = dict(new[0][i + 1].split("=", 1) for i, a in enumerate(new[0]) if a == "--label")
        self.assertEqual(labels["unbug-durable/pool"], "wp2-test")
        self.assertEqual(labels["unbug-durable/case"], CASE)
        self.assertRegex(labels["unbug-durable/intent"], "^[0-9a-f]{32}$")
        home = self.h.home("bx_d6dzvjbc")
        self.assertEqual(json.loads((home / RELEASE_MANIFEST).read_text()),
                         {"plumbing_version": self.h.plumbing, "bench_version": self.bench})
        self.assertEqual(os.readlink(home / "factory-release"), "releases/" + self.h.plumbing)
        self.assertTrue((home / "factory-release/factory/durable/worker_step.py").is_file())
        self.assertFalse(list((home / "releases").glob("*.tgz*")))
        self.assertFalse((self.h.tmp / "must-not-be-used").exists())

    def test_acquire_is_idempotent_per_case(self):
        pool = self.h.pool()
        first = self.acquire(pool)
        before = len(self.h.calls())
        self.assertEqual(self.acquire(self.h.pool()), first)
        later = self.h.calls()[before:]
        self.assertFalse([c for c in later if c[0] in ("new", "delete")])
        self.assertEqual(len(later), 2)   # one inventory read, one RELEASE.json read
        self.assertNotEqual(self.acquire(pool, case="case-20261105T000000Z-def456").worker_id, first.worker_id)

    def test_plumbing_release_installs_beside_the_old_one_on_the_same_worker(self):
        pool = self.h.pool()
        lease = self.acquire(pool)
        second = self.h.second_plumbing()
        self.assertNotEqual(second, self.h.plumbing)
        self.assertEqual(self.acquire(pool, plumbing=second), lease)
        home = self.h.home("bx_d6dzvjbc")
        self.assertEqual(json.loads((home / RELEASE_MANIFEST).read_text())["plumbing_version"], second)
        self.assertTrue((home / "releases" / self.h.plumbing / "RELEASE.json").is_file())  # old tree kept for live units
        self.assertEqual(len([c for c in self.h.calls() if c[0] == "new"]), 1)

    def test_bench_comes_from_the_registered_image_and_a_mismatch_deletes_the_worker(self):
        pool = self.h.pool()
        lease = self.acquire(pool, bench=self.h.benches["bench-env-2"])
        self.assertEqual(self.h.inventory()[0]["id"], W.boat_id(lease.worker_id))
        self.assertEqual(json.loads((self.h.boat_dir / "images.json").read_text()), {"bx_d6dzvjbc": "bench-env-2"})
        # The same case on another bench needs another image, hence another worker.
        lease2 = self.acquire(pool)
        self.assertNotEqual(lease2.worker_id, lease.worker_id)
        self.assertEqual([r["id"] for r in self.h.inventory()], ["bx_sk2p68qq"])
        # A bench with no registered image lands on the default image and fails its fingerprint.
        with self.assertRaises(W.PoolError) as caught:
            self.acquire(pool, bench="e" * 64, case="case-20261105T000000Z-def456")
        self.assertEqual(caught.exception.reason, "infra:bench_mismatch")
        self.assertEqual([r["id"] for r in self.h.inventory()], ["bx_sk2p68qq"])
        receipt = self.h.tmp / "state-wp2-test/deletions/bx_z4wktrbn/deletion-completion.json"
        self.assertEqual(json.loads(receipt.read_text())["status"], "completed")

    def test_missing_release_is_refused_before_any_provider_call(self):
        with self.assertRaises(W.PoolError) as caught:
            self.acquire(self.h.pool(), plumbing="f" * 64)
        self.assertEqual(caught.exception.reason, "infra:release_missing")
        self.assertEqual(self.h.calls(), [])

    def test_lost_create_response_is_adopted_by_its_intent_label(self):
        self.h.flag("new-lost")
        lease = self.acquire(self.h.pool())
        self.assertEqual(lease.worker_id, "bx-d6dzvjbc")
        self.assertEqual(len([c for c in self.h.calls() if c[0] == "new"]), 1)

    def test_lost_create_with_no_trace_creates_once_more_and_recover_deletes_a_late_orphan(self):
        pool = self.h.pool()
        self.h.flag("new-fail")
        with self.assertRaises(W.PoolError) as caught:
            self.acquire(pool)
        self.assertEqual(caught.exception.reason, "infra:worker_create_failed")
        self.h.flag("new-fail", None)
        lease = self.acquire(pool)
        # The first request shows up late, under the abandoned intent: an orphan.
        self.h.add_row("bx_bykfqbyn", {"unbug-durable/pool": "wp2-test", "unbug-durable/case": CASE,
                                       "unbug-durable/intent": "0" * 32})
        self.assertEqual(self.h.pool().recover(), {"adopted": ["bx_d6dzvjbc"], "deleted": ["bx_bykfqbyn"]})
        self.assertEqual([r["id"] for r in self.h.inventory()], [W.boat_id(lease.worker_id)])

    def test_nonzero_exit_with_an_id_keeps_and_uses_the_worker(self):
        self.h.flag("new-exit-1")
        self.assertEqual(self.acquire(self.h.pool()).worker_id, "bx-d6dzvjbc")

    def test_restart_adopts_recorded_workers_and_deletes_only_this_pools_orphans(self):
        lease = self.acquire(self.h.pool())
        self.h.add_row("bx_sk2p68qq", {"unbug-durable/pool": "wp2-test", "unbug-durable/case": "case-20261105T000000Z-zzz999",
                                       "unbug-durable/intent": "1" * 32})
        self.h.add_row("bx_z4wktrbn", {"unbug-durable/pool": "other-pool", "unbug-durable/case": CASE})
        self.h.add_row("bx_bykfqbyn", {})
        restarted = self.h.pool()
        self.assertEqual(restarted.recover(), {"adopted": ["bx_d6dzvjbc"], "deleted": ["bx_sk2p68qq"]})
        self.assertEqual(sorted(r["id"] for r in self.h.inventory()), ["bx_bykfqbyn", "bx_d6dzvjbc", "bx_z4wktrbn"])
        self.assertTrue(restarted.alive(lease))
        self.assertEqual(self.acquire(restarted), lease)

    def test_incomplete_inventory_deletes_nothing(self):
        self.acquire(self.h.pool())
        self.h.add_row("bx_sk2p68qq", {"unbug-durable/pool": "wp2-test", "unbug-durable/case": CASE})
        self.h.flag("list-more")
        with self.assertRaises(W.PoolError) as caught:
            self.h.pool().recover()
        self.assertEqual(caught.exception.reason, "infra:inventory_unavailable")
        self.assertFalse([c for c in self.h.calls() if c[0] == "delete"])

    def test_dead_worker_is_replaced(self):
        pool = self.h.pool()
        lease = self.acquire(pool)
        rows = self.h.inventory()
        rows[0]["state"] = "archived"
        (self.h.boat_dir / "inventory.json").write_text(json.dumps(rows))
        self.assertFalse(pool.alive(lease))
        replacement = self.acquire(pool)
        self.assertEqual(replacement.worker_id, "bx-sk2p68qq")
        self.assertTrue(pool.alive(replacement))

    def test_release_deletes_with_operation_receipts_and_is_idempotent(self):
        pool = self.h.pool()
        lease = self.acquire(pool)
        pool.release(lease)
        self.assertEqual(self.h.inventory(), [])
        evidence = self.h.tmp / "state-wp2-test/deletions/bx_d6dzvjbc"
        self.assertEqual(json.loads((evidence / "deletion-request.json").read_text()),
                         {**json.loads(DELETE_REQUEST.read_text())})
        self.assertEqual(json.loads((evidence / "deletion-completion.json").read_text()),
                         json.loads(DELETE_DONE.read_text()))
        before = len(self.h.calls())
        pool.release(lease)
        self.assertEqual(len(self.h.calls()), before)
        self.assertFalse(pool.alive(lease))

    def test_unconfirmed_deletion_resumes_the_same_operation(self):
        pool = self.h.pool()
        lease = self.acquire(pool)
        self.h.flag("deletion-pending")
        with self.assertRaises(W.PoolError) as caught:
            pool.release(lease)
        self.assertEqual(caught.exception.reason, "infra:worker_delete_unconfirmed")
        self.h.flag("deletion-pending", None)
        self.h.pool().release(lease)
        deletes = [c for c in self.h.calls() if c[0] == "delete"]
        self.assertEqual(len(deletes), 1)   # never a second delete request
        self.assertFalse((self.h.tmp / "state-wp2-test" / (CASE + ".json")).exists())

    def test_alive_is_true_when_the_inventory_cannot_be_read(self):
        pool = self.h.pool()
        lease = self.acquire(pool)
        self.h.flag("list-fail")
        self.assertTrue(pool.alive(lease))
        with self.assertRaises(W.PoolError) as caught:
            self.acquire(pool)
        self.assertEqual(caught.exception.reason, "infra:inventory_unavailable")

    def test_corrupted_upload_is_refused_and_the_fresh_worker_deleted(self):
        self.h.flag("ssh-corrupt", "tgz.part")
        with self.assertRaises(W.PoolError) as caught:
            self.acquire(self.h.pool())
        self.assertEqual(caught.exception.reason, "infra:release_upload_failed")
        self.assertEqual(self.h.inventory(), [])

    def test_failed_qualification_is_retried_once_then_refused(self):
        self.h.flag("ssh-exit", "import hashlib,json,pathlib")
        with self.assertRaises(W.PoolError) as caught:
            self.acquire(self.h.pool())
        self.assertEqual(caught.exception.reason, "infra:release_qualify_failed")
        qualify = [c for c in self.h.calls() if c[0] == "ssh" and "import hashlib,json,pathlib" in c[2]]
        self.assertEqual(len(qualify), 2)

    def test_unreachable_kept_worker_is_not_deleted(self):
        pool = self.h.pool()
        self.acquire(pool)
        self.h.flag("ssh-fail", "RELEASE.json")
        with self.assertRaises(W.PoolError) as caught:
            self.acquire(pool)
        self.assertEqual(caught.exception.reason, "infra:worker_unreachable")
        self.assertEqual(len(self.h.inventory()), 1)

    def test_default_steps_are_launch_sh_verbatim(self):
        launch = (ROOT / "factory/launch.sh").read_text()
        self.assertIn(W.PIN_SCRIPT.strip(), launch)
        self.assertIn(W.IMAGE_SCRIPT, launch)
        self.assertIn("--root ~/unbug-bench", W.QUALIFY_SCRIPT)
        self.assertIn("--drivers opencode,codex", W.QUALIFY_SCRIPT)


if __name__ == "__main__":
    unittest.main()
