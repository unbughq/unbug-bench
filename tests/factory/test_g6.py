"""A failed negative-control execution must fail G6 without inventing a cheat pass; G6 and G7 stop at the
first passing cheat, and a passing case still runs every cheat."""

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


class G6Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.work = pathlib.Path(tmp.name)
        self.c = types.SimpleNamespace(seed=7, args=types.SimpleNamespace(bench_workers=1, runs=10), card={},
                                       work=self.work, case=self.work / "case")

    def invoke(self, code, output):
        with patch.object(run, 'cheat_runs', return_value=(0, 10)), patch.object(
                run, 'sh', return_value=types.SimpleNamespace(returncode=code, stdout=output)):
            ok, detail = run.g6(self.c)
        return ok, self.c.card, detail

    def test_invalid_probe_is_operational_without_a_cheat_pass(self):
        from run_validity import InvalidInfra
        with self.assertRaises(InvalidInfra):
            self.invoke(1, 'negative-probe outcome=invalid-probe\n')

    def test_actual_generic_cheat_pass_is_counted(self):
        ok, card, _ = self.invoke(1, 'negative-probe outcome=cheat-pass\n')
        self.assertFalse(ok)
        self.assertEqual(card['cheats_passed'], '1/11')

    def test_clean_negative_suite_can_pass(self):
        ok, card, detail = self.invoke(0, 'example: 2 scored failing run(s); check verified\n')
        self.assertTrue(ok)
        self.assertEqual(card['cheats_passed'], '0/11')
        self.assertTrue(detail['negative_probes_ok'])

    def run_gate(self, gate, names, passing):
        guards = [run.BENCH / "guards/refuse-all"] + [self.work / n for n in names]
        ran = []
        def checkpoint(c, scenarios, guard, runs, seed, label, **kw):
            ran.append((guard.name, runs, seed)); return None, guard.name
        sh = patch.object(run, 'sh', return_value=types.SimpleNamespace(returncode=0, stdout='x: 1 scored failing run(s)\n'))
        plain = patch.object(run, "plain_and_reference", return_value=([{"clean": True, "broken": True}],
                             [{"clean": True, "solved": True}], {"legit_completion": 1}))
        patches = [patch.object(run, "cheats", return_value=guards), patch.object(run, "checkpoint", checkpoint),
                   patch.object(run, "verdicts", lambda c, name: [{"solved": name in passing}]), sh, plain]
        mocks = [p.start() for p in patches]
        for p in patches: self.addCleanup(p.stop)
        return getattr(run, gate.lower())(self.c), ran, mocks[3]

    def test_g6_stops_at_the_first_passing_cheat_and_skips_the_probes(self):
        (ok, detail), ran, sh = self.run_gate("G6", ["a", "b", "c"], {"b"})
        self.assertFalse(ok)
        self.assertEqual([r[0] for r in ran], ["refuse-all", "a", "b"])
        sh.assert_not_called()
        self.assertEqual(json.loads((self.work / "gate-details/G6.json").read_text()), {"passing_cheats": ["b"]})
        self.assertNotIn('"b"', json.dumps(detail))

    def test_a_passing_g6_runs_every_cheat_at_full_runs_and_seed_then_the_probes(self):
        (ok, detail), ran, sh = self.run_gate("G6", ["a", "b"], set())
        self.assertTrue(ok)
        self.assertEqual(ran, [("refuse-all", 10, 7), ("a", 10, 7), ("b", 10, 7)])
        sh.assert_called_once()

    def test_a_cheat_that_failed_the_gate_before_runs_first_after_refuse_all(self):
        (self.work / "gate-details").mkdir()
        (self.work / "gate-details/G6.json").write_text(json.dumps({"passing_cheats": ["c"]}))
        (ok, _), ran, _ = self.run_gate("G6", ["a", "b", "c"], {"c"})
        self.assertFalse(ok)
        self.assertEqual([r[0] for r in ran], ["refuse-all", "c"])

    def test_g7_stops_at_the_first_passing_cheat(self):
        (ok, detail), ran, _ = self.run_gate("G7", ["a", "b", "c"], {"a"})
        self.assertFalse(ok)
        self.assertEqual([r[0] for r in ran], ["refuse-all", "a"])
        self.assertEqual(detail["cheats_passed"], "1/4")
        self.assertEqual(json.loads((self.work / "gate-details/G7.json").read_text()), {"passing_cheats": ["a"]})

    def test_a_passing_g7_runs_every_cheat_with_the_new_seed(self):
        (ok, _), ran, _ = self.run_gate("G7", ["a", "b"], set())
        self.assertTrue(ok)
        self.assertEqual(ran, [("refuse-all", 10, 7 + 7919), ("a", 10, 7 + 7919), ("b", 10, 7 + 7919)])

    def test_g7_already_failed_by_its_plain_or_reference_rerun_runs_no_cheat(self):
        for none, ref in (([{"clean": True, "broken": False}], [{"clean": True, "solved": True}]),
                          ([{"clean": True, "broken": True}], [{"clean": True, "solved": False}])):
            with self.subTest(none=none, ref=ref), patch.object(run, "plain_and_reference", return_value=(none, ref, {"legit_completion": 1})), \
                 patch.object(run, "cheat_runs", return_value=(0, 1)) as cheat_runs:
                ok, detail = run.g7(self.c)
            self.assertFalse(ok)
            cheat_runs.assert_not_called()
            self.assertEqual(detail["cheats_passed"], "not run")


if __name__ == '__main__':
    unittest.main()
