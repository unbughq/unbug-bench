"""The campaign guard: one pass a minute, run by a systemd timer as root.

A failed check never stops anything. It is retried, logged and marks the batch degraded,
which pauses new attempts (engine.py) until a pass succeeds. A stalled campaign (a case waiting on
credentials or the router, no case progress for STALL_S while cases are live, or a case parked
on a founder decision for FOUNDER_WAIT_S) also reads
degraded, with the reason in `stalled`, and alerts; it pauses nothing. Only these are hard stops: the
deadline, the money ceiling and a confirmed Boat allowance or rate breach.

A hard stop pauses new attempts and gives steps in flight a checkpoint grace to record. When none
is left, or the grace ends, the guard stops the controller and deletes the workers. Work still
unrecorded then becomes an ordinary worker_lost retry when the batch resumes, and is never scored.
Nothing else deletes a worker here.

Everything under `<state_dir>/guard` is public-safe: fixed codes, numbers and scrubbed text.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Callable, Optional
import urllib.request

from durable.workers import PoolError, _atomic_json

RETRY_WAITS_S = (2.0, 6.0)   # a check gets three tries; the unit timeout fits a pass where all fail
GRACE_S = 120.0              # a controller that just came up is not judged yet
CHECKPOINT_GRACE_S = 600.0   # after a hard stop, for steps in flight; a pass runs once a minute
LOW_CREDIT_USD = 20.0        # alert below this provider credit; a call's hold can be most of a grant
ROUTER_MARGIN_USD = 1.0      # the router refuses a call that would pass its ceiling, so spend stalls below it
ESCALATE_S = 900.0           # sustained failure raises an alert; it still stops nothing
DOWN_ALERT_S = 600.0
STALL_S = 900.0              # no case or router progress this long while cases are live is a stall
FOUNDER_WAIT_S = 1800.0      # a case parked on a founder decision this long raises a reminder
MARKER_TTL_S = 600.0         # a dead guard cannot pause admission for longer than this
EVIDENCE_KEPT = 200
READ_LIMIT = 1 << 20
# Worker limits. The campaign caps sandboxes running at once, never sandboxes started in total:
# a case that needs a fresh worker waits for a free slot instead of stopping. Starts are only
# rate-limited, below Boat's plan (100 running, 60 starts an hour, 12 a minute, 200 a day).
# Going past the request's own limits only degrades (an operator may lower them mid-run);
# going past Boat's plan is a confirmed allowance breach and a hard stop.
BOAT_RUNNING_LIMIT = 100
BOAT_STARTS_PER_HOUR = 60
BOAT_STARTS_PER_MINUTE = 12
BOAT_STARTS_PER_DAY = 200
STARTS_PER_MINUTE = 10
STARTS_PER_DAY = 180
WORKER_TTL_S = 7200          # the longest a worker lives without a renewal
TERMINAL = ("sealed", "retired", "held", "stopped_admission", "engine_error")
HARD_STOPS = {
    "deadline": "The batch deadline passed.",
    "money_ceiling": "Spending passed the money ceiling. Check the ledger before raising it.",
    "compute_bound": "Reserved compute passed the approved infrastructure budget.",
    "worker_count": "More live workers than the Boat plan allows. Check Boat before restarting.",
    "worker_allowance": "Workers were started faster than the Boat plan allows. Check Boat.",
    "worker_rate": "A worker costs more than its approved rate, or the live workers passed the compute bound. Check Boat.",
}
CASE_ALERTS = {
    "escalated": "{case} needs your ruling before it can continue.",
    "held": "{case} is held and needs your decision.",
    "waiting_for_bound": "{case} is waiting for budget. Raise the batch bound or retire it.",
    "waiting_for_release": "{case} is waiting for a fixed plumbing release.",
    "retrying_admission": "{case} keeps failing admission on infrastructure and is still retrying. Check its stop reason.",
    "stopped_admission": "{case} stopped admission. Decide whether to start a new batch.",
}
# Waits that only an operator can end, so one case in them stalls the campaign (9 November: the
# router's certificate expired and the guard read healthy for twenty minutes).
STALL_STATUSES = ("waiting_for_credentials", "waiting_for_router")
STALL_ALERTS = {
    "waiting_for_credentials": "{case} is stuck waiting for credentials. Check the router and its certificate.",
    "waiting_for_router": "{case} is stuck waiting for the router. Check the router and its certificate.",
    "no_progress": "No case has made progress for {minutes} minutes ({cases}). Check the controller and router logs.",
}
# A case parked on a founder decision: the decision it waits on, as the guard can read it.
FOUNDER_WAITS = {
    "escalated": "a ruling on its escalation",
    "held": "a decision on its hold",
    "waiting_for_bound": "a raised batch bound or its retirement",
    "waiting_for_release": "a fixed plumbing release",
}
CASE_REASON_ALERTS = {
    "router:credit": "{case} is waiting: the provider account refused a call for lack of credit. Top it up.",
}


def scrub(text, limit: int = 240) -> str:
    """Provider error text made safe to publish: no addresses, paths or long tokens."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    text = re.sub(r"\b\d{1,3}(\.\d{1,3}){3}\b", "[ip]", str(text))
    text = re.sub(r"\b[0-9a-fA-F:]*:[0-9a-fA-F:]{6,}\b", "[ip]", text)
    text = re.sub(r"(?:/[\w.@-]+){2,}", "[path]", text)
    text = re.sub(r"[A-Za-z0-9_+/=.-]{24,}", "[redacted]", text)
    return " ".join(text.split())[:limit]


class CheckFailed(Exception):
    def __init__(self, code: str, detail=""):
        super().__init__(code)
        self.code, self.detail = code, scrub(detail)


def campaign_limits(request: dict) -> tuple:
    """(max_running_sandboxes, max_starts_per_hour) from the campaign request, or a failed check."""
    running, hourly = request.get("max_running_sandboxes"), request.get("max_starts_per_hour")
    if type(running) is not int or not 1 <= running <= BOAT_RUNNING_LIMIT:
        raise CheckFailed("request_malformed", "max_running_sandboxes")
    if type(hourly) is not int or not 1 <= hourly < BOAT_STARTS_PER_HOUR:
        raise CheckFailed("request_malformed", "max_starts_per_hour")
    return running, hourly


def compute_bound(request: dict, grace_s: float) -> float:
    """Worst-case worker compute in dollars: every running slot busy for the whole wall, plus the
    checkpoint grace that each worker's TTL may run past the deadline, plus one more worker for a
    full TTL as slack for a sandbox Boat lists late. Starts add nothing: a sandbox holds a slot
    from its create request until Boat stops listing it as live."""
    running, _ = campaign_limits(request)
    return request["max_worker_rate_usd_per_second"] * (running * (request["wall_seconds"] + grace_s) + WORKER_TTL_S)


def compute_fits(request: dict, grace_s: float) -> bool:
    """Whether the worst case fits the founder's typed infrastructure approval."""
    return (request["prior_compute_retained_usd"] + request["control_allowance_usd"] + compute_bound(request, grace_s)
            <= request["approved_infrastructure_usd"] - request["cleanup_margin_usd"])


def read_starts(path) -> list:
    """Recorded worker start times. Missing means none; anything malformed is a failed check."""
    try:
        starts = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        raise CheckFailed("allowance_malformed") from None
    if not isinstance(starts, list) or not all(type(t) in (int, float) and math.isfinite(t) for t in starts):
        raise CheckFailed("allowance_malformed")
    return starts


def starts_over(starts: list, hourly: int, now: float, adding: int = 0, *,
                limits: Optional[tuple] = None) -> bool:
    """Whether the starts in each rolling window (plus `adding`) pass a start limit: the
    campaign's own by default, Boat's plan with limits=BOAT_START_LIMITS."""
    minute, day = limits if limits is not None else (STARTS_PER_MINUTE, STARTS_PER_DAY)
    return any(sum(1 for t in starts if now - t < window) + adding > limit
               for window, limit in ((60, minute), (3600, hourly), (86400, day)))


BOAT_START_LIMITS = (BOAT_STARTS_PER_MINUTE, BOAT_STARTS_PER_DAY)


def reserve_start(path, request: dict, running: Callable, clock: Callable = lambda: time.time()) -> float:
    """Record one worker start and return its time, or refuse it with a reason the engine waits on
    (classify.py). The caller holds the campaign create lock until the create request has been
    recorded, so `running` sees every earlier start. The clock is read after the inventory
    lookup, which can take minutes, so the recorded time is when the create really goes out."""
    try:
        cap, hourly = campaign_limits(request)
        starts = read_starts(path)
    except CheckFailed:
        raise PoolError("infra:compute_approval_unverified") from None
    if running() >= cap:
        raise PoolError("infra:worker_slots_full")
    now = clock()
    if starts_over(starts, hourly, now, adding=1):
        raise PoolError("infra:worker_start_rate")
    _atomic_json(Path(path), [t for t in starts if now - t < 86400] + [now])
    return now


class Guard:
    def __init__(self, request: dict, directory: Path, *, boat: Callable, rpc: Callable, service,
                 ours: Callable, count: Callable, delete: Callable, notify: Optional[Callable] = None,
                 router: Optional[Callable] = None, low_credit_usd: float = LOW_CREDIT_USD,
                 grace_s: float = GRACE_S, escalate_s: float = ESCALATE_S,
                 checkpoint_grace_s: float = CHECKPOINT_GRACE_S, clock=time.time, sleep=time.sleep):
        self.request, self.directory = request, Path(directory)
        self.boat, self.rpc, self.service, self.ours, self.count = boat, rpc, service, ours, count
        self.delete, self.checkpoint_grace_s, self.router = delete, checkpoint_grace_s, router
        self.low_credit_usd = low_credit_usd
        self.notify = notify
        # A campaign watches one batch (batch_id) or several started side by side (batch_ids).
        self.batches = list(request.get("batch_ids") or [request["batch_id"]])
        self.grace_s, self.escalate_s = grace_s, escalate_s
        self.clock, self.sleep = clock, sleep
        self.failed: list = []
        self.evidence: list = []
        self.cases: list = []   # this pass's case rows, once the controller answered

    # -- files --

    def path(self, name: str) -> Path:
        return self.directory / name

    def load(self, name: str, default):
        try:
            value = json.loads(self.path(name).read_text())
            return value if isinstance(value, type(default)) else default
        except (OSError, ValueError):
            return default

    def save(self, name: str, value) -> None:
        owner = None
        if os.geteuid() == 0:   # the guard is root; the controller and `unbug status` are not
            self.directory.mkdir(exist_ok=True)
            info = self.directory.parent.stat()
            owner = (info.st_uid, info.st_gid)
            os.chown(self.directory, *owner)
        _atomic_json(self.path(name), value, owner=owner)

    # -- checks --

    def check(self, name: str, call: Callable):
        """(True, value) or (False, None) after three tries, every failed try on record."""
        for attempt, wait in enumerate((0.0, *RETRY_WAITS_S), 1):
            if wait:
                self.sleep(wait)
            started = self.clock()
            try:
                return True, call()
            except CheckFailed as error:
                code, detail = error.code, error.detail
            except Exception as error:  # a bug here must degrade, never stop the factory
                code, detail = "guard_error", type(error).__name__
            self.evidence.append({"at": started, "check": name, "try": attempt, "code": code,
                                  "seconds": round(self.clock() - started, 3), "stderr": detail})
        self.failed.append(name)
        return False, None

    def flag(self, name: str, code: str, detail: str = "") -> None:
        """A confirmed number past one of our own limits: it degrades, it does not stop."""
        self.evidence.append({"at": self.clock(), "check": name, "try": 1, "code": code,
                              "seconds": 0, "stderr": scrub(detail)})
        self.failed.append(name)

    def _boat(self, args: list, timeout: float) -> bytes:
        done = self.boat(args, timeout)
        if done["code"]:
            raise CheckFailed(f"exit_{done['code']}", done.get("stderr", ""))
        return done["out"]

    def _inventory(self) -> list:
        data = json.loads(self._boat(["list", "--json"], 30))
        if data["pageInfo"]["hasMore"] is not False:
            raise CheckFailed("inventory_incomplete")
        return data["sandboxes"]

    def _usage(self, worker: str) -> tuple:
        usage = json.loads(self._boat(["usage", worker, "--json"], 30))
        values = [usage.get(k) for k in ("dollars", "billingMultiplier", "secondsPerDollar")]
        if not all(type(v) in (float, int) and math.isfinite(v) and v >= 0 for v in values) or values[2] <= 0:
            raise CheckFailed("usage_malformed")
        return values[0], values[1] / values[2]

    def _count(self) -> list:
        starts = self.count()
        if not isinstance(starts, list) or not all(type(t) in (int, float) and math.isfinite(t) for t in starts):
            raise CheckFailed("allowance_malformed")
        return starts

    def _breach(self, owned: list) -> Optional[str]:
        """A hard stop only on confirmed numbers. An unreadable number is a failed check."""
        r = self.request
        grace = self.checkpoint_grace_s
        # An unreadable request confirms nothing: the checks that need it only degrade.
        ok, limits = self.check("request", lambda: (*campaign_limits(r), compute_fits(r, grace),
                                                    compute_bound(r, grace)))
        cap, hourly, fits, worker_bound = limits if ok else (None, None, True, None)
        if not fits:
            return "compute_bound"
        if len(owned) > BOAT_RUNNING_LIMIT:
            return "worker_count"
        if cap is not None and len(owned) > cap:
            # Past our own cap (an operator may have lowered it): pause new attempts, alert.
            self.flag("running_cap", "over_cap", f"{len(owned)} live, cap {cap}")
        ok, starts = self.check("worker_allowance", self._count)
        if ok and starts_over(starts, BOAT_STARTS_PER_HOUR, self.clock(), limits=BOAT_START_LIMITS):
            return "worker_allowance"
        if ok and hourly is not None and starts_over(starts, hourly, self.clock()):
            self.flag("start_rate", "over_limit", f"cap {hourly} an hour")
        spent = 0.0
        for row in owned:
            ok, usage = self.check("boat_usage", lambda: self._usage(row["id"]))
            if ok and usage[1] > r["max_worker_rate_usd_per_second"]:
                return "worker_rate"
            spent += usage[0] if ok else 0.0
        if worker_bound is not None and spent > worker_bound:
            return "worker_rate"   # the live workers alone already passed the whole bound
        return None

    def _extend(self, owned: list) -> None:
        for row in owned:
            ttl = min(7200, int(self.request["deadline_epoch"] + self.checkpoint_grace_s - self.clock()))
            if ttl >= 1:
                self.check("boat_extend", lambda: self._boat(["extend", row["id"], "--ttl", str(ttl)], 30))

    # -- the pass --

    def run(self, *, cleanup: bool = False) -> dict:
        now = self.clock()
        status = self.load("status.json", {})
        health = {"at": now, "phase": "healthy", "degraded_since": status.get("degraded_since"),
                  "down_since": status.get("down_since"), "hard_stop": status.get("hard_stop"),
                  "finished": status.get("finished", False), "failed_checks": [], "owned_workers": None,
                  "stopping_since": status.get("stopping_since"), "controller_stopped": status.get("controller_stopped", False),
                  "money_held": None, "router_spent_usd": status.get("router_spent_usd"),
                  "provider_credit_usd": status.get("provider_credit_usd"), "stalled": None, "stalled_cases": [],
                  "progress_at": status.get("progress_at"), "progress_digest": status.get("progress_digest"),
                  "waits": status.get("waits") if isinstance(status.get("waits"), dict) else {}, "founder_waits": []}
        ok, service = self.check("service_state", self.service.state)
        active, active_since, ready_since = service if ok else ("unknown", None, None)
        if health["finished"]:
            health["phase"] = "finished"
            if active == "active":   # an earlier stop failed
                self.check("controller_stop", self.service.stop)
            return self._finish(health, status)
        if health["hard_stop"] or cleanup or now >= self.request["deadline_epoch"]:
            health["hard_stop"] = health["hard_stop"] or "deadline"
            return self._wind_down(health, status, active)
        if active == "active":
            down = health["down_since"]
            if now - max(active_since or 0, ready_since or 0) >= self.grace_s:
                health["down_since"] = None
            elif down is None or now - down < 2 * self.grace_s:
                health["phase"] = "starting"
                return self._finish(health, status)
        elif ok:
            health["down_since"] = health["down_since"] or now
            self.evidence.append({"at": now, "check": "controller", "try": 1, "code": active,
                                  "seconds": 0, "stderr": ""})
            self.failed.append("controller")
        ok, owned = self.check("boat_list", lambda: [r for r in self._inventory() if self.ours(r)])
        if ok:
            health["owned_workers"] = len(owned)
            health["hard_stop"] = self._breach(owned)
        if health["hard_stop"] is None and active in ("active", "unknown"):
            health["hard_stop"] = self._controller(health)
        if health["hard_stop"]:
            return self._wind_down(health, status, active)
        # A crashed controller restarts and resumes on its worker, so renewal continues. A cleanly
        # stopped one (an operator stop) runs nothing: the worker is left to its Boat timer and a
        # resume gets a fresh one (b5521c, 8 November: an idle worker was renewed for nine hours).
        if owned and active != "inactive":
            self._extend(owned)
        return self._finish(health, status)

    def _controller(self, health: dict) -> Optional[str]:
        def over_ceiling():
            # Every watched batch keeps its own bound; held money is their sum.
            moneys = [self.rpc("budget", batch) for batch in self.batches]
            health["money_held"] = sum(m.get("held") or 0 for m in moneys)
            return any(m["spent"] > m["bound"] for m in moneys)
        def router_over_ceiling():
            """The router's charges are the real spend, and the ledger has read low."""
            spent, ceiling, *credit = self.router()
            health["router_spent_usd"] = round(spent, 6)
            health["provider_credit_usd"] = round(credit[0], 2) if credit and credit[0] is not None else None
            return spent >= ceiling - ROUTER_MARGIN_USD
        def terminal():
            # The campaign is finished only when every watched batch is.
            reports = [self.rpc("status", batch) for batch in self.batches]
            cases = [c for report in reports for c in report["cases"]]
            if not all(isinstance(c["case"], str) and isinstance(c["status"], str) for c in cases):
                raise CheckFailed("status_malformed")
            self.save("scorecard.json", {**reports[0], "cases": cases} if len(reports) == 1 else
                      {"batches": self.batches, "cases": cases})
            self.cases = cases
            return all(report["cases"] and all(c["status"] in TERMINAL for c in report["cases"])
                       for report in reports)
        ok, over = self.check("ledger", over_ceiling)
        if ok and over:
            return "money_ceiling"
        if self.router is not None:
            ok, over = self.check("router_spend", router_over_ceiling)
            if ok and over:
                return "money_ceiling"
        ok, finished = self.check("controller_status", terminal)
        if ok and not finished:
            self._stall(health)
        if ok and finished:
            done, _ = self.check("publish", lambda: [self.rpc("publish", batch) for batch in self.batches])
            if done:
                health["finished"] = True
                health["phase"] = "finished"
                health["down_since"] = None
                self.check("controller_stop", self.service.stop)
        return None

    def _stall(self, health: dict) -> None:
        """Name a stall from data already read: case waits only an operator can end, or no change
        in any case row or in router spend for STALL_S while cases are live. Alerts only."""
        now = self.clock()
        progress = json.dumps([[c.get(k) for k in ("case", "status", "stage", "gates", "writer_rounds", "extensions")]
                               for c in self.cases] + [health.get("router_spent_usd")], sort_keys=True, default=str)
        if progress != health["progress_digest"] or type(health["progress_at"]) not in (int, float):
            health["progress_digest"], health["progress_at"] = progress, now
        # Since when each case has sat in its founder wait; a case that moves on starts over.
        waits = {}
        for c in self.cases:
            if c["status"] in FOUNDER_WAITS and not (c["status"] == "waiting_for_bound" and health.get("money_held")):
                before = health["waits"].get(c["case"])
                same = isinstance(before, dict) and before.get("status") == c["status"] and type(before.get("since")) in (int, float)
                waits[c["case"]] = before if same else {"status": c["status"], "since": now}
        health["waits"] = waits
        health["founder_waits"] = sorted(case for case, w in waits.items() if now - w["since"] > FOUNDER_WAIT_S)
        stuck = sorted(c["case"] for c in self.cases if c["status"] in STALL_STATUSES)
        if stuck:
            health["stalled"] = next(s for s in STALL_STATUSES if any(c["status"] == s for c in self.cases))
            health["stalled_cases"] = stuck
            return
        # Cases waiting on a founder decision already raise their own alert.
        live = sorted(c["case"] for c in self.cases if c["status"] not in TERMINAL and c["status"] not in CASE_ALERTS)
        if live and now - health["progress_at"] > STALL_S:
            health["stalled"], health["stalled_cases"] = "no_progress", live
        elif health["founder_waits"]:
            health["stalled"], health["stalled_cases"] = "founder_wait", health["founder_waits"]

    def _recording(self, health: dict, active: str) -> bool:
        """Whether to keep waiting for steps in flight. A controller that cannot answer may
        still be recording, so it gets the rest of the grace; a dead one records nothing."""
        if active not in ("active", "unknown"):
            return False
        if self.clock() - health["stopping_since"] >= self.checkpoint_grace_s:
            return False
        ok, running = self.check("in_flight", lambda: self.rpc("in_flight", self.batches[0]))
        return not ok or running > 0

    def _wind_down(self, health: dict, status: dict, active: str) -> dict:
        """A hard stop, one step a pass: wait for steps in flight, stop, delete the workers. It
        holds until an operator clears it: every pass stops a controller that came back (a
        reboot) and deletes a worker that landed late."""
        health["stopping_since"] = health["stopping_since"] or self.clock()
        health["phase"] = "stopping"
        if not health["controller_stopped"] and self._recording(health, active):
            return self._finish(health, status)
        if not health["controller_stopped"] or active == "active":
            health["controller_stopped"], _ = self.check("controller_stop", self.service.stop)
        if health["controller_stopped"]:
            ok, owned = self.check("boat_list", lambda: [r for r in self._inventory() if self.ours(r)])
            if ok:
                for row in owned:
                    self.check("worker_delete", lambda: self.delete(row["id"]))
                health["owned_workers"] = len(owned)
                if "worker_delete" not in self.failed:
                    health["phase"] = "stopped"
        return self._finish(health, status)

    def _finish(self, health: dict, previous: dict) -> dict:
        now = self.clock()
        health["failed_checks"] = sorted(set(self.failed))
        if health["phase"] != "starting":
            health["degraded_since"] = (health["degraded_since"] or now) if self.failed else None
        if health["hard_stop"]:
            health["degraded_since"] = None   # the hard stop's own alert says what is needed
        if health["degraded_since"] is not None and health["phase"] == "healthy":
            health["phase"] = "degraded"
        if (health["phase"] in ("degraded", "stopping")
                or (health["phase"] == "starting" and health["degraded_since"] is not None)):
            self.save("degraded.json", {"until": now + MARKER_TTL_S})
        else:
            self.path("degraded.json").unlink(missing_ok=True)
        if health.get("stalled") and health["phase"] == "healthy":
            health["phase"] = "degraded"   # after the marker: a stall alerts, it pauses nothing
        if self.evidence:
            self.save("evidence.json", (self.load("evidence.json", []) + self.evidence)[-EVIDENCE_KEPT:])
        self._alerts(health, now)
        self.save("status.json", health)
        return health

    # -- alerts: one message per condition, while it lasts --

    def wanted(self, health: dict, now: float) -> dict:
        out = {}
        if health["hard_stop"]:
            out["hard_stop"] = "Factory stopped. " + HARD_STOPS.get(health["hard_stop"], "Check the guard log.")
        since = health["degraded_since"]
        if since is not None and now - since >= self.escalate_s:
            failing = ", ".join(health["failed_checks"]) or "a check"
            out["degraded"] = f"New attempts have been paused for {int((now - since) / 60)} minutes: {failing} keeps failing."
        down = health["down_since"]
        if down is not None and now - down >= DOWN_ALERT_S:
            out["controller_down"] = (f"The controller has been down for {int((now - down) / 60)} minutes "
                                      "and has not restarted. Check its service log.")
        # Keyed per case (or per case set), so a newly stuck case alerts while a lasting one does not repeat.
        stuck = health.get("stalled_cases") or []
        if health.get("stalled") in STALL_STATUSES:
            for case in self.load("scorecard.json", {}).get("cases", []):
                if isinstance(case, dict) and case.get("case") in stuck and case.get("status") in STALL_STATUSES:
                    out[f"stalled:{case['status']}:{case['case']}"] = STALL_ALERTS[case["status"]].format(case=case["case"])
        elif health.get("stalled") == "no_progress":
            cases = ", ".join(stuck[:5]) + (f" and {len(stuck) - 5} more" if len(stuck) > 5 else "")
            minutes = int((now - (health.get("progress_at") or now)) / 60)
            out["stalled:no_progress:" + ",".join(stuck)] = STALL_ALERTS["no_progress"].format(cases=cases, minutes=minutes)
        for case in health.get("founder_waits") or []:
            wait = health["waits"][case]
            out[f"founder_wait:{case}:{wait['status']}"] = (
                f"{case} has waited {int((now - wait['since']) / 60)} minutes ({wait['status']}) "
                f"for {FOUNDER_WAITS[wait['status']]}.")
        credit = health.get("provider_credit_usd")
        if credit is not None and credit < self.low_credit_usd:
            out["provider_credit"] = (f"Provider account credit is ${credit:.2f}, below ${self.low_credit_usd:.0f}. "
                                      "Top it up before calls start being refused.")
        for case in self.load("scorecard.json", {}).get("cases", []):
            if not isinstance(case, dict):
                continue
            # While another attempt holds money, the wait may end by itself.
            if case.get("status") == "waiting_for_bound" and health.get("money_held"):
                continue
            if case.get("reason") in CASE_REASON_ALERTS and "case" in case:
                out[f"case:{case['case']}:{case['reason']}"] = CASE_REASON_ALERTS[case["reason"]].format(case=case["case"])
            if case.get("status") in CASE_ALERTS and "case" in case:
                out[f"case:{case['case']}:{case['status']}"] = CASE_ALERTS[case["status"]].format(case=case["case"])
        return out

    def _alerts(self, health: dict, now: float) -> None:
        alerts = self.load("alerts.json", {})
        wanted = self.wanted(health, now)
        alerts = {key: alerts.get(key, {"since": now, "message": message, "sent": False})
                  for key, message in wanted.items()}
        if self.notify is not None:
            for alert in alerts.values():
                if not alert["sent"]:
                    try:
                        self.notify(alert["message"])
                        alert["sent"] = True
                    except Exception:   # kept unsent; the next pass tries again
                        pass
        self.save("alerts.json", alerts)


def router_spend(path) -> tuple:
    """Real spend and the ceiling, in dollars, read-only from the router's books."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        # A pending row carries its full hold, not a charge. Unknown charges stay counted.
        spent = db.execute("SELECT COALESCE(SUM(charge), 0) FROM paid_requests WHERE state != 'pending'").fetchone()[0]
        row = db.execute("SELECT ceiling, credit FROM paid_account").fetchone()
    finally:
        db.close()
    ceiling = row[0] / 1e9 if row and row[0] is not None else math.inf   # no ceiling set: no limit here
    credit = row[1] / 1e9 if row and row[1] is not None else None       # the provider's last observed balance
    return spent / 1e9, ceiling, credit


def webhook(url: str) -> Callable:
    """One JSON POST per alert, to any endpoint that accepts {"text": ...}."""
    def send(message: str) -> None:
        request = urllib.request.Request(url, json.dumps({"text": message}).encode(),
                                         {"Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=10).close()
    return send


def degraded(state_dir) -> bool:
    """Whether the guard currently pauses new attempts. Unreadable or stale means no."""
    try:
        until = json.loads((Path(state_dir) / "guard" / "degraded.json").read_text())["until"]
        return type(until) in (int, float) and time.time() < until
    except (OSError, ValueError, KeyError, TypeError):
        return False


def health(state_dir) -> Optional[dict]:
    """The guard's public record for `unbug status`, or None if it never ran."""
    directory = Path(state_dir) / "guard"
    out = {}
    for name, default in (("status.json", {}), ("alerts.json", {}), ("evidence.json", [])):
        try:
            path = directory / name
            out[name] = json.loads(path.read_text()) if path.stat().st_size <= READ_LIMIT else default
        except (OSError, ValueError):
            out[name] = default
    if not out["status.json"]:
        return None
    return {**out["status.json"], "alerts": sorted(a["message"] for a in out["alerts.json"].values()),
            "evidence": out["evidence.json"][-5:]}
