"""Stdlib checks with fake upstreams only: python3 -m unittest discover -s tests/harbor/keyswap -v."""
import sys
from pathlib import Path
# The Docker fixture stages this test beside the runtime module.
if (Path(__file__).parent / "keyswap.py").is_file():
    sys.path.insert(0, str(Path(__file__).parent))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "harbor/keyswap"))
import contextlib
import base64
from datetime import datetime, timedelta, timezone
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import unittest

import keyswap

SECRET = "SYNTHETIC_REAL_SECRET_NEVER_IN_CONTESTANT"
ACCOUNT = "SYNTHETIC_REAL_ACCOUNT"
REFRESH = "SYNTHETIC_REFRESH_SECRET"


def auth(expired=False):
    claims = {"exp": 1 if expired else 4102444800, "https://api.openai.com/auth": {
        "chatgpt_account_id": ACCOUNT, "chatgpt_plan_type": "plus"}}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    token = "eyJhbGciOiJub25lIn0." + payload + "." + SECRET
    return {"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "tokens": {
        "id_token": token, "access_token": token, "refresh_token": REFRESH, "account_id": ACCOUNT}}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.do_POST()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.seen.append((self.path, dict(self.headers), body))
        if self.path == "/oauth/token":
            assert json.loads(body) == {"client_id": keyswap.CLIENT_ID,
                                        "grant_type": "refresh_token", "refresh_token": REFRESH}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"access_token": auth()["tokens"]["access_token"],
                                        "refresh_token": "rotated-" + REFRESH}).encode())
            return
        if self.server.reject_once:
            self.server.reject_once = False
            self.send_response(401)
            self.end_headers()
            return
        status = json.loads(body or b"{}").get("status", 200)
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Authorization", "Bearer " + SECRET)
        self.send_header("Location", "https://evil.test/" + SECRET)
        self.end_headers()
        if status != 200:
            self.wfile.write(("Authorization: Bearer " + SECRET).encode())
            return
        self.wfile.write(b"data: first\n\n")
        self.wfile.flush()
        self.server.release.wait(5)
        self.wfile.write(b"data: last\n\n")


def start(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "claude").write_text(SECRET)
        self.auth_file = self.root / "auth.json"
        self.auth_file.write_text(json.dumps(auth()))
        self.fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        self.fake.seen, self.fake.release, self.fake.reject_once = [], threading.Event(), False
        self.fake.release.set()
        start(self.fake)
        fake_port = self.fake.server_port

        class LocalRelay(keyswap.Relay):
            def connect(self, host):
                return http.client.HTTPConnection("127.0.0.1", fake_port, timeout=3)

        self.relay = start(LocalRelay(("127.0.0.1", 0), self.root / "claude", self.auth_file, self.root / "web.jsonl"))

    def tearDown(self):
        self.fake.release.set()
        for server in (self.relay, self.fake):
            server.shutdown()
            server.server_close()
        self.tmp.cleanup()

    def request(self, path="/anthropic/v1/messages", body=b"{}", method="POST", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.relay.server_port, timeout=3)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        return connection, response

    def test_swap_and_stream(self):
        self.fake.release.clear()
        connection, response = self.request(headers={"Authorization": "Bearer dummy", "X-Api-Key": "dummy",
            "ChatGPT-Account-Id": "dummy", "Cookie": "dummy", "Host": "evil.test",
            "Anthropic-Beta": "other-beta", "Anthropic-Version": "2023-06-01"})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.readline(), b"data: first\n")  # second event is still blocked upstream
        self.fake.release.set()
        self.assertEqual(response.read(), b"\ndata: last\n\n")
        connection.close()
        headers = {k.lower(): v for k, v in self.fake.seen[0][1].items()}
        self.assertEqual(headers["authorization"], "Bearer " + SECRET)
        self.assertEqual(headers["anthropic-beta"], "other-beta," + keyswap.OAUTH_BETA)
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertNotIn("x-api-key", headers)
        self.assertNotIn("cookie", headers)
        self.assertNotIn("chatgpt-account-id", headers)
        self.assertNotIn("Authorization", dict(response.getheaders()))
        raw = (self.root / "web.jsonl").read_text()
        self.assertNotIn(SECRET, raw)
        self.assertEqual(json.loads(raw)["url"], "https://api.anthropic.com/v1/messages")
        meter = (self.root / "claude-meter.jsonl").read_text().splitlines()
        self.assertEqual(len(meter), 1)  # one row per Claude response, no secrets
        self.assertNotIn(SECRET, meter[0])

    def test_upstream_allowlist(self):
        for path in ("https://evil.test/", "//evil.test/", "/anthropic/../v1/messages",
                     "/anthropic/v1/messages/../../evil", "/anthropic/v1/%6dessages",
                     "/chatgpt/backend-api/codex/../../oauth/token", "/oauth/token"):
            connection, response = self.request(path)
            self.assertEqual(response.status, 403, path)
            response.read()
            connection.close()
        self.assertEqual(self.fake.seen, [])
        with self.assertRaises(ValueError):
            keyswap.Relay.connect(self.relay, "evil.test")
        with self.assertRaises(ValueError):
            keyswap.swapped_headers({}, "evil.test", SECRET)

    def test_error_and_redirect_redaction(self):
        for status in (400, 429, 500, 302):
            connection, response = self.request(body=json.dumps({"status": status}).encode())
            self.assertEqual(response.status, status if status >= 400 else 502)
            body = response.read()  # error details reach the agent, credential scrubbed
            self.assertEqual(body, b"Authorization: Bearer [redacted]" if status >= 400 else b"")
            self.assertNotIn(SECRET, str(response.getheaders()))
            connection.close()
        def broken(host):
            raise RuntimeError("Authorization: Bearer " + SECRET)
        self.relay.connect = broken
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            connection, response = self.request()
            self.assertEqual(response.status, 502)
            self.assertEqual(response.read(), b"")
            connection.close()
        self.assertNotIn(SECRET, output.getvalue() + (self.root / "web.jsonl").read_text())

    def test_refresh_and_account(self):
        self.auth_file.write_text(json.dumps(auth(expired=True)))
        connection, response = self.request("/chatgpt/backend-api/codex/responses?secret=" + SECRET)
        self.assertEqual(response.status, 200)
        response.read()
        connection.close()
        self.assertEqual([r[0] for r in self.fake.seen], ["/oauth/token", "/backend-api/codex/responses?secret=" + SECRET])
        headers = {k.lower(): v for k, v in self.fake.seen[-1][1].items()}
        self.assertEqual(headers["chatgpt-account-id"], ACCOUNT)
        self.assertEqual(headers["authorization"], "Bearer " + auth()["tokens"]["access_token"])
        self.assertEqual(json.loads(self.auth_file.read_text())["tokens"]["refresh_token"], "rotated-" + REFRESH)
        self.assertNotIn(SECRET, (self.root / "web.jsonl").read_text())

    def test_401_refresh_once(self):
        self.fake.reject_once = True
        connection, response = self.request("/chatgpt/backend-api/codex/responses")
        self.assertEqual(response.status, 200)
        response.read()
        connection.close()
        self.assertEqual([r[0] for r in self.fake.seen], ["/backend-api/codex/responses", "/oauth/token", "/backend-api/codex/responses"])

    def test_legacy_auth_and_serial_refresh(self):
        data = auth(expired=True)
        del data["auth_mode"]  # Codex also infers ChatGPT mode from token-only files.
        self.auth_file.write_text(json.dumps(data))
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.relay.credential("chatgpt.com"))) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 4)
        self.assertEqual([r[0] for r in self.fake.seen], ["/oauth/token"])

    def test_audit_failure_prevents_forwarding(self):
        self.relay.log_file = self.root / "absent" / "log"
        connection, response = self.request()
        self.assertEqual(response.status, 502)
        response.read()
        connection.close()
        self.assertEqual(self.fake.seen, [])


def fake_https():
    """Docker-only TLS fixture. Every network in the test is internal."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "keyswap-test")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(h) for h in
                ("api.anthropic.com", "chatgpt.com", "auth.openai.com")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    Path("/ca/cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    Path("/tmp/key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain("/ca/cert.pem", "/tmp/key.pem")

    class CheckedFake(Fake):
        def do_POST(self):
            if self.path != "/oauth/token":
                expected = SECRET if self.path.startswith("/v1/") else auth()["tokens"]["access_token"]
                assert self.headers.get("Authorization") == "Bearer " + expected
                assert not self.headers.get("X-Api-Key")
                if self.path.startswith("/backend-api/"):
                    assert self.headers.get("ChatGPT-Account-Id") == ACCOUNT
                else:
                    assert keyswap.OAUTH_BETA in self.headers.get("Anthropic-Beta", "")
            super().do_POST()

    server = ThreadingHTTPServer(("0.0.0.0", 443), CheckedFake)
    server.seen, server.release, server.reject_once = [], threading.Event(), False
    server.release.set()
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    if sys.argv[1:] == ["--fake-https"]:
        fake_https()
    else:
        unittest.main()
