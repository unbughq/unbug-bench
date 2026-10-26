#!/usr/bin/env python3
"""Real Harbor 0.24 two-step/two-trial persistence + forgery probe; no models or shop traffic."""
import json, pathlib, subprocess, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[4]
HARBOR = pathlib.Path.home() / ".local/share/uv/tools/harbor/bin/harbor"
root = pathlib.Path(tempfile.mkdtemp(prefix="unbug-v2-persistence-"))
task = root / "task"
def write(name, text):
    path = task / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
(task / "environment").mkdir(parents=True)
write("environment/docker-compose.yaml", '''services:
  main:
    volumes:
      - type: bind
        source: ${HOST_VERIFIER_LOGS_PATH:?}/../deployment-state
        target: /deployments
        read_only: true
        bind:
          create_host_path: true
''')
write("instruction.md", "Infrastructure probe only.\n")
write("task.toml", '''schema_version = "1.4"
artifacts = ["/app/guard", "/app/claims.json"]
[environment]
docker_image = "unbug-bench-box:v2-dev"
cpus = 1
memory_mb = 256
[verifier.environment]
docker_image = "unbug-v2-persistence:dev"
cpus = 1
memory_mb = 256
[[steps]]
name = "block"
[steps.verifier.env]
PROBE_STEP = "block"
[[steps]]
name = "later"
[steps.verifier.env]
PROBE_STEP = "later"
''')
write("tests/docker-compose.yaml", '''services:
  main:
    volumes:
      - type: bind
        source: ${HOST_VERIFIER_LOGS_PATH:?}/../pending-state
        target: /judge-state
        bind:
          create_host_path: true
''')
# A different sibling directory carries the public receipt; only the judge writes it.
with (task / "tests/docker-compose.yaml").open("a") as compose:
    compose.write("      - type: bind\n        source: ${HOST_VERIFIER_LOGS_PATH:?}/../deployment-state\n        target: /deployment-out\n        bind:\n          create_host_path: true\n")
write("tests/test.sh", '''#!/bin/bash
set -eu
python3 - <<'CHECK'
import importlib.machinery, importlib.util, json, os, pathlib, socket, sys
sys.path.insert(0, "/bench/bin")
loader = importlib.machinery.SourceFileLoader("checkpoint", "/bench/bin/checkpoint")
spec = importlib.util.spec_from_loader(loader.name, loader)
checkpoint = importlib.util.module_from_spec(spec); loader.exec_module(checkpoint)
state = pathlib.Path("/judge-state/decisions.json")
step = os.environ["PROBE_STEP"]
key = {"owner_decision": "block"}
pending = {"id": "P1", "delivery": "pending", "key": key}
report = json.loads(pathlib.Path("/app/claims.json").read_text())
history = json.loads(state.read_text()) if state.exists() else {}
assert bool(history) == (step == "later"), history
scenarios = [pending] + ([{"id": "S0"}] if step == "later" else [])
active, decisions = checkpoint.select_scenarios(scenarios, report, history)
assert not any(s["id"] == "P1" for s in active), (active, decisions)
assert decisions["P1"] == {"decision": "block", "missing": False, "landed": False}, decisions
state.write_text(json.dumps(decisions))
pathlib.Path("/deployment-out/decisions.json").write_text(json.dumps({"P1": {"landed": False}}))
pathlib.Path("/logs/verifier/reward.json").write_text(json.dumps({"reward": 1}))
pathlib.Path("/logs/verifier/probe.json").write_text(json.dumps({"step": step, "hostname": socket.gethostname(), "decisions": decisions}))
CHECK
''')
for step in ("block", "later"):
    write(f"steps/{step}/instruction.md", "Probe the isolation boundary.\n")
    decision = "block" if step == "block" else "approve"
    receipt_check = "" if step == "block" else """python3 - <<'RECEIPT'
import errno, json, pathlib
p = pathlib.Path('/deployments/decisions.json')
assert json.loads(p.read_text()) == {'P1': {'landed': False}}
try: p.write_text('{"P1":{"landed":true}}')
except OSError as error: assert error.errno == errno.EROFS, error
else: raise AssertionError('public deployment receipt must be read-only')
RECEIPT
"""
    write(f"steps/{step}/solution/solve.sh", f'''#!/bin/bash
set -eu
# Neither the ledger mount nor the host parent of the verifier bind is exposed.
test ! -e /judge-state
{receipt_check}
mkdir -p /app/guard /logs/pending-state
echo '{{"P1":{{"landed":true,"decision":"approve"}}}}' > /app/guard/decisions.json
cp /app/guard/decisions.json /logs/pending-state/decisions.json
echo '{{"pending_decision":"{decision}"}}' > /app/claims.json
''')
write("tests/Dockerfile", "FROM unbug-bench-judge:v2-dev\nCOPY test.sh /tests/test.sh\n")
subprocess.run(["docker", "build", "-t", "unbug-v2-persistence:dev", str(task / "tests")], check=True, stdout=subprocess.DEVNULL)
subprocess.run([str(HARBOR), "run", "-p", str(task), "-a", "oracle", "-o", str(root / "jobs"), "--job-name", "fixes-persistence", "-k", "2", "-n", "1", "--max-retries", "0"], check=True)
probes = [json.loads(p.read_text()) for p in (root / "jobs").rglob("probe.json")]
assert len(probes) == 4 and len({p["hostname"] for p in probes}) == 4, probes
assert all(json.loads(p.read_text())["reward"] == 1 for p in (root / "jobs").rglob("reward.json"))
print(json.dumps({"passed": True, "fresh_verifiers": 4, "independent_trials": 2, "evidence": str(root)}))
