# Early writer rejection observations

Merged factory-simplify b75c9b4 before implementation (G1 observations, lane 1
blocking-stress outcome and stream B fresh admission). This slice retains only
failed early gate or saved-cheat observations. It does not complete history or
claim progress/retirement; the existing execution-pending hold remains.

The optional writer_early and on_rejection hooks preserve ordinary defaults and
run record publication outside gate_attempt retry. Records retains the exact
feedback plus worker count; replay verifies using copied args, avoiding the
one-worker dependency-selection mismatch without changing scientific versions.
Package entry authenticates and restores a rejection before G1/early execution.
Saved-cheat observations use their own namespace/version, not a G6 result/cache.
The saved-cheat summary is cleared before sampling so CaseProblem cannot retain
an older pass marker. No pass records or additional allowances are introduced.

Tests use admitted practice bytes/5813be ledger, real G4/G5 and saved-cheat judging
on saved executions, with labelled writer/G1/G15/G3/checkpoint transports. Coverage
includes both writer recovery windows, record publication crashes, refusal and
worker-count cases, stale summary/CaseProblem, sample invalid-infra/timeout,
all-pass routing and save failure outside retries. Existing assertions stay intact.

Design reviews docs/reviews/stream-d-writer-early-observation-design-{1,2}.md;
round 2 PASS. Both blockers are fixed. Optional worker-count simplification was
independently rejected in round 2 because dependency_files excludes factory_pool
at one worker. Terminal receipt consistency remains a next-slice obligation.
Focused file: 11 tests pass. Implementation caba7e6 passes the locked full suite:
179 scripts, 0 failed, exit 0, elapsed 2282.7 seconds. Record and log:
`stream-d-writer-early-suite-20261102T153312Z-deedf1fd.{json,log}`.
Log SHA-256: `87f8ab62e82bf21687422c4cef444a927770a135d2759875c65d1d590766fc47`.
Fresh diff review pending. No Murphy rows close.

Next lane 2 slice: rejected-writer terminal completion/replay and progress decision,
including stricter receipt consistency and irrelevant-edit rerolls. Then partial/
legacy entry reconstruction and final all-outcomes integration. Lane 1 public-match
and blocking-stress have landed; post-extension factory-bug return is lane 1.
Activation, limits, attribution and existing snapshot/gate versions are unchanged.
