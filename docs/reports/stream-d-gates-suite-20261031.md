# Stream D item 5 suite record

Command: `uv run --with numpy --with scipy python -B tests/run.py`.

Branch: `t3/stream-d-gates`, base `b500db9`.
Tested implementation: `9060780e1a4e056a3f848a28e9a9b7a8d8e070da`.
Completed UTC: 2026-10-31T08:17:30.396597+00:00.

- Run 1, revision `d20e899`: 156 scripts; 1 failed (two obsolete whole-manifest assertions in test_strategy_reuse.py). Log: [stream-d-gates-suite-20261031-1.log.gz](stream-d-gates-suite-20261031-1.log.gz). Uncompressed SHA256: `e27ddb452ddb9fc87e534b0c26c36755e7e4950f16df3d297ded209abfd654b6`. Original unique log: `/tmp/stream-d-gates-20261031-full-suite-1.log`.

- Run 2, revision `9060780e1a4e056a3f848a28e9a9b7a8d8e070da`: 156 scripts; 0 failed; exit 0. Log: [stream-d-gates-suite-20261031-2.log.gz](stream-d-gates-suite-20261031-2.log.gz). Uncompressed SHA256: `999900c32dd6285cbad3acce19dafd6a19d5ddc515b3401327e9aa88240abc14`. Original unique log: `/tmp/stream-d-gates-20261031-full-suite-2.log`.

The first run finished before changes. The strategy tests now distinguish an
unrelated whole-release change (reuse) from an evaluator byte change (invalidate).
The corrected implementation also binds G1 source mode and stress judge environment.
Both focused test scripts passed before the second full run. Existing skips are
visible in the retained logs; no live model, cloud case or diagnosis enablement
is claimed by this offline suite.

Row 39 stays open: saved public card 18681d proves capped no-submission counts,
and saved public practice executions prove valid/invalid execution handling.
Capped-submission stop metadata and reviewer mistakes in the new tests are
explicitly authored perturbations, not a retained real capped-attempt lifecycle.
No Murphy row was closed. Item 6 was not started.
