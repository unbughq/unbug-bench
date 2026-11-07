"""The campaign guard: one pass a minute, run by a systemd timer as root.

A failed check never stops anything. It is retried, logged and marks the batch degraded,
which pauses new attempts (engine.py) until a pass succeeds. Only these are hard stops: the
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
import time
from typing import Callable, Optional
import urllib.request

from durable.workers import _atomic_json

RETRY_WAITS_S = (2.0, 6.0)   # a check gets three tries; the unit timeout fits a pass where all fail
GRACE_S = 120.0              # a controller that just came up is not judged yet
CHECKPOINT_GRACE_S = 600.0   # after a hard stop, for steps in flight; a pass runs once a minute
ESCALATE_S = 900.0           # sustained failure raises an alert; it still stops nothing
DOWN_ALERT_S = 600.0
MARKER_TTL_S = 600.0         # a dead guard cannot pause admission for longer than this
EVIDENCE_KEPT = 200
READ_LIMIT = 1 << 20
TERMINAL = ("sealed", "retired", "held", "stopped_admission", "engine_error")
HARD_STOPS = {
    "deadline": "The batch deadline passed.",
    "money_ceiling": "Spending passed the money ceiling. Check the ledger before raising it.",
    "compute_bound": "Reserved compute passed the approved infrastructure budget.",
    "worker_count": "More than one live worker. Check Boat before restarting.",
    "worker_allowance": "More workers were created than the allowance permits.",
    "worker_rate": "A worker costs more than its approved rate or bound. Check Boat.",
}
CASE_ALERTS = {
    "escalated": "{case} needs your ruling before it can continue.",
    "held": "{case} is held and needs your decision.",
    "waiting_for_bound": "{case} is waiting for budget. Raise the batch bound or retire it.",
    "waiting_for_release": "{case} is waiting for a fixed plumbing release.",
    "retrying_admission": "{case} keeps failing admission on infrastructure and is still retrying. Check its stop reason.",
    "stopped_admission": "{case} stopped admission. Decide whether to start a new batch.",
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


class Guard:
    def __init__(self, request: dict, directory: Path, *, boat: Callable, rpc: Callable, service,
                 ours: Callable, count: Callable, delete: Callable, notify: Optional[Callable] = None,
                 router: Optional[Callable] = None,
                 grace_s: float = GRACE_S, escalate_s: float = ESCALATE_S,
                 checkpoint_grace_s: float = CHECKPOINT_GRACE_S, clock=time.time, sleep=time.sleep):
        self.request, self.directory = request, Path(directory)
        self.boat, self.rpc, self.service, self.ours, self.count = boat, rpc, service, ours, count
        self.delete, self.checkpoint_grace_s, self.router = delete, checkpoint_grace_s, router
        self.notify = notify
        self.grace_s, self.escalate_s = grace_s, escalate_s
        self.clock, self.sleep = clock, sleep
        self.failed: list = []
        self.evidence: list = []

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

    def _count(self) -> int:
        count = self.count()
        if type(count) is not int or count < 0:
            raise CheckFailed("allowance_malformed")
        return count

    def _breach(self, owned: list) -> Optional[str]:
        """A hard stop only on confirmed numbers. An unreadable number is a failed check."""
        r = self.request
        worker_bound = r["max_worker_rate_usd_per_second"] * (r["wall_seconds"] + r["max_workers_lifetime"] * 7200)
        if (r["prior_compute_retained_usd"] + r["control_allowance_usd"] + worker_bound
                > r["approved_infrastructure_usd"] - r["cleanup_margin_usd"]):
            return "compute_bound"
        if len(owned) > 1:
            return "worker_count"
        ok, count = self.check("worker_allowance", self._count)
        if ok and count > r["max_workers_lifetime"]:
            return "worker_allowance"
        for row in owned:
            ok, usage = self.check("boat_usage", lambda: self._usage(row["id"]))
            if ok and (usage[1] > r["max_worker_rate_usd_per_second"] or usage[0] > worker_bound):
                return "worker_rate"
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
                  "money_held": None, "router_spent_usd": status.get("router_spent_usd")}
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
        if owned:
            self._extend(owned)
        return self._finish(health, status)

    def _controller(self, health: dict) -> Optional[str]:
        def over_ceiling():
            money = self.rpc("budget")
            health["money_held"] = money.get("held")
            return money["spent"] > money["bound"]
        def router_over_ceiling():
            """The router's charges are the real spend, and the ledger has read low."""
            spent, ceiling = self.router()
            health["router_spent_usd"] = round(spent, 6)
            return spent >= ceiling
        def terminal():
            report = self.rpc("status")
            cases = report["cases"]
            if not all(isinstance(c["case"], str) and isinstance(c["status"], str) for c in cases):
                raise CheckFailed("status_malformed")
            self.save("scorecard.json", report)
            return bool(cases) and all(c["status"] in TERMINAL for c in cases)
        ok, over = self.check("ledger", over_ceiling)
        if ok and over:
            return "money_ceiling"
        if self.router is not None:
            ok, over = self.check("router_spend", router_over_ceiling)
            if ok and over:
                return "money_ceiling"
        ok, finished = self.check("controller_status", terminal)
        if ok and finished:
            done, _ = self.check("publish", lambda: self.rpc("publish"))
            if done:
                health["finished"] = True
                health["phase"] = "finished"
                health["down_since"] = None
                self.check("controller_stop", self.service.stop)
        return None

    def _recording(self, health: dict, active: str) -> bool:
        """Whether to keep waiting for steps in flight. A controller that cannot answer may
        still be recording, so it gets the rest of the grace; a dead one records nothing."""
        if active not in ("active", "unknown"):
            return False
        if self.clock() - health["stopping_since"] >= self.checkpoint_grace_s:
            return False
        ok, running = self.check("in_flight", lambda: self.rpc("in_flight"))
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
        for case in self.load("scorecard.json", {}).get("cases", []):
            if not isinstance(case, dict):
                continue
            # While another attempt holds money, the wait may end by itself.
            if case.get("status") == "waiting_for_bound" and health.get("money_held"):
                continue
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
