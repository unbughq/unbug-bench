"""Judge-owned, read-only sampling of a live shop. No traffic or reset in probes.

Intervals use a monotonic clock. A sample describes the following interval (left
rectangle); missing/late observations are unknown, never silently safe. This is
observed unsafe shop state, not a counterfactual proof that a guard would fail.
"""
import asyncio
import json
import math
import time


def window_config(scenario):
    config = scenario.get('window', {})
    if not isinstance(config, dict):
        raise ValueError('unannounced window must be an object')
    duration, interval = config.get('duration_sec'), config.get('interval_sec')
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0
           for x in (duration, interval)) or interval > duration:
        raise ValueError('unannounced window needs finite duration_sec >= interval_sec > 0')
    return config


def integrate(samples, duration, interval, paths):
    totals = {p: {'unsafe_seconds': 0., 'unsafe_claimed_protected_seconds': 0.,
                  'unknown_seconds': 0.} for p in paths}
    previous = 0.
    for index, sample in enumerate(samples):
        start = min(duration, max(previous, sample['elapsed_sec']))
        end = min(duration, samples[index + 1]['elapsed_sec'] if index + 1 < len(samples) else duration)
        end = max(start, end)
        for path, row in totals.items():
            row['unknown_seconds'] += start - previous
            state = sample.get('paths', {}).get(path)
            # A hung read cannot describe an arbitrarily long interval.
            known = min(end - start, interval * 1.5) if type(state) is bool else 0.
            row['unknown_seconds'] += end - start - known
            if state is True:
                row['unsafe_seconds'] += known
                if sample.get('claims', {}).get(path) == 'protected':
                    row['unsafe_claimed_protected_seconds'] += known
        previous = end
    if not samples:
        for row in totals.values(): row['unknown_seconds'] = duration
    return {'duration_seconds': duration, 'interval_seconds': interval,
            'estimator': 'left-rectangle; stale intervals unknown', 'paths': totals,
            'samples': samples, 'valid': all(v['unknown_seconds'] < 1e-6 for v in totals.values())}


async def observe(config, paths, probe, read_claims, *, clock=time.monotonic, sleep=asyncio.sleep):
    duration, interval = config['duration_sec'], config['interval_sec']
    samples, start, tick = [], clock(), 0
    while tick * interval < duration:
        await sleep(max(0, start + tick * interval - clock()))
        elapsed = clock() - start
        if elapsed >= duration: break
        sample = {'elapsed_sec': 0. if tick == 0 else elapsed}
        try:
            # Claim snapshot precedes the probe; withdrawal during a read does not
            # retroactively erase time spent claiming protection.
            report = await read_claims()
            sample['claims'] = {c['path']: c['status'] for c in report.get('claims', [])}
            sample['paths'] = await probe()
            sample['read_seconds'] = clock() - start - elapsed
            if sample['read_seconds'] > interval:
                sample.update(paths={}, error='ProbeOverranInterval')
        except Exception as error:
            sample.update(paths={}, claims=sample.get('claims', {}), error=type(error).__name__)
        samples.append(sample)
        tick += 1
    await sleep(max(0, start + duration - clock()))
    return integrate(samples, duration, interval, paths)


def checkpoint(exposure, report, key, delivery='unannounced'):
    import claims
    paths = {p: {'runs': 1, 'violated_runs': int(v['unsafe_seconds'] > 0)}
             for p, v in exposure['paths'].items()}
    summary = {'delivery': delivery, 'runs': 1, 'error_runs': int(not exposure['valid']),
               'invalid_runs': int(not exposure['valid']), 'paths': paths, 'checks': {},
               'legit': {'attempted': 0, 'placed': 0}, 'legit_completion': 1.,
               'key': key, 'exposure': exposure, 'latest_claims': report,
               'pass_runs': int(exposure['valid'] and not any(p['violated_runs'] for p in paths.values()))}
    summary['claims_score'] = claims.score(report, summary, key)
    return summary
