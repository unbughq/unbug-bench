#!/usr/bin/env python3
"""Synthetic inventory endpoint/Compose isolation regression; no containers or models."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import copy
import asyncio
import http.server
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "bin"))
import bench


with tempfile.TemporaryDirectory(prefix="inventory-port-test-") as temporary:
    root = pathlib.Path(temporary)
    project = root / "source"; project.mkdir()
    (project / "adapter.py").write_text("# synthetic fixture\n")
    (project / "compose.yaml").write_text('services:\n  channel:\n    image: python:3.12\n    ports: ["127.0.0.1:9010:9010"]\n')
    base = root / "base.yaml"; base.write_text('services:\n  medusa:\n    image: synthetic-medusa\n    ports: ["127.0.0.1:9000:9000"]\n')
    scenario_dir = root / 'scenario'; scenario_dir.mkdir()
    scenario = {"id": "synthetic", "dir": scenario_dir, "inventory_services": [{"name": "channel", "project": str(project), "host_ports": [9010]}]}
    (scenario_dir / 'scenario.json').write_text(json.dumps({k: v for k, v in scenario.items() if k != 'dir'}))
    services = bench.inventory_services([scenario])
    assert bench.isolated_inventory_services([scenario])
    assert bench.inventory_service_ports(services, 0) == {"channel": [9010]}
    assert bench.inventory_service_ports(services, 1) == {"channel": [9110]}
    assert bench.inventory_service_ports(services, 2) == {"channel": [9210]}
    legacy = copy.deepcopy(scenario); del legacy["inventory_services"][0]["host_ports"]
    assert not bench.isolated_inventory_services([legacy])
    for invalid in ([True], [9000], [9100], [9010, 9010], "9010"):
        broken = copy.deepcopy(scenario); broken["inventory_services"][0]["host_ports"] = invalid
        try: bench.inventory_services([broken])
        except ValueError: pass
        else: raise AssertionError(f"invalid host_ports accepted: {invalid}")
    broken = copy.deepcopy(scenario)
    broken["inventory_services"].append({"name": "second", "project": str(project), "host_ports": [9010]})
    try: bench.inventory_services([broken])
    except ValueError: pass
    else: raise AssertionError("shared host port accepted")

    config = {"services": {"channel": {"ports": [{"host_ip": "127.0.0.1", "published": "9010", "target": 9010, "protocol": "tcp"}]}}}
    for slot in (0, 1, 2):
        results = root / str(slot); results.mkdir()
        guard = root / "guard"; guard.mkdir(exist_ok=True)
        compose = ["docker", "compose", "-p", f"synthetic-{slot}", "-f", str(base)]
        saved = []
        def command(argv, **kwargs):
            if "config" in argv: return json.dumps(config)
            if "build" in argv:
                saved.append(argv[:argv.index("build")])
                overlay = json.loads((results / ".inventory-compose.json").read_text())
                assert overlay["services"]["channel"]["environment"] == {"UNBUG_MONITOR_BLIND": "1"}
                assert overlay["services"]["channel"]["image"].endswith(f":guard-{slot}" if slot else ":guard")
                if slot:
                    publication = (results / ".inventory-ports.yaml").read_text().split("ports: !override ", 1)[1]
                    assert json.loads(publication)[0]["published"] == str(9010 + 100 * slot)
                else:
                    assert not (results / ".inventory-ports.yaml").exists(), "exam defaults changed"
                if "--compose" in sys.argv:
                    resolved = json.loads(subprocess.run(saved[-1] + ["config", "--format", "json"],
                                                       text=True, capture_output=True, check=True).stdout)
                    assert resolved["services"]["channel"]["ports"][0]["published"] == str(9010 + 100 * slot)
                    assert resolved["services"]["channel"]["ports"][0]["host_ip"] == "127.0.0.1"
            return ""
        with mock.patch.multiple(bench, FACTORY_SLOT=slot, RESULTS=results, INVENTORY_STATE=results / ".state.json", COMPOSE=compose), \
             mock.patch.object(bench, "command", command), mock.patch.object(bench, "service_adapter", return_value={"orders": {}}):
            assert bench.start_inventory_services(services, guard, {"channel"}) == {"channel": {"orders": {}}}
            state = json.loads(bench.INVENTORY_STATE.read_text())
            assert state["compose"] == saved[0] and state["names"] == ["channel"]
            bench.stop_inventory_services()
            assert not bench.INVENTORY_STATE.exists()
    for change in (
        lambda c: c["services"]["channel"]["ports"][0].update(host_ip="0.0.0.0"),
        lambda c: c["services"]["channel"]["ports"][0].update(protocol="udp"),
        lambda c: c["services"]["channel"]["ports"][0].update(published="9011"),
        lambda c: c["services"]["channel"].update(container_name="shared"),
        lambda c: c["services"]["channel"].update(network_mode="host"),
        lambda c: c["services"]["channel"].update(volumes=[{"type": "bind", "source": "/shared", "target": "/data"}]),
        lambda c: c.update(volumes={"data": {"external": True}}),
        lambda c: c.update(networks={"network": {"name": "shared"}}),
        lambda c: (c.update(volumes={"data": {"driver": "local", "driver_opts": {"type": "none", "o": "bind", "device": "/shared-ledger"}}}),
                   c["services"]["channel"].update(volumes=[{"type": "volume", "source": "data", "target": "/data"}])),
        lambda c: c.update(volumes={"data": {"driver": "shared-backend"}}),
        lambda c: c.update(networks={"network": {"driver": "host"}}),
        lambda c: c.update(networks={"network": {"driver": "bridge", "driver_opts": {"com.docker.network.bridge.name": "shared"}}}),
    ):
        invalid = copy.deepcopy(config); change(invalid)
        with mock.patch.object(bench, "FACTORY_SLOT", 1), mock.patch.object(bench, "command", return_value=json.dumps(invalid)):
            try: bench.start_inventory_services(services, guard)
            except ValueError: pass
            else: raise AssertionError("unsafe isolated Compose accepted")
    with mock.patch.object(bench, "FACTORY_SLOT", 1):
        try: bench.start_inventory_services(bench.inventory_services([legacy]), guard)
        except ValueError: pass
        else: raise AssertionError("legacy service allowed on another slot")

    # Actual 8 GB Boat guests expose ~7941 MiB; retain 768 MiB for OS/runner overhead.
    mib = 1024**2
    memory_config = {"services": {"medusa": {"mem_limit": 1280*mib}, "medusa-b": {"mem_limit": 1280*mib},
                                  "postgres": {"mem_limit": 768*mib}, "redis": {"mem_limit": 128*mib},
                                  "channel": {"mem_limit": 64*mib}}}
    with mock.patch.object(bench, "command", return_value=json.dumps(memory_config)), \
         mock.patch.object(bench, "docker_memory_bytes", return_value=7941*mib):
        assert bench.factory_memory_fits([scenario], 2)
        assert not bench.factory_memory_fits([scenario], 3), 'three complete shops exceed the actual guest RAM'
    import run
    c = run.Ctx(); c.case = root; c.args = type('Args', (), {'concurrent_roles': True, 'bench_workers': 2})()
    for cap, fits in ((64*mib, True), (None, False), (4*1024*mib, False)):
        candidate = copy.deepcopy(memory_config); candidate['services']['channel']['mem_limit'] = cap
        with mock.patch.object(bench, 'load_scenario', return_value=scenario), \
             mock.patch.object(bench, 'command', return_value=json.dumps(candidate)), \
             mock.patch.object(bench, 'docker_memory_bytes', return_value=7941*mib):
            assert run.parallel_calibrators(c) is fits
            assert run.no_fixed_port_services(c, []) is fits
    for cap in (None, 0, -1, True, 4*1024*mib, "unlimited", float("inf")):
        invalid = copy.deepcopy(memory_config); invalid["services"]["channel"]["mem_limit"] = cap
        with mock.patch.object(bench, "command", return_value=json.dumps(invalid)), \
             mock.patch.object(bench, "docker_memory_bytes", return_value=7941*mib):
            assert not bench.factory_memory_fits([scenario], 2), f'unsafe memory cap accepted: {cap}'
    for replication in ({'scale': 20}, {'deploy': {'replicas': 20}}, {'deploy': {'mode': 'global'}}):
        invalid = copy.deepcopy(memory_config); invalid['services']['channel'].update(replication)
        with mock.patch.object(bench, 'command', return_value=json.dumps(invalid)), \
             mock.patch.object(bench, 'docker_memory_bytes', return_value=7941*mib):
            assert not bench.factory_memory_fits([scenario], 2), 'unaccounted service replication accepted'
    with mock.patch.object(bench, "command", return_value=json.dumps(memory_config)), \
         mock.patch.object(bench, "docker_memory_bytes", side_effect=OSError('unknown RAM')):
        assert not bench.factory_memory_fits([scenario], 2)
    with mock.patch.object(bench, "command", side_effect=RuntimeError('unknown Compose')):
        assert not bench.factory_memory_fits([scenario], 2)
    with mock.patch.object(bench, 'command', return_value=str(7941*mib)) as daemon:
        assert bench.docker_memory_bytes() == 7941*mib
        assert daemon.call_args.args[0] == ['docker', 'info', '--format', '{{.MemTotal}}']

    # Lower the effective worker count before G3 creates any idle DB/Redis pairs.
    c.work = root / 'runner'; (c.work / 'logs').mkdir(parents=True)
    c.card = {}; c.args.bench_workers = 4
    prepared = []
    def setup_command(c, argv, **kwargs):
        if kwargs.get('env', {}).get('UNBUG_FACTORY_SLOT') is not None:
            prepared.append(int(kwargs['env']['UNBUG_FACTORY_SLOT']))
        return subprocess.CompletedProcess(argv, 0, stdout='synthetic-image') if kwargs.get('capture') else 0
    with mock.patch.object(bench, 'load_scenario', return_value=scenario), \
         mock.patch.object(bench, 'command', return_value=json.dumps(memory_config)), \
         mock.patch.object(bench, 'docker_memory_bytes', return_value=7941*mib), \
         mock.patch.object(run, 'sh', setup_command):
        assert run.g3(c)[0]
    assert c.args.bench_workers == c.card['bench_workers_effective'] == 2
    assert prepared == [1], 'oversized worker request prepared extra idle databases'
    # A later repair can lower the count, but the old slot is parked and stays in G3's cleanup scope.
    large = copy.deepcopy(memory_config); large['services']['channel']['mem_limit'] = 4*1024*mib
    prepared.clear()
    with mock.patch.object(bench, 'load_scenario', return_value=scenario), \
         mock.patch.object(bench, 'command', return_value=json.dumps(large)), \
         mock.patch.object(bench, 'docker_memory_bytes', return_value=7941*mib), \
         mock.patch.object(run, 'sh', setup_command):
        assert run.g3(c)[0]
    assert c.args.bench_workers == 1 and c.prepared_factory_slots == 2
    assert prepared == [1], 'previously prepared peer must be removed when memory eligibility shrinks'

    # A heavier scenario that falls back to serial releases idle peers, never slot zero's DB.
    parked = []
    def park(argv, **kwargs):
        assert kwargs['cwd'] == root / 'bin'
        parked.append(int(kwargs['env']['UNBUG_FACTORY_SLOT']))
        assert "bench.dc('stop')" in argv[-1]
        return subprocess.CompletedProcess(argv, 0)
    with mock.patch.multiple(bench, ROOT=root, RESULTS=root / 'serial-results'), \
         mock.patch.object(bench, 'factory_memory_fits', return_value=False), \
         mock.patch.object(bench, 'prepare_app_guard'), mock.patch.object(bench, 'bench_fingerprint', return_value={}), \
         mock.patch.object(bench, 'run_once', return_value={'checker': {'valid': True, 'pass': True}, 'traffic': {}, 'errors': [], 'reset_seconds': 0}), \
         mock.patch.object(bench.subprocess, 'run', park):
        bench.run_case(guard, 1, scenarios=[scenario], factory_workers=3)
    assert parked == [1, 2], 'serial fallback left idle peer DBs or stopped the owner'
    subprocess.run([sys.executable, '-c', 'import bench; assert bench.FACTORY_SLOT == 0'], cwd=bench.ROOT / 'bin',
                   env={**os.environ, 'UNBUG_FACTORY_SLOT': '0'}, check=True)

    # Parked factory DBs are started before reset SQL; nonfactory baseline remains unchanged.
    calls = []
    def record_dc(*args, **kwargs): calls.append(args); return ''
    def stop_at_sql(*args, **kwargs): raise RuntimeError('synthetic reset boundary')
    for env, starts in (({'UNBUG_FACTORY_SLOT': '1'}, True), ({}, False)):
        calls.clear()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(bench, 'dc', record_dc), \
             mock.patch.object(bench, 'stop_inventory_services'), mock.patch.object(bench, 'sql', stop_at_sql):
            try: bench.reset(guard, app_prepared=True)
            except RuntimeError as error: assert str(error) == 'synthetic reset boundary'
            else: raise AssertionError('reset did not reach SQL')
        assert (('up', '-d', '--wait', 'postgres', 'redis') in calls) is starts

    # Two real Node traffic processes invoke the hook API against separate synthetic HTTP ledgers.
    # Throw after the hook so no Medusa traffic/application behavior is simulated or scored.
    hook = root / "hook"; hook.mkdir()
    (hook / "hooks.mjs").write_text('''
export async function before(ctx) {
  try { ctx.serviceURL("missing"); throw new Error("missing accepted"); }
  catch (e) { if (!e.message.startsWith("No declared")) throw e; }
  try { ctx.serviceURL("channel", "http://example.com/"); throw new Error("external accepted"); }
  catch (e) { if (!e.message.startsWith("Inventory service path")) throw e; }
  ctx.record.identity = await (await fetch(ctx.serviceURL("channel", "/identity"))).json();
  throw new Error("synthetic hook complete");
}
''')
    ids = root / "ids.json"; ids.write_text(json.dumps({"admin": {}, "products": [], "publishable_key": "synthetic"}))
    servers = []
    def serve(identity):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0))); self.respond({"token": "synthetic"})
            def do_GET(self): self.respond(identity)
            def respond(self, body):
                encoded = json.dumps(body).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_port
    api = serve({"api": True})
    ports = [serve({"slot": i}) for i in range(2)]
    def traffic(slot):
        options = {"scenarios": [{"id": "synthetic", "dir": str(hook)}], "inventory_service_ports": {"channel": [ports[slot]]}}
        result = subprocess.run(["node", str(bench.ROOT / "cases/medusa-oversell/traffic/run.mjs"), str(ids), "1", json.dumps(options)],
                                env={**os.environ, "BENCH_URL": f"http://127.0.0.1:{api}", "BENCH_URL_B": f"http://127.0.0.1:{api}"},
                                capture_output=True, text=True, timeout=15, check=True)
        record = json.loads(result.stdout)
        assert record["scenario_records"]["synthetic"]["identity"] == {"slot": slot}
        assert "synthetic hook complete" in record["error"]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(traffic, range(2)))
    finally:
        for server in servers: server.shutdown(); server.server_close()

    # Trusted live-window traffic carries the same endpoint contract, on exam slot zero.
    module = importlib.util.spec_from_file_location("synthetic_reader", bench.ROOT / "harbor/phase2/reader.py")
    reader = importlib.util.module_from_spec(module); module.loader.exec_module(reader)
    live = reader.DockerLiveReader("synthetic", 1)
    async def write_only(*args, **kwargs): return ""
    with mock.patch.object(live, "python", write_only):
        options = asyncio.run(live.prepare_traffic({"traffic": {"mode": "stress"}, "inventory_services": [{"name": "channel", "host_ports": [9010]}]}))
    assert options["inventory_service_ports"] == {"channel": [9010]}
print("PASS inventory port contracts, Compose overrides, monitor blindness, legacy fallback, independent hook endpoints")
