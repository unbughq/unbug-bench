# Admission decision queue design review 2

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — revision 2 resolves several normal-path issues, but recovery and replay are not yet specified safely enough to implement.**

1. **Blocker — admitted grants and preparation tokens can be stranded without an active reaper.**  
   `docs/designs/durable-execution-admission-queue.md:56–66, 107–120, 150–158`

   The batch polls a terminal-fence holder, but an admitted case can fail after receiving its permit and before creating or claiming a preparation workflow. Its grant is held, yet there is neither a terminal fence nor a preparation-token holder to trigger the stated reconciliation. Separately, the design says a failed preparation holder’s reconciler resolves the token, but does not explicitly say who detects and starts that reconciler when no terminal fence exists. It also does not define recovery if a deterministic reconciliation workflow itself ends in ERROR or CANCELLED; attaching to the same completed workflow ID does not restart it.

   **Fix:** Have the batch independently monitor admitted cases, the preparation token, terminal fences, and their reconcilers. Specify how each failed reconciler is resumed or replaced without duplicating side effects. Retain the grant and token until the relevant child chain is resolved; zero-settle only after proving no permit-driven child or in-flight acquisition can execute. Test failure before preparation creation, after token claim, after lease acquisition, after terminal enqueue, and during reconciliation.

2. **Blocker — probe recovery omits the recorded-grant/no-clock boundary.**  
   `durable-execution-admission-queue.md:107–120`; `de/wp6-wp7:factory/durable/ledger.py:166–203`

   The reconstruction rule requires both a recorded reserve and clock result. It does not specify what happens when a probe is cancelled or fails after its reservation is recorded but before its clock read is recorded, or when the reservation committed but its step result was not recorded. These are ordinary crash boundaries and can leave the singleton fence and money held indefinitely.

   **Fix:** Specify the transitions for each boundary. The ledger permits recovery of the original grant by repeating the same idempotent reserve. Once it is safe to proceed, record a new clock decision if none was recorded, or zero-settle only with proof no holder can deliver the grant. Test ERROR and CANCELLED before and after reserve commit and before clock recording, including a still-running synchronous reserve.

3. **Blocker — unknown-usage settlement ordering is contradictory.**  
   `durable-execution-admission-queue.md:123–128`; `factory/durable/executor.py:204–215, 242–248`

   The design first says a recorded result is authenticated and settled, then says a recorded unknown-usage result does not prove the worker stopped. That leaves an implementation able to call `settle_lost` while a detached worker is still live. A later authenticated DONE can then conflict with WP6’s first settlement, and a retry can overlap the original attempt.

   **Fix:** State that **every** unknown-usage result, recorded or synthesized, retains its grant and fence until exact-lease DONE, a confirmed tombstone, or proven worker death. Only then settle actual usage or lost and permit a retry or fence closure. Test a recorded `engine:executor_raised` while the worker remains live, followed by late DONE.

4. **Blocker — message idempotency keys need a phase discriminator.**  
   `durable-execution-admission-queue.md:225–231`

   DBOS 3.4 deduplicates sends by idempotency key and destination, not by message kind or topic. If `open` and the subsequent `probe_result` or `close` use the same key derived only from batch, case, and attempt, the later message is silently dropped and the fence remains open.

   **Fix:** Include message kind and role or phase in every deterministic send key, in addition to the operation identity. Specify the keys for request, result, acknowledgement, and token release; test that distinct messages for one operation are delivered while duplicates of each are ignored.

5. **Blocker — the batch patch does not preserve older WP1 child histories.**  
   `durable-execution-admission-queue.md:179–187`; `factory/durable/engine.py:37–38, 214–265, 349–373`

   The batch-level patch can select the current V1 path, but it cannot repair an independently recovered older case or attempt workflow. Earlier WP1 revisions and current `77f1e6f` share `factory-engine-1` despite changes to workflow operations, the queue topology, and step signatures. The parent’s isolated SQLite experiment restarted a fake-worker journal from `7d09dae` under `77f1e6f`: replay raised `DBOSUnexpectedStepError` for recorded `reserve_step` versus expected `DBOS.getEvent`, and recorded `attempt_workflow` versus expected `slot_workflow`; the case ended as `engine_error`.

   **Fix:** Either establish and document that no journals from those earlier revisions can exist at rollout, or preserve versioned legacy child workflows and step interfaces with explicit replay routing. Add an upgrade test using an earlier recorded case and an in-flight attempt. The reported minimal `DBOS.patch` smoke verifies the patch boundary only; it does not cover those child histories.

Revision 2 does specify the successful grant handoff, replacement-first selection, predecessor-fact join, post-result counters, final-slot release comparison, and retention of authenticated seals. Independent preparation for non-first steps addresses the previously identified one-worker cycle on the normal path. Those provisions still need their proposed fault-injection tests. The WP2 uncertain-create finding is correctly identified as a prerequisite, but remains unresolved until WP2 fixes or proves that path before real Boat use.

**Minor documentation:** In the parent design, change “cases … already running” at `docs/designs/durable-execution.md:190–191` to include already-admitted cases whose execution has not begun. Clarify that a known authenticated seal remains reported as `sealed` with a cleanup error, consistent with the proposed report test.

The serialized decision queue is materially simpler than the earlier overlapping barrier-generation protocol. I found no smaller complete alternative that preserves the frozen ledger contract and the same failure guarantees.

Read-only review. I made no changes and ran no tests; the cross-version experiment above was reported by the parent.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–5 and parent wording | Revision 3 specifies independent monitors, probe replay boundaries, exact-lease settlement proof, phase-specific send keys, an old-journal startup guard, and the target wording. Fresh review and implementation remain pending. |
