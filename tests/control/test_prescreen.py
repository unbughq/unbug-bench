"""control/prescreen.py: ADMIT's own offline checks, run on a manifest of ideas before a batch starts."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prescreen", ROOT / "control/prescreen.py")
prescreen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prescreen)

MINIMAX = "openrouter/minimax/minimax-m3.1-flash"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def inputs(statement=None, *, builder=MINIMAX, **more):
    value = {"version": 1, "dry_run": False, "seed": 11, "source": "port", "app_repo": "medusajs/medusa",
             "app_commit": "a" * 40, "promise": "# Promise\n\nCheckout holds stock.", "promise_paths": [],
             "models": {"builder": [builder], "attacker": ["openrouter/deepseek/deepseek-v4.1-flash"],
                        "reviewers": [["openrouter/xiaomi/mimo-v2.6-pro"]], "strong_calibrator": ["claude/claude-opus-5-5"],
                        "easy_calibrator": ["openrouter/z-ai/glm-5.3-flash"]}}
    if statement is not None:
        value["candidate"] = {"statement": statement, "statement_sha256": sha(statement)}
    value.update(more)
    return json.dumps(value).encode()


def board(entries):
    return {"version": 1, "registry": {"revision": len(entries), "entries": {
        case: {"status": status, "statement_sha256": digest} for case, (status, digest) in entries.items()}},
        "objects": {}, "refs": {}}


def idea(label, raw, case=None, archive=None):
    return {"label": label, "case": case, "inputs_raw": raw, "archive_raw": archive}


class PrescreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])

    def archive(self, old, statement, *, commit="a" * 40, writer="opencode-go/minimax-m3"):
        """A pre-durable checkpoint as run_artifacts.seal wrote it, encrypted to a fresh key."""
        key = self.tmp / "statements-key"
        if not key.exists():
            subprocess.run(["age-keygen", "-o", str(key)], capture_output=True, check=True)
        work = self.tmp / "src" / old
        (work / "case").mkdir(parents=True)
        (work / "case/statement.md").write_text(statement)
        (work / "case/case.json").write_text(json.dumps({"source": "port", "app": {"repo": "medusajs/medusa", "commit": commit}}))
        (work / "scorecard.json").write_text(json.dumps({"case": old, "source": "port", "gates": {"G1": "pass"},
            "failed_gate": None, "models": {"builder": [writer]}, "continuation_budget": {"cost": 2.5, "events": []}}))
        tar = subprocess.run(["tar", "-C", str(work.parent), "-czf", "-", old], capture_output=True, check=True).stdout
        recipient = subprocess.run(["age-keygen", "-y", str(key)], capture_output=True, check=True).stdout.decode().strip()
        return subprocess.run(["age", "-r", recipient], input=tar, capture_output=True, check=True).stdout

    def test_malformed_inputs_and_board_cleanup_runs_are_dropped(self):
        rows = prescreen.screen([idea("bad", b"{}"), idea("cleanup", inputs(board_dedup=True))], board({}))
        self.assertEqual([(r["verdict"], r["codes"]) for r in rows],
                         [("drop", ["admit:inputs_invalid"]), ("drop", ["admit:board_planned"])])

    def test_a_statement_already_on_the_board_or_earlier_in_the_manifest_is_dropped(self):
        b = board({"case-old": ("screening", sha("oversell")), "case-gone": ("released", sha("refund"))})
        rows = prescreen.screen([idea("a", inputs("oversell")), idea("b", inputs("refund")), idea("c", inputs("refund")),
                                 idea("d", inputs("tax"))], b)
        self.assertEqual([(r["verdict"], r["codes"], r["keep"]) for r in rows], [
            ("drop", ["admit:dedup_board_duplicate"], "case-old"),
            ("ok", [], None),   # a released entry is skipped by every screen
            ("drop", ["duplicate_in_manifest"], "b"),
            ("ok", [], None)])

    def test_mutual_duplicates_keep_one_and_the_keeper_needs_the_other_released(self):
        # 000990 and e9d919 rejected each other: the backfill ties them; the older ID is kept.
        history = [{"case": "case-b-1", "imported_case": "case-e9d919", "reason": "admit:dedup_board_duplicate",
                    "candidates": [{"screen": "dedup", "duplicate_of": "case-000990"}]},
                   {"case": "case-b-2", "imported_case": "case-000990", "reason": "admit:dedup_board_duplicate",
                    "candidates": [{"screen": "dedup", "duplicate_of": "case-e9d919"}]},
                   {"case": "case-b-3", "imported_case": "case-fresh", "reason": "admit:freshness_third_party"},
                   {"case": "case-b-4", "imported_case": "case-real", "reason": "admit:realism_rejected",
                    "overturned": ["realism"]}]
        b = board({"case-000990": ("screening", sha("x")), "case-e9d919": ("screening", sha("y"))})
        rows = prescreen.screen([idea("e", inputs(), "case-e9d919"), idea("z", inputs(), "case-000990"),
                                 idea("f", inputs(), "case-fresh"), idea("r", inputs(), "case-real")], b, history)
        self.assertEqual([(r["verdict"], r["codes"], r["keep"]) for r in rows], [
            ("drop", ["admit:dedup_board_duplicate", "prior:dedup_board_duplicate"], "case-000990"),
            ("review", ["release_group_first", "prior:dedup_board_duplicate"], "case-000990"),
            ("review", ["prior:freshness_third_party"], None),
            ("ok", [], None)])   # a second family overturned that rejection

    def test_imports_run_admits_own_archive_checks(self):
        key = str(self.tmp / "statements-key")
        good = self.archive("case-oct-1", "oversell")
        b = board({"case-other": ("screening", sha("oversell"))})
        rows = prescreen.screen([
            idea("good", inputs(import_spent_usd_micros=2_500_000), archive=good),
            idea("pin", inputs(import_spent_usd_micros=2_500_000), archive=self.archive("case-oct-2", "a", commit="b" * 40)),
            idea("writer", inputs(import_spent_usd_micros=2_500_000, builder="claude/claude-opus-5-5"),
                 archive=self.archive("case-oct-3", "b")),
            idea("spend", inputs(import_spent_usd_micros=1), archive=self.archive("case-oct-4", "c")),
        ], b, identity=key)
        self.assertEqual([(r["idea"], r["codes"]) for r in rows], [
            ("case-oct-1", ["admit:dedup_board_duplicate"]),   # the archive's statement is on the board
            (None, ["admit:import_pin"]),
            ("case-oct-3", ["admit:import_writer"]),
            (None, ["admit:import_spend"])])
        unchecked = prescreen.screen([idea("good", inputs(import_spent_usd_micros=2_500_000), archive=good)], board({}))
        self.assertEqual((unchecked[0]["verdict"], unchecked[0]["codes"]), ("review", ["import_unchecked"]))

    def test_cli_prints_a_table(self):
        (self.tmp / "in.json").write_bytes(inputs("tax"))
        (self.tmp / "manifest.json").write_text(json.dumps([{"label": "tax-idea", "inputs": "in.json"}]))
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(prescreen.main([str(self.tmp / "manifest.json")]), 0)
        self.assertEqual(out.getvalue().splitlines(), ["LABEL     IDEA  VERDICT  CHECKS  KEEP", "tax-idea  -     ok       -       -"])


if __name__ == "__main__":
    unittest.main()
