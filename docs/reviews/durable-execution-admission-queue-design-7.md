# Admission decision queue design review 7: SQLite increment

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — checkpoint 1a needs two SQLite guard corrections before implementation.** Both findings concern the requested fail-closed primitive; this review does not assess PostgreSQL production readiness.

1. **Blocker — a populated durable database can be mistaken for an uninitialized one.** The [design](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:315) requires durable tables to be empty before DBOS exists only when the table set is incomplete. If all three durable tables remain populated but every DBOS object has been lost, the [SQLite rule](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:327) accepts the database as an interrupted initialization. A subsequent launch could recreate an empty DBOS journal and lose the workflow history.

   Require **every present durable table to be empty whenever no DBOS object exists**, whether the durable-table set is complete or incomplete. Specify that bootstrap constructors create tables but do not write durable data before DBOS initialization. Test a marked, populated database with all DBOS objects removed and verify refusal before any factory runs, with schema and data unchanged.

2. **Blocker — the durable-table validation omits essential constraints.** The [design](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:315) requires checking columns and types, but not the pinned WP6/WP7 primary keys, foreign key, nullability, and other constraints. For example, `durable_scope_key` could retain the expected columns and types while losing its `scope` primary key. `AgeKeyService` relies on that key to resolve concurrent first creation; its `create_all` constructor does not repair a present table. Duplicate scope rows can make previously encrypted artifacts inaccessible on restart. Ledger idempotency likewise depends on its primary keys.

   Validate the complete pinned SQLite table definitions and required indexes and constraints, not just column names and types. Add refusal tests for missing or altered primary keys, foreign keys, nullability, and required indexes; check that no factory runs and that schema and data remain unchanged.

The correction requested by review 6 **is present**: an incomplete durable-table set is refused once any DBOS object exists, and PostgreSQL is rejected before an executor or seam factory is called. The specified SQLite marker transaction, flock lifetime, independent DBOS-v125 snapshot, old-journal refusal, and fixed-error tests provide a suitable basis for the isolated increment once the two gaps above are corrected.

WP1’s fake ledger is file-backed and its fake keys do not create WP6/WP7 tables. Its old journal remains appropriate for the refusal regression. For accepted marked-restart tests, create all three real-shaped durable tables in the disposable database before initializing DBOS; do not weaken the guard for fakes.

Read-only review. No files were changed, no tests were run, and no database was accessed.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–2 | Revision 8 requires all pre-DBOS durable tables to be empty and validates pinned keys, constraints and indexes. Fresh verification remains pending. |
