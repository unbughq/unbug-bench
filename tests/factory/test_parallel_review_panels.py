"""The G8/G9 reviewers run together; the early probe still finishes before G16. Synthetic reviewers,
probe and gates; no models, bench instances or providers."""
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin")]

import pathlib
import tempfile
import threading
import time
import types
import unittest
from contextlib import ExitStack
from decimal import Decimal
from unittest import mock

import budget
import gate_state
import run
from durable import checkpoints as cp


def panel_context(test):
    tmp = tempfile.TemporaryDirectory(); test.addCleanup(tmp.cleanup)
    work = pathlib.Path(tmp.name)
    c = types.SimpleNamespace(work=work, case=work / "case", card={}, args=types.SimpleNamespace(resume=None, dry_run=False),
                              models={"reviewers": [["claude/opus"], ["codex/gpt"]]},
                              engine=types.SimpleNamespace(key="case-x/1/gates/1"), ledger=work / "ledger.json")
    c.engine_checkpoint = lambda: True
    c.case.mkdir(); (c.case / "statement.md").write_text("one")
    return c


def run_review(test, c, answer, *, fits=True):
    with ExitStack() as stack:
        for name, value in (("retained_answer", answer), ("prompt", lambda *a: "synthetic"),
                            ("run_context", lambda *a, **k: ""), ("case_inventory", lambda c: {}),
                            ("engine_review_ruling", lambda c: ""), ("case_hash", lambda c: "h")):
            stack.enter_context(mock.patch.object(run, name, value))
        stack.enter_context(mock.patch.object(run.model_router, "_bounded_routes",
                                              lambda model, accounts: [{"max_usd": 10}, {"max_usd": 12.5}]))
        stack.enter_context(mock.patch.object(budget, "invocation_headroom",
                                              lambda path, attempt: Decimal(25 if fits else 24)))
        return run.review(c)


def index(name):
    return int(name.rsplit("-", 1)[1])


class Panel(unittest.TestCase):
    def test_both_reviewers_run_at_once_and_votes_keep_panel_order(self):
        met = threading.Barrier(2, timeout=3)
        finished = []
        def answer(rc, chain, text, cwd, name, out, *rest):
            met.wait()   # one reviewer after the other breaks this barrier
            i = index(name)
            if i == 1: time.sleep(0.2)
            rc.router_excluded = (f"pool/route-{i}",)
            finished.append(i)
            return {"reviewer": i}
        c = panel_context(self)
        self.assertEqual(run_review(self, c, answer), [{"reviewer": 1}, {"reviewer": 2}])
        self.assertEqual(finished, [2, 1])
        self.assertEqual(c.votes_hash, "h")
        self.assertEqual(set(c.router_excluded), {"pool/route-1", "pool/route-2"})
        self.assertTrue((c.work / "review-1/case/statement.md").is_file() and (c.work / "review-2/case/statement.md").is_file())

    def test_a_failed_reviewer_lets_the_other_finish_and_sets_no_votes(self):
        finished = []
        def answer(rc, chain, text, cwd, name, out, *rest):
            if index(name) == 1: raise run.BudgetError("model_call_cap")
            time.sleep(0.2); finished.append(2)
            return {"reviewer": 2}
        c = panel_context(self)
        with self.assertRaisesRegex(run.BudgetError, "model_call_cap"):
            run_review(self, c, answer)
        self.assertEqual(finished, [2], "reviewer 2 keeps its answer for the retry")
        self.assertEqual(c.votes, [])
        self.assertFalse(hasattr(c, "votes_hash"))

    def test_a_failed_second_reviewer_keeps_the_first_vote_as_serially(self):
        def answer(rc, chain, text, cwd, name, out, *rest):
            if index(name) == 2: raise run.BudgetError("model_call_cap")
            return {"reviewer": 1}
        c = panel_context(self)
        with self.assertRaisesRegex(run.BudgetError, "model_call_cap"):
            run_review(self, c, answer)
        self.assertEqual(c.votes, [{"reviewer": 1}])
        self.assertFalse(hasattr(c, "votes_hash"))

    def test_short_headroom_runs_the_reviewers_one_after_the_other(self):
        active, overlap = [], []
        def answer(rc, chain, text, cwd, name, out, *rest):
            active.append(name); overlap.append(len(active)); time.sleep(0.1); active.remove(name)
            return {"reviewer": index(name)}
        c = panel_context(self)
        self.assertEqual(run_review(self, c, answer, fits=False), [{"reviewer": 1}, {"reviewer": 2}])
        self.assertEqual(overlap, [1, 1])

    def test_holds_fit_needs_every_largest_hold_at_once_and_the_engine(self):
        c = panel_context(self)
        with mock.patch.object(run.model_router, "_bounded_routes", lambda model, accounts: [{"max_usd": 10}, {"max_usd": 12.5}]):
            for headroom, fits in ((24, False), (25, True)):
                with mock.patch.object(budget, "invocation_headroom", lambda path, attempt: Decimal(headroom)):
                    self.assertIs(run.holds_fit(c, ["a", "b"]), fits)
            with mock.patch.object(budget, "invocation_headroom", side_effect=run.BudgetError("usage_unknown")):
                self.assertFalse(run.holds_fit(c, ["a"]))
            del c.engine
            self.assertFalse(run.holds_fit(c, ["a"]))


GATES = ["G1", "G2", "G3", "G4", "G5", "G16", "G8", "G9", "G6", "G13", "G7", "G11"]


def gates(test, fakes, probe, *, overlap=True):
    """The gate pipeline under the engine with synthetic gates and probe; overlap: G10's conditions hold."""
    tmp = tempfile.TemporaryDirectory(); test.addCleanup(tmp.cleanup)
    work = pathlib.Path(tmp.name)
    c = types.SimpleNamespace(args=types.SimpleNamespace(dry_run=False, resume=None, bench_workers=2, no_early_probe=False),
                              card={"gates": {}, "failed_gate": None}, prepared_factory_slots=4, work=work, case=work / "case",
                              models={"strong_calibrator": ["claude/opus"], "reviewers": [["codex/gpt"], ["claude/opus"]]},
                              engine=types.SimpleNamespace(key="case-x/1/gates/1"))
    c.engine_checkpoint = lambda: True
    c.case.mkdir(); (c.case / "statement.md").write_text("one")
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(run, "GATES", GATES))
        for name in ("log", "public_progress", "update_case_budget", "case_budget_boundary"):
            stack.enter_context(mock.patch.object(run, name))
        stack.enter_context(mock.patch.object(run, "g10_overlap_reason", return_value=None if overlap else "memory"))
        stack.enter_context(mock.patch.object(run, "parallel_gates", return_value=True))
        stack.enter_context(mock.patch.object(run, "early_probe", probe))
        stack.enter_context(mock.patch("gate_state.inputs", return_value={}))
        stack.enter_context(mock.patch.object(cp, "gate_call", lambda c, gate, invoke, binding: invoke()))
        for gate in GATES:
            stack.enter_context(mock.patch.object(run, gate.lower(), fakes.get(gate, lambda c: (True, {}))))
        run.run_gates(c)
    return c


class ProbeBeforeG16(unittest.TestCase):
    def test_the_probe_finishes_before_g16_whatever_the_overlap(self):
        # G16's independent review reads the probe's transcripts (fairness.review_attempts), so they
        # must be complete when G16 starts, as on origin: moving the probe is a grading change.
        for overlap in (True, False):
            with self.subTest(overlap=overlap):
                order = []
                def probe(p, user="pilot"):
                    time.sleep(0.2); order.append(("probe", user))
                def g16(c):
                    order.append("G16"); return True, {}
                gates(self, {"G16": g16}, probe, overlap=overlap)
                self.assertEqual(order, [("probe", "pilot"), "G16"])


class Identity(unittest.TestCase):
    def test_only_the_g8_g9_runner_identity_holds_the_new_code(self):
        moved = {"review", "holds_fit"}
        for gate in run.GATES:
            found = gate_state.source_inputs(gate.lower(), *gate_state.EXTRA_ROOTS.get(gate, ()))
            expected = {"review", "holds_fit"} if gate in ("G8", "G9") else set()
            self.assertEqual(moved & found.keys(), expected, gate)
        # sealed_audit's calibration identity, and G10/G16's shared roots.
        self.assertFalse(moved & gate_state.source_inputs("calibrate", "make_pilots", "calibration_identity").keys())


if __name__ == "__main__": unittest.main()
