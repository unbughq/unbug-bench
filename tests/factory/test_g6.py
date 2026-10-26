"""A failed negative-control execution must fail G6 without inventing a cheat pass."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import types
import unittest
from unittest.mock import patch
import run


class G6Tests(unittest.TestCase):
    def invoke(self, code, output):
        c = types.SimpleNamespace(seed=7, args=types.SimpleNamespace(bench_workers=1), card={})
        with patch.object(run, 'cheat_runs', return_value=(0, 10)), patch.object(
                run, 'sh', return_value=types.SimpleNamespace(returncode=code, stdout=output)):
            ok, detail = run.g6(c)
        return ok, c.card, detail

    def test_invalid_probe_fails_gate_without_a_cheat_pass(self):
        ok, card, detail = self.invoke(1, 'negative-probe outcome=invalid-probe\n')
        self.assertFalse(ok)
        self.assertEqual(card['cheats_passed'], '0/10')
        self.assertFalse(detail['negative_probes_ok'])

    def test_actual_generic_cheat_pass_is_counted(self):
        ok, card, _ = self.invoke(1, 'negative-probe outcome=cheat-pass\n')
        self.assertFalse(ok)
        self.assertEqual(card['cheats_passed'], '1/11')

    def test_clean_negative_suite_can_pass(self):
        ok, card, detail = self.invoke(0, 'example: 2 scored failing run(s); check verified\n')
        self.assertTrue(ok)
        self.assertEqual(card['cheats_passed'], '0/11')
        self.assertTrue(detail['negative_probes_ok'])


if __name__ == '__main__':
    unittest.main()
