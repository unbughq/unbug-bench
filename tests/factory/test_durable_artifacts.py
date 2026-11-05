"""WP3: the age Sealer and the ArtifactStore (ARCHITECTURE.md).

Real artifacts only: the real `age` and `age-keygen` binaries, real files, a real child
process killed mid-write, and real HTTP sockets. Independent checks: RFC 7748's X25519
vectors, and AWS's published SigV4 examples.
"""
import base64
import hashlib
import hmac
import http.client
import http.server
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest import mock
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory"), str(ROOT / "bin")]
os.environ.setdefault("BENCH", str(ROOT))
os.environ["no_proxy"] = os.environ["NO_PROXY"] = ",".join(
    filter(None, [os.environ.get("no_proxy", ""), "127.0.0.1", "localhost"]))

import datetime  # noqa: E402

import durable.artifacts as artifacts  # noqa: E402
from durable.artifacts import (ArtifactError, ArtifactMissing, AgeSealer, LocalObjects, R2Objects,  # noqa: E402
                               SealedStore, age_identity, bech32_encode, identity_secret, local_store,
                               open_from, scope_for, seal_into, sigv4_headers, urllib_transport)
from durable.contract import BATCH_SCOPED, ArtifactKind, Ref, artifact_digest, derive_keys  # noqa: E402

K = ArtifactKind
CASE, OTHER, BATCH = "case-20261105T000000Z-a1b2c3", "case-20261105T000000Z-d4e5f6", "b-pilot-7"
CASE_KEY, OTHER_KEY, BATCH_KEY = os.urandom(32), os.urandom(32), os.urandom(32)


class Keys:
    """A KeyService (WP7's seam) holding scope keys in memory."""
    def __init__(self, keys):
        self.keys = keys

    def scope_key(self, scope):
        return self.keys[scope]


KEYS = Keys({CASE: CASE_KEY, OTHER: OTHER_KEY, BATCH: BATCH_KEY})


# Independent RFC 7748 X25519, to check the identity really is the derived secret.
P = 2 ** 255 - 19


def x25519(scalar: bytes, u: bytes) -> bytes:
    k = bytearray(scalar)
    k[0] &= 248; k[31] &= 127; k[31] |= 64
    k = int.from_bytes(k, "little")
    x1 = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in reversed(range(255)):
        bit = (k >> t) & 1
        swap ^= bit
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a, b, c, d = x2 + z2, x2 - z2, x3 + z3, x3 - z3
        aa, bb, da, cb = a * a, b * b, d * a, c * b
        e = aa - bb
        x3, z3 = (da + cb) ** 2 % P, x1 * (da - cb) ** 2 % P
        x2, z2 = aa * bb % P, e * (aa + 121665 * e) % P
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, P - 2, P) % P).to_bytes(32, "little")


BASE = (9).to_bytes(32, "little")


def run(args, data=None):
    return subprocess.run(args, input=data, capture_output=True, check=True).stdout


class IdentityEncoding(unittest.TestCase):
    def test_x25519_matches_rfc7748(self):
        """RFC 7748 section 6.1: Alice's and Bob's public keys and their shared secret."""
        alice = bytes.fromhex("77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")
        bob = bytes.fromhex("5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb")
        self.assertEqual(x25519(alice, BASE).hex(), "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a")
        self.assertEqual(x25519(bob, BASE).hex(), "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f")
        self.assertEqual(x25519(alice, x25519(bob, BASE)).hex(),
                         "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742")

    def test_real_age_keygen_identity_round_trips(self):
        for _ in range(5):
            made = run(["age-keygen"]).decode().splitlines()
            identity = next(line for line in made if line.startswith("AGE-SECRET-KEY-1"))
            public = next(line for line in made if line.startswith("# public key: ")).split(": ")[1]
            secret = identity_secret(identity)
            self.assertEqual(age_identity(secret), identity)
            self.assertEqual(bech32_encode("age", x25519(secret, BASE)), public)

    def test_derived_identity_is_accepted_by_age_keygen(self):
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(5):
                secret = derive_keys(os.urandom(32))[0]
                path = Path(tmp) / "id"
                path.write_text(age_identity(secret) + "\n")
                public = run(["age-keygen", "-y", str(path)]).decode().strip()
                self.assertEqual(public, bech32_encode("age", x25519(secret, BASE)))

    def test_bad_identity_strings_are_refused(self):
        good = age_identity(derive_keys(CASE_KEY)[0])
        for bad in (good[:-1] + ("Q" if good[-1] != "Q" else "P"), good.lower()[:20] + good[20:], "AGE1XYZ", ""):
            with self.assertRaises(ArtifactError):
                identity_secret(bad)


class Sealing(unittest.TestCase):
    sealer = AgeSealer()

    def test_interop_with_the_real_age_cli(self):
        plaintext = os.urandom(4096) + b"promise text"
        ref, ciphertext = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, plaintext)
        self.assertTrue(ciphertext.startswith(b"age-encryption.org/v1\n-> X25519 "))
        with tempfile.TemporaryDirectory() as tmp:
            ident = Path(tmp) / "id"
            ident.write_text(age_identity(derive_keys(CASE_KEY)[0]) + "\n")
            self.assertEqual(run(["age", "-d", "-i", str(ident)], ciphertext), plaintext)
            recipient = run(["age-keygen", "-y", str(ident)]).decode().strip()
        foreign = run(["age", "-r", recipient], plaintext)
        self.assertEqual(self.sealer.open(CASE_KEY, ref, foreign), plaintext)

    def test_same_plaintext_same_ref_within_a_scope_and_different_across(self):
        plaintext = b"the same snapshot bytes"
        r1, c1 = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, plaintext)
        r2, c2 = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, plaintext)
        self.assertEqual(r1, r2)
        self.assertNotEqual(c1, c2)   # age is randomised; both open to the same bytes
        self.assertEqual(self.sealer.open(CASE_KEY, r1, c2), plaintext)
        self.assertEqual(r1.digest, hmac.new(derive_keys(CASE_KEY)[1], plaintext, hashlib.sha256).hexdigest())
        r3, _ = self.sealer.seal(OTHER_KEY, K.CASE_SNAPSHOT, plaintext)
        r4, _ = self.sealer.seal(BATCH_KEY, K.CASE_SNAPSHOT, plaintext)
        self.assertEqual(len({r1.digest, r3.digest, r4.digest}), 3)
        self.assertNotEqual(r1.digest, hashlib.sha256(plaintext).hexdigest())
        r5, _ = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, plaintext + b"!")
        self.assertNotEqual(r1.digest, r5.digest)

    def test_ciphertext_opens_only_with_its_scope_key(self):
        ref, ciphertext = self.sealer.seal(CASE_KEY, K.WRITER_FEEDBACK, b"findings for the next round")
        for key in (OTHER_KEY, BATCH_KEY, os.urandom(32)):
            with self.assertRaises(ArtifactError) as raised:
                self.sealer.open(key, ref, ciphertext)
            self.assertEqual(raised.exception.code, "open_failed")
        damaged = bytearray(ciphertext); damaged[-5] ^= 1
        truncated = ciphertext[:len(ciphertext) - 3]
        for bad in (bytes(damaged), truncated, b"", b"not age at all"):
            with self.assertRaises(ArtifactError):
                self.sealer.open(CASE_KEY, ref, bad)
        other_ref, other_ct = self.sealer.seal(CASE_KEY, K.WRITER_FEEDBACK, b"different findings")
        with self.assertRaises(ArtifactError) as raised:
            self.sealer.open(CASE_KEY, ref, other_ct)   # a valid ciphertext under the wrong Ref
        self.assertEqual(raised.exception.code, "digest_mismatch")
        self.assertEqual(self.sealer.open(CASE_KEY, ref, ciphertext), b"findings for the next round")

    def test_errors_carry_no_content(self):
        ref, ciphertext = self.sealer.seal(CASE_KEY, K.DIAGNOSTIC, b"secret transcript line")
        with self.assertRaises(ArtifactError) as raised:
            self.sealer.open(OTHER_KEY, ref, ciphertext)
        text = str(raised.exception)
        self.assertEqual(text, "open_failed")
        for leak in (base64.b64encode(OTHER_KEY).decode(), age_identity(derive_keys(OTHER_KEY)[0]), "transcript"):
            self.assertNotIn(leak, repr(raised.exception) + text)

    def test_empty_and_large_plaintexts(self):
        for plaintext in (b"", os.urandom(8 * 1024 * 1024)):
            ref, ciphertext = self.sealer.seal(CASE_KEY, K.SEALED_ARCHIVE, plaintext)
            self.assertEqual(self.sealer.open(CASE_KEY, ref, ciphertext), plaintext)

    def test_a_stuck_age_times_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            stuck = Path(tmp) / "age"
            stuck.write_text("#!/bin/sh\nexec sleep 60\n")
            stuck.chmod(0o700)
            sealer = AgeSealer(age=str(stuck), timeout_s=1)
            for call in (lambda: sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"x"),
                         lambda: sealer.open(CASE_KEY, Ref("a" * 64, K.CASE_SNAPSHOT), b"y")):
                with self.assertRaises(ArtifactError) as raised:
                    call()
                self.assertEqual(str(raised.exception), "age_timeout")

    def test_identity_never_on_disk_argv_or_env(self):
        seen = []
        real = subprocess.run

        def spy(args, **kw):
            seen.append((list(args), kw.get("env")))
            return real(args, **kw)
        with mock.patch("durable.artifacts.subprocess.run", spy):
            ref, ct = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"x")
            self.sealer.open(CASE_KEY, ref, ct)
        identity = age_identity(derive_keys(CASE_KEY)[0])
        for args, env in seen:
            self.assertTrue(args[-1].startswith("/dev/fd/"))
            self.assertNotIn(identity, " ".join(args))
            self.assertIsNone(env)


class Scopes(unittest.TestCase):
    sealer = AgeSealer()

    def test_batch_scoped_kinds_use_the_batch_scope(self):
        self.assertEqual(BATCH_SCOPED, {K.INPUTS, K.STATEMENT_REGISTRY})
        for kind in K:
            self.assertEqual(scope_for(kind, CASE, BATCH), BATCH if kind in BATCH_SCOPED else CASE)
        with tempfile.TemporaryDirectory() as tmp:
            store = local_store(tmp)
            for kind in K:
                plaintext = f"{kind.value} bytes".encode()
                ref = seal_into(store, KEYS, self.sealer, kind, plaintext, case_id=CASE, batch_id=BATCH)
                scope = BATCH if kind in BATCH_SCOPED else CASE
                path = Path(tmp) / "durable" / scope / f"{ref.digest}.{kind.value}.age"
                self.assertTrue(path.is_file())
                self.assertEqual(ref.digest, artifact_digest(derive_keys(KEYS.keys[scope])[1], plaintext))
                self.assertEqual(open_from(store, KEYS, self.sealer, ref, case_id=CASE, batch_id=BATCH), plaintext)
                wrong = CASE_KEY if scope == BATCH else BATCH_KEY
                with self.assertRaises(ArtifactError):
                    self.sealer.open(wrong, ref, path.read_bytes())
            # Another case of the same batch reads the batch inputs, never this case's snapshot.
            inputs = seal_into(store, KEYS, self.sealer, K.INPUTS, b"pin", case_id=CASE, batch_id=BATCH)
            self.assertEqual(open_from(store, KEYS, self.sealer, inputs, case_id=OTHER, batch_id=BATCH), b"pin")
            snap = seal_into(store, KEYS, self.sealer, K.CASE_SNAPSHOT, b"s", case_id=CASE, batch_id=BATCH)
            with self.assertRaises(ArtifactMissing):
                open_from(store, KEYS, self.sealer, snap, case_id=OTHER, batch_id=BATCH)

    def test_store_refuses_a_scope_that_does_not_fit_the_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = local_store(tmp)
            ref, ct = self.sealer.seal(BATCH_KEY, K.INPUTS, b"inputs")
            snap, sct = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"snapshot")
            for scope, r, c in ((CASE, ref, ct), (BATCH, snap, sct)):
                for call in (lambda: store.put_sealed(scope, r, c), lambda: store.get_sealed(scope, r),
                             lambda: store.exists(scope, r)):
                    with self.assertRaises(ArtifactError) as raised:
                        call()
                    self.assertEqual(raised.exception.code, "wrong_scope")
            for scope in ("../" + CASE, CASE + "/..", "case-a/b", "", "B-PILOT", None):
                with self.assertRaises(ArtifactError):
                    store.put_sealed(scope, snap, sct)
            with self.assertRaises(ArtifactError):
                scope_for(K.INPUTS, CASE, "../etc")
            self.assertEqual(sorted(p.name for p in Path(tmp).rglob("*")), [])


class LocalStore(unittest.TestCase):
    sealer = AgeSealer()

    def test_round_trip_and_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = local_store(tmp)
            ref, ct = self.sealer.seal(CASE_KEY, K.GATE_RECEIPT, b"receipt")
            self.assertFalse(store.exists(CASE, ref))
            with self.assertRaises(ArtifactMissing):
                store.get_sealed(CASE, ref)
            store.put_sealed(CASE, ref, ct)
            self.assertTrue(store.exists(CASE, ref))
            self.assertEqual(store.get_sealed(CASE, ref), ct)
            path = Path(tmp) / "durable" / CASE / f"{ref.digest}.receipt.age"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), [path.name])

    def test_store_refuses_plaintext(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = local_store(tmp)
            ref, _ = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"plain")
            for bad in (b"plain", "age-encryption.org/v1\n", bytearray(b"age-encryption.org/v1\n")):
                with self.assertRaises(ArtifactError):
                    store.put_sealed(CASE, ref, bad)
            self.assertFalse(store.exists(CASE, ref))

    def test_first_complete_object_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = local_store(tmp)
            ref, first = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"same bytes")
            _, second = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"same bytes")
            store.put_sealed(CASE, ref, first)
            inode = (Path(tmp) / "durable" / CASE / f"{ref.digest}.case.age").stat().st_ino
            store.put_sealed(CASE, ref, second)
            self.assertEqual(store.get_sealed(CASE, ref), first)
            self.assertEqual((Path(tmp) / "durable" / CASE / f"{ref.digest}.case.age").stat().st_ino, inode)

    def test_a_lost_race_keeps_the_first_inode_and_fsyncs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = local_store(tmp)
            ref, first = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"same bytes")
            _, second = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"same bytes")
            store.put_sealed(CASE, ref, first)
            path = Path(tmp) / "durable" / CASE / f"{ref.digest}.case.age"
            inode = path.stat().st_ino
            real_is_file = Path.is_file

            def unseen(p):   # the second writer checked before the first linked
                return False if p == path else real_is_file(p)
            with mock.patch.object(Path, "is_file", unseen), \
                    mock.patch("durable.artifacts._fsync_dir", wraps=artifacts._fsync_dir) as synced, \
                    mock.patch("durable.artifacts.os.link", wraps=os.link) as linked:
                store.put_sealed(CASE, ref, second)   # reaches os.link -> FileExistsError
            self.assertEqual(linked.call_count, 1)
            self.assertIn(mock.call(path.parent), synced.call_args_list)
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(path.read_bytes(), first)
            self.assertEqual([p.name for p in path.parent.iterdir()], [path.name])   # temp removed
            with mock.patch("durable.artifacts._fsync_dir", wraps=artifacts._fsync_dir) as synced:
                store.put_sealed(CASE, ref, second)   # the is_file shortcut
            self.assertEqual(synced.call_args_list, [mock.call(path.parent)])
            self.assertEqual(path.read_bytes(), first)

    def _killed_put(self, tmp, fault):
        """Run put_sealed in a real child process that SIGKILLs itself at `fault`."""
        plaintext = os.urandom(64 * 1024 * 1024)
        ref, ct = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, plaintext)
        blob = Path(tmp) / "ct"
        blob.write_bytes(ct)
        child = textwrap.dedent(f"""
            import os, signal, sys
            sys.path.insert(0, {str(ROOT / 'factory')!r})
            from durable.artifacts import local_store
            from durable.contract import ArtifactKind, Ref
            real_write, real_link = os.write, os.link
            def write(fd, data):
                real_write(fd, bytes(data[:len(data) // 2]))
                os.kill(os.getpid(), signal.SIGKILL)
            def link(src, dst):
                os.kill(os.getpid(), signal.SIGKILL)
            if {fault!r} == "write": os.write = write
            if {fault!r} == "link": os.link = link
            store = local_store({str(Path(tmp) / 'store')!r})
            store.put_sealed({CASE!r}, Ref({ref.digest!r}, ArtifactKind.CASE_SNAPSHOT), open({str(blob)!r}, "rb").read())
            print("finished")
        """)
        done = subprocess.run([sys.executable, "-B", "-c", child], capture_output=True)
        self.assertEqual(done.returncode, -signal.SIGKILL, done.stderr)
        self.assertNotIn(b"finished", done.stdout)
        return ref, ct, plaintext

    def test_an_upload_killed_mid_write_is_never_visible(self):
        for fault in ("write", "link"):
            with tempfile.TemporaryDirectory() as tmp:
                ref, ct, plaintext = self._killed_put(tmp, fault)
                directory = Path(tmp) / "store" / "durable" / CASE
                leftovers = list(directory.iterdir())
                self.assertEqual(len(leftovers), 1)
                self.assertTrue(leftovers[0].name.startswith(".tmp-"))
                size = leftovers[0].stat().st_size
                if fault == "write":
                    self.assertTrue(0 < size < len(ct), size)   # really interrupted halfway
                else:
                    self.assertEqual(size, len(ct))             # complete, but never linked
                store = local_store(Path(tmp) / "store")
                self.assertFalse(store.exists(CASE, ref))
                with self.assertRaises(ArtifactMissing):
                    store.get_sealed(CASE, ref)
                store.put_sealed(CASE, ref, ct)   # a retry after the crash succeeds
                self.assertEqual(self.sealer.open(CASE_KEY, ref, store.get_sealed(CASE, ref)), plaintext)

    def test_a_failed_write_leaves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = local_store(tmp)
            ref, ct = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"x" * 100_000)
            with mock.patch("durable.artifacts.os.fsync", side_effect=OSError(28, "No space left on device")):
                with self.assertRaises(ArtifactError) as raised:
                    store.put_sealed(CASE, ref, ct)   # fails creating the scope directory
            self.assertEqual(str(raised.exception), "store_failed")
            self.assertFalse(store.exists(CASE, ref))
            first, fct = self.sealer.seal(CASE_KEY, K.GATE_RECEIPT, b"an earlier object")
            store.put_sealed(CASE, first, fct)   # the directory now exists
            with mock.patch("durable.artifacts.os.fsync", side_effect=OSError(28, "No space left on device")):
                with self.assertRaises(ArtifactError) as raised:
                    store.put_sealed(CASE, ref, ct)   # fails after writing the file's bytes
            self.assertEqual(str(raised.exception), "store_failed")
            self.assertEqual([p.name for p in (Path(tmp) / "durable" / CASE).iterdir()], [f"{first.digest}.receipt.age"])
            self.assertFalse(store.exists(CASE, ref))
            store.put_sealed(CASE, ref, ct)
            self.assertEqual(store.get_sealed(CASE, ref), ct)

    def test_local_objects_refuse_bad_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            objects = LocalObjects(tmp)
            for key in ("../x", "a/../b", "/abs", "a//b", ".tmp-x", "a/.hidden", ""):
                with self.assertRaises(ArtifactError):
                    objects.put(key, b"age-encryption.org/v1\n")


# ---- R2 -------------------------------------------------------------------------------------------

class SigV4(unittest.TestCase):
    """AWS S3 docs, 'Signature Calculations for the Authorization Header: Transferring Payload in a
    Single Chunk': examplebucket, us-east-1, 20130524T000000Z, the documentation's example keys."""
    ACCESS, SECRET = "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    NOW = datetime.datetime(2013, 5, 24, tzinfo=datetime.timezone.utc)

    def test_get_object_example(self):
        headers = sigv4_headers("GET", "examplebucket.s3.amazonaws.com", "/test.txt", {"Range": "bytes=0-9"},
                                hashlib.sha256(b"").hexdigest(), access_key=self.ACCESS, secret_key=self.SECRET,
                                now=self.NOW, region="us-east-1")
        self.assertEqual(headers["Authorization"],
                         "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
                         "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
                         "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")

    def test_put_object_example(self):
        body = b"Welcome to Amazon S3."
        headers = sigv4_headers("PUT", "examplebucket.s3.amazonaws.com", "/test%24file.text",
                                {"Date": "Fri, 24 May 2013 00:00:00 GMT", "x-amz-storage-class": "REDUCED_REDUNDANCY"},
                                hashlib.sha256(body).hexdigest(), access_key=self.ACCESS, secret_key=self.SECRET,
                                now=self.NOW, region="us-east-1")
        self.assertEqual(headers["x-amz-content-sha256"],
                         "44ce7dd67c959e0d3524ffac1771dfbba87d2b6b4b4e99e42034a8b803f8b072")
        self.assertTrue(headers["Authorization"].endswith(
            "SignedHeaders=date;host;x-amz-content-sha256;x-amz-date;x-amz-storage-class, "
            "Signature=98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd"))


EMPTY = hashlib.sha256(b"").hexdigest()


class FakeS3(http.server.ThreadingHTTPServer):
    """An S3-like server over real sockets. Like S3 and R2, it commits a PUT only when the whole
    Content-Length body arrived and its sha256 matches the signed x-amz-content-sha256, keeps an
    existing object under If-None-Match: *, and checks every request's SigV4 signature."""
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), S3Handler)
        self.objects, self.requests, self.corrupt_reads, self.redirect_to = {}, [], False, None
        self.put_headers = []
        self.put_done = threading.Event()
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


class S3Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _reply(self, status, body=b"", length=None):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body) if length is None else length))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _signed(self, body_sha256=None):
        """Recompute the SigV4 signature from what actually arrived, with the test secret."""
        body_sha256 = body_sha256 or EMPTY
        auth = self.headers.get("Authorization", "")
        m = re.fullmatch(r"AWS4-HMAC-SHA256 Credential=ak/(\d{8})/([a-z0-9-]+)/s3/aws4_request, "
                         r"SignedHeaders=([a-z0-9;-]+), Signature=[0-9a-f]{64}", auth)
        if not m or self.headers.get("x-amz-content-sha256") != body_sha256:
            return False
        names = m.group(3).split(";")
        if not {"host", "x-amz-date", "x-amz-content-sha256"} <= set(names) or \
                any(self.headers.get(n) is None for n in names):
            return False
        others = {n: self.headers[n] for n in names if n not in ("host", "x-amz-date", "x-amz-content-sha256")}
        now = datetime.datetime.strptime(self.headers["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(
            tzinfo=datetime.timezone.utc)
        want = sigv4_headers(self.command, self.headers["host"], self.path, others, body_sha256,
                             access_key="ak", secret_key="sk-secret", now=now, region=m.group(2))
        return m.group(1) == self.headers["x-amz-date"][:8] and hmac.compare_digest(want["Authorization"], auth)

    def _redirected(self):
        if self.server.redirect_to is None:
            return False
        self.send_response(302)
        self.send_header("Location", self.server.redirect_to + self.path)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def do_PUT(self):
        try:
            self.server.requests.append(("PUT", self.path))
            want, body = int(self.headers["Content-Length"]), b""
            while len(body) < want:
                chunk = self.rfile.read(want - len(body))
                if not chunk:
                    self.close_connection = True
                    return   # the client went away: nothing is committed
                body += chunk
            if self._redirected():
                return
            self.server.put_headers.append({k.lower(): v for k, v in self.headers.items()})
            if hashlib.sha256(body).hexdigest() != self.headers.get("x-amz-content-sha256"):
                return self._reply(400, b"<Code>XAmzContentSHA256Mismatch</Code>")
            if not self._signed(self.headers["x-amz-content-sha256"]):
                return self._reply(403)
            key = urllib.parse.unquote(self.path)
            if self.headers.get("If-None-Match") == "*" and key in self.server.objects:
                return self._reply(412)   # conditional PUT: the first object is kept
            self.server.objects[key] = body
            self._reply(200)
        finally:
            self.server.put_done.set()

    def do_GET(self):
        self.server.requests.append(("GET", self.path))
        if self._redirected():
            return
        body = self.server.objects.get(urllib.parse.unquote(self.path))
        if not self._signed():
            return self._reply(403)
        if body is None:
            return self._reply(404)
        if self.server.corrupt_reads:
            body = body[:-1] + bytes([body[-1] ^ 1])
        self._reply(200, body)

    def do_HEAD(self):
        self.server.requests.append(("HEAD", self.path))
        if self._redirected():
            return
        body = self.server.objects.get(urllib.parse.unquote(self.path))
        if not self._signed():
            return self._reply(403)
        self._reply(404) if body is None else self._reply(200, length=len(body))


def cut_put(fraction):
    """A transport that sends a PUT's real signed headers, then only part of the body, and drops the
    connection, as a network cut or a killed control VM would."""
    def transport(method, url, headers, body):
        if method != "PUT":
            return urllib_transport(method, url, headers, body)
        parts = urllib.parse.urlsplit(url)
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
        conn.putrequest("PUT", parts.path)
        for name, value in headers.items():
            conn.putheader(name, value)
        conn.endheaders()
        conn.send(body[:int(len(body) * fraction)])
        conn.sock.shutdown(2)
        conn.close()
        raise ConnectionResetError("cut")
    return transport


def altered_put(method, url, headers, body):
    if method == "PUT":
        body = body[:-1] + bytes([body[-1] ^ 1])   # corrupted in transit after signing
    return urllib_transport(method, url, headers, body)


class R2Store(unittest.TestCase):
    sealer = AgeSealer()

    def setUp(self):
        self.server = FakeS3()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def objects(self, **kw):
        return R2Objects("acct", "ak", "sk-secret", "bucket", endpoint=self.server.endpoint, **kw)

    def test_round_trip_over_http(self):
        store = SealedStore(self.objects())
        plaintext = os.urandom(3 * 1024 * 1024)
        ref, ct = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, plaintext)
        self.assertFalse(store.exists(CASE, ref))
        with self.assertRaises(ArtifactMissing):
            store.get_sealed(CASE, ref)
        store.put_sealed(CASE, ref, ct)
        self.assertEqual(list(self.server.objects), [f"/bucket/durable/{CASE}/{ref.digest}.case.age"])
        self.assertTrue(store.exists(CASE, ref))
        self.assertEqual(self.sealer.open(CASE_KEY, ref, store.get_sealed(CASE, ref)), plaintext)
        # put = HEAD (absent), PUT, GET read-back.
        self.assertEqual([m for m, _ in self.server.requests[:5]], ["HEAD", "GET", "HEAD", "PUT", "GET"])
        del self.server.requests[:]
        _, again = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, plaintext)
        store.put_sealed(CASE, ref, again)   # first wins: no second PUT
        self.assertEqual([m for m, _ in self.server.requests], ["HEAD"])
        self.assertEqual(store.get_sealed(CASE, ref), ct)

    def test_an_interrupted_upload_is_never_visible(self):
        for fraction in (0.0, 0.5, 0.999):
            self.server.put_done.clear()
            store = SealedStore(self.objects(transport=cut_put(fraction)))
            ref, ct = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, os.urandom(1024 * 1024))
            with self.assertRaises(ArtifactError) as raised:
                store.put_sealed(CASE, ref, ct)
            self.assertEqual(raised.exception.code, "transport_failed")
            self.assertTrue(self.server.put_done.wait(10))
            fresh = SealedStore(self.objects())
            self.assertFalse(fresh.exists(CASE, ref))
            with self.assertRaises(ArtifactMissing):
                fresh.get_sealed(CASE, ref)
            fresh.put_sealed(CASE, ref, ct)   # the retry commits the whole object
            self.assertEqual(fresh.get_sealed(CASE, ref), ct)

    def test_a_body_altered_in_transit_is_refused(self):
        store = SealedStore(self.objects(transport=altered_put))
        ref, ct = self.sealer.seal(CASE_KEY, K.GATE_RECEIPT, b"receipt bytes")
        with self.assertRaises(ArtifactError) as raised:
            store.put_sealed(CASE, ref, ct)
        self.assertEqual(raised.exception.code, "upload_failed")
        self.assertEqual(self.server.objects, {})

    def test_a_read_back_mismatch_fails_the_put(self):
        self.server.corrupt_reads = True
        store = SealedStore(self.objects())
        ref, ct = self.sealer.seal(CASE_KEY, K.GATE_RECEIPT, b"receipt bytes")
        with self.assertRaises(ArtifactError) as raised:
            store.put_sealed(CASE, ref, ct)
        self.assertEqual(raised.exception.code, "upload_unverified")

    def test_unreachable_store_and_credentials(self):
        port = self.server.server_address[1]
        self.server.shutdown(); self.server.server_close()
        store = SealedStore(R2Objects("acct", "ak", "sk-secret", "bucket", endpoint=f"http://127.0.0.1:{port}"))
        ref, ct = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"x")
        with self.assertRaises(ArtifactError) as raised:
            store.put_sealed(CASE, ref, ct)
        self.assertEqual(str(raised.exception), "transport_failed")
        with self.assertRaises(ArtifactError) as raised:
            R2Objects.from_env({"R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "k", "R2_BUCKET": "b"})
        self.assertEqual(str(raised.exception), "r2_credentials_missing")
        made = R2Objects.from_env({"R2_ACCOUNT_ID": "acct", "R2_ACCESS_KEY_ID": "ak",
                                   "R2_SECRET_ACCESS_KEY": "sk-secret", "R2_BUCKET": "bucket"})
        self.assertEqual(made.endpoint, "https://acct.r2.cloudflarestorage.com")
        self.assertNotIn("sk-secret", repr(made))

    def test_put_headers_are_signed_and_conditional(self):
        store = SealedStore(self.objects())
        ref, ct = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"snapshot")
        store.put_sealed(CASE, ref, ct)
        (sent,) = self.server.put_headers
        self.assertEqual(sent["content-type"], "application/octet-stream")
        self.assertEqual(sent["if-none-match"], "*")
        signed = re.search(r"SignedHeaders=([^,]+)", sent["authorization"]).group(1).split(";")
        self.assertEqual(signed, ["content-type", "host", "if-none-match", "x-amz-content-sha256", "x-amz-date"])

    def test_a_wrong_secret_is_refused_by_the_signature_check(self):
        bad = R2Objects("acct", "ak", "not-the-secret", "bucket", endpoint=self.server.endpoint)
        with self.assertRaises(ArtifactError) as raised:
            bad.exists("durable/x")
        self.assertEqual(str(raised.exception), "store_unavailable")

    def test_a_concurrent_writer_keeps_the_first_object(self):
        plaintext = b"same snapshot from two writers"
        ref, mine = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, plaintext)
        _, theirs = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, plaintext)
        key = f"/bucket/durable/{CASE}/{ref.digest}.case.age"

        def racing(method, url, headers, body):
            if method == "PUT":   # the other writer commits between our HEAD and our PUT
                self.server.objects[key] = theirs
            return urllib_transport(method, url, headers, body)
        store = SealedStore(self.objects(transport=racing))
        store.put_sealed(CASE, ref, mine)   # 412: already present, confirmed, kept
        self.assertEqual(self.server.objects[key], theirs)
        self.assertEqual(self.sealer.open(CASE_KEY, ref, store.get_sealed(CASE, ref)), plaintext)

    def test_a_redirect_is_never_followed(self):
        other = FakeS3()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        self.server.redirect_to = f"http://localhost:{other.server_address[1]}"
        objects = self.objects()
        store = SealedStore(objects)
        ref, ct = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, b"x")
        for call, code in ((lambda: store.exists(CASE, ref), "store_unavailable"),
                           (lambda: store.get_sealed(CASE, ref), "download_failed"),
                           (lambda: store.put_sealed(CASE, ref, ct), "store_unavailable")):
            with self.assertRaises(ArtifactError) as raised:
                call()
            self.assertEqual(str(raised.exception), code)
        with mock.patch.object(objects, "exists", return_value=False):   # reach the PUT itself
            with self.assertRaises(ArtifactError) as raised:
                store.put_sealed(CASE, ref, ct)
        self.assertEqual(str(raised.exception), "upload_failed")
        self.assertEqual([m for m, _ in self.server.requests], ["HEAD", "GET", "HEAD", "PUT"])
        self.assertEqual(other.requests, [])   # nothing, signed or not, reached the other host

    def test_requests_carry_no_plaintext_or_key(self):
        seen = []

        def spy(method, url, headers, body):
            seen.append((method, url, dict(headers), body))
            return urllib_transport(method, url, headers, body)
        store = SealedStore(self.objects(transport=spy))
        plaintext = b"private promise text " * 100
        ref, ct = self.sealer.seal(CASE_KEY, K.CASE_SNAPSHOT, plaintext)
        store.put_sealed(CASE, ref, ct)
        for method, url, headers, body in seen:
            blob = (url + repr(headers)).encode() + (body or b"")
            self.assertNotIn(b"private promise", blob)
            self.assertNotIn(b"sk-secret", blob)
            self.assertNotIn(base64.b64encode(CASE_KEY), blob)
            self.assertNotIn(age_identity(derive_keys(CASE_KEY)[0]).encode(), blob)


if __name__ == "__main__":
    unittest.main()
