"""Real Docker integration, synthetic model server only; no model calls.

Run: rtk proxy python3 tests/live/harbor/webproxy/test_webproxy.py
Requires the local unbug-bench-box:dev and redis:7.4.8-bookworm images.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

HERE = (Path(__file__).resolve().parents[4] / 'harbor/webproxy')
IMAGE = "mitmproxy/mitmproxy:12.1.2@sha256:0d7b2a14b4a71a908cd6f31b8f50e29bbc5c8720fe6caa706acf782da558e5c7"
MARKER = "SYNTHETIC_CREDENTIAL_MUST_NOT_BE_LOGGED"


def run(*args, check=True, **kwargs):
    return subprocess.run(["rtk", "proxy", *args], check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)


def main():
    spec = importlib.util.spec_from_file_location("audit", HERE / "audit.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    assert audit.sanitized_url("https://user:password@github.com/medusajs/medusa/issues/17032?token=secret#x")[0] == "https://github.com/medusajs/medusa/issues/17032"
    assert "sk-abc" not in audit.sanitized_url("https://example.com/sk-abc")[0]
    assert all(audit.model_host(h) for h in ("api.openai.com", "auth.openai.com", "ab.chatgpt.com", "regional.files.oaiusercontent.com"))
    assert not audit.model_host("boat.dev")
    assert all(audit.blocked_host(h) for h in ("boat.dev", "BOAT.DEV.", "api.boat.dev"))
    assert not audit.blocked_host("boat.dev.evil.test")
    assert all(not audit.model_host(h) for h in ("evilapi.openai.com", "api.openai.com.evil.test", "oaiusercontent.com.evil.test", "evil-oaiusercontent.com", ".oaiusercontent.com", "1.1.1.1", "evil.boat.dev", "boat.dev.evil.test"))
    failed_write = run("python3", "-c", f"import importlib.util; s=importlib.util.spec_from_file_location('audit',{str(HERE / 'audit.py')!r}); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); a=m.Audit(); a.log=None; a.record('GET','https://example.com/','request')", check=False)
    assert failed_write.returncode == 70 and not failed_write.stdout and not failed_write.stderr
    project = "unbug-webproxy-test-" + uuid.uuid4().hex[:8]
    env = dict(os.environ, UNBUG_WEBPROXY_DIR=str(HERE))
    with tempfile.TemporaryDirectory(prefix="unbug-webproxy-") as tmp:
        tmp = Path(tmp)
        # TLS destination emulates the API hostname on this project's egress network.
        # This never contacts an actual model API, and accepts synthetic credentials only.
        (tmp / "fixture.py").write_text('''
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from datetime import datetime, timedelta, timezone
import ssl, socket
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.openai.com")])
cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(datetime.now(timezone.utc)-timedelta(days=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=1)).sign(key, hashes.SHA256())
open('/tmp/key.pem','wb').write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
open('/tmp/cert.pem','wb').write(cert.public_bytes(serialization.Encoding.PEM))
ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain('/tmp/cert.pem','/tmp/key.pem')
s=socket.socket(); s.bind(('0.0.0.0',443)); s.listen()
while True:
    connection,_=s.accept()
    try:
        with ctx.wrap_socket(connection,server_side=True) as c:
            data=c.recv(65536)
            while b'\\r\\n\\r\\n' not in data: data+=c.recv(65536)
            headers, body=data.split(b'\\r\\n\\r\\n',1)
            while len(body)<len(b'SYNTHETIC_CREDENTIAL_MUST_NOT_BE_LOGGED'): body+=c.recv(65536)
            ok=b'Authorization: Bearer SYNTHETIC_CREDENTIAL_MUST_NOT_BE_LOGGED' in headers and body==b'SYNTHETIC_CREDENTIAL_MUST_NOT_BE_LOGGED'
            c.sendall(b'HTTP/1.1 '+(b'200 OK' if ok else b'400 Bad Request')+b'\\r\\nContent-Length: 2\\r\\nConnection: close\\r\\n\\r\\nOK')
    except (ssl.SSLError, OSError): pass
''')
        base = tmp / "base.yaml"
        base.write_text(f'''services:
  main:
    image: unbug-bench-box:dev
    privileged: true
    volumes: [nested:/var/lib/docker]
    healthcheck:
      test: [CMD, docker, info]
      interval: 2s
      timeout: 5s
      retries: 60
  fixture:
    image: {IMAGE}
    entrypoint: [python, /fixture.py]
    volumes: ["{tmp}/fixture.py:/fixture.py:ro"]
    networks:
      web-egress:
        aliases: [api.openai.com]
volumes:
  nested: {{}}
''')
        compose = ["docker", "compose", "-p", project, "-f", str(base), "-f", str(HERE / "docker-compose.webproxy.yaml")]

        def dc(*args, **kwargs):
            return run(*compose, *args, env=env, **kwargs)

        def curl(*args, **kwargs):
            return dc("exec", "-T", "main", "curl", "-sS", "--max-time", "30", *args, **kwargs)

        try:
            dc("up", "-d", "--wait")
            curl("-f", "http://example.com/?token=" + MARKER, "-o", "/dev/null")
            curl("-f", "https://github.com/medusajs/medusa/issues/17032?token=" + MARKER, "-o", "/dev/null")
            assert curl("--noproxy", "*", "--connect-timeout", "3", "https://1.1.1.1", check=False).returncode != 0
            # API passthrough is proven by this fixture's self-signed certificate:
            # -k is intentional only here; the ordinary HTTPS request above trusts the CA.
            curl("-fk", "https://api.openai.com/synthetic-secret-path?token=" + MARKER,
                 "-H", "Authorization: Bearer " + MARKER, "--data-binary", MARKER)
            # A forged model SNI must never turn a public CONNECT into an opaque tunnel.
            assert curl("-k", "--connect-to", "api.openai.com:443:github.com:443",
                        "https://api.openai.com/medusajs/medusa/issues/17032", check=False).returncode != 0, dc("logs", "webproxy").stdout
            # Nor may a model CONNECT use a public hostname or a literal IP as SNI.
            assert curl("-k", "--connect-to", "github.com:443:api.openai.com:443",
                        "https://github.com/medusajs/medusa/issues/17032", check=False).returncode != 0
            assert curl("-k", "--connect-to", "api.openai.com:443:1.1.1.1:443",
                        "https://api.openai.com/", check=False).returncode != 0
            assert curl("-fk", "https://github.com/", "-H", "Host: api.openai.com", check=False).returncode != 0
            # Forwarded packets from nested Docker cannot use the outer internal network.
            with open(tmp / "nested.tar", "wb") as output:
                subprocess.run(["rtk", "proxy", "docker", "save", "redis:7.4.8-bookworm"], stdout=output, check=True)
            with open(tmp / "nested.tar", "rb") as source:
                subprocess.run(["rtk", "proxy", *compose, "exec", "-T", "main", "docker", "load"], stdin=source, env=env, stdout=subprocess.DEVNULL, check=True)
            result = dc("exec", "-T", "main", "docker", "run", "--rm", "redis:7.4.8-bookworm",
                        "bash", "-c", "timeout 3 bash -c 'echo test >/dev/tcp/1.1.1.1/443'", check=False)
            assert result.returncode != 0
            raw = dc("exec", "-T", "webproxy", "cat", "/log/web.jsonl").stdout
            rows = [json.loads(line) for line in raw.splitlines()]
            assert any(r["url"] == "https://github.com/medusajs/medusa/issues/17032" and r["method"] == "GET" for r in rows)
            assert any(r["url"] == "http://example.com/" for r in rows)
            api = [r for r in rows if r["domain"] == "api.openai.com"]
            assert api and all(r["method"] == "CONNECT" and r["visibility"] == "tunnel" for r in api)
            assert MARKER not in raw and "synthetic-secret-path" not in raw
            assert MARKER not in dc("logs", "webproxy").stdout
            dc("stop", "webproxy")
            assert curl("--connect-timeout", "3", "https://example.com", check=False).returncode != 0
            print("PASS HTTP + trusted HTTPS path logging; queries stripped; model TLS passthrough with no credentials/body/path logged; direct main + nested egress denied; proxy-down fails closed")
        finally:
            dc("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
