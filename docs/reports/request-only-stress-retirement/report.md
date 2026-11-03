# O5b offline evidence

Baseline: land12 `7f1c09e`. Implementation: `e3cd178` on `t3/isolation-o5b`.
No live workers, model CLIs, HTTP requests, paid calls or pilot launched.

Authenticated, exhausted request-only stress without metadata now retires
unscored. An existing independent clearance is authenticated even without report
metadata, allowing the ordinary clean stress path. No stress outcome is created
by retirement and the extension history remains open. B holds its money as for
other terminal cases; no diagnosis, replacement or settlement resume is invented.

Design round 2's category-mode blocker was resolved by the parent's explicit
approval: accept complete=True OR status=scored under the existing receipt/hash
checks. No third design review. Both reviews are retained under docs/reviews.

## Tests

- `focused.log`: 18 tests pass in 50.007 seconds. Uses saved practice case and
  5813be ledger, real category publication, package proof checks, dispatch apply,
  accounting finalization, B collection/projection and status/recovery code.
- `negative-control.log`: expected failure, exit 1. A temporary copy of
  extension_package.py had the entire retirement branch removed (between the
  complete/status conjunction and the clearance condition); that source was
  compiled into the imported package module. The real case_freshness retirement
  test failed because it received extension_execution_pending. Repository
  production source stayed unchanged. No runtime opt-out was added.
- `full-suite.log`: **182 scripts, 0 failures, exit 0**. Elapsed 2847.271 seconds
  including shared-lock wait; no timing rerun or limit change needed. Command exactly
  `lockf -t 7000 /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py`,
  with subprocess timeout 7200000 ms including lock wait.

Development checks exposed only fixture/assertion errors, fixed before the
recorded focused pass: saved freshness flags required an explicit authored
no-flag boundary; the B test initially used legacy schema-1 authorization rather
than the holder's schema-2 locked API; normalized public totals are decimal
strings. No production limits were changed.

CLI answers, checkpoint ACKs and no-flag inputs are authored controls. The
clearance exam uses saved HTTP bytes and an authored reviewer exclusion, while
real confirm_hits creates the proof and real cleared_stress authenticates it.
B transport uses saved opaque encrypted bytes as a collection envelope with
authored release binding and known/unknown total controls; this is not a live
encrypted checkpoint or accounting acceptance claim.

## Residuals

No Murphy row closes. Unfinished diagnostic/validation evidence remains an
accepted hold. Comparison re-runs can still score request-only/no-metadata as a
failure leading to retired_no_progress; ordinary writer rounds still forward
request lines as problems. Disabled diagnosis can overwrite the retirement label
on an explicit relaunch. Cross-batch export filters remain unchanged. Live
isolated-UID, actual-CLI cancellation and deployment delegation acceptance remain
unqualified from O7. None of these is claimed fixed by this package increment.

Fresh Claude diff review round 1 PASS, no blockers:
`docs/reviews/request-only-stress-retirement-diff-1.md`. Optional nits remain,
including a stale clearance beside a clean same-round re-attempt causing an
additional unscored hold. Production source is unchanged after testing/review.
No merge or push performed.
