#!/usr/bin/env python3
"""Observe local deployment metadata. Never authorizes cleanup or activation."""
import boat_lifecycle
from boat_lifecycle import unique_object, reject_constant, number
import datetime
from decimal import Decimal, Inexact, InvalidOperation, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

LIMIT = 8 * 1024 * 1024
SOURCES = ('factory/control_resume.py', 'factory/launch.sh',
           'bin/boat-launch-guards.sh', 'bin/boat-spend')
FILES = ('launch.json', 'controller.lock', 'monitor.sh', 'ids', 'complete',
         'spend-finished', 'cleanup-status.json')
LABELS = ('intent-only', 'response-and-intent', 'response-without-marker')
TYPES = ('file', 'directory', 'symlink', 'other')
STATUSES = ('reserved', 'finished', 'reconciled_expired', 'settled')


def kind(mode):
    for test, name in ((stat.S_ISREG, 'file'), (stat.S_ISDIR, 'directory'),
                       (stat.S_ISLNK, 'symlink')):
        if test(mode):
            return name
    return 'other'


def canonical_directory(path):
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        if not stat.S_ISDIR(part.lstat().st_mode):
            raise ValueError('invalid-root')
    return path


def metadata(path):
    try:
        info = path.lstat()
        return dict(state='present', type=kind(info.st_mode), size=info.st_size,
                    mtime_ns=info.st_mtime_ns)
    except FileNotFoundError:
        return dict(state='missing')
    except OSError:
        return dict(state='error')


def signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_regular(path):
    """Read only a bounded regular file with stable metadata, without following links."""
    before = None
    try:
        canonical_directory(path.parent)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT:
            return 'unsupported', None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if signature(opened) != signature(before):
                return 'changed', None
            data = stream.read(LIMIT + 1)
            after = os.fstat(stream.fileno())
        if len(data) > LIMIT:
            return 'unsupported', None
        if signature(before) != signature(after) or signature(before) != signature(path.lstat()):
            return 'changed', None
        return 'ok', data
    except FileNotFoundError:
        return ('changed' if before is not None else 'missing'), None
    except ValueError:
        return 'unsupported', None
    except OSError:
        return 'error', None


def scan_launch(path):
    result = dict(id=path.name, state='ok', files={}, creations=[],
                  creation_counts=dict.fromkeys(LABELS, 0), unknown_entries=0)
    for suffix in ('deleted', 'parked', 'keep'):
        result[suffix + '_markers'] = dict.fromkeys(TYPES, 0)
    for name in FILES:
        observation = metadata(path / name)
        result['files'][name] = observation
        if observation['state'] == 'error' or (observation['state'] == 'present' and observation['type'] != 'file'):
            result['state'] = 'error'
    try:
        entries = list(path.iterdir())
        serials = set()
        for entry in entries:
            name = entry.name
            if name in FILES:
                continue
            match = re.fullmatch(r'new\.([0-9]+)(\.pending)?', name)
            if match:
                serials.add(match[1])
                continue
            match = re.fullmatch(r'[A-Za-z0-9_-]+\.(deleted|parked|keep)', name)
            if match:
                observation = metadata(entry)
                if observation['state'] != 'present':
                    result['state'] = 'error'
                else:
                    result[match[1] + '_markers'][observation['type']] += 1
                continue
            result['unknown_entries'] += 1
        for serial in sorted(serials):
            response = metadata(path / ('new.' + serial))
            intent = metadata(path / ('new.' + serial + '.pending'))
            for observation in (response, intent):
                if observation['state'] == 'error' or (observation['state'] == 'present' and observation['type'] != 'file'):
                    result['state'] = 'error'
            present = (response['state'] == 'present', intent['state'] == 'present')
            # A listed file that disappears makes this scan incomplete.
            if present == (False, False):
                result['state'] = 'error'
                continue
            label = {(False, True): LABELS[0], (True, True): LABELS[1], (True, False): LABELS[2]}[present]
            result['creation_counts'][label] += 1
            result['creations'].append(dict(serial=serial, label=label, response=response, intent=intent))
    except OSError:
        result['state'] = 'error'
    return result


def scan_launches(path):
    result = dict(state='ok', invalid_entries=0, items=[])
    found = False
    try:
        info = path.lstat()
        found = True
        if not stat.S_ISDIR(info.st_mode):
            result['state'] = 'error'
            return result
        for entry in sorted(path.iterdir(), key=lambda entry: entry.name):
            if not re.fullmatch(r'[0-9a-f]{32}', entry.name) or not stat.S_ISDIR(entry.lstat().st_mode):
                result['invalid_entries'] += 1
                result['state'] = 'error'
                continue
            item = scan_launch(entry)
            result['items'].append(item)
            if item['state'] == 'error':
                result['state'] = 'error'
    except FileNotFoundError:
        result['state'] = 'error' if found else 'missing'
    except OSError:
        result['state'] = 'error'
    return result


def empty_ledger(state):
    return dict(state=state, counts=dict.fromkeys(STATUSES, 0), reserved_usd=None, settled_usd=None,
                expired_reserved=0, malformed_records=0, unknown_statuses=0)


def scan_ledger(path, observed):
    state, data = read_regular(path)
    result = empty_ledger('missing' if state == 'missing' else 'invalid')
    if state != 'ok':
        return result
    try:
        ledger = json.loads(data, parse_float=Decimal, parse_constant=reject_constant,
                            object_pairs_hook=unique_object)
        if (not isinstance(ledger, dict) or type(ledger.get('version')) is not int
                or ledger['version'] != 1 or not isinstance(ledger.get('reservations'), dict)):
            return result
        with localcontext() as context:
            context.prec = 64 + len(str(LIMIT))
            context.traps[Inexact] = True
            total = Decimal(0)
            settled = Decimal(0)
            for record in ledger['reservations'].values():
                if not isinstance(record, dict):
                    result['malformed_records'] += 1
                    continue
                status = record.get('status')
                known = isinstance(status, str) and status in STATUSES
                if known:
                    result['counts'][status] += 1
                else:
                    result['unknown_statuses'] += 1
                try:
                    usd, expiry = number(record.get('usd')), number(record.get('expires_at'))
                except (ValueError, InvalidOperation):
                    result['malformed_records'] += 1
                    continue
                if status == 'settled':
                    try: settled += boat_lifecycle.settlement_amount(record)
                    except (ValueError, KeyError, TypeError, InvalidOperation):
                        result['malformed_records'] += 1
                if status == 'reserved':
                    total += usd
                    if expiry < observed:
                        result['expired_reserved'] += 1
            if not result['malformed_records'] and not result['unknown_statuses']:
                result.update(state='ok', reserved_usd=format(total, 'f'), settled_usd=format(settled, 'f'))
    except (ValueError, InvalidOperation, Inexact, RecursionError):
        pass
    return result


def inventory(root, home, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    result = dict(schema=1, observed_at=now.isoformat(), activation_authorized=False,
                  snapshot_atomic=False,
                  outstanding_proofs=['historical-provenance', 'controller-ownership',
                                      'provider-creation-deletion', 'cumulative-cost'],
                  launches=dict(state='error', invalid_entries=0, items=[]),
                  ledger=empty_ledger('invalid'), sources={}, errors=[])
    try:
        root, home = canonical_directory(root), canonical_directory(home)
    except (OSError, ValueError):
        result['errors'] = ['invalid-root']
        return result
    result['launches'] = scan_launches(home / 'launches')
    result['ledger'] = scan_ledger(home / 'boat-reservations.json', Decimal(str(now.timestamp())))
    if result['launches']['state'] == 'error':
        result['errors'].append('launch-scan-error')
    if result['ledger']['state'] == 'invalid':
        result['errors'].append('ledger-invalid')
    for name in SOURCES:
        state, data = read_regular(root / name)
        result['sources'][name] = dict(state=state)
        if state == 'ok':
            result['sources'][name]['sha256'] = hashlib.sha256(data).hexdigest()
        elif state != 'missing':
            result['errors'].append('source-scan-error')
    result['errors'] = sorted(set(result['errors']))
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 4 or set(argv[::2]) != {'--root', '--control-home'}:
        print('{"error":"invalid-arguments"}')
        return 2
    args = dict(zip(argv[::2], argv[1::2]))
    result = inventory(args['--root'], args['--control-home'])
    print(json.dumps(result, sort_keys=True, indent=2))
    return int(bool(result['errors']))


if __name__ == '__main__':
    sys.exit(main())
