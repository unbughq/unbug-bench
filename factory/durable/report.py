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

import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from durable.contract import CASE_ID, GATE, REASON, ArtifactKind, ContractError, Ref

STATUSES = ("sealed", "running", "waiting_for_bound", "escalated", "held", "retired", "stopped_admission",
            "engine_error", "pending_admission", "waiting_for_worker", "not_admitted", "waiting_for_credentials", "waiting_for_router",
            "waiting_for_credit", "waiting_for_release", "retrying_admission", "held_for_release")
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
             # Cards from before the attack cap carry no count.
             "attack_rounds": _count(card.get("attack_rounds", 0), "attack_rounds"),
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


def publish(objects, batch_id: str, cards: Iterable[dict], allowlist: Iterable[str]) -> dict:
    """Write the allowlisted scorecard (codes and numbers only, never case material) to the
    existing object store under its own digest. Objects are never replaced, so a changed
    scorecard is a new key and a repeat of the same one is a no-op."""
    data = json.dumps(scorecard(batch_id, cards, allowlist=allowlist), sort_keys=True).encode()
    key = f"scorecards/{batch_id}/{hashlib.sha256(data).hexdigest()}.json"
    objects.put(key, data)
    if objects.get(key) != data:
        raise ContractError("scorecard publication unverified")
    return {"published": key}


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
                     f"attacks with findings {c.get('attack_rounds', 0)}, extensions {c['extensions']}{rep}; {gates}")
    return "\n".join(lines) + "\n"


def render_status(card: dict) -> str:
    """Terminal view of recorded facts. Worker assignment is not a liveness probe."""
    observation = card.get('observation')
    if not isinstance(observation, dict):
        return render_text(card)
    def stamp(value):
        if type(value) not in (int, float):
            return 'unavailable'
        try:
            return datetime.fromtimestamp(value, timezone.utc).strftime('%d %b %Y %H:%M:%S UTC')
        except (ValueError, OverflowError, OSError):
            return 'unavailable'
    def money(value):
        return f'${value / 1_000_000:,.2f}' if type(value) is int and value >= 0 else 'unavailable'
    def field(label, value):
        return f'  {label:<17} {value}'
    limits = observation.get('limits', {})
    workflow = observation.get('workflow', {})
    controller = observation.get('controller', {})
    lines = ['UNBUG FACTORY', '=' * 76, field('Batch', card['batch']),
             field('Observed', stamp(observation.get('at'))),
             field('Controller', controller.get('state', 'unavailable').upper()
                   + (f" ({controller['result']})" if controller.get('result') else '')),
             field('Workflow', workflow.get('status', 'unavailable')),
             field('Started', stamp(workflow.get('created_at'))),
             field('Sealed', f"{card['sealed']} / {card.get('target_sealed') or '?'}"),
             field('Cases', f"{len(card['cases'])} / {limits.get('max_cases_started', '?')} tracked; "
                   f"concurrency limit {limits.get('max_concurrency', '?')}"),
             field('Admission cutoff', stamp(limits.get('deadline_epoch')))]
    guard = observation.get('guard')
    if guard:
        lines += ['', 'FACTORY HEALTH', '-' * 76, field('Guard', str(guard.get('phase', 'unavailable')).upper()
                  + (f" ({guard['hard_stop']})" if guard.get('hard_stop') else '')),
                  field('Last guard pass', stamp(guard.get('at')))]
        if guard.get('degraded_since') is not None:
            lines.append(field('Degraded since', stamp(guard['degraded_since']) + '  (new attempts paused)'))
        if guard.get('stalled'):
            lines.append(field('Stalled', f"{guard['stalled']}: {', '.join(guard.get('stalled_cases') or [])}"))
        if guard.get('failed_checks'):
            lines.append(field('Failing checks', ', '.join(guard['failed_checks'])))
        lines += [f'  NEEDS YOU: {message}' for message in guard.get('alerts', [])]
        for row in guard.get('evidence', []):
            lines.append(f"  {stamp(row.get('at'))}  {row.get('check')} try {row.get('try')}: {row.get('code')}"
                         f" after {row.get('seconds')}s" + (f" - {row['stderr']}" if row.get('stderr') else ''))
    budget = observation.get('budget')
    if budget:
        lines += ['', 'BATCH BUDGET', '-' * 76,
            field('Ceiling', money(budget.get('bound'))),
            field('Settled spend', money(budget.get('spent'))),
            field('Reserved', money(budget.get('held')) + '  (not yet spent)'),
            field('Unreserved', money(budget.get('remaining'))),
            field('Recorded waste', money(budget.get('waste')) + '  (included in settled spend)'),
            field('Settled calls', budget.get('settled_calls', 'unavailable')),
            field('Attempts', ', '.join(f'{n} {state}' for state, n in budget.get('attempts', {}).items()) or 'none'),
            '  Active attempt usage is not included until it settles.']
    else:
        lines += ['', 'BATCH BUDGET: unavailable']
    for case in card['cases']:
        context = case.get('operation', {})
        worker = context.get('worker', {})
        active = context.get('latest_attempt') or {}
        previous = context.get('last_result') or {}
        lines += ['', case['case'], '-' * 76,
            field('Recorded state', f"{case['status']} / {case['stage']}"),
            field('Workflow', context.get('workflow', {}).get('status', 'unavailable')),
            field('Workflow update', stamp(context.get('workflow', {}).get('updated_at'))),
            field('Worker record', f"{worker.get('id') or '-'} ({worker.get('state', 'unavailable')})"),
            field('Writer rounds', case['writer_rounds']), field('Extensions', case['extensions']),
            field('Attacks with findings', case.get('attack_rounds', 0)),
            field('Gates', '  '.join(f'{g}={value.upper()}' for g, value in case['gates'].items()) or 'none reported')]
        if case.get('reason'):
            lines.append(field('Case reason', case['reason']))
        if case.get('cleanup_error'):
            lines.append(field('WARNING', 'Seal cleanup unconfirmed'))
        if 'hard' in case:
            lines.append(field('Hard case', 'yes' if case['hard'] else 'no'))
        if case.get('replacement_of'):
            lines.append(field('Replaces', case['replacement_of']))
        if active:
            lines += [field('Latest attempt', f"{active['seq']}/{active['step']}/{active['attempt']}  {active['status']}"),
                      field('Attempt started', stamp(active.get('created_at')))]
        if previous:
            lines += [field('Last result', f"attempt {previous['attempt']}: {previous['outcome']}"
                            + (f" ({previous['reason']})" if previous.get('reason') else '')),
                      field('Result recorded', stamp(previous.get('updated_at'))),
                      field('Result checkpoint', 'saved' if previous.get('snapshot_saved') else 'not reported')]
            if previous.get('retry_at') is not None:
                pending = active.get('status') in ('PENDING', 'ENQUEUED')
                lines.append(field('Previous retry' if pending else 'Recorded retry', stamp(previous['retry_at'])))
                if pending:
                    lines.append('  A newer attempt is recorded; the previous result is historical.')
                elif (context.get('workflow', {}).get('status') in ('PENDING', 'ENQUEUED')
                      and worker.get('state') == 'unassigned'):
                    lines.append('  No attempt is active; the workflow is waiting or queued for retry.')
        if context.get('unavailable'):
            lines.append('  Attempt details unavailable.')
    lines += ['', 'Worker state comes from the ownership journal; liveness is not polled.',
              'Workflow timestamps describe records, not the latest model activity.']
    if controller.get('state') in ('inactive', 'failed'):
        lines.append('WARNING: Controller is stopped; pending workflow records do not mean work is running.')
    if observation.get('unavailable'):
        lines.append('Unavailable: ' + ', '.join(observation['unavailable']))
    return '\n'.join(lines) + '\n'


def load_cards(batch_id: str, *, timeout_s: float = 1.0, client=None) -> list:
    """Read persisted cards through launched DBOS or a read-only DBOSClient."""
    if client is None:
        from dbos import DBOS
        event, status = DBOS.get_event, DBOS.get_workflow_status
    else:
        event = client.get_event
        def status(workflow_id):
            rows = client.list_workflows(workflow_ids=[workflow_id], load_input=False, load_output=False)
            return rows[0] if rows else None
    case_ids = event(batch_id, "cases", timeout_seconds=timeout_s) or []
    cards = []
    for case_id in case_ids:
        card = event(case_id, "card", timeout_seconds=timeout_s)
        workflow = status(case_id)
        failed = workflow is not None and workflow.status in ("ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED")
        if failed:
            # A failed workflow cannot update its own event. Keep any previously
            # published, content-free facts and trust only a recorded verified seal.
            card = dict(card or {"case_id": case_id, "stage": "admit", "passed": [], "failed_gate": None,
                                 "writer_rounds": 0, "extensions": 0, "replacement_of": None})
            seal = verified_seal(event(case_id, "verified_seal", timeout_seconds=timeout_s))
            if seal is None:
                card["status"] = "engine_error"
                card.pop("cleanup_error", None)
            else:
                cleaned = event(case_id, "seal_cleanup_complete", timeout_seconds=timeout_s) is True
                card.update(status="sealed", stage="sealed", hard=seal["hard"], cleanup_error=not cleaned)
        if card is not None:
            cards.append(card)
    return cards
