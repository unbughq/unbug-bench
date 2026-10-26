"""Run on the Hetzner native stack after strategies, with no traffic writers.
Prove repeated judge reads leave the logical database and SQLite bytes unchanged.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'bin'))
from live_shop import LiveShop


def output(command):
    return subprocess.check_output(command, cwd=ROOT)


def fingerprint():
    dump = output(['docker', 'compose', '-f', str(ROOT / 'projects/medusa/compose.yaml'),
                   'exec', '-T', 'postgres', 'pg_dump', '-U', 'medusa', '-d', 'medusa', '--data-only'])
    dump = b'\n'.join(line for line in dump.splitlines() if not line.startswith((b'\\restrict ', b'\\unrestrict ')))
    cid = output(['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.service=marketplace']).decode().strip()
    sqlite = output(['docker', 'exec', cid, '/bin/cat', '/data/marketplace.sqlite'])
    return {'postgres_data_sha256': hashlib.sha256(dump).hexdigest(),
            'sqlite_sha256': hashlib.sha256(sqlite).hexdigest()}


async def main():
    assert sys.platform == 'linux', 'Docker probes run on Hetzner only'
    async def execute(command):
        process = await asyncio.create_subprocess_shell(command, cwd=ROOT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await process.communicate()
        assert process.returncode == 0, err.decode()
        return out.decode()
    shop = LiveShop(execute, {'root': str(ROOT), 'inventory_services': [
        {'name': 'marketplace', 'project': 'projects/marketplace', 'reader': 'marketplace-sqlite'}]})
    before = fingerprint()
    paths = None
    for _ in range(5): paths = await shop.probe()
    after = fingerprint()
    assert before == after, (before, after)
    print(json.dumps({'passed': True, 'reads': 5, 'paths': paths, 'before': before, 'after': after}, indent=2))


if __name__ == '__main__': asyncio.run(main())
