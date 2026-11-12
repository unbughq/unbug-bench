"""G1 warns, never fails, when a bench inventory service cannot run in parallel bench copies."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import pathlib
import tempfile
import types
import unittest
from unittest.mock import patch

import bench
import run


class IsolationWarnings(unittest.TestCase):
    def warnings(self, services, fits):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp); (work / "logs").mkdir(); (work / "case/scenarios").mkdir(parents=True)
            c = types.SimpleNamespace(work=work, case=work / "case")
            with patch.object(bench, "load_scenario", return_value={}), \
                 patch.object(bench, "inventory_services", return_value=services), \
                 patch.object(bench, "factory_memory_fits", return_value=fits):
                return run.isolation_warnings(c), (work / "logs/runner.log").read_text() if (work / "logs/runner.log").exists() else ""

    def test_compliant_services_and_no_services_are_silent(self):
        self.assertEqual(self.warnings([{"name": "channel", "host_ports": [9010]}], True)[0], [])
        self.assertEqual(self.warnings([], False)[0], [])

    def test_missing_host_ports_warns_with_a_count_and_logs_the_name(self):
        warnings, log = self.warnings([{"name": "channel"}, {"name": "ok", "host_ports": [9011]}], True)
        self.assertEqual(len(warnings), 1)
        self.assertIn("1 inventory service(s) lack host_ports", warnings[0])
        self.assertNotIn("channel", warnings[0])
        self.assertIn("channel", log)

    def test_missing_mem_limit_warns(self):
        warnings, _ = self.warnings([{"name": "channel", "host_ports": [9010]}], False)
        self.assertEqual(len(warnings), 1)
        self.assertIn("mem_limit", warnings[0])

    def test_g1_reports_the_warning_without_failing(self):
        c = types.SimpleNamespace(args=types.SimpleNamespace(dry_run=False, source=None), card={}, case=pathlib.Path("."),
                                  work=pathlib.Path("."), manifest0=None)
        class Contract:
            def __init__(self, *a): pass
            def inspect(self, *a, **kw): return [], {}
        with patch.object(run, "CaseContract", Contract), patch.object(run, "log"), \
             patch.object(run, "case_hash", return_value="h"), patch.object(run, "isolation_warnings", return_value=["w"]), \
             patch("run_validity.retry", lambda path, identity, invoke, **kw: invoke()):
            ok, details = run.g1(c)
        self.assertTrue(ok)
        self.assertEqual(details["warnings"], ["w"])


if __name__ == "__main__":
    unittest.main()
