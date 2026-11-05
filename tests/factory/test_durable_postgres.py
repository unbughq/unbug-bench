"""First-use races against a disposable PostgreSQL database, when explicitly configured."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "factory"))
from durable.ledger import SqlLedger
from durable.keys import AgeKeyService


@unittest.skipUnless(os.environ.get("DURABLE_LEDGER_PG_URL"), "disposable PostgreSQL URL not configured")
class FirstUse(unittest.TestCase):
    def setUp(self):
        self.schema = "durable_test_" + uuid.uuid4().hex
        self.admin = sa.create_engine(os.environ["DURABLE_LEDGER_PG_URL"])
        with self.admin.begin() as conn:
            conn.exec_driver_sql(f"CREATE SCHEMA {self.schema}")
        url = self.admin.url.update_query_dict({"options": f"-csearch_path={self.schema}"})
        self.url = url.render_as_string(hide_password=False)

    def tearDown(self):
        with self.admin.begin() as conn:
            conn.exec_driver_sql(f"DROP SCHEMA {self.schema} CASCADE")
        self.admin.dispose()

    def concurrent(self, fn):
        barrier = threading.Barrier(8)
        def run(n):
            barrier.wait(timeout=30)
            return fn(n)
        with ThreadPoolExecutor(8) as pool:
            return list(pool.map(run, range(1, 9)))

    def test_fresh_ledger_schema_and_concurrent_first_open(self):
        def open_batch(bound):
            ledger = SqlLedger(self.url)
            try:
                ledger.open("b-first-use", bound)
            finally:
                ledger.close()
        self.concurrent(open_batch)
        ledger = SqlLedger(self.url)
        try:
            self.assertEqual(ledger.balance("b-first-use")["bound"], 8)
        finally:
            ledger.close()

    def test_fresh_key_schema_and_concurrent_first_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            identity = Path(directory) / "restore.key"
            subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
            identity.chmod(0o600)
            recipient = subprocess.check_output(["age-keygen", "-y", str(identity)], text=True).strip()
            def create_key(_):
                service = AgeKeyService(self.url, restore_recipient=recipient,
                                        founder_recipient=recipient, restore_identity=identity)
                try:
                    return service.scope_key("case-first-use")
                finally:
                    service.close()
            keys = self.concurrent(create_key)
            self.assertEqual(len(set(keys)), 1)
            self.assertEqual(len(keys[0]), 32)


if __name__ == "__main__":
    unittest.main()
