"""Local Docker Desktop integration; all networks internal, no real provider calls.

Run: python3 tests/live/harbor/keyswap/test_docker.py
"""
import sys
from pathlib import Path
_TEST_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_TEST_ROOT / "harbor/keyswap"))
sys.path.insert(0, str(_TEST_ROOT / "tests/harbor/keyswap"))
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from test_keyswap import ACCOUNT, REFRESH, SECRET, auth

HERE = (Path(__file__).resolve().parents[4] / 'harbor/keyswap')
IMAGE = "mitmproxy/mitmproxy:12.1.2@sha256:0d7b2a14b4a71a908cd6f31b8f50e29bbc5c8720fe6caa706acf782da558e5c7"


def main():
    spec = importlib.util.spec_from_file_location("audited", HERE.parent / "run-audited.py")
    audited = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audited)
    with tempfile.TemporaryDirectory(prefix="unbug-keyswap-docker-") as tmp:
        root = Path(tmp)
        stage = root / "inputs"
        stage.mkdir()
        shutil.copytree(HERE, stage / "keyswap", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(_TEST_ROOT / "tests/harbor/keyswap/test_keyswap.py", stage / "keyswap/test_keyswap.py")
        secrets = root / "secrets"
        secrets.mkdir(mode=0o700)
        (secrets / "claude").write_text(SECRET)
        (secrets / "auth.json").write_text(json.dumps(auth(expired=True)))
        env = dict(os.environ, KEYSWAP_CODEX_AUTH_FILE=str(secrets / "auth.json"),
                   UNBUG_WEBPROXY_DIR=str(HERE.parent / "webproxy"))
        overlay, extra = audited.stage_keyswap(stage, "codex", env)
        assert env["CODEX_AUTH_JSON_PATH"] == str(stage / "keyswap/placeholder-auth.json")
        assert SECRET not in (stage / "keyswap/placeholder-auth.json").read_text()
        config = json.loads(overlay.read_text())
        relay = config["services"]["keyswap"]
        relay["environment"].update(KEYSWAP_CLAUDE_TOKEN_FILE="/run/secrets/claude-token", SSL_CERT_FILE="/ca/cert.pem")
        relay["volumes"] += [f"{secrets / 'claude'}:/run/secrets/claude-token:ro", "fixture-ca:/ca:ro"]
        relay["depends_on"] = {"fixture": {"condition": "service_healthy"}}
        overlay.write_text(json.dumps(config))
        base = root / "base.yaml"
        base.write_text(json.dumps({"services": {
            "main": {"image": IMAGE, "entrypoint": ["python"], "command": ["-c", "import time; time.sleep(600)"]},
            "fixture": {"image": IMAGE, "entrypoint": ["python", "/fixture/test_keyswap.py", "--fake-https"],
                "volumes": [f"{stage / 'keyswap'}:/fixture:ro", "fixture-ca:/ca"],
                "networks": {"web-egress": {"aliases": ["api.anthropic.com", "chatgpt.com", "auth.openai.com"]}},
                "healthcheck": {"test": ["CMD", "python", "-c", "import pathlib,socket; assert pathlib.Path('/ca/cert.pem').exists(); socket.create_connection(('127.0.0.1',443),2).close()"],
                                "interval": "1s", "timeout": "3s", "retries": 30}}},
            "networks": {"web-egress": {"internal": True}}, "volumes": {"fixture-ca": {}}}))
        final = root / "final.yaml"
        final.write_text(json.dumps({"services": {"main": {"command": ["-c", "import time; time.sleep(600)"]}}}))
        compose = ["docker", "compose", "-p", "unbug-keyswap-test-" + uuid.uuid4().hex[:8],
                   "-f", str(base), "-f", str(HERE.parent / "webproxy/docker-compose.webproxy.yaml"),
                   "-f", str(overlay), "-f", str(final)]

        def dc(*args, check=True):
            result = subprocess.run(["rtk", "proxy", *compose, *args], env=env, text=True, capture_output=True)
            if check and result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            return result.stdout

        try:
            dc("up", "-d", "--wait")
            output = dc("exec", "-T", "main", "python", "-c", '''
import http.client, pathlib
assert not pathlib.Path('/run/secrets/auth.json').exists()
assert not pathlib.Path('/run/secrets/claude-token').exists()
assert not pathlib.Path('/srv/keyswap').exists()
for path in ('/anthropic/v1/messages', '/chatgpt/backend-api/codex/responses'):
 c=http.client.HTTPConnection('keyswap',8090,timeout=10)
 c.request('POST',path,b'{}',{'Authorization':'Bearer keyswap-placeholder','X-Api-Key':'keyswap-placeholder','ChatGPT-Account-Id':'keyswap-placeholder'})
 r=c.getresponse(); assert r.status==200, r.status
 assert r.read()==b'data: first\\n\\ndata: last\\n\\n'
 c.close()
# CONNECT and plain HTTP boat.dev are rejected before DNS/upstream connection.
for method,path in (('CONNECT','boat.dev:443'),('GET','http://boat.dev/')):
 c=http.client.HTTPConnection('webproxy',8080,timeout=5)
 c.request(method,path); r=c.getresponse(); assert r.status==403,r.status
 r.read();c.close()
print('PASS contestant: Claude + Codex SSE through keyswap; no secret mounts; boat blocked')
''')
            raw = dc("exec", "-T", "webproxy", "cat", "/log/web.jsonl")
            rows = list(map(json.loads, raw.splitlines()))
            assert {r["url"] for r in rows} >= {"https://api.anthropic.com/v1/messages",
                "https://chatgpt.com/backend-api/codex/responses", "https://auth.openai.com/oauth/token"}
            logs = dc("logs")
            assert all(marker not in raw + logs + output for marker in (SECRET, REFRESH, ACCOUNT))
            updated = json.loads((secrets / "auth.json").read_text())
            assert updated["tokens"]["refresh_token"] == "rotated-" + REFRESH
            # Read-only bind failed to persist rotation would fail the Codex request above.
            print(output.strip())
            print("PASS trusted TLS to fake upstream; refresh persisted on host; shared audit metadata; no credentials in logs")
        finally:
            dc("down", "--volumes", "--remove-orphans", check=False)


if __name__ == "__main__":
    main()
