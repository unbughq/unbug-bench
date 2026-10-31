# Exact read-only remote probe; public scanner embedded to avoid installing files.
SCANNER_SOURCE = '#!/usr/bin/env python3\n"""Observe local deployment metadata. Never authorizes cleanup or activation."""\nimport datetime\nfrom decimal import Decimal, Inexact, InvalidOperation, localcontext\nimport hashlib\nimport json\nimport os\nfrom pathlib import Path\nimport re\nimport stat\nimport sys\n\nLIMIT = 8 * 1024 * 1024\nSOURCES = (\'factory/control_resume.py\', \'factory/launch.sh\',\n           \'bin/boat-launch-guards.sh\', \'bin/boat-spend\')\nFILES = (\'launch.json\', \'controller.lock\', \'monitor.sh\', \'ids\', \'complete\',\n         \'spend-finished\', \'cleanup-status.json\')\nLABELS = (\'intent-only\', \'response-and-intent\', \'response-without-marker\')\nTYPES = (\'file\', \'directory\', \'symlink\', \'other\')\nSTATUSES = (\'reserved\', \'finished\', \'reconciled_expired\')\n\n\ndef kind(mode):\n    for test, name in ((stat.S_ISREG, \'file\'), (stat.S_ISDIR, \'directory\'),\n                       (stat.S_ISLNK, \'symlink\')):\n        if test(mode):\n            return name\n    return \'other\'\n\n\ndef canonical_directory(path):\n    path = Path(os.path.abspath(path))\n    for part in (*reversed(path.parents), path):\n        if not stat.S_ISDIR(part.lstat().st_mode):\n            raise ValueError(\'invalid-root\')\n    return path\n\n\ndef metadata(path):\n    try:\n        info = path.lstat()\n        return dict(state=\'present\', type=kind(info.st_mode), size=info.st_size,\n                    mtime_ns=info.st_mtime_ns)\n    except FileNotFoundError:\n        return dict(state=\'missing\')\n    except OSError:\n        return dict(state=\'error\')\n\n\ndef signature(info):\n    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)\n\n\ndef read_regular(path):\n    """Read only a bounded regular file with stable metadata, without following links."""\n    before = None\n    try:\n        canonical_directory(path.parent)\n        before = path.lstat()\n        if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT:\n            return \'unsupported\', None\n        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)\n        with os.fdopen(fd, \'rb\') as stream:\n            opened = os.fstat(stream.fileno())\n            if signature(opened) != signature(before):\n                return \'changed\', None\n            data = stream.read(LIMIT + 1)\n            after = os.fstat(stream.fileno())\n        if len(data) > LIMIT:\n            return \'unsupported\', None\n        if signature(before) != signature(after) or signature(before) != signature(path.lstat()):\n            return \'changed\', None\n        return \'ok\', data\n    except FileNotFoundError:\n        return (\'changed\' if before is not None else \'missing\'), None\n    except ValueError:\n        return \'unsupported\', None\n    except OSError:\n        return \'error\', None\n\n\ndef scan_launch(path):\n    result = dict(id=path.name, state=\'ok\', files={}, creations=[],\n                  creation_counts=dict.fromkeys(LABELS, 0), unknown_entries=0)\n    for suffix in (\'deleted\', \'parked\', \'keep\'):\n        result[suffix + \'_markers\'] = dict.fromkeys(TYPES, 0)\n    for name in FILES:\n        observation = metadata(path / name)\n        result[\'files\'][name] = observation\n        if observation[\'state\'] == \'error\' or (observation[\'state\'] == \'present\' and observation[\'type\'] != \'file\'):\n            result[\'state\'] = \'error\'\n    try:\n        entries = list(path.iterdir())\n        serials = set()\n        for entry in entries:\n            name = entry.name\n            if name in FILES:\n                continue\n            match = re.fullmatch(r\'new\\.([0-9]+)(\\.pending)?\', name)\n            if match:\n                serials.add(match[1])\n                continue\n            match = re.fullmatch(r\'[A-Za-z0-9_-]+\\.(deleted|parked|keep)\', name)\n            if match:\n                observation = metadata(entry)\n                if observation[\'state\'] != \'present\':\n                    result[\'state\'] = \'error\'\n                else:\n                    result[match[1] + \'_markers\'][observation[\'type\']] += 1\n                continue\n            result[\'unknown_entries\'] += 1\n        for serial in sorted(serials):\n            response = metadata(path / (\'new.\' + serial))\n            intent = metadata(path / (\'new.\' + serial + \'.pending\'))\n            for observation in (response, intent):\n                if observation[\'state\'] == \'error\' or (observation[\'state\'] == \'present\' and observation[\'type\'] != \'file\'):\n                    result[\'state\'] = \'error\'\n            present = (response[\'state\'] == \'present\', intent[\'state\'] == \'present\')\n            # A listed file that disappears makes this scan incomplete.\n            if present == (False, False):\n                result[\'state\'] = \'error\'\n                continue\n            label = {(False, True): LABELS[0], (True, True): LABELS[1], (True, False): LABELS[2]}[present]\n            result[\'creation_counts\'][label] += 1\n            result[\'creations\'].append(dict(serial=serial, label=label, response=response, intent=intent))\n    except OSError:\n        result[\'state\'] = \'error\'\n    return result\n\n\ndef scan_launches(path):\n    result = dict(state=\'ok\', invalid_entries=0, items=[])\n    found = False\n    try:\n        info = path.lstat()\n        found = True\n        if not stat.S_ISDIR(info.st_mode):\n            result[\'state\'] = \'error\'\n            return result\n        for entry in sorted(path.iterdir(), key=lambda entry: entry.name):\n            if not re.fullmatch(r\'[0-9a-f]{32}\', entry.name) or not stat.S_ISDIR(entry.lstat().st_mode):\n                result[\'invalid_entries\'] += 1\n                result[\'state\'] = \'error\'\n                continue\n            item = scan_launch(entry)\n            result[\'items\'].append(item)\n            if item[\'state\'] == \'error\':\n                result[\'state\'] = \'error\'\n    except FileNotFoundError:\n        result[\'state\'] = \'error\' if found else \'missing\'\n    except OSError:\n        result[\'state\'] = \'error\'\n    return result\n\n\ndef empty_ledger(state):\n    return dict(state=state, counts=dict.fromkeys(STATUSES, 0), reserved_usd=None,\n                expired_reserved=0, malformed_records=0, unknown_statuses=0)\n\n\ndef unique_object(pairs):\n    obj = {}\n    for key, value in pairs:\n        if key in obj:\n            raise ValueError(\'duplicate-key\')\n        obj[key] = value\n    return obj\n\n\ndef reject_constant(value):\n    raise ValueError(\'invalid-number\')\n\n\ndef number(value):\n    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):\n        raise ValueError(\'invalid-number\')\n    value = Decimal(value)\n    if not value.is_finite() or value < 0:\n        raise ValueError(\'invalid-number\')\n    digits = value.as_tuple()\n    if len(digits.digits) > 32 or not -18 <= digits.exponent <= 18:\n        raise ValueError(\'invalid-number\')\n    return value\n\n\ndef scan_ledger(path, observed):\n    state, data = read_regular(path)\n    result = empty_ledger(\'missing\' if state == \'missing\' else \'invalid\')\n    if state != \'ok\':\n        return result\n    try:\n        ledger = json.loads(data, parse_float=Decimal, parse_constant=reject_constant,\n                            object_pairs_hook=unique_object)\n        if (not isinstance(ledger, dict) or type(ledger.get(\'version\')) is not int\n                or ledger[\'version\'] != 1 or not isinstance(ledger.get(\'reservations\'), dict)):\n            return result\n        with localcontext() as context:\n            context.prec = 64 + len(str(LIMIT))\n            context.traps[Inexact] = True\n            total = Decimal(0)\n            for record in ledger[\'reservations\'].values():\n                if not isinstance(record, dict):\n                    result[\'malformed_records\'] += 1\n                    continue\n                status = record.get(\'status\')\n                known = isinstance(status, str) and status in STATUSES\n                if known:\n                    result[\'counts\'][status] += 1\n                else:\n                    result[\'unknown_statuses\'] += 1\n                try:\n                    usd, expiry = number(record.get(\'usd\')), number(record.get(\'expires_at\'))\n                except (ValueError, InvalidOperation):\n                    result[\'malformed_records\'] += 1\n                    continue\n                if status == \'reserved\':\n                    total += usd\n                    if expiry < observed:\n                        result[\'expired_reserved\'] += 1\n            if not result[\'malformed_records\'] and not result[\'unknown_statuses\']:\n                result.update(state=\'ok\', reserved_usd=format(total, \'f\'))\n    except (ValueError, InvalidOperation, Inexact, RecursionError):\n        pass\n    return result\n\n\ndef inventory(root, home, now=None):\n    now = now or datetime.datetime.now(datetime.timezone.utc)\n    result = dict(schema=1, observed_at=now.isoformat(), activation_authorized=False,\n                  snapshot_atomic=False,\n                  outstanding_proofs=[\'historical-provenance\', \'controller-ownership\',\n                                      \'provider-creation-deletion\', \'cumulative-cost\'],\n                  launches=dict(state=\'error\', invalid_entries=0, items=[]),\n                  ledger=empty_ledger(\'invalid\'), sources={}, errors=[])\n    try:\n        root, home = canonical_directory(root), canonical_directory(home)\n    except (OSError, ValueError):\n        result[\'errors\'] = [\'invalid-root\']\n        return result\n    result[\'launches\'] = scan_launches(home / \'launches\')\n    result[\'ledger\'] = scan_ledger(home / \'boat-reservations.json\', Decimal(str(now.timestamp())))\n    if result[\'launches\'][\'state\'] == \'error\':\n        result[\'errors\'].append(\'launch-scan-error\')\n    if result[\'ledger\'][\'state\'] == \'invalid\':\n        result[\'errors\'].append(\'ledger-invalid\')\n    for name in SOURCES:\n        state, data = read_regular(root / name)\n        result[\'sources\'][name] = dict(state=state)\n        if state == \'ok\':\n            result[\'sources\'][name][\'sha256\'] = hashlib.sha256(data).hexdigest()\n        elif state != \'missing\':\n            result[\'errors\'].append(\'source-scan-error\')\n    result[\'errors\'] = sorted(set(result[\'errors\']))\n    return result\n\n\ndef main(argv=None):\n    argv = sys.argv[1:] if argv is None else argv\n    if len(argv) != 4 or set(argv[::2]) != {\'--root\', \'--control-home\'}:\n        print(\'{"error":"invalid-arguments"}\')\n        return 2\n    args = dict(zip(argv[::2], argv[1::2]))\n    result = inventory(args[\'--root\'], args[\'--control-home\'])\n    print(json.dumps(result, sort_keys=True, indent=2))\n    return int(bool(result[\'errors\']))\n\n\nif __name__ == \'__main__\':\n    sys.exit(main())\n'
import hashlib
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

ns = {"__name__": "inventory_probe"}
exec(compile(SCANNER_SOURCE, "deployment_inventory.py", "exec"), ns)
root = Path("/home/user/unbug-bench")
home = Path("/home/user/.unbug-control")
legacy = home / "launches/b275ffccd6134a33833853ad1d31ed16"
unit_names = ("unbug-key-holder.service", "unbug-resume-launches.timer",
              "unbug-resume-launches.service", "unbug-model-router.service", "unbug-batch.service")
environment = ("UNBUG_BATCH_OPERATION", "BOAT_CMD", "HCLOUD_PLACES", "UNBUG_SECRETS_FILE",
               "FACTORY_SECRETS", "OPENCODE_SECRET_NAME", "CLAUDE_SECRET_NAME",
               "FACTORY_TTL_CONTINUATION", "FACTORY_ACCOUNT_POLICY", "FACTORY_ACCOUNT_STATE")
errors = set()

def command(argv, seconds=10, extra_env=None):
    # Files cannot leave communicate waiting on inherited capture pipes.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    timeout=seconds, env={**os.environ, **(extra_env or {})})
            if result.returncode:
                errors.add("command-failed"); return None, "command-failed"
            out.seek(0); raw = out.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                errors.add("malformed-output"); return None, "malformed-output"
            return raw, "ok"
        except subprocess.TimeoutExpired:
            errors.add("timeout"); return None, "timeout"
        except OSError:
            errors.add("command-failed"); return None, "command-failed"

def hashed(path):
    state, raw = ns["read_regular"](path)
    if state == "ok": return hashlib.sha256(raw).hexdigest()
    if state != "missing": errors.add("read-failed")
    return None

def timestamps(path, directory=False):
    try:
        ns["canonical_directory"](path.parent)
        st = path.lstat()
        if not (stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode)):
            errors.add("unsupported-file"); return None
        return dict(mtime_ns=st.st_mtime_ns, ctime_ns=st.st_ctime_ns,
                    btime_ns=getattr(st, "st_birthtime_ns", None))
    except (OSError, ValueError):
        errors.add("read-failed"); return None

units = {}
for name in unit_names:
    values = {}
    for field, verb, allowed in (("active", "is-active", {"inactive", "active", "failed"}),
                                 ("enabled", "is-enabled", {"enabled", "disabled", "static", "masked", "not-found"})):
        # systemctl uses nonzero statuses for valid inactive/disabled values.
        with tempfile.TemporaryFile() as out:
            try:
                subprocess.run(["systemctl", verb, name], stdout=out, stderr=subprocess.DEVNULL,
                               stdin=subprocess.DEVNULL, timeout=10)
                out.seek(0); value = out.read(128).decode().strip()
                values[field] = value if value in allowed else "unknown"
            except (OSError, ValueError, subprocess.TimeoutExpired):
                values[field] = "unknown"; errors.add("command-failed")
    units[name] = values
scanner = ns["inventory"](root, home)
locks = {}
for item in scanner["launches"]["items"]:
    identity = item["id"]
    if any(u["active"] != "inactive" for u in units.values()):
        locks[identity] = "skipped-units-active"; errors.add("units-not-inactive"); continue
    path = home / "launches" / identity / "controller.lock"
    try:
        ns["canonical_directory"](path.parent)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError()
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locks[identity] = "free"
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally: os.close(fd)
    except FileNotFoundError: locks[identity] = "missing"
    except BlockingIOError: locks[identity] = "busy"
    except (OSError, ValueError): locks[identity] = "error"

launch = dict(cloud="other", type="other", argv="other",
              environment_present=dict.fromkeys(environment, False), unknown_environment_keys=False)
try:
    state, raw = ns["read_regular"](legacy / "launch.json")
    if state != "ok": raise ValueError()
    value = json.loads(raw, object_pairs_hook=ns["unique_object"])
    env = value["environment"]; argv = value["argv"]
    if not isinstance(env, dict): raise ValueError()
    for field, key, allowed in (("cloud", "UNBUG_CLOUD", {"boat", "hetzner"}),
                                 ("type", "BOAT_TYPE", {"small", "default", "large", "xlarge"})):
        val = env.get(key)
        launch[field] = "absent" if key not in env else val if isinstance(val, str) and val in allowed else "other"
    launch["environment_present"] = {k: k in env for k in environment}
    launch["unknown_environment_keys"] = bool(set(env) - set(environment) - {"UNBUG_CLOUD", "BOAT_TYPE"})
    if (isinstance(argv, list) and argv and all(isinstance(v, str) for v in argv)
            and re.fullmatch("[1-9][0-9]*", argv[0])): launch["argv"] = "launch"
except (ValueError, KeyError, TypeError): errors.add("read-failed")

git = dict(head=None, reflog=[], exit_label="ok")
raw, label = command(["git", "-C", str(root), "rev-parse", "HEAD"])
if label == "ok" and re.fullmatch(rb"[0-9a-f]{40}\n?", raw): git["head"] = raw.decode().strip()
else: git["exit_label"] = label if label != "ok" else "malformed-output"
raw, label = command(["git", "-C", str(root), "log", "-g", "-100", "--format=%H%x09%cI"])
if label == "ok":
    try:
        for line in raw.decode().splitlines():
            commit, stamp = line.split("\t")
            if not re.fullmatch("[0-9a-f]{40}", commit) or datetime.datetime.fromisoformat(stamp).tzinfo is None: raise ValueError()
            git["reflog"].append(dict(commit=commit, committed_at=stamp))
    except (ValueError, UnicodeError):
        git.update(reflog=[], exit_label="malformed-output"); errors.add("malformed-output")
else: git["exit_label"] = label

fleet = dict(readable=False, page_complete=False, worker_ids=[], exit_label="ok")
raw, label = command([str(root / "bin/boat-call"), "list", "--json"], 105,
                     {"BOAT_COMMAND_TIMEOUT_SECONDS": "30", "BOAT_NO_UPDATE": "1"})
fleet["exit_label"] = label
if label == "ok":
    try:
        value = json.loads(raw); rows = value["sandboxes"]; more = value["pageInfo"]["hasMore"]
        if not isinstance(rows, list) or type(more) is not bool: raise ValueError()
        ids = [r["id"] for r in rows]
        if any(not isinstance(v, str) or not re.fullmatch("[A-Za-z0-9_-]+", v) for v in ids) or len(set(ids)) != len(ids): raise ValueError()
        fleet.update(readable=True, page_complete=not more, worker_ids=sorted(ids))
    except (ValueError, TypeError, KeyError):
        fleet["exit_label"] = "malformed-output"; errors.add("malformed-output")

cli_path = Path("/home/user/.ascii/bin/boat")
cli = dict(version=None, sha256=None, format="missing", exit_label="ok")
try:
    fd = os.open(cli_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ValueError()
        magic = stream.read(4); digest = hashlib.sha256(magic)
        for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
    cli["sha256"] = digest.hexdigest()
    cli["format"] = ("elf" if magic == b"\x7fELF" else "macho" if magic in
                     (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf") else "source" if magic.startswith(b"#!") else "other")
except (OSError, ValueError): cli["exit_label"] = "read-failed"; errors.add("read-failed")
raw, label = command([str(cli_path), "--version"], extra_env={"BOAT_NO_UPDATE": "1"})
if label == "ok":
    match = re.fullmatch(rb"(?:boat\s+)?v?([0-9]+\.[0-9]+\.[0-9]+)\s*", raw)
    if match: cli["version"] = match[1].decode()
    else: cli["exit_label"] = "malformed-output"; errors.add("malformed-output")
else: cli["exit_label"] = label
metadata = {name: timestamps(root / name) for name in ns["SOURCES"]}
metadata.update(directory=timestamps(legacy, True), **{n: timestamps(legacy / n) for n in ("launch.json", "controller.lock")})
result = dict(schema=1, observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              activation_authorized=False, snapshot_atomic=False,
              scanner=scanner, scanner_sha256=hashlib.sha256(SCANNER_SOURCE.encode()).hexdigest(),
              units=units, unit_file_sha256={n: hashed(Path("/etc/systemd/system") / n) for n in unit_names},
              policy_sha256=hashed(home / "policy.json"),
              staged_release_sha256=hashed(home / "releases/practice-6ac450e/batch-release.json"),
              locks=locks, legacy=dict(metadata=metadata, launch=launch, git=git),
              fleet=fleet, cli=cli, errors=sorted(errors))
print(json.dumps(result, indent=2, sort_keys=True))
