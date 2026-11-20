#!/usr/bin/env python3
"""Pre-release check of run.G2_SOURCE_RULINGS against held cases' real snapshots. Read-only, in memory.

Run on the control VM from the candidate source tree (the one about to be installed), in the campaign root:
  cd ~/durable-first-case-20261106
  BOAT_NO_UPDATE=1 $V -B source-<candidate>/tools/check-g2-rulings.py case-import-cae763-h5-1 ...
For each case it opens the latest CASE_SNAPSHOT and runs the candidate's own g2_source_ruling on every flagged row
a ruling names for that case's statement. Prints OK (the ruling applies), MISMATCH (it would not: wrong URL, the
page was read, or the reviewer confirmed a match) or NO RULING, plus G2's last recorded search counts. Writes
nothing; the database session is read-only. Releasing to a held batch resumes it, so run this first.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'factory'), str(ROOT / 'bin')]
import run


class Statement:
    """Stands in, in memory, for c.case and c.case / 'statement.md'."""
    def __init__(self, data): self.data = data
    def __truediv__(self, name): return self
    def is_file(self): return True
    def read_bytes(self): return self.data


def check(statement, rows, receipts, answers):
    """[(ruling, 'OK' | 'MISMATCH')] for each G2_SOURCE_RULINGS entry keyed to this statement. rows: the case's
    freshness.jsonl rows; receipts and answers: the current runner receipt and reviewer answer per URL."""
    sha = hashlib.sha256(statement).hexdigest()
    flagged = [r for r in rows if r.get('hit') is True or r.get('ambiguous') is True]
    out = []
    for ruling in [r for r in run.G2_SOURCE_RULINGS if r.get('statement_sha256') == sha]:
        row = next((r for r in flagged if r.get('url') == ruling.get('url')), None)
        receipt = receipts.get(ruling.get('url'))
        got = (run.g2_source_ruling(SimpleNamespace(case=Statement(statement)), row, answers.get(ruling['url']), receipt)
               if row is not None and receipt is not None else None)
        out.append((ruling, 'OK' if got is ruling else 'MISMATCH'))
    return out


def snapshot_files(case):
    """The latest CASE_SNAPSHOT of a case workflow, opened in memory: (digest, {name: bytes reader})."""
    import base64, io, os, pickle, tarfile
    os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on'
    import psycopg
    from durable.artifacts import AgeSealer, SealedStore
    from durable.contract import ArtifactKind, Ref
    from durable.keys import AgeKeyService
    from durable.runtime import load_config, objects_for
    config = load_config('config.json')
    with psycopg.connect(config['database_url']) as db:
        outs = [pickle.loads(base64.b64decode(o)) for (o,) in db.execute(
            'select output from dbos.operation_outputs where workflow_uuid=%s and function_name=%s order by function_id',
            (case, 'DBOS.getResult'))]
    result = [o['result'] for o in outs if isinstance(o, dict) and (o.get('result') or {}).get('snapshot')][-1]
    digest = result['snapshot']['digest'] if isinstance(result['snapshot'], dict) else result['snapshot'].digest
    keys = AgeKeyService(config['database_url'], restore_recipient=config['restore_recipient'],
                         founder_recipient=config['founder_recipient'], restore_identity=config['restore_identity'])
    try:
        key = keys._unwrap(case, keys.wrapped_key(case))
        ref = Ref(digest, ArtifactKind.CASE_SNAPSHOT)
        plain = AgeSealer().open(key, ref, SealedStore(objects_for(config)).get_sealed(case, ref))
    finally:
        keys.close()
    tar = tarfile.open(fileobj=io.BytesIO(plain))
    return digest, {n: (lambda n=n: tar.extractfile(n).read()) for n in tar.getnames() if tar.getmember(n).isfile()}


def main(cases):
    failed = False
    for case in cases:
        digest, files = snapshot_files(case)
        statement = files['case/statement.md']()
        rows = [json.loads(line) for line in files['case/freshness.jsonl']().decode().splitlines() if line.strip()]
        flagged = sum(r.get('hit') is True or r.get('ambiguous') is True for r in rows)
        receipts, answers = {}, {}
        for name, read in files.items():
            if name.startswith('g2-url-retrieval/') and name.endswith('/receipts.json') and '-superseded-' not in name:
                receipts.update((x['url'], x) for x in json.loads(read()))
            elif name.startswith('ordinary-retries/') and re.search(r'/answer-[0-9]+\.json$', name):
                value = json.loads(read())
                if isinstance(value, dict) and isinstance(value.get('hits'), list) and len(value['hits']) == flagged:
                    answers = {h.get('url'): h for h in value['hits'] if isinstance(h, dict)}
        g2 = json.loads(files['scorecard.json']()).get('admission_freshness') or {}
        results = check(statement, rows, receipts, answers)
        failed = failed or any(v != 'OK' for _, v in results)
        print(case, 'snapshot', digest[:12], 'statement', hashlib.sha256(statement).hexdigest()[:12],
              'G2 counted', g2.get('counted'), 'unfetched', g2.get('unfetched_searches'))
        for ruling, verdict in results or [(None, 'NO RULING')]:
            print('  ', verdict, *((ruling['kind'], ruling['url']) if ruling else ()))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
