# Stream D item 4: full suite, run 2

Commit tested: 3197e31. Source was unchanged throughout the run.

Command: `uv run --with numpy --with scipy python -B tests/run.py`

Result: PASS, exit 0. **156 test scripts run; 0 failed.**
The 21 ordinary-retry tests and 42 runtime regression tests passed in this run.
No failure required a timeout-under-load exception or isolated timeout rerun.

The first run's launch-manifest inventory assertion was fixed by listing the
three new worker modules explicitly. The publication barrier now takes the
shared dispatch lock, and G2 output shape/decision projection is stricter.
Affected tests also passed separately before this full rerun.

Full log: `/tmp/stream-d-lane1-item4-full-20261031-implementation-2.log`
SHA-256: `129e1fbb2da37d2eac9b8286c0360ff2e899681b0a6150895188e06f2ee67aa7`.

Scope: batch item 4 only. Rows 11, 12 and 15 have the tested scope/limitations
recorded in docs/murphy-register.md. Row 13 remains open for item 7/8 diagnostic
recovery. Diagnosis is not enabled. No real case or live provider was launched.
