# Admission decision queue design review 10

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL on the full revision 10 design; PASS for the disabled, test-only checkpoint 1 design.** This does not approve the checkpoint 1 code or the WP8 production rollout.

1. **Blocker — no response is defined when the terminal attempt never dispatched.** The reconciler can prove a grant was unstarted and zero-settle it, but the still-live case waits for an authenticated `StepResult` that does not exist. The ADMIT fence also requires a recoverable action before closing. This can leave the case and batch waiting despite proven absence of execution. [Queue design: recovery]( /private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:141)

   **Fix:** Define an operation-keyed no-dispatch response and the case’s continuation, including grant settlement or reuse, attempt/key handling, fence and lease resolution, and preservation of the already-recorded admission decision. Test child failure before dispatch and around zero-settlement; prove the case progresses without reusing a settled key.

2. **Blocker — delayed recovery can affect a newer operation.** ADMIT A can have its registry applied and fence closed, then fail before returning to its case. ADMIT B can advance the registry before A’s reaper runs. The design requires recovery to apply A’s decision, but only explicitly prevents a stale message from *closing* another fence; it does not prevent A’s registry from overwriting B’s. [Queue design: fence]( /private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:96), [recovered decision]( /private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:151)

   A new reaper generation also uses a new send key, so a response already consumed by the case can be delivered again. The design does not require the case to reject a stale response for an earlier operation. [Queue design: message keys]( /private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:325)

   **Fix:** Record applied decisions by operation and skip reapplying a closed operation while still redelivering its result to the case. Correlate and deduplicate case responses by operation and attempt across reaper generations. Test A’s failure after acknowledgement, B’s successful registry update, delayed recovery of A, and a duplicate A response arriving while the case waits for a later attempt.

Revision 10 addresses review 9’s two stated scenarios: it specifies the authenticated-result handoff, non-OK registry retention and terminal-case fallback, and records exact acquisition inputs before requiring quiescence and idempotent recovery. The parent’s old-journal wording and cross-package test order are also corrected. WP2’s acquisition guarantee and the WP8 rollout gate remain prerequisites for real use.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–2 | Revision 11 defines no-dispatch continuation, applied-operation deduplication and stable recovery-response identity, with the requested fault tests. Fresh review and implementation remain pending. |
