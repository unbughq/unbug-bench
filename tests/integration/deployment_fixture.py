"""Synthetic release inputs for the real deployment adapter and installer.

Only release bindings are specialized. Installation, inventory verification,
permission checks, staging, and launcher sequencing execute maintained code.
Nothing here modifies production pins or certifies a deployable release.
"""
import ast
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def bind_constants(source, values):
    lines = source.splitlines(keepends=True)
    found = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in values:
                found[name] = node
    if found.keys() != values.keys():
        raise ValueError('release binding declarations changed')
    for name, node in sorted(found.items(), key=lambda item: item[1].lineno, reverse=True):
        lines[node.lineno - 1:node.end_lineno] = [name + ' = ' + repr(values[name]) + '\n']
    return ''.join(lines).encode()


def build_release(directory):
    directory.mkdir()
    sources = {
        'CONTESTANT.md': b'Synthetic public benchmark.\n',
        'bin/check': b'#!/bin/sh\nexit 0\n',
        'bin/bench.py': b'PUBLIC_FIXTURE = True\n',
        'bin/run-exam': b'#!/usr/bin/env python3\n',
        'factory/budget.py': b'PUBLIC_FIXTURE = True\n',
        'factory/run.py': b'PUBLIC_FIXTURE = True\n',
        'factory/worker_release.py': b'PUBLIC_FIXTURE = True\n',
        'cases/public/case.json': b'{}\n',
        'guards/reference/db.sql': b'-- public fixture\n',
        'harbor/public/task.toml': b'name = "public"\n',
        'projects/medusa/package.json': b'{}\n',
        'scenarios/public/scenario.json': b'{}\n',
        'tests/test_public.py': b'PUBLIC_FIXTURE = True\n',
    }
    files = {name: hashlib.sha256(data).hexdigest() for name, data in sources.items()}
    manifest = directory / 'source-manifest.json'
    manifest.write_text(json.dumps({'files': files}, sort_keys=True) + '\n')
    bundle = directory / 'public-source.tar.gz'
    with tarfile.open(bundle, 'w:gz') as archive:
        for name, data in sources.items():
            member = tarfile.TarInfo('unbug-bench/' + name)
            member.size = len(data)
            member.mode = 0o755 if name in ('bin/check', 'bin/run-exam') else 0o644
            archive.addfile(member, io.BytesIO(data))
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    installer = bind_constants((ROOT / 'tools/install_source.py').read_text(), {
        'MANIFEST_SHA': sha(manifest), 'BUNDLE_SHA': sha(bundle), 'SOURCE_COUNT': len(files)})
    (directory / 'install-source.py').write_bytes(installer)
    (directory / 'worker-release-manifest.json').write_text('{"synthetic": true}\n')
    pins = {name: sha(directory / name) for name in (
        'install-source.py', 'source-manifest.json', 'public-source.tar.gz', 'worker-release-manifest.json')}
    adapter = bind_constants((ROOT / 'bin/qualified-release.py').read_text(), {'PINS': pins})
    return files, pins, adapter


def folding_sequence(worker, expiry):
    common = dict(id=worker, type='default', ttlSeconds=1800, archiveAfter=expiry,
                  holdsCreatorLogins=False, monitoring=False, snapshots=False,
                  state='idle', health='ok', error=None, setupError=None, setupStatus=None,
                  degradedSince=None)
    return [dict(common, hydrated=False, hydration={
        'phase': 'folding', 'entriesDone': n, 'entriesTotal': None, 'percent': None})
        for n in range(5)] + [dict(common, hydrated=True, hydration=None)]
