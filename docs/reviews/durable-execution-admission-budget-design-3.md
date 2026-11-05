# Admission budget design review 3

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — six blocking findings.**

1. **The terminal barrier is installed after money becomes available.**  
   `docs/designs/durable-execution-admission-budget.md:67–78`; `factory/durable/engine.py:205–227`.

   The attempt settles the ledger before sending `settled`. If it is paused or the process crashes between those operations, a batch poll or bound raise can run a pending admission using the newly freed money before the batch knows to install the ADMIT or SEAL barrier. A final SEAL or STOP_ADMISSION can therefore be reported only after another admission has been decided.

   **Repair:** Before an ADMIT or SEAL attempt settles, send an attempt-keyed `barrier_open` and wait for the batch’s durable acknowledgement that the barrier is installed. The batch may finish a probe already in progress, but must process the barrier before acknowledging it and must not begin another admission while it is open. Only then may the attempt settle and return its outcome. The case must send the matching terminal or nonterminal resolution before sleeping, waiting for money, or waiting for a replacement acknowledgement. Probe zero-settlements remain exempt. Define whether an event queued during a probe is ordered before or after that probe, and test the chosen ordering. Kill and pause between barrier acknowledgement, ledger settlement, settlement-step recording, and outcome reporting.

2. **Barrier messages cannot safely be matched across attempts or reordered delivery.**  
   `admission-budget.md:70–76`.

   The proposed settlement message carries only case and step, while a case may perform multiple ADMIT or SEAL attempts. A late acknowledgement for one attempt can clear another attempt’s barrier, or an early acknowledgement can be consumed before the matching settlement event and leave an orphaned barrier. This is not safely resolved by assuming FIFO: DBOS 3.4’s `recv_consume` orders messages by millisecond `created_at_epoch_ms` without a tie-break (`dbos/_sys_db.py:4015–4026`).

   **Repair:** Identify each barrier and resolution by the full attempt idempotency key, including sequence and attempt number. Specify idempotent handling for duplicate, stale, early, and missing messages, and preserve unresolved keys across replay. The handshake in finding 1 must establish the matching barrier before that attempt can settle. Test same-timestamp/reordered messages, a stale acknowledgement after a later attempt begins, a case failure before its resolution, and replay at each message boundary.

3. **Failure reconciliation does not specify safe evidence or preserve a completed seal.**  
   `admission-budget.md:56–63, 75`; `engine.py:189–240, 484–496, 556–567, 659–662`.

   “Proof no attempt started” and “must not allow a later execution” are requirements, but the design gives no procedure for obtaining that proof across the case workflow, queued `slot_workflow`, nested ADMIT `attempt_workflow`, and worker. An absent recorded `attempt_step` result does not prove that dispatch did not happen; DBOS cancellation status alone also does not establish that a synchronous step or detached worker stopped.

   There is a separate target failure: a SEAL can succeed and settle, then `release_worker()` can fail before the case reports `done`. Merely reconciling the money, clearing the barrier, and marking the case `engine_error` loses the recorded seal and can permit admissions after the target was actually reached.

   **Repair:** Define a nonblocking reconciliation state machine for each child workflow status and recorded operation. Follow the nested workflow IDs and recorded attempt result; use the worker poll/cancel and tombstone protocol to establish dispatch, usage, and inability to execute again before zero or lost settlement. If that proof cannot be obtained, quarantine the grant and report an error without reopening admission on an unresolved terminal outcome. Recover and count a recorded successful SEAL, including its archive and hardness, before clearing its barrier; similarly recover an ADMIT terminal decision. Test failures before enqueue, while queued, after lease, during uncertain dispatch, after a recorded result, and during worker release after a successful SEAL.

4. **Waiting for replacement acknowledgement can hold a worker and conceal an escalation.**  
   `admission-budget.md:80–88`; `engine.py:302–315, 500–507, 536–541`.

   The existing `stop_line` call precedes worker release and publication of the escalated status. Adding the proposed wait there means a case can retain its Boat worker while a replacement waits for money, potentially until the deadline. With a bounded worker pool, that retained worker can prevent the admitted replacement from obtaining capacity. An actual reviewer disagreement also remains unpublished while the case waits.

   **Repair:** Release the stopped case’s worker before any potentially unbounded acknowledgement wait. Publish escalation or retirement independently of that wait; use the batch’s durable per-case replacement state for deduplication. Preserve the ordering that prevents diagnosis from taking the replacement’s grant. Test a one-worker pool, unavailable then raised budget, and an escalation while the replacement is pending.

5. **The design changes the unconditional replacement guarantee by interpretation.**  
   `admission-budget.md:80–87`; `docs/ENGINEERING.md:110–116`.

   When another case holds the available money, the proposed replacement workflow does not exist until a usable grant becomes available, and the original does not enqueue diagnosis. Calling this a “budget-qualified meaning” does not reconcile it with ENGINEERING’s statement that a replacement launches at once and never waits on diagnosis; ENGINEERING takes precedence over older designs. Workflow creation itself does not require a paid model call.

   **Repair:** Preserve an immediate durable replacement launch or explicitly obtain an authoritative change to that target. One possible design is to create the replacement workflow immediately in a non-paid waiting state, arbitrate its first grant ahead of diagnosis, and start paid ADMIT only with a valid hold. Specify how this interacts with the case limit, stop, target, deadline, replay, and acknowledgement; test temporary exhaustion caused by another case’s hold as well as a bound raise.

6. **The implementation plan and replay tests remain incomplete.**  
   `admission-budget.md:97–114`.

   The file list is an improvement, but the plan still has no incremental, buildable phases as required by the implementation-readiness standard. Its fault points do not explicitly cover the critical crash after WAIT or EXPIRED zero-settlement commits but before that settlement step is recorded. It also names zero case money without the separately requested positive sub-minimum `NOTHING` case.

   **Repair:** Add stable implementation checkpoints and explicit tests for: WAIT and EXPIRED settlement replay, including a backward clock step and a bound raise; the next probe using a new attempt key; positive sub-minimum `NOTHING` versus a tied sub-minimum `BATCH` grant; the barrier, failure, and resource interleavings above; and no reused released grant. State what existing path this change deletes or replaces.

**Prior findings:** Review 1’s accepted deadline interpretation and review 2’s B1 are addressed in the proposal; the separate recorded clock and removal of the workflow-level start retry are sound. Review 1’s self-wake finding is addressed by excluding probe settlements. Its grant-ownership, stop/target ordering, replacement guarantee, and readiness findings remain open as described above. The zero-case-budget behavior is specified, but the positive sub-minimum test is missing.

Read-only review; no files changed and no tests run.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–6 | Revision 4 specifies an attempt-keyed pre-settlement handshake, non-paid replacement workflows, and reconciliation and test states. Fresh review and implementation remain pending. |
