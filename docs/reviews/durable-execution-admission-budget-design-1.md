# Admission budget design review 1

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — seven blocking findings.**

1. **Deadline checks are not safe across replay.**  
   `docs/designs/durable-execution-admission-budget.md:16–24, 27–30` says a crash between reservation and case start replays the recorded steps and that no case starts after the deadline. The current `admission_open()` reads time through a recorded `now_step` (`factory/durable/engine.py:581–583`). If that check and the reservation happen before the deadline, then the process crashes before creating the case, recovery after the deadline replays the old time and can start the case late. A slow reservation creates a similar window without a crash. Specify an authoritative start decision that checks the deadline at the actual creation boundary, including recovery, and releases a grant only when no case can still use it. Test a kill after reservation with recovery after the deadline.

2. **Grant ownership and cleanup are not defined.**  
   The proposed batch-to-case handoff (`admission-budget.md:16–24, 32–33`) must distinguish a case definitely not created from one whose creation succeeded but whose acknowledgment was lost. WP6’s `SqlLedger.reserve` returns the original grant for an existing key even when that row has already been settled (`de/wp6-wp7:factory/durable/ledger.py:175–181`). If the batch zero-settles an apparently unused grant while a case is queued, its ADMIT can re-reserve the same key, receive the old grant, and start without a hold. Another case can spend the released money; subsequent settlement then fails as different from the zero settlement. The current failed-case path also marks a case `engine_error` without resolving such a hold (`engine.py:659–661`). Define durable ownership and recovery for each boundary: reservation, ambiguous case creation, queued attempt, and attempted worker start. Zero-settle only with proof that no attempt can use the grant; otherwise attach to the existing case or settle confirmed usage/loss through the established rules. Test crashes and failures on both sides of the handoff.

3. **Stop and target events can race a pending admission.**  
   `admission-budget.md:26–30` does not define how pending starts are ordered against a STOP_ADMISSION or the seal that reaches the target. The attempt workflow sends `settled` before its case sends either `stop_admission` or `done` (`engine.py:225–227, 433–437, 556–565`). A batch reacting immediately to that settlement can reserve and start a pending case while the stop or final seal is already being reported. A stop can also arrive while the batch is waiting for its reservation call. Define the authoritative ordering between terminal case outcomes and the case-start decision, and test both the final-SEAL and STOP_ADMISSION interleavings, including an event arriving during reservation.

4. **Insufficient probes can generate their own wakeups.**  
   `admission-budget.md:18–20, 26–27` says an insufficient probe is settled and every settlement retries pending work. The existing insufficient-grant path sends a `settled` message after releasing its grant (`engine.py:205–210`). Applying that notification rule to the new probe makes zero budget produce a loop: probe, settle, wake, probe with a new key. This can grow the ledger and journal indefinitely without new money. Specify how probe settlements are excluded from, or deduplicated in, admission wakeups while preserving wakes for real settlements and bound raises. Test multiple pending candidates with no external event and verify that only the intended timeout causes another probe.

5. **Replacement and diagnosis ordering conflicts with the stated guarantee.**  
   `admission-budget.md:26–33` says pending originals and replacements are processed in order and that a replacement never waits on diagnosis. In the current case workflow, `line_stopped` is sent and the case immediately proceeds to diagnosis; diagnosis can reserve the available batch money before the batch processes that message. The replacement then receives a sub-minimum grant until the diagnosis settles. Pending originals can also take newly available money ahead of a replacement. Define the arbitration among pending originals, replacements, and already-started cases competing for the bound, reconciling it with `docs/ENGINEERING.md:114–116`. Test the race with money sufficient for only one reservation, and demonstrate that existing cases are not indefinitely starved.

6. **“Usable grant” leaves a valid zero-case-budget input unresolved.**  
   `BatchSpec` permits `case_money_usd_micros=0` (`contract.py:371–373`). With a positive batch balance, the first ADMIT requests zero and WP6 returns `Grant(0, NOTHING)`; current `decide_grant` allows every NOTHING grant (`policy.py:150–163`). Thus the proposal’s “only with a usable grant” does not say whether this case starts, stops, or remains pending, and raising the batch bound cannot change its case limit. Specify the behavior for zero and sub-minimum fully granted requests without changing the frozen contract, and test those inputs separately from a zero *batch* bound.

7. **The implementation and verification steps are underspecified.**  
   The note gives behavioral goals but no file-change list, durable pending-state and candidate-ID rules, exact handoff/cleanup transitions, or incremental implementation checkpoints required by `implementation-readiness-standard.md`. Its tests do not cover the boundary interleavings above. Add those decisions and name the test files and assertions. The required Heilmeier review also needs the incremental cost, risks, and timeline, or explicit references to the applicable parent-design estimates.

A smaller implementation path is supported by the existing seams: have the batch process one pending admission at a time, reuse `reserve_step` and `release_unstarted_step`, and use the deterministic case ID to reconcile an ambiguous creation with `DBOS.get_workflow_status`/`retrieve_workflow`. This avoids a new balance API or separate reservation service, but still requires the ownership, cutoff, wakeup, and arbitration rules above.

Read-only review; no files changed and no tests run.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1 | A second goldfish from a different model family accepted the recorded admission cutoff; see design review 2 and revision 3. |
| 2–7 | Revision 3 proposes ownership, ordering, wakeup and arbitration rules; fresh design review and implementation remain pending. |
