# Invalid-run validation

Implementation head after rebase: 255b3ec091fb9ee17760d8aef1b4b3e6796627e7.
Base: factory-simplify 59a2c8c38db7de9e3a0ac09444ae74128ecd5fff.
Rebase changed documentation only: git diff 1e13fb7 HEAD -- bin factory harbor tests tools was empty.

Command:

    uv run --with numpy --with scipy python -B tests/run.py

Result: 130 test scripts run; 0 failed. Completed 2026-10-29 UTC.
Full log: /tmp/invalid-runs-full-suite-final.log
Log SHA256: 404ec8ee603b924542c3cd8c47a0236f197628cf2a9d7e29808e6c94cc8d7951

The final run includes 24 tests in tests/factory/test_invalid_runs.py. The
negative-probe unit script also passed directly after the last scoring-boundary
change (3 tests); the real-artifact regression suite passed directly (24 tests).
The first full run found four integration failures: a missing json import,
missing staged validity helper, outdated independent worker inventory, and an
orphan test for an absent retired rescue finalizer. Those were fixed before this
passing run; unified finalization remains tested by test_late_restore_bundle.py.

Saved valid scientific outputs have unchanged verdicts under differential replay.
116 public card snapshots / 54 case identities have one explicit changed validity
projection: case-20261017T125556Z-18681d's G10/hard label cannot use its two strong
runtime-error outcomes. No original card or archive was modified. See
invalid-runs-artifacts.md for the card-only compatibility limit and raw sources.

Row 14 remains open for prohibited-here live schedule qualification. No real
worker/provider batch was launched and no real archive was decrypted.
