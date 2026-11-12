"""Advance warnings of known limits, for the campaign guard's alerts and status.

Warnings only: nothing here pauses, stops or deletes anything, and a warning never marks the
batch degraded. Each check is independent. A check that cannot read its input yields an
"unknown" warning instead of raising, so a broken check never breaks a guard pass.

Messages are public-safe: fixed text and numbers, never paths or provider output.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import ssl
import subprocess
from typing import Callable, Optional

CERT_PATH = "/run/unbug-bench/router.crt"   # UNBUG_ROUTER_CERT overrides it
CERT_WARN_S = 3 * 86400
HEADROOM_WARN_USD = 10.0
DEADLINE_WARN_S = 6 * 3600


def cert_expiry(path) -> float:
    """The certificate's notAfter, as epoch seconds, from `openssl x509`."""
    done = subprocess.run(["openssl", "x509", "-enddate", "-noout", "-in", str(path)],
                          capture_output=True, text=True, timeout=10)
    out = done.stdout.strip()
    if done.returncode or not out.startswith("notAfter="):
        raise ValueError("unreadable certificate")
    return float(ssl.cert_time_to_seconds(out[len("notAfter="):]))


def check_cert(path, now: float) -> Optional[str]:
    left = cert_expiry(path) - now
    if left >= CERT_WARN_S:
        return None
    if left <= 0:
        return "The router's TLS certificate has expired. Renew it: callers will refuse the router."
    return f"The router's TLS certificate expires in {left / 3600:.0f} hours. Renew it before then."


def check_headroom(router: Callable) -> Optional[str]:
    spent, ceiling, *_ = router()
    if not math.isfinite(ceiling):
        return None   # no ceiling set: the router has no paid limit to run into
    left = ceiling - spent
    if left >= HEADROOM_WARN_USD:
        return None
    return (f"The router has ${max(left, 0):.2f} left under its paid ceiling of ${ceiling:.2f}. "
            "Paid calls stop at the ceiling; raise it or expect waits.")


def check_deadline(request: dict, now: float) -> Optional[str]:
    deadline = request["deadline_epoch"]
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ValueError("deadline_epoch")
    left = deadline - now
    if left >= DEADLINE_WARN_S or left <= 0:   # past the deadline the guard's hard stop speaks
        return None
    return f"The campaign deadline is {left / 3600:.1f} hours away. At the deadline the guard stops the factory."


def campaign_routes(request: dict, rotation_path) -> list:
    """The models the campaign's roles use: the request's explicit `models` (role -> chain, as
    INPUTS spells them) when it has them, otherwise every family and role model in the rotation table."""
    models = request.get("models")
    if isinstance(models, dict) and models:
        chains = [chain for role, chain in models.items() if role != "reviewers"] + list(models.get("reviewers") or [])
        found = [m for chain in chains for m in (chain if isinstance(chain, list) else [chain])]
    else:
        table = json.loads(Path(rotation_path).read_text())
        found = [family["model"] for family in table["families"].values()]
        found += [m for by_family in (table.get("role_models") or {}).values() for m in by_family.values()]
    if not found or not all(isinstance(m, str) for m in found):
        raise ValueError("no routes")
    return sorted(set(found))


def unbounded(models: list) -> list:
    """The models whose whole chain has no route with a positive maximum, so every lease for
    them is refused as unbounded_route."""
    import model_router
    out = []
    for model in models:
        if not any((model_router.route_maximum(r["route"]) or {}).get("max_usd", 0) > 0
                   for r in model_router.routes(model)):
            out.append(model)
    return out


def check_routes(request: dict, rotation_path) -> Optional[str]:
    missing = unbounded(campaign_routes(request, rotation_path))
    if not missing:
        return None
    return (f"No bounded route for {', '.join(missing)}: the router will refuse every call for it. "
            "Add a price maximum or change the rotation.")


def warnings(request: dict, now: float, *, router: Optional[Callable] = None, cert_path=None,
             rotation_path=None) -> dict:
    """{alert key: message} for every limit that is close, or that could not be read."""
    if cert_path is None:
        cert_path = os.environ.get("UNBUG_ROUTER_CERT", CERT_PATH)
    if rotation_path is None:
        rotation_path = (Path(__file__).resolve().parents[1]
                         / os.environ.get("FACTORY_ROTATION", "rotation-3writers.json"))
    checks = {
        "router_cert": ("the router's TLS certificate expiry", lambda: check_cert(cert_path, now)),
        "deadline": ("the campaign deadline", lambda: check_deadline(request, now)),
        "routes": ("whether every role has a bounded route", lambda: check_routes(request, rotation_path)),
    }
    if router is not None:
        checks["router_headroom"] = ("the router's paid headroom", lambda: check_headroom(router))
    out = {}
    for name, (what, call) in checks.items():
        try:
            message = call()
        except Exception:   # an unreadable input is a warning of its own, never a crash
            out[f"preflight:{name}:unknown"] = f"Could not check {what}. It is unknown, so it may be close."
            continue
        if message:
            out[f"preflight:{name}"] = message
    return out
