# Admission budget design review 5

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — three blocking findings.** Revision 5 resolves several of the earlier normal-path races, but it still permits admission starvation and leaves two important ordering and capacity cases unspecified.

1. **Blocker — overlapping terminal barriers can starve admission until the deadline.**  
   `docs/designs/durable-execution-admission-budget.md:88–92, 105–131`; `factory/durable/policy.py:33–35, 111–117`; `factory/durable/engine.py:412–420`.

   The stated fairness rule only alternates message processing with *possible* probes. It does not ensure that all barriers ever close at the same time. For example, two admitted cases can repeatedly run SEAL attempts that each finish with `infra:paused`, staggered so that one barrier is always open. Those retries do not consume the infrastructure allowance. A pending case can therefore wait until the deadline despite available money and a free model slot, even though every individual attempt finishes. This is more than the documented delay for one slow SEAL and contradicts the claim that probes cannot starve.

   **Fix:** Specify admission fairness across barrier generations. For example, once an eligible pending request exists, defer acknowledgements for new terminal barriers until the currently open barriers have resolved; then allow one probe before fairly releasing deferred requests. An actually unresolved or quarantined barrier may still block admission. Test overlapping, repeatedly nonterminal SEAL attempts with an eligible pending case, and show that admission eventually gets a turn without allowing a probe ahead of an already acknowledged barrier.

2. **Blocker — predecessor release can be consumed before its replacement request.**  
   `admission-budget.md:69–79, 88–103, 118–123`; `engine.py:321–327, 625–648`.

   DBOS message delivery is not FIFO. The batch can receive `predecessor_released` before `line_stopped`, even though the predecessor sent them in the opposite order. The proposal does not say to retain a release confirmation when the corresponding replacement has not yet been created. An implementation that looks up only an existing replacement and discards an unmatched release will later hold the replacement’s grant and wait forever for a confirmation that was already consumed.

   **Fix:** Record release confirmation durably by predecessor case ID independently of replacement creation, and join the two facts in either order. Treat duplicates idempotently. Specify that batch termination happens only after draining readable control messages and resolving open terminal barriers, so a reordered `done` cannot hide a preceding replacement request or seal resolution. Test release-before-request, `done`-before-request, and `done`-before-SEAL-resolution, including replay and same-timestamp delivery.

3. **Blocker — predecessor release does not reserve capacity for the replacement.**  
   `admission-budget.md:69–79, 205–213`; `engine.py:236–245, 397–420`; `de/wp2:factory/durable/workers.py:485–510`.

   In the proposed bounded-pool scenario, another admitted case can acquire the sole freed worker capacity between the predecessor’s confirmed release and the replacement’s lease attempt. The replacement can then exhaust its ADMIT infrastructure retries and produce `STOP_ADMISSION` while that other case is still using the worker.

   The frozen `WorkerPool` contract does **not** promise a bounded pool, reserved capacity, or a distinct capacity-exhausted reason. WP2 provisions one Boat worker per case; if Boat rejects creation and no worker is found by intent, it returns the generic `infra:worker_create_failed`. Thus this is conditional on provider capacity rejection or the design’s requested bounded-pool test, not a claim that WP2 itself implements a one-worker pool.

   **Fix:** Specify a capacity handoff or a durable, bounded-backoff wait that cannot exhaust ADMIT’s retry allowance when capacity is unavailable. Account for WP2’s generic creation failure instead of assuming a capacity-specific reason exists. Test a third case taking the released capacity before the replacement, then releasing it; the replacement must eventually run without triggering `STOP_ADMISSION`.

The recorded grant replay, fresh keys after WAIT or EXPIRED, grandfathering of admitted cases, and exact-lease proof requirement address the corresponding earlier findings in the proposal. The cleanup and reconciliation transitions still require the specified fault-injection tests and diff review; this review does not establish their implementation.

The pre-enqueue barrier is the smallest valid approach identified here without changing the frozen ledger contract. The ordering fix can reuse the batch’s durable workflow state with predecessor-keyed facts; it does not require a new ledger operation.

Read-only review; no files changed and no tests run.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–3 | Revision 6 specifies barrier generations, predecessor-keyed facts, and bounded-backoff worker preparation outside model slots. Fresh review and implementation remain pending. |
