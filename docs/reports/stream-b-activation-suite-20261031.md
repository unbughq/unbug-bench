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
