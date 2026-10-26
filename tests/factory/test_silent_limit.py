#!/usr/bin/env python3
"""A silent OpenCode hang whose log says 'usage limit exceeded' stops as provider_limit, not a 45-minute stall."""

# Keep direct execution and unittest discovery independent of the working directory.
import sys
from pathlib import Path as _TestPath
_TEST_ROOT = _TestPath(__file__).resolve().parents[2]
sys.path[:0] = [str(_TEST_ROOT / "factory"), str(_TEST_ROOT / "bin"), str(_TEST_ROOT / "tests/bench")]
import json, os, pathlib, sys, tempfile, time
sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2] / "factory")))
from budget import run_budgeted, BudgetError

with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); log = d / 'opencode/log'; log.mkdir(parents=True)
    stamp = lambda: time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    (log / 'old.log').write_text(f'timestamp=2020-01-01T00:00:00.000Z level=ERROR error="usage limit exceeded"\n')
    def run(write):
        cmd = ['sh', '-c', (f'sleep 1; echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%S.000Z) level=ERROR usage limit exceeded" >> {log}/new.log; ' if write else '') + 'sleep 30']
        t = time.monotonic()
        try: run_budgeted(cmd, d, {**os.environ, 'XDG_DATA_HOME': str(d)}, d / 't', d / f'ledger{write}.json', 60,
                          progress_timeout=4, configured_model='opencode-go/x'); return 'none', 0
        except BudgetError as e: return str(e), time.monotonic() - t
    stop, took = run(True); assert stop == 'provider_limit:opencode-go/x' and took < 10, (stop, took)
    stop, _ = run(False); assert stop != 'provider_limit:opencode-go/x', stop  # an old log line is not news
print('PASS silent Go usage limit stops as provider_limit within a minute; old log lines ignored')

# An isolated tester's log dir is private to its own Unix user: the check must skip it, never crash (2026-10-20).
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); (d / 'opencode/log').mkdir(parents=True); os.chmod(d / 'opencode', 0)
    try:
        run_budgeted(['sh', '-c', 'sleep 30'], d, {**os.environ, 'XDG_DATA_HOME': str(d)}, d / 't', d / 'l.json', 60,
                     progress_timeout=4, configured_model='opencode-go/x'); raise AssertionError('expected a stall')
    except BudgetError as e: assert str(e) == 'stalled', e
    finally: os.chmod(d / 'opencode', 0o700)
print('PASS unreadable log dir is skipped (stall still detected)')

# Resume handshake (2026-10-20): clears a previous run's stop once, so a resumed run's first calls may be parallel.
from budget import resume_ledger
with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d) / 'l.json'; p.write_text(json.dumps({'cost': 0.0, 'calls': 0, 'events': [], 'terminal_stop': 'usage_monitor:X', 'active': [1]}))
    resume_ledger(p); l = json.loads(p.read_text())
    assert l['terminal_stop'] is None and 'active' not in l and l['previous_stops'] == ['usage_monitor:X'], l
print('PASS resume handshake clears the stop once and records it')
