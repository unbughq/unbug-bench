"""Board cleanup on the control VM (durable/board_cleanup.py): plan, apply, revert.

Only statuses change. The worker-side GLM grouping is covered in test_durable_admit.
"""
import sys
from pathlib import Path as _TestPath

_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_TestPath(__file__).resolve().parent)]

import contextlib
import io
import json
import pathlib
import tempfile
import unittest

from durable import board_cleanup as bc

SECRET = "private-sentinel"


def entry(case, status, complete=False):
    return {"version": 1, "case_id": case, "statement_sha256": None, "cipher_sha256": "0" * 64, "complete": complete,
            "reservation": "r" * 32, "registry_revision": 1, "statements": {}, "status": status}


def board(**statuses):
    entries = {case.replace("_", "-"): entry(case.replace("_", "-"), status) for case, status in statuses.items()}
    return {"version": 1, "legacy": True, "registry": {"revision": 10, "entries": entries}, "objects": {"0" * 64: SECRET}}


class Plan(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.sealed = pathlib.Path(tmp.name)
        gates = {f"G{i}": "pass" for i in range(1, 16)}
        (self.sealed / "case-sealed.scorecard.json").write_text(json.dumps({"gates": gates, "failed_gate": None}))
        (self.sealed / "case-far.scorecard.json").write_text(json.dumps({"gates": {"G1": "pass", "G2": "pass"}}))
        (self.sealed / "case-near.scorecard.json").write_text(json.dumps({"gates": {"G1": "pass"}}))

    def plan(self, value, **kw):
        return {r["case"]: r for r in bc.plan(value, sealed_root=self.sealed, **kw)}

    def test_rules(self):
        value = board(case_sealed="completed", case_public="known_public", case_build="building",
                      case_old="completed", case_gone="released", case_far="completed", case_near="completed",
                      case_mid="completed", case_live="screening")
        groups = [{"case-far", "case-near", "case-mid"}, {"case-sealed", "case-old"}]
        rows = self.plan(value, groups=groups, durable={"case-live": (False, True)})
        self.assertEqual({c: (r["new"], r["reason"]) for c, r in rows.items()}, {
            "case-sealed": ("completed", "sealed"), "case-public": ("known_public", "known_public"),
            "case-build": ("building", "live"), "case-live": ("screening", "live"),
            "case-gone": ("released", "released"),
            # The most advanced member stays and blocks; the other members are released.
            "case-far": ("completed", "group_kept"), "case-near": ("released", "duplicate_released"),
            "case-mid": ("released", "duplicate_released"),
            "case-old": ("released", "duplicate_released")})
        self.assertEqual(rows["case-near"]["group"], ["case-far", "case-mid", "case-near"])
        self.assertEqual(rows["case-old"]["group_kept"], "case-sealed")
        # Not in any group, never sealed, not running: abandoned.
        rows = self.plan(board(case_x="completed", case_y="screening"), durable={})
        self.assertEqual((rows["case-x"]["reason"], rows["case-y"]["reason"]), ("abandoned", "abandoned"))
        # Without DBOS a reservation may be live, so it stays; --keep and --sealed override.
        rows = self.plan(board(case_x="completed", case_y="screening"), keep=["case-x"])
        self.assertEqual((rows["case-x"]["reason"], rows["case-y"]["reason"]), ("operator_keep", "live"))
        rows = self.plan(board(case_x="completed"), sealed=["case-x"], durable={})
        self.assertEqual(rows["case-x"]["new"], "completed")

    def test_duplicate_groups_join_backfill_and_manual_groups(self):
        lines = [json.dumps({"case": "case-imp-000990-1", "imported_case": "case-000990",
                             "candidates": [{"duplicate_of": "case-e9d919"}]}),
                 json.dumps({"case": "case-imp-04d417-1", "imported_case": "case-04d417",
                             "candidates": [{"duplicate_of": "case-e9d919"}]}),
                 json.dumps({"case": "case-imp-091b3f-1", "candidates": [{"screen": "realism"}]})]
        groups = bc.duplicate_groups(lines, [["case-b5521c", "case-fcde6b"], ["case-04d417", "case-zzz"]])
        self.assertEqual(sorted(sorted(g) for g in groups),
                         [["case-000990", "case-04d417", "case-e9d919", "case-zzz"], ["case-b5521c", "case-fcde6b"]])


class Files(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = bc.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_plan_apply_revert(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "board.json"
            source.write_text(json.dumps(board(case_a="completed", case_b="completed", case_c="known_public")))
            before = source.read_bytes()
            code, out, _ = self.run_cli("plan", source, "--group", "case-a,case-b")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.splitlines()[-1])["summary"]["release"], 1)
            self.assertNotIn(SECRET, out)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["board.json"])   # a dry run writes nothing

            code, out, _ = self.run_cli("apply", source, "--group", "case-a,case-b", "--out", root / "new.json",
                                        "--log", root / "log.json")
            self.assertEqual(code, 0)
            self.assertEqual(source.read_bytes(), before)
            new = json.loads((root / "new.json").read_text())
            self.assertEqual({c: e["status"] for c, e in new["registry"]["entries"].items()},
                             {"case-a": "completed", "case-b": "released", "case-c": "known_public"})
            self.assertEqual(new["registry"]["revision"], 11)
            self.assertEqual(new["objects"], {"0" * 64: SECRET})   # only statuses change
            log = json.loads((root / "log.json").read_text())
            self.assertEqual(log["changes"], [{"case": "case-b", "status": "completed", "new": "released",
                                               "reason": "duplicate_released"}])
            # Never overwrites a board or a log.
            code, _, err = self.run_cli("apply", source, "--out", root / "new.json", "--log", root / "log2.json")
            self.assertEqual((code, err.strip()), (1, "board_cleanup_refused_existing_output"))

            code, out, _ = self.run_cli("revert", root / "new.json", "--log", root / "log.json", "--out", root / "back.json")
            self.assertEqual(code, 0)
            back = json.loads((root / "back.json").read_text())
            self.assertEqual(back["registry"]["entries"], json.loads(before)["registry"]["entries"])

            # An entry changed since the cleanup is left as it is, and reported.
            changed = json.loads((root / "new.json").read_text())
            changed["registry"]["entries"]["case-b"]["status"] = "screening"
            (root / "changed.json").write_text(json.dumps(changed))
            code, out, _ = self.run_cli("revert", root / "changed.json", "--log", root / "log.json", "--out", root / "b2.json")
            self.assertEqual(json.loads(out), {"reverted": 0, "skipped_changed_since": ["case-b"]})

    def test_a_malformed_board_or_plan_case_without_config_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = pathlib.Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"version": 1, "registry": {"revision": 0, "entries": {"x": {}}}}))
            self.assertEqual(self.run_cli("plan", bad)[2].strip(), "board_invalid")
            good = pathlib.Path(tmp) / "good.json"
            good.write_text(json.dumps(board(case_a="completed")))
            self.assertEqual(self.run_cli("plan", good, "--plan-case", "case-board-1")[2].strip(), "plan_case_needs_config")


if __name__ == "__main__":
    unittest.main()
