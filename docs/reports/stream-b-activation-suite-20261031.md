# Stream B activation full-suite record

Run 1, 2026-10-31. Tested commit `9d39185097822ffd253181bb72212c278493bd75`,
merging `factory-simplify` at `b500db9fff4a719ff8fdf1d74209dd56e7b09448`
into the holder activation implementation `150800aced1c4fa7f32efa3651692547446891d7`.
Production and test code were unchanged throughout this run.

Command: `uv run --with numpy --with scipy python -B tests/run.py`.
Result: **155 test scripts run; 0 failed. Exit 0.** No isolated rerun needed.
Log: `/tmp/stream-b-activation-20261031-150800a-suite-1.log`.
Log SHA-256: `36a9c5f5967193dedf9658218f9041b57b6725161c4ca0623a581e5325d37221`.
Host was loaded (observed 1-minute load 11.18 to 40.02); the suite completed.
This is offline regression coverage, not live VM evidence or a Murphy closure.

Fresh Claude diff review separately found a missing-ids early-exit bug and
insufficient fence/publication-path tests. A standalone reproduction returned
`pending` where `failed` was expected. Those findings remain valid despite this
suite pass; review fixes and their rerun will be recorded below.


## Run 2: review fixes

Tested commit `564c1c8ab134c15e8997ac676178c094c22acd37` on 2026-10-31. Production and test code were
unchanged throughout this run; only final review/design documentation was added.
Command: `uv run --with numpy --with scipy python -B tests/run.py`.
Result: **155 test scripts run; 0 failed. Exit 0.** No isolated rerun needed.
Log: `/tmp/stream-b-activation-20261031-review-fixes-suite-2.log`.
Log SHA-256: `2c902177f6ddc14ca448ebfb084a582f1a7833ad8828dfef56b8db5bb817df5e`.
Script-reported skips: tests/factory/test_budget.py: OK (skipped=1); tests/factory/test_late_rehearsal.py: OK (skipped=1); tests/factory/test_stress_loop.py: OK (skipped=1).

The targeted holder suite also passed 46 tests before the full run. The fresh
Claude Opus 5.5 final review passed with no open blockers in
`docs/reviews/batch-holder-activation-diff-2.md`; the original final report and
fix response are preserved in `docs/reviews/batch-holder-activation-diff-1.md`.
The design review remains `docs/reviews/batch-holder-activation-design-2.md`.
All three diff-1 blockers were fixed, not rejected. No Murphy rows closed.

The account-2 routing proposal, precise credential label/provisioning prerequisite,
parent-approved live practice proposal and deferred per-invocation ACK hardening
are in `docs/reports/stream-b-activation-practice-plan-20261031.md`. No live
practice, cloud deployment, push or merge into factory-simplify was performed.
