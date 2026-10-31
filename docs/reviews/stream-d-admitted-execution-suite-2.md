# Admitted execution full-suite record 2

Command: `uv run --with numpy --with scipy python -B tests/run.py`

Started: 2026-10-31T13:38:15.755095Z.
Finished: 2026-10-31T14:03:26.765191+00:00.
Exit code: 0.
Result: 159 test scripts run; 0 failed.

Log: `docs/reviews/stream-d-admitted-execution-suite-20261031T133815755095Z.log`.
SHA-256: `94cb2f62f4d14094a8d1dfc2ef22a069a75905ffabfd51caec3d87c17501ae34`.
Base: `0d3259f`.
Scope: added admitted-writer provider-wait and stress InfrastructureExhausted
loop replays required by diff-review-1 B1; documentation clarification only.
Production implementation is unchanged from 0d3259f. No files changed during run.
All 11 execution tests passed. Offline controls only; no Murphy row closes.
