"""The stop registry covers every recordable reason, and the stop audit's verdicts from fake attempts."""
import base64
import pickle
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "factory"))
from durable import classify  # noqa: E402
from durable.contract import REASON  # noqa: E402
from durable.stop_registry import REGISTRY, alerts, audit, bug, decode  # noqa: E402

# A quoted reason literal anywhere in the factory or the campaign controller.
LITERAL = re.compile(r"""["'](%s)["']""" % REASON.pattern)
FIX, OTHER_FIX, OLD, NEW = "f" * 40, "e" * 40, "a" * 40, "b" * 40


def recordable() -> set:
    fixed = (classify.REASONS | classify.CONTRACT_REASONS | classify.WORKER_POOL_REASONS
             | classify.IMPORT_REASONS | classify.REJECTION_REASONS | classify.BOARD_REASONS)
    sources = [*(ROOT / "factory").rglob("*.py"), *(ROOT / "control/campaign").glob("*.py")]
    literals = {m.group(1) for p in sources for m in LITERAL.finditer(p.read_text())}
    return fixed | {r for r in literals if not r.endswith("_")}   # "admit:dedup_" etc. are prefixes


def row(reason, *, case="case-1", seq=1, attempt=1, pv="p-new", outcome="infra_error"):
    return {"case_id": case, "batch_id": "b-1", "seq": seq, "attempt": attempt, "plumbing_version": pv,
            "outcome": outcome, "reason": reason, "started_at": 1.0}


class RegistryTests(unittest.TestCase):
    def test_every_recordable_reason_is_classified(self):
        missing = sorted(recordable() - set(REGISTRY))
        self.assertEqual(missing, [], "classify these in factory/durable/stop_registry.py")

    def test_every_entry_is_a_valid_reason_of_a_known_kind(self):
        for reason, entry in REGISTRY.items():
            self.assertRegex(reason, REASON)
            self.assertIn(entry["kind"], ("case", "wait", "bug"), reason)

    def test_every_named_regression_test_exists(self):
        for reason, entry in REGISTRY.items():
            if entry["kind"] == "bug" and entry["test"]:
                path, *_, name = entry["test"].split("::")
                self.assertTrue((ROOT / path).is_file(), reason)
                self.assertIn(f"def {name}(", (ROOT / path).read_text(), reason)
            if entry["kind"] == "bug" and entry["fixed_in"]:
                for fix in entry["fixed_in"]:
                    self.assertRegex(fix, r"^[0-9a-f]{40}$", reason)


class AuditTests(unittest.TestCase):
    registry = {"writer:validated": {"kind": "case"}, "router:quota": {"kind": "wait"},
                "infra:fixed": bug(FIX, test="t.py::T::test"), "infra:open": bug(),
                "infra:two_fixes": bug(FIX, OTHER_FIX)}
    commits = {"p-old": OLD, "p-new": NEW}

    def run_audit(self, rows, contains=lambda commit, fix: commit == NEW):
        return audit(rows, self.commits, contains, self.registry)

    def test_a_fixed_bug_on_a_release_containing_its_fix_is_a_regression(self):
        out = self.run_audit([row("infra:fixed"), row("infra:fixed", case="case-2")])
        reg, = out["regression"]
        self.assertEqual((reg["reason"], reg["commit"], reg["fixed_in"], reg["count"], reg["cases"]),
                         ("infra:fixed", NEW, (FIX,), 2, ["case-1", "case-2"]))
        self.assertEqual(alerts(out), {"stop_audit:infra:fixed":
                                       "Stop audit: fixed bugs came back: infra:fixed. Run bin/stop_audit."})

    def test_a_fixed_bug_before_its_fix_is_not_reported(self):
        out = self.run_audit([row("infra:fixed", pv="p-old")])
        self.assertEqual(out["regression"] + out["unchecked"] + out["open"], [])
        self.assertEqual(alerts(out), {})

    def test_a_bug_with_several_fixes_regresses_only_on_a_release_with_all_of_them(self):
        has = {(NEW, FIX): True, (NEW, OTHER_FIX): True, (OLD, FIX): True, (OLD, OTHER_FIX): False}
        contains = lambda commit, fix: has[commit, fix]
        self.assertEqual(len(self.run_audit([row("infra:two_fixes")], contains)["regression"]), 1)
        out = self.run_audit([row("infra:two_fixes", pv="p-old")], contains)
        self.assertEqual(out["regression"] + out["unchecked"], [])
        unsure = self.run_audit([row("infra:two_fixes")], lambda commit, fix: None if fix == OTHER_FIX else True)
        self.assertEqual(len(unsure["unchecked"]), 1)

    def test_ancestry_works_on_a_plain_clone_of_a_git_bundle(self):
        import subprocess, tempfile
        from durable.stop_registry import git_contains
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            git = lambda *a, cwd=tmp / "src": subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                                                             text=True).stdout.strip()
            (tmp / "src").mkdir()
            git("init", "-q")
            for n in (1, 2):
                git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", str(n))
            fix, release = git("rev-parse", "HEAD~1"), git("rev-parse", "HEAD")
            git("bundle", "create", str(tmp / "main.bundle"), "HEAD")
            git("clone", "-q", str(tmp / "main.bundle"), str(tmp / "clone"), cwd=tmp)   # no remote but the file
            contains = git_contains(tmp / "clone")
            self.assertTrue(contains(release, fix))
            self.assertFalse(contains(fix, release))
            self.assertIsNone(contains("0" * 40, fix))   # a release from outside the bundle: cannot tell

    def test_unknown_release_commit_or_ancestry_is_unchecked(self):
        self.assertEqual(len(self.run_audit([row("infra:fixed", pv="p-gone")])["unchecked"]), 1)
        self.assertEqual(len(self.run_audit([row("infra:fixed")], contains=None)["unchecked"]), 1)
        self.assertEqual(len(self.run_audit([row("infra:fixed")], contains=lambda c, f: None)["unchecked"]), 1)

    def test_open_unknown_and_non_bugs(self):
        out = self.run_audit([row("infra:open"), row("infra:raw_new_thing", seq=2), row("writer:validated", seq=3,
                              outcome="ok"), row("router:quota", seq=4, outcome="provider_limit")])
        self.assertEqual([r["reason"] for r in out["open"]], ["infra:open"])
        self.assertEqual([r["reason"] for r in out["unknown"]], ["infra:raw_new_thing"])
        self.assertEqual(out["regression"], [])
        self.assertEqual(out["releases"], {"p-new": {"commit": NEW, "attempts": 4, "infra": 2}})
        self.assertEqual(list(alerts(out)), ["stop_audit:infra:raw_new_thing"])

    def test_the_same_attempt_read_twice_counts_once(self):
        out = self.run_audit([row("infra:open"), row("infra:open"), row("infra:open", attempt=2)])
        self.assertEqual(out["open"][0]["count"], 2)
        self.assertEqual(out["releases"]["p-new"]["attempts"], 2)

    def test_release_commits_merge_the_store_map_and_release_records(self):
        import json, tempfile
        from durable.stop_registry import release_commits
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "store").mkdir()
            (tmp / "store/release-commits.json").write_text(json.dumps({"p-live": NEW}))
            (tmp / "work/plumbing-aaaa").mkdir(parents=True)
            (tmp / "work/plumbing-aaaa/state.json").write_text(json.dumps({"commit": OLD, "plumbing_version": "p-old"}))
            self.assertEqual(release_commits(tmp / "work", tmp / "store/release-commits.json"),
                             {"p-live": NEW, "p-old": OLD})
            self.assertEqual(release_commits(None, tmp / "missing.json"), {})

    def test_decode_reads_a_recorded_attempt_and_skips_other_outputs(self):
        record = {"started": True, "input": {"case_id": "case-1", "batch_id": "b-1", "seq": 3, "attempt": 2,
                                             "step": {"kind": "writer"}, "plumbing_version": "p"},
                  "result": {"outcome": "infra_error", "reason": "infra:cancelled", "usage": {}}, "started_at": 5.0}
        encode = lambda v: base64.b64encode(pickle.dumps(v)).decode()
        self.assertEqual(decode(encode(record)), {"case_id": "case-1", "batch_id": "b-1", "seq": 3, "attempt": 2,
                         "plumbing_version": "p", "outcome": "infra_error", "reason": "infra:cancelled",
                         "started_at": 5.0})
        self.assertIsNone(decode(encode({"started": False, "action": "stale_preparation"})))
        self.assertIsNone(decode(encode("not a dict")))


if __name__ == "__main__":
    unittest.main()
