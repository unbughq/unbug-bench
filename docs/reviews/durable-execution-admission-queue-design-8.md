# Admission decision queue design review 8: SQLite increment

Fresh read-only goldfish; zoom_out, design_critic, implementation_readiness;
Mode: REVIEW. Verbatim response:

---

**FAIL — revision 8 is not yet ready for checkpoint 1a.** The two findings from review 7 are addressed in the written rules, but three gaps remain in the SQLite guard.

1. **Blocker — the WP6/WP7 schema is not pinned to an identifiable source.** The [design](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:315) requires validation of the “complete pinned WP6/WP7 definition,” but does not identify a commit or provide the definitions. Neither `factory/durable/ledger.py` nor `factory/durable/keys.py` exists in this checkpoint’s checkout. The separate `de/wp6-wp7` branch currently contains them at `4cabb424350229752a7096830fef5cddfe0d7311`, but the design does not pin that revision. An implementer must choose which schema to trust and how to make it available to the isolated test.

   **Resolution required:** Name an immutable schema source and make its full SQLite definitions available independently of runtime imports from the unintegrated branch—for example, a checked-in fixture derived from that commit. Require accepted-restart tests to construct the real-shaped tables from that independent source. When WP6/WP7 are integrated, verify that their actual definitions still match the pinned guard.

2. **Blocker — SQLite restart validation does not check workflow ownership and version.** The [SQLite rule](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:330) validates the DBOS schema and migration version, but the requirement that every `workflow_status` row match the marker’s application and version appears only in the [PostgreSQL paragraph](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:358). A marked SQLite database with a complete v125 schema can therefore contain incompatible workflow rows and still pass the stated SQLite checks. This matters beyond reporting: pinned DBOS 3.4.0 can claim an enqueued row with a null application version when the current version is latest, and its application-name filter includes unclaimed rows.

   **Resolution required:** Apply the workflow-row application and version check to SQLite as well. On disposable marked databases, test mismatched and null application/version values, asserting refusal before any factory runs and unchanged schema and data. Include a valid populated marked restart as a positive case.

3. **Blocker — canonical path hashing does not serialize hard-link aliases.** The [lock protocol](/private/tmp/unbug-durable-execution-review-20261105/docs/designs/durable-execution-admission-queue.md:272) claims canonical paths make cooperating processes use one lock. Two hard links to the same SQLite file have different canonical pathnames and therefore different lock files. Two otherwise cooperating bootstraps can acquire both locks and overlap during seam construction and `DBOS.launch`, after any marker transaction has ended.

   **Resolution required:** Ensure all supported names for one physical database share the initialization lock, including the absent-file creation boundary, or explicitly restrict and enforce a single-path/no-alias precondition. Add a disposable two-process alias test that proves serialization or fixed refusal before any factory runs.

Revision 8 explicitly requires every present durable table to be empty whenever no DBOS object exists, including when all three tables exist. It also requires full durable-table definitions, keys, constraints and required indexes to be validated. The guard contains no fake-service exception. The test for the first rule should explicitly create **all three** tables, populate at least one, remove all DBOS objects, and assert refusal without mutation; that directly exercises review 7’s original failure.

The specified marker transaction, read-only inspection, reinspection, and lock lifetime are otherwise clear, subject to the alias finding. Checkpoint 1a is disabled, uses disposable SQLite tests, is not wired into `Engine`, and expressly rejects PostgreSQL and other backends before an executor or seam factory is called. PostgreSQL implementation and production readiness remain outside this review.

Read-only review. No files were changed, no tests were run, and no database was accessed.

---

## Resolution

| Finding | Disposition |
|---|---|
| 1–3 | The guard proposal is superseded for this un-deployed WP1 scope after independent scope review; its findings are not fixed and remain relevant if WP8 adopts that protocol. WP8 rollout safety remains open. |
