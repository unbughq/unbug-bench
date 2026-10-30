# Router maxima implementation validation

The implementation follows the design/readiness PASS in
`router-maxima-design-4.md`. This is offline implementation evidence, not
production qualification. Murphy rows 2, 3, 4, 20, 47 and 48 remain OPEN.

## Pinned Linux CLI exam

`tests/factory/fixtures/router-maxima-linux-gate.json.gz` saves verbatim commands,
results, binary hashes, source hashes, image configuration hashes and the public
Dockerfile for ten successful probes after diff-1's contention fix. Both Linux x64 (production architecture)
and ARM64 ran the exact Claude 2.1.299 public package. The fixture's recorded
source hashes match the tested implementation. Public package provenance is in
`router-maxima-cli-audit.json.gz`.

Every command used Docker `--network none`, the actual ModelRuntime, router
Store/start RPC, wrapper gate, `run_budgeted`, and the isolated-user `sudo` path.
Only public source and public binaries were mounted read-only. No host home,
credential directory, SSH material or Docker socket was mounted. A synthetic
OAuth value reached only a loopback fake provider; no real provider, model,
case or Boat worker ran. The harness replaces the fixed HTTPS connection in
test code only; production has no upstream URL override.

Each architecture passed all five scenarios. The original eight were actually
rerun on the changed source, not relabeled:

| Scenario | Forwarded | Unknown | Result |
| --- | ---: | ---: | --- |
| Bash tool loop, hosted WebSearch rejected locally, continuation | 3 | 0 | done |
| Actual CLI retries after scripted 503, allowance exhausted | 2 | 2 | model_call_cap |
| Actual reactive client compaction, native compact_boundary | 4 | 1 | done, final_usage_known=false |
| max_tokens stop then continuation | 2 | 0 | done |
| Three concurrent native clients, third waits for validated release | 3 | 0 | done |

The retry scenario deliberately enables retries after the production environment
normalizer to prove they use the same gate. Compaction deliberately reduces the
test context threshold and scripts a context-length rejection. These overrides
are enumerated in the artifact; they are not production settings. Every
forwarded body used the exact allowed model, standard_only tier and at most
32,768 output tokens. Each scenario acquired and started exactly one Lease.

The concurrency exam uses three actual pinned CLI SDK clients, two launched as
test-only extra clients sharing the main invocation's gate. The fake upstream
holds two replies until the third admission really waits on the Condition, then
releases validated usage. All three complete; no cap is raised. This is not a
claim that a live parallel WebFetch workflow completed under network denial.

## Focused checks

`uv run --with numpy --with scipy python -B tests/factory/test_model_call_maxima.py`
passes 16 tests, including real-receipt repricing, lost CLI final/unchanged
partial booking, exact near-ceiling float booking, supplied/RPC cap tampering,
one-use start, interruption propagation, sticky exhaustion, close-before-send,
missing/empty/malformed terminal provider usage retaining the whole W, refundable
concurrency waits, permanent unknown exhaustion, cancel/deadline/close wakeups,
and preservation of cancellation_failed.
Existing router (36), runtime (3), provider routes (4), and launch manifest (2)
tests also pass.

## Integration rebase

Rebased onto factory-simplify `6abe1690d2cc65078a64b347d923cd0aba6be655`
after the previous diff review. D's budget.py and B's authority/installer/money
modules are byte-identical to that base. A's gate/router/runtime/pricing logic is
byte-identical to the old reviewed d6e1f80 tree. Conflict resolution preserves
B's entire interfaces section8 byte-for-byte and unions the required worker
manifest test expectations. D accounting-only synthetic Lease constructors now
carry the required fields. They are not enforcement proof.

The new contract test uses an actual route policy Lease with the real
job_authority reader and reserve_invocation/settle functions: 49.999999999 USD
refuses without booking, 50.000000000 admits, unknown usage settles 50 once,
replay adds zero and mismatched authority refuses. Maxima16, D accounting17,
job_config4 and launch_manifest2 focused tests pass. No D2 dispatch or B practice
qualification is claimed. All ten native probes were actually rerun against the
integrated budget source and PASS; the artifact now records that base and the
seven freshly verified source hashes. Full current-suite and fresh integration
diff-review results follow; old hashes/results are not relabeled.

At max_usd=50, a default $50 job can admit only one separately reserved Claude
invocation from zero spend once that call has a positive charge. Another needs
settled+50 authority, any priced ordinary writer call triggers D's ordinary $50 diagnosis
test, and two concurrent nested owners need $100 plus settled spend. A first-call
success must not qualify package availability. Founder/D/B must size commitments
or revisions accordingly, or approve a separately reviewed lower route profile
against the 153-receipt table, before D2 enablement. D2 reserves the exact verified
Lease maximum (nine-place upward rounding); D's unknown settlement intentionally
uses maximum minus booked events, not cap_used.held_usd. No authority or route
profile is changed to conceal this limitation.

## Full suite

The first full run on `fcc003058d6a5a648041beb845d0c5e975fb86a2`
completed 135 scripts with one failure, the historical C policy migration test.
The complete log is `router-maxima-full-fcc0030.log.gz`; metadata with command,
tested SHA and timestamps is `router-maxima-full-fcc0030.json`. The calibration
interruption-label addition changes a digest that C deliberately pins. Runtime
correctly refuses that unpinned migration. The test now exercises C's recorded
target as its positive example and asserts refusal of the newer actual identity
and panel. C's production compatibility policy and scoring are unchanged.

The second run on `de33c1b6207440d01bf6bb61b028fd6d8d410eff` was deliberately
interrupted after fresh diff review found M1. Its partial log and interruption
metadata are saved as `router-maxima-full-de33c1b.log.gz` and `.json`; it is not
claimed as a passing run. A final full-suite result follows stabilized fixes.

The integrated full run PASSES: **139 test scripts run; 0 failed**, exit0,
on tested implementation `0a91d8abb7fee8c275af50ae641ab8ff94418c2b`, base
`6abe1690d2cc65078a64b347d923cd0aba6be655`. Command:
`uv run --with numpy --with scipy python -B tests/run.py`. It ran from
2026-10-30T02:45:16.984398Z to 03:01:42.286237Z. Complete terminal log:
`router-maxima-full-0a91d8a.log.gz`; metadata, command, exact SHA, timestamps,
script count and uncompressed/compressed log hashes:
`router-maxima-full-0a91d8a.json`. Subsequent changes are documentation/review
records only; `git diff 0a91d8a HEAD -- factory tests bin tools` is empty.

Final design/readiness PASS is `router-maxima-design-4.md`. Final fresh
cross-family integrated diff PASS is `router-maxima-diff-4.md`: zero Blockers,
zero Majors, with the terminal green suite and archival hashes independently
verified. All prior reviews and responses remain verbatim records. No blocking
finding was rejected. No merge, push, deployment or real model/case run occurred.

Current rotation packages remain unqualified because
their non-Claude routes have no enforceable bound; B's separately authorized
practice-case exam remains required for production qualification.
