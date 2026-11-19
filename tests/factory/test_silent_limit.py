#!/usr/bin/env python3
"""A silent OpenCode hang whose log reports a usage limit (Go: 'usage limit exceeded'; free tier: 'Free usage limit
reached') on an ERROR line stops as provider_limit, not a 45-minute stall."""

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
                          containment=False, progress_timeout=4, configured_model='opencode-go/x'); return 'none', 0
        except BudgetError as e: return str(e), time.monotonic() - t
    stop, took = run(True); assert stop == 'provider_limit:opencode-go/x' and took < 10, (stop, took)
    stop, _ = run(False); assert stop != 'provider_limit:opencode-go/x', stop  # an old log line is not news
print('PASS silent Go usage limit stops as provider_limit within a minute; old log lines ignored')

# The free tier says it differently (1bb2ad writer:2/1 and 2/2 sat 45 minutes each, then counted as stalls, 2026-11-15).
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); log = d / 'opencode/log'; log.mkdir(parents=True)
    line = ('level=ERROR run=d1ffa54c message="stream error" providerID=opencode modelID=minimax-m3.1-flash-free '
            'error.error="AI_APICallError: Free usage limit reached. Free models work in OpenCode (https://opencode.ai); '
            'subscribe to OpenCode Go to keep going: https://opencode.ai/go"')
    cmd = ['sh', '-c', f"sleep 1; echo \"timestamp=$(date -u +%Y-%m-%dT%H:%M:%S.000Z) {line.replace(chr(34), chr(92) + chr(34))}\" >> {log}/opencode.log; sleep 30"]
    t = time.monotonic()
    try: run_budgeted(cmd, d, {**os.environ, 'XDG_DATA_HOME': str(d)}, d / 't', d / 'l.json', 60,
                      containment=False, progress_timeout=4, configured_model='opencode/minimax-m3.1-flash-free'); stop = 'none'
    except BudgetError as e: stop, err = str(e), e
    assert stop == 'provider_limit:opencode/minimax-m3.1-flash-free' and time.monotonic() - t < 10, stop
    assert err.provider_failure['reason'] == 'quota', err.provider_failure
print('PASS silent free usage limit stops as a provider quota, not a stall')

# Case text in an INFO line (a writer grepping "usage limit" on a promotion case) is not a provider limit.
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); log = d / 'opencode/log'; log.mkdir(parents=True)
    cmd = ['sh', '-c', f'sleep 1; echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%S.000Z) level=INFO message=evaluate command=\\"grep -rn usage limit src\\"" >> {log}/opencode.log; sleep 30']
    try: run_budgeted(cmd, d, {**os.environ, 'XDG_DATA_HOME': str(d)}, d / 't', d / 'l.json', 60,
                      containment=False, progress_timeout=4, configured_model='opencode-go/x'); stop = 'none'
    except BudgetError as e: stop = str(e)
    assert stop == 'stalled', stop
print('PASS an INFO line mentioning usage limit is not a provider limit')

# An isolated tester's log dir is private to its own Unix user: the check must skip it, never crash (2026-10-20).
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); (d / 'opencode/log').mkdir(parents=True); os.chmod(d / 'opencode', 0)
    try:
        run_budgeted(['sh', '-c', 'sleep 30'], d, {**os.environ, 'XDG_DATA_HOME': str(d)}, d / 't', d / 'l.json', 60,
                     containment=False, progress_timeout=4, configured_model='opencode-go/x'); raise AssertionError('expected a stall')
    except BudgetError as e: assert str(e) == 'stalled', e
    finally: os.chmod(d / 'opencode', 0o700)
print('PASS unreadable log dir is skipped (stall still detected)')

# A real call's progress_timeout is 900 s; the log is read after 5 s of silence, not min(60, 450) (f46dac G10 owner,
# 2026-11-18: two dead Go keys at 60 s each used up the owner's 120 s before the OpenRouter twin ran).
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); log = d / 'opencode/log'; log.mkdir(parents=True)
    cmd = ['sh', '-c', f'echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%S.000Z) level=ERROR usage limit exceeded" >> {log}/opencode.log; sleep 30']
    t = time.monotonic()
    try: run_budgeted(cmd, d, {**os.environ, 'XDG_DATA_HOME': str(d)}, d / 't', d / 'l.json', 60,
                      containment=False, progress_timeout=900, configured_model='opencode-go/x'); stop = 'none'
    except BudgetError as e: stop = str(e)
    took = time.monotonic() - t
    assert stop == 'provider_limit:opencode-go/x' and took < 10, (stop, took)
print('PASS a silent Go quota stops within seconds on a 900 s progress timeout')

# A call that logged a limit, then recovered and printed, then went quiet for 8 s is healthy: only lines at or after
# the last output count, so the 5 s check does not kill it.
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); log = d / 'opencode/log'; log.mkdir(parents=True)
    cmd = ['sh', '-c', f'echo "timestamp=$(date -u +%Y-%m-%dT%H:%M:%S.000Z) level=ERROR usage limit exceeded" >> {log}/opencode.log; '
                       'sleep 2; echo recovered; sleep 8; echo done']
    try: run_budgeted(cmd, d, {**os.environ, 'XDG_DATA_HOME': str(d)}, d / 't', d / 'l.json', 60,
                      containment=False, progress_timeout=900, configured_model='opencode-go/x'); stop = 'none'
    except BudgetError as e: stop = str(e)
    assert stop == 'missing_usage', stop  # ran to its end (the fake prints no usage); not provider_limit
print('PASS a limit line before later output does not stop a recovered call')

# Resume handshake (2026-10-20): clears a previous run's stop once, so a resumed run's first calls may be parallel.
from budget import resume_ledger
with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d) / 'l.json'; p.write_text(json.dumps({'cost': 0.0, 'calls': 0, 'events': [], 'terminal_stop': 'usage_monitor:X', 'active': [1]}))
    resume_ledger(p); l = json.loads(p.read_text())
    assert l['terminal_stop'] is None and 'active' not in l and l['previous_stops'] == ['usage_monitor:X'], l
print('PASS resume handshake clears the stop once and records it')
