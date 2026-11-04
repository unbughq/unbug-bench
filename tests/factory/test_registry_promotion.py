"""A pending candidate that another handoff imported as history stays restorable (Murphy 7).

Uses a copy of the retained public registry (sealed/statement-registry) and its real
age ciphertext; only the plaintext digests of pending candidates are authored.
"""
import sys
from pathlib import Path as _P
_ROOT = _P(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory")]
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

import registry

SEALED = _ROOT / "sealed"


class PromotionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        shutil.copytree(SEALED / "statement-registry", self.tmp / "reg")
        self.r = registry.Registry(self.tmp / "reg")
        real = sorted(SEALED.glob("case-*.statement.age"))
        self.ct = {n: real[i] for i, n in enumerate(("case-pa", "case-pb", "case-pc", "case-pz"))}
        self.dg = {"case-pa": "a" * 64, "case-pb": "b" * 64, "case-pc": "c" * 64, "case-pz": "e" * 64}

    def history(self, *cases):  # what statement_round.prepare does for non-candidates
        for c in cases:
            self.r.import_historical(c, self.ct[c], statement_sha256=self.dg[c] if c != "case-pc" else None)

    def test_pending_candidates_stay_exportable_under_interleaving(self):
        self.history("case-pb", "case-pc")  # handoff A imports B and C as history
        a = self.r.replace_rejected("case-pa", self.dg["case-pa"], self.ct["case-pa"], [])
        self.assertTrue({"case-pb", "case-pc"} <= set(a["statements"]))
        self.history("case-pb")  # a second handoff re-imports; must not demote or change B
        errors = []
        def promote(c):
            try: self.r.replace_rejected(c, self.dg[c], self.ct[c], [])
            except Exception as x: errors.append(x)
        threads = [threading.Thread(target=promote, args=(c,)) for c in ("case-pb", "case-pc")]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(errors, [])
        for c in ("case-pb", "case-pc"):
            snap = self.tmp / ("snap-" + c)
            entry = self.r.export(c, snap)
            self.assertTrue(entry["complete"]); self.assertEqual(entry["status"], "screening")
            self.assertEqual(entry["statement_sha256"], self.dg[c])
            self.assertIn("case-pa", entry["statements"])
            self.assertEqual(sorted(p.name for p in snap.glob("*.statement.age")),
                             sorted(k + ".statement.age" for k in entry["statements"]))
        # idempotent: replay returns the same reservation
        again = self.r.reserve("case-pb", self.dg["case-pb"], self.ct["case-pb"])
        self.assertEqual(again["reservation"], self.r.export("case-pb", self.tmp / "again")["reservation"])
        # B and C screened against each other (both were live entries) and against A
        for c, other in (("case-pb", "case-pc"), ("case-pc", "case-pb")):
            self.assertTrue({"case-pa", other} <= set(json.loads((self.tmp / ("snap-" + c) / "admission.json").read_text())["statements"]))
        # re-importing after promotion neither demotes nor reissues the reservation
        token = again["reservation"]
        self.assertEqual(self.r.import_historical("case-pb", self.ct["case-pb"], self.dg["case-pb"])["reservation"], token)
        self.assertTrue(self.r.export("case-pb", self.tmp / "after-import")["complete"])
        board = self.r.export_board(self.tmp / "board")
        self.assertTrue({"case-pa", "case-pb", "case-pc"} <= set(board["statements"]))

    def test_promotion_keeps_stored_ciphertext(self):
        self.history("case-pb")
        stored = self.r.export_board(self.tmp / "b0")["statements"]["case-pb"]
        resealed = self.ct["case-pc"]  # different real age bytes for the same plaintext digest
        entry = self.r.reserve("case-pb", self.dg["case-pb"], resealed)
        self.assertEqual(entry["cipher_sha256"], stored)
        self.assertEqual((self.r.root / "objects" / (stored + ".age")).read_bytes(), self.ct["case-pb"].read_bytes())

    def test_promotion_refuses_missing_stored_object(self):
        stored = self.history("case-pb") or self.r.export_board(self.tmp / "b0")["statements"]["case-pb"]
        (self.r.root / "objects" / (stored + ".age")).unlink()
        with self.assertRaisesRegex(ValueError, "corrupted"):
            self.r.reserve("case-pb", self.dg["case-pb"], self.ct["case-pb"])

    def test_prepare_promotes_other_waves_pending_candidate(self):
        import statement_round
        hist = self.tmp / "hist"; hist.mkdir()
        for c in ("case-pa", "case-pb"):
            shutil.copyfile(self.ct[c], hist / (c + ".statement.age"))
        (hist / "case-pb.scorecard.json").write_text(json.dumps({"statement_sha256": self.dg["case-pb"]}))
        waves = {}
        for c in ("case-pa", "case-pb"):  # each handoff sees the other's pending ciphertext as history
            waves[c] = statement_round.prepare(hist, self.tmp / "reg", {c: self.dg[c]}, self.tmp / ("w-" + c), history_sealed=hist)[c]
        self.assertIn("case-pb.statement.age", {p.name for p in waves["case-pa"].iterdir()})
        self.assertIn("case-pa.statement.age", {p.name for p in waves["case-pb"].iterdir()})
        for c in waves:
            self.assertTrue(json.loads((waves[c] / "admission.json").read_text())["complete"])

    def wave(self, name, candidate, y_ct, y_digest, rejected, y_candidate=False):
        """statement_round.prepare with case-py's collected ciphertext/card as the history."""
        import statement_round
        d = self.tmp / name; d.mkdir()
        shutil.copyfile(self.ct[candidate], d / (candidate + ".statement.age"))
        shutil.copyfile(y_ct, d / "case-py.statement.age")
        (d / "case-py.scorecard.json").write_text(json.dumps(
            {"statement_sha256": y_digest, "rejected_candidates": [{"statement_sha256": r} for r in rejected]}))
        cands = {"case-py": y_digest} if y_candidate else {candidate: self.dg[candidate]}
        return statement_round.prepare(d, self.tmp / "reg", cands, self.tmp / ("out-" + name), history_sealed=d)

    def test_reselected_pending_candidate_survives_other_wave_and_own_handoff(self):
        c1, c2, d1, d2 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64, "2" * 64
        for first in ("reserved", "history"):
            with self.subTest(first=first):
                shutil.rmtree(self.tmp / "reg"); shutil.copytree(SEALED / "statement-registry", self.tmp / "reg")
                self.r = registry.Registry(self.tmp / "reg")
                if first == "reserved":
                    self.wave(first + "1", "case-pa", c1, d1, [], y_candidate=True)  # Y's own handoff reserved c1
                    self.assertEqual(self.r.export("case-py", self.tmp / (first + "-old"))["statement_sha256"], d1)
                else:
                    self.wave(first + "1", "case-pa", c1, d1, [])  # another wave imported c1 as history
                out = self.wave(first + "2", "case-pz", c2, d2, [d1])  # Y reselected c2; X's wave must not fail
                self.assertEqual((out["case-pz"] / "case-py.statement.age").read_bytes(), c2.read_bytes())
                mine = self.wave(first + "3", "case-pa", c2, d2, [d1], y_candidate=True)["case-py"]
                entry = json.loads((mine / "admission.json").read_text())
                self.assertTrue(entry["complete"]); self.assertEqual(entry["statement_sha256"], d2)
                self.assertTrue({"case-pa", "case-pz"} <= set(entry["statements"]))
                self.assertEqual(self.r.export("case-pz", self.tmp / (first + "-a"))["statements"]["case-py"], entry["cipher_sha256"])

    def test_own_handoff_releases_reselected_historical_only_entry(self):
        c1, c2, d1, d2 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64, "2" * 64
        self.wave("h1", "case-pa", c1, d1, [])  # c1 imported as history by another wave
        mine = self.wave("h2", "case-pa", c2, d2, [d1], y_candidate=True)["case-py"]  # no X wave in between
        entry = json.loads((mine / "admission.json").read_text())
        self.assertEqual((entry["complete"], entry["statement_sha256"]), (True, d2))

    def test_stale_reservation_is_retried_once(self):
        from unittest import mock
        c1, c2, d1, d2 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64, "2" * 64
        self.wave("r1", "case-pa", c1, d1, [], y_candidate=True)
        real = registry.Registry.transition; calls = []
        def flaky(reg, *a):
            calls.append(a)
            if len(calls) == 1: raise ValueError("stale reservation")
            return real(reg, *a)
        with mock.patch.object(registry.Registry, "transition", flaky):
            self.assertEqual(self.r.replace_rejected("case-py", d2, c2, [d1])["statement_sha256"], d2)
        self.assertEqual(len(calls), 2)
        calls.clear()
        with mock.patch.object(registry.Registry, "transition", side_effect=ValueError("stale reservation")) as always:
            with self.assertRaisesRegex(ValueError, "stale"): self.r.replace_rejected("case-py", "3" * 64, c1, [d2])
        self.assertEqual(always.call_count, 2)

    def test_malformed_input_refuses_before_releasing(self):
        c1, c2, d1 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64
        self.wave("m1", "case-pa", c1, d1, [], y_candidate=True)
        junk = self.tmp / "junk.age"; junk.write_bytes(b"not age")
        with self.assertRaises(ValueError): self.r.replace_rejected("case-py", "2" * 64, junk, [d1])
        with self.assertRaises(ValueError): self.r.replace_rejected("case-py", "xyz", c2, [d1])
        self.assertEqual(self.r.export("case-py", self.tmp / "m-out")["statement_sha256"], d1)

    def test_unauthenticated_reselection_still_refuses_and_keeps_reservation(self):
        c1, c2, d1, d2 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64, "2" * 64
        for first in ("reserved", "history"):
            with self.subTest(first=first):
                shutil.rmtree(self.tmp / "reg"); shutil.copytree(SEALED / "statement-registry", self.tmp / "reg")
                self.wave(first + "1", "case-pa", c1, d1, [], y_candidate=first == "reserved")
                with self.assertRaisesRegex(ValueError, "different content"):  # c1 not listed as rejected
                    self.wave(first + "2", "case-pa", c2, d2, [])
                with self.assertRaisesRegex(ValueError, "different content"):  # rejected list names another digest
                    self.wave(first + "3", "case-pa", c2, d2, ["9" * 64])
                kept = json.loads((self.tmp / "reg/registry.json").read_text())["entries"]["case-py"]
                self.assertEqual((kept["statement_sha256"], kept["status"] != "released"), (d1, True))

    def test_negative_identities_still_refuse(self):
        self.history("case-pb", "case-pc")
        with self.assertRaisesRegex(ValueError, "different content"):  # wrong statement for known digest
            self.r.reserve("case-pb", "d" * 64, self.ct["case-pb"])
        with self.assertRaisesRegex(ValueError, "different content"):  # unknown digest, other ciphertext
            self.r.reserve("case-pc", self.dg["case-pc"], self.ct["case-pa"])
        for c in ("case-pb", "case-pc"):  # never promoted: stays historical-only
            with self.assertRaisesRegex(ValueError, "historical-only"):
                self.r.export(c, self.tmp / ("n" + c))
        released = self.r.reserve("case-pa", self.dg["case-pa"], self.ct["case-pa"])
        self.r.transition("case-pa", released["reservation"], "released")
        with self.assertRaises(ValueError): self.r.transition("case-pa", released["reservation"], "building")
        with self.assertRaisesRegex(ValueError, "released or historical"):
            self.r.export("case-pa", self.tmp / "rel")
        self.assertNotIn("case-pa", self.r.export_board(self.tmp / "board")["statements"])

    def test_stale_expected_revision_still_refuses_promotion(self):
        self.history("case-pb")
        with self.assertRaisesRegex(ValueError, "registry changed"):
            self.r.reserve("case-pb", self.dg["case-pb"], self.ct["case-pb"], expected_revision=0)


if __name__ == "__main__":
    unittest.main()
