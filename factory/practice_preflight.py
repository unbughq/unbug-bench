"""Practice contract and release checks, plus the read-only live launch prerequisites.

check() is offline. live() (operator, before practice step 2) and dispatch_checks()
(every batch_holder.dispatch, before dispatch_started) reserve, start, call and spend nothing.
"""
import base64
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
from types import SimpleNamespace
import urllib.error
import urllib.request

import batch
import batch_holder
import batch_money
import codex_login
import key_holder
import model_router
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
# Founder decisions no API can prove; a new decision changes pins() and means a repin.
DECISIONS = {practice.BATCH: ("topup_off", "accounts_unverified_accepted", "router_ram_openrouter")}
WALLET_CAP = Decimal(dict(LIVE)["worker_and_verified_deletion"])
PAID_CAP = Decimal(dict(LIVE)["account2_model_work_and_settlement"])
R2_ABSENT = "preflight/absent"  # never written; a 404 proves the R2 credentials were accepted
VM_REPO = "/home/user/unbug-bench"
VM_KEY, VM_BUNDLE = "/home/user/.unbug-control/control.key", "/home/user/.config/unbug-bench/secrets.age"
# The key holder service's environment (control/unbug-key-holder.service).
VM_USER = ("runuser -u user -- env -i HOME=/home/user USER=user PATH=/usr/local/bin:/usr/bin:/bin "
           "BOAT_CMD=/usr/local/bin/boat BOAT_NO_UPDATE=1 ")


class PreflightHold(Exception):
    """A launch prerequisite is missing. Dispatch returns TEMPFAIL; the operation stays pending."""


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
                activation_dropin_sha256=digest(bundle / "practice.conf"),
                decisions_sha256=digest(decisions_file(root)) if decisions_file(root).is_file() else None)


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


def check(root, bundle=None, server=False):
    """server=False: offline only. Otherwise also the live checks against that control server (None if unresolved)."""
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
    if server is not False: report["preflight"] = live(root, server, record)
    return report


def code(report):
    rows = report["offline"] + report.get("preflight", [])
    if any(r["status"] == "fail" for r in rows): return 1
    return 0 if "preflight" in report and all(r["status"] == "pass" for r in rows) else 3


def decisions_file(root, batch_id=practice.BATCH):
    return root / "factory/batches" / (batch_id + ".decisions.json")


def founder_decisions(root, batch_id=practice.BATCH):
    """Every required decision ID not on record, listed together so the founder answers once."""
    path = decisions_file(root, batch_id)
    rows = json.loads(path.read_text()) if path.is_file() else []
    if not isinstance(rows, list): raise ValueError()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"id", "text", "recorded_utc"} or
                not all(isinstance(v, str) and v for v in row.values()) or
                datetime.fromisoformat(row["recorded_utc"]).tzinfo is None): raise ValueError()
    return [d for d in DECISIONS[batch_id] if d not in {r["id"] for r in rows}]


def _load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
    loader.exec_module(module)
    return module


def boat_version(root):
    return re.search(r"^VERSION = '(.+)'$", (root / "bin/boat-call").read_text(), re.M).group(1)


def decrypt(identity, path):
    """The credential bundle, decrypted once, in memory only: {label: bytes}."""
    try:
        result = subprocess.run(["age", "-d", "-i", "/dev/stdin", str(path)], input=identity,
                                capture_output=True, timeout=10)
        if result.returncode: raise ValueError()
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            return {m.name.removeprefix("./"): archive.extractfile(m).read() for m in archive if m.isfile()}
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
        raise PreflightHold("credentials: bundle not decryptable") from None


def missing_labels(names, claude, opencode):
    """Labels as dispatch and launch.sh require them; router names are added by pack, not the bundle."""
    return sorted({claude, opencode, "openrouter-key", "codex-auth.json"} - set(names))


def job_labels(card, job, names):
    """The Claude and OpenCode labels this launch uses, chosen as dispatch chooses them."""
    from account_handoff import launch_accounts
    held = (set(key_holder.OPENCODE_ACCOUNTS.values()) | set(key_holder.CLAUDE_ACCOUNTS.values())) & set(names)
    account, claude, accounts = launch_accounts(card, job, {}, held)
    opencode = "opencode-go-key" if account is None else key_holder.OPENCODE_ACCOUNTS[account]
    return account, accounts, key_holder.CLAUDE_ACCOUNTS[claude], opencode


def worker_names(names, claude, opencode):
    """launch.sh's selection filter: one account per provider, no R2 keys, no AppleDouble entries."""
    def keep(name):
        if name.startswith("._") or name == "r2-env": return False
        if name in ("opencode-go-key", "opencode-go-key-2"): return name == opencode
        if name in ("claude-token", "claude-token-2") or name.startswith("claude-factory-token-"): return name == claude
        return True
    return [n for n in names if keep(n)]


def ttl_hours(args):
    return float(args[args.index("--ttl-hours") + 1]) if "--ttl-hours" in args else 8.0  # launch.sh default


def login_lifetimes(bundle, args):
    if codex_login.codex_role(args):
        codex_login.validate(json.loads(bundle["codex-auth.json"]), ttl_hours(args) * 3600)


def router(bundle, claude, opencode, client):
    """pack succeeds and adds the router names; the shared paid ledger is well formed and settled."""
    import router_delivery
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name in worker_names(bundle, claude, opencode):
            member = tarfile.TarInfo(name); member.size = len(bundle[name]); member.mode = 0o600
            archive.addfile(member, io.BytesIO(bundle[name]))
    packed = router_delivery.pack(base64.b64encode(stream.getvalue()), client)
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(packed))) as archive:
        if not set(router_delivery.NAMES) <= set(archive.getnames()): raise ValueError()
    config = router_delivery.read_config(client)
    paid = model_router.router_request(config["url"], config["token"], "status", {}, ca_pem=config["ca_pem"])["paid"]
    if set(paid) != {"total_usd", "outstanding_usd", "ceiling_usd", "available_credit_usd"}: raise ValueError()
    for key, value in paid.items():
        if not (value is None and key in ("ceiling_usd", "available_credit_usd")) and (
                not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]{9}", value)): raise ValueError()
    if Decimal(paid["outstanding_usd"]) != 0: raise ValueError()


def _status(url):
    opener = urllib.request.build_opener(model_router._NoRedirect)
    try:
        with opener.open(url, timeout=10) as response: return response.status
    except urllib.error.HTTPError as error:
        error.close(); return error.code


def r2(root, env):
    """One signed GET of a key that never exists: 404 means the credentials were accepted."""
    values = dict(line.removeprefix("export ").split("=", 1) for line in env.splitlines() if "=" in line)
    names = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
    if not all(values.get(n) for n in names): raise ValueError()
    url = _load(root / "bin/r2-presign", "r2_presign").presign("GET", R2_ABSENT, 60, *(values[n] for n in names))
    if _status(url) not in (200, 404): raise ValueError()


def dispatch_checks(root, bundle, claude, opencode, args, client):
    """Phase B, run inside dispatch before dispatch_started. Every check runs; one hold names each failure.

    Returns the effective practice paid ceiling, min(LIVE cap, OpenRouter credit)."""
    failed, credit = [], None
    missing = missing_labels(bundle, claude, opencode)
    if missing: failed.append("credentials: missing " + " ".join(missing))
    def run(name, fn):
        try: fn()
        except Exception: failed.append(name)  # fixed names only: never exception or credential text
    run("login_lifetimes", lambda: login_lifetimes(bundle, args))
    run("router", lambda: router(bundle, claude, opencode, client))
    try: credit = model_router.available_credit(bundle["openrouter-key"].decode().rstrip("\n"))
    except (KeyError, UnicodeDecodeError): pass
    if credit is None: failed.append("openrouter")
    run("r2", lambda: r2(root, bundle["r2-env"].decode()))
    if failed: raise PreflightHold("; ".join(failed))
    return min(PAID_CAP, credit)


def live(root, server, record):
    """Phase A, from the operator's Mac before practice step 2: root SSH only, as bin/control-vm."""
    control = _load(root / "bin/control-vm", "control_vm")
    def ssh(command):
        if server is None: raise ValueError()
        return subprocess.run(["ssh", *control.ssh_options(server), control.host(server, "root"), command],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    def vm(command): return ssh(VM_USER + command)
    rows = []
    def run(name, fn):
        try: status, reason = fn() or ("pass", "checked_live")
        except Exception: status, reason = "fail", name + "_refused"
        rows.append(dict(id=name, status=status, reason=reason))
    def decisions():
        missing = founder_decisions(root, record["id"])
        if missing: return "needs_founder", "missing " + " ".join(missing)
    def deploy():
        if ssh("true").returncode: return "fail", "root_ssh_refused"
    def boat_cli():
        installed = vm("/usr/local/bin/boat --version").stdout.strip()
        if installed != boat_version(root): return "fail", "installed " + installed + ", pinned " + boat_version(root)
        listed = vm(VM_REPO + "/bin/boat-call list --json")
        if listed.returncode or json.loads(listed.stdout)["pageInfo"]["hasMore"] is not False: return "fail", "boat_list_refused"
    def boat_wallet():
        billed = vm(VM_REPO + "/bin/boat-call billing --json")
        if billed.returncode: return "fail", "boat_billing_refused"
        balance = Decimal(str(json.loads(billed.stdout)["limits"]["creditBalanceSeconds"])) / 100000
        if not balance <= WALLET_CAP: return "fail", "balance above " + str(WALLET_CAP)
    job = record["jobs"]["practice"]
    def credentials():
        listed = vm("bash -c " + shlex.quote("set -o pipefail; age -d -i " + VM_KEY + " " + VM_BUNDLE + " | tar -tf -"))
        if listed.returncode: return "fail", "bundle not decryptable"
        names = {n.removeprefix("./") for n in listed.stdout.splitlines()}
        missing = missing_labels(names, *job_labels({}, job, names)[2:])
        if missing: return "fail", "missing " + " ".join(missing)
    def lifetimes():
        if not codex_login.codex_role(job["args"]): return "pass", "no_codex_role"
        checked = vm("bash -c " + shlex.quote("set -o pipefail; age -d -i " + VM_KEY + " " + VM_BUNDLE + " | python3 -B " +
                                       VM_REPO + "/factory/codex_login.py --ttl-hours " + str(ttl_hours(job["args"]))))
        if checked.returncode: return "fail", "codex_login_expired"
    for name, fn in (("founder_decisions", decisions), ("deploy_access", deploy), ("boat_cli", boat_cli),
                     ("boat_wallet", boat_wallet), ("credentials", credentials), ("login_lifetimes", lifetimes)):
        run(name, fn)
    return rows
