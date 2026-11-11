"""The Sealing Board, built from live factory records on every read (bench promise O8).

One row per case in every batch the ledger knows: status, stage, writer round, gates passed
(and the gate that failed), spend, and the time of the case's last recorded event. Nothing
here is typed by hand or cached, so the board cannot drift from the factory: rerun it and it
says what the engine and the ledger say now.

Read-only, like `unbug status`: the ledger is opened read-only, DBOS through a DBOSClient,
and nothing launches work, contacts workers or reads case material. Each row reuses the same
scorecard (report.py) and observation (observation.py) code as `unbug status <batch>`, so the
board and the per-batch status cannot disagree.

Each case also carries its time to seal (`time_to_seal`), from the same DBOS attempt records
across every batch of its case id (a resumed case keeps its id): wall time since its first
attempt, split by step kind into attempts that produced a result and attempts lost to infra or
provider limits, worker setup (reserve to lease), waits between attempts, and time held for a
human (a founder decision, a factory_bug hold, or a resume into a new batch). `fleet` adds the
median and p90 time to seal and the largest time sinks over the last WINDOW_S.

Controller-side imports stay inside read_board: the laptop client ships only render_board.
"""
from __future__ import annotations

import math
import statistics
import time
from datetime import datetime, timezone
from typing import Optional


# Statuses that end a case: nothing more will happen to it in its batch.
FINAL = ("sealed", "retired", "not_admitted", "stopped_admission", "engine_error")
LIVE_WORKFLOW = ("PENDING", "ENQUEUED")
# A batch workflow in one of these states has ended. Any other value, including an unread
# one, is not evidence that it ended, so its unfinished cases stay on the live board.
ENDED_WORKFLOW = ("SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED")
SEAL_BUDGET_S = 6 * 3600   # founder target: every case seals within 6 hours
WINDOW_S = 7 * 86400       # fleet summary: cases with an event in the last week
PATH = ("admit", "writer", "stress", "gates", "seal")   # one pass; repair rounds add more
LOST = ("infra_error", "provider_limit")                # attempts that reached no result
HUMAN = ("escalated", "held")                           # a case parked on a person


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


def _live_start(client, row) -> Optional[float]:
    """When a running attempt got its worker: a prepared attempt was leased before it began;
    otherwise its recorded lease_step (engine.attempt_workflow) ended. None while still in setup."""
    if row.name == 'prepared_attempt_workflow':
        return row.created_at / 1000
    leases = [s for s in client.list_workflow_steps(row.workflow_id, load_output=False)
              if s.function_name.endswith('lease_step') and s.completed_at_epoch_ms]
    return leases[-1].completed_at_epoch_ms / 1000 if leases else None


def _spans(client, case_id: str) -> list:
    """Every attempt of the case, in any batch, as content-free timings."""
    from durable.observation import _attempt, _number, _result
    rows = client.list_workflows(workflow_id_prefix=case_id + '/',
                                 name=['attempt_workflow', 'prepared_attempt_workflow'],
                                 load_input=True, load_output=True)
    spans = []
    for row in rows:
        args = row.input.get('args', []) if isinstance(row.input, dict) else []
        value = args[0].get('input', {}) if args and isinstance(args[0], dict) else {}
        batch = value.get('batch_id') if isinstance(value, dict) else None
        span = (_result(row, case_id, batch) if row.status == 'SUCCESS' else None) or _attempt(row, case_id, batch)
        if span is None or 'created_at' not in span:
            continue
        output = row.output if isinstance(row.output, dict) else {}
        result = output.get('result') if isinstance(output.get('result'), dict) else {}
        span.update(batch=batch, kind=span['step'].partition(':')[0], started=output.get('started') is not False,
                    verdict=result.get('verdict') if isinstance(result.get('verdict'), str) else None)
        span['started_at'] = output['started_at'] if _number(output.get('started_at')) else None
        if span['status'] in ('PENDING', 'ENQUEUED'):
            span['started_at'] = _live_start(client, row)
        spans.append(span)
    return sorted(spans, key=lambda s: (s['created_at'], s['seq'], s['attempt']))


def _time_to_seal(spans: list, status: str, stage: str, now: float, medians: dict) -> Optional[dict]:
    """Split a case's wall time since its first attempt. Pure: spans come from _spans."""
    if not spans:
        return None
    steps = {k: {'result': 0.0, 'lost': 0.0, 'running': 0.0} for k in PATH[:4] + ('diagnosis', 'seal')}
    out = {'setup_s': 0.0, 'wait_s': 0.0, 'human_s': 0.0}
    first = cursor = spans[0]['created_at']
    previous, sealed_at, running = None, None, 0.0
    for s in spans:
        start = max(s['created_at'], cursor)
        end = s['updated_at'] if s['status'] not in ('PENDING', 'ENQUEUED') else now
        if previous is not None and start > cursor:
            human = (previous.get('outcome') == 'needs_founder' or previous.get('verdict') == 'factory_bug'
                     or previous['batch'] != s['batch'])
            out['human_s' if human else 'wait_s'] += start - cursor
        end = max(end, start)
        if not s['started']:          # never reached a worker: waiting for bound, funding or a deadline
            out['wait_s'] += end - start
        else:
            run_from = min(max(end if s['started_at'] is None else s['started_at'], start), end)
            out['setup_s'] += run_from - start
            pot = ('running' if end == now and s['status'] in ('PENDING', 'ENQUEUED') else
                   'lost' if s.get('outcome') in (None,) + LOST else 'result')
            steps[s['kind']][pot] += end - run_from
            if pot == 'running':
                running = end - run_from
        if s['kind'] == 'seal' and s.get('outcome') == 'ok':
            sealed_at = end
        cursor, previous = max(cursor, end), s
    if status == 'sealed' and sealed_at is not None:
        until = sealed_at
    elif status in FINAL:
        until = cursor                 # retired or stopped: the clock stops at its last attempt
    else:
        until = max(now, cursor)
        out['human_s' if status in HUMAN else 'wait_s'] += until - cursor
    elapsed = until - first
    out = {'first_attempt_at': first, 'elapsed_s': round(elapsed),
           'steps': {k: {p: round(v) for p, v in pots.items() if v} for k, pots in steps.items() if any(pots.values())},
           **{k: round(v) for k, v in out.items()}}
    if status == 'sealed':
        out['budget'] = 'met' if elapsed <= SEAL_BUDGET_S else 'missed'
    elif status in FINAL:
        out['budget'] = 'ended'
    else:
        kind = stage.partition(':')[0]
        todo = (('diagnosis',) + PATH[1:]) if kind == 'diagnosis' else PATH[PATH.index(kind):] if kind in PATH else ()
        # ponytail: one pass of each remaining step at its median, a floor; repair rounds add more.
        remaining = sum(medians.get(k, 0) for k in todo[1:]) + max(0.0, medians.get(todo[0], 0) - running) if todo else 0
        out['projected_remaining_s'] = round(remaining)
        out['budget'] = ('over' if elapsed > SEAL_BUDGET_S else
                         'at_risk' if elapsed + remaining > SEAL_BUDGET_S else 'on_track')
    return out


def _medians(all_spans) -> dict:
    """Median seconds per step kind of past attempts that produced a result (setup included)."""
    by_kind = {}
    for s in all_spans:
        if s.get('outcome') and s['outcome'] not in LOST and s['started']:
            by_kind.setdefault(s['kind'], []).append(s['updated_at'] - s['created_at'])
    return {k: statistics.median(v) for k, v in by_kind.items()}


def _fleet(times: dict, now: float) -> dict:
    """Median and p90 time to seal of cases sealed in the window, and its five largest time sinks."""
    recent = [t for t in times.values() if t and t['first_attempt_at'] + t['elapsed_s'] >= now - WINDOW_S]
    sealed = sorted(t['elapsed_s'] for t in recent if t['budget'] in ('met', 'missed'))
    sinks = {}
    for t in recent:
        for kind, pots in t['steps'].items():
            for pot, seconds in pots.items():
                sinks[f'{kind} ({pot})'] = sinks.get(f'{kind} ({pot})', 0) + seconds
        for name in ('setup', 'wait', 'human'):
            sinks[name] = sinks.get(name, 0) + t[name + '_s']
    top = sorted(((k, v) for k, v in sinks.items() if v), key=lambda kv: -kv[1])[:5]
    return {'window_s': WINDOW_S, 'budget_s': SEAL_BUDGET_S, 'cases': len(recent), 'sealed': len(sealed),
            'median_s': round(statistics.median(sealed)) if sealed else None,
            'p90_s': sealed[math.ceil(0.9 * len(sealed)) - 1] if sealed else None,   # nearest rank
            'within_budget': sum(s <= SEAL_BUDGET_S for s in sealed),
            'top_sinks': [{'sink': k, 'seconds': v} for k, v in top]}


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
        spans = {}
        for case_id in dict.fromkeys(r['case'] for r in board['cases']):
            try:
                spans[case_id] = _spans(client, case_id)
            except Exception:
                board['unavailable'].append(f'{case_id}:time')
        medians = _medians(s for v in spans.values() for s in v)
        times = {}
        for r in sorted(board['cases'], key=lambda r: r['last_event_at'] or 0):   # the latest row wins
            if r['case'] in spans:
                times[r['case']] = _time_to_seal(spans[r['case']], r['status'], r['stage'], at, medians)
        for r in board['cases']:
            r['time_to_seal'] = times.get(r['case'])
        board['fleet'] = _fleet(times, at)
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
    def clock(t):
        if not t:
            return ('-', '-')
        flag = t['budget'].upper().replace('_', ' ')
        if 'projected_remaining_s' in t:
            flag += f" (+{ago(t['projected_remaining_s'])})"
        return (ago(t['elapsed_s']), flag)
    controller = board.get('controller', {})
    guard = board.get('guard') or {}
    spend = board['spend_usd_micros']
    lines = ['SEALING BOARD (generated from the engine and ledger; do not edit by hand)',
             f"Observed {stamp(board['at'])}   controller {str(controller.get('state', 'unavailable')).upper()}"
             f"   guard {str(guard.get('phase', 'unavailable')).upper()}",
             f"{board['sealed']} sealed, {board['live']} live, {len(board['cases'])} cases; "
             f"spent {money(spend['spent'])} (waste {money(spend['waste'])}), reserved {money(spend['held'])}",
             '']
    header = ('case', 'status', 'stage', 'round', 'gates passed', 'spent', 'last event', 'quiet', 'to seal', '6h')
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
        status = r['status'] + (f" ({r['reason']})" if r['reason'] else '') + note
        table.append((r['case'], status, r['stage'], str(r['writer_round']), gates,
                      money(r['spend_usd_micros']['spent']), stamp(r['last_event_at']), ago(r['quiet_for_s']),
                      *clock(r.get('time_to_seal'))))
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    for i, row in enumerate(table):
        lines.append('  '.join(cell.ljust(widths[j]) for j, cell in enumerate(row)).rstrip())
        if i == 0:
            lines.append('  '.join('-' * w for w in widths))
    fleet = board.get('fleet')
    if fleet:
        lines += ['', f"TIME TO SEAL (target {ago(fleet['budget_s'])}; last {fleet['window_s'] // 86400} days): "
                      f"{fleet['sealed']} sealed, median {ago(fleet['median_s'])}, p90 {ago(fleet['p90_s'])}, "
                      f"{fleet['within_budget']} within target",
                  'Top time sinks: ' + (', '.join(f"{x['sink']} {ago(x['seconds'])}" for x in fleet['top_sinks']) or '-')]
        seen = set()
        for r in board['cases']:
            t = r.get('time_to_seal')
            if not t or r['case'] in seen:
                continue
            seen.add(r['case'])
            split = [f"{k} {ago(v.get('result', 0))}" + ''.join(f" ({p} {ago(v[p])})" for p in ('lost', 'running') if p in v)
                     for k, v in t['steps'].items()]
            split += [f"{n} {ago(t[n + '_s'])}" for n in ('setup', 'wait', 'human') if t[n + '_s']]
            lines.append(f"  {r['case']}: {ago(t['elapsed_s'])} = " + ', '.join(split))
    for message in guard.get('alerts', []):
        lines.append(f'NEEDS YOU: {message}')
    if controller.get('state') in ('inactive', 'failed'):
        lines.append('WARNING: Controller is stopped; live rows are recorded state, not running work.')
    if board['unavailable']:
        lines.append('Unavailable (rows left out, not guessed): ' + ', '.join(board['unavailable']))
    return '\n'.join(lines) + '\n'
