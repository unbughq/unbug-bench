# Admission decision queue design review 9

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL on the full revision 9 design; PASS for the disabled, disposable-test-only checkpoint 1.** Checkpoint 1 can implement pending-workflow bookkeeping and reporting with V1 still the default. It does not establish the later queue or recovery behavior.

1. **Blocker — a recovered ADMIT result does not reach the case.** The [recovery protocol](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:151) restores the action and registry to the batch, but does not deliver the authenticated result, snapshot, and post-result counters to the case. Current WP1 waits for the child result and does not catch that failure ([engine.py](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/engine.py:371)); DBOS 3.4 records and re-raises a child error. A successfully completed ADMIT can therefore leave its case in `engine_error` or waiting, despite the registry being preserved.

   **Fix:** Have V2 catch terminal-child failure and wait for an idempotently keyed reconciliation response carrying the authenticated `StepResult`, action, and post-result counters. Define the fallback if the case itself cannot resume. For a non-OK ADMIT, retain the existing registry: the contract forbids an updated registry on that result. Test failure after settlement and before reporting, then prove the case continues without rerunning ADMIT.

2. **Blocker — an acquired worker can be missing from the journal.** The [preparation-token protocol](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:184) says the reconciler resolves the lease, but does not specify recovery when `acquire` succeeds and its DBOS step fails before recording the returned lease. Missing output cannot prove there is no worker, and clearing the token on that assumption can leak capacity or allow another first-ADMIT preparation.

   **Fix:** Record the case and requested release versions before acquisition. Retain the grant and token while the old call may still execute; after proving it quiescent, repeat that exact idempotent acquisition to recover or safely resolve the worker before clearing the token. Treat confirmed absence as a predecessor-release fact. Test both committed-but-unrecorded and still-running acquisition. WP2’s idempotency correction remains necessary for real Boat use.

The [parent design](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution.md:308) also still says the queue migration is reviewed and refuses old journals. That contradicts revision 9’s proposed, unguarded WP1 scope; the parent confirmed it will correct this wording.

Checkpoint 5 should explicitly place the WP2/WP5a/WP6/WP7 cross-package test after those packages are independently reviewed and merged, before integrated real use. WP1’s own merge gate can retain its fake-seam tests, 20-kill exam, full suite, and diff review.

The parent’s [admission-cutoff clarification](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution.md:179) is coherent: the recorded admission decision is subject to the cutoff, while already-admitted execution may occur later. The queue’s normal-path ordering, keyed grant handoff, and seal-before-fence acknowledgement address the earlier reviewed races, subject to their proposed fault tests. Deferring the database guard to WP8 is acceptable for this unpublished package with disposable databases; it remains an open production rollout gate. The design also explicitly accepts quarantining uncertain operations at a possible availability cost.

No files were changed, tests run, databases inspected, or remote services contacted.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–2 | Revision 10 specifies a keyed recovered-result handoff and quiescent exact-acquisition recovery, with the requested fault tests. Fresh review and implementation remain pending. |
| Parent wording | Corrected in the isolated checkpoint-1 implementation; not yet integrated. |
| Integration order | Revision 10 moves the cross-package test to the final merged-tree and real-use gate, after the dependent reviews. |
