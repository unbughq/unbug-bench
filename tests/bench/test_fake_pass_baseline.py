"""Fake-pass installation uses the contestant's case baseline, including services."""
import importlib.machinery
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))
loader = importlib.machinery.SourceFileLoader("fakepass", str(ROOT / "bin/fake-pass-check"))
m = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(m)


class BaselineTests(unittest.TestCase):
    def test_baseline_dependent_patch_and_service_are_installed_with_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            guard = Path(tmp)
            scenarios = [{"id": "base", "dir": guard / "base", "inventory_services": [{"id": "stock"}]}]
            base = {key: [] for key in (*m.FLAG_IF_NEW, "tables", "triggers")}
            def prepare(path, supplied=()):
                if supplied != scenarios:
                    raise ValueError("fix patch requires base/app.patch and stock service")
            summary = dict(traffic_options={}, runs=1, **{"pass": 1}, oversold=0, errors=0,
                           invalid=0, results_directory="synthetic")
            with patch.object(m.bench, "prepare_app_guard", side_effect=prepare), \
                 patch.object(m.bench, "reset") as reset, \
                 patch.object(m.bench, "run_case", return_value=summary) as traffic, \
                 patch.object(m, "catalog", return_value=base), \
                 patch.object(m, "digests", return_value={}), patch.object(m, "stocked", return_value="seed"):
                generic = m.check_guard(guard, 5, 42, base, set(), {}, "seed")
                self.assertTrue(any(f['where'] == 'install' and f['severity'] == 'forbidden'
                                    for f in generic['findings']))
                reset.reset_mock(); traffic.reset_mock()
                result = m.check_guard(guard, 5, 42, base, set(), {}, "seed", scenarios=scenarios)
            self.assertEqual(result["verdict"], "clean")
            self.assertEqual(reset.call_args.kwargs["scenarios"], scenarios)
            self.assertTrue(all(call.kwargs["scenarios"] == scenarios for call in traffic.call_args_list))


if __name__ == "__main__": unittest.main()
