"""Every public dry fixture answer key must resolve without guessing a sibling."""

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
import run


class FixtureTests(unittest.TestCase):
    def test_all_key_guards_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = types.SimpleNamespace(case=pathlib.Path(tmp) / "case")
            run.build_fixture(c)
            for scenario in (c.case / "scenarios").iterdir():
                key = json.loads((scenario / "key.json").read_text())
                for guard in key.get("expected_judge", {}):
                    with self.subTest(scenario=scenario.name, guard=guard):
                        self.assertTrue(run.find_guard(c, guard, scenario).is_dir())


if __name__ == "__main__":
    unittest.main()
