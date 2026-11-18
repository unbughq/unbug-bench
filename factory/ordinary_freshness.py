"""Batch G2 refresh and transport policy. Scientific verdicts remain in run.py."""
import model_router
import time
import hashlib
import shutil
import uuid
import datetime

from admission import REFRESH, rerun_url, search_evidence_error, superseded
from budget import BudgetError
import freshness_retrieval as retrieval
from ordinary_retry import check, backoff, digest, read, transport
from registry import atomic_json
from run_validity import InvalidInfra


REVIEW_REASKS = 2   # extra reviewer asks per attempt after an unresolved G2 review
# G2 cycles in a row held by the same access failures with the same evidence and result. 18681d (15
# November 09:30-12:44) ran 39 such cycles on one flagged page answering 429 with no archive copy.
STALLED = 'g2-stalled.json'   # in run.SNAPSHOT_RETAINED, so the count survives a new worker
# A real bot wall with no archive copy belongs to the page: G2 stops for a person after this many cycles.
SOURCE_BLOCKED_CYCLES = 3
WALLS = ('http_202', 'http_401', 'http_403', 'http_451')   # 202: a WAF challenge (cae763)
# 429, 5xx and network errors can be our own outage or rate limit (0cc00438): G2 waits this long on one
# unchanged hold before it stops as our own retryable infra stall.
STALLED_SECONDS = 30 * 60


def stalled(run, c, info):
    """Track the held cycle's evidence and result; stop when the same hold has lasted SOURCE_BLOCKED_CYCLES
    cycles behind a wall with no archive copy, or STALLED_SECONDS otherwise. Anything new starts again."""
    receipts = getattr(c, 'freshness_retrieval', [])
    signature = digest({'rows': run.freshness_lines(c), 'info': info,
                        'flagged': retrieval.judgment_projection(receipts)})
    before = read(c.work / STALLED, {})
    if not isinstance(before, dict): raise BudgetError('ordinary_retry_state_invalid')
    if before.get('signature') != signature: before = {'cycles': 0, 'since': time.time()}
    elif type(before.get('cycles')) is not int or type(before.get('since')) not in (int, float):
        raise BudgetError('ordinary_retry_state_invalid')
    state = {'signature': signature, 'cycles': before['cycles'] + 1, 'since': before['since']}
    atomic_json(c.work / STALLED, state)
    held = [{'url': r['url'], 'failure': r['live_failure'], 'archive': r['archive_available']}
            for r in receipts if retrieval.access_failure(r)]
    walled = any(h['failure'] in WALLS and h['archive'] is False for h in held)
    minutes = (time.time() - state['since']) / 60
    if walled and state['cycles'] < SOURCE_BLOCKED_CYCLES or not walled and minutes < STALLED_SECONDS / 60: return
    c.card['freshness_stalled'] = {'cycles': state['cycles'], 'minutes': round(minutes), 'sources': held, 'note':
        f"G2 stopped: held {state['cycles']} cycles ({round(minutes)} min) with no new information by "
        + '; '.join(f"{h['url']} ({h['failure']}, archive {h['archive']})" for h in held)
        + ('. A page is behind a bot wall with no archive copy: someone must open it, or rule the claim does '
           'not need it.' if walled else '. Only rate limits, server or network errors: retried as our own infra stall.')}
    if not walled:   # each retry of our own stall gets its own STALLED_SECONDS
        atomic_json(c.work / STALLED, {**state, 'since': time.time()})
    raise BudgetError('freshness_source_blocked' if walled else 'freshness_refresh_stalled')


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
                if (saved[0]['retrieved_from'] == 'live' and not retrieval.missing_twin(saved[0]) or
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
        rows = [{**r, 'at': now, 'retrieved': True, 'note': r.get('note') or 'x', 'version_scope': r.get('version_scope') or 'x',
                 'url': rerun_url(r)} if e in REFRESH else r for r, e in zip(rows, errors)]
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
            # Nothing tells our outage from a dead link here (our retrieval never fetches an unflagged row the
            # searcher marked unretrieved), so every stall is one retryable infra reason.
            raise BudgetError('freshness_refresh_stalled')
    save()
    failures = 0
    while True:
        check(c)
        finish()
        pending = state['pending']
        if pending:
            (c.work / STALLED).unlink(missing_ok=True)   # the hold count is of held cycles in a row
            def role_done(who):
                pending['roles'].append(who); save()
            run.freshness_topup(c, completed_roles=pending['roles'], role_completed=role_done)
            pending['phase'] = 'completed'; save()
            continue
        ok, info = run._g2(c)
        c.card['admission_freshness'] = info
        # A flagged page held while other pages answer; an outage of ours keeps backoff and the deadline.
        held = info.get('transport_pending') and not info.get('all_transport_failed')
        if ok or info.get('outcome') == 'public_match' or not held:
            (c.work / STALLED).unlink(missing_ok=True)   # the hold count is of held cycles in a row
        if ok or info.get('outcome') == 'public_match':
            c.freshness_refetch_urls = set()
            (c.work / 'g2-source-blocked.json').unlink(missing_ok=True)   # the bot-wall count before 16 Nov
            return ok, info
        if info.get('transport_pending') or info.get('all_transport_failed'):
            if held: stalled(run, c, info)
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
        n = run.freshness_counts(c)
        state['pending'] = {'operation_id': str(uuid.uuid4()), 'before_rows': run.freshness_lines(c),
            'targeted_errors': errors, 'phase': 'pending', 'roles': [], 'charged': False,
            'short': [who for who, short in (('builder', n['builder_web'] < 3 or n['builder_github'] < 3),
                                             ('attacker', n['attacker'] < 2)) if short]}
        state['last_topup'] = signature
        save()
