"""WP7: the key service (docs/designs/durable-execution-wp7.md), with the real `age` and
`age-keygen` CLIs and real SQLite through SQLAlchemy (installed by dbos==3.4.0).

Every identity here is a throwaway made by age-keygen in a temporary directory. No real
founder or VM key is read or touched.

Done when (wave-1 brief and the task for WP7):
- a key never appears in any record, log or exception text the service produces;
- the same scope returns the same key after a restart;
- a wrapped key opens with the restore identity and the founder identity, and not with an
  unrelated one.
"""
import base64
from contextlib import closing
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "factory")]

from durable.contract import derive_keys             # noqa: E402
from durable.keys import AgeKeyService, KeyServiceError, recipients_from_repo   # noqa: E402

if not (shutil.which("age") and shutil.which("age-keygen")):
    raise SystemExit("age and age-keygen are required (apt-get install age)")


def keygen(path: Path) -> str:
    subprocess.run(["age-keygen", "-o", str(path)], check=True, capture_output=True)
    os.chmod(path, 0o600)
    return subprocess.run(["age-keygen", "-y", str(path)], check=True, capture_output=True, text=True).stdout.strip()


# Bech32 (BIP 173), to scan for a derived secret in its age identity form "AGE-SECRET-KEY-1...".
_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    gen = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def age_identity(secret: bytes) -> str:
    hrp = "age-secret-key-"
    acc = bits = 0
    data = []
    for b in secret:
        acc = (acc << 8) | b; bits += 8
        while bits >= 5:
            bits -= 5; data.append((acc >> bits) & 31)
    if bits:
        data.append((acc << (5 - bits)) & 31)
    expanded = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    pm = _polymod(expanded + data + [0] * 6) ^ 1
    data += [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return (hrp + "1" + "".join(_CHARSET[d] for d in data)).upper()


def forms(key: bytes):
    """Every encoding of a scope key, and of both secrets derived from it, worth scanning for."""
    age_secret, hmac_key = derive_keys(key)
    out = []
    for raw in (key, age_secret, hmac_key):
        out += [raw, raw.hex().encode(), raw.hex().upper().encode(), base64.b64encode(raw),
                base64.urlsafe_b64encode(raw), base64.b64encode(raw).rstrip(b"=")]
    out.append(age_identity(age_secret).encode())
    out.append(age_identity(age_secret).lower().encode())
    return out


class Keys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.restore_id, self.founder_id, self.other_id = (self.dir / n for n in ("restore.key", "founder.key",
                                                                                   "other.key"))
        self.restore, self.founder, self.other = keygen(self.restore_id), keygen(self.founder_id), keygen(self.other_id)
        self.url = f"sqlite:///{self.dir}/engine.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def service(self, identity=None, restore=None):
        return AgeKeyService(self.url, restore_recipient=restore or self.restore, founder_recipient=self.founder,
                             restore_identity=identity or self.restore_id)

    def stored(self, scope):
        with closing(sqlite3.connect(self.dir / "engine.sqlite")) as db, db:
            return db.execute("SELECT wrapped FROM durable_scope_key WHERE scope = ?", (scope,)).fetchone()[0]

    def test_same_scope_same_key_after_restart(self):
        first = self.service()
        a, b, batch = first.scope_key("case-a"), first.scope_key("case-b"), first.scope_key("b-keys-test")
        for k in (a, b, batch):
            self.assertIs(type(k), bytes)
            self.assertEqual(len(k), 32)
        self.assertEqual(len({a, b, batch}), 3)
        self.assertEqual(first.scope_key("case-a"), a)
        first.close()
        restarted = self.service()       # a new process on the same database: nothing in memory
        self.assertEqual((restarted.scope_key("case-a"), restarted.scope_key("case-b"),
                          restarted.scope_key("b-keys-test")), (a, b, batch))
        with closing(sqlite3.connect(self.dir / "engine.sqlite")) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM durable_scope_key").fetchone()[0], 3)
        restarted.close()

    def test_wrapped_key_opens_with_either_recipient_and_not_another(self):
        svc = self.service()
        key = svc.scope_key("case-a")
        wrapped = self.stored("case-a")
        self.assertEqual(svc.wrapped_key("case-a"), wrapped)
        self.assertTrue(wrapped.startswith(b"age-encryption.org/v1\n"))
        self.assertEqual(wrapped.count(b"\n-> X25519 "), 2)      # exactly two recipient stanzas
        for identity in (self.restore_id, self.founder_id):
            line = subprocess.run(["age", "-d", "-i", str(identity)], input=wrapped, capture_output=True,
                                  check=True).stdout
            self.assertEqual(line, b"unbug-durable/scope-key/v1 case-a " + base64.b64encode(key) + b"\n")
        refused = subprocess.run(["age", "-d", "-i", str(self.other_id)], input=wrapped, capture_output=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(refused.stdout, b"")
        svc.close()

    def test_no_key_in_any_record_log_or_exception(self):
        log = io.StringIO()
        handler = logging.StreamHandler(log)
        root = logging.getLogger()
        root.addHandler(handler); old_level = root.level; root.setLevel(logging.DEBUG)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.DEBUG)   # every SQL statement and parameter
        errors = []

        def expect_error(fn):
            try:
                fn()
            except KeyServiceError as e:
                errors.append("".join(traceback.format_exception(e)) + repr(e) + str(e))
            else:
                self.fail("expected KeyServiceError")
        try:
            svc = self.service()
            keys = [svc.scope_key(s) for s in ("case-a", "case-b", "b-keys-test")]
            svc.scope_key("case-a")
            texts = [repr(svc)]
            # Error paths: a wrong identity, an unsafe identity file, a bad scope, a wrapped key
            # filed under another scope, a corrupted wrapped key, and a missing age binary.
            expect_error(lambda: self.service(identity=self.founder_id))
            loose = self.dir / "loose.key"
            shutil.copy(self.restore_id, loose); os.chmod(loose, 0o644)
            expect_error(lambda: self.service(identity=loose))
            expect_error(lambda: svc.scope_key("../case-a"))
            expect_error(lambda: svc.wrapped_key("case-none"))
            with closing(sqlite3.connect(self.dir / "engine.sqlite")) as db, db:
                db.execute("INSERT INTO durable_scope_key VALUES ('case-swapped', ?)", (self.stored("case-a"),))
                db.execute("INSERT INTO durable_scope_key VALUES ('case-corrupt', ?)",
                           (self.stored("case-b")[:-40] + b"\0" * 40,))
            fresh = self.service()
            expect_error(lambda: fresh.scope_key("case-swapped"))
            expect_error(lambda: fresh.scope_key("case-corrupt"))
            path = os.environ["PATH"]
            os.environ["PATH"] = str(self.dir / "no-such-bin")
            try:
                expect_error(lambda: fresh.scope_key("case-new"))
            finally:
                os.environ["PATH"] = path
            texts.append(repr(fresh))
            svc.close(); fresh.close()
        finally:
            root.removeHandler(handler); root.setLevel(old_level)
            logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
        self.assertEqual(len(errors), 7)
        self.assertIn("INSERT INTO durable_scope_key", log.getvalue())     # the log really was captured
        blobs = [log.getvalue().encode(), *(e.encode() for e in errors), *(t.encode() for t in texts)]
        with closing(sqlite3.connect(self.dir / "engine.sqlite")) as db, db:
            blobs += [repr(row).encode() for row in db.execute("SELECT * FROM durable_scope_key")]
        blobs += [p.read_bytes() for p in self.dir.rglob("*") if p.is_file()]   # the raw database file, too
        for k in keys:
            for f in forms(k):
                for blob in blobs:
                    self.assertNotIn(f, blob)

    def test_concurrent_first_use_agrees_on_one_key(self):
        self.service().close()           # tables exist before the processes race
        program = textwrap.dedent('''
            import hashlib, json, pathlib, sys, time
            sys.path.insert(0, sys.argv[1])
            from durable.keys import AgeKeyService
            url, restore, founder, ident, go = sys.argv[2:7]
            svc = AgeKeyService(url, restore_recipient=restore, founder_recipient=founder, restore_identity=ident)
            while not pathlib.Path(go).exists():
                time.sleep(0.001)
            print(json.dumps([hashlib.sha256(svc.scope_key(f"case-r{i}")).hexdigest() for i in range(6)]))
        ''')
        go = self.dir / "go"
        procs = [subprocess.Popen([sys.executable, "-B", "-c", program, str(ROOT / "factory"), self.url,
                                   self.restore, self.founder, str(self.restore_id), str(go)],
                                  stdout=subprocess.PIPE, text=True) for _ in range(4)]
        time.sleep(1.0)
        go.touch()
        outs = [json.loads(p.communicate(timeout=120)[0]) for p in procs]
        self.assertTrue(all(p.returncode == 0 for p in procs))
        for out in outs[1:]:
            self.assertEqual(out, outs[0])
        svc = self.service()
        self.assertEqual([hashlib.sha256(svc.scope_key(f"case-r{i}")).hexdigest() for i in range(6)], outs[0])
        with closing(sqlite3.connect(self.dir / "engine.sqlite")) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM durable_scope_key").fetchone()[0], 6)
        svc.close()

    def test_construction_checks(self):
        with self.assertRaises(KeyServiceError):
            self.service(restore="not-a-recipient")
        link = self.dir / "link.key"
        link.symlink_to(self.restore_id)
        with self.assertRaises(KeyServiceError):
            self.service(identity=link)
        with self.assertRaises(KeyServiceError):
            self.service(identity=self.dir / "missing.key")

    def test_recipients_from_repo_reads_the_tracked_public_keys(self):
        restore, founder = recipients_from_repo(ROOT)
        self.assertEqual(restore, (ROOT / "factory/control-recipient.txt").read_text().strip())
        self.assertIn(f'FOUNDER_RECIPIENT = "{founder}"', (ROOT / "factory/run.py").read_text())


if __name__ == "__main__":
    unittest.main()
