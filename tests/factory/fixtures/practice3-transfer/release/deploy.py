#!/usr/bin/env python3
"""Pinned public deployment adapter; no credentials, cloud calls or workloads."""
import argparse
import hashlib
import io
import json
import os
import stat
import sys
from pathlib import Path
import shutil
import tarfile
import tempfile

PINS = {'install-source.py': '48585d98a7c3c4271ca6ffc0b3ff4bced122da645d24a1d571cb9e41b5fca536', 'source-manifest.json': '51b81ed0c012762bed0472fe38dce9105eee7d862593edca195641af1a45b15e', 'public-source.tar.gz': '6b748eed4bd8a03ad5a5c2b9f89bb7d7256124a3c68c0d48d8f1b19f0bd60032', 'worker-release-manifest.json': 'c35c291ff815e9017d409757d5b4fda1ac3abf959047f55ee62b04e484b0b295'}


def load(directory):
    data = {}
    for name, digest in PINS.items():
        path = directory / name
        if not path.exists() and name != 'install-source.py':
            path = directory / 'candidate' / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('missing regular release input: ' + name)
        data[name] = path.read_bytes()
        if hashlib.sha256(data[name]).hexdigest() != digest:
            raise ValueError('unqualified release input: ' + name)
    installer = {'__name__': 'qualified_installer', '__file__': str(directory / 'install-source.py')}
    exec(compile(data['install-source.py'], 'install-source.py', 'exec'), installer)
    manifest = directory / 'source-manifest.json'
    if not manifest.exists():
        manifest = directory / 'candidate/source-manifest.json'
    return data, installer, installer['load_manifest'](manifest)


def prepare(directory, output, batch_record=None):
    data, installer, files = load(directory)
    with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve()) as tmp:
        source = Path(tmp) / 'source'
        bundle = directory / 'public-source.tar.gz'
        if not bundle.exists():
            bundle = directory / 'candidate/public-source.tar.gz'
        installer['install'](bundle, source, files)
        with tarfile.open(output, 'w:gz') as archive:
            for name in files:
                if name.startswith('factory/'):
                    archive.add(source / name, arcname=name, recursive=False)
            data['deploy.py'] = globals().get('QUALIFIED_ADAPTER_BYTES') or Path(__file__).read_bytes()
            for name, content in data.items():
                member = tarfile.TarInfo('qualified-release/' + name)
                member.size = len(content)
                member.mode = 0o644
                archive.addfile(member, io.BytesIO(content))
            content = data['worker-release-manifest.json']
            member = tarfile.TarInfo('worker-release-manifest.json')
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
            if batch_record is not None:
                content = batch_record.read_bytes()
                member = tarfile.TarInfo('batch-release.json'); member.size = len(content)
                archive.addfile(member, io.BytesIO(content))


def safe_path(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink deployment path')


OWNED_DIRS = {'bin', 'cases', 'factory', 'guards', 'harbor', 'projects', 'scenarios', 'tests'}
INCOMPLETE = '.qualified-source-incomplete'


def inspect_targets(home, files, generated):
    """Names/types only; validate all owned targets before staging or renaming."""
    root = home / 'unbug-bench'
    safe_path(root)
    if root.exists() and not root.is_dir():
        raise ValueError('non-directory source root')
    targets = [root / n for n in sorted(OWNED_DIRS)]
    targets += [root / n for n in sorted(files) if '/' not in n]
    targets += [home / 'factory']
    snapshot, extras = {}, []
    home_stat = home.stat()
    device = home_stat.st_dev
    if (not stat.S_ISDIR(home_stat.st_mode) or home_stat.st_uid != os.getuid() or
            home_stat.st_mode & 0o7022):
        raise ValueError('unsafe deployment home')
    if root.exists():
        st = root.stat()
        if st.st_dev != device or st.st_uid != os.getuid() or st.st_mode & 0o7022:
            raise ValueError('unsafe source root')
        snapshot['unbug-bench'] = (st.st_dev, st.st_ino, st.st_mode)

    def walk(path):
        safe_path(path)
        if not path.exists():
            return
        st = path.lstat()
        name = path.relative_to(home).as_posix()
        kind = 'directory' if stat.S_ISDIR(st.st_mode) else 'file'
        if (not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)) or
                st.st_dev != device or st.st_uid != os.getuid() or
                st.st_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX |
                              (0o002 if stat.S_ISDIR(st.st_mode) else 0o022)) or
                (stat.S_ISREG(st.st_mode) and st.st_nlink != 1)):
            raise ValueError('unsafe source entry: ' + name)
        # Fresh images may create owner-owned directories with umask 0002.
        # Tighten only those directories; never relax the file/mode guards or
        # descend into preserved dependencies. Pin the inode before chmod.
        if stat.S_ISDIR(st.st_mode) and st.st_mode & 0o020:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                current = os.fstat(fd)
                if (current.st_dev, current.st_ino, current.st_uid, current.st_mode) != (
                        st.st_dev, st.st_ino, st.st_uid, st.st_mode):
                    raise ValueError('source directory changed before permission tightening: ' + name)
                os.fchmod(fd, stat.S_IMODE(st.st_mode) & ~0o020)
            finally:
                os.close(fd)
            st = path.lstat()
            if (st.st_dev, st.st_ino, st.st_mode) != (current.st_dev, current.st_ino, current.st_mode & ~0o020):
                raise ValueError('source directory changed during permission tightening: ' + name)
        snapshot[name] = (st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        relative = path.relative_to(root).as_posix() if path.is_relative_to(root) else None
        preserved = relative is not None and any(relative == g or relative.startswith(g + '/') for g in generated)
        expected = relative in files if relative is not None else 'factory/' + path.relative_to(home / 'factory').as_posix() in files
        prefix = relative if relative is not None else 'factory/' + path.relative_to(home / 'factory').as_posix()
        expected_dir = any(n.startswith(prefix.rstrip('/') + '/') for n in files)
        if not preserved and not expected and not expected_dir and path != home / 'factory':
            extras.append({'path': name, 'type': kind})
        # These explicit installed assets move intact; npm links and hardlinks
        # inside them are not source entries. Their roots/ancestors stay checked.
        if relative in generated and relative in {
                'projects/medusa/node_modules', 'projects/medusa/.medusa'}:
            if kind != 'directory':
                raise ValueError('invalid generated source path: ' + relative)
            return
        if kind == 'directory':
            for child in sorted(path.iterdir()):
                walk(child)

    for path in targets:
        walk(path)
    if len(extras) > 10000:
        raise ValueError('source diagnostic exceeds 10000 entries; no replacement')
    return targets, snapshot, sorted(extras, key=lambda entry: entry['path'])


def deploy(directory, home, verify_only=False):
    _, installer, files = load(directory)
    home = home.absolute()
    root, factory = home / 'unbug-bench', home / 'factory'
    safe_path(home)
    marker = home / INCOMPLETE
    if marker.exists() or marker.is_symlink():
        raise ValueError('incomplete source preparation; no delivery or automatic retry')
    if verify_only:
        installer['verify'](root, files, root / 'factory')
        return installer['verify'](root, files, factory)
    # The launcher owns a newly created worker and rejects --reuse-worker.
    # Never reset a case or a budget ledger.
    for name in ('work', 'sealed'):
        path = home / name
        safe_path(path)
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise ValueError('source installation requires a fresh worker')
    if {n.split('/')[0] for n in files if '/' in n} != OWNED_DIRS:
        raise ValueError('unexpected owned source roots')
    generated = installer['GENERATED_PATHS']
    targets, snapshot, extras = inspect_targets(home, files, generated)
    # Preserve reviewed generated paths only with their expected entry types.
    for name in generated:
        path = root / name
        if path.exists() and (path.is_dir() if name.endswith('.json') else not path.is_dir()):
            raise ValueError('invalid generated source path: ' + name)
    stage = Path(tempfile.mkdtemp(prefix='.qualified-source-', dir=home))
    source = stage / 'source'
    bundle = directory / 'public-source.tar.gz'
    if not bundle.exists():
        bundle = directory / 'candidate/public-source.tar.gz'
    installer['install'](bundle, source, files)
    shutil.copytree(source / 'factory', stage / 'factory')
    receipt = stage / 'source-preparation.json'
    receipt.write_text(json.dumps({'extra_entries': extras, 'extra_count': len(extras),
                                   'truncated': False}, sort_keys=True) + '\n')
    # Persist the complete paths-only receipt before touching active source.
    print(receipt.read_text(), end='', file=sys.stderr, flush=True)
    if inspect_targets(home, files, generated)[1] != snapshot:
        raise ValueError('source targets changed during preparation')
    for name in ('work', 'sealed'):
        path = home / name
        safe_path(path)
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise ValueError('source installation requires a fresh worker')
    with marker.open('x') as pending:
        pending.write(stage.name + '\n')
    old = stage / 'quarantine'
    old.mkdir()
    root.mkdir(exist_ok=True)
    # Bounded explicit renames: no recursive deletion of inherited trees.
    for path in targets:
        if path.exists():
            destination = old / path.relative_to(home)
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.rename(destination)
    for name in sorted(generated):
        previous = old / 'unbug-bench' / name
        if previous.exists():
            destination = source / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            previous.rename(destination)
    for path in targets:
        staged = stage / 'factory' if path == factory else source / path.relative_to(root)
        staged.rename(path)
    installer['verify'](root, files, root / 'factory')
    result = installer['verify'](root, files, factory)
    marker.unlink()
    result['preparation_receipt'] = str(receipt.relative_to(home))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'install', 'verify'))
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--batch-record', type=Path)
    parser.add_argument('--home', type=Path, default=Path.home())
    args = parser.parse_args()
    if args.operation == 'prepare':
        if args.output is None:
            parser.error('--output required')
        prepare(args.release, args.output, args.batch_record)
    else:
        print(json.dumps(deploy(args.release, args.home, args.operation == 'verify'), sort_keys=True))


if __name__ == '__main__':
    main()
