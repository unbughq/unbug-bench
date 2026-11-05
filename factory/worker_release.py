#!/usr/bin/env python3
"""Stamp a public source release on the host; verify it on a worker before credentials.

Stamping reads only the explicit source allowlist, never keys, cases or results.
Verification does not install tools, start workloads or call model providers.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

POLICY = Path(__file__).with_name('worker-release.json')
from launch_manifest import WORKER_BENCH as BENCH_FILES, worker_files


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files(root):
    paths = [root / name for name in worker_files(root)]
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError('missing or symlink release source: ' + str(path))
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(paths)}


def candidate_policy(root=None):
    policy = json.loads((Path(root) / 'factory/worker-release.json' if root else POLICY).read_text())
    policy['release'] += '-durable-candidate-v1'
    return policy


def stamp(root, output):
    policy = candidate_policy(root)
    policy['files'] = source_files(root)
    output.write_text(json.dumps(policy, indent=2, sort_keys=True) + '\n')


def output(command):
    sys.path.insert(0, str(Path(os.environ.get('BENCH', Path.home() / 'unbug-bench')) / 'bin'))
    import processes
    return processes.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=30, check=True,
                         env={**os.environ, 'OPENCODE_DISABLE_AUTOUPDATE': '1'}).stdout.strip()


def verify_driver(driver, executable=None, policy=None):
    """Read-only check for a selected driver, after any runner-owned installation.

    Pass the actual pinned_cli() result for Claude/Codex. No provider calls occur.
    """
    policy = policy or json.loads(POLICY.read_text())
    if driver not in policy['tools']:
        raise ValueError('unknown worker driver: ' + driver)
    spec = policy['tools'][driver]
    command = list(spec['command'])
    if executable is not None:
        command[0] = str(executable)
    actual = output(command)
    if ('version' in spec and actual != spec['version']) or ('contains' in spec and
            not re.search(r'(?<![0-9.])' + re.escape(spec['contains']) + r'(?![0-9.])', actual)):
        raise ValueError('worker tool version mismatch: ' + driver)
    return actual


def verify_selected_drivers(models, executable_for_driver=None, policy=None):
    """Qualify exactly the drivers used by resolved role chains, without model calls.

    executable_for_driver(driver) may perform runner-owned pinned installation and
    return the actual executable. It is called once per selected driver only.
    OpenRouter and OpenCode Go use the same OpenCode driver as model_runtime.
    """
    drivers = set()
    def visit(value):
        if isinstance(value, str) and '/' in value:
            prefix = value.split('/', 1)[0]
            drivers.add(prefix if prefix in ('codex', 'claude') else 'opencode')
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
        else:
            raise ValueError('invalid resolved model chain')
    if not isinstance(models, dict) or not models:
        raise ValueError('missing resolved role models')
    for value in models.values():
        visit(value)
    if not drivers:
        raise ValueError('missing selected drivers')
    versions = {}
    for driver in sorted(drivers):
        executable = executable_for_driver(driver) if executable_for_driver else None
        versions[driver] = verify_driver(driver, executable, policy)
    return {'verified_drivers': sorted(drivers), 'tools': versions}


def verify(manifest, root, factory_root, drivers):
    if manifest.get('schema') != 1 or not manifest.get('files'):
        raise ValueError('missing versioned source release hashes')
    for name, expected in manifest['files'].items():
        parts = Path(name).parts
        if not parts or '..' in parts or Path(name).is_absolute():
            raise ValueError('unsafe manifest path')
        path = factory_root.joinpath(*parts[1:]) if parts[0] == 'factory' else root / name
        if path.is_symlink() or sha(path) != expected:
            raise ValueError('release file mismatch: ' + name)
    if tuple(sys.version_info[:2]) < tuple(manifest['python_minimum']):
        raise ValueError('Python is older than worker release minimum')
    node = output(['node', '--version'])
    if int(node.removeprefix('v').split('.')[0]) not in manifest['node_majors']:
        raise ValueError('unsupported worker Node version')
    versions = {}
    # Requested drivers must already be installed and match the pinned policy.
    for tool in sorted(set(drivers) | {'harbor'}):
        versions[tool] = verify_driver(tool, policy=manifest)
    versions['age'] = output(['age', '--version'])
    versions['compose'] = output(['docker', 'compose', 'version', '--short'])
    output(['docker', 'info', '--format', '{{.ServerVersion}}'])
    images = {}
    for reference in manifest['images']:
        identity = output(['docker', 'image', 'inspect', '--format', '{{.Id}}', reference])
        if not re.fullmatch('sha256:[0-9a-f]{64}', identity):
            raise ValueError('invalid runtime image identity')
        images[reference] = identity
    subprocess.run(['node', 'verify-lock.mjs'], cwd=root / 'projects/medusa', check=True,
                   stdout=subprocess.DEVNULL, timeout=30)
    return {'schema': 1, 'release': manifest['release'], 'manifest_sha256':
            hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            'verified_drivers': sorted(set(drivers)),
            'deferred_drivers': [], 'tools': versions,
            'runtime_images': images, 'node': node, 'python': sys.version.split()[0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'unbug-bench')
    parser.add_argument('--factory-root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--stamp', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--drivers', default='opencode,codex')
    args = parser.parse_args()
    try:
        if args.stamp:
            stamp(args.root, args.stamp)
        else:
            if not args.manifest:
                raise ValueError('--manifest is required for verification')
            print(json.dumps(verify(json.loads(args.manifest.read_text()), args.root,
                                    args.factory_root, [v for v in args.drivers.split(',') if v]), sort_keys=True))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('worker qualification failed: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
