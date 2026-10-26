"""Prove Harbor 0.24 sidecar artifact collection, with nop and no model calls."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = (Path(__file__).resolve().parents[4] / 'harbor/webproxy')


def main():
    with tempfile.TemporaryDirectory(prefix="unbug-webproxy-harbor-") as directory:
        root = Path(directory)
        task = root / "task"
        (task / "environment").mkdir(parents=True)
        (task / "steps/visit/workdir").mkdir(parents=True)
        (task / "steps/visit/instruction.md").write_text("No work required.\n")
        (task / "steps/visit/workdir/setup.sh").write_text("#!/bin/sh\nset -eu\ncurl -fsS --max-time 30 'https://github.com/medusajs/medusa/issues/17032?token=SYNTHETIC_HARBOR_SECRET' -o /dev/null\n")
        (task / "instruction.md").write_text("No work required.\n")
        (task / "environment/docker-compose.yaml").write_text("services:\n  main:\n    privileged: true\n    volumes: [nested:/var/lib/docker]\n    healthcheck:\n      test: [CMD, docker, info]\n      interval: 2s\n      timeout: 5s\n      retries: 60\nvolumes:\n  nested: {}\n")
        (task / "task.toml").write_text('''schema_version = "1.4"
artifacts = [{source="/log/web.jsonl", destination="web/web.jsonl", service="webproxy"}]
[environment]
docker_image = "unbug-bench-box:dev"
cpus = 1
memory_mb = 1024
[[steps]]
name = "visit"
''')
        result = subprocess.run(["rtk", "proxy", "harbor", "run", "-p", str(task), "-a", "nop",
                                 "--disable-verification", "--extra-docker-compose",
                                 str(HERE / "docker-compose.webproxy.yaml"), "-o", str(root / "jobs")],
                                env=dict(os.environ, UNBUG_WEBPROXY_DIR=str(HERE)),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        logs = list((root / "jobs").rglob("web.jsonl"))
        assert result.returncode == 0 and logs, result.stdout[-4000:]
        raw = logs[0].read_text()
        rows = [json.loads(line) for line in raw.splitlines()]
        assert any(row["url"] == "https://github.com/medusajs/medusa/issues/17032" for row in rows), raw
        assert "SYNTHETIC_HARBOR_SECRET" not in raw
        results = list((root / "jobs").rglob("result.json"))
        assert all(not json.loads(p.read_text()).get("exception_info") for p in results)
        print("PASS Harbor nop setup HTTPS visit collected from webproxy as steps/visit/artifacts/web/web.jsonl")


if __name__ == "__main__":
    main()
