# Admission decision queue design review 4

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — the full queue design has a SEAL recovery ordering gap, and the specified disabled first increment is not yet implementation-ready because its database guard leaves safety-critical choices open.**

1. **Blocker — recovered SEAL must reach the batch before its fence closes.**  
   [Queue design, lines 141–160](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:141) requires a recovered successful SEAL to retain its archive and `hard` value and count toward the target. It does not require the batch to record that seal and update the target **before** the reconciler closes the fence. The explicit before-close rule at lines 151–155 covers ADMIT.

   If a SEAL succeeds and settles but its holder fails before reporting, a reconciler could close the fence first. A waiting probe could then be authorized using the old sealed count and admit a case after the target should have been reached.

   **Fix:** Require the reconciler to deliver the authenticated seal, archive, and `hard` value to the batch and receive a durable acknowledgement that the seal and target count are recorded before closing its fence. Add a failure-after-settlement/before-report test at target one, with a queued probe; assert the probe cannot reserve and is refused once the recovered seal is applied.

2. **Blocker — the first checkpoint’s guard is specified by invariants but not an executable database protocol.**  
   [Queue design, lines 226–266](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:226) correctly requires a pre-seam guard, transactional marker, serialized initialization, fail-closed inspection, and exclusive control of the new database. It leaves the implementer to choose the PostgreSQL and SQLite locking protocols, marker schema and values, new DBOS application version, and the allowed database objects or partial setup states. Those choices determine whether concurrent bootstraps coordinate and whether restart after interrupted initialization is accepted safely. This is a readiness gap, not evidence that the stated invariants are inherently unsafe.

   **Fix:** Specify the lock and its scope for each supported backend, including reinspection while holding it; the marker record and pinned application version; and exactly which objects and partial initialization states a marked restart accepts. Keep the existing schema-and-data preservation and crash-boundary tests, and verify the PostgreSQL protocol against a disposable database before enabling the production path. The isolated SQLite transaction smoke reported by the parent supports the transaction primitive only; it does not validate the bootstrap or PostgreSQL behavior.

Revision 4 addresses the previous guard finding **in principle**: it places the check before DBOS, the eager `SqlLedger` and `AgeKeyService` constructors, refuses unmarked partial databases, and states the exclusive-new-database assumption. It also explicitly recovers ADMIT’s action, counters, and registry before fence closure. Refusing old journals avoids claiming cross-version recovery; the requirement for future patches to cover independently recovered children remains explicit.

The first-ADMIT preparation token, independent preparation for other steps, and quarantine of uncertain workers describe a conservative safety limit; I found no additional demonstrated queue or worker deadlock in the written protocol. The WP2 uncertain-create path remains an acknowledged prerequisite for real Boat use, not a proven fix. These are design provisions awaiting implementation and fault-injection tests.

Read-only review; no files were changed and no tests or production database operations were run.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–2 | Revision 5 specifies seal-before-fence acknowledgement, backend locks, marker identity, object allowlists and interrupted-init states. Fresh review and implementation remain pending. |
