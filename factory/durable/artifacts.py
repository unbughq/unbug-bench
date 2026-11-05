"""WP3: the age Sealer and the ArtifactStore (local and R2 backends).

docs/designs/durable-execution-wp3.md. The Sealer runs on both sides; the store runs on
the control VM only and holds ciphertext, never keys or plaintext.

- AgeSealer encrypts with the real `age` CLI, to the X25519 identity derived from the
  scope key (contract.derive_keys), encoded as an age identity "AGE-SECRET-KEY-1..."
  (Bech32). The identity reaches age through an anonymous pipe, never disk, argv or env.
  Ref.digest is contract.artifact_digest under the derived HMAC key, checked on open.
- SealedStore names one immutable object per (scope, Ref):
  <prefix>/<scope>/<digest>.<kind>.age, and refuses a scope that does not fit the kind
  (BATCH_SCOPED kinds live in the batch scope, every other kind in the case scope).
- LocalObjects writes a temporary file, fsyncs it and link()s it into place, so a partial
  write is never visible and the first complete object wins.
- R2Objects signs each S3 request with SigV4, including the payload's sha256, so the
  store refuses a truncated or altered body, and reads every PUT back before returning.

Errors carry fixed codes only: never a path, URL, key, credential or age's stderr.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import http.client
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Callable, Mapping, Optional, Protocol
import urllib.error
import urllib.parse
import urllib.request

from durable.contract import (BATCH_ID, BATCH_SCOPED, CASE_ID, DIGEST, ArtifactKind, KeyService, Ref,
                              artifact_digest, derive_keys)

AGE_HEADER = b"age-encryption.org/v1\n"
IDENTITY_HRP = "age-secret-key-"
RECIPIENT_HRP = "age"


class ArtifactError(ValueError):
    """A fixed, content-free code (lowercase letters and underscores)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ArtifactMissing(ArtifactError):
    def __init__(self):
        super().__init__("artifact_missing")


# ---- Bech32 (BIP 173), as age encodes identities and recipients ---------------------------------

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_GEN = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)


def _polymod(values) -> int:
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= _GEN[i]
    return chk


def _hrp_expand(hrp: str) -> list:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convert(data, frombits: int, tobits: int, pad: bool) -> list:
    acc, bits, out, maxv = 0, 0, [], (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            out.append((acc >> bits) & maxv)
    if pad:
        if bits:
            out.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or (acc << (tobits - bits)) & maxv:
        raise ArtifactError("bad_bech32")
    return out


def bech32_encode(hrp: str, data: bytes) -> str:
    five = _convert(data, 8, 5, True)
    pm = _polymod(_hrp_expand(hrp) + five + [0] * 6) ^ 1
    return hrp + "1" + "".join(_CHARSET[d] for d in five + [(pm >> 5 * (5 - i)) & 31 for i in range(6)])


def bech32_decode(text: str) -> tuple[str, bytes]:
    if text.lower() != text and text.upper() != text:
        raise ArtifactError("bad_bech32")
    text = text.lower()
    sep = text.rfind("1")
    if sep < 1 or len(text) - sep < 7 or any(c not in _CHARSET for c in text[sep + 1:]):
        raise ArtifactError("bad_bech32")
    hrp, values = text[:sep], [_CHARSET.index(c) for c in text[sep + 1:]]
    if _polymod(_hrp_expand(hrp) + values) != 1:
        raise ArtifactError("bad_bech32")
    return hrp, bytes(_convert(values[:-6], 5, 8, False))


def age_identity(secret: bytes) -> str:
    """The age identity line for a 32-byte X25519 secret, as age-keygen writes it."""
    if type(secret) is not bytes or len(secret) != 32:
        raise ArtifactError("bad_secret")
    return bech32_encode(IDENTITY_HRP, secret).upper()


def identity_secret(identity: str) -> bytes:
    """Inverse of age_identity."""
    hrp, secret = bech32_decode(identity.strip())
    if hrp != IDENTITY_HRP or len(secret) != 32:
        raise ArtifactError("bad_identity")
    return secret


# ---- the Sealer ---------------------------------------------------------------------------------

class AgeSealer:
    """contract.Sealer with the age CLI. Stateless; holds no key between calls."""

    def __init__(self, age: str = "age"):
        self.age = age

    def seal(self, scope_key: bytes, kind: ArtifactKind, plaintext: bytes) -> tuple[Ref, bytes]:
        if type(plaintext) is not bytes:
            raise ArtifactError("plaintext_not_bytes")
        secret, hmac_key = derive_keys(scope_key)
        ref = Ref(artifact_digest(hmac_key, plaintext), ArtifactKind(kind))
        ciphertext = self._run("--encrypt", secret, plaintext, "seal_failed")
        if not ciphertext.startswith(AGE_HEADER):
            raise ArtifactError("seal_failed")
        return ref, ciphertext

    def open(self, scope_key: bytes, ref: Ref, ciphertext: bytes) -> bytes:
        if not isinstance(ref, Ref):
            raise ArtifactError("bad_ref")
        if type(ciphertext) is not bytes:
            raise ArtifactError("ciphertext_not_bytes")
        secret, hmac_key = derive_keys(scope_key)
        plaintext = self._run("--decrypt", secret, ciphertext, "open_failed")
        if not hmac.compare_digest(artifact_digest(hmac_key, plaintext), ref.digest):
            raise ArtifactError("digest_mismatch")
        return plaintext

    def _run(self, mode: str, secret: bytes, data: bytes, code: str) -> bytes:
        identity = (age_identity(secret) + "\n").encode()
        read_end, write_end = os.pipe()
        try:
            os.write(write_end, identity)   # 75 bytes: always fits the pipe buffer
            os.close(write_end)
            write_end = None
            try:
                done = subprocess.run([self.age, mode, "-i", f"/dev/fd/{read_end}"], input=data,
                                      capture_output=True, pass_fds=(read_end,))
            except OSError:
                raise ArtifactError("age_unavailable") from None
        finally:
            os.close(read_end)
            if write_end is not None:
                os.close(write_end)
        if done.returncode != 0:
            raise ArtifactError(code)   # age's stderr is dropped: it may name inputs
        return done.stdout


# ---- scopes -------------------------------------------------------------------------------------

def scope_for(kind: ArtifactKind, case_id: str, batch_id: str) -> str:
    """The scope a kind lives in: the batch for BATCH_SCOPED kinds, the case otherwise."""
    if ArtifactKind(kind) in BATCH_SCOPED:
        _scope_id(batch_id, BATCH_ID)
        return batch_id
    _scope_id(case_id, CASE_ID)
    return case_id


def _scope_id(value, pattern):
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ArtifactError("bad_scope")


def check_scope(scope: str, ref: Ref) -> None:
    """Refuse a scope that is not a valid id, or that does not fit the Ref's kind."""
    if not isinstance(ref, Ref) or type(ref.digest) is not str or DIGEST.fullmatch(ref.digest) is None:
        raise ArtifactError("bad_ref")
    if type(scope) is not str:
        raise ArtifactError("bad_scope")
    batch, case = BATCH_ID.fullmatch(scope) is not None, CASE_ID.fullmatch(scope) is not None
    if not (batch or case):
        raise ArtifactError("bad_scope")
    if batch != (ref.kind in BATCH_SCOPED):
        raise ArtifactError("wrong_scope")


def blob_name(ref: Ref) -> str:
    """<digest>.<kind>.age, the name attempt_paths uses for blobs on workers."""
    return f"{ref.digest}.{ref.kind.value}.age"


def seal_into(store, keys: KeyService, sealer, kind: ArtifactKind, plaintext: bytes, *,
              case_id: str, batch_id: str) -> Ref:
    """Seal under the kind's scope key and store; returns the Ref only once stored."""
    scope = scope_for(kind, case_id, batch_id)
    ref, ciphertext = sealer.seal(keys.scope_key(scope), kind, plaintext)
    store.put_sealed(scope, ref, ciphertext)
    return ref


def open_from(store, keys: KeyService, sealer, ref: Ref, *, case_id: str, batch_id: str) -> bytes:
    scope = scope_for(ref.kind, case_id, batch_id)
    return sealer.open(keys.scope_key(scope), ref, store.get_sealed(scope, ref))


# ---- the store ----------------------------------------------------------------------------------

class Objects(Protocol):
    """Immutable byte objects by key. put is first-wins and makes an object visible only
    once complete; get returns None when absent."""
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> Optional[bytes]: ...
    def exists(self, key: str) -> bool: ...


class SealedStore:
    """contract.ArtifactStore over an Objects backend. Never takes a key."""

    def __init__(self, objects: Objects, prefix: str = "durable"):
        if not _PART.fullmatch(prefix):
            raise ArtifactError("bad_prefix")
        self.objects, self.prefix = objects, prefix

    def key(self, scope: str, ref: Ref) -> str:
        check_scope(scope, ref)
        return f"{self.prefix}/{scope}/{blob_name(ref)}"

    def put_sealed(self, scope: str, ref: Ref, ciphertext: bytes) -> None:
        key = self.key(scope, ref)
        if type(ciphertext) is not bytes or not ciphertext.startswith(AGE_HEADER):
            raise ArtifactError("not_age_ciphertext")
        self.objects.put(key, ciphertext)

    def get_sealed(self, scope: str, ref: Ref) -> bytes:
        data = self.objects.get(self.key(scope, ref))
        if data is None:
            raise ArtifactMissing()
        return data

    def exists(self, scope: str, ref: Ref) -> bool:
        return self.objects.exists(self.key(scope, ref))


_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class LocalObjects:
    """Objects in a directory tree (tests, offline runs, a control-VM cache)."""

    def __init__(self, root):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        parts = key.split("/") if type(key) is str else []
        if not parts or not all(_PART.fullmatch(p) and ".." not in p for p in parts):
            raise ArtifactError("bad_key")
        return self.root.joinpath(*parts)

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        if path.is_file():
            return
        try:
            _mkdirs(path.parent)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")   # mode 0600
        except OSError:
            raise ArtifactError("store_failed") from None
        try:
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
            finally:
                os.close(fd)
            try:
                os.link(tmp, path)   # first complete object wins; never replaced
            except FileExistsError:
                pass
            _fsync_dir(path.parent)
        except OSError:
            raise ArtifactError("store_failed") from None
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def get(self, key: str) -> Optional[bytes]:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            raise ArtifactError("store_failed") from None

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


def _mkdirs(path: Path) -> None:
    missing = []
    while not path.is_dir():
        missing.append(path)
        path = path.parent
    for p in reversed(missing):
        try:
            p.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _fsync_dir(p.parent)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# ---- R2 (S3 API, SigV4 header auth) --------------------------------------------------------------

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def sigv4_headers(method: str, host: str, path: str, headers: Mapping[str, str], payload_sha256: str, *,
                  access_key: str, secret_key: str, now: datetime.datetime, region: str = "auto",
                  query: str = "", service: str = "s3") -> dict:
    """AWS Signature Version 4, Authorization-header form, with a signed payload hash.
    `path` is already URI-encoded (S3 encodes once). Returns the headers to send."""
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    date = stamp[:8]
    canon = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    canon.update({"host": host, "x-amz-date": stamp, "x-amz-content-sha256": payload_sha256})
    signed = ";".join(sorted(canon))
    request = "\n".join([method, path, query, "".join(f"{k}:{canon[k]}\n" for k in sorted(canon)), signed,
                         payload_sha256])
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(request.encode()).hexdigest()])
    k = ("AWS4" + secret_key).encode()
    for part in (date, region, service, "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    out = {k: v for k, v in headers.items() if k.lower() != "host"}
    out.update({"x-amz-date": stamp, "x-amz-content-sha256": payload_sha256,
                "Authorization": f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
                                 f"SignedHeaders={signed}, Signature={signature}"})
    return out


Transport = Callable[[str, str, Mapping[str, str], Optional[bytes]], tuple]


def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: Optional[bytes],
                     timeout: float = 300) -> tuple:
    """(status, headers, body). An HTTP error status is returned, not raised."""
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        return status, {}, b""


class R2Objects:
    """Objects in a Cloudflare R2 bucket over the S3 API. Credentials stay in memory."""

    def __init__(self, account: str, access_key: str, secret_key: str, bucket: str, *,
                 endpoint: Optional[str] = None, region: str = "auto", transport: Optional[Transport] = None,
                 clock: Optional[Callable[[], datetime.datetime]] = None):
        if not all(type(v) is str and v for v in (account, access_key, secret_key, bucket)):
            raise ArtifactError("r2_credentials_missing")
        self._access, self._secret, self.bucket, self.region = access_key, secret_key, bucket, region
        self.endpoint = (endpoint or f"https://{account}.r2.cloudflarestorage.com").rstrip("/")
        self.host = urllib.parse.urlsplit(self.endpoint).netloc
        self._transport = transport or urllib_transport
        self._clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))

    def __repr__(self):
        return f"R2Objects(bucket={self.bucket!r})"   # never the credentials

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ, **kw) -> "R2Objects":
        names = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
        return cls(*(env.get(n, "") for n in names), **kw)

    def _call(self, method: str, key: str, body: Optional[bytes] = None) -> tuple:
        if not all(_PART.fullmatch(p) and ".." not in p for p in key.split("/")):
            raise ArtifactError("bad_key")
        path = "/" + urllib.parse.quote(f"{self.bucket}/{key}", safe="/~")
        payload = hashlib.sha256(body).hexdigest() if body is not None else EMPTY_SHA256
        extra = {"Content-Length": str(len(body))} if body is not None else {}
        headers = sigv4_headers(method, self.host, path, {}, payload, access_key=self._access,
                                secret_key=self._secret, now=self._clock(), region=self.region)
        headers.update(extra)
        try:
            status, got, data = self._transport(method, self.endpoint + path, headers, body)
        except ArtifactError:
            raise
        except (OSError, http.client.HTTPException, ValueError):
            raise ArtifactError("transport_failed") from None
        return status, got, data

    def put(self, key: str, data: bytes) -> None:
        if self.exists(key):
            return   # first complete object wins; every object was verified when written
        status, _, _ = self._call("PUT", key, data)
        if status != 200:
            raise ArtifactError("upload_failed")
        back = self.get(key)
        if back is None or not hmac.compare_digest(hashlib.sha256(back).digest(), hashlib.sha256(data).digest()):
            raise ArtifactError("upload_unverified")

    def get(self, key: str) -> Optional[bytes]:
        status, headers, data = self._call("GET", key)
        if status == 404:
            return None
        if status != 200:
            raise ArtifactError("download_failed")
        length = headers.get("content-length")
        if length is not None and length.isdigit() and int(length) != len(data):
            raise ArtifactError("download_failed")
        return data

    def exists(self, key: str) -> bool:
        status, _, _ = self._call("HEAD", key)
        if status == 404:
            return False
        if status != 200:
            raise ArtifactError("store_unavailable")
        return True


def local_store(root, prefix: str = "durable") -> SealedStore:
    return SealedStore(LocalObjects(root), prefix)


def r2_store(env: Mapping[str, str] = os.environ, prefix: str = "durable", **kw) -> SealedStore:
    return SealedStore(R2Objects.from_env(env, **kw), prefix)
