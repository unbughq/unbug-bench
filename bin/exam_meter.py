"""Only subscription meter metadata may leave a sealed case. No log paths or bodies."""
import datetime
import json
import math
import pathlib
import time

FIELDS = {'timestamp', 'status', 'http_status', '5h-utilization', '7d-utilization',
          '5h-reset', '7d-reset', 'reset', 'retry-after'}


def limited(row):
    return str(row.get('http_status', row.get('status'))) == '429' or row.get('status') == 'rejected'


def rows_under(directory):
    rows = []
    for path in pathlib.Path(directory).rglob('claude-meter.jsonl'):
        try:
            for line in path.read_text().splitlines():
                try:
                    row = json.loads(line)
                    rows.append({k: v for k, v in row.items() if k in FIELDS})
                except (ValueError, AttributeError):
                    pass  # a concurrently appended final row may be incomplete
        except OSError:
            pass
    # Harbor artifacts can contain cumulative duplicates; timestamps order responses.
    return sorted(rows, key=lambda r: r.get('timestamp', ''))


def epoch(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        try:
            result = datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
        except ValueError:
            return None
    return result if math.isfinite(result) else None


def merge(meter, rows):
    for row in sorted(rows, key=lambda r: r.get('timestamp', '')):
        if row.get('timestamp', '') < meter.get('timestamp', ''):
            continue
        meter.update({k: v for k, v in row.items() if k in FIELDS})
        meter['_hold_until'] = max(meter.get('_hold_until', 0), row.get('_hold_until', 0))
        if row.get('_unknown_reset'):
            meter['_unknown_reset'] = True
        windows = []
        for window, threshold in (('5h', .85), ('7d', .95)):
            try:
                if float(meter.get(window + '-utilization', 0)) >= threshold:
                    windows.append(window)
            except (ValueError, TypeError):
                windows.append(window)  # malformed usage must not permit another start
        reject = limited(row)
        if windows or reject:
            generic = epoch(meter.get('reset'))
            retry = epoch(row.get('retry-after'))
            stamp = epoch(row.get('timestamp'))
            if retry is not None and stamp is not None:
                generic = max(generic or 0, stamp + retry)
            resets = []
            for window in (windows or ['5h', '7d']):
                bounds = [r for r in (epoch(meter.get(window + '-reset')), generic) if r is not None]
                resets.append(max(bounds) if bounds else None)
            # A rejection needs one reported reset; every explicitly high window needs its own.
            known = [r for r in resets if r is not None]
            unknown = (any(r is None for r in resets) if windows else not known)
            if known:
                meter['_hold_until'] = max(meter.get('_hold_until', 0), *known)
            if unknown:
                meter['_unknown_reset'] = True
            else:
                meter.pop('_unknown_reset', None)
        elif not limited(meter) and not row.get('_unknown_reset'):
            meter.pop('_unknown_reset', None)
    return meter


def ready(meter, now=None):
    return not meter.get('_unknown_reset') and meter.get('_hold_until', 0) <= (time.time() if now is None else now)


if __name__ == '__main__':
    # Invoked over SSH with sudo: volume files are not readable by the VM user.
    rows = rows_under('/var/lib/docker/volumes') + rows_under(pathlib.Path('/home/user/exam-private'))
    print(json.dumps(merge({}, rows)))
