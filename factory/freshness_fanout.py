"""Fan-out freshness search for the G2 top-up: plan -> concurrent search -> one reading -> deep dives.

Per role (writer, stress tester; each plans from the statement alone and never sees the other's
queries): one model call writes the query plan, the runner runs every query at once (Exa for the web,
the GitHub search API for GitHub), one model call scores every result, and only close or unsure
results get an agentic deep dive. The runner then writes the rows in the exact format G2 validates, so
G2's counts, expiry and flagged-hit review are unchanged. Anything the fan-out cannot settle is left
for the old agentic top-up, which still runs for a role that is short afterwards.
"""
import concurrent.futures
import datetime
import json
import os
import re
import shutil
import threading
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

from admission import REFRESH as REPAIRABLE, search_evidence_error, superseded   # REPAIRABLE: a re-run fixes it
from budget import BudgetError

EXA_URL = 'https://mcp.exa.ai/mcp'   # the endpoint opencode's websearch tool (OPENCODE_ENABLE_EXA) uses; keyless
UA = 'unbug-bench-freshness/1'
MAX_LEADS = 12                        # deep dives per role; further leads stay flagged for G2's reviewer
SNIPPET = 1000                        # body excerpt the scorer reads per result
THIN = 40                             # a web result with less body than this cannot be cleared unread
COPIED = ('statement.md', 'disclosure.md', 'provenance.json', 'promise.md', 'case.json')
norm = lambda q: ' '.join(q.casefold().split())


def excerpt(text):
    """The scorer's excerpt of a result body, and whether it was cut short (the scorer is told)."""
    text = re.sub(r'\s+', ' ', text).strip()
    return {'snippet': text[:SNIPPET], **({'truncated': True} if len(text) > SNIPPET else {})}


def _results(items):
    return [r for r in items if isinstance(r.get('url'), str) and r['url'].startswith(('http://', 'https://'))]


def web_search(query, limit=8):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'web_search_exa', 'arguments': {'query': query, 'numResults': limit}}}).encode()
    request = Request(EXA_URL, body, {'Content-Type': 'application/json',
                                      'Accept': 'application/json, text/event-stream', 'User-Agent': UA})
    with urlopen(request, timeout=30) as response: text = response.read().decode('utf-8', 'replace')
    payload = None
    for line in text.splitlines():
        line = line.strip()
        line = line[5:].strip() if line.startswith('data:') else line
        if line.startswith('{'):
            try: payload = json.loads(line); break
            except ValueError: continue
    if payload is None or 'error' in payload: raise OSError('exa search failed')
    content = ''.join(p.get('text', '') for p in payload['result']['content'] if isinstance(p, dict))
    out = []
    for chunk in re.split(r'(?m)^(?=Title: )', content):
        url = re.search(r'(?m)^URL: (\S+)', chunk)
        if url:
            title = re.match(r'Title: (.*)', chunk)
            body = re.sub(r'(?m)^(Title|URL|Published|Published Date|Author|Id|Image|Favicon): .*$', '', chunk)
            out.append({'url': url[1], 'title': title[1].strip() if title else '', **excerpt(body)})
    return _results(out)[:limit]


def github_search(query, limit=8):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': UA}
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')   # used only if the worker already has one
    if token: headers['Authorization'] = 'Bearer ' + token
    def get(kind, n):
        with urlopen(Request(f'https://api.github.com/search/{kind}?per_page={n}&q=' + quote(query), headers=headers),
                     timeout=30) as response:
            return json.loads(response.read())['items']
    out = [{'url': i.get('html_url'), 'title': str(i.get('title') or ''), **excerpt(str(i.get('body') or ''))}
           for i in get('issues', limit)]
    try:   # fix commits are public evidence too; a failed commit search leaves the issue results
        for i in get('commits', max(1, limit // 2)):
            message = str((i.get('commit') or {}).get('message') or '')
            out.append({'url': i.get('html_url'), 'title': message.split('\n')[0][:200], **excerpt(message)})
    except Exception: pass
    return _results(out)[:limit + limit // 2]


SEARCH = {'web': web_search, 'github': github_search}


def pinned_version(c):
    semver = r'[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?'
    try: app = json.loads((c.case / 'case.json').read_text()).get('app') or {}
    except (OSError, ValueError, AttributeError): return None
    m = re.match(r'^v?(' + semver + r')(?=\s|$)', str(app.get('version', ''))) or \
        re.fullmatch(r'v?(' + semver + ')', str(app.get('commit', '')))
    return m[1] if m else None


def _read(path):
    """The JSON a model call left in the case directory, removed afterwards; None if absent or invalid."""
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return None
    finally: path.unlink(missing_ok=True)


def _ask(c, who, models, opencode, scratch, name, text, deadline):
    timeout = deadline - time.monotonic()
    if timeout <= 0: raise BudgetError('timeout')
    opencode(c, models, text, scratch, f'{who}-freshness-{name}', timeout=timeout, deadline=deadline)


def _role(run, c, who, opencode, deadline, lock, version, now):
    """One role in a private scratch directory (copies of the bug's files only): its scratch JSON never
    touches the case (so case_hash and gate fingerprints stay put) and the other role's plan, scores and
    rows are not in reach of its model calls."""
    scratch = c.work / 'freshness' / who
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    try:
        for name in COPIED:
            if (c.case / name).is_file(): shutil.copy(c.case / name, scratch / name)
        _role_in(run, c, who, opencode, deadline, lock, version, now, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _role_in(run, c, who, opencode, deadline, lock, version, now, scratch):
    ctx = '```json\n' + json.dumps({'case_dir': str(scratch), 'bug_source': c.args.source}, indent=2) + '\n```\n'
    models = c.models['builder' if who == 'builder' else 'attacker']
    case, kinds = c.case, ('web', 'github')
    rows, counts = run.freshness_lines(c), run.freshness_counts(c)
    stamp = lambda: now().isoformat()
    # 1. Rows a re-run search can repair (expired or failed retrieval) keep their identity and are amended.
    items, have = [], set()
    for row, old in zip(rows, superseded(rows)):
        if not isinstance(row, dict) or old: continue
        if row.get('who') == who and row.get('kind') in kinds and isinstance(row.get('query'), str) and row['query'].strip():
            reason = search_evidence_error(row)
            fixed = {**row, 'at': stamp(), 'retrieved': True, 'note': 'x', 'app_version': version or '',
                     'version_scope': 'x', 'hit': row['hit'] if type(row.get('hit')) is bool else False}
            if reason is None: have.add((row['kind'], norm(row['query'])))
            # A hit row is never rewritten by a re-run search (its URL and verdict are the evidence).
            elif (reason in REPAIRABLE and search_evidence_error(fixed) is None and row.get('_search_id')
                  and row.get('hit') is not True):
                items.append({'kind': row['kind'], 'query': row['query'], 'amend': row['_search_id'], 'url': row['url']})
                have.add((row['kind'], norm(row['query'])))
    # 2. One planning call for the queries still missing against G2's minimums (plus one spare each).
    short = ({'web': max(0, 3 - counts['builder_web']), 'github': max(0, 3 - counts['builder_github'])} if who == 'builder'
             else {k: max(0, 2 - counts['attacker']) for k in kinds})
    amend = {k: sum(i['kind'] == k for i in items) for k in kinds}
    want = {k: (max(0, short[k] - amend[k]) + 1 if short[k] > amend[k] else 0) for k in kinds}
    if who == 'attacker' and sum(amend.values()) >= short['web']: want = dict.fromkeys(kinds, 0)
    if any(want.values()):
        plan = f'{who}-freshness-plan.json'
        (scratch / plan).unlink(missing_ok=True)
        _ask(c, who, models, opencode, scratch, 'plan',
             f"Freshness search PLAN only; do not search, browse or run anything, and change nothing except writing `{plan}` in the current directory. "
             f"Read `statement.md` and any `disclosure.md`, `provenance.json`, `promise.md` and `case.json` in the current directory to learn the bug and "
             f"pinned app version{' ' + version if version else ''}. Do not read `freshness.jsonl` or any other role's files; plan from the "
             f"bug alone. Write `{plan}` as JSON {{\"web\": [\"query\", ...], \"github\": [\"query\", ...]}} with exactly {want['web']} "
             f"distinct web queries and {want['github']} distinct GitHub issue-search queries that would find a public report, fix or "
             f"workaround of this bug in this app. Vary the angle: symptom wording, API/flow names, error text, fix commits.\n\n"
             f"## This run\n\n" + ctx, deadline)
        planned = _read(scratch / plan)
        for kind in kinds:
            queries = planned.get(kind) if isinstance(planned, dict) else None
            for q in (queries if isinstance(queries, list) else [])[:want[kind] + 4]:
                if isinstance(q, str) and 3 <= len(q.strip()) <= 300 and (kind, norm(q)) not in have:
                    have.add((kind, norm(q))); items.append({'kind': kind, 'query': q.strip(), 'amend': None})
    if not items: return
    # 3. The runner runs every query at once; a failed query is simply not logged.
    def search(item):
        try: return SEARCH[item['kind']](item['query'])
        except Exception: return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(items))) as pool:
        for item, found in zip(items, pool.map(search, items)): item['results'] = found
    items = [i for i in items if i['results'] is not None and (i['results'] or i['kind'] == 'github' or i['amend'])]
    if not items: return
    # 4. One call reads and scores every result.
    listing = [{'id': f'{n}.{m}', 'url': r['url'], 'title': r['title'], 'snippet': r['snippet'],
                **({'truncated': True} if r.get('truncated') else {})}
               for n, i in enumerate(items) for m, r in enumerate(i['results'])]
    verdict = {}
    if listing:
        out = f'{who}-freshness-scores.json'
        for step in ('score', 'score-retry'):   # a scoring that skips results is asked once more, never defaulted
            (scratch / out).unlink(missing_ok=True)
            _ask(c, who, models, opencode, scratch, step,
                 f"Freshness scoring only; do not search or browse, and change nothing except writing `{out}` in the current directory. Read `statement.md` "
                 f"(and `disclosure.md`, `promise.md`, `case.json` if present) in the current directory to learn the bug and pinned app version"
                 f"{' ' + version if version else ''}. Do not read `freshness.jsonl`. For every search result below judge how close it is to "
                 f"THIS bug in THIS app: \"miss\" (positively unrelated, other app, or only the generic pattern; never \"miss\" a result whose excerpt is too short or vague to tell; an excerpt marked \"truncated\" was cut short, so \"miss\" it only if the part shown already rules it out), \"close\" (discusses this bug, its fix or "
                 f"a workaround) or \"unsure\" (could be this bug; needs reading). Write JSON {{\"results\": [{{\"id\": \"...\", "
                 f"\"verdict\": \"miss\" | \"close\" | \"unsure\", \"reason\": \"one sentence on why, including version applicability\"}}]}} "
                 f"with one entry per id.\n\n## Results\n\n```json\n{json.dumps(listing, indent=1)}\n```\n\n## This run\n\n" + ctx,
                 deadline)
            scored = _read(scratch / out)
            verdict = {}
            for e in (scored.get('results') if isinstance(scored, dict) else None) or []:
                if isinstance(e, dict) and isinstance(e.get('id'), str):
                    verdict[e['id']] = (e.get('verdict') if e.get('verdict') in ('miss', 'close', 'unsure') else 'unsure',
                                        str(e.get('reason') or '').strip())
            if all(r['id'] in verdict for r in listing): break
        else:
            return   # still incomplete: log nothing; the role stays short and the agentic top-up fills it
        for r in listing:   # a result with next to no text, or cut short, cannot be cleared unread
            if (len(r['snippet']) < THIN or r.get('truncated')) and verdict[r['id']][0] == 'miss':
                verdict[r['id']] = ('unsure', 'excerpt too short to clear' if len(r['snippet']) < THIN else 'excerpt cut short; read it')
    # 5. Deep dive (today's agentic browsing) only on close/unsure leads; an unanswered lead stays flagged.
    leads = [r for r in listing if verdict.get(r['id'], ('unsure', ''))[0] != 'miss']
    leads.sort(key=lambda r: verdict.get(r['id'], ('unsure',))[0] != 'close')   # the browsing cap reads close leads first
    final = {r['id']: ('close' if verdict.get(r['id'], ('unsure',))[0] == 'close' else 'unsure',
                       verdict.get(r['id'], ('', ''))[1]) for r in leads}
    if leads[:MAX_LEADS]:
        out = f'{who}-freshness-dive.json'
        (scratch / out).unlink(missing_ok=True)
        _ask(c, who, models, opencode, scratch, 'dive',
             f"Freshness deep dive; browse ONLY these leads, nothing else, and change nothing except writing `{out}` in the current directory. Read "
             f"`statement.md` (and `case.json`) in the current directory for the bug and pinned app version{' ' + version if version else ''}. Open each "
             f"URL, read it and decide whether it discusses this bug, its fix or a workaround in this app at a version that still "
             f"applies. Write JSON {{\"leads\": [{{\"id\": \"...\", \"verdict\": \"hit\" | \"miss\" | \"unsure\", \"note\": \"what the page "
             f"says\", \"version_scope\": \"why it applies or not\"}}]}}. \"unsure\" if you cannot read it or cannot tell; never invent evidence."
             f"\n\n## Leads\n\n```json\n{json.dumps(leads[:MAX_LEADS], indent=1)}\n```\n\n## This run\n\n" + ctx,
             deadline)
        dived = _read(scratch / out)
        for e in (dived.get('leads') if isinstance(dived, dict) else None) or []:
            if isinstance(e, dict) and e.get('id') in final and e.get('verdict') in ('hit', 'miss', 'unsure'):
                note = ' '.join(str(e.get('note') or e.get('version_scope') or '').split())
                final[e['id']] = ({'hit': 'close', 'miss': 'miss', 'unsure': 'unsure'}[e['verdict']],
                                  note or final[e['id']][1])
    # 6. The runner writes the rows in G2's format; one lock, one rewrite.
    new, amended = [], {}
    for n, item in enumerate(items):
        found = item['results']
        base = {'who': who, 'kind': item['kind'], 'query': item['query'], 'at': stamp(), 'retrieved': True,
                'app_version': version}
        flagged = [(r, final[f'{n}.{m}']) for m, r in enumerate(found) if f'{n}.{m}' in final and final[f'{n}.{m}'][0] != 'miss']
        for r, (v, why) in flagged:   # every unresolved lead is logged for G2's review; only browsing is capped
            new.append({**base, 'url': r['url'], 'hit': v == 'close', **({} if v == 'close' else {'ambiguous': True}),
                        'note': (why or f"Fan-out lead: {r['title']}")[:600],
                        'version_scope': why[:300] or 'Needs independent same_bug and version review'})
        top = found[0] if found else None
        reason = verdict.get(f'{n}.0', ('', ''))[1] if found else ''
        note = (f"Fan-out search returned {len(found)} results, " + (f"{len(flagged)} flagged (logged as their own rows). "
                if flagged else "none flagged. ") + (f"Top: {top['title']}. {reason}" if top else 'No results.'))[:600]
        scope = reason or 'No result describes this bug in the pinned app version'
        url = top['url'] if top else 'https://github.com/search?type=issues&q=' + quote(item['query'])
        if item['amend']:
            # The row keeps its URL (history), so it is amended only if this search retrieved that URL
            # again; otherwise the re-run is logged as a new row of the same query, which supersedes it.
            if any(r['url'] == item['url'] for r in found):
                amended[item['amend']] = {'at': stamp(), 'retrieved': True, 'note': note, 'app_version': version,
                                          'version_scope': scope}
                continue
        if not flagged and (found or item['kind'] == 'github'):   # a web search with no results logs nothing
            new.append({**base, 'url': url, 'hit': False, 'note': note, 'version_scope': scope})
    with lock:
        current = run.freshness_lines(c)
        for row in current:
            patch = amended.get(row.get('_search_id'))
            if patch:
                row.update(patch)
                if type(row.get('hit')) is not bool: row['hit'] = False
        (case / 'freshness.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in [*current, *new]))


def fan_out(run, c, roles, opencode, deadline):
    """Run the given roles at once. Returns when all are done; a budget/timeout stop is re-raised."""
    version = pinned_version(c)
    if version is None or not roles: return
    lock, now = threading.Lock(), lambda: datetime.datetime.now(datetime.timezone.utc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(roles)) as pool:
        futures = [pool.submit(_role, run, c, who, opencode, deadline, lock, version, now) for who in roles]
        errors = [f.exception() for f in futures]
    for error in errors:
        if isinstance(error, BudgetError): raise error
    # Anything else (a model call or parsing gone wrong) leaves the role short; the agentic top-up fills it.
