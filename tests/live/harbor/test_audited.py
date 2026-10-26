"""Real launcher smoke: canned responder + HTTPS audit + main artifact, no model calls.

Run with Python 3.12+: rtk proxy python3.13 tests/live/harbor/test_audited.py
Keeps its source/job evidence under the printed /tmp directory; Harbor removes containers.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = (Path(__file__).resolve().parents[3] / 'harbor')


def launch(*args):
    result = subprocess.run(["rtk", "proxy", sys.executable, str(HERE / "run-audited.py"), *args],
                            env=dict(os.environ, ANSWERER="canned"), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert result.returncode == 0, result.stdout[-6000:]
    return result.stdout


def main():
    root = Path(tempfile.mkdtemp(prefix="unbug-audited-smoke-"))
    # Config-only probes prove appended extra options cannot re-enable hosted tools.
    for agent, key, attempted, expected in (("codex", "web_search", "live", "disabled"),
                                             ("claude-code", "disable_web_search", "false", True)):
        raw = launch("--agent", agent, "--job-name", "config-only", "--",
                     "--ak", key + "=" + attempted, "--print-config")
        config = json.loads(raw.split("\n", 1)[1])
        assert config["agents"][0]["kwargs"][key] == expected
    task = root / "task"
    (task / "environment").mkdir(parents=True)
    (task / "steps/visit/workdir").mkdir(parents=True)
    (task / "instruction.md").write_text("Infrastructure probe only.\n")
    (task / "steps/visit/instruction.md").write_text("No work required.\n")
    (task / "steps/visit/workdir/setup.sh").write_text('''#!/bin/sh
set -eu
mkdir -p /app/audited-probe
ASK_STEP=visit ask-human "What is the shipping policy?" > /app/audited-probe/answer.txt
curl -fsS --max-time 30 'https://example.com/?token=SYNTHETIC_AUDITED_SECRET' -o /dev/null
printf 'setup-completed\\n' > /app/audited-probe/marker.txt
''')
    (task / "environment/docker-compose.yaml").write_text('''services:
  main:
    privileged: true
    command: [start-dockerd]
    volumes: [nested:/var/lib/docker]
    healthcheck:
      test: [CMD, docker, info]
      interval: 2s
      timeout: 5s
      retries: 60
volumes:
  nested: {}
''')
    (task / "task.toml").write_text('''schema_version = "1.4"
artifacts = ["/app/audited-probe"]
[environment]
docker_image = "unbug-bench-box:dev"
cpus = 1
memory_mb = 1024
[[steps]]
name = "visit"
''')
    raw = launch("--agent", "nop", "--job-name", "actual-audited-probe", "--task", str(task),
                 "--jobs-dir", str(root / "jobs"), "--", "--disable-verification")
    (root / "launcher.log").write_text(raw)
    stage = Path(json.loads(raw.splitlines()[0])["staged_inputs"])
    hashes = json.loads((stage / "inputs.sha256.json").read_text())
    assert all(hashlib.sha256((stage / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items())
    assert stage not in task.parents and stage != task
    for file in ("webproxy/audit.py", "responder/responder.py"):
        assert (stage / file).read_bytes() == (HERE / file).read_bytes()
        assert (stage / file).stat().st_ino != (HERE / file).stat().st_ino
    questions = list((root / "jobs").rglob("questions.jsonl"))
    web = list((root / "jobs").rglob("web.jsonl"))
    markers = list((root / "jobs").rglob("marker.txt"))
    assert questions and web and markers
    contacts = [json.loads(line) for line in questions[0].read_text().splitlines()]
    assert len(contacts) == 1 and contacts[0]["step"] == "visit" and contacts[0]["minutes_charged"] == 5
    assert contacts[0]["answer"] == "Orders ship on business days only; no weekend dispatch."
    web_raw = web[0].read_text()
    assert "SYNTHETIC_AUDITED_SECRET" not in web_raw
    assert any(row["url"] == "https://example.com/" and row["method"] == "GET"
               for row in map(json.loads, web_raw.splitlines()))
    assert markers[0].read_text() == "setup-completed\n"
    for result in (root / "jobs").rglob("result.json"):
        assert not json.loads(result.read_text()).get("exception_info")
    print(json.dumps({"passed": True, "evidence": str(root), "staged_inputs": str(stage),
                      "checks": ["hosted tool overrides rejected", "responder health",
                                 "canned question + 5 minutes", "trusted HTTPS + sanitized URL",
                                 "both sidecar artifacts + main directory", "source snapshots unchanged"]}))


if __name__ == "__main__":
    main()
