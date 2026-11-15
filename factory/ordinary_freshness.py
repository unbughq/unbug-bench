"""Batch G2 refresh and transport policy. Scientific verdicts remain in run.py."""
import model_router
import time
import hashlib
import shutil
import uuid
import datetime

from admission import REFRESH, search_evidence_error, superseded
from budget import BudgetError
import freshness_retrieval as retrieval
from ordinary_retry import check, backoff, digest, read, transport
from registry import atomic_json
from run_validity import InvalidInfra


REVIEW_REASKS = 2   # extra reviewer asks per attempt after an unresolved G2 review
# G2 retry cycles in a row that bring no new information (same rows, same verdict, same held or
# unfetched URLs and failures) before G2 stops. 18681d (15 November 09:30-12:44) ran 39 such cycles on one
# flagged page answering 429 with no archive copy, until its rows expired.
STALLED_CYCLES = 3
STALLED = 'g2-stalled.json'   # in run.SNAPSHOT_RETAINED, so the count survives a new worker
# Failures that belong to the page: a bot wall, or a page that is gone. 429, 5xx, network errors and
# unfetched rows can be our own outage or rate limit (0cc00438), so a stall of only those is our stop.
PAGE_FAILURES = ('http_401', 'http_403', 'http_451', 'http_404', 'http_410', 'dns_failure')


def stalled(run, c, info):
    """Count retry cycles in a row whose evidence and result match the cycle before; stop once the
    count reaches the bound. A cycle with anything new starts the count again."""
    receipts = getattr(c, 'freshness_retrieval', [])
    unfetched = sorted(getattr(c, 'freshness_unfetched', ()))
    signature = digest({'rows': run.freshness_lines(c), 'info': info, 'unfetched': unfetched,
                        'flagged': retrieval.judgment_projection(receipts)})
    before = read(c.work / STALLED, {})
    cycles = before.get('cycles', 0) + 1 if before.get('signature') == signature else 1
    atomic_json(c.work / STALLED, {'signature': signature, 'cycles': cycles})
    if cycles < STALLED_CYCLES: return
    sources = [{'url': r['url'], 'failure': r['live_failure']} for r in receipts if r['retrieved_from'] != 'live']
    sources += [{'url': url, 'failure': 'not fetched'} for url in unfetched if url not in {s['url'] for s in sources}]
    page = any(s['failure'] in PAGE_FAILURES for s in sources)
    c.card['freshness_stalled'] = {'cycles': cycles, 'sources': sources, 'note':
        f"G2 stopped: {cycles} cycles in a row brought no new information ({info.get('outcome')}); "
        + '; '.join(f"{s['url']} ({s['failure']})" for s in sources)
        + ('. Someone must open these pages, or rule the claim does not need them.' if page else
           '. Only rate limits, server or network errors: retried as our own infra stop.')}
    raise BudgetError('freshness_source_blocked' if page else 'freshness_refresh_stalled')


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
    c.card.pop('freshness_stalled', None)   # set only by the stop that raises with it
    c.card.pop('freshness_source_blocked', None)   # its name in cards saved before 16 November
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
        rows = [r for r, old in zip(rows, superseded(rows)) if not old]   # history a re-run replaced
        errors = [search_evidence_error(r) for r in rows]
        # A row that is only old or unretrieved needs its search re-run, not a repair: judge the
        # rest of it as if refreshed (an unretrieved result has no note or scope yet; the re-run writes
        # them, as freshness_fanout assumes). G2 itself still rejects it until the re-run really happens.
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rows = [{**r, 'at': now, 'retrieved': True, 'note': r.get('note') or 'x', 'version_scope': r.get('version_scope') or 'x'}
                if e in REFRESH else r for r, e in zip(rows, errors)]
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
        # rows, or more valid searches by a role that was short of G2's minimum when the refresh opened
        # (every top-up may add spare searches, so those alone are no progress on rows needing a re-run).
        valid = lambda rows, who: len({v for r in rows if isinstance(r, dict) and r.get('url') not in getattr(c, 'freshness_unfetched', set())
                                       and (v := run.own_search(c, r)) is not None and v[0] == who})
        fixed = sum(e is not None for e in errors) < sum(e is not None for e in pending.get('targeted_errors') or ())
        short = pending.get('short') if isinstance(pending.get('short'), list) else ()
        added = any(valid(run.freshness_lines(c), who) > valid(pending.get('before_rows') or (), who) for who in short)
        if not defect and any(errors) and not fixed and not added:
            # Nothing tells our outage from a dead link here (our retrieval never fetches a row the
            # searcher marked unretrieved), so every stall is one retryable infra reason.
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
            (c.work / STALLED).unlink(missing_ok=True)
            return ok, info
        if info.get('transport_pending') or info.get('all_transport_failed'):
            stalled(run, c, info)
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
            stalled(run, c, info)
            failures += 1
            backoff(c, failures)
            c.freshness_refetch_urls = set(c.freshness_unfetched)
            continue
        n = run.freshness_counts(c)
        state['pending'] = {'operation_id': str(uuid.uuid4()), 'before_rows': run.freshness_lines(c),
            'targeted_errors': errors, 'phase': 'pending', 'roles': [], 'charged': False,
            'short': [who for who, short in (('builder', n['builder_web'] < 3 or n['builder_github'] < 3),
                                             ('attacker', n['attacker'] < 2)) if short]}
        state['last_topup'] = signature
        save()
