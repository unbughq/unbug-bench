"""Independent cleanup of one authenticated disposable practice operation."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

import batch_holder as holder
import batch_money as money
import batch_service as service
import boat_lifecycle
import practice
from registry import atomic_json
from transfer import digest

UNIT = "unbug-practice-cleanup@.service"


def location(home, op):
    return home / "batches" / practice.BATCH / "cleanup" / op["operation_id"]


def ready(policy, op, pid):
    from key_holder import policy_digest
    return dict(schema=1, operation_id=op["operation_id"], launch_id=op["launch_id"],
                timing=practice.TIMING, policy_sha256=policy_digest(policy), pid=pid)


def armed(policy, root, home, op):
    if not practice.active(policy, root): return
    practice.admission(money.manifest(policy, root))
    try:
        if os.environ.get("UNBUG_CLOUD") != "boat": raise ValueError()
        if digest(Path("/etc/systemd/system") / UNIT) != digest(root / "control" / UNIT): raise ValueError()
        marker = service._json(location(home, op).with_suffix(".ready.json"))
        response = subprocess.run(["systemctl", "show", "unbug-practice-cleanup@" + op["operation_id"] + ".service",
                                   "--property=ActiveState,SubState,ExecMainPID"], capture_output=True,
                                  text=True, check=True, timeout=10)
        status = dict(line.split("=", 1) for line in response.stdout.splitlines())
        pid = int(status["ExecMainPID"])
        if pid <= 0 or status["ActiveState"] != "active" or status["SubState"] != "running" or marker != ready(policy, op, pid):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        raise money.MoneyWait("cleanup not armed") from None


def monitor(root, path):
    with service._regular(path / "monitor.sh") as stream: lines = stream.read().decode().splitlines()
    values = {}
    for key in ("spend_file", "ttl_seconds", "retire_at"):
        found = [shlex.split(line.split("=", 1)[1]) for line in lines if line.startswith(key + "=")]
        if len(found) != 1 or len(found[0]) != 1: raise ValueError("invalid monitor")
        values[key] = found[0][0]
    spend = Path(values["spend_file"])
    if not spend.is_absolute() or not spend.resolve().is_relative_to((root / "results/spend").resolve()):
        raise ValueError("invalid monitor")
    if int(values["ttl_seconds"]) != practice.TIMING["ttl_seconds"] or int(values["retire_at"]) != practice.TIMING["run_seconds"]:
        raise ValueError("invalid cleanup timing")
    return spend


def step(policy, root, home, op, now=None):
    """One observation; absence is never a deletion receipt. No replayed creation."""
    now = time.time() if now is None else now
    result = dict(schema=1, operation_id=op["operation_id"], deadline=None, state="waiting", workers=[])
    if not op["dispatch_started"]:
        if op["state"] == "failed": result["state"] = "not_dispatched"
        return result
    path = home / "launches" / op["launch_id"]
    try:
        if service._json(path / "launch.json") != op["launch"]: raise ValueError("launch mismatch")
        if not (path / "monitor.sh").exists() and not list(path.glob("new.*")):
            ids_file = path / "ids"
            if not ids_file.exists(): return result
            with service._regular(ids_file) as stream:
                if not stream.read().strip(): return result
        spend = monitor(root, path)
        workers = boat_lifecycle.ids(path, "resolve")
        result["workers"] = workers
        if not workers: raise ValueError("creation unknown")
        deadlines = []
        for worker in workers:
            # This durable start belongs to guard_new; restart cannot move it.
            with service._regular(path / (worker + ".started")) as stream:
                raw = stream.read().decode().strip()
            if not raw.isascii() or not raw.isdigit() or int(raw) <= 0 or int(raw) > now:
                raise ValueError("start unknown")
            _, deadline, _ = practice.deadlines(int(raw))
            deadlines.append(deadline)
            result["deadline"] = min(deadlines)
            try: holder._retirement(root, path, worker)
            except (OSError, ValueError, KeyError, TypeError):
                if now >= deadline:
                    result["state"] = "deleting"
                    boat_lifecycle.delete_receipt(root, spend, worker, path / "ids")
        result["deadline"] = min(deadlines)
        # Recheck after deletion; verify complete inventory, never absence alone.
        if all((spend.with_suffix(".deletions") / w / "deletion-completion.json").exists() for w in workers):
            for worker in workers: holder._retirement(root, path, worker)
            fleet = subprocess.run([str(root / "bin/boat-call"), "list", "--json"], capture_output=True,
                                   check=True, timeout=100, env={**os.environ, "BOAT_COMMAND_TIMEOUT_SECONDS": "25"})
            inventory = json.loads(fleet.stdout)
            listed = [r["id"] for r in inventory["sandboxes"]]
            if inventory["pageInfo"]["hasMore"] is not False or len(listed) != len(set(listed)):
                raise ValueError("inventory incomplete")
            if not set(workers).intersection(listed) and not list(path.glob("new.*.pending")):
                result["state"] = "complete"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        result["state"] = "uncertain"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", required=True)
    a = parser.parse_args()
    from key_holder import policy_load, ROOT, CONTROL_HOME
    if os.environ.get("UNBUG_CLOUD") != "boat": raise ValueError("request_refused")
    policy = policy_load(CONTROL_HOME / "policy.json")
    if not practice.active(policy, ROOT): raise ValueError("request_refused")
    while True:
        # Read the validated full operation under its lock.
        with money.locked(CONTROL_HOME, practice.BATCH) as directory:
            op = holder._operations(directory, money.manifest(policy, ROOT), policy)[a.operation]
        target = location(CONTROL_HOME, op)
        target.parent.mkdir(mode=0o700, exist_ok=True)
        atomic_json(target.with_suffix(".ready.json"), ready(policy, op, os.getpid()))
        status = step(policy, ROOT, CONTROL_HOME, op)
        atomic_json(target.with_suffix(".status.json"), status)
        if status["state"] in ("complete", "not_dispatched"): return 0
        time.sleep(5)


if __name__ == "__main__":
    try: raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError): raise SystemExit("practice cleanup refused")
