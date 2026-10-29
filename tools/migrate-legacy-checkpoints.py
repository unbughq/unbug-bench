#!/usr/bin/env python3
"""Founder-only streaming migration. Originals and active pointers never change.

First use --dry-run with the reviewed plan and its SHA. Real runs require a TTY,
one hidden identity entry, age and age-keygen. No models or cloud calls.
VM recipient/decryption qualification and pointer activation are separate steps.
"""
import argparse
from contextlib import contextmanager, ExitStack
import fcntl
import getpass
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'tools')]
from registry import atomic_json, identifier
from unlock_sealed_audit import write_private

CHUNK = 1024 * 1024
KINDS = {'checkpoint', 'final', 'divergent_checkpoint', 'card_bound_absent', 'rewrap_key'}


def sha(stream):
    stream.seek(0)
    result = hashlib.file_digest(stream, 'sha256').hexdigest()
    stream.seek(0)
    return result


def file_sha(path):
    with path.open('rb') as stream:
        return sha(stream)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('invalid digest')
    return value


def load_plan(path, expected, founder, restore):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest(expected):
        raise ValueError('plan digest mismatch')
    plan = json.loads(raw)
    if (plan['schema'] != 1 or plan['founder_recipient'] != founder or
            plan['restore_recipient'] != restore or plan['vm_restore_recipient'] != restore or
            founder == restore or not plan['entries']):
        raise ValueError('plan authority mismatch')
    if (not Path(plan['mac_root']).is_absolute() or
            Path(plan['output_root']) != Path(plan['mac_root']) / 'generations'):
        raise ValueError('invalid output root')
    seen, cases = set(), {}
    for row in plan['entries']:
        identifier(row['case'])
        if row['kind'] not in KINDS or type(row['active_source']) is not bool:
            raise ValueError('invalid plan entry')
        key = row['kind'] == 'rewrap_key'
        source = digest(row['key_sha256'] if key else row['archive_sha256'])
        digest(row['card_sha256']); digest(row['card_archive_sha256'])
        if source in seen or type(row['size']) is not int or row['size'] <= 0:
            raise ValueError('duplicate or invalid source')
        seen.add(source)
        if row['case'] in cases and cases[row['case']] != key:
            raise ValueError('mixed key and archive migration')
        cases[row['case']] = key
        if key:
            if row['size'] != row['key_size'] or row['size'] > 65536 or not row['archives']:
                raise ValueError('invalid wrapped key')
            for archive in row['archives']:
                digest(archive['sha256'])
                if type(archive['size']) is not int or archive['size'] <= 0:
                    raise ValueError('invalid archive reference')
            if row['card_archive_sha256'] not in {a['sha256'] for a in row['archives']}:
                raise ValueError('absent rewrap current archive')
        elif row['active_source'] and row['card_archive_sha256'] != source:
            raise ValueError('current card binding mismatch')
        if row['kind'] == 'card_bound_absent' and row['active_source']:
            raise ValueError('absent card cannot activate')
    if len([r for r in plan['entries'] if r['active_source']]) != len({
            r['case'] for r in plan['entries'] if r['active_source']}):
        raise ValueError('duplicate active case')
    return plan


def opened_file(stack, path, expected, size=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stream = stack.enter_context(os.fdopen(fd, 'rb'))
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            (size is not None and info.st_size != size) or sha(stream) != expected):
        raise ValueError('input changed or unsafe')
    return stream


def preflight(plan, stack):
    """All planned input/card hashes are checked before the one hidden prompt."""
    opened, cards = {}, {}
    for i, row in enumerate(plan['entries']):
        source = row.get('key_sha256', row['archive_sha256'])
        stream = opened_file(stack, row['local_path'], source, row['size'])
        card = cards.get(row['card_path'])
        if card is None:
            card = opened_file(stack, row['card_path'], row['card_sha256']).read()
            cards[row['card_path']] = card
        if hashlib.sha256(card).hexdigest() != row['card_sha256']:
            raise ValueError('conflicting card versions')
        metadata = json.loads(card)
        if metadata.get('case') != row['case'] or metadata.get('sha256') != row['card_archive_sha256']:
            raise ValueError('original card binding changed')
        opened[i] = (stream, card)
    return opened


def stanzas(path):
    with path.open('rb') as stream:
        if stream.readline(128) != b'age-encryption.org/v1\n':
            raise ValueError('invalid age header')
        count = 0
        for _ in range(64):
            line = stream.readline(1024)
            if line.startswith(b'--- '):
                return count
            if line.startswith(b'-> X25519 '):
                count += 1
    raise ValueError('invalid age header')


def small(command, data=None):
    return subprocess.run(command, input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, check=True, timeout=30).stdout


def public(identity):
    return small(['age-keygen', '-y'], identity).decode('ascii').strip()


def decrypt(stream, identity, children):
    # Same descriptor/Popen pattern as unlock_sealed_audit.decrypt_one, no extraction.
    stream.seek(0)
    fd = stream.fileno()
    child = subprocess.Popen(['age', '-d', '-i', '/dev/stdin', '/dev/fd/' + str(fd)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, pass_fds=(fd,))
    children.append(child)
    child.stdin.write(identity); child.stdin.close()
    return child


@contextmanager
def processes(size):
    children = []
    def expired(*_):
        raise TimeoutError('migration deadline')
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, max(1200, 2 + math.ceil(size / 262144)))
    try:
        yield children
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
            for stream in (child.stdin, child.stdout):
                if stream is not None and not stream.closed:
                    stream.close()


def unwrap(stream, identity):
    with processes(4096) as children:
        child = decrypt(stream, identity, children)
        data = bytearray(child.stdout.read(4097))
        if len(data) > 4096 or child.wait(timeout=10) != 0:
            data[:] = b'\0' * len(data)
            raise ValueError('key authentication failed')
        # Native age identity validation; comments are preserved byte-for-byte.
        public(data)
        return data


def wrap(identity, founder, restore):
    return small(['age', '-e', '-r', founder, '-r', restore], identity)


def plaintext_hash(path, identity, children):
    with path.open('rb') as stream:
        child = decrypt(stream, identity, children)
        h, count = hashlib.sha256(), 0
        for block in iter(lambda: child.stdout.read(CHUNK), b''):
            h.update(block); count += len(block)
        if child.wait(timeout=10) != 0:
            raise ValueError('archive authentication failed')
        return h.hexdigest(), count


class Relay:
    """Tee compressed plaintext to encryption while tar/gzip consume it, in RAM."""
    def __init__(self, source, destination):
        self.source, self.destination = source, destination
        self.hash, self.count = hashlib.sha256(), 0

    def read(self, size=CHUNK):
        block = self.source.read(min(size, CHUNK) if size >= 0 else CHUNK)
        self.destination.write(block)
        self.hash.update(block); self.count += len(block)
        return block


def reencrypt(stream, stage, identity, case_key, founder, size):
    out = stage / 'archive.age'
    with processes(size) as children:
        decoder = decrypt(stream, identity, children)
        encoder = subprocess.Popen(['age', '-e', '-r', founder, '-r', public(case_key), '-o', str(out)],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        children.append(encoder)
        relay = Relay(decoder.stdout, encoder.stdin)
        with gzip.GzipFile(fileobj=relay, mode='rb') as compressed:
            with tarfile.open(fileobj=compressed, mode='r|') as archive:
                for _ in archive:
                    # ponytail: only structural validation; extraction policy stays on workers.
                    archive.members.clear()
            while compressed.read(CHUNK):
                pass  # gzip CRC, concatenation and EOF must validate after tar ends.
        while relay.read(CHUNK):
            pass
        if decoder.wait(timeout=10) != 0:
            raise ValueError('original archive authentication failed')
        encoder.stdin.close()
        if encoder.wait(timeout=10) != 0:
            raise ValueError('encryption failed')
        with out.open('rb') as encrypted:
            os.fsync(encrypted.fileno())
        expected = (relay.hash.hexdigest(), relay.count)
        if (plaintext_hash(out, case_key, children) != expected or
                plaintext_hash(out, identity, children) != expected or stanzas(out) != 2):
            raise ValueError('round trip failed')
        return expected


def complete(path, row, plan_sha):
    """Only a fully verified immutable output may be skipped or reused."""
    if not path.is_dir() or path.is_symlink():
        raise ValueError('invalid generation')
    manifest = json.loads((path / 'manifest.json').read_text())
    expected = {'casekey.age', 'original-card.json', 'migration.json'}
    if row['kind'] != 'rewrap_key':
        expected |= {'archive.age', 'projected-card.json'}
    if set(manifest['files']) != expected:
        raise ValueError('incomplete manifest')
    for name, wanted in manifest['files'].items():
        file = path / name
        if file.is_symlink() or not file.is_file() or file_sha(file) != wanted:
            raise ValueError('damaged generation')
    record = json.loads((path / 'migration.json').read_text())
    source = row.get('key_sha256', row['archive_sha256'])
    if (record['plan_sha256'] != plan_sha or record['source_sha256'] != source or
            record['case'] != row['case'] or record['kind'] != row['kind'] or
            manifest['files']['original-card.json'] != row['card_sha256']):
        raise ValueError('generation binding changed')
    return path


def existing(root, row, plan_sha):
    case = root / row['case']
    if not case.exists():
        return None
    if case.is_symlink():
        raise ValueError('unsafe generation directory')
    if row['kind'] == 'rewrap_key':
        path = case / ('key-' + row['key_sha256'])
        return complete(path, row, plan_sha) if path.exists() else None
    matches = []
    for path in sorted(case.iterdir()):
        if not re.fullmatch('[0-9a-f]{64}', path.name):
            continue
        record = json.loads((path / 'migration.json').read_text())
        if record.get('source_sha256') == row['archive_sha256']:
            matches.append(complete(path, row, plan_sha))
    if len(matches) > 1:
        raise ValueError('duplicate migrated source')
    return matches[0] if matches else None


def publish(stage, destination):
    hashes = {p.name: file_sha(p) for p in stage.iterdir()}
    atomic_json(stage / 'manifest.json', {'schema': 1, 'files': hashes})
    for path in stage.iterdir():
        with path.open('rb') as stream:
            os.fsync(stream.fileno())
    sync_directory(stage)
    destination.parent.mkdir(mode=0o700, exist_ok=True)
    if destination.exists():
        raise ValueError('immutable output exists')
    os.rename(stage, destination)
    sync_directory(destination.parent)
    sync_directory(destination.parent.parent)


def migrate_one(plan, row, stream, card, identity, case_key, root, plan_sha):
    source = row.get('key_sha256', row['archive_sha256'])
    with tempfile.TemporaryDirectory(prefix='.migration-stage-', dir=root) as temporary:
        stage = Path(temporary)
        wrapped = wrap(case_key, plan['founder_recipient'], plan['restore_recipient'])
        write_private(stage / 'casekey.age', wrapped)
        with (stage / 'casekey.age').open('rb') as file:
            verified = unwrap(file, identity)
        try:
            if verified != case_key or stanzas(stage / 'casekey.age') != 2:
                raise ValueError('key round trip failed')
        finally:
            verified[:] = b'\0' * len(verified)
        write_private(stage / 'original-card.json', card)
        record = {'schema': 1, 'plan_sha256': plan_sha, 'case': row['case'],
                  'source_sha256': source, 'kind': row['kind'],
                  'founder_recipient': plan['founder_recipient'],
                  'restore_recipient': plan['restore_recipient'],
                  'case_recipient': public(case_key), 'founder_unwrap_verified': True,
                  'vm_unwrap_verified': False, 'active_source': row['active_source']}
        if row['kind'] == 'rewrap_key':
            record['archives'] = list({a['sha256']: {'sha256': a['sha256'], 'size': a['size']}
                                       for a in row['archives']}.values())
            destination = root / row['case'] / ('key-' + source)
        else:
            plain_sha, size = reencrypt(stream, stage, identity, case_key,
                                       plan['founder_recipient'], row['size'])
            archive_sha = file_sha(stage / 'archive.age')
            record.update(archive_sha256=archive_sha, plaintext_sha256=plain_sha,
                          plaintext_bytes=size, founder_archive_verified=True,
                          case_archive_verified=True)
            projected = json.loads(card)
            projected['migration'] = {'source_sha256': source, 'active_source': row['active_source']}
            if row['kind'] == 'card_bound_absent':
                projected['bound_archive'] = {'status': 'absent', 'sha256': row['card_archive_sha256']}
                projected['migration']['available_archive_sha256'] = archive_sha
            else:
                projected['sha256'] = archive_sha
                projected.pop('r2_object', None)
            atomic_json(stage / 'projected-card.json', projected)
            destination = root / row['case'] / archive_sha
        # The same opened input must still match the frozen plan after crypto.
        if sha(stream) != source:
            raise ValueError('source changed during migration')
        atomic_json(stage / 'migration.json', record)
        publish(stage, destination)
    return destination


def run(plan, opened, identity, root, plan_sha, counts=None):
    if public(identity) != plan['founder_recipient']:
        raise ValueError('founder identity mismatch')
    counts = dict(migrated=0, failed=0, skipped=0) if counts is None else counts
    keys = {}
    try:
        for i, row in enumerate(plan['entries']):
            try:
                old = existing(root, row, plan_sha)
                stream, card = opened[i]
                if old is not None:
                    if row['kind'] != 'rewrap_key' and row['case'] not in keys:
                        with (old / 'casekey.age').open('rb') as wrapped:
                            keys[row['case']] = unwrap(wrapped, identity)
                    counts['skipped'] += 1
                    continue
                if row['kind'] == 'rewrap_key':
                    key = unwrap(stream, identity)
                else:
                    if row['case'] not in keys:
                        # A completed sibling can appear later in plan order on replay.
                        for peer in plan['entries']:
                            if peer['case'] == row['case']:
                                saved = existing(root, peer, plan_sha)
                                if saved is not None:
                                    with (saved / 'casekey.age').open('rb') as wrapped:
                                        keys[row['case']] = unwrap(wrapped, identity)
                                    break
                        else:
                            keys[row['case']] = bytearray(small(['age-keygen']))
                    key = keys[row['case']]
                try:
                    migrate_one(plan, row, stream, card, identity, key, root, plan_sha)
                    counts['migrated'] += 1
                finally:
                    if row['kind'] == 'rewrap_key':
                        key[:] = b'\0' * len(key)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError, tarfile.TarError, EOFError):
                counts['failed'] += 1
                print(row['case'] + ': migration failed; VM-unrestorable (original retained)', file=sys.stderr)
    finally:
        for key in keys.values():
            key[:] = b'\0' * len(key)
    return counts


def estimate(plan, root=None, plan_sha=None):
    pending = [r for r in plan['entries'] if root is None or existing(root, r, plan_sha) is None]
    archive_bytes = sum(r['size'] for r in pending if r['kind'] != 'rewrap_key')
    keys = [r for r in pending if r['kind'] == 'rewrap_key']
    # VM verification is outstanding even when all Mac outputs are replay skips.
    all_keys = [r for r in plan['entries'] if r['kind'] == 'rewrap_key']
    verification = sum({a['sha256']: a['size'] for r in all_keys for a in r['archives']}.values())
    return (math.ceil(archive_bytes * 1.1) + sum(r['size'] * 2 for r in keys) + 64 * CHUNK,
            math.ceil(4 * archive_bytes / (10 * CHUNK)),
            math.ceil(2 * verification / (10 * CHUNK)) + len(all_keys))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--plan-sha256', required=True)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.umask(0o077)
    identity = None
    counts = dict(migrated=0, failed=0, skipped=0)
    try:
        founder = re.search(r'^FOUNDER_RECIPIENT = "(age1[a-z0-9]+)"',
                            (ROOT / 'factory/run.py').read_text(), re.M)[1]
        restore = (ROOT / 'factory/control-recipient.txt').read_text().strip()
        plan = load_plan(args.plan, args.plan_sha256, founder, restore)
        root = Path(plan['output_root'])
        with ExitStack() as stack:
            opened = preflight(plan, stack)
            needed, seconds, vm_seconds = estimate(plan, root, args.plan_sha256)
            disk = root
            while not disk.exists():
                disk = disk.parent
            for row in plan['entries']:
                print(f"{row['case']} {row['kind']} {row['size']} bytes {row['local_path']}")
            print(f'Space needed: {needed} bytes; estimated Mac {seconds}s; VM verification {vm_seconds}s')
            if args.dry_run:
                if shutil.disk_usage(disk).free < needed:
                    raise ValueError('insufficient disk')
                print('Dry run; no prompt, outputs or pointer changes.')
                return 0
            if not sys.stdin.isatty() or not shutil.which('age') or not shutil.which('age-keygen'):
                raise ValueError('interactive terminal and age required')
            root.mkdir(parents=True, mode=0o700, exist_ok=True)
            if root.is_symlink():
                raise ValueError('unsafe output root')
            sync_directory(root.parent)
            with (root / '.migration.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                # A dead process can leave only ciphertext/public staging here.
                # The root-wide lock proves no other migration owns these stages.
                for stage in root.glob('.migration-stage-*'):
                    if stage.is_symlink() or not stage.is_dir() or stage.stat().st_uid != os.getuid():
                        raise ValueError('unsafe stale stage')
                    shutil.rmtree(stage)
                if shutil.disk_usage(root).free < needed:
                    raise ValueError('insufficient disk')
                with warnings.catch_warnings():
                    warnings.simplefilter('error', getpass.GetPassWarning)
                    identity = bytearray(getpass.getpass('Founder age identity (hidden; one entry): ').strip().encode() + b'\n')
                def interrupted(*_):
                    raise KeyboardInterrupt()
                for sig in (signal.SIGTERM, signal.SIGHUP):
                    signal.signal(sig, interrupted)
                run(plan, opened, identity, root, args.plan_sha256, counts)
                print('Summary: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))
                print('VM qualification pending; original evidence and active pointers unchanged.')
                return int(bool(counts['failed']))
    except (KeyboardInterrupt, Exception):
        # Never echo exception text, subprocess output, key material or traceback.
        if identity is not None:
            counts['failed'] += 1
            print('Summary: ' + ', '.join(f'{k}={v}' for k, v in counts.items()), file=sys.stderr)
        print('Migration stopped; original evidence retained. Invalid plan/preflight or interrupted.', file=sys.stderr)
        return 2
    finally:
        if identity is not None:
            identity[:] = b'\0' * len(identity)


if __name__ == '__main__':
    sys.exit(main())
