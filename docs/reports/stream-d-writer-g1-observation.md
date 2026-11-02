# Rejected-writer G1 observation

Merged factory-simplify 02f3bc9 before implementation, including lane 1 public-match
completion and stream B worker-router delivery. The existing public capture
context stays in place; the package adds only a writer_g1 callback inside it.

Both post-writer G1 checks use the optional callback, with ordinary default g1
unchanged. Records.writer_g1 retains only a real scientific failure and restores
it across the record-before-validation-receipt crash window. Passes and pending
returns publish nothing. Existing exceptions propagate; no retry or allowance
is added. Authenticated identity/support/version checks are reused.

All 10 new focused tests pass over saved practice bytes and the 5813be ledger.
The real failure is exactly case.json source differs from the run argument,
not a fabricated case-content diagnosis. Tests cover fresh/completed/done writer,
publication crash windows, legacy receipt without inferred evidence, pass and
pending/exception controls, support/case/version refusal and both stop-label
layers. The first test run exposed missing logs/ in the fixture, corrected before
the passing run; no production failure or live execution was involved.

Design review round 1 PASS: docs/reviews/stream-d-writer-g1-observation-design-1.md.
M1/M2 and all nits are incorporated. Full suite under the shared lock passed
177 scripts / 0 failures at fdfab00 (tree 599910529c71285ef3a8d5e5c98371739c0d96c9).
Record: stream-d-writer-g1-suite-20261102T114057Z-086295fe.json and matching log.
Log SHA-256: 72871d6e79848e72f9e290dc252cd00198a032500c37eec50bce45c3888447a2.
Elapsed 2160.8 seconds. Fresh Claude diff review round 1 PASS:
docs/reviews/stream-d-writer-g1-observation-diff-1.md. The reviewer independently
ran the new tests plus execution, runtime, unchanged and public-match tests.
No production/test changes follow review. factory-simplify was already up to date
on the final merge check. No Murphy rows close.
No terminal outcome/progress/retirement is claimed:
the current extension_execution_pending hold remains for rejected writers.

Remaining lane 2 rejected-writer work: early-gate/saved-cheat observations, then
terminal publication/replay and progress decisions (including irrelevant-edit
rerolls). Partial/legacy entry reconstruction and final all-outcomes integration
remain separate. Lane 1 public-match has landed; scored stress and post-extension
factory-bug return remain lane 1. Activation/limits/attribution/schema/version are
unchanged.
