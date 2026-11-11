"""The Sealing Board, built from live factory records on every read (bench promise O8).

One row per case in every batch the ledger knows: status, stage, writer round, gates passed
(and the gate that failed), spend, and the time of the case's last recorded event. Nothing
here is typed by hand or cached, so the board cannot drift from the factory: rerun it and it
says what the engine and the ledger say now.

Read-only, like `unbug status`: the ledger is opened read-only, DBOS through a DBOSClient,
and nothing launches work, contacts workers or reads case material. Each row reuses the same
scorecard (report.py) and observation (observation.py) code as `unbug status <batch>`, so the
board and the per-batch status cannot disagree.

Controller-side imports stay inside read_board: the laptop client ships only render_board.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional


# Statuses that end a case: nothing more will happen to it in its batch.
FINAL = ("sealed", "retired", "not_admitted", "stopped_admission", "engine_error")
LIVE_WORKFLOW = ("PENDING", "ENQUEUED")
# A held case either waits for a factory release and resumes by itself (engine wait_for_fix) or
# needs the founder's decision; the board says which.
HELD_LABELS = {"held": "held: needs your decision", "held_for_release": "held: waiting for a factory release"}
# A batch workflow in one of these states has ended. Any other value, including an unread
# one, is not evidence that it ended, so its unfinished cases stay on the live board.
ENDED_WORKFLOW = ("SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED")


def _ledger(config) -> tuple[list[str], dict]:
    """Every batch id, and per (batch, case) money in micro-dollars, from one read-only pass."""
    import sqlalchemy as sa
    from durable.ledger import ATTEMPTS, BATCHES, HELD, LOST, REBOOKED, SETTLED
    from durable.observation import readonly, readonly_engine
    a = ATTEMPTS.c
    # Settled money later rebooked as waste (SqlLedger.book_waste) is waste, never the case's.
    is_waste = sa.or_(a.waste, a.idempotency_key.in_(sa.select(REBOOKED.c.idempotency_key)))
    zero = 0
    def total(*whens):
        return sa.func.coalesce(sa.func.sum(sa.case(*whens, else_=zero)), zero)
    engine = readonly_engine(config)
    try:
        with engine.connect() as conn:
            conn = readonly(conn)
            with conn.begin():
                batches = [r[0] for r in conn.execute(sa.select(BATCHES.c.batch_id).order_by(BATCHES.c.batch_id))]
                rows = conn.execute(sa.select(
                    a.batch_id, a.case_id,
                    total((a.state == SETTLED, a.paid_usd_micros), (a.state == LOST, a.granted_usd_micros)),
                    total((a.state == HELD, a.granted_usd_micros)),
                    total((sa.and_(a.state == SETTLED, is_waste), a.paid_usd_micros), (a.state == LOST, a.granted_usd_micros)),
                    # The case's own money: the same rule as SqlLedger._case_used.
                    total((sa.and_(a.draws_case_money, sa.not_(a.waste), a.state == HELD), a.granted_usd_micros),
                          (sa.and_(a.draws_case_money, sa.not_(is_waste), a.state == SETTLED), a.paid_usd_micros)),
                    total((a.state == SETTLED, a.list_usd_micros)),
                    total((a.state != HELD, a.calls)),
                ).group_by(a.batch_id, a.case_id)).all()
    finally:
        engine.dispose()
    money = {(r[0], r[1]): {'spent': int(r[2]), 'held': int(r[3]), 'waste': int(r[4]),
                            'case_used': int(r[5]), 'list_price': int(r[6]), 'calls': int(r[7])} for r in rows}
    return batches, money


def _latest(*stamps) -> Optional[float]:
    values = [s for s in stamps if type(s) in (int, float)]
    return max(values) if values else None


def _row(batch: str, batch_workflow: Optional[str], case: dict, money: dict, now: float) -> dict:
    gates = case.get('gates', {})
    context = case.get('operation', {})
    workflow = context.get('workflow', {})
    active = context.get('latest_attempt') or {}
    previous = context.get('last_result') or {}
    last = _latest(workflow.get('updated_at'), active.get('updated_at'), active.get('created_at'),
                   previous.get('updated_at'))
    row = {
        'batch': batch, 'case': case['case'], 'status': case['status'], 'stage': case['stage'],
        'writer_round': case['writer_rounds'],
        'gates_passed': [g for g, v in gates.items() if v == 'pass'],
        'failed_gate': next((g for g, v in gates.items() if v == 'fail'), None),
        'reason': case.get('reason'),
        'spend_usd_micros': money.get((batch, case['case']),
                                      {'spent': 0, 'held': 0, 'waste': 0, 'case_used': 0, 'list_price': 0, 'calls': 0}),
        'last_event_at': last,
        'quiet_for_s': round(now - last) if last is not None and now >= last else None,
        'latest_attempt': (f"{active['seq']}/{active['step']}/{active['attempt']} {active['status']}"
                           if active else None),
        'last_result': (previous['outcome'] + (f" ({previous['reason']})" if previous.get('reason') else '')
                        if previous else None),
        'worker': context.get('worker', {}).get('state', 'unavailable'),
        'batch_workflow': batch_workflow or 'UNKNOWN',
        'live': batch_workflow not in ENDED_WORKFLOW and case['status'] not in FINAL,
    }
    if 'hard' in case:
        row['hard'] = case['hard']
    if case.get('replacement_of'):
        row['replacement_of'] = case['replacement_of']
    if context.get('unavailable'):
        row['unavailable'] = True
    return row


def read_board(config, *, client=None, live_only: bool = False, now: Optional[float] = None) -> dict:
    """The board as JSON-ready data. Sections that cannot be read are named in `unavailable`
    and their rows are left out rather than guessed."""
    from dbos import DBOSClient
    from durable.classify import PUBLISHED_REASONS
    from durable.guard import health as guard_health
    from durable.report import load_cards, scorecard
    from durable.observation import _controller, observe
    at = time.time() if now is None else now
    board = {'at': at, 'unavailable': [], 'controller': _controller(config),
             'guard': guard_health(config['state_dir']), 'cases': []}
    try:
        batches, money = _ledger(config)
    except Exception:
        board['unavailable'].append('ledger')
        return _summarise(board)
    owned = client is None
    try:
        if client is None:
            client = DBOSClient(system_database_url=config['database_url'], retry_connection_errors=False,
                                observability_query_timeout_sec=3)
        for batch in batches:
            try:
                card = scorecard(batch, load_cards(batch, client=client), allowlist=PUBLISHED_REASONS)
                seen = observe(config, card, client=client, controller=board['controller'], guard=board['guard'] or {})
            except Exception:
                board['unavailable'].append(batch)
                continue
            missing = seen['observation'].get('unavailable', [])
            # observe() reports a failed workflow read here instead of raising: keep the batch
            # state unknown and say so, rather than reading the gap as an ended batch.
            board['unavailable'] += [f'{batch}:{section}' for section in missing if section == 'workflows']
            workflow = None if 'workflows' in missing else seen['observation'].get('workflow', {}).get('status')
            for case in seen['cases']:
                board['cases'].append(_row(batch, workflow, case, money, at))
    except Exception:
        board['unavailable'].append('workflows')
    finally:
        if owned and client is not None:
            client.destroy()
    if live_only:
        board['cases'] = [r for r in board['cases'] if r['live']]
    board['cases'].sort(key=lambda r: (not r['live'], -(r['last_event_at'] or 0), r['batch'], r['case']))
    return _summarise(board)


def _summarise(board: dict) -> dict:
    rows = board['cases']
    board['totals'] = {}
    for r in rows:
        board['totals'][r['status']] = board['totals'].get(r['status'], 0) + 1
    board['sealed'] = board['totals'].get('sealed', 0)
    board['live'] = sum(r['live'] for r in rows)
    board['spend_usd_micros'] = {k: sum(r['spend_usd_micros'][k] for r in rows) for k in ('spent', 'held', 'waste')}
    return board


def render_board(board: dict) -> str:
    def stamp(value):
        if type(value) not in (int, float):
            return '-'
        return datetime.fromtimestamp(value, timezone.utc).strftime('%d %b %H:%M UTC')
    def money(value):
        return f'${value / 1_000_000:,.2f}'
    def ago(seconds):
        if seconds is None:
            return '-'
        return f'{seconds // 3600}h{seconds % 3600 // 60:02d}m' if seconds >= 3600 else f'{seconds // 60}m'
    controller = board.get('controller', {})
    guard = board.get('guard') or {}
    spend = board['spend_usd_micros']
    lines = ['SEALING BOARD (generated from the engine and ledger; do not edit by hand)',
             f"Observed {stamp(board['at'])}   controller {str(controller.get('state', 'unavailable')).upper()}"
             f"   guard {str(guard.get('phase', 'unavailable')).upper()}",
             f"{board['sealed']} sealed, {board['live']} live, {len(board['cases'])} cases; "
             f"spent {money(spend['spent'])} (waste {money(spend['waste'])}), reserved {money(spend['held'])}",
             '']
    header = ('case', 'status', 'stage', 'round', 'gates passed', 'spent', 'last event', 'quiet')
    table = [header]
    for r in board['cases']:
        gates = ' '.join(r['gates_passed']) or '-'
        if r['failed_gate']:
            gates += f" ({r['failed_gate']} failed)"
        if r['status'] in FINAL:
            note = ''
        elif r.get('batch_workflow') in ENDED_WORKFLOW:
            note = ' [batch ended]'
        elif r.get('batch_workflow') not in LIVE_WORKFLOW:
            note = ' [batch state unknown]'
        else:
            note = ''
        status = HELD_LABELS.get(r['status'], r['status']) + (f" ({r['reason']})" if r['reason'] else '') + note
        table.append((r['case'], status, r['stage'], str(r['writer_round']), gates,
                      money(r['spend_usd_micros']['spent']), stamp(r['last_event_at']), ago(r['quiet_for_s'])))
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    for i, row in enumerate(table):
        lines.append('  '.join(cell.ljust(widths[j]) for j, cell in enumerate(row)).rstrip())
        if i == 0:
            lines.append('  '.join('-' * w for w in widths))
    for message in guard.get('alerts', []):
        lines.append(f'NEEDS YOU: {message}')
    if controller.get('state') in ('inactive', 'failed'):
        lines.append('WARNING: Controller is stopped; live rows are recorded state, not running work.')
    if board['unavailable']:
        lines.append('Unavailable (rows left out, not guessed): ' + ', '.join(board['unavailable']))
    return '\n'.join(lines) + '\n'
