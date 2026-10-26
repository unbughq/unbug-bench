#!/usr/bin/env python3
"""Resume public result bytes over bounded Boat SSH calls; promote only verified files.

No identities, plaintext cases, cloud credentials or external transport are needed.
Each chunk is independently retryable. Completed chunks survive later invocations.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

CALL = Path(__file__).resolve().parents[1] / 'bin/boat-call'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def remote(worker, code):
    result = subprocess.run([str(CALL), 'ssh', worker, 'python3 -c ' + shlex.quote(code)],
                            stdout=subprocess.PIPE, check=True)
    return result.stdout


def metadata(worker, name):
    # Hash and stat the same open inode, refusing a writer that changed it while hashing.
    code = '''import hashlib,json,os,pathlib
p=pathlib.Path.home()/'sealed'/NAME
with p.open('rb') as f:
 a=os.fstat(f.fileno()); h=hashlib.sha256()
 for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 z=os.fstat(f.fileno())
 if (a.st_size,a.st_mtime_ns,a.st_ctime_ns)!=(z.st_size,z.st_mtime_ns,z.st_ctime_ns): raise SystemExit('result changed while hashing')
 print(json.dumps({'sha256':h.hexdigest(),'size':z.st_size}))
'''.replace('NAME', repr(name))
    info = json.loads(remote(worker, code))
    if (not re.fullmatch('[a-f0-9]{64}', info['sha256']) or
            type(info['size']) is not int or info['size'] < 0):
        raise ValueError('invalid remote result metadata')
    return info


def collect(worker, name, directory, chunk_bytes=8 * 1024 * 1024, retries=3):
    if not re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]*', name):
        raise ValueError('invalid result filename')
    if chunk_bytes <= 0 or retries <= 0:
        raise ValueError('chunk size and retries must be positive')
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    if destination.is_symlink():
        raise ValueError('refusing symlink destination')
    # Serialize collectors of this filename, including sweeper/launcher overlap.
    with (directory / ('.' + name + '.transfer.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        info = metadata(worker, name)
        if destination.is_file() and digest(destination) == info['sha256']:
            return
        partial = directory / ('.' + name + '.' + info['sha256'] + '.part')
        if partial.is_symlink():
            raise ValueError('refusing symlink partial')
        with partial.open('a+b') as stream:
            offset = stream.tell()
            if offset > info['size']:
                stream.truncate(0)
                offset = 0
            while offset < info['size']:
                length = min(chunk_bytes, info['size'] - offset)
                code = ('import pathlib,sys; p=pathlib.Path.home()/"sealed"/' + repr(name) +
                        '; f=p.open("rb"); f.seek(' + str(offset) +
                        '); sys.stdout.buffer.write(f.read(' + str(length) + '))')
                for attempt in range(retries):
                    try:
                        block = remote(worker, code)
                        if len(block) != length:
                            raise ValueError('short result chunk')
                        break
                    except (subprocess.CalledProcessError, ValueError):
                        if attempt + 1 == retries:
                            raise
                stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
                offset += length
        if metadata(worker, name) != info or digest(partial) != info['sha256']:
            # A damaged partial must not poison all future attempts against this digest.
            partial.unlink()
            raise ValueError('result changed or ciphertext hash mismatch; original retained')
        os.replace(partial, destination)
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('worker')
    parser.add_argument('name')
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        collect(args.worker, args.name, args.directory,
                int(os.environ.get('COLLECT_CHUNK_BYTES', 8 * 1024 * 1024)),
                int(os.environ.get('COLLECT_CHUNK_RETRIES', 3)))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print('collection failed for ' + args.name + ': ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
