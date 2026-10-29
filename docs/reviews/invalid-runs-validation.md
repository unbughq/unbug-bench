# Invalid-run validation

Implementation/design head: 9de22476adb230714f3251b51400865203d97550.
Base: factory-simplify ac3326791f40af7ccf7c319ce0bf56552a6b4506, including E and the subsequent single-path increment.

Command:

    uv run --with numpy --with scipy python -B tests/run.py

Result: 133 test scripts run; 0 failed. Recorded 2026-10-29T23:10:55.401744+00:00.
Full log: /tmp/invalid-runs-full-suite-final-rebased.log
Log SHA256: 78b81a2cea5dcd8e2eb46a2ae79943eaa80852f130628cd76e64b5e0b5adfca0

The full run includes 34 tests in tests/factory/test_invalid_runs.py, all 20
isolation/timeout tests, and the new base's batch/restore regressions. Direct checks
also passed: 34 invalid-run regressions, 8 archive-ruling tests, overlap/dual-stop
checks, frozen live runtime staging, negative probes and worker manifest tests.
Implementation and fixtures were unchanged throughout this final complete run.

Earlier combined runs: the E timeout fixture needed a case directory and the new
unscored card expectation; it was corrected and a complete 131/0 run passed. After
the final flagged-dead-URL fix, factory-simplify advanced with a single-path
increment. The pre-rebase run was intentionally interrupted and superseded by the
complete 133/0 run above. The final rebase preserved batch.py and C's helper
inventory and changed no single-path contract.

Review fixes cover early-probe inputs/transcripts, per-try replacements, provider
waits, fresh retry allowances, inaccessible/dead searches regardless of hit flags,
structural missing-observation feedback, stable G11 evidence and first-stop
retention. A dead flagged URL can clear as unreachable yet never fill a search
minimum. Actual confirmation validation is exercised at exact practice-log minima.

Saved valid scientific outputs have unchanged verdicts under differential replay.
116 public card snapshots / 54 case identities have one explicit changed validity
projection: case-20261017T125556Z-18681d's G10/hard label cannot use its two strong
runtime-error outcomes. No original card or archive was modified. See
invalid-runs-artifacts.md for the card-only compatibility limit and raw sources.

Row 14 remains open for prohibited-here live schedule qualification. No real
worker/provider batch was launched and no real archive was decrypted.
