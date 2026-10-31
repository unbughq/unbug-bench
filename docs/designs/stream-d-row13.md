# Row 13: a usable stress report at the time limit

Problem: item 4 retains category answers and interrupted bytes, but its aggregate
has no explicit pending status, coverage inventory or interrupted-output index.
A timeout before a valid category answer leaves an unexplained empty aggregate.

Smallest change: keep category mode and its ordinary pending receipt. Extend the
aggregate with status (pending or scored), round, operation_id, category_state,
coverage for every required category/subcheck, and an index of retained partial
files (relative paths and SHA-256). Pending is never a pass: complete stays false
until all coverage completes; uncompleted CLI output is evidence only, never
promoted to findings or coverage. Previously authenticated findings survive.
Write the pending aggregate before publication/dispatch. On BudgetError from
answer (including timeout), record stop_reason, regenerate the report after the
existing finally block saves partial bytes, and mark publication pending. Re-raise
the original error: no fresh model call, automatic diagnosis or money change.
The ordinary stop/seal path retains these files; the existing dispatch barrier
publishes pending bytes before any resumed model call. Do not retry publication
inside an expired operation or mask its original stop. A later successful
category clears the stop reason and regenerates the report.

Delete no execution path or allowance. Optional cleanup removes only the redundant
write_and_attack barrier install once test contexts use Ctx; fix http_5xx prose.
No item-7 routing changes. Legacy non-batch stress is outside this increment.

Tests: replay the hash-verified real saved practice case and 5813be ledger through
write_and_attack and actual ModelRuntime with authored CLI output/timeouts. Cover
first-category timeout with no bytes, malformed partial bytes, and timeout after
two completed categories. Assert valid pending report, exact retained coverage,
partial digest, pending receipt, unchanged round/operation and no fabricated
findings/pass. Archive and restore the resulting work tree, rebuild a production
Ctx, resume only unfinished categories, and assert report becomes scored with
unchanged completed bytes and operation. This is saved-artifact control-flow proof,
not a live model-timeout claim. Full suite then fresh diff review required.

Murphy row 13 closes only its report-loss failure with this real-artifact test.
The older requirement for automatic diagnostic recovery remains open under row 9
and item 8; this change makes no recovery claim. Item 8 must exercise live stress
timeout/publication and diagnostic exhaustion. No other row closes.

Design-review clarifications: catch BudgetError around answer(), after invoke's
finally has run. Aggregate metadata is additive and preserved by classify and
attack_report; identity echoes the receipt. Closure tests are
`tests/factory/test_stream_d_retries.py::test_row13_real_artifacts_timeout_before_output`,
`test_row13_real_artifacts_timeout_malformed_partial` and
`test_row13_real_artifacts_timeout_after_categories`.
