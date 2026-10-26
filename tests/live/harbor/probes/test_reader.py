"""Attach to a quiescent Harbor shop and verify trusted reads leave facts unchanged."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'harbor/phase2'), str(ROOT / 'bin')]
from reader import DockerLiveReader, command
from live_shop import LiveShop


async def main():
    assert sys.platform == 'linux', 'Run Docker probes on Hetzner only'
    reader = await DockerLiveReader.create(sys.argv[1])
    try:
        info = json.loads(await command('docker', 'inspect', reader.container))[0]
        assert all(m['Type'] == 'tmpfs' for m in info['Mounts']), 'judge client must not share host or case files'
        assert info['HostConfig']['PidMode'] == 'host'
        processes = await command('docker', 'exec', sys.argv[1], 'ps', '-eo', 'args')
        assert 'unbug-phase2-judge-client' not in processes, 'contestant can see the judge client process'
        role = json.loads(await reader.sql("BEGIN READ ONLY; SET LOCAL search_path=pg_catalog; SELECT json_build_object('role',current_user,'superuser',rolsuper,'bypassrls',rolbypassrls) FROM pg_roles WHERE rolname=current_user; COMMIT;"))
        assert role['role'] == 'medusa' and role['superuser']
        shop = LiveShop(None, {'root': '/app', 'inventory_services': [
            {'name': 'marketplace', 'project': 'projects/marketplace', 'reader': 'marketplace-sqlite'}]}, reader)
        snapshot = await shop.snapshot()
        fingerprint = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        before = fingerprint(snapshot)
        for _ in range(5):
            snapshot = await shop.snapshot()
        after = fingerprint(snapshot)
        assert before == after, 'Run this probe while the shop has no active writers'
        report = await reader.claims()
        print(json.dumps({'passed': True, 'role': role, 'mounts': info['Mounts'],
            'client_outside_contestant_pid_namespace': True,
            'read_only_state_proof': {'reads': 5, 'before_sha256': before, 'after_sha256': after},
            'live_order_count': len(snapshot['checker']['orders']),
            'marketplace_order_count': len(snapshot['inventory_services']['marketplace']['orders']),
            'claim_count': len(report.get('claims', [])), 'paths': shop.judge(snapshot)['paths']}, indent=2))
    finally:
        await reader.stop()


if __name__ == '__main__': asyncio.run(main())
