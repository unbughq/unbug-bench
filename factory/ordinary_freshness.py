"""Batch G2 refresh and transport policy. Scientific verdicts remain in run.py."""
import model_router
import time
import hashlib
import shutil
import uuid
import datetime

from admission import search_evidence_error
from budget import BudgetError
import freshness_retrieval as retrieval
from freshness_fanout import REPAIRABLE as REFRESH   # expired or failed retrieval: a re-run search fixes it
from ordinary_retry import check, backoff, digest, read, transport
from registry import atomic_json
from run_validity import InvalidInfra


REVIEW_REASKS = 2   # extra reviewer asks per attempt after an unresolved G2 review


def semantic_binding(binding, rows):
    fields = ('who', 'kind', 'query', 'url', 'hit', 'ambiguous', 'note', 'app_version', 'version_scope')
    return {**binding, 'evidence_sha256': digest([{k: row.get(k) for k in fields} for row in rows])}


def obtain(c, rows, directory, *, flagged):
    """Reuse successful URLs while retrying only held retrievals in the next cycle."""
    refresh = getattr(c, 'freshness_refetch_urls', set())
    receipts = []
    sources = []
    for row in rows:
        target = c.work / 'g2-url-retrieval' / digest(row['url'])
        def cycle():
            check(c)
            try:
                saved = retrieval.load(target, [row])
                # A changing live page must not change judgment identity merely
                # because another URL is held. Failed URLs refresh once per cycle.
                if (saved[0]['retrieved_from'] == 'live' or
                        row['url'] not in refresh and type(saved[0]['archive_available']) is bool):
                    return saved
            except InvalidInfra:
                pass
            deadline = min(time.monotonic() + 120, time.monotonic() +
                (model_router.epoch(c.batch_deadline) - time.time()))
            failures = 0
            while True:
                check(c)
                try:
                    result = retrieval.retrieve([row], target, archive=False, deadline=deadline, access=True)
                except InvalidInfra:
                    result = []
                if result and result[0]['retrieved_from'] == 'live': return result
                if result and result[0]['live_failure'] in ('http_404', 'http_410', 'dns_failure'): break
                if time.monotonic() >= deadline: break
                failures += 1
                backoff(c, failures, deadline=deadline)
            check(c)
            remaining = (model_router.epoch(c.batch_deadline) - time.time())
            return retrieval.retrieve([row], target, archive=True,
                deadline=time.monotonic() + min(120, remaining), access=True)
        result = transport(c, {'retrieval': row['url']}, cycle) if flagged else cycle()
        refresh.discard(row['url'])
        receipts.append(result[0])
        sources.append(target)
    # Materialize one authenticated, immutable generation for the reviewer.
    if directory.exists():
        directory.rename(directory.with_name(directory.name + '-superseded-' + uuid.uuid4().hex))
    directory.mkdir(parents=True, exist_ok=True)
    for index, (receipt, source) in enumerate(zip(receipts, sources)):
        for number, response in enumerate(receipt['responses']):
            name = f'{index}-{number}.body'
            shutil.copyfile(source / response['body'], directory / name)
            response['body'] = name
    atomic_json(directory / 'receipts.json', receipts)
    return retrieval.load(directory, rows)


def ensure(run, c):
    """Only completed bad metadata work spends the defect bound; expiry and failed retrieval are refresh."""
    run.finish_freshness_repair(c)
    statement = (c.case / 'statement.md').read_bytes()
    key = hashlib.sha256(statement).hexdigest()
    path = c.work / 'freshness-repair.json'
    state = read(path, {})
    if state:
        if state.get('version') == 1:
            if (type(state.get('attempts')) is not int or not 0 <= state['attempts'] <= 2
                    or not isinstance(state.get('statement_sha256'), str)):
                raise BudgetError('freshness_repair_state_invalid')
            state = {'version': 2, 'statement_sha256': state['statement_sha256'],
                     'completed_defects': state['attempts'], 'pending': None}
        if state.get('version') != 2 or type(state.get('completed_defects')) is not int:
            raise BudgetError('freshness_repair_state_invalid')
    if state.get('statement_sha256') != key:
        state = {'version': 2, 'statement_sha256': key, 'completed_defects': 0, 'pending': None}
    def save():
        atomic_json(path, state)
        c.card['freshness_repair'] = dict(state)
    def metadata():
        """(errors, defect): the rows' G2 errors, and whether anything but a refresh is missing."""
        rows = run.freshness_lines(c)
        errors = [search_evidence_error(r) for r in rows]
        # A row that is only old or unretrieved needs its search re-run, not a repair: judge the
        # rest of it as if refreshed. G2 itself still rejects it until the re-run really happens.
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rows = [{**r, 'at': now, 'retrieved': True} if e in REFRESH else r for r, e in zip(rows, errors)]
        found = {v for r in rows if (v := run.own_search(c, r)) is not None}
        enough = (sum(w == 'builder' and k == 'web' for w,k,q in found) >= 3 and
                  sum(w == 'builder' and k == 'github' for w,k,q in found) >= 3 and
                  sum(w == 'attacker' for w,k,q in found) >= 2)
        return errors, any(search_evidence_error(r) for r in rows) or not enough
    def finish():
        pending = state['pending']
        if not pending or pending['phase'] != 'completed': return
        errors, defect = metadata()
        if defect: state['completed_defects'] += 1
        pending['charged'] = True
        state['pending'] = None
        state['last_topup'] = digest(run.freshness_lines(c))
        save()
        if defect and state['completed_defects'] >= 2:
            raise BudgetError('freshness_evidence_unavailable')
        # A refresh is never charged as a defect, so it is bounded by progress instead: fewer invalid
        # rows or more valid searches. One that made neither is a retrieval outage (retryable infra),
        # not a forever-repeated stop.
        valid = lambda rows: len({v for r in rows if isinstance(r, dict) and (v := run.own_search(c, r)) is not None})
        fixed = sum(e is not None for e in errors) < sum(e is not None for e in pending.get('targeted_errors') or ())
        added = valid(run.freshness_lines(c)) > valid(pending.get('before_rows') or ())
        if not defect and any(errors) and not fixed and not added:
            raise BudgetError('freshness_refresh_stalled')
    save()
    failures = 0
    while True:
        check(c)
        finish()
        pending = state['pending']
        if pending:
            def role_done(who):
                pending['roles'].append(who); save()
            run.freshness_topup(c, completed_roles=pending['roles'], role_completed=role_done)
            pending['phase'] = 'completed'; save()
            continue
        ok, info = run._g2(c)
        c.card['admission_freshness'] = info
        if ok or info.get('outcome') == 'public_match':
            c.freshness_refetch_urls = set()
            return ok, info
        if info.get('transport_pending') or info.get('all_transport_failed'):
            failures += 1
            backoff(c, failures)
            # Don't reuse a held access-failure snapshot for the next HTTP cycle.
            c.freshness_refetch_urls = {r['url'] for r in run.freshness_lines(c) if 'url' in r}
            continue
        if info.get('outcome') == 'review_unresolved':
            # The reviewer left a flagged hit unresolved. Ask it again in this attempt (a bounded
            # number of times) rather than failing the admit and paying a new worker to re-ask.
            # The hit still blocks until a review clears it: G2's rule is unchanged.
            asked = getattr(c, 'freshness_reask', 0)
            if asked >= REVIEW_REASKS or getattr(c, 'freshness_review_reason', None) == 'same_family_reviewer':
                raise BudgetError('freshness_review_unavailable')
            c.freshness_reask = asked + 1
            # Re-fetch the flagged pages that were not read live, so the reviewer is not handed the
            # same held receipts again (obtain() keeps a live page and refreshes only these).
            c.freshness_refetch_urls = {r['url'] for r in run.freshness_lines(c)
                                        if (r.get('hit') is True or r.get('ambiguous') is True) and 'url' in r}
            c.card['freshness_reasks'] = c.freshness_reask
            continue
        errors, defect = metadata()
        if state['completed_defects'] >= 2 and defect:
            raise BudgetError('freshness_evidence_unavailable')
        # Do not repeatedly buy alternatives when transport is the only problem.
        signature = digest(run.freshness_lines(c))
        if info.get('unfetched_searches') and not any(errors) and not defect and state.get('last_topup') == signature:
            failures += 1
            backoff(c, failures)
            c.freshness_refetch_urls = set(c.freshness_unfetched)
            continue
        state['pending'] = {'operation_id': str(uuid.uuid4()), 'before_rows': run.freshness_lines(c),
            'targeted_errors': errors, 'phase': 'pending', 'roles': [], 'charged': False}
        state['last_topup'] = signature
        save()
