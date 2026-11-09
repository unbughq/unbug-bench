#!/usr/bin/env python3
"""Bench orchestration. Python standard library only; Docker provides the runtime."""
import contextlib
import bench_judging
# Public case judges and checkpoint tools retain the established observation helpers.
from bench_judging import (PHASES, STOCK, CROWD_STOCK, PATH_OF_KIT, BASE_CHECKS,
                           kit_units, confirmed_order, cross_check, crowd_check, score, wilson)
import argparse, datetime, fcntl, hashlib, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time, urllib.request
if "MEDUSA_DEPS_IMAGE" not in os.environ and pathlib.Path("/opt/medusa-deps-image").is_file():
    os.environ["MEDUSA_DEPS_IMAGE"] = pathlib.Path("/opt/medusa-deps-image").read_text().strip()
ROOT = pathlib.Path(__file__).resolve().parents[1]
# Appended, never first: on a worker this file comes from the baked bench (~/unbug-bench), and the
# factory release's own modules must keep precedence over the bench's copy (9 November: G16 loaded
# fairness.py from the baked bench instead of the deployed release).
if str(ROOT / "factory") not in sys.path:
    sys.path.append(str(ROOT / "factory"))
from case_permissions import normalize_case_tree
APP = ROOT / "projects/medusa"
COMPOSE_PROJECT = "unbug-bench"
COMPOSE = ["docker", "compose", "-f", str(APP / "compose.yaml")]
IDS = APP / "seed-ids.json"
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)  # every CLI opens .bench.lock after importing bench
FACTORY_SLOT = int(os.environ.get("UNBUG_FACTORY_SLOT", "0"))
GUARD_IMAGE = "unbug-bench-medusa:guard"
PORTS = (9000, 9001)
if FACTORY_SLOT:
    # Factory workers opt in; the exam and Harbor keep the original project and ports.
    RESULTS = RESULTS / "factory-slots" / str(FACTORY_SLOT)
    RESULTS.mkdir(parents=True, exist_ok=True)
    IDS = RESULTS / "seed-ids.json"
    PORTS = tuple(p + 100 * FACTORY_SLOT for p in PORTS)
    GUARD_IMAGE += f"-{FACTORY_SLOT}"
    override = RESULTS / ".slot-compose.yaml"
    # !override is needed because Compose otherwise merges ports by container/host tuple.
    override.write_text("services:\n" + "".join(
        f"  {s}:\n    ports: !override [\"127.0.0.1:{p}:9000\"]\n"
        for s, p in zip(("medusa", "medusa-b"), PORTS)))
    COMPOSE += ["-p", f"unbug-factory-{FACTORY_SLOT}", "-f", str(override)]
    os.environ.update(BENCH_URL=f"http://127.0.0.1:{PORTS[0]}", BENCH_URL_B=f"http://127.0.0.1:{PORTS[1]}")
APP_SERVICES = ("medusa", "medusa-b")  # two app instances, ports 9000 and 9001
EXPECTED_BASELINE = dict(units_sold_x=0, stocked_x=10, reserved_x=0, available_x=10, reservation_rows_sum_x=0,
    units_sold_s=0, available_s=10,
    kits={k: dict(stocked=n, reserved=0, reservation_rows=0, sold=0, identity_ok=True) for k, n in {**STOCK, "bo": 4}.items()},
    normal_orders_placed=0, trigger_orders_placed=0, sequential_first_placed=False, legit_orders_placed=0,
    concurrent_oversold=False, sequential_oversold=False, oversold=False, oversold_other_items=[], overreserved=False, bookkeeping_ok=True, normal_ok=False,
    trigger_ok=False, legit_concurrent_ok=False, backorder_ok=False, draft_oversold=False, edit_oversold=False,
    draft_store_placed=False, draft_fit_placed=False, edit_store_placed=False, edit_fit_placed=False, draft_ok=False,
    edit_ok=False, resold_oversold=False, resold_ok=False, checker_ok=True, valid=True, orders={}, **{"pass": False})

# Operational metadata only. Never copy commands, labels, paths, errors or verdicts here.
_PROGRESS = None
_INVENTORY_PREPARATION = None  # batch-local; never reuse a previous case's images

class BenchProgress:
    def __init__(self, total):
        self.path = RESULTS / f"bench-progress-{os.getpid()}.json"
        self.data = {"schema": 1, "pid": os.getpid(), "slot": FACTORY_SLOT,
                     "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     "status": "running", "phase": "prepare", "completed_trials": 0,
                     "total_trials": total, "phase_seconds": {}}
        self.write()

    def write(self):
        self.data["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as output:
            temporary = pathlib.Path(output.name)
            json.dump(self.data, output)
            output.write("\n")
        temporary.replace(self.path)

    @contextlib.contextmanager
    def phase(self, name):
        previous = self.data["phase"]
        previous_started = self.data.get("phase_started_at")
        self.data["phase"] = name
        self.data["phase_started_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.write()
        start = time.monotonic()
        try:
            yield
        finally:
            seconds = self.data["phase_seconds"]
            seconds[name] = seconds.get(name, 0.0) + time.monotonic() - start
            self.data["phase"] = previous
            self.data["phase_started_at"] = previous_started
            self.write()


def phase(name):
    return _PROGRESS.phase(name) if _PROGRESS is not None else contextlib.nullcontext()

def command(args, *, data=None, capture=True, cwd=ROOT, timeout=3600):
    import processes
    p = processes.run(args, cwd=cwd, input=data, text=True, timeout=timeout, stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)
    if p.returncode:
        raise RuntimeError(f"Command failed: {args}\n{p.stdout or ''}\n{p.stderr or ''}")
    return (p.stdout or "").strip()

def dc(*args, **kw): return command(COMPOSE + list(args), **kw)
def sql(query, database="medusa", user="medusa"):
    args = ["exec", "-T", "postgres", "psql", "-Xq", "-v", "ON_ERROR_STOP=1", "-At", "-U", user, "-d", database]
    if user == "bench_guard":
        # -c also accepts a single psql backslash command; reject those explicitly.
        if any(line.lstrip().startswith("\\") for line in query.splitlines()):
            raise ValueError("Guard SQL cannot contain psql backslash commands")
        return dc(*args, "-c", query)
    return dc(*args, data=query)

def wait_ready():
    # 180 s: under heavy host load (load average > 100 seen 2026-10-14) startup took 49 s.
    deadline = time.monotonic() + 180
    for port in PORTS:
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                    if r.status == 200: break
            except (OSError, TimeoutError): pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"Medusa on port {port} did not become healthy within 180 seconds")
            time.sleep(.2)

# The judge (harbor tests/test.sh sets UNBUG_JUDGE=1) reads as the administrator, which no landed
# change can hide rows from; bench_checker is the contestant box's own view and can go blind (S11).
CHECKER_ROLE = "medusa" if os.environ.get("UNBUG_JUDGE") else "bench_checker"

def checker(user=None):
    q = (ROOT / "cases/medusa-oversell/checker/check.sql").read_text()
    ids = json.loads(IDS.read_text())
    for key in ("inventory_x", "product_x", "variant_single", "variant_pack"):
        q = q.replace("{{" + key + "}}", "'" + ids[key].replace("'", "''") + "'")
    return json.loads(sql(q, user=user or CHECKER_ROLE))


def inventory_services(scenarios):
    """Declarations are bench input; adapters remain outside guard-patched runtime code."""
    services = {}
    for scenario in scenarios:
        for entry in scenario.get("inventory_services", []):
            name = entry["name"]
            if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or name in (*APP_SERVICES, "postgres", "redis"):
                raise ValueError(f"Invalid inventory service name: {name}")
            project = pathlib.Path(entry["project"])
            if not project.is_absolute(): project = (scenario["dir"] / project if (scenario["dir"] / project).is_dir() else ROOT / project)
            project = project.resolve()
            service = {"name": name, "project": project, "compose": project / "compose.yaml"}
            if "host_ports" in entry:
                ports = entry["host_ports"]
                if (not isinstance(ports, list) or any(type(p) is not int or not 9002 <= p < 9100 for p in ports)
                        or len(ports) != len(set(ports))):
                    raise ValueError(f"Inventory service {name} host_ports must be unique integers in 9002..9099")
                service["host_ports"] = ports
            if not service["compose"].is_file() or not (project / "adapter.py").is_file():
                raise ValueError(f"Inventory service {name} needs compose.yaml and adapter.py")
            if name in services and services[name] != service:
                raise ValueError(f"Conflicting inventory service: {name}")
            services[name] = service
    declared = [p for s in services.values() for p in s.get("host_ports", [])]
    if len(declared) != len(set(declared)): raise ValueError("Inventory services cannot share host_ports")
    return list(services.values())

def isolated_inventory_services(scenarios):
    """Opt-in contract: hooks use ctx.serviceURL, and all publications are declared loopback TCP."""
    return all("host_ports" in s for s in inventory_services(scenarios))

def inventory_service_ports(services, slot=None):
    slot = FACTORY_SLOT if slot is None else slot
    return {s["name"]: [p + 100 * slot for p in s["host_ports"]] for s in services if "host_ports" in s}

def docker_memory_bytes():
    # Containers are daemon-owned, outside the SSH runner's user.slice on Boat.
    total = int(command(["docker", "info", "--format", "{{.MemTotal}}"]))
    if total <= 0: raise ValueError("Unknown host memory")
    return total

def factory_memory_fits(scenarios, copies):
    """Unknown/uncapped services stay serial; never raise container limits to fit a schedule."""
    try:
        services = inventory_services(scenarios)
        compose = COMPOSE + [a for s in services for a in ("-f", str(s["compose"]))]
        config = json.loads(command(compose + ["config", "--format", "json"]))
        if any(s.get('scale', 1) != 1 or (s.get('deploy') or {}).get('replicas', 1) != 1
               or (s.get('deploy') or {}).get('mode', 'replicated') != 'replicated' for s in config['services'].values()):
            return False  # memory accounting is one container per service
        caps = [s.get("mem_limit") for s in config["services"].values()]
        if not caps or any(type(n) not in (int, str) or not str(n).isdigit() or int(n) <= 0 for n in caps): return False
        return copies * sum(map(int, caps)) + 768 * 1024**2 <= docker_memory_bytes()
    except Exception:
        return False

INVENTORY_STATE = RESULTS / ".inventory-services.json"

def stop_inventory_services():
    if INVENTORY_STATE.exists():
        state = json.loads(INVENTORY_STATE.read_text())
        command(state["compose"] + ["stop", *state["names"]])
        command(state["compose"] + ["rm", "-f", *state["names"]])
        INVENTORY_STATE.unlink()

def service_adapter(service, action, compose):
    return json.loads(command([sys.executable, str(service["project"] / "adapter.py"), action,
                               service["name"], json.dumps(compose)]))

def inventory_build_signature(services, guard_path, config):
    """Only cache self-contained build contexts; external build inputs retain fresh builds."""
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    for service in services:
        project = service["project"]
        build = config["services"][service["name"]].get("build") or {}
        if set(build) - {"context", "dockerfile", "args", "target", "labels", "network", "shm_size", "ulimits", "platforms"}:
            return None
        dockerfile = project / build.get("dockerfile", "Dockerfile")
        if not dockerfile.resolve().is_relative_to(project.resolve()): return None
        digest.update(json.dumps({k: str(v) for k, v in service.items()}, sort_keys=True).encode())
        for directory, dirs, files in os.walk(project):
            dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", "node_modules", ".git"))
            if any((pathlib.Path(directory) / d).is_symlink() for d in dirs): return None
            digest.update(json.dumps([str(pathlib.Path(directory).relative_to(project)), pathlib.Path(directory).stat().st_mode]).encode())
            for filename in sorted(files):
                path = pathlib.Path(directory) / filename
                if path.is_symlink(): return None
                digest.update(json.dumps([str(path.relative_to(project)), path.stat().st_mode,
                                         hashlib.sha256(path.read_bytes()).hexdigest()]).encode())
    patch = guard_path / "services.patch"
    digest.update(b"patch:" + (patch.read_bytes() if patch.exists() else b""))
    return digest.hexdigest()

def start_inventory_services(services, guard_path, blind_monitors=()):
    if not services: return {}
    compose = COMPOSE + [a for service in services for a in ("-f", str(service["compose"]))]
    ports, config = {}, None
    if FACTORY_SLOT:
        if not all("host_ports" in s for s in services):
            raise ValueError("Inventory services without the host_ports isolation contract require slot zero")
        config = json.loads(command(compose + ["config", "--format", "json", "--no-normalize"]))
        if any(x.get("external") or x.get("name") for kind in ("volumes", "networks") for x in config.get(kind, {}).values()):
            raise ValueError("Isolated inventory services cannot use external or explicitly named storage/networks")
        if any(x.get("driver_opts") or x.get("driver", default) != default
               for kind, default in (("volumes", "local"), ("networks", "bridge")) for x in config.get(kind, {}).values()):
            # Even a project-scoped local volume can bind /shared-data through driver_opts.
            raise ValueError("Isolated inventory services require plain local volumes and bridge networks")
        if any(s.get("container_name") or s.get("network_mode") or any(v.get("type") == "bind" for v in s.get("volumes", []))
               for s in config["services"].values()):
            raise ValueError("Isolated inventory services require project-scoped containers and storage")
        for service in services:
            runtime = config["services"][service["name"]]
            published = runtime.get("ports", [])
            if (any(p.get("host_ip") != "127.0.0.1" or p.get("protocol", "tcp") != "tcp" for p in published) or
                    sorted(int(p["published"]) for p in published) != sorted(service["host_ports"])):
                raise ValueError(f"Inventory service {service['name']} does not match its host_ports isolation contract")
            ports[service["name"]] = [{**p, "published": str(int(p["published"]) + 100 * FACTORY_SLOT)} for p in published]
    override = RESULTS / ".inventory-compose.json"
    if ports:
        # Compose merges ports by host/container tuple unless !override replaces the original list.
        port_override = RESULTS / ".inventory-ports.yaml"
        port_override.write_text("services:\n" + "".join(f"  {name}:\n    ports: !override {json.dumps(value)}\n" for name, value in ports.items()))
        compose += ["-f", str(port_override)]
    signature = None
    if _INVENTORY_PREPARATION is not None:
        if config is None:
            config = json.loads(command(compose + ["config", "--format", "json", "--no-normalize"]))
        signature = inventory_build_signature(services, guard_path, config)
        # Monitor visibility is runtime configuration, included so the saved override stays exact.
        if signature is not None: signature += json.dumps(sorted(blind_monitors))
    if signature is not None and _INVENTORY_PREPARATION.get("signature") == signature:
        compose = _INVENTORY_PREPARATION["compose"]
    else:
        if _INVENTORY_PREPARATION is not None: _INVENTORY_PREPARATION.clear()
        compose = build_inventory_services(services, guard_path, blind_monitors, compose, override)
        if signature is not None:
            _INVENTORY_PREPARATION.update(signature=signature, compose=compose)
    # Save before up: the next reset also cleans up a partially started service.
    INVENTORY_STATE.write_text(json.dumps({"compose": compose, "names": [s["name"] for s in services]}))
    try:
        command(compose + ["up", "-d", "--no-deps", "--no-build", "--wait", *[s["name"] for s in services]])
    except Exception as error:
        logs = command(compose + ["logs", "--no-color", "--tail", "30", *[s["name"] for s in services]])
        raise RuntimeError(f"{error}\n{logs}") from error
    for service in services:
        if service_adapter(service, "reset", compose) != {"orders": {}} or service_adapter(service, "check", compose) != {"orders": {}}:
            raise RuntimeError(f"Inventory service {service['name']} did not reset to an empty ledger")
    return {s["name"]: {"orders": {}} for s in services}

def build_inventory_services(services, guard_path, blind_monitors, compose, override):
    with tempfile.TemporaryDirectory(prefix="unbug-services-") as temporary:
        context = pathlib.Path(temporary)
        for service in services:
            shutil.copytree(service["project"], context / service["name"],
                            ignore=shutil.ignore_patterns("__pycache__", "node_modules", ".git"))
        patch = guard_path / "services.patch"
        if patch.exists():
            paths = command(["git", "apply", "--numstat", str(patch)]).splitlines()
            for line in paths:
                path = pathlib.PurePosixPath(line.split("\t", 2)[2])
                if path.parts[0] not in {s["name"] for s in services} or any(p == ".." for p in path.parts) or path.name in ("adapter.py", "compose.yaml", "Dockerfile"):
                    raise ValueError(f"Service guard cannot patch {path}")
            command(["git", "apply", "--check", str(patch)], cwd=context)
            command(["git", "apply", str(patch)], cwd=context)
        # COPY retains source modes, including private files newly made by git apply.
        for service in services:
            normalize_case_tree(context / service["name"])
        override.write_text(json.dumps({"services": {s["name"]: {
            "image": f"unbug-bench-service-{s['name']}:guard" + (f"-{FACTORY_SLOT}" if FACTORY_SLOT else ""),
            "environment": {"UNBUG_MONITOR_BLIND": "1" if s["name"] in blind_monitors else "0"},
            "build": {"context": str(context / s["name"])}
        } for s in services}}))
        compose += ["-f", str(override)]
        command(compose + ["build", *[s["name"] for s in services]])
    return compose

def check_inventory_services(services):
    if not services: return {}
    compose = json.loads(INVENTORY_STATE.read_text())["compose"]
    return {s["name"]: service_adapter(s, "check", compose) for s in services}

def setup(scenarios=()):
    command(["node", str(APP / "verify-lock.mjs")])
    dc("build", "medusa")
    dc("up", "-d", "--wait", "postgres", "redis")
    dc("run", "--rm", "--no-deps", "-e", "DATABASE_URL=postgres://medusa:medusa@postgres:5432/medusa", "medusa", "npm", "run", "migrate")
    seed_container = f"unbug-factory-{FACTORY_SLOT}-seed" if FACTORY_SLOT else "unbug-bench-seed"
    def remove_seed():
        # A failed/killed setup can leave the explicit name behind. Ignore "not found";
        # a daemon failure will be reported by the following captured setup command.
        with contextlib.suppress(RuntimeError):
            command(["docker", "rm", "-f", seed_container])
    remove_seed()
    try:
        dc("run", "--name", seed_container, "--no-deps", "-e", "DATABASE_URL=postgres://medusa:medusa@postgres:5432/medusa", "medusa", "npm", "run", "seed")
        command(["docker", "cp", seed_container + ":/app/seed-ids.json", str(IDS)])
    finally:
        remove_seed()
    admin = json.loads(IDS.read_text())["admin"]  # admin API login for draft orders and order edits
    dc("run", "--rm", "--no-deps", "-e", "DATABASE_URL=postgres://medusa:medusa@postgres:5432/medusa", "medusa",
       "npx", "medusa", "user", "-e", admin["email"], "-p", admin["password"])
    sql("""CREATE ROLE bench_checker LOGIN BYPASSRLS; ALTER ROLE bench_checker SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE medusa TO bench_checker; GRANT USAGE ON SCHEMA public TO bench_checker;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bench_checker;""")
    sql("""SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'medusa' AND pid <> pg_backend_pid();
CREATE DATABASE medusa_seed WITH TEMPLATE medusa; ALTER DATABASE medusa_seed ALLOW_CONNECTIONS false;""", database="postgres")
    baseline = reset(scenarios=scenarios)
    (RESULTS / "runs").mkdir(exist_ok=True)
    (RESULTS / "runs/baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
    return baseline


def factory_slot_ready(results, slot):
    """A seed-ID file alone does not prove that setup finished.

    This receipt proves completed preparation, not a live database. Every trial
    still restores the seed template and validates the baseline before scoring.
    """
    if slot < 1:
        raise ValueError("factory readiness requires a nonzero slot")
    directory = results / "factory-slots" / str(slot)
    try:
        receipt = json.loads((directory / ".prepared.json").read_text())
        return receipt == {"version": 1, "slot": slot,
                           "seed_ids_sha256": hashlib.sha256((directory / "seed-ids.json").read_bytes()).hexdigest()}
    except (OSError, ValueError):
        return False


def prepare_factory_main():
    """Fresh startup/G3 shop; factory_pool owns the root bench lock."""
    if FACTORY_SLOT:
        raise ValueError("main preparation requires slot zero")
    stop_inventory_services()
    # Baked containers can retain fixed names without adoptable Compose labels.
    # Release their named volumes BEFORE down -v, or seeding reuses the old DB.
    with contextlib.suppress(RuntimeError):
        command(["docker", "rm", "-f", *[f"{COMPOSE_PROJECT}-{name}-1"
                 for name in ("postgres", "redis", "medusa", "medusa-b")]])
    dc("down", "-v")
    # setup owns stale seed-container removal, diagnostics and baseline checks.
    # The parent holds .bench.lock across this subprocess and all extra slots.
    return setup()


def retire_factory_slot():
    """Discard only this disposable extra slot and its readiness evidence."""
    if FACTORY_SLOT < 1:
        raise ValueError("factory slot retirement requires a nonzero slot")
    (RESULTS / ".prepared.json").unlink(missing_ok=True)
    stop_inventory_services()
    dc("down", "-v", "--remove-orphans")
    IDS.unlink(missing_ok=True)


def prepare_factory_slot():
    """Prepare one disposable shop; publish readiness only after cleanup succeeds."""
    if FACTORY_SLOT < 1:
        raise ValueError("factory slot preparation requires a nonzero slot")
    receipt = RESULTS / ".prepared.json"
    receipt.unlink(missing_ok=True)
    stop_inventory_services()
    dc("down", "-v", "--remove-orphans")
    IDS.unlink(missing_ok=True)
    try:
        try:
            setup()
        finally:
            dc("stop")
        ready = {"version": 1, "slot": FACTORY_SLOT,
                 "seed_ids_sha256": hashlib.sha256(IDS.read_bytes()).hexdigest()}
        temporary = receipt.with_suffix(".tmp")
        temporary.write_text(json.dumps(ready) + "\n")
        temporary.replace(receipt)
    except BaseException:
        IDS.unlink(missing_ok=True)
        receipt.unlink(missing_ok=True)
        raise


def app_patches(guard_path, scenarios=()):
    """Scenario changes first, then the guard's own patch (written against the changed app)."""
    # A landed change's app.patch is already merged into projects/medusa (bin/land).
    return [p for p in [s["dir"] / "app.patch" for s in scenarios if not s.get("admin_only")] + [guard_path / "app.patch"] if p.exists()]

def prepare_app_guard(guard_path, scenarios=()):
    """Build an isolated application image; the pinned source tree stays untouched."""
    patches = app_patches(guard_path, scenarios)
    if not patches:
        return
    dc("stop", *APP_SERVICES)
    with tempfile.TemporaryDirectory(prefix="unbug-guard-") as temporary:
        context = pathlib.Path(temporary)
        shutil.copytree(APP, context, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("node_modules", ".medusa", "seed-ids.json"))
        for patch in patches:
            command(["git", "apply", "--check", str(patch)], cwd=context)
            command(["git", "apply", str(patch)], cwd=context)
        command(["docker", "build", "--build-arg", "MEDUSA_DEPS_IMAGE=" + os.environ.get("MEDUSA_DEPS_IMAGE", "node:22.22.2-bookworm-slim"), "--memory=2560m", "-t", GUARD_IMAGE, str(context)], capture=False)

def start_app(guard_image):
    """Start both app instances: the image prepare_app_guard built, else the pinned app image."""
    if guard_image:
        override = RESULTS / ".guard-compose.yaml"
        override.write_text("services:\n" + "".join(f"  {s}:\n    image: {GUARD_IMAGE}\n" for s in APP_SERVICES))
        command(COMPOSE + ["-f", str(override), "up", "-d", "--no-deps", "--no-build", *APP_SERVICES])
    else:
        dc("up", "-d", "--no-deps", *APP_SERVICES)
    wait_ready()

# Changes landed in a contestant box by bin/land (Harbor step setup): their admin.sql is part of
# the live app from then on, so a plain reset (no scenarios) re-applies it. Absent on the judge.
LANDED = ROOT / "changes"

def reset(guard="none", *, app_prepared=False, scenarios=(), progress=None, refusal=None):
    # ponytail: landed admin.sql replays in directory-name order; record landing order if two ever interact.
    scenarios = scenarios or [{"dir": f.parent, "admin_only": True} for f in sorted(LANDED.glob("*/admin.sql"))]
    guard_path = resolve_guard(guard)
    if not app_prepared: prepare_app_guard(guard_path, scenarios)
    start = time.monotonic()
    with phase("reset_stop"):
        stop_inventory_services()
        services = inventory_services(scenarios)
        if "UNBUG_FACTORY_SLOT" in os.environ:
            # Serial fallback may park idle peers, including their databases; never reset a peer's shop.
            dc("up", "-d", "--wait", "postgres", "redis")
        dc("stop", *APP_SERVICES)
    with phase("reset_database_cache"):
        # Row-level security must never hide rows from the checker; reasserted every reset.
        sql("""SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'medusa';
    DROP DATABASE IF EXISTS medusa; CREATE DATABASE medusa WITH TEMPLATE medusa_seed;
    ALTER ROLE bench_checker BYPASSRLS;""", database="postgres")
        if progress is not None: progress["fresh_database"] = True  # this run's database, not a previous one
        dc("exec", "-T", "redis", "redis-cli", "FLUSHALL")
        baseline = checker("medusa")  # bench integrity, never the contestant's view
        expected = EXPECTED_BASELINE
        if baseline != expected: raise RuntimeError(f"Unexpected reset baseline: {baseline}")
        # Roles and the template remain owned by the bench administrator. Guard SQL
        # owns only restored application tables (needed for ADD CONSTRAINT), never
        # the database/schema, template, bench objects, or privileged roles.
        sql("""DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bench_guard') THEN
            CREATE ROLE bench_guard LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
          END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'medusa_app') THEN
            CREATE ROLE medusa_app LOGIN PASSWORD 'medusa_app' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
          END IF;
          -- Contestants' monitors (CONTESTANT.md): read-only login on app tables.
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'arm_monitor') THEN
            CREATE ROLE arm_monitor LOGIN PASSWORD 'arm_monitor' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
          END IF;
        END $$;
        ALTER ROLE bench_guard RESET ALL;
        ALTER ROLE medusa_app RESET ALL;
        REVOKE ALL ON DATABASE medusa FROM PUBLIC;
        GRANT CONNECT ON DATABASE medusa TO bench_guard, bench_checker, medusa_app;
        REVOKE CREATE ON SCHEMA public FROM PUBLIC;
        GRANT USAGE, CREATE ON SCHEMA public TO bench_guard;
        GRANT USAGE ON SCHEMA public TO medusa_app;
        GRANT CONNECT ON DATABASE medusa TO arm_monitor;
        GRANT USAGE ON SCHEMA public TO arm_monitor;
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO arm_monitor;
        DO $$ DECLARE t record; BEGIN
          FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
            EXECUTE format('ALTER TABLE public.%I OWNER TO bench_guard', t.tablename);
          END LOOP;
        END $$;
        -- Keep owner DML privileges: PostgreSQL FK cascades/Medusa compensation
        -- execute as table owner. Seed tampering is rejected by the checker.
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO medusa_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO medusa_app;
        ALTER DEFAULT PRIVILEGES FOR ROLE bench_guard IN SCHEMA public
          GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO medusa_app;
        ALTER DEFAULT PRIVILEGES FOR ROLE bench_guard IN SCHEMA public
          GRANT USAGE, SELECT ON SEQUENCES TO medusa_app;
        """)
        app_tables = sql("SELECT string_agg(oid::text, ',') FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'")
        if (guard_path / "db.sql").exists(): sql((guard_path / "db.sql").read_text(), user="bench_guard")
        # Return restored app tables to the administrator once the guard is installed, so
        # no guard object (e.g. a SECURITY DEFINER function) can later ALTER, DROP or
        # re-own them while traffic runs. FK cascades run as the new owner; the app role
        # keeps its DML grants, so Medusa compensation is unaffected.
        sql(f"""DO $$ DECLARE t regclass; BEGIN
          FOR t IN SELECT oid::regclass FROM pg_class WHERE oid = ANY('{{{app_tables}}}'::oid[]) LOOP
            EXECUTE format('ALTER TABLE %s OWNER TO medusa', t);
            EXECUTE format('GRANT SELECT, REFERENCES, TRIGGER ON %s TO bench_guard', t);
          END LOOP;
        END $$;""")
        # Scenario database changes (as the administrator), after the guard and before the app starts.
        for s in scenarios:
            if (s["dir"] / "admin.sql").exists(): sql((s["dir"] / "admin.sql").read_text())
        if refusal is not None: refusal.install()
    with phase("reset_app_start"):
        start_app(app_patches(guard_path, scenarios))
        if checker("medusa") != expected: raise RuntimeError("Baseline changed during application startup")
    with phase("reset_inventory_start"):
        service_baseline = start_inventory_services(services, guard_path, {name for s in scenarios for name in s.get("blind_monitors", [])})
    return {"reset_seconds": time.monotonic() - start, "checker": baseline, "inventory_services": service_baseline}


def resolve_guard(guard):
    path = pathlib.Path(guard)
    if not path.is_absolute(): path = ROOT / "guards" / guard
    if not path.is_dir(): raise ValueError(f"Unknown guard: {guard}")
    return path

GUARD_FILES = ("db.sql", "app.patch", "services.patch")
def digest(files):
    """SHA-256 over (name, content) pairs, in name order."""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode() + b"\0" + (files[name].encode() if isinstance(files[name], str) else files[name]) + b"\0")
    return h.hexdigest()

def bench_fingerprint():
    """Hashes of the files a verdict depends on, so a replay can tell whether the judge changed."""
    files = ["factory/case_permissions.py", "cases/medusa-oversell/checker/check.sql", "cases/medusa-oversell/traffic/run.mjs", "bin/bench.py", "bin/bench_judging.py", "bin/refusal.py", "projects/medusa/seed-ids.json"]
    files += [str(f.relative_to(ROOT)) for p in sorted((ROOT / "projects").iterdir()) if p.name != "medusa"
              for f in sorted(p.rglob("*")) if f.is_file() and "__pycache__" not in f.parts]
    # Keep the logical input name stable across slots; hash the IDs actually used by traffic.
    return {f: hashlib.sha256((IDS if f == "projects/medusa/seed-ids.json" else ROOT / f).read_bytes()).hexdigest() for f in files}

# Scored traffic is stress traffic (see README "Stress traffic"); {"mode": "normal"} is the fixed
# schedule used by the 2026-10-13 calibrations and bin/verify-negative.
DEFAULT_TRAFFIC = {"mode": "stress", "seed_base": 1}

def traffic_options(options, run):
    """Per-run traffic options. Stress runs get a seed derived from the base seed and run number
    unless an exact seed is given (replay); the seed is recorded with the run."""
    options = dict(options or DEFAULT_TRAFFIC)
    if options.get("mode") == "stress" and "seed" not in options:
        options["seed"] = (int(options.pop("seed_base", 1)) * 1_000_003 + run) % 2**31
    options.pop("seed_base", None)
    return options

def load_scenario(path):
    """A change scenario directory (see scenarios/dev/README.md)."""
    path = pathlib.Path(path).resolve()
    meta = json.loads((path / "scenario.json").read_text())
    key = json.loads((path / "key.json").read_text()) if (path / "key.json").exists() else None
    return {**meta, "dir": path, "key": key}

def scenario_files(scenario):
    return {str(f.relative_to(scenario["dir"])): f.read_bytes() for f in sorted(scenario["dir"].rglob("*"))
            if f.is_file() and "__pycache__" not in f.parts}


def inventory_judge(result, scenarios, medusa_units, limits, backorder, window_limits=None, services=None):
    """Resolve runtime service declarations before evaluating recorded observations."""
    return bench_judging.inventory_judge(result, inventory_services(scenarios) if services is None else services,
                                         medusa_units, limits, backorder, window_limits)


def judge_checkpoint(result, scenarios, *, declared_services=None, refusal=None):
    """Load scenario judges in the runtime; all verdict arithmetic lives in bench_judging."""
    services = inventory_services(scenarios) if declared_services is None else declared_services

    def scenario_verdict(scenario, observed):
        path = scenario["dir"] / "judge.py"
        if not path.exists(): return None
        namespace = {}
        exec(compile(path.read_text(), str(path), "exec"), namespace)
        try:
            extra = namespace["judge"](observed, refusal or sys.modules[__name__])
        except Exception as error:
            observed["errors"].append({"stage": "judge", "message": f"{scenario['id']}: {error}"})
            return {"checks": {f"{scenario['id']}_judge": False}}
        # None is reserved for an absent judge, never a malformed executed judge.
        if not isinstance(extra, dict):
            raise ValueError("Scenario judge must return an object")
        return extra

    return bench_judging.judge_checkpoint(result, scenarios, services=services, scenario_verdict=scenario_verdict)

def installation_identity(guard_path, scenarios):
    return {"guard_sha256": digest({f: (guard_path / f).read_bytes() for f in GUARD_FILES if (guard_path / f).exists()}),
            "scenarios": [{"id": s["id"], "sha256": digest(scenario_files(s))} for s in scenarios]}


def run_once(guard_path, i, options, preparation_error=None, scenarios=(), expected_installation=None):
    """One scored run: reset with the guard (and scenarios), traffic, checker, score. Never raises."""
    start = time.monotonic()
    for s in scenarios: options = {**(options or DEFAULT_TRAFFIC), **(s.get("traffic") or {})}
    options = traffic_options(options, i)
    if scenarios: options["scenarios"] = [{"id": s["id"], "dir": str(s["dir"])} for s in scenarios]
    options["inventory_service_ports"] = inventory_service_ports(inventory_services(scenarios))
    result = {"case": "medusa-oversell", "guard": guard_path.name, "run": i,
              "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "traffic_options": options, "host_load_average": os.getloadavg(), "traffic": None, "errors": []}
    reset_failed, progress = False, {}
    refusal = None
    # Judge-owned installation receipt: emitted only after reset applies these exact inputs.
    installation = expected_installation or installation_identity(guard_path, scenarios)
    try:
        if any((s["dir"] / "refusal_oracle.py").is_file() for s in scenarios):
            from refusal import BehavioralRefusal
            refusal = BehavioralRefusal(sys.modules[__name__], expected_installation or installation_identity(guard_path, scenarios), scenarios)
            refusal.guard_path = guard_path
            options["judge_refusal_socket"] = str(refusal.socket_path)
        if preparation_error:
            raise RuntimeError(f"Application guard preparation failed: {preparation_error}")
        if installation != installation_identity(guard_path, scenarios):
            raise RuntimeError("Installation inputs changed during preparation")
        with phase("reset"):
            result.update(reset(str(guard_path), app_prepared=True, scenarios=scenarios, progress=progress, **({"refusal": refusal} if refusal else {})))
            if installation != installation_identity(guard_path, scenarios):
                raise RuntimeError("Installation inputs changed during reset")
            result["installation"] = installation
            if refusal is not None: refusal.start()
    except Exception as error:
        result["errors"].append({"stage": "reset", "message": str(error)})
        result["reset_seconds"] = time.monotonic() - start
        reset_failed = True
    else:
        try:
            traffic_start = time.monotonic()
            with phase("traffic"):
                result["traffic"] = json.loads(command(["node", str(ROOT / "cases/medusa-oversell/traffic/run.mjs"), str(IDS), str(i), json.dumps(options)]))
            if result["traffic"].get("error"):
                result["errors"].append({"stage": "traffic", "message": result["traffic"]["error"]})
        except Exception as error:
            result["errors"].append({"stage": "traffic", "message": str(error)})
        finally:
            result["traffic_seconds"] = time.monotonic() - traffic_start
    # Failed checkout setup gets a database verdict. A failed reset never does: if it failed
    # before this run's database was created (e.g. the image build failed), the database is a
    # previous run's, so the checker is skipped; otherwise (e.g. a rejected guard) it is read
    # as evidence only. Either way the run is invalid.
    try:
        if reset_failed and not progress.get("fresh_database"):
            raise RuntimeError("skipped: reset failed before this run's database was created (stale state)")
        with phase("check"):
            result["checker"] = checker()
    except Exception as error:
        result["errors"].append({"stage": "checker", "message": str(error)})
        result["checker"] = {"valid": False, "oversold": False,
                             "normal_ok": False, "bookkeeping_ok": False, "pass": False}
    if not reset_failed:
        try:
            with phase("inventory_check"):
                result["inventory_services"] = check_inventory_services(inventory_services(scenarios))
        except Exception as error:
            result["errors"].append({"stage": "inventory-checker", "message": str(error)})
    if refusal is not None and not reset_failed:
        refusal.finalize(result)
        result["refusal_identity"] = refusal.identity
        if refusal.failure:
            result["errors"].append({"stage": "refusal-evidence", "message": refusal.failure})
    if refusal is not None:
        refusal.close()
    score(result)
    if reset_failed: result["checker"].update({"valid": False, "pass": False})
    if scenarios:
        result["judge"] = ({"rule": {}, "paths": {}, "violated": {}, "checks": {}, "legit": {"attempted": 0, "placed": 0},
                            "crowd": None, "facts": {}, "pass": False, "invalid": "reset failed"}
                           if reset_failed else judge_checkpoint(result, scenarios, **({"refusal": refusal} if refusal else {})))
        from refusal import invalidate_unqualified
        invalidate_unqualified(result)
    return result

def run_case(guard, runs, *, options=None, run_numbers=None, label=None, per_run_options=None, scenarios=(), factory_workers=1, frozen_inputs=False):
    global _PROGRESS, _INVENTORY_PREPARATION
    previous, previous_inventory = _PROGRESS, _INVENTORY_PREPARATION
    numbers = list(run_numbers or range(1, runs + 1))
    _PROGRESS = BenchProgress(len(numbers))
    _INVENTORY_PREPARATION = {}
    try:
        result = _run_case(guard, runs, options=options, run_numbers=numbers, label=label,
                           per_run_options=per_run_options, scenarios=scenarios, factory_workers=factory_workers, frozen_inputs=frozen_inputs)
        _PROGRESS.data.update(status="completed", phase="complete")
        return result
    except BaseException:
        _PROGRESS.data.update(status="failed", phase="stopped")
        raise
    finally:
        _PROGRESS.write()
        _PROGRESS = previous
        _INVENTORY_PREPARATION = previous_inventory

def _run_case(guard, runs, *, options=None, run_numbers=None, label=None, per_run_options=None, scenarios=(), factory_workers=1, frozen_inputs=False):
    run_numbers = list(run_numbers or range(1, runs + 1))
    if not run_numbers or min(run_numbers) < 1: raise ValueError("runs must be positive")
    requested_workers = factory_workers
    factory_workers = min(factory_workers, len(run_numbers))
    if requested_workers > factory_workers:
        import factory_pool
        for slot in range(factory_workers, requested_workers):
            subprocess.run([sys.executable, "-c", "import bench; bench.stop_inventory_services(); bench.dc('stop')"],
                           cwd=ROOT / 'bin', env=factory_pool.worker_env(slot), check=True)
    if factory_workers > 1 and (not isolated_inventory_services(scenarios) or not factory_memory_fits(scenarios, factory_workers)):
        import factory_pool
        # These are idle pool slots, not G10 peers (each G10 context requests one worker).
        # Their extra Postgres/Redis must not consume the serial shop's memory allowance.
        for slot in range(1, factory_workers):
            subprocess.run([sys.executable, "-c", "import bench; bench.stop_inventory_services(); bench.dc('stop')"],
                           cwd=ROOT / 'bin', env=factory_pool.worker_env(slot), check=True)
        factory_workers = 1
    guard_path = resolve_guard(guard)
    files = {f: (guard_path / f).read_text() for f in GUARD_FILES if (guard_path / f).exists()}
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    name = label or guard_path.name
    directory = RESULTS / "runs" / f"{stamp}-{name}"
    # The guard is stored with its runs so bin/replay can re-apply exactly what was scored.
    (directory / "guard").mkdir(parents=True)
    for f, text in files.items(): (directory / "guard" / f).write_text(text)
    # Scenario directories are stored too, in application order, so a replay re-applies them.
    applied, frozen_services, frozen_scenarios = [], {}, []
    for n, s in enumerate(scenarios, 1):
        source_hash = digest(scenario_files(s))
        if frozen_inputs:
            # Pool children score the parent's snapshot; re-freezing rewrites shared service paths.
            applied.append({"id": s["id"], "dir": str(s["dir"].relative_to(ROOT)), "sha256": source_hash,
                            "source_sha256": source_hash})
            frozen_scenarios.append(s)
            continue
        stored = directory / "scenarios" / f"{n:02}-{s['dir'].name}"
        for f, text in scenario_files(s).items():
            (stored / f).parent.mkdir(parents=True, exist_ok=True); (stored / f).write_bytes(text)
        if (s['dir'] / 'refusal_oracle.py').is_file():
            from refusal import policy_files
            (stored / 'refusal-policy.json').write_text(json.dumps(policy_files(s['dir']), sort_keys=True))
        # Freeze service baselines with the scenario, including external/relative projects.
        # Replay's existing scenario digest then covers source, adapter and Compose together.
        declared = inventory_services([s])
        if declared:
            meta = json.loads((stored / "scenario.json").read_text())
            meta["inventory_services"] = []
            for service in declared:
                identity = (service["name"], service["project"])
                if identity not in frozen_services:
                    project = stored / "inventory_sources" / service["name"]
                    shutil.copytree(service["project"], project, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("__pycache__", "node_modules", ".git"))
                    frozen_services[identity] = project
                meta["inventory_services"].append({"name": service["name"], "project": os.path.relpath(frozen_services[identity], stored),
                                                   **({"host_ports": service["host_ports"]} if "host_ports" in service else {})})
            (stored / "scenario.json").write_text(json.dumps(meta, indent=2) + "\n")
        applied.append({"id": s["id"], "dir": str(stored.relative_to(ROOT)), "sha256": digest(scenario_files({"dir": stored})),
                        "source_sha256": source_hash})
        frozen_scenarios.append(load_scenario(stored))
    frozen_guard = directory / "guard"
    expected_installation = installation_identity(frozen_guard, frozen_scenarios)
    preparation_error = None
    parallel = None
    if factory_workers > 1:
        import factory_pool
        with phase("parallel_trials"):
            parallel = factory_pool.run_records(frozen_guard, run_numbers, options, frozen_scenarios, factory_workers, per_run_options)
    else:
        try:
            with phase("prepare"):
                prepare_app_guard(frozen_guard, frozen_scenarios)
        except Exception as error:
            preparation_error = str(error)
    outcomes = []
    for i in run_numbers:
        result = parallel[i] if parallel is not None else run_once(frozen_guard, i, (per_run_options or {}).get(i, options), preparation_error, frozen_scenarios, expected_installation)
        if result.get("installation") != expected_installation or installation_identity(frozen_guard, frozen_scenarios) != expected_installation:
            result.pop("installation", None)
            result["errors"].append({"stage": "installation", "message": "Frozen installation identity changed"})
        # Pool workers fingerprint their own seed manifest. The parent uses a
        # different shop and must retain each worker's execution provenance.
        if parallel is None:
            result["bench_sha256"] = bench_fingerprint()
        result.update(guard=guard_path.name, guard_sha256=digest(files), scenarios=applied)
        (directory / f"{i:02}.json").write_text(json.dumps(result, indent=2) + "\n")
        outcomes.append(result)
        if _PROGRESS is not None:
            _PROGRESS.data["completed_trials"] += 1
            _PROGRESS.write()
        brief = {k: v for k, v in result["checker"].items() if k not in ("orders", "kits", "confirmed_problems", "stress")}
        print(f"{name} {i}/{run_numbers[-1]}: {json.dumps(brief)} errors={len(result['errors'])} reset={result['reset_seconds']:.3f}s", flush=True)
    count = lambda field: sum(bool(r["checker"].get(field)) for r in outcomes)
    by_offset = {}
    for r in outcomes:
        o = by_offset.setdefault(str((r["traffic"] or {}).get("dispatch_offset_ms")), {"runs": 0, "concurrent_oversold": 0, "concurrent_placed": {}})
        o["runs"] += 1; o["concurrent_oversold"] += bool(r["checker"].get("concurrent_oversold"))
        p = r["checker"].get("concurrent_placed"); o["concurrent_placed"][p] = o["concurrent_placed"].get(p, 0) + 1
    n = len(outcomes)
    summary = {"guard":name, "runs":n, "traffic_options": options or DEFAULT_TRAFFIC, "guard_sha256": digest(files), "scenarios": applied, **{f: count(f) for f in SUMMARY_FIELDS}, "errors":sum(bool(r["errors"]) for r in outcomes), "invalid":sum(not r["checker"]["valid"] for r in outcomes), "by_dispatch_offset_ms": by_offset, "reset_seconds": {"min":min(r["reset_seconds"] for r in outcomes), "max":max(r["reset_seconds"] for r in outcomes), "mean":sum(r["reset_seconds"] for r in outcomes)/n}, "results_directory":str(directory.relative_to(ROOT))}
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary

SUMMARY_FIELDS = ("crowd_oversold", "crowd_ok", "oversold", "concurrent_oversold", "sequential_oversold", "draft_oversold", "edit_oversold", "normal_ok", "trigger_ok", "legit_concurrent_ok", "backorder_ok", "draft_ok", "edit_ok", "resold_oversold", "resold_ok", "bookkeeping_ok", "confirmed_orders_ok", "pass")

def main():
    os.chdir(ROOT); RESULTS.mkdir(exist_ok=True)
    with (RESULTS / ".bench.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        action = sys.argv[1]
        if action in ("setup", "reset"):
            p = argparse.ArgumentParser(prog="bin/" + action)
            p.add_argument("--scenario", action="append", default=[])
            if action == "reset": p.add_argument("--guard", default="none")
            a = p.parse_args(sys.argv[2:])
            scenarios = [load_scenario(s) for s in a.scenario]
            for scenario in scenarios:
                if scenario["dir"].parent == LANDED: scenario["admin_only"] = True
            result = setup(scenarios) if action == "setup" else reset(a.guard, scenarios=scenarios)
        elif action == "check": result = checker()
        elif action == "run-case":
            p = argparse.ArgumentParser(prog="bin/run-case")
            p.add_argument("case", choices=["medusa-oversell"]); p.add_argument("guard"); p.add_argument("runs", nargs="?", type=int, default=1)
            p.add_argument("--normal", action="store_true", help="fixed normal schedule instead of stress traffic")
            p.add_argument("--seed", type=int, default=1, help="base seed for stress traffic")
            a = p.parse_args(sys.argv[2:])
            result = run_case(a.guard, a.runs, options={"mode": "normal"} if a.normal else {"mode": "stress", "seed_base": a.seed})
        elif action == "calibrate":
            guards = [run_case(g, 30) for g in ("none", "refuse-all", "reference")]
            result = {"guards":guards, "calibrated":guards[0]["oversold"] >= 1 and guards[1]["normal_ok"] == 0 and guards[2]["pass"] == 30 and all(g["errors"] == 0 and g["invalid"] == 0 for g in guards), "scenario_changed":False, "variations_tried":[{"transport":"http", "instances":2, "locking":"redis", "timing":"warmed keep-alive socket per instance; second cart dispatched 0, 5 or 20 ms after the first by run number"}, {"sequential":"cart A completes, then cart B, on a separate kit product"}, {"admin":"draft-order conversion (product D) and order edit (product E) after a 5-unit store order, sequential, admin API"}, {"resale":"product R: 10-unit order canceled via admin API then resold (must place); resale order's reservation deleted via admin API, then another 10 units (must be refused)"}, {"stress":"default traffic: seeded random instance per request group, random pair order and 0-50 ms gaps, normal orders released together, W crowd (6 x 4 units = stock, all must be placed) and up to 10 Y bursts of 2-4 conflicting carts released within 5 ms, canceled between bursts; seed per run = (base 1 x 1000003 + run) mod 2^31"}], "traffic": DEFAULT_TRAFFIC}
            (RESULTS / "calibration-summary.json").write_text(json.dumps(result, indent=2) + "\n")
        else: raise ValueError("Unknown action")
        print(json.dumps(result, indent=2))
        if action == "calibrate" and not result["calibrated"]:
            sys.exit(1)
if __name__ == "__main__": main()
