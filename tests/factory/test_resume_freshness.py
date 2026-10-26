"""Saved public matches reach G2 without another expensive build pass."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch
import run

class ResumeFreshnessTests(unittest.TestCase):
    def test_flagged_saved_case_defers_build_but_clean_case_does_not(self):
        for flagged in (True, False):
            with self.subTest(flagged=flagged), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                case = root / "case"
                case.mkdir()
                (case / "freshness.jsonl").write_text(json.dumps({"hit": flagged}) + "\n")
                c = types.SimpleNamespace(work=root, case=case, card={},
                    args=types.SimpleNamespace(resume="saved", dry_run=False, skip_build=False))
                with patch.object(run, "g1", return_value=(True, {"problems": []})), \
                     patch.object(run, "write_and_attack") as build, \
                     patch.object(run, "g2", return_value=(False, {"hits": 1, "outcome": "public_match"})), \
                     patch.object(run, "freshness_topup"):
                    run.build(c)
                self.assertEqual(build.call_count, 0 if flagged else 1)
                self.assertEqual(c.card.get("build_deferred"),
                    "existing_public_match_requires_G2" if flagged else None)

if __name__ == "__main__":
    unittest.main()
