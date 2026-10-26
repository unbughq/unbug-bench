#!/usr/bin/env python3
"""Run the two-session Codex infrastructure probe with frozen sidecar source copies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
HARBOR = HERE.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # Immutable for this run: mitmproxy auto-reloads bind-mounted addon changes.
    snapshot = Path(tempfile.mkdtemp(prefix="unbug-codex-sidecars-"))
    hashes = {}
    for folder, files in {"webproxy": ["audit.py", "start-main.sh", "docker-compose.webproxy.yaml"],
                          "responder": ["responder.py", "canned.json", "docker-compose.responder.yaml"]}.items():
        target = snapshot / folder
        target.mkdir()
        for name in files:
            shutil.copy2(HARBOR / folder / name, target / name)
            hashes[folder + "/" + name] = hashlib.sha256((target / name).read_bytes()).hexdigest()
    (snapshot / "manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(f"Frozen sidecar source: {snapshot}", flush=True)
    env = dict(os.environ, UNBUG_WEBPROXY_DIR=str(snapshot / "webproxy"),
               RESPONDER_DIR=str(snapshot / "responder"), ANSWERER="canned", OPENROUTER_API_KEY="")
    command = [sys.executable, str(HERE / "run.py"), "--task", str(HERE / "combined"),
               "--job-name", args.job_name, "--overlay", str(snapshot / "webproxy/docker-compose.webproxy.yaml"),
               "--overlay", str(snapshot / "responder/docker-compose.responder.yaml"),
               "--overlay", str(HERE / "combined/joint.yaml")]
    if args.dry_run:
        command.append("--dry-run")
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
