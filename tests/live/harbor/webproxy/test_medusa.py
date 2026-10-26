#!/usr/bin/env python3
"""Build/reset current practice app behind proxy in an isolated nested daemon."""
import json, os, shutil, subprocess, tarfile, tempfile, time
from pathlib import Path

HERE = (Path(__file__).resolve().parents[4] / 'harbor/webproxy')
ROOT = HERE.parents[1]
OUT = ROOT / 'results/infrastructure/2026-10-14-medusa-proxy'
OUT.mkdir(parents=True, exist_ok=True)

def run(args, **kwargs):
    return subprocess.run(['rtk', 'proxy', *args], check=True, text=True, **kwargs)


def main():
    started = time.time()
    with tempfile.TemporaryDirectory(prefix='unbug-medusa-proxy-') as directory:
        temp = Path(directory)
        proxy = temp / 'webproxy'
        shutil.copytree(HERE, proxy, ignore=shutil.ignore_patterns('__pycache__'))
        config = temp / 'compose.json'
        config.write_text(json.dumps({'services': {'main': {
            'image': 'unbug-bench-box:dev', 'privileged': True,
            'volumes': ['nested:/var/lib/docker'],
            'healthcheck': {'test': ['CMD', 'docker', 'info'], 'interval': '2s', 'timeout': '5s', 'retries': 60}}},
            'volumes': {'nested': {}}}))
        cmd = ['docker', 'compose', '-p', 'unbug-medusa-proxy-smoke', '-f', str(config), '-f', str(proxy / 'docker-compose.webproxy.yaml')]
        env = dict(os.environ, UNBUG_WEBPROXY_DIR=str(proxy), COMPOSE_ANSI="never", BUILDKIT_PROGRESS="plain")
        def dc(*args, **kwargs):
            return run([*cmd, *args], env=env, **kwargs)
        success = False
        try:
            dc('up', '-d', '--wait', stdout=subprocess.DEVNULL)
            container = dc('ps', '-q', 'main', capture_output=True).stdout.strip()
            archive = temp / 'source.tar'
            with tarfile.open(archive, 'w') as tar:
                for rel in ['bin/bench.py', 'bin/setup', 'bin/reset', 'bin/check', 'cases/medusa-oversell/checker/check.sql', 'projects/medusa', 'guards/none']:
                    def exclude(info):
                        parts = Path(info.name).parts
                        return None if any(p in ('node_modules', '.medusa', '__pycache__') or p.startswith('._') for p in parts) or info.name.endswith('seed-ids.json') else info
                    tar.add(ROOT / rel, arcname=rel, filter=exclude)
            run(['docker', 'cp', str(archive), container + ':/tmp/source.tar'], stdout=subprocess.DEVNULL)
            dc('exec', '-T', 'main', 'sh', '-c', 'tar -xf /tmp/source.tar -C /app && mkdir -p /app/results && chmod +x /app/bin/setup /app/bin/reset')
            config_json = dc('exec', '-T', 'main', 'sh', '-c', 'cd /app && docker compose -f projects/medusa/compose.yaml config --format json', capture_output=True).stdout
            direct = json.loads(dc('exec', '-T', 'main', 'python3', '-c', 'import socket,json;s=socket.socket();s.settimeout(2);code=s.connect_ex(("1.1.1.1",443));print(json.dumps({"direct_tcp_exit_code":code,"direct_tcp_blocked":code!=0}));assert code!=0', capture_output=True).stdout)
            build_config = json.loads(config_json)
            ca_lengths = {name: len(service['build']['args']['UNBUG_PROXY_CA']) for name, service in build_config['services'].items() if 'build' in service}
            assert all(length > 100 for length in ca_lengths.values()), ca_lengths
            with (OUT / 'setup.log').open('w') as log:
                dc('exec', '-T', 'main', '/app/bin/setup', stdout=log, stderr=subprocess.STDOUT)
            with (OUT / 'reset.log').open('w') as log:
                dc('exec', '-T', 'main', '/app/bin/reset', stdout=log, stderr=subprocess.STDOUT)
            health = dc('exec', '-T', 'main', 'python3', '-c', 'import urllib.request,json;print(json.dumps({str(p):urllib.request.urlopen("http://127.0.0.1:%d/health"%p).status for p in [9000,9001]}))', capture_output=True).stdout
            dc('cp', 'webproxy:/log/web.jsonl', str(OUT / 'web.jsonl'), stdout=subprocess.DEVNULL)
            rows = [json.loads(line) for line in (OUT / 'web.jsonl').read_text().splitlines()]
            registry = [r for r in rows if r['domain'] == 'registry.npmjs.org' and r['visibility'] == 'request']
            assert registry and any('.tgz' in r['url'] for r in registry)
            assert json.loads(health) == {'9000': 200, '9001': 200}
            (OUT / 'summary.json').write_text(json.dumps({'verdict': 'PASS', 'model_calls': 0, 'isolated_outer_project': 'unbug-medusa-proxy-smoke', 'npm_registry_http_requests': len(registry), 'health_after_reset': json.loads(health), 'elapsed_sec': round(time.time() - started, 2), 'setup_and_second_reset': True, 'resolved_public_ca_arg_lengths': ca_lengths, 'direct_egress_check': direct}, indent=2) + '\n')
            print((OUT / 'summary.json').read_text())
            success = True
        finally:
            if not success:
                try:
                    dc('cp', 'webproxy:/log/web.jsonl', str(OUT / 'web-failed.jsonl'), stdout=subprocess.DEVNULL)
                except subprocess.CalledProcessError:
                    pass
            dc('down', '-v', '--remove-orphans', stdout=subprocess.DEVNULL)

if __name__ == '__main__':
    main()
