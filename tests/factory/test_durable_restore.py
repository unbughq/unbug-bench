"""Executable cold restore exercise; opt in with UNBUG_TEST_POSTGRES=1.

Uses a disposable local PG14 cluster, synthetic age keys and local immutable
object storage. Never contacts providers or an existing PostgreSQL service.
"""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "factory"))
from durable.backup import backup, restore, resume, _unpack, _age, _objects
from durable.runtime import Runtime, RuntimeErrorCode
from durable.engine import APP_VERSION
from durable.contract import ArtifactKind, Usage
from durable.ledger import _make_engine
import sqlalchemy as sa
from durable.workers import build_bundle, LABEL_CASE, LABEL_POOL, LABEL_INTENT


class ArchiveSafetyTests(unittest.TestCase):
    def test_remote_snapshot_reads_all_pages_and_refuses_incomplete_inventory(self):
        from durable.artifacts import R2Objects
        objects = R2Objects("synthetic", "synthetic", "synthetic", "synthetic")
        calls = []
        def transport(method, url, headers, body):
            calls.append(url)
            token = "continuation-token" in url
            payload = ("<ListBucketResult xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\">"
                       "<Contents><Key>durable/b-test/" + ("two" if token else "one") + "</Key></Contents>"
                       "<IsTruncated>" + ("false" if token else "true") + "</IsTruncated>"
                       "<NextContinuationToken>next</NextContinuationToken></ListBucketResult>")
            return 200, {}, payload.encode()
        objects._transport = transport
        with patch("durable.backup.objects_for", return_value=objects), patch.object(objects, "get", side_effect=AssertionError("remote data must not be downloaded during backup")):
            self.assertEqual(_objects({"r2": {}}), {"b-test/one": None, "b-test/two": None})
            self.assertEqual(len(calls), 2)
            objects._transport = lambda *args: (200, {}, b"<invalid/>")
            with self.assertRaises(RuntimeErrorCode):
                _objects({"r2": {}})

    def test_unsafe_and_duplicate_members_refused(self):
        for name in ("../escape", "/escape", "pool/../../escape", "pool//record"):
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w") as archive:
                info = tarfile.TarInfo(name)
                archive.addfile(info, io.BytesIO())
            with self.assertRaises(RuntimeErrorCode):
                _unpack(data.getvalue())
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as archive:
            for _ in range(2):
                archive.addfile(tarfile.TarInfo("database.dump"), io.BytesIO())
        with self.assertRaises(RuntimeErrorCode):
            _unpack(data.getvalue())


@unittest.skipUnless(os.environ.get("UNBUG_TEST_POSTGRES") == "1", "explicit disposable PostgreSQL exercise")
class RestoreExercise(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ub-r-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pg = Path(os.environ.get("UNBUG_TEST_PG_BIN", "/opt/homebrew/bin"))
        self.env = {**os.environ, "PATH": str(self.pg) + os.pathsep + os.environ["PATH"]}
        self.patch_env = patch.dict(os.environ, self.env)
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)
        self.run_pg("initdb", "-D", str(self.root / "pg"), "-A", "trust", "--no-locale", "--encoding=UTF8")
        self.run_pg("pg_ctl", "-D", str(self.root / "pg"), "-l", str(self.root / "pg.log"), "-o",
                    "-k " + str(self.root) + " -c listen_addresses=" + chr(39) * 2, "-w", "start")
        self.addCleanup(lambda: self.run_pg("pg_ctl", "-D", str(self.root / "pg"), "-m", "immediate", "-w", "stop"))
        for database in ("source", "destination", "refused"):
            self.run_pg("createdb", "-h", str(self.root), database)
        identity = self.root / "identity"
        subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
        identity.chmod(0o600)
        recipient = subprocess.run(["age-keygen", "-y", str(identity)], check=True, capture_output=True).stdout.decode().strip()
        self.config = dict(database_url=self.url("source"), state_dir=str(self.root / "source"),
                           pool_id="restore-test", application_version=APP_VERSION,
                           restore_identity=str(identity), restore_recipient=recipient,
                           founder_recipient=recipient, local_objects=str(self.root / "objects"))
        founder = self.root / "founder"
        subprocess.run(["age-keygen", "-o", str(founder)], check=True, capture_output=True)
        founder.chmod(0o600)
        self.config["founder_recipient"] = subprocess.run(["age-keygen", "-y", str(founder)], check=True, capture_output=True).stdout.decode().strip()
        self.destination = {**self.config, "database_url": self.url("destination"),
                            "state_dir": str(self.root / "destination"),
                            "local_objects": str(self.root / "recovered-objects")}

    def run_pg(self, name, *args):
        subprocess.run([str(self.pg / name), *args], check=True, capture_output=True, env=self.env)

    def url(self, database):
        return "postgresql:///" + database + "?host=" + str(self.root)

    def test_restore_usage_artifacts_pins_and_worker_ownership(self):
        runtime = Runtime(self.config)
        runtime.ledger.open("b-restore", 1000)
        runtime.ledger.reserve("b-restore", "case-restored", "case-restored/1/writer/1", 200, 600)
        runtime.ledger.reserve("b-restore", "case-restored", "case-restored/1/gates/1", 100, 600)
        runtime.ledger.settle("case-restored/1/gates/1", Usage(2, 60, 80))
        balance = runtime.ledger.balance("b-restore")
        unused_key = runtime.keys.scope_key("case-restored")
        ref = runtime.prepare("b-restore", ArtifactKind.INPUTS, b"synthetic evidence")
        bundle = runtime.releases.put_bundle(build_bundle(ROOT))
        runtime.releases.register_bench("a" * 64, "bench-env")
        record = {"intent": "synthetic-intent", "worker": "bx_12345678", "deleting": None}
        runtime.pool._write("case-restored", record)
        with self.assertRaises(RuntimeErrorCode):
            backup(self.config)
        runtime.close()
        scheduled = backup(self.config, resume_after=True)
        self.assertFalse(scheduled["source_fenced"])
        fence = Path(self.config["state_dir"]) / "cold-backup.json"
        self.assertFalse(fence.exists())
        with patch("durable.backup._pg", side_effect=RuntimeErrorCode("injected_backup_failure")):
            with self.assertRaises(RuntimeErrorCode):
                backup(self.config, resume_after=True)
        self.assertFalse(fence.exists())
        stale = backup(self.config)
        operator_fence = fence.read_bytes()
        with self.assertRaises(RuntimeErrorCode):
            backup(self.config, resume_after=True)
        self.assertEqual(fence.read_bytes(), operator_fence)
        stale_archive = self.root / "stale.age"
        stale_archive.write_bytes(Path(self.config["local_objects"], stale["backup"]).read_bytes())
        stale_archive.chmod(0o600)
        resume(self.config)
        with self.assertRaises(RuntimeErrorCode):
            restore({**self.destination, "state_dir": str(self.root / "stale-destination")}, stale_archive, self.config["state_dir"])
        result = backup(self.config)
        archive = self.root / "backup.age"
        archive.write_bytes(Path(self.config["local_objects"], result["backup"]).read_bytes())
        archive.chmod(0o600)
        with self.assertRaises(RuntimeErrorCode):
            Runtime(self.config)
        wrong = {**self.destination, "application_version": "wrong"}
        with self.assertRaises(RuntimeErrorCode):
            restore(wrong, archive, self.config["state_dir"])
        bad = self.root / "bad.age"
        bad.write_bytes(archive.read_bytes()[:-20]); bad.chmod(0o600)
        with self.assertRaises(RuntimeErrorCode):
            restore(self.destination, bad, self.config["state_dir"])
        self.assertFalse(Path(self.destination["state_dir"]).exists())
        with self.assertRaises(RuntimeErrorCode):
            restore({**self.destination, "restore_identity": str(self.root / "founder")}, archive, self.config["state_dir"])
        manifest, members = _unpack(_age(self.config, archive.read_bytes(), decrypt=True))
        members["manifest.json"] = json.dumps(manifest).encode()
        members.pop("database.dump")
        incomplete = io.BytesIO()
        with tarfile.open(fileobj=incomplete, mode="w") as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name); info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        with self.assertRaises(RuntimeErrorCode):
            _unpack(incomplete.getvalue())
        # Matching ciphertext is decryptable by the separate founder recipient.
        subprocess.run(["age", "-d", "-i", str(self.root / "founder")], input=archive.read_bytes(), check=True, capture_output=True)
        engine = _make_engine(self.destination["database_url"])
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE must_survive (id integer)"))
        with self.assertRaises(RuntimeErrorCode):
            restore({**self.destination, "state_dir": str(self.root / "populated-refusal")}, archive, self.config["state_dir"])
        with engine.begin() as conn:
            self.assertEqual(conn.execute(sa.text("SELECT count(*) FROM must_survive")).scalar(), 0)
            conn.execute(sa.text("DROP TABLE must_survive"))
        engine.dispose()
        restore(self.destination, archive, self.config["state_dir"])
        recovered = Runtime(self.destination)
        self.addCleanup(recovered.close)
        self.assertEqual(recovered.ledger.balance("b-restore"), balance)
        self.assertEqual(recovered.keys.scope_key("case-restored"), unused_key)
        self.assertEqual(recovered.pool._read("case-restored"), record)
        self.assertEqual(recovered.releases.bundle(bundle), runtime.releases.bundle(bundle))
        self.assertEqual(recovered.releases.image_for("a" * 64, "unused"), "bench-env")
        self.assertEqual(recovered.sealer.open(recovered.keys.scope_key("b-restore"), ref,
                         recovered.store.get_sealed("b-restore", ref)), b"synthetic evidence")
        # The running old worker retains its reservation; settlement stays idempotent.
        recovered.ledger.settle("case-restored/1/writer/1", Usage(3, 120, 150))
        recovered.ledger.settle("case-restored/1/writer/1", Usage(3, 120, 150))
        labels = {LABEL_POOL: "restore-test", LABEL_CASE: "case-newer", LABEL_INTENT: "new"}
        with patch.object(recovered.pool, "_inventory", return_value=[{"id": "bx_87654321", "labels": labels}]), patch.object(recovered.pool, "recover") as recover:
            with self.assertRaises(RuntimeErrorCode):
                recovered.launch()
            recover.assert_not_called()
        owned_labels = {LABEL_POOL: "restore-test", LABEL_CASE: "case-restored", LABEL_INTENT: "synthetic-intent"}
        from durable.workers import LIVE_STATES
        owned = {"id": "bx_12345678", "labels": owned_labels, "state": sorted(LIVE_STATES)[0]}
        with patch.object(recovered.pool, "_inventory", return_value=[owned]), patch.object(recovered.pool, "recover") as orphan_cleanup, patch.object(recovered.engine, "launch") as launch:
            recovered.launch()
            launch.assert_called_once()
            orphan_cleanup.assert_not_called()
        recovered.launched = False
        self.assertEqual(recovered.pool._read("case-restored"), record)
        with self.assertRaises(RuntimeErrorCode):
            restore(self.destination, archive, self.config["state_dir"])
        with self.assertRaises(RuntimeErrorCode):
            resume(self.config)
        # A lost source may be recovered as data, without creating a second controller.
        quarantine = {**self.destination, "database_url": self.url("refused"),
                      "state_dir": str(self.root / "quarantined"),
                      "local_objects": str(self.root / "quarantined-objects")}
        restored = restore(quarantine, archive, str(self.root / "lost-source"), quarantine=True)
        self.assertTrue(restored["quarantined"])
        with self.assertRaisesRegex(RuntimeErrorCode, "source_fenced"):
            Runtime(quarantine)
        with self.assertRaisesRegex(RuntimeErrorCode, "source_retired"):
            resume(quarantine)
        for path in Path(self.destination["state_dir"]).rglob("*"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)


if __name__ == "__main__":
    unittest.main()
