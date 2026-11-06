"""A pending candidate that another handoff imported as history stays restorable (Murphy 7),
and a reselected pending candidate survives stale history (new-registry-pending-promotion-1).

Uses a copy of the retained public registry (sealed/statement-registry) and its real
age ciphertext; only the scorecards (plaintext digests, cipher bindings, rejected lists)
of pending candidates are authored.
"""
import sys
from pathlib import Path as _P
_ROOT = _P(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory")]
import hashlib
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


    def entry(self):
        return json.loads((self.tmp / "reg/registry.json").read_text())["entries"]["case-py"]


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
