#!/usr/bin/env python3
"""bin/fake-pass-check static rules follow CONTESTANT.md (2026-10-19): hardening a SECURITY DEFINER function with a pinned
search_path and GRANT EXECUTE on it are review notes; runtime session changes, table grants and ownership stay forbidden."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import importlib.machinery, importlib.util, pathlib, re, sys
here = (_BENCH_ROOT / "bin"); sys.path.insert(0, str(here))
loader = importlib.machinery.SourceFileLoader('fpc', str(here / 'fake-pass-check'))
m = importlib.util.module_from_spec(importlib.util.spec_from_loader('fpc', loader)); loader.exec_module(m)
def severity(sql):
    for patterns, sev in ((m.FORBIDDEN_SQL, 'forbidden'), (m.REVIEW_SQL, 'review')):
        if any(re.search(p, sql, re.I) for p, _ in patterns): return sev
    return 'clean'
for sql, want in (("CREATE FUNCTION f() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$ BEGIN RETURN NEW; END $$;", 'review'),
                  ("GRANT EXECUTE ON FUNCTION f() TO PUBLIC;", 'review'), ("SET search_path = public;", 'review'),
                  ("GRANT SELECT ON product TO public;", 'forbidden'),
                  ("REVOKE ALL ON FUNCTION guard_check() FROM PUBLIC;", 'review'), ("GRANT USAGE ON SEQUENCE guard_seq TO PUBLIC;", 'review'),
                  ("REVOKE SELECT ON product FROM PUBLIC;", 'forbidden'), ("GRANT ALL ON SCHEMA public TO PUBLIC;", 'forbidden'), ("SELECT set_config('search_path', 'x', false);", 'forbidden'),
                  ("ALTER TABLE x OWNER TO y;", 'forbidden'), ("SELECT pg_sleep(1);", 'forbidden'), ("CREATE ROLE r;", 'forbidden')):
    assert severity(sql) == want, (sql, severity(sql))
def patch_severity(line):
    for patterns, sev in ((m.FORBIDDEN_PATCH, 'forbidden'), (m.REVIEW_PATCH, 'review')):
        if any(re.search(p, line, re.I | re.M) for p, _ in patterns): return sev
    return 'clean'
for line, want in (("+  await db.raw('UPDATE inventory_level SET reserved_quantity = reserved_quantity + ? WHERE stocked_quantity - reserved_quantity >= ?')", 'review'),
                   ("+  await new Promise(r => setTimeout(r, 20))", 'review'), ("+  db.raw('TRUNCATE reservation_item')", 'forbidden'),
                   ("+  if (email === 'a@bench.test') return", 'forbidden')):
    assert patch_severity(line) == want, (line, patch_severity(line))
print('PASS fake-pass rules follow the contestant contract')
