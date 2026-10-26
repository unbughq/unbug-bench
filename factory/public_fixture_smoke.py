#!/usr/bin/env python3
"""Public S0 fixture only. Default: read-only local preflight; --run: isolated Docker smoke.

Uses existing images, never model providers, private cases, identities or cloud APIs.
This qualifies bench mechanics; it is not a full Linux factory/UID-wall canary.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

IMAGES = ('unbug-bench-medusa:latest', 'postgres:17.11-bookworm', 'redis:7.4.8-bookworm')
ROOT = Path(__file__).resolve().parents[1]


def output(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=30).strip()


def preflight(root, slot):
    if not 1 <= slot <= 500:
        raise ValueError('use an isolated slot between 1 and 500')
    endpoint = output(['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'])
    if os.environ.get('DOCKER_HOST') or not endpoint.startswith('unix://'):
        raise ValueError('requires the current local Unix Docker context; DOCKER_HOST must be unset')
    project = 'unbug-factory-' + str(slot)
    for kind in ('container', 'volume'):
        if output(['docker', kind, 'ls', '-q', '--filter', 'label=com.docker.compose.project=' + project]):
            raise ValueError('canary project is already in use: ' + project)
    server = json.loads(output(['docker', 'info', '--format',
        '{"version":{{json .ServerVersion}},"architecture":{{json .Architecture}},"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}}}']))
    if server['memory_bytes'] < 5 * 1024 ** 3:
        raise ValueError('public serial bench requires at least 5 GiB Docker memory')
    images = {name: json.loads(output(['docker', 'image', 'inspect', '--format',
                    '{"id":{{json .Id}},"architecture":{{json .Architecture}}}', name])) for name in IMAGES}
    for port in (9000 + 100 * slot, 9001 + 100 * slot):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
    for name in ('node', 'age', 'python3'):
        if not shutil.which(name):
            raise ValueError('missing public fixture tool: ' + name)
    for name in ('scenarios/dev/S0-null/scenario.json', 'scenarios/dev/S0-null/key.json',
                 'guards/reference/db.sql', 'bin/checkpoint', 'bin/checkpoint_evidence.py', 'bin/bench.py', 'bin/bench_judging.py'):
        if not (root / name).is_file():
            raise ValueError('missing public fixture source: ' + name)
    subprocess.run(['node', str(root / 'projects/medusa/verify-lock.mjs')], check=True,
                   stdout=subprocess.DEVNULL, timeout=30)
    return {'schema': 1, 'kind': 'public-fixture-mechanical-smoke', 'project': project,
            'slot': slot, 'server': server, 'images': images, 'model_calls': 0,
            'full_factory_qualified': False}


def smoke(root, slot):
    report = preflight(root, slot)
    started = time.monotonic()
    os.environ['UNBUG_FACTORY_SLOT'] = str(slot)
    sys.path.insert(0, str(root / 'bin'))
    import bench
    if bench.ROOT != root:
        raise ValueError('bench import does not match requested source root')
    if bench.FACTORY_SLOT != slot:
        raise ValueError('cached bench import does not match the isolated canary slot')
    from checkpoint_evidence import read_completed
    scenario = bench.load_scenario(root / 'scenarios/dev/S0-null')
    guards = ('none', 'reference', 'refuse-all')
    if bench.inventory_services([scenario]) or any(bench.app_patches(bench.resolve_guard(g), [scenario]) for g in guards):
        raise ValueError('public canary must not build inventory services or patched images')
    command, dc = bench.command, bench.dc
    def existing_images(*args, **kwargs):
        if args == ('build', 'medusa'):
            return ''  # Deliberately qualify the already-inspected baked image.
        if args and args[0] == 'up':
            args = ('up', '--no-build', '--pull', 'never', *args[1:])
        return dc(*args, **kwargs)
    def no_image_writes(args, **kwargs):
        if args[:2] in (['docker', 'build'], ['docker', 'tag'], ['docker', 'pull']):
            raise ValueError('public smoke cannot change images')
        return command(args, **kwargs)
    bench.dc, bench.command = existing_images, no_image_writes
    try:
        bench.setup([scenario])
        report['checks'] = []
        for guard in guards:
            result = subprocess.run([sys.executable, str(root / 'bin/checkpoint'), '--scenario',
                str(scenario['dir']), '--guard', guard, '--runs', '1', '--stress', '--seed', '1',
                '--label', 'public-canary-' + guard], check=True, capture_output=True, text=True, timeout=600)
            summary, _, evidence_path = read_completed(result, 1, 'public-canary-' + guard, require_valid=True)
            matched = (summary['pass_runs'] == 0 and summary['legit_completion'] < .95) if guard == 'refuse-all' else summary.get('key_consistent') is True
            if summary['error_runs'] or summary['invalid_runs'] or not matched:
                raise ValueError('public control did not match its key: ' + guard)
            report['checks'].append({'guard': guard, 'runs': summary['runs'], 'pass_runs': summary['pass_runs'],
                                    'expected_control': True, 'checkpoint': str(evidence_path)})
    finally:
        # The preflight refused pre-existing resources with this project label.
        bench.dc('down', '-v', '--remove-orphans')
    after = {name: json.loads(output(['docker', 'image', 'inspect', '--format',
                '{"id":{{json .Id}},"architecture":{{json .Architecture}}}', name])) for name in IMAGES}
    if after != report['images']:
        raise ValueError('image identities changed during public smoke')
    report['seconds'] = round(time.monotonic() - started, 3)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--slot', type=int, default=89)
    parser.add_argument('--run', action='store_true', help='run the public Docker fixture and remove its isolated resources')
    args = parser.parse_args()
    try:
        report = smoke(args.root.resolve(), args.slot) if args.run else preflight(args.root.resolve(), args.slot)
        print(json.dumps(report, sort_keys=True))
    except (OSError, ValueError, RuntimeError, StopIteration, subprocess.SubprocessError) as error:
        print('public fixture qualification failed: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
