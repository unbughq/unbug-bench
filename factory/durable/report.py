"""The public scorecard, generated from the engine's own records (WP1).

Each case workflow keeps a content-free `card` event (engine.py `_Case.card`): its status,
stage, the gates its latest GATES step passed (`StepResult.passed`) and the one that failed,
its rounds, extensions and reason code. The batch workflow's `cases` event lists the cases.
This module reads those and renders the scorecard. Nothing reads the scorecard back to make
a decision (design, "The case, step by step", 6); WP8 publishes it.

The card shows outcomes, stages and gates. A reason code appears only if it is on the
published-reason allowlist (WP4 ships it); every other reason is withheld.
"""
from __future__ import annotations

from typing import Iterable, Optional

from durable.contract import CASE_ID, GATE, REASON, ArtifactKind, ContractError, Ref

STATUSES = ("sealed", "running", "waiting_for_bound", "escalated", "held", "retired", "stopped_admission",
            "engine_error", "pending_admission", "waiting_for_worker", "not_admitted", "waiting_for_credentials")
STAGE_KINDS = ("admit", "writer", "stress", "gates", "seal", "diagnosis", "sealed")


def _gate_order(g: str) -> int:
    return int(g[1:])


def _stage(value) -> str:
    if not isinstance(value, str):
        raise ContractError("bad stage")
    kind, _, rnd = value.partition(":")
    if kind not in STAGE_KINDS or (rnd and not rnd.isdigit()):
        raise ContractError("bad stage")
    return value


def _count(value, name) -> int:
    if type(value) is not int or value < 0:
        raise ContractError(f"bad {name}")
    return value


def verified_seal(value) -> Optional[dict]:
    """Validate a seal event written only after the engine authenticates the archive."""
    if not isinstance(value, dict) or set(value) != {"archive", "hard"} or type(value["hard"]) is not bool:
        return None
    try:
        archive = Ref(**value["archive"])
    except (ContractError, TypeError):
        return None
    if archive.kind is not ArtifactKind.SEALED_ARCHIVE:
        return None
    return {"archive": {"digest": archive.digest, "kind": archive.kind.value}, "hard": value["hard"]}


def case_entry(card: dict, allowlist: Iterable[str] = ()) -> dict:
    """One public row, checked field by field so nothing but codes and numbers gets out."""
    if not isinstance(card, dict) or not isinstance(card.get("case_id"), str) or not CASE_ID.fullmatch(card["case_id"]):
        raise ContractError("bad card")
    status = card.get("status")
    if status not in STATUSES:
        raise ContractError("bad status")
    passed = card.get("passed") or []
    if not all(isinstance(g, str) and GATE.fullmatch(g) for g in passed):
        raise ContractError("bad gate")
    gates = {g: "pass" for g in sorted(set(passed), key=_gate_order)}
    failed = card.get("failed_gate")
    if failed is not None:
        if not (isinstance(failed, str) and GATE.fullmatch(failed)):
            raise ContractError("bad gate")
        gates[failed] = "fail"
        gates = dict(sorted(gates.items(), key=lambda kv: _gate_order(kv[0])))
    replacement_of = card.get("replacement_of")
    if replacement_of is not None and not (isinstance(replacement_of, str) and CASE_ID.fullmatch(replacement_of)):
        raise ContractError("bad replacement_of")
    reason = card.get("reason")
    shown = reason if isinstance(reason, str) and REASON.fullmatch(reason) and reason in set(allowlist) else None
    entry = {"case": card["case_id"], "status": status, "stage": _stage(card.get("stage")), "gates": gates,
             "writer_rounds": _count(card.get("writer_rounds"), "writer_rounds"),
             "extensions": _count(card.get("extensions"), "extensions"), "replacement_of": replacement_of,
             "reason": shown}
    if status == "sealed":
        if type(card.get("hard")) is not bool:
            raise ContractError("a sealed card says whether it is hard")
        entry["hard"] = card["hard"]
    if "cleanup_error" in card:
        if status != "sealed" or type(card["cleanup_error"]) is not bool:
            raise ContractError("cleanup_error is a boolean on a sealed card")
        entry["cleanup_error"] = card["cleanup_error"]
    return entry


def scorecard(batch_id: str, cards: Iterable[dict], *, allowlist: Iterable[str] = (),
              target_sealed: Optional[int] = None) -> dict:
    allowlist = tuple(allowlist)
    cases = [case_entry(c, allowlist) for c in cards]
    totals = {s: sum(1 for c in cases if c["status"] == s) for s in STATUSES}
    gate_passes = {}
    for c in cases:
        for g, v in c["gates"].items():
            if v == "pass":
                gate_passes[g] = gate_passes.get(g, 0) + 1
    return {"batch": batch_id, "target_sealed": target_sealed, "sealed": totals["sealed"],
            "totals": {k: v for k, v in totals.items() if v},
            "gate_passes": dict(sorted(gate_passes.items(), key=lambda kv: _gate_order(kv[0]))),
            "cases": cases}


def render_text(card: dict) -> str:
    lines = [f"batch {card['batch']}: {card['sealed']} sealed"
             + (f" of {card['target_sealed']}" if card.get("target_sealed") is not None else "")]
    for c in card["cases"]:
        gates = " ".join(f"{g}={v}" for g, v in c["gates"].items()) or "-"
        extra = f" hard={c['hard']}" if "hard" in c else ""
        if c.get("cleanup_error"):
            extra += " cleanup unconfirmed"
        why = f" ({c['reason']})" if c["reason"] else ""
        rep = f" replaces {c['replacement_of']}" if c["replacement_of"] else ""
        lines.append(f"  {c['case']}: {c['status']} at {c['stage']}{why}{extra}; rounds {c['writer_rounds']}, "
                     f"extensions {c['extensions']}{rep}; {gates}")
    return "\n".join(lines) + "\n"


def load_cards(batch_id: str, *, timeout_s: float = 1.0) -> list:
    """Read the cards from a launched engine (DBOS events of the batch and case workflows)."""
    from dbos import DBOS
    case_ids = DBOS.get_event(batch_id, "cases", timeout_seconds=timeout_s) or []
    cards = []
    for case_id in case_ids:
        card = DBOS.get_event(case_id, "card", timeout_seconds=timeout_s)
        workflow = DBOS.get_workflow_status(case_id)
        failed = workflow is not None and workflow.status in ("ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED")
        if failed:
            # A failed workflow cannot update its own event. Keep any previously
            # published, content-free facts and trust only a recorded verified seal.
            card = dict(card or {"case_id": case_id, "stage": "admit", "passed": [], "failed_gate": None,
                                 "writer_rounds": 0, "extensions": 0, "replacement_of": None})
            seal = verified_seal(DBOS.get_event(case_id, "verified_seal", timeout_seconds=timeout_s))
            if seal is None:
                card["status"] = "engine_error"
                card.pop("cleanup_error", None)
            else:
                cleaned = DBOS.get_event(case_id, "seal_cleanup_complete", timeout_seconds=timeout_s) is True
                card.update(status="sealed", stage="sealed", hard=seal["hard"], cleanup_error=not cleaned)
        if card is not None:
            cards.append(card)
    return cards
