# Qualified-path allowances: suite record

The first full run used `uv run --with numpy --with scipy python -B tests/run.py`.
It finished with 161 scripts and one failure: test_isolation_timeouts.py's
post-ready fault injection corrupted free_models.py, whose unused eager import
this change intentionally deletes. See stream-d-qualified-allowances-suite-
20261031T142200Z-6c3189ed.log and its JSON timing/exit record in this directory.

The correction injects an ImportError at the same post-ready runner boundary
instead of restoring the obsolete dependency. The pre-ready gate_pipeline import
fault is unchanged. All 22 tests in test_isolation_timeouts.py then passed.
The full suite is rerun, not inferred from that focused result.

The 10 new qualified-path tests use the saved public practice tree and historical
5813be ledger. Model outputs, job delivery, and gate judgments are authored offline
controls; startup, accounting, exhaustion recording and recovery decisions run
through production code. No inference, VM launch or live qualification is claimed.
The unchanged B test test_wrong_authority_and_pointer_alone_never_grant in
tests/factory/test_batch_holder.py retains legacy_retire coverage.

No Murphy rows close. Row 9's two-repair subproblem is addressed; integrated
outcomes and live qualification remain separate. Rows 13 and 39 are unchanged.

## Final full-suite result

PASS: 161 test scripts run, 0 failed; exit code 0. Command unchanged:
`uv run --with numpy --with scipy python -B tests/run.py`.
Started 2026-10-31T14:49:17Z; completed 2026-10-31T15:17:59Z.
Full output: `stream-d-qualified-allowances-suite-20261031T144917Z-7e4fe9b8.log`;
structured timing/exit record has the same basename with `.json`.
The corrected isolation file ran 22 tests successfully in this full run. The
new qualified-path file ran 10 tests successfully. Both full runs completed;
neither a running process nor focused success is reported as a full-suite pass.
