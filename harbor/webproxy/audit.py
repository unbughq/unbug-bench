"""Persist sanitized request metadata only; never save mitmproxy flows."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

SECRET_SEGMENT = re.compile(r"(?i)^(?:sk-|gh[pousr]_|github_pat_|eyJ)|^[A-Za-z0-9_+=.-]{48,}$")
MODEL_HOSTS = ("api.openai.com", "auth.openai.com", "chatgpt.com", "ab.chatgpt.com",
               "api.anthropic.com", "claude.ai", "platform.claude.com")


def blocked_host(host):
    host = host.lower().rstrip(".")
    return host == "boat.dev" or host.endswith(".boat.dev")


def model_host(host):
    # OpenAI's documented upload/download hosts are region-specific subdomains.
    # Match only DNS labels under this suffix, never a bare string substring.
    return host in MODEL_HOSTS or bool(re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+oaiusercontent\.com", host))


class TlsGate:
    def tls_start_client(self, data):
        if data.context.client.error == "webproxy authority mismatch":
            # Registered after built-in tlsconfig, so it cannot replace this None.
            # mitmproxy closes the connection if no TLS context was provided.
            data.ssl_conn = None


def sanitized_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    authority = f"[{host}]" if ":" in host else host
    if parsed.port and (parsed.scheme, parsed.port) not in (("http", 80), ("https", 443)):
        authority += f":{parsed.port}"
    path = "/".join("[redacted]" if SECRET_SEGMENT.search(unquote(s)) else s for s in parsed.path.split("/"))
    return urlunsplit((parsed.scheme, authority, path, "", "")), host


class Audit:
    def running(self):
        from mitmproxy import ctx
        self.connects = {}
        ctx.master.addons.add(TlsGate())
        self.log = open(os.environ.get("WEB_LOG", "/log/web.jsonl"), "a", buffering=1)
        ca = Path(ctx.options.confdir) / "mitmproxy-ca-cert.pem"
        Path("/ca-public/mitmproxy-ca-cert.crt").write_bytes(ca.read_bytes())

    def record(self, method, url, visibility):
        try:
            clean, host = sanitized_url(url)
            self.log.write(json.dumps({"schema": 1, "timestamp": datetime.now(timezone.utc).isoformat(),
                                       "method": method, "url": clean, "domain": host,
                                       "visibility": visibility}, ensure_ascii=True) + "\n")
            self.log.flush()
            os.fsync(self.log.fileno())
        except Exception:
            # Never forward unlogged traffic if logging/storage fails. Do not print the URL.
            os._exit(70)

    def http_connect(self, flow):
        from mitmproxy import http
        if blocked_host(flow.request.host):
            flow.response = http.Response.make(403, b"Relay disabled")
            return
        self.connects[flow.client_conn.id] = (flow.request.host.lower(), flow.request.port)
        self.record("CONNECT", f"https://{flow.request.host}:{flow.request.port}", "tunnel")

    def tls_clienthello(self, data):
        authority = self.connects.get(data.context.client.id)
        sni = (data.client_hello.sni or "").lower()
        # ignore_hosts also matches attacker-controlled SNI/Host and is unsafe here.
        # Decide passthrough only after comparing SNI to the actual CONNECT target.
        if authority and (model_host(authority[0]) or model_host(sni)):
            if authority == (sni, 443) and model_host(sni):
                data.ignore_connection = True
            else:
                data.context.client.error = "webproxy authority mismatch"
                data.ignore_connection = False

    def client_disconnected(self, client):
        self.connects.pop(client.id, None)

    def requestheaders(self, flow):
        from mitmproxy import http
        if blocked_host(flow.request.host):
            flow.response = http.Response.make(403, b"Relay disabled")
            return
        authority = self.connects.get(flow.client_conn.id)
        if authority:
            try:
                header = urlsplit(flow.request.scheme + "://" + (flow.request.host_header or ""))
                header_authority = ((header.hostname or "").lower(), header.port or (443 if flow.request.scheme == "https" else 80))
            except ValueError:
                header_authority = None
            if authority != (flow.request.host.lower(), flow.request.port) or authority != header_authority:
                flow.response = http.Response.make(403, b"CONNECT and request authority must match")
                return
        if model_host(flow.request.host.lower()):
            flow.response = http.Response.make(403, b"Model APIs require HTTPS")
            return
        self.record(flow.request.method, flow.request.url, "request")
        flow.request.stream = True

    def responseheaders(self, flow):
        flow.response.stream = True


addons = [Audit()]
