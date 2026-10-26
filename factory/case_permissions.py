"""Restore executable case inputs without changing the private work/secret boundary.

Tar preserves good archive modes; legacy 0600/0700 case trees need a separate
repair. Only case inputs (or disposable Docker contexts) get readable modes.
"""
import argparse
import os
from pathlib import Path
import stat
import subprocess


def private_name(name):
    name = name.lower()
    return (name in {'.casekey', 'casekey', '.factory-r2', '.env', '.ssh', '.aws',
                     '.gnupg', 'keys', 'secrets', 'id_rsa', 'id_ed25519'} or
            name.startswith('.env.') or name.endswith(('.key', '.pem', '.p12', '.pfx')))


def normalize_case_tree(case):
    """Canonical case modes: dirs 0755, files 0644, existing executables 0755.

    Never follow symlinks or chmod multiply-linked files. Secrets keep their
    private modes, including when they occur inside a case's build context.
    The case's enclosing work directory and all siblings are untouched.
    """
    case = Path(case)
    if case.is_symlink():
        raise ValueError('symlink case tree')
    case = case.resolve()
    if not case.is_dir():
        raise ValueError('missing case tree')
    for directory, dirs, files in os.walk(case, followlinks=False):
        Path(directory).chmod(0o755)
        dirs[:] = [d for d in dirs if not private_name(d) and not (Path(directory) / d).is_symlink()]
        for name in files:
            path = Path(directory) / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                continue
            if info.st_nlink != 1:
                raise ValueError('hardlink in case tree')
            path.chmod(0o600 if private_name(name) else 0o755 if info.st_mode & 0o111 else 0o644)


def restore_archive(destination, case_trees, *, stream=None):
    """Extract a trusted factory tar stream, retaining modes despite umask 077.

    Do not apply this to credential bundles. Callers supply exact case roots,
    rather than recursively opening up the archive's logs/agent state/keys.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(['tar', '-xzpf', '-', '--no-same-owner', '-C', str(destination)],
                   stdin=stream, check=True)
    for tree in case_trees:
        normalize_case_tree(tree)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extract-to', type=Path, required=True)
    parser.add_argument('--case-tree', type=Path, action='append', required=True)
    args = parser.parse_args()
    restore_archive(args.extract_to, args.case_tree)
