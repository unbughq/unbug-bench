# Stream D item 4 final merged full suite

Tested merge commit: `80d40a325d3d8b93498f9ea1a276d30e88b71c3f`. This includes factory-simplify at
`4fecb01` (items 5/6 and A/B/E fixes), merged into t3/stream-d-implementation.
Only the appended design sections conflicted; both were retained. Code merged
without conflicts. Item 7 belongs to lane 2 and was not started here.

Command: `uv run --with numpy --with scipy python -B tests/run.py`.
Log: `/tmp/stream-d-lane1-item4-full-20261031-merged-5.log`.
Log SHA-256: `bdb941b0fb7b90dc50e890a41e5245d740aed6e4a292dfb259f96a36cb9aa54e`.

Finished with exit code 0: **158 test scripts run; 0 failed.**
No timeout-only failure or isolated rerun was needed. Existing conditional skips
remain recorded in the log. Source stayed unchanged during the run.

All 33 item-4 retry tests and 42 stream-D runtime tests passed. The incoming
16 extension-comparison tests and 7 scientific-receipt tests also passed.
No real cases, model provider calls or rollout qualification ran.

Reviews are retained verbatim with author responses in
stream-d-retries-design-1.md through stream-d-retries-design-7.md and
stream-d-retries-diff-1.md through stream-d-retries-diff-2.md. Both diff-review
reports found blockers; all were accepted and addressed. The final small callback
initialization fix was verified with fresh-context tests and full suites rather
than another delegate, as required by the review tool workflow. No finding was
rejected, and no unqualified reviewer PASS is claimed.

Murphy rows 11, 12 and 15 are closed within the batch scopes stated in the
register; row 13 remains open. The new helper scientific-input interface for
lane 2 is documented under Item 4 handoff in docs/designs/stream-d.md.
