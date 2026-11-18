"""A gate step imports factory modules from its release only (1108c, 18 November 2026).

G2 crashed with `cannot import name 'superseded' from 'admission' (/home/user/unbug-bench/factory/admission.py)`:
bin/bench.py appends <bench>/factory to sys.path, so a module the release dir did not serve fell through to the
baked bench's stale copy. Real artifacts: this checkout is the release, and a copy of its own bin/ and factory/
stands in for the baked bench at a separate path, the worker layout (/home/user/releases/<sha> beside
/home/user/unbug-bench). The crash record test raises real ImportErrors through the real gate_pipeline.
"""
import sys
from pathlib import Path as _TestPath
_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_ROOT / "bin")]

import json
import os
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from gate_pipeline import GatePipeline

PROBE = r"""
import importlib, importlib.util, json, pathlib, sys
release = sys.argv[1]
sys.path.insert(0, release + "/factory")   # as the worker command's worker_step.py does
from durable import worker_step
if sys.argv[2] == "runner":
    worker_step.Worker(pathlib.Path(sys.argv[3])).runner()
else:
    import run, bench                        # the old runner(): bench appends the baked factory dir
names = sorted(p.stem for p in pathlib.Path(release, "factory").glob("*.py"))
out = {"path": sys.path, "origins": {n: importlib.util.find_spec(n).origin for n in names},
       "loaded": {n: sys.modules[n].__file__ for n in worker_step.EAGER if n in sys.modules}}
try:
    import baked_only
    out["baked_only"] = baked_only.__file__
except ModuleNotFoundError:
    out["baked_only"] = None
print(json.dumps(out))
"""


class ReleaseImports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()).resolve()   # macOS: /var is /private/var
        cls.bench = cls.tmp / "unbug-bench"
        skip = shutil.ignore_patterns("__pycache__")
        for d in ("bin", "factory"):
            shutil.copytree(_ROOT / d, cls.bench / d, ignore=skip)
        # A module only the baked bench has: what the release dir failed to serve on the 1108c worker.
        (cls.bench / "factory/baked_only.py").write_text("")
        (cls.tmp / "home").mkdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def probe(self, mode):
        env = {**os.environ, "BENCH": str(self.bench), "HOME": str(self.tmp / "home")}
        p = subprocess.run([sys.executable, "-I", "-B", "-c", PROBE, str(_ROOT), mode, str(self.tmp / "home")],
                           capture_output=True, text=True, env=env, cwd=self.tmp, timeout=300)
        self.assertEqual(p.returncode, 0, p.stderr[-3000:])
        return json.loads(p.stdout.splitlines()[-1])

    def test_old_runner_falls_through_to_the_baked_bench(self):
        """The control: without the fix the baked factory dir is on sys.path and serves what the release lacks."""
        out = self.probe("old")
        self.assertIn(str(self.bench / "factory"), out["path"])
        self.assertEqual(out["baked_only"], str(self.bench / "factory/baked_only.py"))

    def test_runner_serves_every_factory_module_from_the_release_only(self):
        out = self.probe("runner")
        release = _ROOT / "factory"
        self.assertNotIn(str(self.bench / "factory"), out["path"])
        self.assertIsNone(out["baked_only"])   # fails loudly instead of running baked code
        self.assertGreater(len(out["origins"]), 20)
        for name, origin in out["origins"].items():
            self.assertEqual(Path(origin).parent, release, name)
        # The G2 modules are already loaded from the release when the step starts.
        self.assertEqual(sorted(out["loaded"]), sorted(["admission", "ordinary_freshness", "freshness_fanout"]))
        for name, origin in out["loaded"].items():
            self.assertEqual(Path(origin).parent, release, name)


class CrashRecord(unittest.TestCase):
    def record(self, statement):
        """Raise for real and record inside the handler, as gate_attempt.execute does."""
        with tempfile.TemporaryDirectory() as tmp:
            c = types.SimpleNamespace(work=Path(tmp))
            try:
                exec(statement, {})
            except Exception as error:
                GatePipeline.record_crash(types.SimpleNamespace(log=lambda *a: None), c, "G2", error)
            else:
                self.fail(statement)
            return json.loads((Path(tmp) / "gate-details/G2.crash-1.json").read_text())

    def test_import_error_records_where_the_import_looked(self):
        # The 1108c shape: the module exists in the release, the name is not in the copy that loaded.
        record = self.record("from admission import no_such_name")
        facts = record["imports"]
        self.assertEqual(record["error"], "ImportError")
        self.assertIn("cannot import name 'no_such_name' from 'admission'", record["traceback"])
        self.assertEqual(facts["module"], "admission")
        self.assertEqual(facts["release_factory"], str(_ROOT / "factory"))
        self.assertEqual(facts["sys_path"], sys.path)
        self.assertEqual(facts["release_finder"], "FileFinder")
        self.assertTrue(facts["release_lists_module"])
        self.assertTrue(facts["finder_lists_module"])
        self.assertIsInstance(facts["finder_mtime"], float)
        self.assertEqual(facts["release_mtime"], os.stat(_ROOT / "factory").st_mtime)

    def test_missing_module_records_it_is_not_listed(self):
        record = self.record("import no_such_factory_module")
        self.assertEqual(record["error"], "ModuleNotFoundError")
        self.assertEqual(record["imports"]["module"], "no_such_factory_module")
        self.assertFalse(record["imports"]["release_lists_module"])
        self.assertFalse(record["imports"]["finder_lists_module"])

    def test_package_counts_as_listed(self):
        facts = self.record("from durable import no_such_name")["imports"]
        self.assertEqual(facts["module"], "durable")
        self.assertTrue(facts["release_lists_module"])

    def test_other_crashes_keep_the_old_record(self):
        record = self.record("1 / 0")
        self.assertEqual(set(record), {"error", "message", "traceback"})


if __name__ == "__main__":
    unittest.main()
