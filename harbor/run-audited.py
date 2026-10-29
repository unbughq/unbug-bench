#!/usr/bin/env python3
"""Stage immutable sidecars and run a practice task with question and web artifacts.

No model is selected implicitly. Use --agent oracle for an infrastructure check.
  python3 harbor/run-audited.py --agent oracle --job-name audited-dev --dry-run
Extra Harbor arguments follow --. Claude practice runs still require authorization.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import shlex

HERE = Path(__file__).resolve().parent


def stage_keyswap(stage, agent, env):
    """Only the relay gets host secrets; Harbor uploads a separate dummy auth.json."""
    import sys
    sys.path.insert(0, str(HERE / "keyswap"))
    from keyswap import PLACEHOLDER, placeholder_auth

    kind = "CODEX_AUTH" if agent == "codex" else "CLAUDE_TOKEN"
    key = f"KEYSWAP_{kind}_FILE"
    source = Path(env.get(key, "")).expanduser()
    if not env.get(key) or not source.is_file():
        raise ValueError(f"Set {key} to a host credential file")
    source = source.resolve()
    if source.is_relative_to(stage) or source.is_relative_to(HERE.parent):
        raise ValueError("Keep real credentials outside staged inputs and the repository")
    target = "/run/secrets/" + ("auth.json" if agent == "codex" else "claude-token")
    service = {
        "image": "mitmproxy/mitmproxy:12.1.2@sha256:0d7b2a14b4a71a908cd6f31b8f50e29bbc5c8720fe6caa706acf782da558e5c7",
        "entrypoint": ["python", "/srv/keyswap/keyswap.py"], "user": "0:0",
        "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
        "read_only": True, "networks": ["web-isolated", "web-egress"],
        "environment": {key: target},
        "volumes": [f"{stage / 'keyswap'}:/srv/keyswap:ro", "webproxy-log:/log",
                    {"type": "bind", "source": str(source), "target": target,
                     "read_only": agent != "codex", "bind": {"create_host_path": False}}],
        "healthcheck": {"test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=2)"],
                        "interval": "2s", "timeout": "5s", "retries": 30},
    }
    main_env = {"NO_PROXY": "localhost,127.0.0.1,::1,responder,keyswap",
                "no_proxy": "localhost,127.0.0.1,::1,responder,keyswap"}
    if agent == "codex":
        dummy = stage / "keyswap/placeholder-auth.json"
        dummy.write_text(json.dumps(placeholder_auth()) + "\n")
        env["CODEX_AUTH_JSON_PATH"] = str(dummy)
        extra = ["--ak", f"config={stage / 'keyswap/codex.toml'}"]
    else:
        main_env.update({"CLAUDE_CODE_OAUTH_TOKEN": PLACEHOLDER, "CLAUDE_FORCE_OAUTH": "1",
                         "ANTHROPIC_BASE_URL": "http://keyswap:8090/anthropic", "ANTHROPIC_API_KEY": ""})
        env.update(main_env)
        # Harbor scrubs the value of every --ae key that looks secret (*OAUTH*, *TOKEN*, *KEY*...)
        # from all trial output; CLAUDE_FORCE_OAUTH=1 erased every "1", rewards included. It stays
        # in the container env above only.
        extra = [part for key in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")
                 for part in ("--ae", f"{key}={main_env[key]}")]
    overlay = stage / "keyswap.yaml"
    overlay.write_text(json.dumps({"services": {"keyswap": service, "main": {
        "environment": main_env, "depends_on": {"keyswap": {"condition": "service_healthy"}}}}}, indent=2) + "\n")
    return overlay, extra


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--task", type=Path, default=HERE / "medusa-oversell")
    parser.add_argument("--jobs-dir", type=Path, default=Path("/tmp/unbug-audited-jobs"))
    parser.add_argument("--harbor", default=shutil.which("harbor") or str(Path.home() / ".local/share/uv/tools/harbor/bin/harbor"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--answerer", choices=("canned", "model", "reviewer"), default="canned")
    parser.add_argument("--fact-sheet", type=Path, help="owner fact sheet; staged into the responder only, never main")
    parser.add_argument("extra", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.jobs_dir.resolve().is_relative_to(HERE.parent):
        parser.error("Raw trial logs must stay outside the repository")
    if subprocess.check_output([args.harbor, "--version"], text=True).strip() != "0.24.0":
        parser.error("Requires Harbor 0.24.0")
    stage = Path(tempfile.mkdtemp(prefix="unbug-audited-inputs-"))
    for source, name in ((args.task, "task"), (HERE / "webproxy", "webproxy"), (HERE / "responder", "responder"), (HERE / "keyswap", "keyswap")):
        shutil.copytree(source, stage / name, ignore=shutil.ignore_patterns("__pycache__"))
    # Task-owned owner answers stay in the responder sidecar, outside the agent image.
    owner = stage / "task/responder"
    if (owner / "canned.json").is_file():
        shutil.copy(owner / "canned.json", stage / "responder/canned.json")
    if not args.fact_sheet and (owner / "fact-sheet.md").is_file():
        args.fact_sheet = owner / "fact-sheet.md"
    task = stage / "task/task.toml"
    text = task.read_text()
    # Artifact tables are legal alongside path strings in Harbor schema 1.4.
    start = text.index("artifacts = [")
    end = text.index("]", start) + 1
    body = text[start + len("artifacts = ["):end - 1].strip()
    separator = "" if not body or body.endswith(",") else ","
    text = text[:end - 1] + separator + '''
  {source = "/logs/responder/questions.jsonl", destination = "responder/questions.jsonl", service = "responder"},
  {source = "/log/web.jsonl", destination = "web/web.jsonl", service = "webproxy"},
]''' + text[end:]
    task.write_text(text)
    for instruction in (stage / "task/steps").glob("*/instruction.md"):
        if (instruction.parent / 'window.json').is_file():
            if instruction.read_text().strip():
                parser.error('An unannounced step must have an empty instruction')
            continue
        step = instruction.parent.name
        instruction.write_text(instruction.read_text() + f'\nOwner questions: run `ASK_STEP={step} ask-human "your question"`. Use shell/browser web retrieval through the supplied audit proxy; hosted web-search/fetch tools are disabled.\n')
    if args.fact_sheet and args.answerer != "reviewer":
        shutil.copy(args.fact_sheet, stage / "responder/fact-sheet.txt")
    joint = stage / "joint.yaml"
    joint.write_text('''services:
  responder:
    networks: [web-isolated]
    environment:
      HTTP_PROXY: http://webproxy:8080
      HTTPS_PROXY: http://webproxy:8080
      NO_PROXY: localhost,127.0.0.1,::1
      no_proxy: localhost,127.0.0.1,::1
      SSL_CERT_FILE: /webproxy-ca/mitmproxy-ca-cert.crt
    volumes:
      - webproxy-public-ca:/webproxy-ca:ro
  main:
    environment:
      RESPONDER_URL: http://responder:8080/ask
      NO_PROXY: localhost,127.0.0.1,::1,responder
      no_proxy: localhost,127.0.0.1,::1,responder
''')
    if args.answerer == "reviewer":
        joint.write_text(joint.read_text().replace("networks: [web-isolated]", "networks: [web-isolated, web-egress]"))
        network, address = os.environ.get("OWNER_RELAY_NETWORK", ""), os.environ.get("OWNER_RELAY_ADDRESS", "")
        if not re.fullmatch(r"owner-relay-[a-f0-9]{16}", network):
            parser.error("--answerer reviewer requires the private owner relay network")
        import ipaddress
        try:
            address = str(ipaddress.IPv4Address(address))
        except ValueError:
            parser.error("invalid private owner relay address")
        joint.write_text(joint.read_text().replace("networks: [web-isolated, web-egress]", "networks:\n      web-isolated: {}\n      web-egress: {}\n      owner-relay:\n        ipv4_address: " + address)
            + "\nnetworks:\n  owner-relay:\n    external: true\n    name: " + network + "\n")
    env = dict(os.environ, UNBUG_WEBPROXY_DIR=str(stage / "webproxy"), RESPONDER_DIR=str(stage / "responder"), ANSWERER=args.answerer)
    # Never let inherited provider credentials enter Harbor's model resolver/extra env.
    for key in list(env):
        if key.startswith(("ANTHROPIC_", "CLAUDE_", "OPENAI_", "AZURE_OPENAI_", "CODEX_", "LITELLM_", "OPENCODE_", "OPENROUTER_")):
            del env[key]
    keyswap_overlay, credentials = (None, [])
    if args.agent not in ("oracle", "nop"):
        try:
            keyswap_overlay, credentials = stage_keyswap(stage, args.agent, env)
        except ValueError as error:
            parser.error(str(error))
    if args.fact_sheet:
        env["FACT_SHEET"] = "/srv/responder/fact-sheet.txt"  # path inside the responder container
    if args.answerer == "reviewer":
        if not env.get("OWNER_URL"):
            parser.error("--answerer reviewer requires the private owner endpoint")
        env["ANSWER_API_KEY"] = ""
    elif args.answerer == "canned":
        env["ANSWER_API_KEY"] = ""
    else:  # default owner: DeepSeek on OpenRouter (pay per token; Go's weekly cap stalls runs)
        env.setdefault("ANSWER_BASE_URL", "https://openrouter.ai/api/v1")
        env.setdefault("ANSWER_MODEL", "deepseek/deepseek-v4-pro")
        if not env.get("ANSWER_API_KEY"):  # key file on the host; reaches only the responder sidecar
            key_file = os.environ.get("ANSWER_API_KEY_FILE", "")
            env["ANSWER_API_KEY"] = Path(key_file).read_text().strip() if key_file else ""
        if not env["ANSWER_API_KEY"]:
            parser.error("--answerer model needs ANSWER_API_KEY_FILE (or ANSWER_API_KEY)")
    command = [args.harbor, "run", "-p", str(stage / "task"), "-a", args.agent,
               "--extra-docker-compose", str(stage / "webproxy/docker-compose.webproxy.yaml"),
               "--extra-docker-compose", str(stage / "responder/docker-compose.responder.yaml"),
               "--extra-docker-compose", str(joint), "--job-name", args.job_name,
               "-o", str(args.jobs_dir.resolve()), "--max-retries", "0"]
    if list((stage / 'task/steps').glob('*/window.json')):
        # Freeze host-side judge code/data too: unlike ordinary verifiers, live
        # windows do not get their implementation from the immutable judge image.
        runtime = stage / 'runtime'
        for name in ('bench.py', 'bench_judging.py', 'claims.py', 'checkpoint_evidence.py', 'run_validity.py', 'exposure.py', 'live_shop.py', 'silent_window.py', 'live_traffic.py', 'shoppers'):
            target = runtime / 'bin' / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(HERE.parent / 'bin' / name, target)
        (runtime / 'factory').mkdir()
        shutil.copy(HERE.parent / 'factory/case_permissions.py', runtime / 'factory/case_permissions.py')
        shutil.copytree(HERE / 'phase2', runtime / 'harbor/phase2', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(HERE.parent / 'cases/medusa-oversell/traffic', runtime / 'cases/medusa-oversell/traffic')
        for name in ('cases/medusa-oversell/checker/check.sql', 'projects/medusa/seed-ids.json'):
            target = runtime / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(HERE.parent / name, target)
        image = 'unbug-phase2-reader:dev'
        needs_reader = any(json.loads(p.read_text()).get('probe_kind') == 'medusa'
                           for p in (stage / 'task/steps').glob('*/window.json'))
        if needs_reader and not args.dry_run and '--print-config' not in args.extra:
            built = subprocess.run(['docker', 'build', '-t', image, str(runtime / 'harbor/phase2')],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if built.returncode: raise RuntimeError('live reader image build failed: ' + built.stdout[-4000:])
            identity = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
            env['UNBUG_PHASE2_READER_IMAGE'] = identity
            (runtime / 'reader-image.json').write_text(json.dumps({'image': image, 'id': identity}) + '\n')
        # Run in this exact Harbor installation, including the Unbug wheel venv.
        executable = Path(shutil.which(args.harbor) or args.harbor).resolve().read_text().splitlines()[0]
        if not executable.startswith('#!'):
            parser.error('phase 2 requires a Python Harbor console entry point')
        command[:1] = [*shlex.split(executable[2:]), str(runtime / 'harbor/phase2/run.py')]
    if args.dry_run:
        command.append("--dry-run")
    command.extend(args.extra[1:] if args.extra[:1] == ["--"] else args.extra)
    if keyswap_overlay:
        command.extend(["--extra-docker-compose", str(keyswap_overlay), *credentials])
        if args.agent != "codex":  # keyswap writes Claude's usage meters beside the web log
            text = task.read_text().replace('{source = "/log/web.jsonl"', '{source = "/log/claude-meter.jsonl", destination = "web/claude-meter.jsonl", service = "webproxy"},\n  {source = "/log/web.jsonl"', 1)
            task.write_text(text)
    if args.agent == "codex":
        command.extend(["--ak", "web_search=disabled"])
    elif args.agent not in ("oracle", "nop"):  # Claude Code and its subclasses (arm B, Unbug)
        command.extend(["--ak", "disable_web_search=true"])
    # Harbor replaces every occurrence of a secret-named --ae value in all trial output; a short
    # one ("1", "true") silently corrupts rewards and logs. Pattern copied from harbor/utils/env.py.
    for flag, pair in zip(command, command[1:]):
        key, _, value = pair.partition("=")
        if flag == "--ae" and value and len(value) < 12 and re.search(r"(?i)(KEY|SECRET|TOKEN(?!S)|PASSWORD|CREDENTIAL|AUTH)", key):
            parser.error(f"--ae {key}: secret-named values under 12 characters corrupt Harbor's output")
    hashes = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(stage.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
    (stage / "inputs.sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(json.dumps({"staged_inputs": str(stage), "agent": args.agent, "dry_run": args.dry_run}), flush=True)
    raise SystemExit(subprocess.call(command, env=env))


if __name__ == "__main__":
    main()
