"""Host-only Boat filesystem readiness gate; never part of the worker release."""
import argparse
import datetime
import json
import math
import os
from pathlib import Path
import subprocess
import time


def wait_ready(command, worker, vm_type, ttl, requested_mono, requested_wall,
               margin, receipt, controller_deadline=math.inf):
    """Wait within the original lifetime, retaining only public allowlisted metadata."""
    deadline = min(requested_mono + ttl - margin, time.monotonic() + 600,
                   controller_deadline)
    record = {'worker_id': worker, 'requested_at': requested_wall,
              'deadline_monotonic': deadline, 'attempts': 0, 'outcome': 'refused'}
    try:
        if not all(math.isfinite(x) for x in (ttl, requested_mono, requested_wall, margin, deadline)) or margin <= 0 or ttl <= margin:
            raise ValueError('invalid readiness envelope')
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('readiness deadline reached')
            record['attempts'] += 1
            # boat-call owns/kills the provider process group on timeout or TERM.
            proc = subprocess.Popen([command, 'info', worker, '--json'],
                stdout=subprocess.PIPE, stderr=None, text=True,
                env={**os.environ, 'BOAT_COMMAND_TIMEOUT_SECONDS': str(min(120, remaining))})
            try:
                raw, _ = proc.communicate(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.communicate()
                raise TimeoutError('readiness query exceeded deadline') from None
            if time.monotonic() >= deadline:
                raise TimeoutError('readiness response after deadline')
            if proc.returncode:
                raise ValueError('readiness provider query failed')
            current = json.loads(raw)['sandbox']
            if not isinstance(current, dict):
                raise ValueError('invalid sandbox')
            # Never retain profiles, addresses, environment or arbitrary error text.
            record['observed'] = {k: current.get(k) for k in
                ('id', 'type', 'ttlSeconds', 'archiveAfter', 'hydrated', 'hydratedAt',
                 'state', 'health', 'holdsCreatorLogins', 'monitoring', 'snapshots')
                if current.get(k) is None or type(current.get(k)) in (str, bool, int, float)}
            record['provider_error'] = bool(current.get('error') or current.get('setupError'))
            if (current['id'] != worker or current['type'] != vm_type or
                    type(current['ttlSeconds']) is not int or current['ttlSeconds'] != ttl or
                    any(current[k] is not False for k in ('holdsCreatorLogins', 'monitoring', 'snapshots'))):
                raise ValueError('readiness identity or creation invariants mismatch')
            expiry = datetime.datetime.fromisoformat(current['archiveAfter'].replace('Z', '+00:00'))
            if expiry.tzinfo is None:
                raise ValueError('expiry lacks timezone')
            # Convert provider expiry against the original clock pair; never refresh TTL.
            deadline = min(deadline, requested_mono + expiry.timestamp() - requested_wall - margin)
            record['deadline_monotonic'] = deadline
            if time.monotonic() >= deadline:
                raise TimeoutError('no readiness interval before collection reserve')
            # 2026-10-23: Boat reports a booted, healthy sandbox as 'ready' (seen live from the control VM).
            if (current['state'] not in ('idle', 'running', 'ready') or current['health'] != 'ok' or
                    current['error'] is not None or current['setupError'] is not None or
                    current['setupStatus'] not in (None, 'completed') or
                    current['degradedSince'] is not None):
                raise ValueError('provider is not healthy')
            if type(current['hydrated']) is not bool or 'hydration' not in current:
                raise ValueError('missing or malformed hydration completion')
            progress = current['hydration']
            record['hydration_phase'] = progress.get('phase') if isinstance(progress, dict) else None
            if progress is not None:
                # Phase names describe work, not completion. Observed folding and
                # future well-formed phases remain incomplete within the same deadline.
                if (not isinstance(progress, dict) or
                        not isinstance(progress.get('phase'), str) or not progress['phase'].strip() or
                        progress['phase'].lower() in ('failed', 'error', 'degraded', 'cancelled', 'canceled')):
                    raise ValueError('failed or malformed hydration progress')
                if (type(progress.get('entriesDone')) is not int or progress['entriesDone'] < 0 or
                        any(progress.get(k) is not None and type(progress[k]) is not int
                            for k in ('entriesTotal', 'percent')) or
                        not all(k in progress for k in ('entriesTotal', 'percent'))):
                    raise ValueError('malformed hydration progress')
                if (progress['entriesTotal'] is not None and progress['entriesTotal'] < 0 or
                        progress['percent'] is not None and not 0 <= progress['percent'] <= 99):
                    raise ValueError('invalid hydration progress range')
            if current['hydrated'] is True:
                if progress is not None:
                    raise ValueError('contradictory hydration completion')
                if time.monotonic() >= deadline:
                    raise TimeoutError('readiness completed after deadline')
                record['outcome'] = 'ready'
                return record
            time.sleep(min(10, max(0, deadline - time.monotonic())))
    except Exception as exc:
        record['failure_type'] = type(exc).__name__
        raise
    finally:
        record['finished_at'] = time.time()
        target = Path(receipt)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(record, out, sort_keys=True, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command')
    parser.add_argument('worker')
    parser.add_argument('vm_type')
    for name in ('ttl', 'requested_mono', 'requested_wall', 'margin'):
        parser.add_argument(name, type=float)
    parser.add_argument('receipt')
    args = parser.parse_args()
    wait_ready(**vars(args))


if __name__ == '__main__':
    main()
