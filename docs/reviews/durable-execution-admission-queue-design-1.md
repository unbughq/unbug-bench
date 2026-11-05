# Admission decision queue design review 1

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — the queue is a promising simplification, but the design is not ready for a meaningful disabled implementation increment.** The serialized decision queue removes the overlapping terminal-barrier fairness protocol and gives a clear normal-path ordering for probes, ADMIT, and SEAL. Its remaining gaps affect grant ownership, recovery, capacity, and decisions that the first increment would have to encode.

1. **Blocker — the first-ADMIT preparation limit is not durable.**  
   `docs/designs/durable-execution-admission-queue.md:109–118`

   A DBOS queue with concurrency 1 limits running workflows, not live leases. If its holder acquires a worker and then enters ERROR or CANCELLED before its first terminal workflow completes, the queue slot can be released while that worker or an already-enqueued terminal child remains unresolved. The next holder can acquire another worker, violating the claimed bound of one prepared first-ADMIT worker.

   The design also needs to say explicitly that preparation for other steps does not wait behind a first-ADMIT holder that is waiting for capacity. Otherwise the one-worker cycle from review 6 remains possible.

   **Fix:** Retain a durable preparation token or fence through failure until the first terminal attempt resolves or the acquired lease is confirmed released. Specify how a new holder is admitted and how the token is recovered. Keep other-step preparation independent of this held token. Test ERROR and CANCELLED after lease acquisition and after terminal enqueue, with a one-worker pool, replay, and eventual progress.

2. **Blocker — the first grant has no specified handoff to the pending case.**  
   `durable-execution-admission-queue.md:43–53, 132–148`; `de/wp6-wp7:factory/durable/ledger.py:175–181, 217–225`

   The probe reports to the batch and waits for its acknowledgement, but the design does not say which workflow sends the pending case its attempt number and held key, when the case may prepare, or how duplicate and lost messages are handled. Counting admission before acknowledging the probe does not deliver the grant. Conversely, settling a grant after an ambiguous handoff is unsafe: the ledger returns the original grant even after that key was settled.

   **Fix:** Specify the durable sequence and payloads from reserve and recorded clock through ADMITTED, batch count, keyed permit delivery, worker preparation, and first ADMIT. A case must ignore duplicate permits, use the exact held key, and never run without a permit. Define recovery if the probe fails before or after its result, batch acknowledgement, or permit send. Preserve a recorded admitted decision across deadline, stop, or target changes. Test each boundary, including a backward clock step after WAIT or EXPIRED settlement and proof that no settled key is reused.

3. **Blocker — reconciliation states are goals rather than an executable failure protocol.**  
   `durable-execution-admission-queue.md:72–96`

   The design names a separate reconciler, but does not specify who detects a failed holder and starts it, its deterministic identity, or how it distinguishes a probe from a queued, pending, or running nested dispatch. “No worker execution can still occur” is insufficient for a failed probe: a synchronous reservation step may still be in flight after cancellation, and a recorded grant and clock may require recovery of ADMITTED rather than zero settlement. For a terminal attempt, a cancelled workflow status alone does not prove that an active synchronous step or detached worker stopped.

   **Fix:** Define the trigger and state transitions for the holder and every nested workflow status. Inspect recorded reserve, clock, lease, result, and settlement operations; attach to or cancel queued children without starting another attempt; and require a tombstone, authenticated DONE, or proven death for the exact lease and key before settlement or fence closure. Recover an ADMIT decision and registry or a successful SEAL, including archive and hardness, before closing the matching fence. Unknowns retain the hold and fence while the batch remains responsive. Test cancellation of an enqueued child and of an executing synchronous step, plus failures before and after each recorded operation.

4. **Blocker — replacement ordering and batch termination lose earlier guarantees.**  
   `durable-execution-admission-queue.md:28–49, 98–107`; `factory/durable/engine.py:625–648, 669–688`

   Joining a replacement request with predecessor release in either order is necessary, but the design does not state when the batch may terminate or how it handles a `done` message received before `line_stopped`. DBOS message order is not guaranteed for equal timestamps; the current batch exits when its known cases are done. It can therefore exit before consuming the replacement request. “Selects pending candidates deterministically” also omits the earlier proposal’s replacement-before-original priority and does not define which eligible candidates are selected after a WAIT wake.

   **Fix:** Persist immutable replacement and release facts by predecessor ID, deduplicate them, and define how `done` carries or preserves those facts. Keep the batch alive until cases, cleanup and reconciliation are terminal, readable control messages are drained, and fences are resolved. Specify replacement-before-original selection and deterministic order within each class, as well as diagnosis acknowledgement conditions. Test `done` before request, release before request, duplicate and same-timestamp messages, real settlement and bound-raise wakes, and replay.

5. **Blocker — terminal policy inputs are underspecified at the decision boundary.**  
   `durable-execution-admission-queue.md:63–70`; `factory/durable/policy.py:63–70, 102–117`; `factory/durable/engine.py:394–409`

   The proposal says the terminal workflow computes the action from the case’s **pre-attempt** counters, while the existing policy expects counters including the current result. Passing those counters directly would make the 96th free ADMIT limit sleep instead of producing the required STOP_ADMISSION; infrastructure-retry exhaustion would likewise be delayed. The late-deadline rule also needs a recorded current clock value.

   **Fix:** Specify exactly how the terminal workflow derives post-result infrastructure, spent-limit, free-limit and late-deadline counters from the recorded pre-attempt state and `StepResult`, including when it records `now_step`, before calling `decide` and reporting the outcome. Test the threshold result and the late-deadline interleaving before a following probe.

6. **Blocker — the release check is not pinned to the final dispatch boundary.**  
   `durable-execution-admission-queue.md:54–62, 149–154`; `factory/durable/engine.py:219–226`

   A prepared SEAL can enter the decision queue, then wait for a global model slot. The text requires a current-release comparison but does not unambiguously place it after **both** slots are held. If an implementation checks before waiting for the model slot, a release processed during that wait can let SEAL run under the old passing-gate versions. The current engine reads releases after it has its slots.

   **Fix:** Place the authoritative release read and SEAL-versus-passing-GATES comparison in the model child after it acquires its slot and immediately before dispatch. On mismatch, start no worker, safely settle the unstarted grant, resolve the decision as nonterminal, and rerun GATES. Specify the equivalent latest-plumbing check for other steps and keep ADMIT’s latest registry read inside the decision queue. Test release changes before preparation, while waiting on the decision queue, and while holding the decision queue but waiting for a model slot.

7. **Blocker — the disabled phase and reporting changes still require design choices.**  
   `durable-execution-admission-queue.md:130–162`; `factory/durable/report.py:18–20, 42–48, 104–120`

   The first phase asks for pending workflows, status fields, IDs, deduplication, and release joins without naming the files, data and message shapes, feature-switch location, or replay behavior for existing workflows. The parent design requires workflow changes behind `DBOS.patch()`. The current report rejects the new statuses and overlays a failed workflow with `engine_error`; its sealed total counts only `sealed` statuses. It also hides worker-creation reasons unless they are on WP4’s published allowlist, contrary to the promised operator view.

   **Fix:** Give a file-by-file first increment, its switch and patch behavior, exact status and message records, and named tests with assertions. Define how a known seal remains counted when cleanup fails, and coordinate safe publication of the fixed worker-creation reasons with the allowlist owner. State which tests can exercise the disabled path while the existing path remains the default. Gate any real WP2 use on fixing or proving its uncertain-create path; the current code clears an intent after an inventory miss and may issue another nonce (`de/wp2:factory/durable/workers.py:379–403, 485–510`).

**What the proposal covers:** It explicitly keeps the batch event loop from waiting on the decision queue, orders normal terminal results before acknowledgement, suppresses probe self-wakes, preserves positive sub-minimum `NOTHING` grants, retains admitted grants and authenticated seals after the target, and calls out WP2’s uncertain-create dependency. The reported local DBOS smoke supports normal-path queue nesting and acknowledgement mechanics; it does not establish failure or replay correctness.

**Major, nonblocking documentation gap:** The queue design should reference the applicable parent cost and timeline estimates and state the expected incremental effort or its uncertainty. Its serial SEAL tradeoff is candidly documented, but actual duration remains unmeasured.

A strictly inert scaffold could be written, but it would not establish the proposed admission increment. Resolve the blockers and obtain another fresh design review before implementing that increment. No files were changed and no tests were run for this review.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–7 and documentation | Revision 2 specifies the token, handoff, reconciliation, ordering, counters, release boundary and phased implementation. Further findings in design review 2 remain open. |
