"""Gate execution policy: evidence reuse, early feedback and joined scheduling.

Scientific evaluators and runtime effects are injected by the factory composition
root. This module never imports the runner or discovers its globals.
"""
import json
import copy
import os
import queue
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


def import_facts(error):
    """Where an ImportError looked, read at the crash (1108c, 18 November: G2 loaded the baked bench's
    admission.py though the release dir has its own): the path, the release dir's cached finder, and
    whether the module's file is listed in that dir right now."""
    here = Path(__file__).resolve().parent
    name = (error.name or "").split(".")[0]
    files = (f"{name}.py", name)   # a module or a package
    finder = sys.path_importer_cache.get(str(here), "absent")
    facts = {"module": name, "sys_path": list(sys.path), "release_factory": str(here),
             "release_finder": finder if finder in ("absent", None) else type(finder).__name__,
             "finder_mtime": getattr(finder, "_path_mtime", None),
             "finder_lists_module": any(f in getattr(finder, "_path_cache", ()) for f in files)}
    try:
        facts["release_mtime"] = os.stat(here).st_mtime
        facts["release_lists_module"] = any(f in os.listdir(here) for f in files)
    except OSError as failure:
        facts["release_lists_module"] = type(failure).__name__
    return facts


class _Tickets:
    """First come, first served: lanes take the case box's bench turn in the order they asked for it."""
    def __init__(self):
        self.cv, self.next, self.serving = threading.Condition(), 0, 0

    def take(self):
        with self.cv:
            self.next += 1
            return self.next - 1

    def wait(self, ticket):
        with self.cv: self.cv.wait_for(lambda: self.serving == ticket)

    def done(self):
        with self.cv:
            self.serving += 1
            self.cv.notify_all()


class BenchTurn:
    """One overlap lane's turn on the case box's bench instances. Bench commands take .bench.lock without
    waiting, so only the lane holding the turn runs local bench work; a lane waiting on helpers gives it
    up (durable.helpers._dispatch). The inventory files that change while a lane holds the turn are its
    own (`mine`): the other lanes' evidence leaves them out. The first ticket is taken when the lane is
    made, so lanes first run in the order they were made."""
    def __init__(self, tickets, files, mine):
        self.tickets, self.files, self.mine = tickets, files, mine
        self.first, self.held, self.before = tickets.take(), False, {}

    def acquire(self):
        ticket, self.first = (self.tickets.take() if self.first is None else self.first), None
        self.tickets.wait(ticket)
        try:
            self.before = self.files()
        except BaseException:
            self.tickets.done()
            raise
        self.held = True

    def release(self):
        if not self.held: return
        self.held = False
        try:
            after = self.files()
            self.mine.update(k for k in after.keys() | self.before.keys() if after.get(k) != self.before.get(k))
        finally:
            self.tickets.done()


def hold_turn(c):
    """An overlap lane that gave the case box up (helpers._dispatch) takes its turn back before it
    reads the bench: another lane's files are only known as its own once that lane gives the turn up."""
    turn = getattr(c, "bench_turn", None)
    if turn is not None and not turn.held: turn.acquire()


_MISSING = object()


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
    # (gate, before): the lane's first gate is recorded before `before` is recorded, so a failure there
    # stops the loop ahead of whatever `before`'s after_gate spends (G2 before G5's early probe).
    side_early: tuple = ()
    # A context whose bench commands run on their own reserved instance, for the early gates beside G15
    # (early_parallel); None keeps today's serial early order.
    early_lane: Callable = lambda c: None
    # Raises BudgetError before the first bench gate when G10's strong calls could not be funded.
    money_headroom: Callable = lambda c: None
    # Lanes of consecutive gates that run at once from the first one when overlap(c) is true (G6 and G7,
    # whose cheats run on helper machines, beside G13-G15 on the case box), recorded in gate order
    # (overlap_run). overlap_card names the card keys each of them writes, restored when it is discarded.
    overlap_lanes: tuple = ()
    overlap: Callable = lambda c: False
    overlap_card: dict = None

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
        hold_turn(c)
        reusable = gate in gate_state.REUSABLE and hasattr(c, "manifest0") and hasattr(c, "case")
        if reusable:
            held = c.__dict__.setdefault("gate_cached", set())   # passes gate-cache holds (checkpoints.gate_call)
            held.discard(gate)
            cached = gate_state.load(c, gate, self.bench)
            if cached is not None:
                held.add(gate)
                if gate in ("G8", "G9"):
                    c.card["reviewers_fairness" if gate == "G8" else "reviewers_realism"] = cached.get("approve")
                if gate == "G7": c.card["flakiness_rerun"] = {k: v for k, v in cached.items() if k != "reused_verified_evidence"}
                return True, {**cached, "reused_verified_evidence": True,
                              "fingerprint_version": c.gate_fingerprint_versions[gate]}
            signature = gate_state.fingerprint(c, gate, self.bench)
            before = gate_state.digests(c, self.bench)
            gate_state.forget_receipts(c, gate)
        try:
            with self.window(c, gate):
                ok, info = self.evaluate(c, gate)
                if info.get('classification') == 'invalid-infra':
                    from run_validity import InvalidInfra
                    raise InvalidInfra('gate execution evidence is incomplete')
        except CaseProblem as error:
            return False, {'problems': [str(error)]}
        if reusable and ok: hold_turn(c)   # a gate that ended on helpers digests no other lane's half-written files
        if reusable and ok and signature == gate_state.fingerprint(c, gate, self.bench):
            if gate_state.save(c, gate, info, signature, before, self.bench): c.gate_cached.add(gate)
            # Published now, not at the next quiescent point, which a lane beside this gate may delay for
            # hours. Side-lane passes are kept at the join: the next review() renames their evidence.
            if getattr(c, "engine", None) is not None and gate not in self.side_gates:
                from durable.checkpoints import progress
                progress(c, gate, self.bench)
        return ok, info


    def record_crash(self, c, gate, error):
        directory = c.work / "gate-details"; directory.mkdir(exist_ok=True)
        attempt = 1
        while (directory / f"{gate}.crash-{attempt}.json").exists(): attempt += 1
        (directory / f"{gate}.crash-{attempt}.json").write_text(json.dumps({
            "error": type(error).__name__, "message": str(error)[:20000], "traceback": traceback.format_exc()[:20000],
            **({"imports": import_facts(error)} if isinstance(error, ImportError) else {})}, default=str))
        # Where, without the message (it may quote case paths): the innermost non-stdlib frame and the record
        # holding the full traceback (cae763, 14 November: the log said only FileNotFoundError).
        frames = [f for f in traceback.extract_tb(error.__traceback__) if not f.filename.startswith(traceback.__file__.rsplit('/', 1)[0])]
        self.log(c, gate, "crashed", type(error).__name__, *[f"at {f.filename.rsplit('/', 1)[-1]}:{f.lineno}" for f in frames[-1:]],
                 f"(gate-details/{gate}.crash-{attempt}.json)")


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
        # Each gate cites only its own lane's bench instance; gate_state.owned keeps its work files its own.
        own = f"factory-slots/{lane.factory_slot}/"
        lane.evidence_scope = lambda kind, rel: kind != "bench" or rel.startswith(own)
        c.evidence_scope = lambda kind, rel: kind != "bench" or not rel.startswith(own)
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


    def overlap_run(self, c, gates, run_gate, record, boundary_stop):
        """The overlap lanes at once, each on its own copy of c (shared card, own role_cancel and bench
        turn), inside one concurrent section. Results are recorded in gate order as a serial loop would:
        once a gate stops the loop, every later lane is cancelled at once and the later gates are
        discarded (card keys, gate-details and progress put back), an exception is raised at its gate's
        turn and a G10 failure (boundary_stop) seen once the previous gate is recorded wins there. A cancelled lane stops at its
        next bench command or helper dispatch; a strategy run (G13-G15) has no cancel and finishes its
        gate first. True when the loop must stop."""
        pos = {g: i for i, g in enumerate(gates)}
        lanes = [[g for g in lane if g in pos] for lane in self.overlap_lanes]
        keys = self.overlap_card or {}
        details = c.work / "gate-details"
        def detail_files(gate):
            return {p.name: p.read_bytes() for p in details.glob(f"{gate}.*") if p.is_file()} if details.is_dir() else {}
        prior = {g: detail_files(g) for g in gates}
        # Per-run state the lanes must share with c, made before they are copied.
        for name, empty in (("gate_cached", set), ("strategy_shared", dict), ("engine_path_ordinals", dict),
                            ("gate_fingerprint_versions", dict)):
            c.__dict__.setdefault(name, empty())
        import gate_state
        base = getattr(c, "evidence_scope", None)
        tickets, mine = _Tickets(), [set() for _ in lanes]
        files = lambda: gate_state.digests(c, self.bench)
        contexts = []
        for i in range(len(lanes)):
            lane = copy.copy(c)
            lane.role_cancel = threading.Event()
            lane.bench_turn = BenchTurn(tickets, files, mine[i])
            lane.evidence_scope = (lambda i: lambda kind, rel: (base is None or base(kind, rel))
                                   and not any((kind, rel) in m for j, m in enumerate(mine) if j != i))(i)
            contexts.append(lane)
        lock, stop_at, running = threading.Lock(), [len(gates)], {}
        events, snapshots = queue.Queue(), {}

        def stop_from(at):
            """Gates after position `at` are not reached: cancel every lane running one."""
            with lock:
                stop_at[0] = min(stop_at[0], at)
                for i, where in running.items():
                    if where > stop_at[0]: contexts[i].role_cancel.set()

        def lane_run(i):
            lane = contexts[i]
            for gate in lanes[i]:
                started, outcome, error = time.time(), None, None
                try:
                    try:
                        lane.bench_turn.acquire()
                        with lock:
                            if pos[gate] > stop_at[0]: return
                            running[i] = pos[gate]
                        snapshots[gate] = {k: copy.deepcopy(c.card[k]) if k in c.card else _MISSING for k in keys.get(gate, ())}
                        if pos[gate]: self.budget_boundary(lane)   # the serial loop's boundary before each later gate
                        outcome = run_gate(gate, lane)
                    finally:
                        lane.bench_turn.release()   # may raise (listing the results): the gate crashed
                except BaseException as failure:
                    error = failure
                if error is not None or outcome.crashed or not outcome.ok: stop_from(pos[gate])
                events.put((gate, outcome, error, started, time.time()))   # always: the main thread waits for it
                if error is not None or outcome.crashed or not outcome.ok: return

        group_hash = self.case_hash(c)
        self.log(c, "+".join(gates), "start (" + ", ".join("+".join(lane) for lane in lanes) + " at once)")
        done, error, stop, recorded = {}, None, False, 0
        # Put back inside the section: its exit publishes the deferred engine snapshot.
        with self.section(c):
            try:
                pool = ThreadPoolExecutor(max_workers=len(lanes))
                try:
                    for i in range(len(lanes)): pool.submit(contextvars.copy_context().run, lane_run, i)
                    while recorded < len(gates) and not stop:
                        gate = gates[recorded]
                        # Where the serial loop would start this gate (the previous one is recorded): a G10
                        # failure seen now wins; one that comes while the gate runs waits for its result.
                        if recorded and boundary_stop(gate): break
                        while gate not in done:
                            event = events.get()
                            done[event[0]] = event[1:]
                        outcome, error, started, finished = done[gate]
                        if error is not None: break
                        stop = record(gate, outcome, started, finished)
                        recorded += 1
                finally:
                    stop_from(recorded - 1)   # nothing after the last recorded gate is reached
                    pool.shutdown(wait=True)
            finally:
                for gate in reversed(gates[recorded:]):   # never recorded: put back as a serial loop would have left them
                    for k, v in snapshots.get(gate, {}).items():
                        if v is _MISSING: c.card.pop(k, None)
                        else: c.card[k] = v
                    now = detail_files(gate)
                    for name in set(now) - set(prior[gate]): (details / name).unlink(missing_ok=True)
                    for name, data in prior[gate].items():
                        if now.get(name) != data: (details / name).write_bytes(data)
                    getattr(getattr(c, "engine", None), "__dict__", {}).get("progress_gates", set()).discard(gate)
        if error is not None: raise error
        if self.case_hash(c) != group_hash:
            for gate in gates:
                for field in ("gates", "gate_results", "gate_minutes"): c.card.get(field, {}).pop(gate, None)
            self.log(c, gates[0], "case changed while gates ran in parallel")
            c.card["gates"][gates[0]] = "invalid-infra"
            c.card["failed_gate"] = gates[0]
            c.card["failed_detail"] = {"error": "case_changed_during_parallel_gates"}
            return True
        return stop


    def run(self, c, *, replay_gate=None, around_gate=None):
        """Run gates, joining/cancelling the isolated G10 before returning to seal/checkpoint."""
        a = c.args
        def run_gate(gate, on=None):
            on = c if on is None else on
            def invoke():
                if gate in getattr(on, "early", {}) and on.early_hash == self.case_hash(on):
                    ok, info = on.early[gate]
                    return ok, {**info, "reused_from_early_check": True}
                if getattr(on, 'engine', None) is not None:
                    from durable.checkpoints import gate_call
                    from gate_state import inputs
                    import run
                    binding = {"science": inputs(on, gate, run.BENCH),
                               "ruling": getattr(on, "engine_ruling", None)}
                    return gate_call(on, gate, lambda: self.check(on, gate), binding)
                return self.check(on, gate)
            retained = replay_gate(c, gate) if replay_gate else None
            if retained is not None:
                ok, info = retained
                self.publish(c, gate, 'completed' if ok else 'failed', 0, True)
                return gate_attempt.Outcome(ok, info, 0)
            with self.window(on, gate):
                outcome = gate_attempt.execute(
                    (lambda: around_gate(on, gate, invoke)) if around_gate else invoke,
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
        lane = {"future": None, "hash": None, "section": None, "results": [], "first": threading.Event(), "taken": False}
        early = bool(side and self.side_early and side[0] == self.side_early[0] and self.side_early[1] in order
                     and order.index(self.side_early[1]) < order.index(side_join or order[-1]))

        def side_run():
            results = lane["results"] = []
            try:
                for gate in side:
                    self.budget_boundary(c)
                    started = time.time()
                    outcome = run_gate(gate)
                    results.append((gate, outcome, started, time.time()))
                    lane["first"].set()
                    if outcome.crashed or not outcome.ok: break
            finally:
                lane["first"].set()
            return results

        def side_first():
            """Record the lane's first gate now (waiting for it). True when the loop must stop."""
            lane["first"].wait()
            if lane["future"].done() and lane["future"].exception(): return side_finish()  # raised: surface it now
            # No result means the lane raised; its finally sets `first` before the future is done, so join it.
            if not lane["results"]: return side_finish()
            lane["taken"] = True
            return record(*lane["results"][0], quiet())

        def lane_failed():
            # A reviewer verdict that failed: G16 (and G5) precede G8/G9 in gate order, so record it at the
            # join (or after the loop's earliest-failure fix-up), not at the next boundary.
            return any(not o.ok and not o.crashed for _, o, _, _ in lane["results"])

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
            for gate, outcome, started, finished in results[1 if lane["taken"] else 0:]:
                stop = record(gate, outcome, started, finished, quiet()) or stop
            return stop

        group = [g for g in order if any(g in lane for lane in self.overlap_lanes)]
        start = order.index(group[0]) if group else 0
        overlapping = (bool(group) and len(group) == sum(map(len, self.overlap_lanes)) and order[start:start + len(group)] == group
                       and not a.dry_run and replay_gate is None and getattr(c, "audit_gates", None) is None and self.overlap(c))
        def g10_failed(gate):
            return future is not None and future.done() and future.exception() is None and not future.result().ok

        future, g10_started = None, None
        pool = ThreadPoolExecutor(max_workers=1)
        side_pool = ThreadPoolExecutor(max_workers=1) if side else None
        g10_section = None
        try:
            if side and side_after is None: side_start()
            for gate in order:
                if gate in side or (overlapping and gate in group[1:]): continue
                if lane["future"] is not None and ((lane["future"].done() and not lane_failed()) or gate == side_join):
                    if side_finish(): break
                self.budget_boundary(c)
                if a.dry_run and gate in self.dry_skip:
                    c.card["gates"][gate] = f"skipped ({self.dry_skip[gate]})"; continue
                # 2026-10-20: a completed G10 rejection wins at the next boundary; an already-running
                # foreground gate finishes first (its failure wins). Founder 2026-11-12: a G10 stop
                # (money, quota, provider refusal) is parked instead: bench gates cost no model money,
                # so they finish, and the stop is raised when G10 is joined.
                if future is not None and future.done() and gate != "G10":
                    error = future.exception()
                    if error is None:
                        if not future.result().ok: gate = "G10"
                    elif not isinstance(error, BudgetError) or str(error) == "cancelled":
                        future.result()
                    elif g10_section is not None:
                        self.log(c, "G10", "stopped, parked until the bench gates finish:", str(error))
                        g10_section.__exit__(None, None, None); g10_section = None
                if gate == "G6" and "G10" in order and not a.dry_run:
                    self.money_headroom(c)
                if gate == "G6" and not (a.dry_run and "G10" in self.dry_skip):
                    reason = self.overlap_reason(c)
                    if reason is None and getattr(c, "prepared_factory_slots", 1) < a.bench_workers + 2:
                        reason = "reserved tester instances were not prepared"
                    if reason:
                        self.log(c, "G10", "serial:", reason)
                    else:
                        c.calibrator_slot_offset = a.bench_workers
                        # Gates cite neither G10's tester instances (as early_parallel) nor what they hold,
                        # from here until run() exits (its finally drops the scope), not only while G10 overlaps.
                        testers = tuple(f"factory-slots/{n}/" for n in (a.bench_workers, a.bench_workers + 1))
                        c.evidence_scope = lambda kind, rel: kind != "bench" or not rel.startswith(testers)
                        c.role_cancel = threading.Event()
                        g10_started = time.time()
                        self.log(c, "G10", "start (overlapping bench gates)")
                        g10_section = self.section(c)
                        g10_section.__enter__()
                        future = pool.submit(contextvars.copy_context().run, run_gate, "G10")
                if overlapping and gate == group[0]:
                    if self.overlap_run(c, group, run_gate, lambda g, o, s, f: record(g, o, s, f, quiet(g)), g10_failed): break
                    continue
                started = g10_started if gate == "G10" and future is not None else time.time()
                if gate == "G10" and future is not None:
                    try:
                        outcome = future.result()  # joined before G11; same card/log format
                    finally:
                        if g10_section is not None:
                            g10_section.__exit__(None, None, None); g10_section = None
                else:
                    outcome = run_gate(gate)
                if early and gate == self.side_early[1] and lane["future"] is not None and not lane["taken"]:
                    if side_first(): break
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
                        elif error is not None and not outcome.crashed and not outcome.ok and not cancelling \
                                and not c.card.get('failed_gate'):
                            # An exception ended the loop before G10 was joined: its failure stays on
                            # the card, so a money stop cannot hide a verdict (run.run_step).
                            record('G10', outcome, g10_started or time.time(), time.time(), quiet('G10'))
                    except BudgetError as error:
                        if not (cancelling and str(error) == "cancelled"): raise
                else:
                    pool.shutdown(wait=True)
            finally:
                if lane["future"] is not None:
                    # An exception left the lane running: let it finish (reviewer calls have no
                    # cancellation) and record its gates, so a money stop cannot hide a G8/G9 verdict
                    # (run.run_step); the earliest recorded failure in gate order still wins.
                    failed, detail = c.card.get("failed_gate"), c.card.get("failed_detail")
                    try: side_finish()
                    except BaseException: pass
                    later = c.card.get("failed_gate")
                    if failed and later and later != failed and later in order and order.index(failed) < order.index(later):
                        c.card["failed_gate"], c.card["failed_detail"] = failed, detail
                    lane["future"] = None
                if lane["section"] is not None:
                    lane["section"].__exit__(None, None, None); lane["section"] = None
                if side_pool is not None: side_pool.shutdown(wait=True)
                if g10_started is not None: c.__dict__.pop("evidence_scope", None)


