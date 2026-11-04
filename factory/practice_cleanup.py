"""Independent cleanup on the existing practice/pilot operation path."""
import argparse
import fcntl
import hashlib
import json
import math
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
import pilot
from registry import atomic_json
from transfer import digest

UNIT = "unbug-practice-cleanup@.service"
PILOT_UNIT = "unbug-pilot-cleanup.service"


def location(home, op):
    return home / "batches" / op["authority"]["batch"] / "cleanup" / op["operation_id"]


def ready(policy, op, pid):
    from key_holder import policy_digest
    return dict(schema=1, operation_id=op["operation_id"], launch_id=op["launch_id"],
                timing=practice.TIMING, policy_sha256=policy_digest(policy), pid=pid)


def armed(policy, root, home, op, operations=None):
    is_pilot = pilot.active(policy, root)
    if not is_pilot and not practice.active(policy, root): return
    record = money.manifest(policy, root)
    if is_pilot:
        pilot.admission(record)
        pilot.history(record, operations)
        for other in operations.values():
            if other['operation_id'] == op['operation_id'] or not other['dispatch_started']: continue
            if preflight_clear(home, other): continue
            try:
                status = service._json(location(home, other).with_suffix('.status.json'))
                if (type(status['schema']) is not int or status['schema'] != 1 or
                        status['operation_id'] != other['operation_id'] or
                        status['state'] != 'complete'): raise ValueError()
            except (OSError, ValueError, KeyError, TypeError):
                raise money.MoneyWait('cleanup not settled') from None
    else: practice.admission(record)
    unit = PILOT_UNIT if is_pilot else UNIT
    instance = unit if is_pilot else 'unbug-practice-cleanup@' + op['operation_id'] + '.service'
    try:
        if os.environ.get("UNBUG_CLOUD") != "boat": raise ValueError()
        if digest(Path("/etc/systemd/system") / unit) != digest(root / "control" / unit): raise ValueError()
        marker = service._json(location(home, op).with_suffix(".ready.json"))
        response = subprocess.run(["systemctl", "show", instance,
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


def bound_spend(home, path, *, absent_ok=False):
    # Missing ledger is unknown. Never let read_ledger's admission default prove absence.
    ledger_path = home / 'boat-reservations.json'
    ledger = boat_lifecycle.read_ledger(ledger_path, missing_ok=False)
    matches = [record for record, row in ledger['reservations'].items()
               if row.get('state_path') == str(path.resolve())]
    if not matches and absent_ok: return None
    if len(matches) != 1: raise ValueError('unknown spend binding')
    return Path(matches[0])


def preflight_clear(home, op):
    """Prove no creation and no reservation, never infer deletion from absence."""
    if not (op['dispatch_started'] and op['state'] == 'failed' and
            op.get('incident') == 'preflight_refused' and op.get('worker_id') is None): return False
    path = home / 'launches' / op['launch_id']
    directory = home / 'batches' / op['authority']['batch']
    try:
        with holder.operation_lock(directory, op['operation_id']):
            if path.is_symlink() or not path.is_dir(): return False
            # _reconcile_one fences a launch that never reached control_resume by
            # creating its empty directory while holding this same operation lock.
            entries = list(path.iterdir())
            if entries:
                if service._json(path / 'launch.json') != op['launch']: return False
                with service._regular(path / 'controller.lock') as controller:
                    fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if list(path.glob('new.*')): return False
                    try: ids = boat_lifecycle.regular(path / 'ids').strip()
                    except FileNotFoundError: ids = b''
                    if ids: return False
                    return no_reservation(home, path)
            return no_reservation(home, path)
    except (OSError, ValueError, KeyError, TypeError): return False



def preallocation_settlement(home, op):
    """Certify an immutable failed launch with durable settled-zero no-creation proof."""
    from carry_over import digest as value_digest
    if not (op['dispatch_started'] is True and op['state'] == 'failed' and
            op['incident'] == 'preflight_refused' and
            all(op[k] is None for k in ('worker_id','output_generation','retirement'))):
        raise ValueError('not a preallocation failure')
    path = home / 'launches' / op['launch_id']
    directory = home / 'batches' / op['authority']['batch']
    if path.is_symlink() or not path.is_dir(): raise ValueError('unsafe launch')
    with holder.operation_lock(directory, op['operation_id']):
        with service._regular(path / 'controller.lock') as controller:
            fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
            names = ('launch.json','ids','complete','spend-finished')
            raw = {n: boat_lifecycle.regular(path / n) for n in names}
            if (json.loads(raw['launch.json']) != op['launch'] or raw['ids'].strip() or
                    list(path.glob('new.*'))): raise ValueError('creation not excluded')
            with service._regular(home / 'boat-reservations.lock') as lock:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                spend = bound_spend(home, path)
                row = boat_lifecycle.read_ledger(home / 'boat-reservations.json', missing_ok=False)['reservations'][str(spend)]
                if (row['status'] != 'settled' or row['settlement']['basis'] != 'no_creation' or
                        row['settlement']['workers'] != [] or boat_lifecycle.settlement_amount(row) != 0 or
                        boat_lifecycle.number(row['actual_spend_usd']) != 0):
                    raise ValueError('unsettled creation liability')
                spend_raw = boat_lifecycle.regular(spend); data = boat_lifecycle.loads(spend_raw)
                if (data.get('provider') != 'boat' or data.get('allowed') is not True or
                        data.get('ids') != [] or any(type(data.get(k)) is not int for k in ('vms','ttl_seconds')) or
                        data.get('settlement') != row['settlement'] or
                        data.get('finished_at') != row.get('finished_at') or
                        data.get('vms') != row['vms'] or data.get('ttl_seconds') != row['ttl_seconds'] or
                        boat_lifecycle.number(data['max_spend_usd']) != boat_lifecycle.number(row['max_spend_usd']) or
                        boat_lifecycle.number(data['actual_spend_usd']) != 0):
                    raise ValueError('spend proof mismatch')
                boat_lifecycle.timestamp(data['finished_at'])
                status_path = location(home, op).with_suffix('.status.json')
                status_raw = boat_lifecycle.regular(status_path); status = json.loads(status_raw)
                if (type(status.get('schema')) is not int or status.get('schema') != 1 or
                        status.get('operation_id') != op['operation_id'] or
                        status.get('state') != 'complete' or status.get('settlement') != 'settled' or
                        status.get('workers') != []): raise ValueError('cleanup not complete')
                stable = {k: row[k] for k in ('status','state_path','vms','ttl_seconds','max_spend_usd',
                                             'finished_at','actual_spend_usd','settlement')}
                raw.update(spend=spend_raw, cleanup=status_raw)
                return dict(schema=1, operation_id=op['operation_id'], launch_id=op['launch_id'],
                            files={n: hashlib.sha256(v).hexdigest() for n,v in raw.items()},
                            settlement_sha256=value_digest(stable))


def no_reservation(home, path):
    # Existing lock only: an absent ledger/lock does not establish clearance.
    with service._regular(home / 'boat-reservations.lock') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return bound_spend(home, path, absent_ok=True) is None


def settle(root, home, op, path, spend, result, now):
    target = location(home, op).with_suffix('.status.json')
    previous = service._json(target) if target.exists() else {}
    last = previous.get('settlement_attempted_at')
    if last is not None and (type(last) not in (int, float) or not math.isfinite(last) or last < 0):
        raise ValueError('invalid settlement timestamp')
    result.update(state='settlement_pending', settlement='pending', settlement_attempted_at=last)
    if last is not None and now < last + 60: return
    result['settlement_attempted_at'] = now
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(target, result)
    # No output from the provider or arbitrary subprocess diagnostics enters status.
    try:
        response = subprocess.run([str(root / 'bin/boat-spend'), '--settle', str(spend), str(path)],
                                  capture_output=True, timeout=180,
                                  env={**os.environ, 'UNBUG_CONTROL_HOME': str(home)})
        if response.returncode == 0: result.update(state='complete', settlement='settled')
    except (OSError, subprocess.SubprocessError): pass


def step(policy, root, home, op, now=None):
    """One observation; absence is never a deletion receipt. No replayed creation."""
    now = time.time() if now is None else now
    result = dict(schema=1, operation_id=op["operation_id"], deadline=None, state="waiting", workers=[],
                  settlement="not_attempted", settlement_attempted_at=None)
    previous_path = location(home, op).with_suffix('.status.json')
    if previous_path.exists():
        try:
            previous = service._json(previous_path)
            result['settlement_attempted_at'] = previous.get('settlement_attempted_at')
        except (OSError, ValueError, TypeError):
            result['state'] = 'uncertain'
            return result
    if not op["dispatch_started"]:
        if op["state"] == "failed": result["state"] = "not_dispatched"
        return result
    path = home / "launches" / op["launch_id"]
    try:
        if service._json(path / "launch.json") != op["launch"]: raise ValueError("launch mismatch")
        if not list(path.glob("new.*")) and (path / 'spend-finished').exists():
            with service._regular(path / 'spend-finished'): pass
            with service._regular(path / 'ids') as stream: empty = not stream.read().strip()
            if empty:
                settle(root, home, op, path, bound_spend(home, path), result, now)
                return result
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
                if now >= deadline or os.path.lexists(path / (worker + ".collected")) or os.path.lexists(path / (worker + ".retiring.json")):
                    result["state"] = "deleting"
                    boat_lifecycle.delete_receipt(root, spend, worker, path / "ids", delete_due=deadline)
        result["deadline"] = min(deadlines)
        # A deadline safety winner invalidated accounting; no inventory/meter work
        # may delay its safety path or turn it into exact settlement.
        if any(os.path.lexists(path / (w + '.metering-bypassed')) for w in workers):
            result.update(state='settlement_pending', settlement='unknown')
            return result
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
                settle(root, home, op, path, spend, result, now)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        result["state"] = "uncertain"
    return result


def observe_batch(policy, root, home, operations, terminal):
    """Arm all identities first, then service live workers before retained proof."""
    for op in operations.values():
        target = location(home, op)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        atomic_json(target.with_suffix('.ready.json'), ready(policy, op, os.getpid()))
    def order(op):
        if op['operation_id'] in terminal: return 3
        try:
            retained = service._json(location(home, op).with_suffix('.status.json'))
            if (retained.get('schema') == 1 and retained.get('operation_id') == op['operation_id'] and
                    retained.get('state') in ('complete', 'not_dispatched', 'window_closed')): return 3
        except (OSError, ValueError, TypeError): pass
        if op['dispatch_started']: return 0 if op['retirement'] is None else 1
        return 2
    for op in sorted(operations.values(), key=order):
        identity = op['operation_id']
        if identity in terminal: continue
        if preflight_clear(home, op):
            status = dict(schema=1, operation_id=identity, deadline=None, workers=[],
                          state='not_dispatched', basis='preflight_no_reservation')
        else:
            status = step(policy, root, home, op)
            if not op['dispatch_started'] and status['state'] == 'waiting':
                record = money.manifest(policy, root)
                try: pilot.admission(record)
                except money.MoneyWait: status['state'] = 'window_closed'
        atomic_json(location(home, op).with_suffix('.status.json'), status)
        if status['state'] in ('complete', 'not_dispatched', 'window_closed'): terminal.add(identity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--operation')
    mode.add_argument('--batch', action='store_true')
    a = parser.parse_args()
    from key_holder import policy_load, ROOT, CONTROL_HOME
    if os.environ.get('UNBUG_CLOUD') != 'boat': raise ValueError('request_refused')
    policy = policy_load(CONTROL_HOME / 'policy.json')
    if not (pilot.active(policy, ROOT) if a.batch else practice.active(policy, ROOT)):
        raise ValueError('request_refused')
    record = money.manifest(policy, ROOT)
    terminal = set()
    while True:
        # Cloud/subprocess work occurs after releasing the existing batch lock.
        with money.locked(CONTROL_HOME, record['id']) as directory:
            operations = holder._operations(directory, record, policy)
        if a.batch:
            pilot.history(record, operations)
            observe_batch(policy, ROOT, CONTROL_HOME, operations, terminal)
        else:
            op = operations[a.operation]
            target = location(CONTROL_HOME, op)
            target.parent.mkdir(mode=0o700, exist_ok=True)
            atomic_json(target.with_suffix('.ready.json'), ready(policy, op, os.getpid()))
            status = step(policy, ROOT, CONTROL_HOME, op)
            atomic_json(target.with_suffix('.status.json'), status)
            if status['state'] in ('complete', 'not_dispatched'): return 0
        time.sleep(5)


if __name__ == "__main__":
    try: raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError): raise SystemExit("practice cleanup refused")
