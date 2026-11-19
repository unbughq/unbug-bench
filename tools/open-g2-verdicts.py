#!/usr/bin/env python3
"""Founder-only local G2 diagnosis. No models, network, workers or restores."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import sys
import types
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'factory'), str(ROOT/'bin')]
import unlock_sealed_audit as unlock
import run

OUT = Path('/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/'
           '00d02e9b-ca70-4919-b958-898ec30f1b3a/scratchpad/g2-open')
CASES = (
    ('case-20261024T043353Z-e15450', '2675a0cbaee17019e42d6412a29433b70bce9c0de9bae58d56b2f86fb17c3608'),
    ('case-20261024T085209Z-873d7f', 'd1f9174de33ca6fe824693b90f14300f77d38bb78db44e3cdea48d51c8eb1e90'),
)
FIELDS = ('resolved', 'same_bug', 'retrieved', 'app_version', 'version_scope',
          'retrieved_from', 'archive_checked', 'archive_available', 'archive_snapshot_url',
          'live_failure', 'why')


def load(path): return json.loads(path.read_text())


def describe(case, work, card):
    """Use the factory's actual verdict validator, including malformed clearances."""
    retained = (card.get('loop_freshness') or {}).get('verdict_path')
    if retained:
        if not re.fullmatch(r'g2-confirm-[0-9]+/verdict.json', retained):
            raise ValueError('invalid verdict path')
        verdict_path = work/retained
    else:
        reviews = sorted(work.glob('g2-confirm-*/verdict.json'),
                         key=lambda p: int(p.parent.name.removeprefix('g2-confirm-')))
        if not reviews: raise ValueError('missing verdict')
        verdict_path = reviews[-1]
    if not (verdict_path.parent/'review-completed.json').is_file():
        raise ValueError('review did not complete')
    snapshot = verdict_path.parent/'case'
    context = types.SimpleNamespace(case=snapshot, card={}, freshness_confirmed_hits=0)
    lines = run.freshness_lines(context)
    flagged = [r for r in lines if r.get('hit') is True or r.get('ambiguous') is True]
    answers = load(verdict_path).get('hits')
    if not isinstance(answers, list): raise ValueError('missing per-hit verdicts')
    # loop_freshness appends request-only URLs after all flagged rows. Preserve
    # repeated flagged URLs by position; never collapse distinct queries by URL.
    app = load(snapshot/'case.json').get('app') or {}
    semver = r'[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?'
    version = re.match(r'^v?(' + semver + r')(?=\s|$)', str(app.get('version', '')))
    tag = re.fullmatch(r'v?(' + semver + ')', str(app.get('commit', '')))
    pinned = (version or tag)[1] if version or tag else None
    rows = list(flagged)
    for answer in answers[len(flagged):]:
        url = answer.get('url') if isinstance(answer, dict) else None
        matches = [r for r in lines if r.get('url') == url]
        queries = list(dict.fromkeys(r['query'] for r in matches if r.get('query')))
        rows.append(dict(who='attacker', url=url,
            query='\n'.join(queries) or 'Attacker freshness_review request',
            app_version=pinned))
    if len(rows) != len(answers): raise ValueError('review row coverage mismatch')
    from freshness_retrieval import load as load_retrieval, digest
    try:
        receipts = load_retrieval(verdict_path.parent/'retrieval', rows)
        completed = load(verdict_path.parent/'review-completed.json')
        if (completed.get('binding', {}).get('confirmation_contract') not in (2, 3)   # 3: SOURCE_CODE_NOT_PUBLIC
                or completed.get('retrieval_sha256') != digest(receipts)):
            raise ValueError('unverified retrieval completion')
    except (OSError, ValueError, RuntimeError):
        receipts = None  # Legacy model assertions do not prove a page was fetched.
    # Preserve the exact app metadata, rather than guessing a version from a URL.
    paragraphs = [p for p in re.split(r'\n\s*\n', (snapshot/'statement.md').read_text())
                  if p.strip() and not all(line.lstrip().startswith('#') for line in p.splitlines())]
    if not paragraphs: raise ValueError('missing bug statement')
    summary = ' '.join(paragraphs[0].split())
    output = [f'## {case}', '', f'Pinned app: {json.dumps(app, ensure_ascii=True)}', '',
              f'Bug statement summary (opening paragraph): {summary}', '',
              f'Reviewer verdict: {verdict_path.relative_to(work)}', '']
    count = 0
    for index, (row, answer) in enumerate(zip(rows, answers), 1):
        context.freshness_confirmed_hits = 0
        context.freshness_retrieval = [receipts[index - 1]] if receipts else []
        blocked = run.checked_freshness_verdict(context, [row], [answer])
        if not blocked or context.freshness_confirmed_hits: continue
        count += 1
        value = {k:row.get(k) for k in ('url', 'who', 'query')}
        value['reviewer'] = {k:answer.get(k) for k in FIELDS} if isinstance(answer, dict) else answer
        output += [f'### Unresolved row {index}', '', '```json',
                   json.dumps(value, indent=2, ensure_ascii=True), '```', '']
    expected = (card.get('admission_freshness') or {}).get('unresolved_hits')
    if receipts and not retained and count != expected: raise ValueError('unresolved row count mismatch')
    if receipts is None:
        output += ['Runner retrieval proof unavailable; model claims alone remain unresolved.',
                   f'Historical unresolved count: {expected}', '']
    output += [f'Unresolved rows: {count}', '']
    return '\n'.join(output)


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    streams = []
    created = False
    identity = None
    try:
        age = shutil.which('age')
        if not age or not sys.stdin.isatty(): raise RuntimeError('interactive terminal and age required')
        if OUT.exists() or OUT.is_symlink(): raise ValueError('output already exists; preserve it before rerunning')
        # Verify both exact collected ciphertexts before asking for the identity.
        for case, digest in CASES:
            bundle = ROOT.parent/('unbug-bench-'+case.rsplit('-', 1)[1]+'-restore-14-20261029')
            card = load(bundle/'sealed'/(case+'.scorecard.json'))
            fd = os.open(bundle/'sealed'/(case+'.checkpoint.tar.gz.age'), os.O_RDONLY|os.O_NOFOLLOW)
            stream = os.fdopen(fd, 'rb'); streams.append((case, stream, card))
            if card.get('sha256') != digest or hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('collected checkpoint hash mismatch')
            stream.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            identity = getpass.getpass('Founder age identity (hidden; one entry for both cases): ').strip()
        if not re.fullmatch(r'AGE-SECRET-KEY-1[0-9A-Z]+', identity):
            raise ValueError('native age identity required')
        OUT.mkdir(mode=0o700); created = True
        sections = ['# Collected G2 unresolved verdicts', '']
        for case, stream, card in streams:
            destination = OUT/case; destination.mkdir(mode=0o700)
            # Existing streaming age helper: identity goes only to age stdin;
            # authenticated extraction omits keys, credentials and raw logs.
            unlock.decrypt_one(age, stream, identity, case, destination)
            sections.append(describe(case, destination, card))
        identity = None
        unlock.write_private(OUT/'summary.md', '\n'.join(sections).encode())
        print('Diagnosis written to '+str(OUT/'summary.md'))
    except BaseException as error:
        if created: shutil.rmtree(OUT)
        # Never echo exception data, decrypted material, or a traceback containing
        # the identity. All detailed evidence stays in the private output tree.
        print('Diagnosis failed ('+type(error).__name__+'); no partial output retained.', file=sys.stderr)
        return 1
    finally:
        identity = None
        for _, stream, _ in streams: stream.close()
    return 0


if __name__ == '__main__': sys.exit(main())
