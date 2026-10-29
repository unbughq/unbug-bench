# Invalid-run validation

Implementation head after rebase: 396689ccc887611d5340c127dd77bf1802d73e0c.
Base: factory-simplify 8c5de614d14af0df1e6b63f31972195825e8cd53.
Rebase changed documentation only: git diff c57128f HEAD -- bin factory harbor tests tools was empty.

Command:

    uv run --with numpy --with scipy python -B tests/run.py

Result: 130 test scripts run; 0 failed. Completed 2026-10-29 UTC.
Full log: /tmp/invalid-runs-full-suite-review2.log
Log SHA256: 4e22b0321d6ba6e8c351968ddcc1851dd9c9988c6729857d134733100bb89631

The final run includes 31 tests in tests/factory/test_invalid_runs.py. The
regression script also passed directly (31 tests) after all diff-review-1 fixes.
These include external early-probe workspaces/transcripts, per-try replacement
reuse without rebuying a valid suffix, provider waits, fresh post-success retry
allowances, unflagged freshness alternatives, stable G11 evidence and one crash
diagnostic per execution. No implementation code changed during the full run;
the rebase brought documentation/interface clarifications only.

Saved valid scientific outputs have unchanged verdicts under differential replay.
116 public card snapshots / 54 case identities have one explicit changed validity
projection: case-20261017T125556Z-18681d's G10/hard label cannot use its two strong
runtime-error outcomes. No original card or archive was modified. See
invalid-runs-artifacts.md for the card-only compatibility limit and raw sources.

Row 14 remains open for prohibited-here live schedule qualification. No real
worker/provider batch was launched and no real archive was decrypted.
