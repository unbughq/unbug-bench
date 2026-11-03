**NOT PASS — fresh DESIGN review, round 1/2, HEAD `2efbbc3`.** Three Major readiness findings remain.

1. **Major — The main exam is not executable as specified.**  
   The [test recipe](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/docs/designs/stream-d-resume-queue-drain.md:150) reuses `HolderTests.output()`, whose underlying [fixture installs `diagnosis_state={}`](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/tests/factory/test_batch_service.py:73). Calling the real [`record_exhaustion()`](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/factory/diagnosis.py:127) on that state raises `diagnosis_state_invalid`; the saved card also has no exhaustion stop. Specify removing the placeholder, setting an authored valid exhaustion, calling the producer, and writing the resulting card back to the **collected** input before publication.

   Line 163 also says to pass an ID to `HolderTests.preflight`; that [helper requires an operation dict](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/tests/factory/test_batch_holder.py:437). Use `self.ops()[identity]`. Label its fingerprint/account-selection doubles and inherited release-verification double accurately; with `Popen` doubled, assert restore **arguments**, not execution of a restore.

   Finally, prescribe advancing monotonic time by 60 seconds—or explicitly simulating restart—for interruption retries. Immediate repeated scans, as used by the existing wait tests, will remain suppressed after a refusal.

2. **Major — The changed-config refusal promises more than the proposed validation supplies.**  
   The [interruption table](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/docs/designs/stream-d-resume-queue-drain.md:133) promises no new authority or operation when config changes. But [`_source()`](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/factory/batch_holder.py:146) never validates the producing operation’s frozen config.

   Concrete sequence: plan successfully; corrupt the producer’s config; drain the queued row. The specified checks still permit money advancement and creation of a successor with a new, valid config. Dispatch’s [`_current_operation()`](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/factory/batch_holder.py:171) validates that successor config, so it does not catch the producer-config change.

   Specify an independent producer `_config` check before queued admission and add this post-planning interleaving test, or explicitly narrow the advertised refusal contract. Do not reuse the producer’s whole `_current_operation` check for crash recovery: money may already have advanced while the successor reservation is still absent.

3. **Major — The unknown-total exam stops before the essential second admission.**  
   The [null-total test plan](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/docs/designs/stream-d-resume-queue-drain.md:167) proves priority and unchanged revision/hold, but never proves settlement produces a newly collected, acknowledged source that the scanner subsequently drains for diagnosis.

   [Section 8](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/docs/designs/interfaces.md:450) requires this two-leg transition. The [worker deliberately exits after an unknown-at-launch pending resume](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/factory/diagnosis_dispatch.py:319), even when reconciliation has made usage known.

   Add an offline replay covering: covered unknown exhaustion → same-revision settlement reservation → real accounting settlement → distinct known-total `diagnosis_pending` generation → collect/ACK/retirement → second queue drain. Assert the same reservation owner, unchanged held commitment, preserved exhaustion ID, correct next revision, distinct deterministic operation IDs, and no duplicate dispatch. Include the documented held-card settlement exception with an assertion that the same-batch model-work guard still refuses work.

**Nit — State the scheduling cutoff explicitly.** The proposed ordering is snapshot-local. A higher-priority row added after selection is not reconsidered by the specified in-lock row check; backoff also temporarily skips older rows after their underlying blocker clears. The existing holder’s [singleton lock](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/factory/key_holder.py:502) limits production overlap. Document that assumption and the retry eligibility rule, so “FIFO” is not mistaken for a stronger concurrent-admission guarantee.

The replacement-enabled deferral is safe and honestly scoped: settlement proceeds, known-total diagnosis waits, and this increment does not claim replacement integration. The UUID5 identity, scan-lock release before `reserve`, and existing money → config → reservations → journal write order support the proposed replay approach. No additional ledger or launch path is warranted.

Skipped as instructed: edits, saved review, tests, workers, delegation, secrets, network/model calls, and live qualification. These are static findings. **No Murphy closure is justified; row 9 and `new-stream-d-current-comparison-1` remain open.**

## Elephant disposition

All three Majors and the nit are accepted. The revision pins the retained-card
setup and dispatch doubles, reauthenticates producer config independently of
current money state, and adds the covered-unknown through known-total two-leg
exam. Retry time and snapshot-local ordering are explicit. Fresh final design
review required before implementation. No finding is rejected.

