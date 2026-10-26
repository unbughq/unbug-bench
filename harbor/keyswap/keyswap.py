"""Fixed-destination subscription relay. No credentials, headers or bodies in logs."""
import base64
from datetime import datetime, timezone
import fcntl
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

PLACEHOLDER = "keyswap-placeholder"
OAUTH_BETA = "oauth-2025-04-20"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ROUTES = {
    ("POST", "/anthropic/v1/messages"): ("api.anthropic.com", "/v1/messages"),
    ("POST", "/anthropic/v1/messages/count_tokens"): ("api.anthropic.com", "/v1/messages/count_tokens"),
    ("GET", "/chatgpt/backend-api/codex/models"): ("chatgpt.com", "/backend-api/codex/models"),
    ("POST", "/chatgpt/backend-api/codex/responses"): ("chatgpt.com", "/backend-api/codex/responses"),
    ("POST", "/chatgpt/backend-api/codex/responses/compact"): ("chatgpt.com", "/backend-api/codex/responses/compact"),
}
REQUEST_HEADERS = {
    "content-type", "accept", "user-agent", "anthropic-version", "anthropic-beta",
    "anthropic-dangerous-direct-browser-access", "x-app", "originator", "version",
    "openai-beta", "session_id", "conversation_id", "x-client-request-id",
    "x-codex-turn-state", "x-codex-turn-metadata", "x-codex-beta-features",
}
RESPONSE_HEADERS = {
    "content-type", "content-encoding", "cache-control", "request-id", "x-request-id",
    "retry-after", "x-codex-turn-state",
}


def route(method, target):
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.fragment or not target.startswith("/"):
        raise ValueError("route rejected")
    host, path = ROUTES[(method, parsed.path)]
    return host, path + ("?" + parsed.query if parsed.query else "")


def swapped_headers(incoming, host, token, account=None):
    headers = {k.lower(): v for k, v in incoming.items() if k.lower() in REQUEST_HEADERS}
    headers.update({"authorization": "Bearer " + token, "accept-encoding": "identity"})
    if host == "api.anthropic.com":
        beta = [b.strip() for b in headers.get("anthropic-beta", "").split(",") if b.strip()]
        if OAUTH_BETA not in beta:
            beta.append(OAUTH_BETA)
        headers["anthropic-beta"] = ",".join(beta)
    elif host == "chatgpt.com":
        headers["chatgpt-account-id"] = account
    else:
        raise ValueError("upstream rejected")
    return headers


def jwt_claims(token):
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def placeholder_auth():
    # 0.162.1 ChatGPT mode requires HTTPS workspace discovery even for custom
    # providers. API transport mode avoids it; ONLY the relay authenticates upstream
    # with the subscription. This dummy key is never sent to an OpenAI API endpoint.
    return {"auth_mode": "apikey", "OPENAI_API_KEY": PLACEHOLDER}


class Relay(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, claude_file=None, codex_file=None, log_file="/log/web.jsonl"):
        super().__init__(address, Handler)
        self.claude_file, self.codex_file = claude_file, codex_file
        self.log_file = log_file
        self.auth_lock, self.log_lock = threading.Lock(), threading.Lock()
        try: open(os.path.join(os.path.dirname(str(log_file)), "claude-meter.jsonl"), "a").close()  # artifact exists even with no calls
        except OSError: pass

    def handle_error(self, request, client_address):
        # Base server prints tracebacks (potentially including upstream auth errors).
        pass

    def connect(self, host):
        # No URL/config/environment-controlled destination; HTTPS verifies the peer.
        if host not in ("api.anthropic.com", "chatgpt.com", "auth.openai.com"):
            raise ValueError("upstream rejected")
        return http.client.HTTPSConnection(host, timeout=300)

    def record(self, method, host, path):
        # Only fixed paths, never caller-controlled URLs, queries, headers or bodies.
        row = {"schema": 1, "timestamp": datetime.now(timezone.utc).isoformat(),
               "method": method, "url": "https://" + host + path.split("?", 1)[0],
               "domain": host, "visibility": "request"}
        with self.log_lock, open(self.log_file, "a") as log:
            log.write(json.dumps(row) + "\n")
            log.flush()
            os.fsync(log.fileno())

    def meter(self, response):
        """Claude's subscription usage meters (5-hour and weekly utilization, 0.01 steps) next to the
        audit log, so every run records how much of the window its work used. No secrets in them."""
        row = {"timestamp": datetime.now(timezone.utc).isoformat(), "http_status": response.status, "status": response.status,
               **({"retry-after": response.getheader("retry-after")} if response.getheader("retry-after") else {}),
               **{k.lower()[len("anthropic-ratelimit-unified-"):]: v for k, v in response.getheaders()
                  if k.lower().startswith("anthropic-ratelimit-unified-")}}
        with self.log_lock, open(os.path.join(os.path.dirname(self.log_file), "claude-meter.jsonl"), "a") as log:
            log.write(json.dumps(row) + "\n")

    def credential(self, host, rejected=None):
        if host == "api.anthropic.com":
            token = Path(self.claude_file).read_text().strip()
            if not token:
                raise ValueError("missing credential")
            return token, None
        if host != "chatgpt.com":
            raise ValueError("upstream rejected")
        # Serialize threads and separate sidecars sharing the *same inode* on the VM.
        # Keep this a dedicated relay-owned auth file; no other login process may replace it.
        with self.auth_lock, open(self.codex_file, "r+") as source:
            fcntl.flock(source, fcntl.LOCK_EX)
            auth = json.load(source)
            if auth.get("auth_mode") not in (None, "chatgpt") or auth.get("OPENAI_API_KEY"):
                raise ValueError("ChatGPT subscription required")
            tokens = auth["tokens"]
            old = tokens["access_token"]
            expires = jwt_claims(old).get("exp", 0)
            if expires <= time.time() + 60 or rejected == old:
                connection = self.connect("auth.openai.com")
                try:
                    self.record("POST", "auth.openai.com", "/oauth/token")
                    connection.request("POST", "/oauth/token", json.dumps({
                        "client_id": CLIENT_ID, "grant_type": "refresh_token",
                        "refresh_token": tokens["refresh_token"]}), {"Content-Type": "application/json"})
                    response = connection.getresponse()
                    if response.status != 200:
                        raise ValueError("refresh failed")
                    fresh = json.loads(response.read(1024 * 1024))
                    tokens["access_token"] = fresh["access_token"]
                    for key in ("refresh_token", "id_token"):
                        if fresh.get(key):
                            tokens[key] = fresh[key]
                    auth["last_refresh"] = datetime.now(timezone.utc).isoformat()
                    # A single-file bind mount cannot be atomically renamed. Persist rotation
                    # before using it; a crash during write requires restoring/relogging in.
                    encoded = json.dumps(auth) + "\n"
                    source.seek(0)
                    source.write(encoded)
                    source.truncate()
                    source.flush()
                    os.fsync(source.fileno())
                finally:
                    connection.close()
            token, account = tokens["access_token"], tokens["account_id"]
            if not token or not account:
                raise ValueError("missing credential")
            return token, account


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def error(self, status):
        # Never relay error bodies/headers, redirects or exception strings: they can echo auth.
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_GET(self):
        if self.path == "/health":
            self.error(204)
        else:
            self.relay()

    def do_POST(self):
        self.relay()

    def relay(self):
        self.close_connection = True
        try:
            host, path = route(self.command, self.path)
        except (KeyError, ValueError):
            self.error(403)
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) > 1:
            self.error(400)
            return
        try:
            length = int(lengths[0]) if lengths else 0
            if not 0 <= length <= 32 * 1024 * 1024:
                raise ValueError()
        except ValueError:
            self.error(413)
            return
        self.connection.settimeout(300)
        connection, started = None, False
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("short body")
            token, account = self.server.credential(host)
            for attempt in range(2):
                headers = swapped_headers(self.headers, host, token, account)
                self.server.record(self.command, host, path)
                connection = self.server.connect(host)
                connection.request(self.command, path, body, headers)
                response = connection.getresponse()
                if host == "api.anthropic.com":
                    try: self.server.meter(response)
                    except OSError: pass  # metering never blocks the relay
                if response.status == 401 and host == "chatgpt.com" and attempt == 0:
                    connection.close()
                    token, account = self.server.credential(host, rejected=token)
                    continue
                break
            if not 200 <= response.status < 300:
                status = response.status if response.status >= 400 else 502
                if response.status in (401, 403) or response.status < 400:
                    # Auth failures and redirects are the relay's business; never echo them.
                    self.error(502 if host == "chatgpt.com" and status == 401 else status)
                    return
                # Other errors carry what the agent acts on (prompt too long, rate limits,
                # retry-after). Scrub the credential anyway in case an upstream echoes it.
                body = response.read(64 * 1024).replace(token.encode(), b"[redacted]")
                self.send_response(status)
                for key, value in response.getheaders():
                    if key.lower() in RESPONSE_HEADERS and key.lower() != "content-encoding":
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() in RESPONSE_HEADERS or key.lower().startswith(("x-codex-", "anthropic-ratelimit-")):
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            started = True
            # read1 returns available data; read(n) would hold short SSE events until n bytes.
            while chunk := response.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        except Exception:
            if not started:
                self.error(502)
        finally:
            if connection:
                connection.close()


if __name__ == "__main__":
    Relay(("0.0.0.0", 8090), os.environ.get("KEYSWAP_CLAUDE_TOKEN_FILE"),
          os.environ.get("KEYSWAP_CODEX_AUTH_FILE")).serve_forever()
