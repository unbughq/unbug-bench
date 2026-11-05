# Admission decision queue design review 5

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — revision 5 is not yet ready for the guarded first increment.** Two bootstrap defects affect restart safety.

1. **Blocker — the PostgreSQL allowlist rejects a normal DBOS database.**  
   [Queue design, lines 301–313](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:301) omits `dbos.event_dispatch_kv`. DBOS 3.4.0 creates that table in its first PostgreSQL migration and does not drop it. A successfully initialized database therefore fails the specified marked-restart inspection. The SQLite migration does not create this table.

   Add it to the PostgreSQL allowlist and test a fresh initialization followed by a marked restart, as well as interruption after the first migration.

2. **Blocker — the accepted migration states include schemas DBOS cannot repair.**  
   [Queue design, lines 314–324](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:314) permits a subset of DBOS tables at every recorded migration version through 125. For example, a marked database at version 125 with `operation_outputs` missing passes that rule, but DBOS skips migrations already recorded as applied; it will not recreate the table before workflows need it. DBOS 3.4 applies SQLite initialization migrations in one transaction, so that example is not an interrupted SQLite initialization.

   Define and validate the objects and columns required by the recorded migration state. Account for PostgreSQL’s per-migration commits and interrupted online-index operations. Test that a marked version-125 database missing a core table is refused before DBOS or a mutating seam is constructed.

The previous SEAL blocker is addressed: the reconciler must now obtain the batch’s durable acknowledgement that the authenticated seal and target count are recorded before closing its fence. The earlier ADMIT recovery, counter, grant handoff, message-key, non-FIFO join, preparation-token, release-boundary, and exact-lease quarantine provisions are also specified. Their fault-injection tests remain to be implemented.

The mandatory bootstrap now precedes the eager ledger and key-service constructors, and its exclusive-control requirement correctly acknowledges that an old engine cannot be fenced by the new lock. The WP2 uncertain-create issue remains a prerequisite for real Boat use. Quarantining an unresolved worker or synchronous operation is a documented safety choice, with a possible availability cost.

After correcting the two bootstrap findings and obtaining a fresh design review, the **disabled, disposable-database first increment can proceed**. Production enablement still requires the specified disposable PostgreSQL verification, recovery exams, and WP2 integration proof. The reported SQLite primitive smoke proves transaction rollback only; it does not prove the bootstrap.

Read-only review. No files were changed, no tests were run, and no production database was accessed.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–2 | Revision 6 adds PostgreSQL's `event_dispatch_kv` and version-specific SQLite/PostgreSQL schema-state validation. Fresh review and implementation remain pending. |
