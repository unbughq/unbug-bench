**NOT PASS — fresh DIFF review, round 1/2, Mode REVIEW.** Reviewed `15a5c6a..ee9392c` against the design and both design-review records. One Major blocks approval; no Blocker findings.

1. **Major — `_admit` signature change breaks existing production and test callers.**  
   [batch_holder.py:231](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/factory/batch_holder.py:231) adds required positional `home`, but [qualify-batch-inputs.py:35](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/tools/qualify-batch-inputs.py:35) still supplies the old arguments. Every qualification reaching this call raises `TypeError` for missing `source_generation`; the tool catches it and silently reports eligible inputs as refused.

   Unchanged direct callers also remain in [test_batch_admission_clamps.py:146](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/tests/factory/test_batch_admission_clamps.py:146), [test_batch_transfer.py:340](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/tests/factory/test_batch_transfer.py:340), and [test_qualify_batch_inputs.py:77](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/tests/tools/test_qualify_batch_inputs.py:77). These now error before exercising admission. This is established statically; no tests were run.

   **Fix:** pass the appropriate `home` through every caller and correct the design’s assertion that `reserve` is `_admit`’s only caller. Include these existing regression files in verification.

2. **Nit — two new refusal branches lack direct negative coverage.**  
   The [imported-source matrix:415](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/tests/factory/test_batch_resume_queue.py:415) mutates current facts but never predecessor facts independently. The [legacy-marker matrix:245](/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c/tests/factory/test_batch_resume_queue.py:245) covers symlink parents but not regular-file/non-directory parents. The production guards are present and look correct. Optional additions should isolate these branches and assert unchanged authority, operations and queue.

The remaining static review supports the implementation:

- Exact queue equality, authenticated policy, producer config/incident checks, recomputed current **and predecessor** facts, reason and legacy checks precede authority advancement under the money lock. Existing source/ACK/outbox/retirement, owner, release, cumulative-money and capacity checks remain in use.
- UUID5 identity and existing reserve/reconcile/dispatch seams cover replay and the specified crash windows. Tick order preserves reconcile first, then planning, draining and provider waits. Settlement priority is snapshot-local; replacement-enabled known-total diagnosis remains explicitly deferred.
- The new tests use real D projection and accounting reconciliation for the two-leg unknown-to-known transition. Worker-boundary cards, imported queue, transport and dispatch doubles are honestly labelled. Legacy, sealed, retired and held-card guards are represented.

**Verification limits:** reported focused results are 21/21 and 11/11; I did not rerun them. The full no-lockf handback suite remains pending. No tests, edits, saved record, commits, delegation, workers, secrets, cloud or additional model calls were performed. Pilot admission and Boat remain with the parent; no Murphy row closes.

## Elephant disposition

Major accepted: migrate every direct holder._admit caller to pass its actual
control home, including the read-only qualification tool and all three named
regression files. The earlier design's sole-caller claim was wrong and is
corrected. The optional negative coverage is also accepted. The fix requires a
fresh, independent final diff review; no source-path change is self-approved.

