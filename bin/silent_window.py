"""Shared live-window judge for Harbor and deterministic strategy simulations."""
import asyncio
import json
import shlex
import time
import tempfile
from pathlib import Path
import exposure
import claims
from live_shop import LiveShop, LocalReader

async def execute(environment, command, timeout_sec=120):
    result = await environment.exec(command, user='root', timeout_sec=timeout_sec)
    if result.return_code:
        detail = result.stderr or result.stdout or ''
        raise RuntimeError(f'live judge command failed ({result.return_code}): {detail[-2000:]}')
    return result.stdout or ''


def readers(environment, spec):
    async def command(text): return await execute(environment, text)
    trusted = getattr(environment, '_phase2_reader', None)
    shop = LiveShop(command, spec, trusted) if spec.get('probe_kind') == 'medusa' else None
    async def report():
        path = spec.get('claims_path', '/app/claims.json')
        try:
            raw = (await trusted.claims(path) if trusted else json.loads(await execute(environment,
                'if test -f ' + shlex.quote(path) + '; then cat ' + shlex.quote(path) + "; else printf '{}'; fi")))
            rows = raw.get('claims') if isinstance(raw, dict) else None
            valid = (isinstance(raw, dict) and raw.get('response') in claims.RESPONSES and isinstance(rows, list)
                     and all(isinstance(r, dict) and isinstance(r.get('path'), str)
                             and r.get('status') in claims.STATUSES for r in rows)
                     and len({r['path'] for r in rows}) == len(rows))
            if valid: environment._phase2_latest_claims = raw
        except Exception:
            # A missing/truncated/corrupt file cannot withdraw a previous report.
            # Database probing still runs, independently of claim-file health.
            pass
        return getattr(environment, '_phase2_latest_claims', {})
    async def probe():
        if shop: return await shop.probe()
        output = {}
        for command in spec['probes']:
            values = json.loads(await execute(environment, command))
            if not isinstance(values, dict) or any(type(v) is not bool for v in values.values()):
                raise ValueError('probe must return path -> boolean unsafe')
            output.update(values)
        return output
    return shop, command, report, probe


class LiveMonitor:
    """Sample throughout the trial, so probes starting cannot announce a window.

    The host owns this task and its buffer; neither enters contestant artifacts.
    """
    def __init__(self, environment, spec):
        self.spec, self.samples = spec, []
        _, _, self.report, self.probe = readers(environment, spec)
        self.task = asyncio.create_task(self.run())

    async def run(self):
        interval, tick, start = self.spec['interval_sec'], 0, time.monotonic()
        while True:
            await asyncio.sleep(max(0, start + tick * interval - time.monotonic()))
            sample = {'at': time.monotonic()}
            try:
                report = await self.report()
                sample['claims'] = {c['path']: c['status'] for c in report.get('claims', [])}
                sample['paths'] = await self.probe()
                sample['read_seconds'] = time.monotonic() - sample['at']
                if sample['read_seconds'] > interval: sample.update(paths={}, error='ProbeOverranInterval')
            except Exception as error:
                sample.update(paths={}, claims={}, error=type(error).__name__)
            self.samples.append(sample)
            # Retain only enough history for the declared window and a boundary sample.
            cutoff = time.monotonic() - self.spec['duration_sec'] - 3 * interval
            self.samples = [s for s in self.samples if s['at'] >= cutoff]
            tick = max(tick + 1, int((time.monotonic() - start) // interval))

    async def window(self, start):
        duration, interval = self.spec['duration_sec'], self.spec['interval_sec']
        await asyncio.sleep(max(0, start + duration - time.monotonic()))
        previous = [s for s in self.samples if start - interval * 1.5 <= s['at'] <= start]
        selected = ([dict(previous[-1], elapsed_sec=0.)] if previous else [])
        selected += [dict(s, elapsed_sec=s['at'] - start) for s in self.samples if start < s['at'] < start + duration]
        return exposure.integrate(selected, duration, interval, self.spec['paths'])


async def run_window(environment, spec, monitor=None):
    exposure.window_config({'window': spec})
    shop, command, report, probe = readers(environment, spec)
    trusted = getattr(environment, '_phase2_reader', None)
    structured_traffic = isinstance(spec.get('traffic'), dict)
    temporary = tempfile.TemporaryDirectory(prefix='live-traffic-') if structured_traffic and not trusted else None
    options = None
    if structured_traffic:
        if trusted:
            options = await trusted.prepare_traffic(spec)
        else:
            options = dict(spec['traffic'])
            options['inventory_service_ports'] = {s['name']: s['host_ports'] for s in spec.get('inventory_services', []) if 'host_ports' in s}
            scenarios = []
            for sid, source in spec.get('traffic_hooks', {}).items():
                directory = Path(temporary.name) / sid; directory.mkdir()
                (directory / 'hooks.mjs').write_text(source)
                scenarios.append({'id': sid, 'dir': str(directory)})
            if scenarios: options['scenarios'] = scenarios
    await report()  # Seed the carry-forward report before the failure can land.
    injection_start = time.monotonic()
    if shop: await shop.inject()
    for text in spec.get('inject', []): await command(text)
    start = time.monotonic()
    # A fixed deadline prevents traffic escaping the declared window.
    if structured_traffic:
        deadline = start + spec['duration_sec']
        if trusted:
            traffic = asyncio.create_task(trusted.traffic(spec, options, deadline))
        else:
            traffic_command = shlex.join(['python3', str(Path(spec.get('root', '/app')) / 'bin/live_traffic.py'),
                                          str(deadline), json.dumps(options), '--deadline'])
            traffic = asyncio.create_task(execute(environment, traffic_command, int(spec['duration_sec'] + 10)))
    else:
        traffic_command = ('timeout --signal=TERM --kill-after=5 ' + str(spec['duration_sec']) +
                           ' sh -c ' + shlex.quote(spec['traffic'])) if spec.get('traffic') else None
        traffic = asyncio.create_task(command(traffic_command)) if traffic_command else None
    traffic_result, traffic_error = None, None
    try:
        measured = (await monitor.window(start) if monitor else
                    await exposure.observe(spec, spec['paths'], probe, report))
    finally:
        try:
            if traffic:
                # Traffic uses the same absolute monotonic deadline as sampling.
                try: traffic_result = await traffic
                except Exception as error: traffic_error = str(error)
        finally:
            if temporary: temporary.cleanup()
    cp = exposure.checkpoint(measured, await report(), spec['key'])
    cp['exposure']['injection_seconds'] = start - injection_start
    if traffic_error:
        cp['error_runs'] = cp['invalid_runs'] = 1
        cp['pass_runs'] = 0
        cp['errors'] = [{'stage': 'live-traffic', 'message': traffic_error}]
    if shop and traffic_result:
        try:
            traffic_data = json.loads(traffic_result)
            cp['traffic'] = traffic_data
            if traffic_data.get('error'):
                cp['error_runs'] = cp['invalid_runs'] = 1
                cp['errors'] = [{'stage': 'live-traffic', 'message': traffic_data['error']}]
            snapshot = await shop.snapshot()
            judge = shop.judge(snapshot, traffic_data)
            if spec.get('judge_source'):
                namespace = {}
                exec(compile(spec['judge_source'], '<case-live-judge>', 'exec'), namespace)
                extra = await namespace['judge'](dict(snapshot, traffic=traffic_data), trusted or LocalReader(shop))
                checks = extra.get('checks', {})
                if any(not isinstance(name, str) or type(ok) is not bool for name, ok in checks.items()):
                    raise ValueError('live judge checks must be named booleans')
                judge['checks'].update(checks)
                judge['pass'] = judge['pass'] and all(checks.values())
                cp['facts'] = extra.get('facts', {})
            if snapshot['errors'] or not snapshot['checker'].get('checker_ok'):
                cp['error_runs'] = cp['invalid_runs'] = 1
                detail = {'snapshot_errors': snapshot['errors'], 'checker': snapshot['checker']}
                cp.setdefault('errors', []).append({'stage': 'live-verdict',
                                                     'message': json.dumps(detail, default=str)[-4000:]})
            ordinary = traffic_data.get('ordinary_customers', {})
            cp['exposure']['ordinary_customers'] = ordinary
            judge['legit']['attempted'] += ordinary.get('attempted', 0)
            judge['legit']['placed'] += ordinary.get('placed', 0)
            cp['legit'] = judge['legit']
            cp['legit_completion'] = judge['legit']['placed'] / judge['legit']['attempted'] if judge['legit']['attempted'] else 1.
            cp['checks'] = {k: {'runs': 1, 'ok_runs': int(v)} for k, v in judge['checks'].items()}
            for path, violated in judge['paths'].items():
                cp['paths'][path]['violated_runs'] = max(cp['paths'][path]['violated_runs'], int(violated))
            cp['exposure']['receipt_violation_not_sampled'] = [p for p, violated in judge['paths'].items()
                if violated and cp['exposure']['paths'][p]['unsafe_seconds'] == 0]
            cp['claims_score'] = claims.score(await report(), cp, spec['key'])
            cp['pass_runs'] = int(not cp['error_runs'] and judge['pass'] and not any(p['violated_runs'] for p in cp['paths'].values()))
        except Exception as error:
            cp['error_runs'] = cp['invalid_runs'] = 1
            cp['pass_runs'] = 0
            cp.setdefault('errors', []).append({'stage': 'live-verdict', 'message': str(error)})
    return cp
