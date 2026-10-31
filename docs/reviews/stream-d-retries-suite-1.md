# Stream D item 4: full suite, run 1

Commit tested: 5287416. Source was unchanged throughout the run.

Command: `uv run --with numpy --with scipy python -B tests/run.py`

Result: exit 1; 156 scripts run, 1 failed. The failure was
`tests/tools/test_launch_manifest.py::test_successful_bundle_dependencies_and_current_consumers`:
the independent expected-worker inventory omitted the three added modules
ordinary_retry.py, ordinary_freshness.py and stress_progress.py. This is an
expectation update, not a timeout; no load-only rerun exception applies.
The new 20-test retry file and all 42 runtime regression tests passed.

Full log: `/tmp/stream-d-lane1-item4-full-20261031-implementation-1.log`
SHA-256: `f6a53a24897c4839713ee63d4f2350691ba534549a8ff0479b142e3682e23109`.

Next: add the explicit worker inventory entries, tighten publication locking and
G2 shape validation found in self-review, rerun affected tests and the full suite.
No real case or live provider was launched.
