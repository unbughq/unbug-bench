"""Synthetic public metadata only; no workers, cases or model calls."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest

import public_progress


class ProgressTests(unittest.TestCase):
    def test_early_gate_completion_is_public_before_sealing(self):
        import run
        import types
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = root / 'fixture'
            case.mkdir()
            c = types.SimpleNamespace(case_id='case-synthetic', case=case, work=root,
                                      card={}, args=types.SimpleNamespace())
            with patch.object(run, 'SEALED', root / 'sealed'), patch.object(run, 'log'), \
                 patch.object(run.GatePipeline, 'check', return_value=(True, {'reused_verified_evidence': True})):
                self.assertIsNone(run.early_checks(c))
            data = json.loads((root / 'sealed/case-synthetic.progress.json').read_text())
            self.assertEqual(set(data['completed']), {'early:G3', 'early:G4', 'early:G5'})
            self.assertTrue(all(row['reused'] for row in data['completed'].values()))
            self.assertFalse((root / 'scorecard.json').exists())

    def test_completion_is_distinct_from_activity_and_survives_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case-synthetic.progress.json"
            first = public_progress.publish(path, "G3", "completed", 7.5, reused=True)
            next_state = public_progress.publish(path, "G3", "running")
            self.assertEqual(next_state["last_completed_at"], first["last_completed_at"])
            self.assertEqual(next_state["completed"]["G3"]["elapsed_seconds"], 7.5)
            self.assertTrue(next_state["completed"]["G3"]["reused"])
            self.assertEqual(next_state["stages"]["G3"]["status"], "running")
            final = public_progress.publish(path, "role:writer", "failed", 3)
            self.assertEqual(final["last_completed_at"], first["last_completed_at"])
            self.assertNotIn("role:writer", final["completed"])

    def test_concurrent_publications_do_not_lose_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case-synthetic.progress.json"
            def update(n):
                public_progress.publish(path, "G" + str(n), "completed", n)
                json.loads(path.read_text())  # every visible replacement is a complete document
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(update, range(1, 18)))
            state = json.loads(path.read_text())
            self.assertEqual(len(state["completed"]), 17)
            self.assertEqual(len(state["stages"]), 17)

    def test_only_fixed_metadata_survives_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case-synthetic.progress.json"
            path.write_text(json.dumps({"prompt": "private text", "stages": {
                "role:writer": {"status": "completed", "updated_at": "2026-10-20T00:00:00Z", "answer": "private text"},
                "private stage": {"status": "completed", "updated_at": "2026-10-20T00:00:00Z"},
                "G2": {"status": ["private text"]}}, "completed": {}}))
            public_progress.publish(path, "early:G5", "completed", 1)
            self.assertNotIn("private", path.read_text())
            self.assertNotIn("answer", path.read_text())
            for stage, status, elapsed in (("prompt text", "running", None), ("G18", "running", None),
                                            ("G1", "answer text", None), ("G1", "running", float("nan"))):
                with self.assertRaises(ValueError): public_progress.publish(path, stage, status, elapsed)
            self.assertEqual(set(json.loads(path.read_text())["stages"]), {"role:writer", "early:G5"})

    def test_failed_write_preserves_previous_publication(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case-synthetic.progress.json"
            public_progress.publish(path, "G1", "completed")
            previous = path.read_bytes()
            with patch.object(public_progress.os, "replace", side_effect=OSError("synthetic")):
                with self.assertRaises(OSError): public_progress.publish(path, "G2", "running")
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(list(path.parent.glob(".case-synthetic.progress.json.*")), [])


if __name__ == "__main__": unittest.main()
