# Admission decision queue design review 12

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — revision 12.** The case-owned acknowledgement resolves review 11’s specific cross-generation scenario: once the case records it, any later reaper can observe it and finish. DBOS 3.4 stores workflow events under the originating workflow ID and allows other workflows to read them. The explicit `no_dispatch` exception also removes the authenticated-result contradiction. Two liveness gaps remain.

1. **Blocker — a terminal case cannot supply the acknowledgement needed for reaper completion.** The design requires response replay until acknowledgement, but its terminal-case fallback does not say how the reaper stops waiting when the case fails before consuming the response or after consuming it but before recording the event. Batch termination requires reconciliation to be terminal. This affects both recovered results and `no_dispatch`. [Acknowledgement and fallback](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:175), [termination requirement](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:221).

   **Minimal correction:** Define a durable, generation-independent terminal-case resolution that every reaper can observe. After proving the case cannot continue and safely resolving its worker, grant and fence, the reaper completes on that resolution without inventing a case acknowledgement. Preserve the existing successful-SEAL reporting rule. Test both response types with the case failing before receipt and after receipt but before acknowledgement, including a reaper-generation change and batch termination.

2. **Blocker — a probe can fail after opening its fence but before reserve starts.** Recovery covers a recorded reserve or a committed reserve with missing output; the new `no_dispatch` transition requires an existing unstarted grant. If no reserve began, there is no grant to settle and no specified transition to close the fence. [Fence](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:96), [reserve recovery and no-dispatch](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:133).

   **Minimal correction:** Once no reserve was started or remains in flight, durably close that probe’s fence without settlement, keep the candidate unadmitted, and enqueue a fresh probe with a new key and authorization. If a reserve may have run, retain the fence until quiescent and recover the grant idempotently. Test failure before invocation and on both sides of the uncertainty boundary.

No tests were run. Full queue tests and the WP2/WP8 gates remain future work.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–2 | Revision 13 records terminal-case resolution independently of case acknowledgement and adds the quiescent pre-reserve transition and fault tests. Fresh review and implementation remain pending. |
