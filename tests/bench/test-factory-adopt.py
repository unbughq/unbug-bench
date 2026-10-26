#!/usr/bin/env python3
"""bin/factory-adopt auto-resume rules: passing stops resume (provider limits wait for the paid hour's end),
gate failures and budget caps never do, and the per-server limit holds."""

import sys
from pathlib import Path as _Path

_BENCH_ROOT = _Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BENCH_ROOT / "bin"))

import importlib.machinery, importlib.util, pathlib

path = (_BENCH_ROOT / "bin" / 'factory-adopt')
spec = importlib.util.spec_from_loader("adopt", importlib.machinery.SourceFileLoader("adopt", str(path)))
adopt = importlib.util.module_from_spec(spec); spec.loader.exec_module(adopt)
plan, now = adopt.auto_resume_plan, 1_000_000

for stop in ("stalled", "paused", "timeout", "claude_error", "runner_error:KeyError"):
    assert plan({"terminal_stop": stop}, {}, now) == (0, f"auto-resume 1/3 after {stop}"), stop
assert plan({"terminal_stop": "provider_limit:claude/claude-opus-5-5"}, {"expires": str(now + 3000)}, now)[0] == 2400
assert plan({"terminal_stop": "provider_limit:x"}, {"expires": str(now + 100)}, now)[0] == 0  # too late to wait: go now
for card in ({"terminal_stop": "call_limit"}, {"terminal_stop": "cost_limit"}, {"terminal_stop": "statement-ready"},
             {"failed_gate": "G8", "terminal_stop": "paused"}, {}):
    assert plan(card, {}, now)[0] is None, card
assert plan({"terminal_stop": "stalled"}, {"autoresumes": "3"}, now)[0] is None
assert plan({"terminal_stop": "stalled"}, {"autoresumes": "2"}, now)[1] == "auto-resume 3/3 after stalled"
print("PASS auto-resume: passing stops resume, provider limits wait, failures/caps never, limit 3")
