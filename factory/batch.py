"""Commit-built public batch release; reuse the existing deployment and holder paths."""
import argparse
import ast
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

from launch_manifest import BATCH_SOURCE, HOST_FILES, WORKER_GLOBS, WORKER_BENCH, WORKER_CONFIG, sha

INPUTS = ('install-source.py', 'source-manifest.json', 'public-source.tar.gz',
          'worker-release-manifest.json')


def launch(batch, job, checkpoint_or_empty=None):
    """Submit progress to the local control service, independent of holder location.

    Restore-key authorization stays behind that service; no identity is accepted
    by this interface. The approved scoped VM key is implemented separately.
    """
    from key_holder import request
    return request({'op': 'launch', 'batch': batch, 'job': job,
                    'checkpoint': None if checkpoint_or_empty == '' else checkpoint_or_empty})


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def restore_inventory(root):
    """Find canonical ciphertext through Git's common directory, then this checkout."""
    directories = [root / 'sealed']
    try:
        common = Path(subprocess.check_output(['git', '-C', str(root), 'rev-parse',
                                              '--git-common-dir'], text=True, stderr=subprocess.DEVNULL).strip())
        common = (root / common).resolve() if not common.is_absolute() else common.resolve()
        directories.insert(0, common.parent / 'sealed')
    except (subprocess.CalledProcessError, OSError):
        pass
    for directory in dict.fromkeys(directories):
        archives = sorted(directory.glob('*.checkpoint.tar.gz.age'))
        if archives:
            return archives
    return []


def build(root, commit, destination):
    """Read git objects, never working-tree files or private case storage."""
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', '--verify',
                                      commit + '^{commit}'], text=True).strip()
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != head: raise ValueError('batch release commit must equal HEAD')
    if subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain',
                                '--untracked-files=all'], text=True).strip():
        raise ValueError('batch release requires a clean working tree')
    qualification = Path(__file__).resolve().parents[1] / 'tests/factory/test_restore_inventory.py'
    subprocess.run([sys.executable, '-B', str(qualification), '--require-inventory'],
                   check=True, stdout=sys.stderr)
    paths = (*BATCH_SOURCE, *HOST_FILES, 'tools/install_source.py')
    data = subprocess.check_output(['git', '-C', str(root), 'archive', '--format=tar', commit, '--', *paths])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = [m for m in archive if not m.isdir()]
        if any(not m.isfile() for m in members):
            raise ValueError('batch source must contain only regular files')
        source = {m.name: archive.extractfile(m).read() for m in members}
        modes = {m.name: m.mode for m in members}
    generated = next(ast.literal_eval(n.value) for n in ast.parse(source['tools/install_source.py']).body
                     if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
                     t.id == 'GENERATED_PATHS' for t in n.targets))
    public = {n: b for n, b in source.items() if any(n == p or n.startswith(p + '/') for p in BATCH_SOURCE)
              and not any(n == p or n.startswith(p + '/') for p in generated)}
    destination.mkdir()  # A release is never overwritten.
    hashes = {n: hashlib.sha256(b).hexdigest() for n, b in public.items()}
    save(destination / 'source-manifest.json', {'commit': commit, 'files': hashes})
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, content in sorted(public.items()):
            member = tarfile.TarInfo('unbug-bench/' + name)
            member.size, member.mode = len(content), modes[name]
            archive.addfile(member, io.BytesIO(content))
    (destination / 'public-source.tar.gz').write_bytes(gzip.compress(stream.getvalue(), mtime=0))
    installer = source['tools/install_source.py'].decode()
    for name, value in {'MANIFEST_SHA': sha(destination / 'source-manifest.json'),
                        'BUNDLE_SHA': sha(destination / 'public-source.tar.gz'),
                        'SOURCE_COUNT': len(public)}.items():
        installer = installer.replace(name + ' = None', name + ' = ' + repr(value), 1)
    (destination / 'install-source.py').write_text(installer)
    worker = json.loads(source['factory/worker-release.json'])
    selected = set(WORKER_BENCH + WORKER_CONFIG)
    selected.update(n for n in public if any(Path(n).match(p) for p in WORKER_GLOBS)
                    and not Path(n).name.startswith('test_'))
    worker['files'] = {n: hashes[n] for n in sorted(selected)}
    save(destination / 'worker-release-manifest.json', worker)
    pins = {n: sha(destination / n) for n in INPUTS}
    # Specialize only the existing adapter's release bindings, as qualification does.
    adapter = re.sub(r'(?ms)^PINS = \{.*?^\}', 'PINS = ' + repr(pins),
                     source['bin/qualified-release.py'].decode(), count=1)
    (destination / 'deploy.py').write_text(adapter)
    save(destination / 'batch-release.json', {
        'schema': 1, 'commit': commit,
        'host_files': {n: hashlib.sha256(source[n]).hexdigest() for n in HOST_FILES},
        'files': {n: sha(destination / n) for n in (*INPUTS, 'deploy.py')}})
    return sha(destination / 'batch-release.json')


def verify(directory, digest, root=None):
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('invalid batch release digest')
    if sha(directory / 'batch-release.json') != digest:
        raise ValueError('batch release changed')
    record = json.loads((directory / 'batch-release.json').read_text())
    if record['schema'] != 1 or set(record['files']) != {*INPUTS, 'deploy.py'}:
        raise ValueError('invalid batch release inventory')
    for name, expected in record['files'].items():
        if sha(directory / name) != expected:
            raise ValueError('batch release input changed: ' + name)
    if root is not None:
        if set(record['host_files']) != set(HOST_FILES) or any(
                sha(root / name) != record['host_files'][name] for name in HOST_FILES):
            raise ValueError('host differs from batch commit')
    return record


def prepare(directory, digest, root, output):
    verify(directory, digest, root)
    subprocess.run(['python3', '-B', str(directory / 'deploy.py'), 'prepare',
                    '--release', str(directory), '--output', str(output),
                    '--batch-record', str(directory / 'batch-release.json')], check=True)


def bind(policy, name, checkpoint, root, *, home=None, operation=None):
    """Translate empty/nonempty progress to the one existing launcher implementation."""
    batch, job = policy['batch'], policy['jobs'][name]
    from batch_money import manifest
    manifest(policy, root)
    case = 'case-' + batch['id'] + '-' + name
    args = job['args']
    forbidden = {'--restore', '--restore-review', '--qualified-release', '--batch-release',
                 '--batch-sha256', '--case-id', '--resume', '--reuse-review-worker', '--probe',
                 '--audit-g11', '--continue-g11-review', '--audit-fairness', '--rehearse-only', '--late-gate-rehearsal',
                 '--batch-release-sha256', '--checkpoint-sha256', '--skip-build', '--statement-only',
                 '--factory-job-config', '--factory-job-config-sha256'}
    if (job['mode'] != 'batch' or job['case'] != case or args[:1] != ['1'] or
            '--source' not in args or '--rotation-slot' not in args or
            any(a.split('=', 1)[0] in forbidden for a in args)):
        raise ValueError('invalid batch job')
    mode = 'new'
    if checkpoint is not None:
        if not isinstance(checkpoint, str) or not re.fullmatch('[0-9a-f]{64}', checkpoint):
            raise ValueError('invalid checkpoint generation')
        import batch_holder
        if batch_holder.HOLDER_ENABLED:
            operation = operation or __import__('os').environ.get('UNBUG_BATCH_OPERATION')
            home = home or Path(__import__('os').environ.get('UNBUG_CONTROL_HOME', str(Path.home() / '.unbug-control')))
            source = batch_holder.source_directory(policy, root, home, operation)
            if source is None: raise ValueError('request_refused')
            card = json.loads((source / (case + '.scorecard.json')).read_text())
        else:
            card = json.loads((root / 'sealed' / (case + '.scorecard.json')).read_text())
        if (card.get('case') != case or card.get('sha256') != checkpoint or
                card.get('batch_release_sha256') != batch['sha256']):
            raise ValueError('checkpoint differs from batch release or requested generation')
        mode = 'case'
    # Historical cumulative caps are metadata only for manifest-bound batch jobs.
    arguments, filtered = iter(args), []
    for arg in arguments:
        if arg in ('--max-cost', '--max-total-calls'):
            if next(arguments, None) is None: raise ValueError('missing historical cap value')
        elif not arg.startswith(('--max-cost=', '--max-total-calls=')):
            filtered.append(arg)
    args = [*filtered, '--batch-release', batch['release'], '--batch-sha256', batch['sha256'],
            '--case-id', case]
    if checkpoint is not None: args += ['--restore', case, '--checkpoint-sha256', checkpoint]
    return {**job, '_batch_job': True, 'mode': mode, 'args': args,
            'card': case + '.scorecard.json', 'archive_prefix': case}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('op', choices=('build', 'verify', 'prepare'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--commit', default='HEAD')
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--sha256')
    parser.add_argument('--output', type=Path)
    a = parser.parse_args()
    if a.op == 'build': print(build(a.root, a.commit, a.release))
    elif a.op == 'verify': verify(a.release, a.sha256, a.root)
    elif a.output: prepare(a.release, a.sha256, a.root, a.output)
    else: parser.error('--output required')


if __name__ == '__main__': main()
