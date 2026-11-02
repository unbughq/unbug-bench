"""Offline practice contract and immutable release checks; never live qualification."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import batch
import batch_holder
import batch_money
import key_holder
import model_runtime
from model_router import route_maximum
import practice
import practice_cleanup
from transfer import digest

MANIFEST = "factory/batches/" + practice.BATCH + ".json"
DROPIN = "[Service]\nEnvironment=UNBUG_PRACTICE_BATCH=b-plumbing-practice-2\nEnvironment=UNBUG_CLOUD=boat\n"
LIVE = [("provider_cost_and_legacy_debt", "0.000000000"), ("distinct_accounts_and_deployment", "0.000000000"),
        ("armed_admission", "0.000000000"), ("worker_and_verified_deletion", "5.000000000"),
        ("account2_model_work_and_settlement", "19.990000000"), ("publication_replay", "0.000000000")]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()


def roles(record):
    args = record["jobs"]["practice"]["args"]
    flags = ("builder", "attacker", "reviewer1", "strong_calibrator", "easy_calibrator")
    a = SimpleNamespace(**{f: args[args.index("--" + f.replace("_", "-")) + 1] for f in flags},
                        **{f + "_effort": None for f in (*flags, "reviewer2")},
                        reviewer2=None, rotation_slot=1, batch_release_sha256="offline")
    c = SimpleNamespace(args=a, card={})
    model_runtime.select_models(c, log=lambda *a: None)
    result = {}
    for name, role in c.card["roles"].items():
        route = role["model"]
        maximum = route_maximum(route)
        if route.startswith("codex/") or maximum is None: raise ValueError("unbounded role")
        result[name] = dict(route=route, **maximum)
    return result


def policy(root, release_sha):
    record = practice.EXPECTED
    return dict(root="/home/user/unbug-bench", code_sha256=key_holder.fingerprint(root),
                recipient=record["restore_recipient"], path="/usr/local/bin:/usr/bin:/bin", jobs=deepcopy(record["jobs"]),
                batch=dict(id=practice.BATCH, release="/home/user/.unbug-control/releases/" + release_sha,
                           sha256=release_sha, max_concurrency=1, manifest_path=MANIFEST, manifest_sha256=digest(root / MANIFEST)))


def files():
    return ["release/" + n for n in (*batch.INPUTS, "deploy.py", "batch-release.json")] + [
        "policy.json", practice_cleanup.UNIT, "practice.conf", "tools/practice-fault.py", "tools/qualify-batch-inputs.py"]


def pins(root, bundle):
    sha = digest(bundle / "release/batch-release.json")
    return dict(schema=1, source_commit=git(root, "rev-parse", "HEAD"), source_tree=git(root, "rev-parse", "HEAD^{tree}"),
                batch_id=practice.BATCH, deadline=practice.EXPECTED["batch_deadline"], launch_ready=False,
                manifest_sha256=digest(root / MANIFEST), trusted_code_sha256=key_holder.fingerprint(root),
                batch_release_sha256=sha, files={n: digest(bundle / n) for n in files()},
                routes=roles(practice.EXPECTED), cleanup_unit_sha256=digest(bundle / practice_cleanup.UNIT),
                activation_dropin_sha256=digest(bundle / "practice.conf"))


def verify_bundle(root, bundle):
    saved = json.loads((bundle / "pins.json").read_text())
    if (bundle / "INCOMPLETE").exists() or saved != pins(root, bundle): raise ValueError("pins stale")
    batch.verify(bundle / "release", saved["batch_release_sha256"], root)
    release = json.loads((bundle / "release/batch-release.json").read_text())
    if release["commit"] != saved["source_commit"]: raise ValueError("pins stale")
    if json.loads((bundle / "policy.json").read_text()) != policy(root, saved["batch_release_sha256"]): raise ValueError("policy stale")
    if (bundle / practice_cleanup.UNIT).read_bytes() != (root / "control" / practice_cleanup.UNIT).read_bytes(): raise ValueError()
    if (bundle / "practice.conf").read_text() != DROPIN: raise ValueError()
    for name in ("tools/practice-fault.py", "tools/qualify-batch-inputs.py"):
        if (bundle / name).read_bytes() != (root / name).read_bytes(): raise ValueError()


def check(root, bundle=None):
    record = json.loads((root / MANIFEST).read_text())
    report = dict(schema=1, source_commit=git(root, "rev-parse", "HEAD"), launch_ready=False, offline=[],
                  live=[dict(id=name, status="unproved", ceiling_usd=cap) for name, cap in LIVE])
    def run(name, fn, reason):
        try:
            if fn() is False: raise ValueError()
            report["offline"].append(dict(id=name, status="pass", reason="checked_offline"))
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            report["offline"].append(dict(id=name, status="fail", reason=reason))
    def manifest():
        batch_money.check_manifest(record)
        practice.admission(record)
        return practice.matches(record)
    run("manifest", manifest, "manifest_refused")
    run("roles", lambda: roles(record), "roles_refused")
    run("activation", lambda: not batch_holder.HOLDER_ENABLED and not practice.active({"batch": {"id": "unrelated"}}, root), "activation_refused")
    run("cleanup", lambda: practice.deadlines(0) and (root / "control" / practice_cleanup.UNIT).is_file(), "cleanup_refused")
    run("fault", lambda: callable(practice.fault) and (root / "tools/practice-fault.py").is_file(), "fault_refused")
    run("pins", lambda: verify_bundle(root, bundle) if bundle is not None else False, "unpinned" if bundle is None else "pins_stale")
    return report


def code(report):
    return 1 if any(r["status"] == "fail" for r in report["offline"]) else 3
