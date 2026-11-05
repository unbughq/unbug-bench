# Admission decision queue design review 3

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — two blocking findings remain. A disabled first increment, as specified, is not yet safe to implement.** Its first checkpoint includes the startup guard, which does not yet cover all database mutations. The recovery protocol also leaves a terminal decision ambiguous.

1. **Blocker — the guard runs too late to guarantee that an old database remains unchanged.**  
   [Queue design, lines 220–252](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:220) places the read-only check before DBOS construction and launch. But `Engine` receives an already-constructed executor, and both WP6’s `SqlLedger.__init__` and WP7’s `AgeKeyService.__init__` call `create_all` immediately (`de/wp6-wp7:factory/durable/ledger.py:89–94`; `de/wp6-wp7:factory/durable/keys.py:84–95`). Constructing either seam against an old database can create tables before the guard refuses it. The proposed regression checks rows, not the complete schema. Also, a missing DBOS schema alone does not prove that a database has no existing ledger, keys, or other data.

   **Minimal correction:** Use one mandatory bootstrap before *any* mutating seam or DBOS initialization. Refuse an unmarked database containing user tables or a partial schema; initialize the generation marker only after establishing that the dedicated database is empty. On restart, validate the marker and expected application/version before opening mutating seams. Make marker creation transactional and recoverable after interruption, fail closed on inspection errors, and prevent other startup paths from bypassing the bootstrap. Test that schema **and** data are unchanged on refused databases, including a legacy journal without ledger/key tables and an unmarked database containing only ledger or key data.

   The proposed guarded-bootstrap correction is sufficient in principle if the check and marker initialization are serialized, all cooperating entry points use it, and exclusive control of the new database prevents an old engine—which ignores the marker—from writing between inspection and launch. A missing SQLite path must be inspected without accidentally creating it. Define the marker as a database-generation identity so later compatible code releases can still restart the same database.

2. **Blocker — reconciliation does not require recovery of an ADMIT decision and registry before reopening the queue.**  
   [Queue design, lines 80–89](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:80) requires the normal terminal workflow to derive post-result counters and apply STOP, target, and registry changes before acknowledgement. The failure path at [lines 141–153](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:141) authenticates and settles a recorded result and specifically preserves a successful SEAL, but does not require reconstructing and applying an ADMIT’s decision, counters, and successful registry before closing the fence. If the holder fails after settlement but before reporting, the next probe could be admitted despite a recovered STOP, or the next ADMIT could use the previous registry.

   **Minimal correction:** Recover the recorded pre-attempt inputs, grant, result, relevant clock and post-result counters; derive or recover the same terminal action; then apply STOP or the authenticated updated registry to the batch before closing the matching fence. Quarantine if the action or registry cannot be established. Test failure after settlement and before result reporting for both a threshold STOP and a successful ADMIT, asserting that no later probe passes STOP and the next ADMIT sees the recovered registry.

The five findings from queue review 2 are otherwise addressed in the written design: independent monitoring and non-overlapping reaper generations; reserve/no-clock recovery; exact-lease proof for every unknown-usage result; phase-distinct send keys; and a pre-launch refusal of old workflow journals. The fifth remains incomplete as a **nonmutation** guarantee for the reason above. These are design provisions, not implementation or test results.

The serialized decision queue is a reasonable simplification of the earlier barrier-generation protocol. The separate first-ADMIT preparation token and independent preparation for other steps address the identified one-worker cycle in the stated normal path; the proposed fault tests still need to establish it under recovery. The WP2 uncertain-create issue is accurately identified as a prerequisite for real Boat use. The final model-slot release check, SEAL-versus-GATES version comparison, post-result counters, target grandfathering, and parent target wording are specified.

A fresh dedicated production database can make final V1 deletion simpler: start it only after V2 becomes the default, and prohibit intermediate V1 batches from using that production generation. If any V1 batch can have run in that same generation, retain the V1 replay path until its workflows are definitively finished. The generation marker alone does not distinguish V1 and V2 jobs within the new database. Preserve the parent design’s `DBOS.patch()` requirement for future compatible workflow changes, including independently recovered child workflows; a batch-only patch does not repair old child histories.

Read-only review; no files were changed and no tests or production database operations were run.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–2 | Revision 4 specifies a mandatory pre-seam guarded bootstrap and ADMIT decision/registry recovery. Fresh review and implementation remain pending. |
