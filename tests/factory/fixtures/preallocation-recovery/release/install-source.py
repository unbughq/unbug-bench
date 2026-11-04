#!/usr/bin/env python3
"""Maintained offline source installer; no cloud, credentials, or workloads.

Release builders bind MANIFEST_SHA, BUNDLE_SHA, and SOURCE_COUNT in a standalone
copy. Unbound copies fail closed. The CLI alternatively requires those explicit
expected values. This source does not qualify or alter any historical release.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import stat
import sys
import tarfile
import tempfile

MANIFEST_SHA = 'a68d15d423c5ae2ffd3bb01ee2272cbad6552b84cf1177d1aa72b2a3edb63c5b'
BUNDLE_SHA = '1db3b14d796e0aeb93dc5af37b7b583315d9d5c82b6f3a1b890d544c8f1aca95'
SOURCE_COUNT = 869
# Reviewed generated paths: npm dependencies, Medusa build, and seed.ts output.
# These are not qualified source; dependency/build validation remains separate.
GENERATED_PATHS = {'projects/medusa/node_modules', 'projects/medusa/.medusa',
                   'projects/medusa/seed-ids.json'}


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing or symlink input')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(path):
    if sha(path) != MANIFEST_SHA:
        raise ValueError('unqualified manifest')
    files = json.loads(path.read_text())['files']
    if type(SOURCE_COUNT) is not int or SOURCE_COUNT < 1 or len(files) != SOURCE_COUNT:
        raise ValueError('unexpected source count')
    for name in files:
        p = PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or str(p) != name:
            raise ValueError('unsafe source path')
    return files


def source_inventory(root, owned_dirs, generated_paths=()):
    actual = set()
    def walk(directory):
        for p in sorted(directory.iterdir()):
            name = p.relative_to(root).as_posix()
            # Never follow or silently exclude symlinks, even at generated paths.
            if p.is_symlink():
                raise ValueError('symlink in source inventory: ' + name)
            if name in generated_paths:
                continue
            if p.is_dir():
                walk(p)
            elif p.is_file():
                actual.add(name)
            else:
                raise ValueError('unsupported source entry: ' + name)
    for name in sorted(owned_dirs):
        directory = root / name
        if directory.is_symlink():
            raise ValueError('symlink source directory: ' + name)
        walk(directory)
    return actual


def bundle_modes(bundle, files):
    if sha(bundle) != BUNDLE_SHA:
        raise ValueError('unqualified bundle')
    with tarfile.open(bundle) as archive:
        members = archive.getmembers()
        expected = {'unbug-bench/' + name for name in files}
        if len(members) != len(expected) or {m.name for m in members} != expected:
            raise ValueError('unexpected or duplicate bundle members')
        if any(not m.isfile() for m in members):
            raise ValueError('invalid bundle member')
        return {m.name.removeprefix('unbug-bench/'): 0o755 if m.mode & 0o111 else 0o644
                for m in members}


def verify(root, files, factory_root=None, bundle=None):
    if bundle is None:
        bundle = Path(__file__).resolve().parent / 'public-source.tar.gz'
        if not bundle.exists():
            bundle = bundle.parent / 'candidate/public-source.tar.gz'
    modes = bundle_modes(bundle, files)
    root = root.absolute()
    for name, digest in files.items():
        p = root / name
        if any(parent.is_symlink() for parent in (p, *p.parents)) or sha(p) != digest or stat.S_IMODE(p.stat().st_mode) != modes[name]:
            raise ValueError('source mismatch: ' + name)
        if factory_root is not None and name.startswith('factory/'):
            p = factory_root.absolute() / name.removeprefix('factory/')
            if any(parent.is_symlink() for parent in (p, *p.parents)) or sha(p) != digest or stat.S_IMODE(p.stat().st_mode) != modes[name]:
                raise ValueError('transferred factory mismatch: ' + name)
    owned_dirs = {PurePosixPath(n).parts[0] for n in files if '/' in n}
    actual = source_inventory(root, owned_dirs, GENERATED_PATHS)
    expected = {n for n in files if '/' in n}
    if actual != expected:
        raise ValueError('source inventory mismatch: extra=' + repr(sorted(actual - expected)) +
                         ', missing=' + repr(sorted(expected - actual)))
    if factory_root is not None:
        factory_root = factory_root.absolute()
        expected = {n.removeprefix('factory/') for n in files if n.startswith('factory/')}
        actual = source_inventory(factory_root, {'.'})
        if actual != expected:
            raise ValueError('unqualified files in transferred factory')
    return {'source_files_verified': len(files), 'factory_copy_verified': factory_root is not None}


def install(bundle, root, files):
    if sha(bundle) != BUNDLE_SHA:
        raise ValueError('unqualified bundle')
    root = root.absolute()
    if root.exists() or root.is_symlink():
        raise ValueError('destination must be absent; no replacement or deletion supported')
    if any(p.is_symlink() for p in (root.parent, *root.parent.parents)):
        raise ValueError('symlink destination parent')
    # Validate every member before creating any source. Never use extractall.
    with tarfile.open(bundle) as archive:
        members = archive.getmembers()
        expected = {'unbug-bench/' + name: digest for name, digest in files.items()}
        if len(members) != len(expected) or {m.name for m in members} != set(expected):
            raise ValueError('unexpected or duplicate bundle members')
        for m in members:
            if not m.isfile() or hashlib.sha256(archive.extractfile(m).read()).hexdigest() != expected[m.name]:
                raise ValueError('invalid bundle member')
        with tempfile.TemporaryDirectory(prefix='.qualified-source-', dir=root.parent) as tmp:
            stage = Path(tmp) / 'source'
            stage.mkdir()
            for m in members:
                p = stage / m.name.removeprefix('unbug-bench/')
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(archive.extractfile(m).read())
                # Keep executable bits; discard special and group/world write bits.
                p.chmod(0o755 if m.mode & 0o111 else 0o644)
            verify(stage, files, bundle=bundle)
            if root.exists() or root.is_symlink():
                raise ValueError('destination appeared during install')
            os.rename(stage, root)
    return verify(root, files, bundle=bundle)


def main():
    global MANIFEST_SHA, BUNDLE_SHA, SOURCE_COUNT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--factory-root', type=Path)
    parser.add_argument('--manifest-sha256', default=MANIFEST_SHA, required=MANIFEST_SHA is None)
    parser.add_argument('--bundle-sha256', default=BUNDLE_SHA, required=BUNDLE_SHA is None)
    parser.add_argument('--source-count', type=int, default=SOURCE_COUNT, required=SOURCE_COUNT is None)
    args = parser.parse_args()
    MANIFEST_SHA, BUNDLE_SHA, SOURCE_COUNT = args.manifest_sha256, args.bundle_sha256, args.source_count
    files = load_manifest(args.manifest)
    if args.bundle:
        install(args.bundle, args.root, files)
    print(json.dumps(verify(args.root, files, args.factory_root, bundle=args.bundle), sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, tarfile.TarError):
        sys.exit('source installation/verification failed; no activation or launch performed')
