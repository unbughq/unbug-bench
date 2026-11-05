# WP1 simpler recovery design review 1

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**Recommendation: narrow WP1’s recovery scope, but do not treat it as an approval of the current package.** A fail-closed response to an unexpected terminal DBOS `ERROR` or `CANCELLED` can be an appreciably smaller design than revision 11’s reaper and recovered-result delivery. It can be acceptable for an unpublished WP1 using disposable databases if the revised design explicitly records that the affected case—and potentially admission for the batch—may remain blocked indefinitely.

That concession falls short of the approved parent design’s broad goal that only a reviewer disagreement reaches the founder. It does not inherently change a founder-set section 4 rule: [ENGINEERING.md](/private/tmp/unbug-durable-execution-review-20261105/docs/ENGINEERING.md:104) calls unattended completion a target property. The narrower design still needs a fresh independent design review and diff review, and any rejected blocking finding needs the different-model-family adjudication prescribed by section 1. Revision 11 is proposed, not approved.

The boundary must be strict: **ordinary worker death, control-process kill or restart, transport interruption, and real provider limits remain automatic paths**. A workflow reaching terminal `ERROR` is not the same as a process being killed and replayed. Known worker and provider failures must become normal outcomes; replay must retain attempt identity and reconcile the original worker. A cancelled workflow, missing lease or context, failed pool call, or elapsed deadline does not prove a synchronous operation or detached worker stopped.

For an unexpected terminal error, the batch must detect and visibly report the affected case, retain any uncertain grant and preparation or decision fence, and prevent a conflicting dispatch. It may continue unrelated safe work. A terminal decision not yet durably applied must keep its fence; an authenticated seal already accepted by the batch remains sealed with a separate cleanup error. This can hold budget and capacity, and it is not automatic completion.

The proposal changes the disposition of prior findings as follows:

- Queue review 9 finding 1 and review 10 finding 1 **are not fixed**: the case will not continue from a recovered ADMIT or proven no-dispatch result. They become explicit liveness concessions requiring review, not “resolved” findings.
- Quarantine can address the **safety** part of queue review 9 finding 2 by retaining an uncertain acquisition token, but it does not recover the worker or provide the requested eventual progress. Removing automatic recovered-result delivery removes review 10 finding 2’s reaper-redelivery scenario; normal replay and duplicate messages still require operation-keyed, idempotent decision handling.
- WP1 diff review 1 findings 4–5 and review 2 findings 4 and 6 remain mandatory: a normal transport failure or replay must reconcile the exact worker, retain a late valid result and its spending, and never use cancellation or time as proof of death. Both reviews’ pool-failure finding 3 still needs safe normal retry and settlement; quarantine alone does not fix it.
- Budget-aware admission, target and STOP ordering, immediate replacements, output authentication, global concurrency, cleanup, and accurate seal reporting remain independently open or subject to verification. In particular, WP1 diff review 1 finding 7 and review 2 finding 9 are not solved by quarantining errors.

There is also a separate section 4 conflict: [policy.py](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/policy.py:102) gives up after 96 zero-spend provider limits **regardless of reason**, including genuine quota limits. On ADMIT this stops admission. The handoff requests that cap to catch missing credentials, but [ENGINEERING.md](/private/tmp/unbug-durable-execution-review-20261105/docs/ENGINEERING.md:151) says a capacity limit never stops or shrinks the plan. Distinguish the configuration failure or remove the generic cutoff; test a genuine limit beyond 96 responses.

The minimum fault evidence for the narrower design is:

1. The required three-case, 20-`SIGKILL` DBOS exam, including reserve, dispatch, settlement and decision/ack boundaries: same-generation replay completes without repeating a finished paid step or overlapping ADMIT.
2. Confirmed worker death settles unknown usage as waste and retries from the snapshot. Lost transport or cancellation with a live worker retains the grant and accepts a late authenticated result without a competing attempt.
3. Provider-limit sleep survives restart and eventually progresses, including more than 96 genuine zero-spend limits. Known pool failures follow normal retry; uncertain creation retains its token and identity.
4. Actual DBOS `ERROR` and `CANCELLED` at reserve, preparation, dispatch, settlement and acknowledgement boundaries—including a synchronous operation that continues after cancellation—leave ambiguous grants and fences held and visibly report the blocked case.
5. ADMIT, STOP and SEAL decision-boundary tests prove no later probe passes an unresolved decision, applied registry/stop/target updates are idempotent, and a verified seal remains counted after cleanup failure.
6. A one-worker replacement/diagnosis test and reordered, duplicated predecessor messages prove immediate replacement bookkeeping, responsiveness and no premature batch completion.

The existing focused tests, exact-head full suite and fresh diff review remain required. Before real use, WP2 must establish uncertain-create idempotence, WP8 must establish and test the fresh-generation database gate, the combined packages need integration testing, and WP9’s live worker-deletion and control-VM-restart exam remains required. Any acceptance of unexpected-terminal-error quarantine at cutover must remain explicit; it cannot be reported as satisfying the broad no-human target.

No files were changed, tests run, databases accessed or network contacted.

---

## Resolution

| Finding | Disposition |
|---|---|
| Narrower exceptional-error recovery | Considered; the current proposal retains its recovery goal rather than treating the liveness findings as fixed by quarantine. |
| Provider-limit conflict | Open; founder choice requested because the handoff and ENGINEERING section 4 give conflicting directions. |
