"""Offline composition checks; SQLite is not PostgreSQL qualification."""
import base64
from contextlib import nullcontext
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "factory"))
from durable.runtime import Runtime, RuntimeErrorCode, private_bytes, load_config
from durable.engine import APP_VERSION
from durable.artifacts import AgeSealer, LocalObjects
from durable.contract import ArtifactKind, Ref, BatchSpec, to_record
from durable.cli import dispatch, backup, main


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        identity = self.root / "identity"
        subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
        identity.chmod(0o600)
        recipient = subprocess.run(["age-keygen", "-y", str(identity)], check=True, capture_output=True).stdout.decode().strip()
        self.config = dict(database_url="sqlite:///" + str(self.root / "db"),
                           state_dir=str(self.root / "state"), pool_id="offline",
                           restore_identity=str(identity), restore_recipient=recipient,
                           founder_recipient=recipient, local_objects=str(self.root / "objects"),
                           application_version=APP_VERSION)

    def runtime(self):
        runtime = Runtime(self.config)
        self.addCleanup(runtime.close)
        return runtime

    def test_real_composition_exports_recoverable_scope_key(self):
        runtime = self.runtime()
        self.assertEqual(runtime.channel.output_retry_s, 60)
        ref = runtime.prepare("b-offline", ArtifactKind.INPUTS, b"opaque secret inputs")
        wrapped = runtime.store.objects.get("durable/b-offline/scope-key.age")
        opened = subprocess.run(["age", "-d", "-i", self.config["restore_identity"]], input=wrapped, check=True, capture_output=True).stdout
        key = base64.b64decode(opened.strip().split()[-1])
        self.assertEqual(AgeSealer().open(key, ref, runtime.store.get_sealed("b-offline", ref)), b"opaque secret inputs")
        self.assertNotIn(b"opaque secret inputs", runtime.store.get_sealed("b-offline", ref))
        self.assertIs(runtime.executor.ledger, runtime.ledger)
        self.assertIs(runtime.channel.keys, runtime.keys)

    def test_export_failure_prevents_artifact_acknowledgment(self):
        runtime = self.runtime()
        with patch.object(runtime.store.objects, "put", side_effect=OSError("secret")):
            with self.assertRaises(OSError):
                runtime.prepare("b-offline", ArtifactKind.INPUTS, b"secret")
        self.assertEqual(list((self.root / "objects").glob("**/*.inputs.age")), [])

    def test_recovery_precedes_launch_and_failure_retains_journal(self):
        runtime = self.runtime()
        record = runtime.pool.state / "case-one.json"
        record.write_text("ownership")
        with patch.object(runtime.pool, "recover", side_effect=ValueError("transport")), patch.object(runtime.engine, "launch") as launch:
            with self.assertRaises(ValueError):
                runtime.launch()
            launch.assert_not_called()
        self.assertEqual(record.read_text(), "ownership")
        order = []
        with patch.object(runtime.pool, "recover", side_effect=lambda: order.append("recover")), patch.object(runtime.engine, "launch", side_effect=lambda: order.append("launch")):
            runtime.launch()
        runtime.launched = False
        self.assertEqual(order, ["recover", "launch"])

    def test_real_recover_inventory_failure_keeps_ownership(self):
        runtime = self.runtime()
        runtime.pool._write("case-one", dict(worker="bx_12345678", intent=None, deleting=None))
        path = runtime.pool._record_path("case-one")
        original = path.read_bytes()
        with patch.object(runtime.pool.boat, "run", return_value=(1, b"")), patch.object(runtime.engine, "launch") as launch:
            with self.assertRaises(Exception):
                runtime.launch()
            launch.assert_not_called()
        self.assertEqual(path.read_bytes(), original)

    def test_real_recover_empty_inventory_before_launch(self):
        runtime = self.runtime()
        with patch.object(runtime.pool.boat, "run", return_value=(0, b'{"sandboxes": [], "pageInfo": {"hasMore": false}}')) as transport, patch.object(runtime.engine, "launch") as launch:
            runtime.launch()
            transport.assert_called()
            launch.assert_called_once()
        runtime.launched = False

    def test_opaque_start_records_only_refs(self):
        runtime = self.runtime()
        inputs = runtime.prepare("b-offline", ArtifactKind.INPUTS, b"arbitrary admission payload")
        registry = runtime.prepare("b-offline", ArtifactKind.STATEMENT_REGISTRY, b"opaque registry")
        spec = BatchSpec(batch_id="b-offline", plumbing_version="a" * 64,
                         bench_version="b" * 64, app_repo="medusajs/medusa", app_commit="c" * 40,
                         inputs=inputs, target_sealed=1, money_bound_usd_micros=100,
                         deadline_epoch=4e9, max_concurrency=1)
        with patch.object(runtime.releases, "bundle", return_value=b"bundle"), patch.object(runtime.engine, "start_batch") as start:
            self.assertEqual(runtime.start(to_record(spec), to_record(registry)), {"batch_id": "b-offline"})
            start.assert_called_once_with(spec, registry)
            self.assertNotIn("arbitrary admission payload", repr(start.call_args))

    def test_private_socket_client_prepare(self):
        import socketserver
        import threading
        from durable.cli import Handler
        runtime = self.runtime()
        config_path = self.root / "config"
        config_path.write_text("{}")
        config_path.chmod(0o600)
        content_path = self.root / "content"
        content_path.write_bytes(b"opaque socket payload")
        content_path.chmod(0o600)
        with socketserver.UnixStreamServer(str(runtime.state / "operator.sock"), Handler) as server:
            server.runtime = runtime
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            try:
                with patch("durable.cli.load_config", return_value=self.config), patch("sys.stdout", new_callable=io.StringIO) as output:
                    self.assertEqual(main(["--config", str(config_path), "prepare", "b-offline", "registry", str(content_path)]), 0)
                    record = json.loads(output.getvalue())
                    self.assertEqual(record["kind"], "registry")
                    self.assertNotIn("opaque socket payload", output.getvalue())
            finally:
                thread.join(timeout=5)
        self.assertEqual(runtime.sealer.open(runtime.keys.scope_key("b-offline"), Ref(**record), runtime.store.get_sealed("b-offline", Ref(**record))), b"opaque socket payload")

    def test_second_owner_rejected(self):
        self.runtime()
        with self.assertRaises(RuntimeErrorCode):
            Runtime(self.config)

    def test_explicit_configuration_and_dsn_sources(self):
        path = self.root / "config.json"
        dsn = self.root / "dsn"
        dsn.write_text("postgresql://user:private@localhost/factory\n")
        dsn.chmod(0o600)
        path.write_text(json.dumps({"database_url_file": str(dsn)}))
        path.chmod(0o600)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_config(path)["database_url"], dsn.read_text().strip())
        with patch.dict(os.environ, {"UNBUG_DURABLE_DSN": "postgresql://localhost/override"}):
            self.assertEqual(load_config(path)["database_url"], "postgresql://localhost/override")
        self.config["application_version"] = "wrong"
        with self.assertRaises(RuntimeErrorCode):
            Runtime(self.config)
        self.assertFalse((self.root / "state").exists())

    def test_private_files_and_symlinks(self):
        path = self.root / "secret"
        path.write_bytes(b"secret")
        path.chmod(0o644)
        with self.assertRaises(RuntimeErrorCode):
            private_bytes(path)
        path.chmod(0o600)
        self.assertEqual(private_bytes(path), b"secret")
        link = self.root / "link"
        link.symlink_to(path)
        with self.assertRaises(OSError):
            private_bytes(link)

    def test_four_messages_and_report_dispatch(self):
        runtime = Mock()
        for op, payload in (("bench_release", {"bench_version": "a" * 64}),
                            ("plumbing_release", {"plumbing_version": "b" * 64}),
                            ("bound_raised", {"money_bound_usd_micros": 123}),
                            ("founder_reply", {"action": "retire", "ruling": None})):
            dispatch(runtime, dict(op=op, destination="case-one" if op == "founder_reply" else "b-offline", payload=payload))
        self.assertEqual(runtime.engine.send.call_count, 3)
        runtime.engine.reply.assert_called_once()

    def test_cli_sanitizes_secret_failure(self):
        with patch("durable.cli.load_config", side_effect=ValueError("secret content")), patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(main(["--config", "unused", "status", "b-offline"]), 1)
            self.assertEqual(err.getvalue(), "durable_operator_failed\n")

    def test_encrypted_backup_uses_existing_objects_and_no_dsn_argv(self):
        self.config["database_url"] = "postgresql://operator:secret@localhost/factory"
        real_run = subprocess.run
        def run(argv, **kwargs):
            if argv[0] == "pg_dump":
                self.assertEqual(argv, ["pg_dump", "--format=custom"])
                self.assertEqual(kwargs["env"]["PGPASSWORD"], "secret")
                return subprocess.CompletedProcess(argv, 0, stdout=b"database plaintext")
            return real_run(argv, **kwargs)
        with patch("durable.backup.subprocess.run", side_effect=run), patch("durable.backup.database_lock", return_value=nullcontext()):
            result = backup(self.config)
        data = LocalObjects(self.config["local_objects"]).get(result["backup"])
        self.assertTrue(data.startswith(b"age-encryption.org/v1"))
        self.assertNotIn(b"database plaintext", data)
        opened = real_run(["age", "-d", "-i", self.config["restore_identity"]], input=data, capture_output=True, check=True).stdout
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(opened)) as archive:
            self.assertEqual(archive.extractfile("database.dump").read(), b"database plaintext")


if __name__ == "__main__":
    unittest.main()
