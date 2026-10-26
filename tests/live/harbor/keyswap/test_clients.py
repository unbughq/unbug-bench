"""Optional pinned CLI wire probe. Download binaries separately; all networking is disabled.

python3 tests/live/harbor/keyswap/test_clients.py /absolute/linux/codex /absolute/linux/claude
No generated model response is claimed; proves CLI accepts dummy auth and HTTP routing.
"""
import sys
from pathlib import Path
_TEST_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_TEST_ROOT / "harbor/keyswap"))
sys.path.insert(0, str(_TEST_ROOT / "tests/harbor/keyswap"))
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import keyswap


def probe():
    rows, seen = [], threading.Event()

    class Capture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"models":[]}')

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            rows.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
            if self.path.split("?", 1)[0].endswith(("/responses", "/v1/messages")):
                seen.set()
            self.send_response(503)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 8090), Capture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "auth.json").write_text(json.dumps(keyswap.placeholder_auth()))
        config = (_TEST_ROOT / "harbor/keyswap/codex.toml").read_text().replace("keyswap:8090", "127.0.0.1:8090")
        (root / "config.toml").write_text(config)
        for binary, version, command, env, expected in (
            ("/codex", "0.162.1", ["exec", "--skip-git-repo-check", "--model", "gpt-6.1-sol", "Say hello"],
             {"CODEX_HOME": str(root)}, "/chatgpt/backend-api/codex/responses"),
            ("/claude", "2.1.299", ["-p", "Say hello", "--model", "claude-opus-5-5"],
             {"CLAUDE_CONFIG_DIR": str(root / "claude"), "CLAUDE_CODE_OAUTH_TOKEN": keyswap.PLACEHOLDER,
              "ANTHROPIC_BASE_URL": "http://127.0.0.1:8090/anthropic", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
             "/anthropic/v1/messages")):
            version_output = subprocess.check_output([binary, "--version"], text=True)
            assert version in version_output, version_output
            rows.clear()
            seen.clear()
            with tempfile.TemporaryFile() as output:
                process = subprocess.Popen([binary, *command], env=dict(os.environ, HOME=str(root), **env), stdout=output, stderr=output)
                try:
                    found = seen.wait(25)
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                if not found:
                    output.seek(0)
                    raise AssertionError(output.read().decode()[-3000:])
            path, headers, body = next(row for row in rows if row[0].split("?", 1)[0] == expected)
            assert path.split("?", 1)[0] == expected, path
            assert headers["authorization"].startswith("Bearer ")
            assert not headers.get("x-api-key")
            if binary == "/claude":
                assert headers["authorization"] == "Bearer " + keyswap.PLACEHOLDER
                assert keyswap.OAUTH_BETA in headers["anthropic-beta"]
            else:
                assert headers["authorization"] == "Bearer " + keyswap.PLACEHOLDER
                assert not headers.get("chatgpt-account-id")  # relay supplies the real account
                request = json.loads(body)
                assert request["store"] is False and request["stream"] is True
                assert request["input"]
            print(f"PASS {binary[1:]} {version}: dummy auth + HTTP {expected}", flush=True)
    server.shutdown()


if __name__ == "__main__":
    if sys.argv[1:] == ["--inside"]:
        probe()
    else:
        codex, claude = (str(Path(p).resolve()) for p in sys.argv[1:])
        subprocess.run(["rtk", "proxy", "docker", "run", "--rm", "--network", "none",
                        "-v", f"{_TEST_ROOT}:/repo:ro", "-v", f"{codex}:/codex:ro",
                        "-v", f"{claude}:/claude:ro", "--entrypoint", "python3", "unbug-bench-box:dev",
                        "/repo/tests/live/harbor/keyswap/test_clients.py", "--inside"], check=True)
