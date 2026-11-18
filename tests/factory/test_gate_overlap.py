"""G6 and G7 on helper machines while G13-G15 use the case box (GatePipeline.overlap_run): recorded in
GATES order as a serial loop would, later lanes cancelled at the first stop, one bench turn at a time,
helper slots shared between dispatches, and queued cheats behind a solving one dropped. Synthetic gates
and helper pools; no models, bench instances or providers."""
import sys
from pathlib import Path as _P
_ROOT = _P(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT / "factory"), str(_ROOT / "bin")]

import contextlib
import fcntl
import json
import pathlib
import tempfile
import threading
import time
import types
import unittest
from contextlib import ExitStack
from unittest import mock

import gate_attempt
import gate_state
import run
from durable import helpers

GATES = ["G1", "G5", "G6", "G13", "G14", "G15", "G7", "G11"]


class Pool:
    """A helper pool whose run() calls `behave(job)` first; `cap` live helpers at most (the Broker's per-case cap)."""
    def __init__(self, behave=lambda job: None, cap=8):
        self.behave, self.cap, self.lock = behave, cap, threading.Lock()
        self.live, self.ran, self.leases = 0, [], 0

    def lease(self):
        with self.lock:
            if self.live >= self.cap: raise helpers.HelperUnavailable("cap")
            self.live += 1; self.leases += 1
            return self.leases

    def run(self, handle, job, key):
        with self.lock: self.ran.append(job["name"])
        self.behave(job)
        return helpers.seal(key, job, {"checkpoint.json": "{}"})

    def release(self, handle, dead):
        with self.lock: self.live -= 1


def dispatch(c, names, label):
    """What G6/G7 do with their cheats: one helper dispatch (real _dispatch, slots and turn hand-over)."""
    jobs = {n: {"name": n} for n in names}
    return helpers._dispatch(c, jobs, lambda job, files: files, lambda: None, label=label, slots=helpers._case_slots(c))


def exercise(test, gates, pool, *, overlap=True, **attrs):
    tmp = tempfile.TemporaryDirectory(); test.addCleanup(tmp.cleanup)
    work = pathlib.Path(tmp.name)
    c = types.SimpleNamespace(args=types.SimpleNamespace(dry_run=False, resume=None, bench_workers=2, no_early_probe=True,
                                                         helper_workers=2, overlap_cheat_gates=overlap, agent_timeout=600),
                              card={"gates": {}, "failed_gate": None, "flakiness_rerun": {"old": 1}},
                              prepared_factory_slots=1, work=work, case=work / "case", helper_pool=pool, seed=5, **attrs)
    c.case.mkdir(); (c.case / "statement.md").write_text("one")
    (work / "logs").mkdir(); (work / "gate-details").mkdir()
    (work / "gate-details" / "G7.json").write_text("old")
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(run, "GATES", GATES))
        for name in ("log", "public_progress", "update_case_budget", "case_budget_boundary"):
            stack.enter_context(mock.patch.object(run, name))
        stack.enter_context(mock.patch.object(run, "g10_overlap_reason", return_value="serial in this test"))
        stack.enter_context(mock.patch.object(run, "parallel_gates", return_value=True))
        for gate in GATES:
            stack.enter_context(mock.patch.object(run, gate.lower(), gates.get(gate, lambda c: (True, {}))))
        c.raised = None
        try: run.run_gates(c)
        except BaseException as error: c.raised = error
    return c


LOCK = [sys.executable, "-c", "import fcntl, sys, time; f = open(sys.argv[1], 'w'); "
        "fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); time.sleep(float(sys.argv[2]))"]


class Overlap(unittest.TestCase):
    def test_g6_waits_on_helpers_while_g13_runs_on_the_case_box(self):
        g13_running = threading.Event()
        def behave(job):
            if job["name"].startswith("g6"):
                self.assertTrue(g13_running.wait(5), "G13 did not run while G6's helpers worked")
        def g6(c):
            dispatch(c, ["g6-a"], "g6-cheat"); return True, {}
        def g13(c):
            g13_running.set(); return True, {}
        c = exercise(self, {"G6": g6, "G13": g13}, Pool(behave))
        self.assertIsNone(c.raised)
        self.assertIsNone(c.card["failed_gate"])
        # Recorded in GATES order although G13 finished first.
        self.assertEqual(list(c.card["gates"]), GATES)
        self.assertEqual(list(c.card["gate_results"]), GATES)

    def test_a_failing_g6_cancels_later_lanes_and_leaves_nothing_behind(self):
        seen, g13_sleeping = {}, threading.Event()
        def behave(job):
            seen["g7"].role_cancel.wait(5)   # G7's first jobs are still running when G6 fails
        def g6(c):
            dispatch(c, [], "g6-cheat")   # gives the case box up, as while its helpers work
            self.assertTrue(g13_sleeping.wait(5))
            c.card["cheats_passed"] = "1/1"
            return False, {"cheats_passed": "1/1"}
        def g7(c):
            seen["g7"] = c
            c.card["flakiness_rerun"] = {"new": 1}
            (c.work / "gate-details" / "G7.json").write_text("new")
            dispatch(c, ["g7-a", "g7-b", "g7-c", "g7-d"], "g7-cheat")
            return True, {}
        def g13(c):
            g13_sleeping.set()
            run.sh(c, ["sleep", "30"])
            return True, {}
        pool = Pool(behave)
        started = time.monotonic()
        c = exercise(self, {"G6": g6, "G7": g7, "G13": g13}, pool)
        self.assertLess(time.monotonic() - started, 15, "G13's bench command was not cancelled")
        self.assertIsNone(c.raised)
        self.assertEqual(c.card["failed_gate"], "G6")
        self.assertEqual([g for g in GATES if g in c.card["gates"]], ["G1", "G5", "G6"])
        self.assertEqual(sorted(pool.ran), ["g7-a", "g7-b"], "G7 kept dispatching after G6 failed")
        self.assertEqual(c.card["flakiness_rerun"], {"old": 1})
        self.assertEqual((c.work / "gate-details" / "G7.json").read_text(), "old")
        self.assertEqual(c.card["cheats_passed"], "1/1")

    def test_the_earliest_failure_in_gate_order_wins(self):
        order = []
        def g7(c):
            order.append("G7"); return False, {"plain": "0/10"}
        def g15(c):
            time.sleep(0.3); order.append("G15"); return False, {"lazy": "kept up"}
        c = exercise(self, {"G7": g7, "G15": g15}, Pool())
        self.assertEqual(order, ["G7", "G15"], "G7 did not run beside G13-G15")
        self.assertEqual(c.card["failed_gate"], "G15")
        self.assertNotIn("G7", c.card["gates"])
        self.assertEqual(c.card["gates"]["G15"], "fail")

    def test_a_stop_in_g7_is_raised_after_the_earlier_gates_are_recorded(self):
        order = []
        def g7(c):
            order.append("G7"); raise run.BudgetError("budget_exhausted")
        def g13(c):
            time.sleep(0.2); order.append("G13"); return True, {}
        c = exercise(self, {"G7": g7, "G13": g13}, Pool())
        self.assertEqual(order, ["G7", "G13"], "G7 did not run beside G13")
        self.assertIsInstance(c.raised, run.BudgetError)
        self.assertEqual(str(c.raised), "budget_exhausted")
        self.assertEqual([g for g in GATES if g in c.card["gates"]], ["G1", "G5", "G6", "G13", "G14", "G15"])
        self.assertEqual(c.card["flakiness_rerun"], {"old": 1})

    def test_one_lane_at_a_time_holds_the_bench_lock(self):
        lock = pathlib.Path(tempfile.mkdtemp()) / ".bench.lock"
        g13_on_box, overlapped = threading.Event(), []
        def bench(c, seconds=0.3):
            p = run.sh(c, LOCK + [lock, seconds], capture=True)
            self.assertEqual(p.returncode, 0, ".bench.lock was held twice")
        def behave(job):
            if job["name"].startswith("g6"): overlapped.append(g13_on_box.wait(5))
        def g6(c):
            dispatch(c, ["g6-a"], "g6-cheat"); bench(c); return True, {}   # verify-negative after the helpers
        def g7(c):
            bench(c); dispatch(c, ["g7-a"], "g7-cheat"); bench(c); return True, {}
        def g13(c):
            g13_on_box.set(); bench(c, 1); return True, {}
        local = lambda c: (bench(c), (True, {}))[1]
        c = exercise(self, {"G6": g6, "G7": g7, "G13": g13, "G14": local, "G15": local}, Pool(behave))
        self.assertEqual(overlapped, [True], "G13 did not run while G6's helpers worked")
        self.assertIsNone(c.raised)
        self.assertIsNone(c.card["failed_gate"])

    def test_a_failing_turn_hand_over_crashes_the_gate_instead_of_hanging(self):
        real, broken = gate_state.digests, threading.Event()
        def digests(c, bench):
            if broken.is_set(): raise OSError("results tree unreadable")
            return real(c, bench)
        def g13(c):
            broken.set(); return True, {}   # the release after this gate cannot list the results
        out = {}
        with mock.patch.object(gate_state, "digests", digests):
            worker = threading.Thread(target=lambda: out.update(c=exercise(self, {"G13": g13}, Pool())), daemon=True)
            worker.start(); worker.join(10)
        self.assertFalse(worker.is_alive(), "the case worker hung waiting for G13's result")
        self.assertIsInstance(out["c"].raised, OSError)

    def test_discarded_gates_are_put_back_before_the_section_publishes(self):
        """The section's exit publishes the deferred engine snapshot: it must not carry a discarded G7."""
        at_exit = {}
        @contextlib.contextmanager
        def section(self_, c):
            yield
            at_exit.update(flakiness=dict(c.card["flakiness_rerun"]),
                           details=(c.work / "gate-details" / "G7.json").read_text())
        def g6(c):
            dispatch(c, [], "g6-cheat"); self.assertTrue(g7_done.wait(5))
            return False, {"cheats_passed": "1/1"}
        g7_done = threading.Event()
        def g7(c):
            c.card["flakiness_rerun"] = {"new": 1}
            (c.work / "gate-details" / "G7.json").write_text("new")
            g7_done.set(); return True, {}
        with mock.patch.object(run.GatePipeline, "section", section):
            c = exercise(self, {"G6": g6, "G7": g7}, Pool())
        self.assertEqual(c.card["failed_gate"], "G6")
        self.assertEqual(at_exit, {"flakiness": {"old": 1}, "details": "old"})

    def test_a_g10_failure_after_a_gate_started_lets_that_gate_finish_first(self):
        """The serial loop checks G10 before starting a gate (once the previous one is recorded); a G10
        rejection that arrives while G13 runs is reported after G13, whose own failure wins."""
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "gate-details").mkdir()
        c = types.SimpleNamespace(work=tmp, card={"gates": {}}, role_cancel=threading.Event())
        pipe = run._gate_pipeline()
        pipe.overlap_lanes, pipe.overlap_card = (("G6",), ("G13",)), {}
        pipe.budget_boundary, pipe.log, pipe.case_hash = (lambda c: None), mock.Mock(), (lambda c: "h")
        pipe.bench = tmp / "bench"
        g10, asked = threading.Event(), []
        def boundary_stop(gate):
            asked.append(gate); return g10.is_set()
        def run_gate(gate, lane):
            if gate == "G13":
                until(lambda: "G13" in asked, 2)   # the boundary before G13 has passed
                g10.set()                          # G10 rejects while G13 is still running
                return gate_attempt.Outcome(False, {"strategy": "kept up"}, 0)
            return gate_attempt.Outcome(True, {}, 0)
        recorded = []
        def record(gate, outcome, started, finished):
            recorded.append(gate); return not outcome.ok
        self.assertTrue(pipe.overlap_run(c, ["G6", "G13"], run_gate, record, boundary_stop))
        self.assertEqual(recorded, ["G6", "G13"])

    def test_off_without_the_launch_flag(self):
        order = []
        g6 = lambda c: (order.append("G6"), (True, {}))[1]
        g13 = lambda c: (order.append("G13"), (True, {}))[1]
        g7 = lambda c: (order.append("G7"), (True, {}))[1]
        c = exercise(self, {"G6": g6, "G7": g7, "G13": g13}, Pool(), overlap=False)
        self.assertEqual(order, ["G6", "G13", "G7"])
        self.assertIsNone(c.card["failed_gate"])

    def test_new_launches_only(self):
        from durable.steps import admit
        self.assertNotIn("overlap_cheat_gates", admit.NEW_CASE_SETTINGS, "adopt_parallel_checks would give it to cases in flight")
        self.assertIn("overlap_cheat_gates", run.ENGINE_SETTINGS)
        self.assertFalse(run.argument_parser().parse_args([]).overlap_cheat_gates)


class Evidence(unittest.TestCase):
    def test_a_gate_never_cites_files_another_lane_wrote(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        bench, results = tmp / "bench", tmp / "bench" / "results"
        results.mkdir(parents=True)
        g13_wrote = threading.Event()
        def behave(job):
            if job["name"].startswith("g6"): self.assertTrue(g13_wrote.wait(5))
        def g6(c):
            dispatch(c, ["g6-a"], "g6-cheat")
            run.sh(c, ["true"]); (results / "g6-negative.json").write_text("6")
            return True, {}
        def g13(c):
            (results / "g13-strategy.json").write_text("13"); g13_wrote.set()
            return True, {}
        saved = {}
        def save(c, gate, info, signature, before, bench_):
            saved[gate] = sorted(rel for (kind, rel) in gate_state.digests(c, bench_) if before.get((kind, rel)) is None)
            return False
        with mock.patch.object(run, "BENCH", bench), mock.patch.object(gate_state, "fingerprint", return_value="f"), \
             mock.patch.object(gate_state, "load", return_value=None), mock.patch.object(gate_state, "save", save):
            c = exercise(self, {"G6": g6, "G13": g13}, Pool(behave), manifest0="m")
        self.assertIsNone(c.card["failed_gate"])
        self.assertEqual(saved["G6"], ["g6-negative.json"])
        self.assertEqual(saved["G13"], ["g13-strategy.json"])

    def test_a_gate_that_ends_on_helpers_saves_its_evidence_holding_the_turn(self):
        """G7 runs plain_and_reference here, gives the case box up and every cheat finishes on helpers: it
        must not digest bench/results while G14 is mid-gate, whose files are not yet in G14's own set."""
        tmp = pathlib.Path(tempfile.mkdtemp())
        bench, results = tmp / "bench", tmp / "bench" / "results"
        results.mkdir(parents=True)
        g14_writing, g7_returned = threading.Event(), threading.Event()
        def behave(job):
            if job["name"].startswith("g7"): self.assertTrue(g14_writing.wait(5))
        def g7(c):
            run.sh(c, ["true"]); (results / "g7-reference.json").write_text("7")
            dispatch(c, ["g7-a"], "g7-cheat")   # every cheat on helpers: no local command after
            g7_returned.set()
            return True, {}
        def g14(c):
            (results / "g14-partial.json").write_text("14"); g14_writing.set()
            g7_returned.wait(5); time.sleep(0.3)   # still mid-gate when G7's evaluation returns
            return True, {}
        saved = {}
        def save(c, gate, info, signature, before, bench_):
            saved[gate] = sorted(rel for (kind, rel) in gate_state.digests(c, bench_) if before.get((kind, rel)) is None)
            return False
        with mock.patch.object(run, "BENCH", bench), mock.patch.object(gate_state, "fingerprint", return_value="f"), \
             mock.patch.object(gate_state, "load", return_value=None), mock.patch.object(gate_state, "save", save):
            c = exercise(self, {"G7": g7, "G14": g14}, Pool(behave), manifest0="m")
        self.assertIsNone(c.card["failed_gate"])
        self.assertEqual(saved["G7"], ["g7-reference.json"])
        self.assertEqual(saved["G14"], ["g14-partial.json"])


def until(condition, seconds=5):
    end = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > end: return False
        time.sleep(0.01)
    return True


class Helpers(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.c = types.SimpleNamespace(work=self.tmp, card={}, args=types.SimpleNamespace(helper_workers=2))

    def test_a_second_dispatch_waits_for_the_first_ones_helpers(self):
        """G7's dispatch while G6's helpers are leased: at the per-case cap it would be refused and run locally."""
        gate = threading.Event()
        pool = Pool(lambda job: gate.wait(5), cap=2)
        self.c.helper_pool = pool
        out = {}
        first = threading.Thread(target=lambda: out.update(g6=dispatch(self.c, ["g6-a", "g6-b"], "g6-cheat")))
        first.start()
        self.assertTrue(until(lambda: pool.live == 2), "the first dispatch did not lease")
        second = threading.Thread(target=lambda: out.update(g7=dispatch(self.c, ["g7-a", "g7-b"], "g7-cheat")))
        second.start()
        time.sleep(0.2); gate.set()
        first.join(10); second.join(30)
        self.assertEqual(sorted(out["g6"]), ["g6-a", "g6-b"])
        self.assertEqual(sorted(out["g7"]), ["g7-a", "g7-b"], "G7's jobs were refused and left to run locally")

    def test_a_cancelled_lane_stops_waiting_for_helper_slots(self):
        hold = threading.Event()
        self.c.helper_pool = Pool(lambda job: hold.wait(10), cap=2)
        first = threading.Thread(target=dispatch, args=(self.c, ["g6-a", "g6-b"], "g6-cheat")); first.start()
        self.assertTrue(until(lambda: self.c.helper_pool.live == 2), "the first dispatch did not lease")
        lane = types.SimpleNamespace(**vars(self.c)); lane.role_cancel = threading.Event()
        threading.Timer(0.2, lane.role_cancel.set).start()
        started = time.monotonic()
        with self.assertRaisesRegex(run.BudgetError, "cancelled"):
            dispatch(lane, ["g7-a"], "g7-cheat")
        self.assertLess(time.monotonic() - started, 8)
        hold.set(); first.join(10)


class SolvingCut(unittest.TestCase):
    """G6/G7 stop at the first solving cheat: helpers drop queued cheats behind one that solved."""
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        case = self.tmp / "case"
        for name in "abcd":
            (case / "guards/cheats" / name).mkdir(parents=True)
            (case / "guards/cheats" / name / "g.js").write_text(name)
        (case / "base").mkdir(); (case / "base/x").write_text("x"); (case / "case.json").write_text("{}")
        self.guards = sorted((case / "guards/cheats").iterdir())
        self.digest = {helpers.digest_of(helpers._tree(g)): g.name for g in self.guards}
        self.c = types.SimpleNamespace(case=case, work=self.tmp / "work", seed=5, card={}, manifest0="m",
                                       args=types.SimpleNamespace(runs=2, helper_workers=0, bench_workers=1))
        self.c.work.mkdir()

    def batch(self, directory, runs, solved):
        directory.mkdir(parents=True, exist_ok=True)
        for i in range(1, runs + 1):
            (directory / f"{i:02}.json").write_text(json.dumps({"run": i, "errors": [], "checker": {"valid": True},
                "judge": {"pass": solved, "paths": {"p": False}, "checks": {"k": solved}, "legit": {"attempted": 1, "placed": 1}}}))
        (directory / "checkpoint.json").write_text(json.dumps({"runs": runs, "pass_runs": runs if solved else 0, "error_runs": 0,
            "invalid_runs": 0, "paths": {"p": {"violated_runs": 0, "runs": runs}}, "checks": {"k": {"ok_runs": runs if solved else 0, "runs": runs}}}))
        return directory

    def local(self, c, scenarios, guard, runs, seed, label, **kw):
        import checkpoint_evidence
        out = self.batch(self.tmp / f"local-{guard.name}", runs, guard.name == "b")
        p = types.SimpleNamespace(returncode=0, stderr="", stdout=checkpoint_evidence.RECEIPT_PREFIX + json.dumps(
            {"version": 1, "path": str(out / "checkpoint.json"), "requested_runs": runs}))
        summary, records, _ = checkpoint_evidence.read_completed(p, runs, label)
        return summary, records

    def cheat_runs(self, gate):
        ran = []
        class Solving:
            def lease(s): return 1
            def run(s, handle, job, key):
                name = self.digest[job["guard"]]; ran.append(name)
                return helpers.execute(job, key, check=lambda j: None,
                                       run=lambda j: self.batch(self.tmp / f"h-{name}", j["runs"], name == "b"))
            def release(s, handle, dead): pass
        failures = []
        g = lambda c: (run.cheat_runs(c, 5, "g6", guards=self.guards, failures=failures, stop_on_pass=True), {})
        with mock.patch.object(run, "checkpoint", side_effect=self.local) as cp, mock.patch.object(run, "case_budget_boundary"), \
             mock.patch.object(run, gate.lower(), g):
            local = run._gate_pipeline().evaluate(self.c, gate)[0]
            self.c.args.helper_workers, self.c.helper_pool = 1, Solving()
            sharded = run._gate_pipeline().evaluate(self.c, gate)[0]
        return local, sharded, ran, failures, cp.call_count

    def test_cheats_queued_behind_a_solving_one_never_dispatch(self):
        local, sharded, ran, failures, local_calls = self.cheat_runs("G6")
        self.assertEqual(local, (1, 4))
        self.assertEqual(sharded, local)
        self.assertEqual(ran, ["a", "b"], "c and d were dispatched after b solved")
        self.assertEqual([pathlib.Path(f).name for f in failures], ["b", "b"])
        self.assertEqual(local_calls, 2, "only the serial pass ran here")   # a, b; the sharded pass ran nothing locally

    def test_other_gates_and_callers_keep_every_job(self):
        _, sharded, ran, _, _ = self.cheat_runs("G4")
        self.assertEqual(sharded, (1, 4))
        self.assertEqual(ran, ["a", "b", "c", "d"])

    def test_g6_and_g7_stop_at_the_first_solving_cheat(self):
        import inspect
        for gate in (run.g6, run.g7):
            self.assertIn("stop_on_pass=True", inspect.getsource(gate))


class Placement(unittest.TestCase):
    def test_g5_never_leases_helpers(self):
        leased = []
        class NoLease:
            def lease(self):
                leased.append(1); raise helpers.HelperUnavailable("test")
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "case/scenarios").mkdir(parents=True); (tmp / "case/base").mkdir(); (tmp / "case/guards/reference").mkdir(parents=True)
        pool = NoLease()
        c = types.SimpleNamespace(case=tmp / "case", work=tmp, seed=1, card={}, helper_pool=pool,
                                  args=types.SimpleNamespace(helper_workers=4, runs=1, scenario_runs=1, rehearse_only=False))
        with mock.patch.object(run, "g5", lambda c: (True, {"shards": run.g5_shards(c)})):
            self.assertEqual(run._gate_pipeline().evaluate(c, "G5"), (True, {"shards": {}}))
        self.assertEqual(leased, [], "G5 leased a helper")
        self.assertIs(c.helper_pool, pool)

    def test_placement_code_is_outside_every_gate_fingerprint(self):
        new = {"evaluate_gate", "overlap_cheat_gates", "OVERLAP_LANES", "OVERLAP_CARD", "sh", "ENGINE_SETTINGS", "argument_parser"}
        for gate in ("G4", "G5", "G6", "G7", "G13", "G14", "G15", "G16"):
            self.assertFalse(new & set(gate_state.runner_inputs(gate)), gate)


if __name__ == "__main__":
    unittest.main()
