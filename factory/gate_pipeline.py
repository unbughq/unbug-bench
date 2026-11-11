"""Gate execution policy: evidence reuse, early feedback and joined scheduling.

Scientific evaluators and runtime effects are injected by the factory composition
root. This module never imports the runner or discovers its globals.
"""
import json
import copy
import contextlib
import contextvars
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from budget import BudgetError
from case_contract import CaseProblem
import gate_attempt
import gate_state


@dataclass
class GatePipeline:
    bench: Path
    evaluate: Callable
    case_hash: Callable
    log: Callable
    publish: Callable
    budget_boundary: Callable
    after_gate: Callable
    overlap_reason: Callable
    gates: tuple
    early_gates: tuple
    saved_cheat_check: Callable
    dry_skip: dict
    # Model/network gates that need no bench instance. When side_lane(c) is true they run in
    # order on their own thread after G1, beside the bench gates, and join before the first
    # gate that follows them (G6, where G10 may start overlapping).
    side_gates: tuple = ()
    side_lane: Callable = lambda c: False
    # A context whose bench commands run on their own reserved instance, for the early gates beside G15
    # (early_parallel); None keeps today's serial early order.
    early_lane: Callable = lambda c: None

    def section(self, c):
        """Defer engine snapshots while two threads work on this case."""
        if getattr(c, "engine", None) is None: return contextlib.nullcontext()
        from durable.checkpoints import concurrent_section
        return concurrent_section(c)

    def window(self, c, gate):
        """One monotonic window for a mechanical gate. Callers wrap every retry in it; nested windows only shrink."""
        import processes  # run.py installs the bench bin path after importing this module
        return (processes.deadline(getattr(getattr(c, 'args', None), 'agent_timeout', 14400))
                if gate in ('G13', 'G14', 'G15') else contextlib.nullcontext())

    def check(self, c, gate):
        """Reuse verified evidence or execute a gate and retain its supporting artifacts."""
        reusable = gate in gate_state.REUSABLE and hasattr(c, "manifest0") and hasattr(c, "case")
        if reusable:
            cached = gate_state.load(c, gate, self.bench)
            if cached is not None:
                if gate in ("G8", "G9"):
                    c.card["reviewers_fairness" if gate == "G8" else "reviewers_realism"] = cached.get("approve")
                return True, {**cached, "reused_verified_evidence": True,
                              "fingerprint_version": c.gate_fingerprint_versions[gate]}
            signature = gate_state.fingerprint(c, gate, self.bench)
            before = {key: gate_state.digest(path) for key, path in gate_state.inventory(c, self.bench).items()}
        try:
            with self.window(c, gate):
                ok, info = self.evaluate(c, gate)
                if info.get('classification') == 'invalid-infra':
                    from run_validity import InvalidInfra
                    raise InvalidInfra('gate execution evidence is incomplete')
        except CaseProblem as error:
            return False, {'problems': [str(error)]}
        if reusable and ok and signature == gate_state.fingerprint(c, gate, self.bench):
            gate_state.save(c, gate, info, signature, before, self.bench)
        return ok, info


    def record_crash(self, c, gate, error):
        directory = c.work / "gate-details"; directory.mkdir(exist_ok=True)
        attempt = 1
        while (directory / f"{gate}.crash-{attempt}.json").exists(): attempt += 1
        (directory / f"{gate}.crash-{attempt}.json").write_text(json.dumps({
            "error": type(error).__name__, "message": str(error)[:20000], "traceback": traceback.format_exc()[:20000]}))
        self.log(c, gate, "crashed", type(error).__name__)


    def early_gate(self, c, gate, on=None):
        """One early gate, executed on `on` (c, or a lane context with its own bench instance). Card,
        log, publication and engine checkpoint are on c; inside a concurrent section the snapshot waits."""
        on = c if on is None else on
        with self.window(c, gate):
            outcome = gate_attempt.execute(
                lambda: self.check(on, gate),
                publish=lambda *args: self.publish(c, 'early:' + gate, *args),
                record_crash=lambda error: self.record_crash(c, gate, error),
                interruption=BudgetError, attempts=1 if getattr(c, "engine", None) is not None else 2, raise_crash=True,
                journal=None if getattr(c, "engine", None) is not None else c.work / "infra-attempts.json",
                identity={"operation": "early-gate", "gate": gate, "case": self.case_hash(c)})
        ok, info = outcome.ok, outcome.info
        self.log(c, gate, "early", "pass" if ok else "FAIL", json.dumps(info), f"{outcome.elapsed_seconds:.0f}s")
        c.card.setdefault("early_gates", {})[gate] = {"ok": ok, "minutes": round((outcome.elapsed_seconds) / 60, 1)}
        if getattr(c, 'engine', None) is not None:
            from durable.checkpoints import checkpoint
            checkpoint(c)
        return ok, info


    def early_sequence(self, c, gates, on=None, *, on_rejection=None, cheats=False):
        """Early gates in order, then (cheats) the saved-cheat sample; writer problems of the first failure, or None."""
        for gate in gates:
            ok, info = self.early_gate(c, gate, on)
            if not ok:
                problems = [f"early check {gate} failed: {json.dumps(info)}"]
                details = c.work / "gate-details" / f"{gate}.json"
                if details.is_file(): problems.append(f"details: {details.read_text()[:8000]}")
                if on_rejection is not None: on_rejection(c, gate, info, problems)
                return problems
            c.early[gate] = (ok, info)
        if not cheats: return None
        c.card.get("early_gates", {}).pop("saved_cheats", None)
        problems = self.saved_cheat_check(c if on is None else on)
        if problems and on_rejection is not None:
            detail = dict(sample="retained_case_cheats",
                summary=copy.deepcopy(c.card.get("early_gates", {}).get("saved_cheats")))
            on_rejection(c, "saved-cheats", detail, problems)
        return problems


    def early_checks(self, c, *, on_rejection=None):
        """G3-G5 right after the writer (~20 min on a cpx42): a case whose bug is not real or whose keys are wrong goes
        back to the writer in the same round, before the stress tester spends time on it. Returns writer problems or None;
        passing results are reused by the gate loop while the case is unchanged.

        When early_lane(c) gives a context, G3 runs first (it rebuilds every bench instance), then G15 runs
        here on the foreground pool while G4, G5 and the saved-cheat sample run on the lane's own instance.
        Both finish; every failure is reported, in serial order. Otherwise the serial order below is kept."""
        c.early = {}
        # G15 needs the complete answer key/ingredients; G1 has validated them before this call.
        g15 = ["G15"] if (c.case / "answer-key.json").is_file() else []
        rest = [g for g in self.early_gates if g != "G3"]
        planned = bool(g15) and "G3" in self.early_gates and self.early_lane(c) is not None
        if not planned:
            problems = self.early_sequence(c, g15 + list(self.early_gates), on_rejection=on_rejection, cheats=True)
        else:
            problems = self.early_sequence(c, ["G3"], on_rejection=on_rejection)
            # G3's memory allowance may lower the worker count; the lane needs the slots it prepared.
            lane = self.early_lane(c) if problems is None else None
            if lane is not None and getattr(c, "prepared_factory_slots", 1) < c.args.bench_workers + 2:
                lane = None
            if problems is None and lane is None:
                self.log(c, "G15", "early serial: reserved bench instance unavailable after G3")
                problems = self.early_sequence(c, g15 + rest, on_rejection=on_rejection, cheats=True)
            elif problems is None:
                problems = self.early_parallel(c, lane, rest, on_rejection)
        if problems:
            c.early = {}
            return problems
        c.early_hash = self.case_hash(c)
        return None


    def early_parallel(self, c, lane, rest, on_rejection):
        """G15 on this thread; the other early gates and the saved-cheat sample on lane's bench instance."""
        self.log(c, "+".join(rest + ["saved-cheats"]), f"early start (beside G15, bench instance {lane.factory_slot})")
        # Each gate cites only its own lane's files: the lane's bench instance and its gates' details.
        own = f"factory-slots/{lane.factory_slot}/"
        details = tuple(f"gate-details/{gate}" for gate in rest)
        lane.evidence_scope = lambda kind, rel: rel.startswith(own) if kind == "bench" else not rel.startswith("gate-details/G15")
        c.evidence_scope = lambda kind, rel: not rel.startswith(own) if kind == "bench" else not rel.startswith(details)
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            with self.section(c):
                future = pool.submit(contextvars.copy_context().run, self.early_sequence, c, rest, lane,
                                     on_rejection=on_rejection, cheats=True)
                try:
                    mine = self.early_sequence(c, ["G15"], on_rejection=on_rejection)
                except BaseException:
                    # Lane commands are cancellable (bench processes are killed); the strategy runs are not.
                    lane.role_cancel.set()
                    with contextlib.suppress(BaseException): future.result()
                    raise
                theirs = future.result()
        finally:
            pool.shutdown(wait=True)
            del c.evidence_scope
        return (mine or []) + (theirs or []) or None


    def early_review(self, c):
        """G8/G9 on the written case (reviewers read it; no bench). Returns writer problems with the reviewers' findings,
        or None; passes are reused by the gate loop while the case is unchanged."""
        early = c.__dict__.setdefault("early", {})
        if not hasattr(c, "early_hash"): c.early_hash = self.case_hash(c)
        problems = []
        for gate, part in (("G8", "fairness"), ("G9", "realism")):
            outcome = gate_attempt.execute(
                lambda: self.check(c, gate),
                publish=lambda *args: self.publish(c, 'early:' + gate, *args),
                record_crash=lambda error: self.record_crash(c, gate, error),
                interruption=BudgetError, attempts=1 if getattr(c, "engine", None) is not None else 2, raise_crash=True,
                journal=None if getattr(c, "engine", None) is not None else c.work / "infra-attempts.json",
                identity={"operation": "early-review", "gate": gate, "case": self.case_hash(c)})
            ok, info = outcome.ok, outcome.info
            self.log(c, gate, "early", "pass" if ok else "FAIL", json.dumps(info), f"{outcome.elapsed_seconds:.0f}s")
            c.card.setdefault("early_gates", {})[gate] = {"ok": ok, "minutes": round(outcome.elapsed_seconds / 60, 1)}
            if getattr(c, 'engine', None) is not None:
                from durable.checkpoints import checkpoint
                checkpoint(c)
            if ok: early[gate] = (ok, info)
            else: problems.append(f"early check {gate} failed: {json.dumps(info)}; reviewer {part} findings: "
                                  + json.dumps([(v.get(part) or {}).get("findings") for v in c.votes])[:8000])
        return problems or None


    def run(self, c, *, replay_gate=None, around_gate=None):
        """Run gates, joining/cancelling the isolated G10 before returning to seal/checkpoint."""
        a = c.args
        def run_gate(gate):
            def invoke():
                if gate in getattr(c, "early", {}) and c.early_hash == self.case_hash(c):
                    ok, info = c.early[gate]
                    return ok, {**info, "reused_from_early_check": True}
                if getattr(c, 'engine', None) is not None:
                    from durable.checkpoints import gate_call
                    from gate_state import inputs
                    import run
                    binding = {"science": inputs(c, gate, run.BENCH),
                               "ruling": getattr(c, "engine_ruling", None)}
                    return gate_call(c, gate, lambda: self.check(c, gate), binding)
                return self.check(c, gate)
            retained = replay_gate(c, gate) if replay_gate else None
            if retained is not None:
                ok, info = retained
                self.publish(c, gate, 'completed' if ok else 'failed', 0, True)
                return gate_attempt.Outcome(ok, info, 0)
            with self.window(c, gate):
                outcome = gate_attempt.execute(
                    (lambda: around_gate(c, gate, invoke)) if around_gate else invoke,
                    publish=lambda *args: self.publish(c, gate, *args),
                    record_crash=lambda error: self.record_crash(c, gate, error), interruption=BudgetError,
                    attempts=1 if getattr(c, "engine", None) is not None else 2, journal=None if getattr(c, "engine", None) is not None else c.work / "infra-attempts.json",
                    identity={"operation": "gate", "gate": gate, "case": self.case_hash(c),
                              "seed": getattr(c, "seed", None), "bench": getattr(c, "manifest0", None), "models": getattr(c, "models", {}),
                              "args": {key: getattr(c.args, key, None) for key in
                                       ("runs", "scenario_runs", "pilot_runs", "pilot_tries", "calibrator_minutes")}})
            return outcome

        def stop_infrastructure(gate, outcome):
            if c.card.get('infrastructure_gate', {}).get('exhausted'): return
            c.stopped = True
            c.exhaustion_occurred = True
            c.card["terminal_stop"] = "infrastructure_exhausted"
            c.card["infrastructure_gate"] = {"gate": gate, "error_type": outcome.info["error"],
                "classification": "invalid-infra", "exhausted": True}
            c.card["gates"][gate] = "invalid-infra"
            c.card.get("gate_results", {}).pop(gate, None)

        def record(gate, outcome, started, finished, quiescent):
            """Card and log entries of one finished gate; True when the loop must stop."""
            ok, info = outcome.ok, outcome.info
            if outcome.crashed:
                stop_infrastructure(gate, outcome)
                return True
            self.log(c, gate, "pass" if ok else "FAIL", json.dumps(info), f"{finished - started:.0f}s")
            c.card["gates"][gate] = "pass" if ok else "fail"
            c.card.setdefault("gate_results", {})[gate] = info
            c.card.setdefault("gate_minutes", {})[gate] = round((finished - started) / 60, 1)
            self.after_gate(c, gate, ok, quiescent)
            if not ok:
                c.card["failed_gate"] = gate
                c.card["failed_detail"] = info.get("problems") or info
                return True
            return False

        def quiet(gate=None):
            # Engine snapshots defer themselves inside a concurrent section, so every boundary may
            # ask for one. Elsewhere only a boundary with no other gate running is quiescent.
            if getattr(c, "engine", None) is not None: return True
            return (future is None or gate == "G10") and lane["future"] is None

        order = list(getattr(c, "audit_gates", self.gates))
        side = ([g for g in order if g in self.side_gates]
                if self.side_gates and not a.dry_run and self.side_lane(c) else [])
        # Start after G1 when it comes first: an invalid case should not reach the reviewers.
        side_after = "G1" if side and "G1" in order and order.index("G1") < order.index(side[0]) else None
        side_join = next((g for g in order[order.index(side[-1]) + 1:] if g not in side), None) if side else None
        lane = {"future": None, "hash": None, "section": None}

        def side_run():
            results = []
            for gate in side:
                self.budget_boundary(c)
                started = time.time()
                outcome = run_gate(gate)
                results.append((gate, outcome, started, time.time()))
                if outcome.crashed or not outcome.ok: break
            return results

        def side_start():
            lane["hash"] = self.case_hash(c)
            lane["section"] = self.section(c)
            lane["section"].__enter__()
            self.log(c, "+".join(side), "start (beside bench gates)")
            lane["future"] = side_pool.submit(contextvars.copy_context().run, side_run)

        def side_finish():
            """Join the lane and record its gates in order. True when the loop must stop."""
            future, lane["future"] = lane["future"], None
            try:
                results = future.result()
            finally:
                section, lane["section"] = lane["section"], None
                section.__exit__(None, None, None)
            if self.case_hash(c) != lane["hash"]:
                # A freshness top-up may edit the case; bench gates beside it saw another revision.
                gate = side[0]
                self.log(c, gate, "case changed while gates ran in parallel")
                c.card["gates"][gate] = "invalid-infra"
                c.card["failed_gate"] = gate
                c.card["failed_detail"] = {"error": "case_changed_during_parallel_gates"}
                return True
            stop = False
            for gate, outcome, started, finished in results:
                stop = record(gate, outcome, started, finished, quiet()) or stop
            return stop

        future, g10_started = None, None
        pool = ThreadPoolExecutor(max_workers=1)
        side_pool = ThreadPoolExecutor(max_workers=1) if side else None
        g10_section = None
        try:
            if side and side_after is None: side_start()
            for gate in order:
                if gate in side: continue
                if lane["future"] is not None and (lane["future"].done() or gate == side_join):
                    if side_finish(): break
                self.budget_boundary(c)
                if a.dry_run and gate in self.dry_skip:
                    c.card["gates"][gate] = f"skipped ({self.dry_skip[gate]})"; continue
                # 2026-10-20: a completed G10 rejection/stop wins at the next boundary;
                # an already-running foreground gate finishes first (its failure wins).
                if future is not None and future.done() and gate != "G10":
                    if not future.result().ok: gate = "G10"
                if gate == "G6" and not (a.dry_run and "G10" in self.dry_skip):
                    reason = self.overlap_reason(c)
                    if reason is None and getattr(c, "prepared_factory_slots", 1) < a.bench_workers + 2:
                        reason = "reserved tester instances were not prepared"
                    if reason:
                        self.log(c, "G10", "serial:", reason)
                    else:
                        c.calibrator_slot_offset = a.bench_workers
                        c.role_cancel = threading.Event()
                        g10_started = time.time()
                        self.log(c, "G10", "start (overlapping bench gates)")
                        g10_section = self.section(c)
                        g10_section.__enter__()
                        future = pool.submit(contextvars.copy_context().run, run_gate, "G10")
                started = g10_started if gate == "G10" and future is not None else time.time()
                if gate == "G10" and future is not None:
                    try:
                        outcome = future.result()  # joined before G11; same card/log format
                    finally:
                        if g10_section is not None:
                            g10_section.__exit__(None, None, None); g10_section = None
                else:
                    outcome = run_gate(gate)
                if record(gate, outcome, started, time.time(), quiet(gate)): break
                if side_after == gate and side: side_start()
            if lane["future"] is not None:
                failed = c.card.get("failed_gate")
                detail = c.card.get("failed_detail")
                side_finish()
                later = c.card.get("failed_gate")
                if failed and later != failed and order.index(failed) < order.index(later):
                    # Report the earliest failure in gate order, where a serial pass would have stopped.
                    c.card["failed_gate"], c.card["failed_detail"] = failed, detail
            if not c.card.get("failed_gate"): self.budget_boundary(c)
        finally:
            error = sys.exc_info()[1]
            try:
                if future is not None:
                    budget_boundary = isinstance(error, BudgetError) and str(error) == 'budget_exhausted'
                    cancelling = not future.done() and not budget_boundary
                    if cancelling: c.role_cancel.set()
                    pool.shutdown(wait=True)  # model cancellation kills its process group
                    if g10_section is not None:
                        g10_section.__exit__(None, None, None); g10_section = None
                    # Stop/provider errors in the tester must reach main's checkpoint path.
                    try:
                        outcome = future.result()
                        if outcome.crashed and not c.card.get('failed_gate'):
                            stop_infrastructure('G10', outcome)
                    except BudgetError as error:
                        if not (cancelling and str(error) == "cancelled"): raise
                else:
                    pool.shutdown(wait=True)
            finally:
                if lane["future"] is not None:
                    # An exception left the lane running: let it finish (reviewer calls have no
                    # cancellation), then leave its section so the deferred snapshot publishes.
                    try: lane["future"].result()
                    except BaseException: pass
                    lane["future"] = None
                if lane["section"] is not None:
                    lane["section"].__exit__(None, None, None); lane["section"] = None
                if side_pool is not None: side_pool.shutdown(wait=True)


