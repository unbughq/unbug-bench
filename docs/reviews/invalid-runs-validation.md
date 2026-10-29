# Invalid-run validation

Implementation head: c50e8d503c0caa4b69c2fbd0df2f7ccb177003ee.
Base: factory-simplify 3f7521bd3eee1e931c2f8ce78ebfe26c368e3b5c, including stream E's first increment.

Command:

    uv run --with numpy --with scipy python -B tests/run.py

Result: 131 test scripts run; 0 failed. Completed 2026-10-29 UTC.
Full log: /tmp/invalid-runs-full-suite-final-combined.log
Log SHA256: 26b53a85e796c7c18c75bac6236752cd98cdbfa8520ef0da3f196f3d057221e0

The full run includes 33 tests in tests/factory/test_invalid_runs.py and all
20 isolation/timeout tests. Direct checks also passed: 33 invalid-run regressions,
20 isolation/timeout tests, overlap/cancellation/dual-exhaustion checks, frozen live
runtime staging, and 3 negative-probe tests. The first E+C full run had one outdated
timeout-test fixture (missing case directory and old scientific-failure card
expectation). It was corrected, passed directly, and the complete suite rerun above
passed. Implementation and fixtures were unchanged during this final full run.

Review fixes cover external early-probe inputs/transcripts, per-try replacement
reuse, provider waits, post-success retry allowances, inaccessible and dead
unflagged freshness URLs, structural missing-observation feedback, stable G11
inputs, first operational-stop retention and nonduplicated crash diagnostics.

Saved valid scientific outputs have unchanged verdicts under differential replay.
116 public card snapshots / 54 case identities have one explicit changed validity
projection: case-20261017T125556Z-18681d's G10/hard label cannot use its two strong
runtime-error outcomes. No original card or archive was modified. See
invalid-runs-artifacts.md for the card-only compatibility limit and raw sources.

Row 14 remains open for prohibited-here live schedule qualification. No real
worker/provider batch was launched and no real archive was decrypted.
