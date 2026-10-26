#!/usr/bin/env python3
"""Bench-owned reset/oracle. Read actual SQLite bytes with the HOST's trusted Python."""
import json, pathlib, sqlite3, subprocess, sys, tempfile

action, name, compose = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
assert action in ("reset", "check")

def command(args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True)
    if result.returncode: raise RuntimeError(result.stderr)
    return result.stdout.strip()

if action == "reset":
    command(compose + ["exec", "-T", name, "/usr/local/bin/python", "-I", "-"],
        "import sqlite3\nwith sqlite3.connect('/data/marketplace.sqlite') as db: db.execute('DELETE FROM orders')\n")
# Traffic has finished and this channel has no background writers/WAL. Copy the
# quiescent ledger, then read using host SQLite, independent of the runtime image.
with tempfile.TemporaryDirectory(prefix="unbug-marketplace-check-") as temporary:
    path = pathlib.Path(temporary) / "ledger.sqlite"
    command(compose + ["exec", "-T", "-u", "0", name, "/usr/bin/test", "!", "-L", "/data/marketplace.sqlite"])
    # Docker cp cannot see tmpfs on Docker Desktop. The image/root filesystem is
    # immutable; /bin/cat transports bytes only, with no runtime Python imports.
    result = subprocess.run(compose + ["exec", "-T", "-u", "0", name, "/bin/cat", "/data/marketplace.sqlite"], capture_output=True)
    if result.returncode: raise RuntimeError(result.stderr.decode())
    path.write_bytes(result.stdout)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        assert db.execute("SELECT type FROM sqlite_master WHERE name='orders'").fetchone() == ("table",)
        rows = db.execute("SELECT id, kit, quantity FROM orders").fetchall()
        # Frozen catalog mapping/factor, independent of patched code and its cache.
        assert all(type(oid) is int and oid > 0 and kit == "s" and type(q) is int and q > 0 for oid, kit, q in rows), rows
        assert len({oid for oid, _, _ in rows}) == len(rows), "duplicate order IDs"
        print(json.dumps({"orders": {"marketplace-" + str(oid): {"units": {kit: q}, "canceled": False} for oid, kit, q in rows}}))
