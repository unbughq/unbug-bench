"""Read-only operator context. No runtime launch, worker RPC, keys or case material."""
import json
import math
from pathlib import Path
import re
import time

from durable.classify import PUBLISHED_REASONS
from durable.contract import Outcome, Step


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _workflow(row):
    return {'status': row.status if row.status in ('PENDING', 'ENQUEUED', 'SUCCESS', 'ERROR',
            'CANCELLED', 'MAX_RECOVERY_ATTEMPTS_EXCEEDED') else 'UNKNOWN',
            **{name: getattr(row, name) / 1000 for name in ('created_at', 'updated_at')
               if _number(getattr(row, name, None))}}


def _attempt(row, case_id, batch_id):
    args = row.input.get('args', []) if isinstance(row.input, dict) else []
    value = args[0].get('input', {}) if args and isinstance(args[0], dict) else {}
    if (not isinstance(value, dict) or value.get('case_id') != case_id or value.get('batch_id') != batch_id
            or not row.workflow_id.startswith(case_id + '/')
            or any(type(value.get(k)) is not int or value[k] < 1 for k in ('seq', 'attempt'))):
        return None
    step = Step(**value['step'])
    return dict(_workflow(row), seq=value['seq'], step=step.name, attempt=value['attempt'])


def _result(row, case_id, batch_id):
    attempt = _attempt(row, case_id, batch_id)
    output = row.output
    result = output.get('result') if isinstance(output, dict) else None
    if attempt is None or not isinstance(result, dict) or result.get('outcome') not in {v.value for v in Outcome}:
        return None
    reason = result.get('reason')
    attempt.update(outcome=result['outcome'], reason=reason if isinstance(reason, str) and reason in PUBLISHED_REASONS else None,
                   snapshot_saved=isinstance(result.get('snapshot'), dict))
    if _number(result.get('retry_at')):
        attempt['retry_at'] = result['retry_at']
    return attempt


def _worker(state, case_id):
    try:
        path = Path(state) / 'pool' / (case_id + '.json')
        if path.stat().st_size > 4096:
            return {'state': 'unavailable'}
        value = json.loads(path.read_text())
        worker = value.get('worker')
        if worker is not None and (not isinstance(worker, str) or not re.fullmatch(r'bx_[a-z0-9]{8}', worker)):
            return {'state': 'unavailable'}
        return {'id': worker, 'state': 'deleting' if value.get('deleting') else
                'assigned' if worker else 'creating' if value.get('intent') else 'unassigned'}
    except FileNotFoundError:
        return {'id': None, 'state': 'unassigned'}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'state': 'unavailable'}


def _budget(config, batch):
    import sqlalchemy as sa
    from durable.ledger import _make_engine, BATCHES, ATTEMPTS, SqlLedger
    url = sa.engine.make_url(config['database_url'])
    if url.get_backend_name() == 'sqlite':
        import sqlite3
        from urllib.parse import quote
        uri = 'file:' + quote(str(Path(url.database).absolute())) + '?mode=ro'
        engine = sa.create_engine('sqlite://', creator=lambda: sqlite3.connect(uri, uri=True, isolation_level=None))
        @sa.event.listens_for(engine, 'begin')
        def begin(conn):
            conn.exec_driver_sql('BEGIN')
    else:
        engine = _make_engine(config['database_url'])
    try:
        with engine.connect() as conn:
            if conn.dialect.name == 'postgresql':
                conn = conn.execution_options(isolation_level='REPEATABLE READ', postgresql_readonly=True)
            with conn.begin():
                bound = conn.execute(sa.select(BATCHES.c.bound_usd_micros).where(BATCHES.c.batch_id == batch)).scalar_one()
                held, spent, waste = SqlLedger._batch_sums(conn, batch)
                calls = conn.execute(sa.select(sa.func.coalesce(sa.func.sum(ATTEMPTS.c.calls), 0))
                    .where(ATTEMPTS.c.batch_id == batch, ATTEMPTS.c.state != 'held')).scalar_one()
                counts = dict(conn.execute(sa.select(ATTEMPTS.c.state, sa.func.count())
                    .where(ATTEMPTS.c.batch_id == batch).group_by(ATTEMPTS.c.state)).all())
        return dict(bound=int(bound), held=held, spent=spent, waste=waste,
                    remaining=max(0, int(bound) - held - spent), settled_calls=int(calls),
                    attempts={k: int(v) for k, v in counts.items() if k in ('held', 'settled', 'lost')})
    finally:
        engine.dispose()


def observe(config, card):
    """Enrich a public scorecard with allowlisted records; unavailable sections stay explicit."""
    from dbos import DBOSClient
    card = {**card, 'cases': [dict(case) for case in card['cases']]}
    meta = card['observation'] = {'at': time.time(), 'unavailable': []}
    try:
        meta['budget'] = _budget(config, card['batch'])
    except Exception:
        meta['unavailable'].append('budget')
    client = None
    try:
        client = DBOSClient(system_database_url=config['database_url'], retry_connection_errors=False,
                            observability_query_timeout_sec=3)
        batch_rows = client.list_workflows(workflow_ids=[card['batch']], load_input=True, load_output=False)
        if batch_rows:
            row = batch_rows[0]
            meta['workflow'] = _workflow(row)
            inputs = row.input
            args = inputs.get('args', []) if isinstance(inputs, dict) else []
            spec = args[0].get('spec', {}) if args and isinstance(args[0], dict) else {}
            meta['limits'] = {name: spec[name] for name in ('target_sealed', 'max_cases_started',
                'max_concurrency', 'deadline_epoch') if _number(spec.get(name))}
            if 'target_sealed' in meta['limits']:
                card['target_sealed'] = meta['limits']['target_sealed']
        for case in card['cases']:
            context = case['operation'] = {'worker': _worker(config['state_dir'], case['case'])}
            try:
                rows = client.list_workflows(workflow_ids=[case['case']], load_input=False, load_output=False)
                if rows:
                    context['workflow'] = _workflow(rows[0])
                attempts = client.list_workflows(workflow_id_prefix=case['case'] + '/',
                    name=['attempt_workflow', 'prepared_attempt_workflow'],
                    load_input=True, load_output=True, sort_desc=True, limit=25)
                if attempts:
                    context['latest_attempt'] = _attempt(attempts[0], case['case'], card['batch'])
                for row in attempts:
                    if row.status == 'SUCCESS':
                        result = _result(row, case['case'], card['batch'])
                        if result is not None:
                            context['last_result'] = result
                            break
            except Exception:
                context['unavailable'] = True
    except Exception:
        meta['unavailable'].append('workflows')
    finally:
        if client is not None:
            client.destroy()
    return card
