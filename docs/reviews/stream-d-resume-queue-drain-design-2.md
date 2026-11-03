**PASS — final DESIGN review, round 2/2, HEAD `6c425e0`.** No Blocker or Major remains. All three accepted Majors and the scheduling nit are resolved at design level.

- **Executable fixture and dispatch exam:** [design lines 169–188](</Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/docs/designs/stream-d-resume-queue-drain.md:169>) correctly remove the placeholder state, record exhaustion, update the collected input, and pass an operation dict to preflight. The helper uses `claude-token`, matching `CLAUDE_ACCOUNTS[1]`. Fingerprint, account selection, credentials, release verification, Boat and Popen doubles are accurately disclosed; assertions concern restore arguments and creator intent.
- **Producer configuration:** [lines 88–103](</Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/docs/designs/stream-d-resume-queue-drain.md:88>) specify exact local and imported producer `_config` validation before advancement. Avoiding `_current_operation` preserves recovery after authority advances but reservation creation fails. Facts are compared against the entry returned by authenticated `_source`, including the predecessor entry for imports.
- **Two-leg settlement:** [lines 189–210](</Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/docs/designs/stream-d-resume-queue-drain.md:189>) prescribe real receipt reconciliation, a distinct known-total `diagnosis_pending` generation, collection/ACK/retirement, and second admission. This matches [money revision advancement](</Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/factory/batch_money.py:360>) and the worker’s unknown-at-launch exit. Same owner, held commitment, exhaustion ID, revision and replay assertions are explicit. The held-card guard assertion correctly expects `factory_bug_held`.
- **Retry and priority:** Refusal retries explicitly advance monotonic time by 60 seconds or simulate restart. [Snapshot-local ordering](</Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/docs/designs/stream-d-resume-queue-drain.md:147>) correctly limits FIFO to eligible observed rows and acknowledges the singleton holder.

The proposed admission boundary retains authenticated policy, exact queue lookup, source/ACK/outbox/retirement proofs, legacy refusal, money/deadline/capacity checks and deterministic replay. Stale, retired or forged requests grant nothing. Replacement-enabled settlement remains allowed; known-total diagnosis deliberately waits for the replacement consumer. No additional launch path or ledger is warranted.

**Nit — clarify malformed-journal scope.** “A bad row cannot block later eligible rows” at design line 60 applies only after journal validation succeeds. Existing [`service._load`](</Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/factory/batch_service.py:132>) rejects the entire journal for malformed rows or non-dense sequences. Optional exact clarification: “A structurally invalid journal refuses the whole scan; per-row continuation applies to a successfully validated journal.”

**Required blocking fixes: none.** Skipped as instructed: edits, saved review, commits, tests, workers, secrets, paid calls, network/model calls, delegation and background processes. This is static design approval, not implementation or live qualification. B retains pilot admission/Boat ownership; no Murphy row closes.

## Elephant disposition

PASS accepted. No blocker or Major remains. The nit is accepted: a structurally
invalid journal refuses the whole scan; per-row continuation applies only after
the journal validates. Implementation and focused tests follow. No Murphy row
is closed.

