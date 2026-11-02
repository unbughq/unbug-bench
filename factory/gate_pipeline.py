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
        import processes  # run.py installs the bench bin path after importing this module
        from factory_waste import attempt
        try:
            with attempt(c, gate, self.case_hash(c)), (processes.deadline(getattr(getattr(c, 'args', None), 'agent_timeout', 14400))
                  if gate in ('G13', 'G14', 'G15') else contextlib.nullcontext()):
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


    def early_checks(self, c, *, on_rejection=None):
        """G3-G5 right after the writer (~20 min on a cpx42): a case whose bug is not real or whose keys are wrong goes
        back to the writer in the same round, before the stress tester spends time on it. Returns writer problems or None;
        passing results are reused by the gate loop while the case is unchanged."""
        c.early = {}
        # G15 needs the complete answer key/ingredients; G1 has validated them before this call.
        gates = (["G15"] if (c.case / "answer-key.json").is_file() else []) + list(self.early_gates)
        for gate in gates:
            outcome = gate_attempt.execute(
                lambda: self.check(c, gate),
                publish=lambda *args: self.publish(c, 'early:' + gate, *args),
                record_crash=lambda error: self.record_crash(c, gate, error),
                interruption=BudgetError, attempts=2, raise_crash=True,
                journal=c.work / "infra-attempts.json",
                identity={"operation": "early-gate", "gate": gate, "case": self.case_hash(c)})
            ok, info = outcome.ok, outcome.info
            self.log(c, gate, "early", "pass" if ok else "FAIL", json.dumps(info), f"{outcome.elapsed_seconds:.0f}s")
            c.card.setdefault("early_gates", {})[gate] = {"ok": ok, "minutes": round((outcome.elapsed_seconds) / 60, 1)}
            if not ok:
                c.early = {}
                problems = [f"early check {gate} failed: {json.dumps(info)}"]
                details = c.work / "gate-details" / f"{gate}.json"
                if details.is_file(): problems.append(f"details: {details.read_text()[:8000]}")
                if on_rejection is not None: on_rejection(c, gate, info, problems)
                return problems
            c.early[gate] = (ok, info)
        c.card.get("early_gates", {}).pop("saved_cheats", None)
        problems = self.saved_cheat_check(c)
        if problems:
            c.early = {}
            if on_rejection is not None:
                detail = dict(sample="retained_case_cheats",
                    summary=copy.deepcopy(c.card.get("early_gates", {}).get("saved_cheats")))
                on_rejection(c, "saved-cheats", detail, problems)
            return problems
        c.early_hash = self.case_hash(c)
        return None


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
                interruption=BudgetError, attempts=2, raise_crash=True,
                journal=c.work / "infra-attempts.json",
                identity={"operation": "early-review", "gate": gate, "case": self.case_hash(c)})
            ok, info = outcome.ok, outcome.info
            self.log(c, gate, "early", "pass" if ok else "FAIL", json.dumps(info), f"{outcome.elapsed_seconds:.0f}s")
            c.card.setdefault("early_gates", {})[gate] = {"ok": ok, "minutes": round(outcome.elapsed_seconds / 60, 1)}
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
                return self.check(c, gate)
            retained = replay_gate(c, gate) if replay_gate else None
            if retained is not None:
                ok, info = retained
                self.publish(c, gate, 'completed' if ok else 'failed', 0, True)
                return gate_attempt.Outcome(ok, info, 0)
            outcome = gate_attempt.execute(
                (lambda: around_gate(c, gate, invoke)) if around_gate else invoke,
                publish=lambda *args: self.publish(c, gate, *args),
                record_crash=lambda error: self.record_crash(c, gate, error), interruption=BudgetError,
                attempts=2, journal=c.work / "infra-attempts.json",
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

        future, g10_started = None, None
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            for gate in getattr(c, "audit_gates", self.gates):
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
                        future = pool.submit(contextvars.copy_context().run, run_gate, "G10")
                started = g10_started if gate == "G10" and future is not None else time.time()
                if gate == "G10" and future is not None:
                    outcome = future.result()  # joined before G11; same card/log format
                else:
                    outcome = run_gate(gate)
                ok, info = outcome.ok, outcome.info
                if outcome.crashed:
                    stop_infrastructure(gate, outcome)
                    break
                self.log(c, gate, "pass" if ok else "FAIL", json.dumps(info), f"{time.time() - started:.0f}s")
                c.card["gates"][gate] = "pass" if ok else "fail"
                c.card.setdefault("gate_results", {})[gate] = info
                c.card.setdefault("gate_minutes", {})[gate] = round((time.time() - started) / 60, 1)
                self.after_gate(c, gate, ok, future is None or gate == "G10")
                if not ok:
                    c.card["failed_gate"] = gate
                    c.card["failed_detail"] = info.get("problems") or info
                    break
            if not c.card.get("failed_gate"): self.budget_boundary(c)
        finally:
            if future is not None:
                error = sys.exc_info()[1]
                budget_boundary = isinstance(error, BudgetError) and str(error) == 'budget_exhausted'
                cancelling = not future.done() and not budget_boundary
                if cancelling: c.role_cancel.set()
                pool.shutdown(wait=True)  # model cancellation kills its process group
                # Stop/provider errors in the tester must reach main's checkpoint path.
                try:
                    outcome = future.result()
                    if outcome.crashed and not c.card.get('failed_gate'):
                        stop_infrastructure('G10', outcome)
                except BudgetError as error:
                    if not (cancelling and str(error) == "cancelled"): raise
            else:
                pool.shutdown(wait=True)


