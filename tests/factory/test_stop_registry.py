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
from durable.stop_registry import REGISTRY, UNDECODABLE, audit, bug, decode, invariants, lookup, result  # noqa: E402

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

    def test_cleanup_labelled_diagnoses_are_one_open_family_and_raw_stops_stay_unknown(self):
        self.assertEqual(lookup("diagnosis:cf_key_error"), {"kind": "bug", "fixed_in": None, "test": None})
        self.assertIsNone(lookup("infra:raw_key_error"))
        self.assertEqual(lookup("writer:validated"), {"kind": "case"})

    def test_reasons_that_collect_several_causes_are_never_marked_fixed(self):
        for reason in ("infra:execution_retries_exhausted", "infra:deadline", "infra:unclassified_stop",
                       "infra:runner_exception", "infra:stalled", "infra:diagnosis_cleanup_failed",
                       "diagnosis:processing_failed", "infra:pool_failed", "infra:cleanup_failed",
                       "infra:prompt_too_large"):
            self.assertIsNone(REGISTRY[reason]["fixed_in"], reason)

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
        written = result(out, undecodable=3, now=100.0)
        self.assertEqual((written["written_at"], written["regression_reasons"], written["unknown_reasons"]),
                         (100.0, ["infra:fixed"], []))
        self.assertEqual((written["counts"]["regression"], written["counts"]["attempts"],
                          written["counts"]["undecodable"]), (1, 2, 3))
        self.assertTrue(written["regression"][0].startswith("REGRESSION infra:fixed"))

    def test_a_fixed_bug_before_its_fix_is_not_reported(self):
        out = self.run_audit([row("infra:fixed", pv="p-old")])
        self.assertEqual(out["regression"] + out["unchecked"] + out["open"], [])
        self.assertEqual(result(out, 0, 1.0)["regression_reasons"], [])

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
        self.assertEqual(result(out, 0, 1.0)["unknown_reasons"], ["infra:raw_new_thing"])

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
                         "started_at": 5.0, "key": "case-1/3/writer/2", "paid_usd_micros": 0,
                         "settles_as_waste": True})
        self.assertIsNone(decode(encode({"started": False, "action": "stale_preparation"})))
        self.assertIsNone(decode(encode("not a dict")))
        # No recorded start (a lease that never started): the row's own DBOS time stands in.
        self.assertEqual(decode(encode({**record, "started_at": None}), row_time=7.0)["started_at"], 7.0)

    def test_decode_refuses_anything_but_builtins(self):
        import collections
        encode = lambda v: base64.b64encode(pickle.dumps(v)).decode()
        for refused in (encode(collections.OrderedDict(a=1)), encode({"input": Path("/"), "result": {}}),
                        "not base64!", base64.b64encode(b"not a pickle").decode()):
            self.assertIs(decode(refused), UNDECODABLE, refused)


def attempt(*, key="case-1/2/writer:1/1", seq=2, outcome="ok", reason="writer:validated", paid=500, waste=False):
    return {"case_id": "case-1", "batch_id": "b-1", "seq": seq, "attempt": 1, "outcome": outcome, "reason": reason,
            "paid_usd_micros": paid, "key": key, "settles_as_waste": waste}


def booked(*, state="settled", paid=500, granted=1000, waste=False, rebooked=False, case_money=True):
    return {"state": state, "paid": paid, "granted": granted, "waste": waste, "rebooked": rebooked,
            "draws_case_money": case_money}


class InvariantTests(unittest.TestCase):
    """Each live invariant from fake attempt, ledger, budget and board rows."""
    BUDGET = {"b-1": {"bound": 10_000, "spent": 5_000, "waste": 1_000}}

    def checks(self, attempts=(), ledger=None, budgets=None, cases=()):
        key = "case-1/2/writer:1/1"
        return [c for c, _ in invariants(list(attempts), {key: booked()} if ledger is None else ledger,
                                         self.BUDGET if budgets is None else budgets, list(cases))]

    def test_a_consistent_batch_breaks_nothing(self):
        self.assertEqual(self.checks([attempt()]), [])

    def test_booked_spend_below_reported_usage(self):
        self.assertEqual(self.checks([attempt(paid=900)]), ["spend_below_usage"])
        self.assertEqual(self.checks([attempt(paid=900)], ledger={}), ["spend_below_usage"])   # never booked
        lost = {"case-1/2/writer:1/1": booked(state="lost", paid=0, granted=1000)}
        self.assertEqual(self.checks([attempt(paid=900)], ledger=lost), [])                    # lost books the grant
        held = {"case-1/2/writer:1/1": booked(state="held", paid=0)}
        self.assertEqual(self.checks([attempt(paid=900)], ledger=held), [])                    # not settled yet

    def test_a_batch_over_its_bound(self):
        over = {"b-1": {"bound": 10_000, "spent": 10_001, "waste": 0}}
        self.assertEqual(self.checks(budgets=over), ["batch_over_bound"])

    def test_waste_booked_to_the_case_s_own_money(self):
        broken = attempt(outcome="infra_error", reason="infra:stalled", waste=True)
        self.assertEqual(self.checks([broken]), ["waste_on_case_money"])
        for fine in (booked(waste=True), booked(rebooked=True), booked(case_money=False)):
            self.assertEqual(self.checks([broken], ledger={"case-1/2/writer:1/1": fine}), [])

    def test_a_live_case_stuck_over_two_hours(self):
        case = lambda status, quiet: {"batch": "b-1", "case": "case-1", "status": status, "live": True,
                                      "quiet_for_s": quiet}
        self.assertEqual(self.checks(cases=[case("running", 7300)]), ["case_stuck"])
        self.assertEqual(self.checks(cases=[case("running", 7000)]), [])
        self.assertEqual(self.checks(cases=[case("held", 99_999)]), [])                 # a hold is not stuck
        self.assertEqual(self.checks(cases=[case("waiting_for_bound", 7300)]), ["case_stuck"])   # 4000 real < bound
        spent = {"b-1": {"bound": 10_000, "spent": 11_000, "waste": 1_000}}               # real spend at the bound
        self.assertEqual(self.checks(budgets=spent, cases=[case("waiting_for_bound", 7300)]), ["batch_over_bound"])

    def test_one_attempt_recorded_with_two_results(self):
        self.assertEqual(self.checks([attempt(), attempt()]), [])                       # read twice, same result
        twice = self.checks([attempt(), attempt(outcome="infra_error", reason="infra:cancelled")])
        self.assertEqual(twice, ["attempt_recorded_twice"])

    def test_decode_gives_the_ledger_key_and_the_waste_rule(self):
        record = {"input": {"case_id": "case-1", "batch_id": "b-1", "seq": 2, "attempt": 1, "plumbing_version": "p",
                            "step": {"kind": "writer", "round": 1}},
                  "result": {"outcome": "provider_limit", "reason": "router:quota",
                             "usage": {"calls": 1, "paid_usd_micros": 7, "list_usd_micros": 9}}}
        row = decode(base64.b64encode(pickle.dumps(record)).decode())
        self.assertEqual((row["key"], row["paid_usd_micros"], row["settles_as_waste"]), ("case-1/2/writer:1/1", 7, True))
        record["input"]["step"] = {"kind": "admit", "round": 0}
        self.assertEqual(decode(base64.b64encode(pickle.dumps(record)).decode())["key"], "case-1/2/admit/1")

    def test_violations_reach_the_result_file(self):
        written = result(audit([], {}, None), 0, 1.0, [("case_stuck", "INVARIANT  case_stuck  b-1 case-1: x")])
        self.assertEqual((written["invariant_reasons"], written["invariant"], written["counts"]["invariant"]),
                         (["case_stuck"], ["INVARIANT  case_stuck  b-1 case-1: x"], 1))


if __name__ == "__main__":
    unittest.main()
