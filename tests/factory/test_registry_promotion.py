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

    def wave(self, name, candidate, y_ct, y_digest, rejected, y_candidate=False, card=None):
        """statement_round.prepare with case-py's collected ciphertext/card as the history."""
        import statement_round
        d = self.tmp / name; d.mkdir()
        shutil.copyfile(self.ct[candidate], d / (candidate + ".statement.age"))
        shutil.copyfile(y_ct, d / "case-py.statement.age")
        (d / "case-py.scorecard.json").write_text(json.dumps(card if card is not None else  # current writer's card shape
            {"statement_sha256": y_digest, "statement_cipher_sha256": hashlib.sha256(y_ct.read_bytes()).hexdigest(),
             "rejected_candidates": [{"statement_sha256": r} for r in rejected]}))
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
        def flaky(reg, *a, **k):
            calls.append(a)
            if len(calls) == 1: raise ValueError("stale reservation")
            return real(reg, *a, **k)
        with mock.patch.object(registry.Registry, "transition", flaky):
            self.assertEqual(self.r.replace_rejected("case-py", d2, c2, [d1])["statement_sha256"], d2)
        self.assertEqual(len(calls), 2)
        calls.clear()
        with mock.patch.object(registry.Registry, "transition", side_effect=ValueError("stale reservation")) as always:
            with self.assertRaisesRegex(ValueError, "stale"): self.r.replace_rejected("case-py", "3" * 64, c1, [d2])
        self.assertEqual(always.call_count, 2)

    def entry(self):
        return json.loads((self.tmp / "reg/registry.json").read_text())["entries"]["case-py"]

    def test_stale_history_ciphertext_cannot_take_reselected_digest(self):
        # diff-5 B1: card already names d2 (rejecting d1) but the collected history bytes are still c1.
        c1, c2, d1, d2 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64, "2" * 64
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        bound = {"statement_sha256": d2, "statement_cipher_sha256": sha(c2), "rejected_candidates": [{"statement_sha256": d1}]}
        for first in ("reserved", "history"):
            with self.subTest(first=first):
                shutil.rmtree(self.tmp / "reg"); shutil.copytree(SEALED / "statement-registry", self.tmp / "reg")
                self.r = registry.Registry(self.tmp / "reg")
                self.wave(first + "1", "case-pa", c1, d1, [], y_candidate=first == "reserved")
                before = self.entry()
                # diff-8 F1: other waves with the stale bytes get base's answer (keep d1/c1, bind nothing), not a failure.
                for i, card in enumerate((None, {"statement_sha256": d2},  # bound-to-c1 card, legacy card, legacy rejecting d1
                                          {"statement_sha256": d2, "rejected_candidates": [{"statement_sha256": d1}]},
                                          bound)):  # card binds c2, bytes are c1: not authenticated
                    out = self.wave(f"{first}2{i}", "case-pz", c1, d2, [d1], card=card)
                    self.assertEqual((out["case-pz"] / "case-py.statement.age").read_bytes(), c1.read_bytes())
                    self.assertEqual(self.entry(), before)
                with self.assertRaisesRegex(ValueError, "different content"):  # Y's own handoff with the same stale bytes
                    self.r.replace_rejected("case-py", d2, c1, [d1], bound=True)
                self.assertEqual(self.entry(), before)
                # the consistent card still succeeds (fresh candidate: case-pz's snapshot is fixed above)
                out = self.wave(first + "4", "case-pb", c2, d2, [d1], card=bound)
                self.assertEqual((out["case-pb"] / "case-py.statement.age").read_bytes(), c2.read_bytes())
                self.assertEqual(self.entry()["cipher_sha256"], sha(c2))

    def test_history_release_needs_card_bound_to_collected_bytes(self):
        # diff-6 G1: a legacy-shape card (no cipher digest) with another seal of the rejected statement.
        c1, d1, d2 = self.ct["case-pb"], "1" * 64, "2" * 64
        other_seal = sorted(SEALED.glob("case-*.statement.age"))[5]
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertNotEqual(sha(other_seal), sha(c1))
        legacy = {"statement_sha256": d2, "rejected_candidates": [{"statement_sha256": d1}]}
        for first in ("reserved", "history"):
            with self.subTest(first=first):
                shutil.rmtree(self.tmp / "reg"); shutil.copytree(SEALED / "statement-registry", self.tmp / "reg")
                self.r = registry.Registry(self.tmp / "reg")
                self.wave(first + "1", "case-pa", c1, d1, [], y_candidate=first == "reserved")
                with self.assertRaisesRegex(ValueError, "different content"):
                    self.wave(first + "2", "case-pz", other_seal, d2, [d1], card=legacy)
                kept = self.entry()
                self.assertEqual((kept["statement_sha256"], kept["cipher_sha256"], kept["status"] != "released"),
                                 (d1, sha(c1), True))

    def test_own_handoff_needs_bound_card_to_release_historical_only_entry(self):
        # diff-7 H1: Y's own legacy-shape card (no cipher digest) with another seal of the rejected statement.
        c1, c2, d1, d2 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64, "2" * 64
        other_seal = sorted(SEALED.glob("case-*.statement.age"))[5]
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        self.wave("o1", "case-pa", c1, d1, [])  # another wave imported c1 as history
        legacy = {"statement_sha256": d2, "rejected_candidates": [{"statement_sha256": d1}]}
        with self.assertRaisesRegex(ValueError, "different content"):
            self.wave("o2", "case-pa", other_seal, d2, [d1], y_candidate=True, card=legacy)
        kept = self.entry()
        self.assertEqual((kept["statement_sha256"], kept["cipher_sha256"], kept["complete"], kept["status"]),
                         (d1, sha(c1), False, "completed"))
        mine = self.wave("o3", "case-pa", c2, d2, [d1], y_candidate=True)["case-py"]  # the bound card still releases
        self.assertEqual(json.loads((mine / "admission.json").read_text())["cipher_sha256"], sha(c2))

    def test_known_public_historical_entry_is_never_released(self):
        # diff-7 M1: only a completed historical-only entry may be released by its own bound card.
        c1, c2, d1, d2 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64, "2" * 64
        self.wave("p1", "case-pa", c1, d1, [])
        self.r.transition("case-py", self.entry()["reservation"], "known_public")
        for name, kw in (("p2", {"y_candidate": True}), ("p3", {})):
            with self.assertRaisesRegex(ValueError, "different content"):
                self.wave(name, "case-pz" if not kw else "case-pa", c2, d2, [d1], **kw)
        self.assertEqual((self.entry()["status"], self.entry()["statement_sha256"]), ("known_public", d1))

    def test_history_cipher_skew_without_release_does_not_fail_other_wave(self):
        # diff-6 G2: a new seal beside an older card, same digest as the registry: nothing to release.
        c1, d1 = self.ct["case-pb"], "1" * 64
        other_seal = sorted(SEALED.glob("case-*.statement.age"))[5]
        self.wave("s1", "case-pa", c1, d1, [], y_candidate=True)
        out = self.wave("s2", "case-pz", other_seal, d1, [], card={
            "statement_sha256": d1, "statement_cipher_sha256": hashlib.sha256(c1.read_bytes()).hexdigest()})
        self.assertEqual((out["case-pz"] / "case-py.statement.age").read_bytes(), c1.read_bytes())  # stored bytes kept
        self.assertEqual((self.entry()["statement_sha256"], self.entry()["status"]), (d1, "screening"))

    def test_own_handoff_keeps_reselected_ciphertext_imported_as_history(self):
        # diff-5 N3: X's history import stores c2; Y hands off a different seal of the same d2.
        c1, c2, d1, d2 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64, "2" * 64
        c2b = sorted(SEALED.glob("case-*.statement.age"))[4]
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertNotIn(sha(c2b), (sha(c1), sha(c2)))
        self.wave("k1", "case-pa", c1, d1, [], y_candidate=True)
        self.wave("k2", "case-pz", c2, d2, [d1])
        mine = json.loads((self.wave("k3", "case-pa", c2b, d2, [d1], y_candidate=True)["case-py"] / "admission.json").read_text())
        self.assertEqual((mine["complete"], mine["statement_sha256"], mine["cipher_sha256"]), (True, d2, sha(c2)))
        self.assertEqual(self.r.export("case-pz", self.tmp / "k-out")["statements"]["case-py"], sha(c2))

    def test_release_is_fenced_on_status_changed_under_same_token(self):
        # diff-5 M1: Y completes c1 between the unlocked read and the release.
        from unittest import mock
        c1, c2, d1, d2 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64, "2" * 64
        self.wave("f1", "case-pa", c1, d1, [], y_candidate=True)
        real = registry.Registry.transition; calls = []
        def racing(reg, case, token, status, **k):
            calls.append(status)
            if len(calls) == 1: real(reg, case, token, "completed")  # the concurrent change, same token
            return real(reg, case, token, status, **k)
        with mock.patch.object(registry.Registry, "transition", racing):
            with self.assertRaisesRegex(ValueError, "different content"):
                self.r.replace_rejected("case-py", d2, c2, [d1])
        self.assertEqual(calls, ["released"])
        self.assertEqual((self.entry()["status"], self.entry()["statement_sha256"]), ("completed", d1))
        token = self.entry()["reservation"]
        with self.assertRaisesRegex(ValueError, "stale reservation"):
            self.r.transition("case-py", token, "released", expect=("screening", d1, self.entry()["cipher_sha256"]))

    def test_malformed_history_rejected_list_authenticates_nothing(self):
        # diff-5 N1: a malformed history card no longer crashes other waves; it never authenticates a release.
        c1, c2, d1, d2 = self.ct["case-pb"], self.ct["case-pc"], "1" * 64, "2" * 64
        for i, rows in enumerate((None, [{"statement_sha256": d1}] * 4, [d1], "x")):
            with self.subTest(rows=rows):
                shutil.rmtree(self.tmp / "reg"); shutil.copytree(SEALED / "statement-registry", self.tmp / "reg")
                self.r = registry.Registry(self.tmp / "reg")
                self.wave(f"n{i}a", "case-pz", c2, d2, [], card={"statement_sha256": d2, "rejected_candidates": rows})
                self.assertEqual(self.entry()["statement_sha256"], d2)  # no previous entry: plain history import
                shutil.rmtree(self.tmp / "reg"); shutil.copytree(SEALED / "statement-registry", self.tmp / "reg")
                self.wave(f"n{i}b", "case-pa", c1, d1, [], y_candidate=True)
                with self.assertRaisesRegex(ValueError, "different content"):
                    self.wave(f"n{i}c", "case-pz", c2, d2, [], card={"statement_sha256": d2, "rejected_candidates": rows})
                self.assertEqual((self.entry()["statement_sha256"], self.entry()["status"]), (d1, "screening"))

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
