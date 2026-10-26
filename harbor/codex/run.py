#!/usr/bin/env python3
"""Run only the infrastructure smoke unless --task explicitly selects a practice task."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CLI_VERSION = "0.162.1"
MODEL = "openai/gpt-6.1-sol"
HARBOR_VERSION = "0.24.0"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor", default=shutil.which("harbor") or str(Path.home() / ".local/share/uv/tools/harbor/bin/harbor"))
    parser.add_argument("--auth", type=Path, default=Path.home() / ".codex/auth.json")
    parser.add_argument("--task", type=Path, default=HERE / "smoke")
    parser.add_argument("--jobs-dir", type=Path, default=Path("/tmp/unbug-codex-jobs"))
    parser.add_argument("--job-name", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overlay", type=Path, action="append", default=[])
    args = parser.parse_args()
    if args.jobs_dir.resolve().is_relative_to(HERE.parents[1]):
        parser.error("Keep raw Harbor logs outside the repository")
    auth = json.loads(args.auth.read_text())
    if auth.get("auth_mode") != "chatgpt" or auth.get("OPENAI_API_KEY") or not auth.get("tokens"):
        parser.error("Requires an existing ChatGPT subscription auth.json without an API key")
    if args.auth.resolve().is_relative_to(HERE.parents[1]):
        parser.error("Credentials must be outside the repository")
    version = subprocess.check_output([args.harbor, "--version"], text=True).strip()
    if version != HARBOR_VERSION:
        parser.error(f"Requires Harbor {HARBOR_VERSION}; found {version}")
    # Pass subscription auth by file path; never inline secrets in argv or job config.
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("OPENAI_", "AZURE_OPENAI_", "CODEX_", "LITELLM_")):
            env.pop(key)
    env["CODEX_AUTH_JSON_PATH"] = str(args.auth.resolve())
    command = [args.harbor, "run", "-p", str(args.task.resolve()), "-a", "codex", "-m", MODEL,
               "--ak", f"version={CLI_VERSION}", "--ak", "reasoning_effort=high", "--ak", "web_search=disabled",
               "-n", "1", "-k", "1", "--max-retries", "0", "-o", str(args.jobs_dir.resolve())]
    for overlay in args.overlay:
        command.extend(["--extra-docker-compose", str(overlay.resolve())])
    if args.job_name:
        command.extend(["--job-name", args.job_name])
    if args.dry_run:
        command.append("--dry-run")
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    sys.exit(main())
