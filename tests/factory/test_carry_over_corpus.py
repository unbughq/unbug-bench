"""Every locally collected real scorecard and portable real-card fixtures."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("carry_over_corpus", ROOT / "tools/carry-over-corpus.py")
corpus = importlib.util.module_from_spec(spec); spec.loader.exec_module(corpus)


class CorpusTests(unittest.TestCase):
    def test_every_real_scorecard_has_a_complete_disposition(self):
        files = corpus.paths(ROOT, ROOT.parent)
        # Packaged tests also cover real fixtures when collections aren't installed.
        files += sorted((ROOT / "tests/factory/fixtures").glob("*-collected-card.json"))
        self.assertTrue(files)
        rows = []
        for path in files:
            before = path.read_bytes()
            row = corpus.inspect(path)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(row["status"] == "MIGRATED", row["admitted"])
            if row["status"] == "REFUSED": self.assertTrue(row["reasons"], path)
            else: self.assertEqual(row["state_version"], corpus.carry_over.STATE_VERSION)
            self.assertIn("source_sha256", row)
            rows.append(row)
        print(corpus.table(rows), end="", flush=True)

    def test_unknown_fields_are_explicitly_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input-scorecard.json"
            path.write_text(json.dumps({"case": "case-future", "unknown": {"secret": "never displayed"}}))
            row = corpus.inspect(path)
            self.assertEqual(row["status"], "REFUSED")
            self.assertIn("unclassified scorecard fields", row["reasons"][0])
            self.assertNotIn("never displayed", json.dumps(row))


if __name__ == "__main__": unittest.main()
