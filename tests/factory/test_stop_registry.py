"""The stop registry covers every recordable reason, and the stop audit's verdicts from fake attempts."""
import ast
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
WORKER_STEP = re.compile(r'self\._step\(\w+, "([a-z][a-z_]*)"')
FIX, OTHER_FIX, OLD, NEW = "f" * 40, "e" * 40, "a" * 40, "b" * 40


def recordable() -> set:
    fixed = (classify.REASONS | classify.CONTRACT_REASONS | classify.WORKER_POOL_REASONS
             | classify.IMPORT_REASONS | classify.REJECTION_REASONS | classify.BOARD_REASONS)
    sources = [*(ROOT / "factory").rglob("*.py"), *(ROOT / "control/campaign").glob("*.py")]
    literals = {m.group(1) for p in sources for m in LITERAL.finditer(p.read_text())}
    # workers.BoatPool._step(worker, "<name>", ...) raises PoolError(f"infra:{name}").
    steps = {"infra:" + m.group(1) for m in WORKER_STEP.finditer((ROOT / "factory/durable/workers.py").read_text())}
    return fixed | steps | {r for r in literals if not r.endswith("_")}   # "admit:dedup_" etc. are prefixes


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


# Stop arguments the scan cannot read as a label, each with why that is safe. Keyed by file and argument source.
# The key is the innermost expression the scan could not read.
UNREAD_STOPS = {
    # Copies of a stop already raised or written elsewhere: its label was scanned where it was made.
    ("factory/budget.py", "ledger.get('terminal_stop')"): "shared_stop re-raises the ledger's own stop",
    ("factory/budget.py", "str(previous)"): "admission refused after an earlier stop (wrapped)",
    ("factory/budget.py", "str(error)"): "a raised error's own label (or class name), copied",
    ("factory/run.py", "hosted[i]['stopped']"): "a hosted call's stop, raised by its own run_budgeted",
    ("factory/run.py", "interruption_label(error)"): "calibration.interruption_label: a raised stop's head",
    ("factory/g11_review.py", "interruption_label(error)"): "calibration.interruption_label: a raised stop's head",
    # model_runtime.pinned_cli's pre-launch CLI version check, never inside run_budgeted: classify._CLI_VERSION
    # names the whole family infra:cli_version, and no route takes it.
    ("factory/model_runtime.py", "f'{kind}_cli_not_{want}'"): "infra:cli_version family, raised before launch",
}


class Unread(Exception):
    pass


def _text(node):
    """The whole constant text of a string expression, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and all(isinstance(v, ast.Constant) for v in node.values):
        return "".join(v.value for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _text(node.left), _text(node.right)
        return None if left is None or right is None else left + right
    return None


def _prefix(node):
    """The constant text a string expression starts with."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        lead = ""
        for v in node.values:
            if not isinstance(v, ast.Constant): break
            lead += v.value
        return lead
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _text(node.left)
        return _prefix(node.left) if left is None else left + _prefix(node.right)
    return ""


def stop_labels(root: Path = ROOT) -> tuple:
    """({label head: first source line}, {(file, expression): line} of what it could not read), for every stop
    label the factory raises or writes as a stop: the text of BudgetError(...) or ContainmentError(...), and any
    value written to a terminal_stop. A constant, a constant head before ":" ('refusal:' + model,
    f"provider_preflight_failed:{role}:..."), a wrapper ("Budget stopped: " + cause), `a if c else b`, a local name
    assigned such values, or a parameter's default and same-module call arguments are read; anything else is
    unread, and fails the test unless UNREAD_STOPS says why it is safe."""
    found, unread = {}, {}
    for path in [*(root / "factory").rglob("*.py"), root / "bin/processes.py"]:
        tree = ast.parse(path.read_text(), str(path))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        functions = (ast.FunctionDef, ast.AsyncFunctionDef)

        def assigned(name, node):
            """Values a name holds at node: its assignments in the functions around it, innermost first, else a
            parameter's default and the arguments same-module calls pass it."""
            while node in parents:
                node = parents[node]
                if not isinstance(node, (*functions, ast.Module)):
                    continue
                values = [a.value for a in ast.walk(node) if isinstance(a, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == name for t in a.targets)]
                if values:
                    return values
                if isinstance(node, functions):
                    args = node.args.posonlyargs + node.args.args
                    if name in [a.arg for a in args]:
                        index = [a.arg for a in args].index(name)
                        defaults = dict(zip([a.arg for a in args][len(args) - len(node.args.defaults):],
                                            node.args.defaults))
                        if name not in defaults:
                            raise Unread(name)
                        calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
                                 and getattr(c.func, "id", getattr(c.func, "attr", None)) == node.name]
                        return [defaults[name], *(c.args[index] for c in calls if len(c.args) > index),
                                *(k.value for c in calls for k in c.keywords if k.arg == name)]
            raise Unread(name)

        def heads(node):
            if isinstance(node, ast.Constant) and node.value is None:
                return set()   # no stop (budget.py's cause when no limit is hit)
            if isinstance(node, ast.IfExp):
                return heads(node.body) | heads(node.orelse)
            if isinstance(node, ast.Name):
                return set().union(*(heads(v) for v in assigned(node.id, node)))
            wrapper = next((w for w in classify._WRAPPERS if _prefix(node).startswith(w)), None)
            if (wrapper and isinstance(node, ast.BinOp) and _text(node.left) == wrapper):
                return heads(node.right)   # "Budget stopped: " + cause: the label is cause's
            text = _text(node)
            lead = (text if text is not None else _prefix(node))[len(wrapper or ""):]
            if text is None and ":" not in lead:
                raise Unread(ast.unparse(node))
            return {lead.partition(":")[0]}

        for node in ast.walk(tree):
            values = []
            if isinstance(node, ast.Call):
                func = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                if func in ("BudgetError", "ContainmentError") and node.args:
                    values.append(node.args[0])
                values += [k.value for k in node.keywords if k.arg == "terminal_stop"]
                if (func == "setdefault" and len(node.args) == 2 and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "terminal_stop"):
                    values.append(node.args[1])
            elif isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                       and t.slice.value == "terminal_stop" for t in node.targets):
                    values.append(node.value)
            where = f"{path.relative_to(root)}:{node.lineno}" if values else None
            for value in values:
                try:
                    for head in heads(value):
                        found.setdefault(head, where)
                except Unread as error:
                    key = (str(path.relative_to(root)), str(error))
                    unread.setdefault(key, where)
    return found, unread


class StopScopeTests(unittest.TestCase):
    def test_every_raised_or_written_stop_label_declares_its_scope(self):
        from durable.stop_registry import STOPS
        labels, unread = stop_labels()
        for seen in ("opencode_error", "provider_preflight_failed", "extension_snapshot_changed", "cost_limit"):
            self.assertIn(seen, labels)   # the scan itself still reads constants, f-heads, defaults, wrappers
        self.assertEqual({k: v for k, v in unread.items() if k not in UNREAD_STOPS}, {},
                         "the scan cannot read these stop labels: name them, or add a reason to UNREAD_STOPS")
        self.assertEqual(set(UNREAD_STOPS) - set(unread), set(), "these UNREAD_STOPS entries are stale")
        missing = {label: where for label, where in labels.items() if label not in STOPS}
        self.assertEqual(missing, {}, "give these a scope in factory/durable/stop_registry.py STOPS")

    def test_every_scope_is_call_or_case_and_every_reroute_a_router_reason(self):
        from durable.stop_registry import STOPS
        from model_router import REASONS
        for label, entry in STOPS.items():
            self.assertIn(entry["scope"], ("call", "case"), label)
            self.assertIn(entry["reroute"], (None, "outage_if_short", "outage_if_free", *REASONS), label)

    def test_a_label_reads_by_its_head_and_an_unknown_label_fails_closed(self):
        from durable.stop_registry import stop
        self.assertEqual(stop("provider_limit:claude/claude-opus-5-5"), {"scope": "call", "reroute": "quota"})
        self.assertEqual(stop("budget_exhausted:grant_insufficient")["scope"], "case")
        self.assertEqual(stop("never_given_a_scope"), {"scope": "case", "reroute": None})
        self.assertEqual(stop("KeyError", exception=True), {"scope": "call", "reroute": None})
        self.assertEqual(stop("PauseRequested", exception=True)["scope"], "case")
        # A ledger another call already stopped is not this call's provider error: no next route.
        self.assertEqual(stop("Budget ledger stopped: opencode_error"), {"scope": "case", "reroute": None})

    def test_the_scan_reads_every_label_shape_and_reports_what_it_cannot(self):
        # The review's probe (15 November): each shape a new stop label can take is either read or reported.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "factory").mkdir(); (root / "bin").mkdir()
            (root / "bin/processes.py").write_text("")
            (root / "factory/probe.py").write_text(
                "from budget import BudgetError\n"
                "def a(): raise BudgetError('new_label')\n"
                "def b(): raise BudgetError(f'new_fstring')\n"
                "def c(x): raise BudgetError(f'{x}_new_lead')\n"
                "def d(reason): raise BudgetError(reason)\n"
                "def e(): raise BudgetError('new_concat_' + 'x')\n"
                "def f():\n    label = 'new_via_name'\n    raise BudgetError(label)\n"
                "def g(ledger): ledger.update(terminal_stop='new_kw')\n"
                "def i(): raise BudgetError(f'new_nocolon_{1}')\n"
                "def j(model): raise BudgetError('new_head:' + model)\n"
                "def k(label='new_default'): raise BudgetError(label)\n"
                "def m(): k('new_passed')\n"
                "def n(cause): raise BudgetError('Budget stopped: ' + cause)\n")
            found, unread = stop_labels(root)
        self.assertEqual(set(found), {"new_label", "new_fstring", "new_concat_x", "new_via_name", "new_kw",
                                      "new_head", "new_default", "new_passed"})
        self.assertEqual({e for _, e in unread}, {"f'{x}_new_lead'", "reason", "f'new_nocolon_{1}'", "cause"})


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
    """Each live invariant from fake attempt, ledger and budget rows."""
    BUDGET = {"b-1": {"bound": 10_000, "held": 0, "spent": 5_000, "waste": 1_000}}
    SENTINEL = object()

    def checks(self, attempts=(), ledger=SENTINEL, budgets=SENTINEL):
        ledger = {"case-1/2/writer:1/1": booked()} if ledger is self.SENTINEL else ledger
        return [c for c, _ in invariants(list(attempts), ledger, self.BUDGET if budgets is self.SENTINEL else budgets)]

    def test_a_consistent_batch_breaks_nothing(self):
        self.assertEqual(self.checks([attempt()]), [])

    def test_booked_spend_below_reported_usage(self):
        self.assertEqual(self.checks([attempt(paid=900)]), ["spend_below_usage"])
        self.assertEqual(self.checks([attempt(paid=900)], ledger={}), ["spend_below_usage"])   # never booked
        lost = {"case-1/2/writer:1/1": booked(state="lost", paid=0, granted=1000)}
        self.assertEqual(self.checks([attempt(paid=900)], ledger=lost), [])                    # lost books the grant
        held = {"case-1/2/writer:1/1": booked(state="held", paid=0)}
        self.assertEqual(self.checks([attempt(paid=900)], ledger=held), [])                    # not settled yet

    def test_a_batch_over_its_bound_by_the_ledger_s_own_rule(self):
        self.assertEqual(self.checks(budgets={"b-1": {"bound": 10_000, "held": 0, "spent": 10_001, "waste": 0}}),
                         ["batch_over_bound"])
        self.assertEqual(self.checks(budgets={"b-1": {"bound": 10_000, "held": 6_000, "spent": 5_000, "waste": 0}}),
                         ["batch_over_bound"])                                            # holds count as used
        self.assertEqual(self.checks(budgets={"b-1": {"bound": 10_000, "held": 0, "spent": 10_000, "waste": 0}}), [])

    def test_waste_booked_to_the_case_s_own_money(self):
        broken = attempt(outcome="infra_error", reason="infra:stalled", waste=True)
        self.assertEqual(self.checks([broken]), ["waste_on_case_money"])
        for fine in (booked(waste=True), booked(rebooked=True), booked(case_money=False)):
            self.assertEqual(self.checks([broken], ledger={"case-1/2/writer:1/1": fine}), [])

    def test_one_attempt_recorded_with_two_results(self):
        self.assertEqual(self.checks([attempt(), attempt()]), [])                       # read twice, same result
        twice = self.checks([attempt(), attempt(outcome="infra_error", reason="infra:cancelled")])
        self.assertEqual(twice, ["attempt_recorded_twice"])

    def test_a_diagnosis_and_the_next_step_may_share_a_seq(self):
        # 1bb2ad 16 November: a factory_bug rerun in place numbered writer:4 at the diagnosis's seq 8.
        diagnosis = attempt(key="case-1/8/diagnosis/1", seq=8, reason="diagnosis:completed", paid=0)
        writer = attempt(key="case-1/8/writer:4/1", seq=8, paid=0)
        self.assertEqual(self.checks([diagnosis, writer]), [])

    def test_an_unreadable_section_skips_only_its_own_checks(self):
        twice = [attempt(paid=900), attempt(outcome="infra_error", reason="infra:cancelled", paid=900)]
        over = {"b-1": {"bound": 1, "held": 0, "spent": 2, "waste": 0}}
        self.assertEqual(self.checks(twice, ledger=None, budgets=over), ["attempt_recorded_twice", "batch_over_bound"])
        self.assertEqual(self.checks(twice, budgets=None), ["attempt_recorded_twice", "spend_below_usage"])

    def test_decode_gives_the_ledger_key_and_the_waste_rule(self):
        record = {"input": {"case_id": "case-1", "batch_id": "b-1", "seq": 2, "attempt": 1, "plumbing_version": "p",
                            "step": {"kind": "writer", "round": 1}},
                  "result": {"outcome": "provider_limit", "reason": "router:quota",
                             "usage": {"calls": 1, "paid_usd_micros": 7, "list_usd_micros": 9}}}
        row = decode(base64.b64encode(pickle.dumps(record)).decode())
        self.assertEqual((row["key"], row["paid_usd_micros"], row["settles_as_waste"]), ("case-1/2/writer:1/1", 7, True))
        record["input"]["step"] = {"kind": "admit", "round": 0}
        self.assertEqual(decode(base64.b64encode(pickle.dumps(record)).decode())["key"], "case-1/2/admit/1")

    def test_a_paid_credit_park_stop_booked_to_the_case_is_no_broken_invariant(self):
        # Goldfish 16 November: under credit_park a router:credit stop's spend is the case's (its
        # snapshot keeps the work); the audit's own copy of the waste rule called that broken.
        record = {"input": {"case_id": "case-1", "batch_id": "b-1", "seq": 2, "attempt": 1, "plumbing_version": "p",
                            "step": {"kind": "writer", "round": 1}},
                  "result": {"outcome": "provider_limit", "reason": "router:credit",
                             "usage": {"calls": 1, "paid_usd_micros": 1_200_000}}}
        row = decode(base64.b64encode(pickle.dumps(record)).decode())
        self.assertEqual(self.checks([row], ledger={row["key"]: booked(paid=1_200_000)}), [])

    def test_violations_reach_the_result_file(self):
        line = "INVARIANT  batch_over_bound  b-1: held 0 + spent 2 > bound 1"
        written = result(audit([], {}, None), 0, 1.0, [("batch_over_bound", line)])
        self.assertEqual((written["invariant_reasons"], written["invariant"], written["counts"]["invariant"]),
                         (["batch_over_bound"], [line], 1))


if __name__ == "__main__":
    unittest.main()
