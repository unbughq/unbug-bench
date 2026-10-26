"""Fingerprint the selected seed input independently of its host location."""
import hashlib
import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'bin'))

spec = importlib.util.spec_from_file_location("bench_fingerprint_test", pathlib.Path(__file__).resolve().parents[2] / "bin/bench.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class FingerprintTests(unittest.TestCase):
    def test_slot_ids_without_default_path_and_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for name in ("factory/case_permissions.py", "cases/medusa-oversell/checker/check.sql", "cases/medusa-oversell/traffic/run.mjs", "bin/bench.py", "bin/bench_judging.py", "bin/refusal.py"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            (root / "projects/medusa").mkdir(parents=True)
            ids = root / "results/factory-slots/97/seed-ids.json"
            ids.parent.mkdir(parents=True)
            ids.write_text('{"admin":"selected-slot"}')
            with mock.patch.multiple(bench, ROOT=root, IDS=ids):
                first = bench.bench_fingerprint()
                self.assertEqual(first["projects/medusa/seed-ids.json"], hashlib.sha256(ids.read_bytes()).hexdigest())
                equivalent = root / "elsewhere/seed-ids.json"
                equivalent.parent.mkdir()
                equivalent.write_bytes(ids.read_bytes())
                with mock.patch.object(bench, "IDS", equivalent):
                    self.assertEqual(first, bench.bench_fingerprint())
                rules = root / "bin/bench_judging.py"
                before = rules.read_bytes()
                rules.write_bytes(before + b"\n# changed verdict rule\n")
                self.assertNotEqual(first, bench.bench_fingerprint())
                rules.write_bytes(before)
                ids.write_text('{"admin":"changed-slot"}')
                self.assertNotEqual(first, bench.bench_fingerprint())
                ids.unlink()
                with self.assertRaises(FileNotFoundError):
                    bench.bench_fingerprint()


if __name__ == "__main__":
    unittest.main()
