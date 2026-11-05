# WP1 disabled admission bookkeeping diff review 1

Fresh read-only goldfish; zoom_out and implementation_readiness; Mode: REVIEW.
Reviewed checkpoint commit `62deb9a`. Verbatim response:

---

**Review: blockers remain in checkpoint 1.**

- **Blocker — failed cards can break the public scorecard.** [report.py](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/report.py:72) permits `cleanup_error` only on a sealed card, but `load_cards` changes every failed workflow’s card to `engine_error` without removing that field. Rendering such a card raises `ContractError` for the whole scorecard. The loader also lacks a way to distinguish a recorded, verified seal from an unverified stale card. Preserve a seal only with independent recorded evidence; otherwise overlay `engine_error` and remove `cleanup_error`. Test both paths through `load_cards` and `scorecard`. This does not require implementing the later reconciliation workflow.

- **Blocker — the required V2 ordering test bypasses DBOS.** [test_durable_admission_bookkeeping.py](/private/tmp/unbug-durable-execution-review-20261105/tests/factory/test_durable_admission_bookkeeping.py:29) manually marks a case admitted and calls `handle()` directly. Its DBOS test covers a pending case and generic message deduplication, but not predecessor facts through the switched batch workflow, equal-time delivery, or reconstruction after restart. Add a controlled real-DBOS test for request, release, and done ordering and duplicates, including a same-generation restart. Full queue and reconciliation recovery remain later checkpoints.

- **Major — text output hides cleanup failures.** [report.py](/private/tmp/unbug-durable-execution-review-20261105/factory/durable/report.py:95) omits `cleanup_error` from `render_text`, so a sealed case with failed cleanup appears without that fact. Render the flag and test the text output.

The pending case path itself does not dispatch attempts, reserve funds, or create workers, and V1 remains the default. I did not run tests, as requested.

---

## Resolution

| Finding | Disposition |
|---|---|
| Failed-card overlay | Implemented recorded verified-seal evidence, loader validation and a real DBOS cleanup-failure test; fresh verification pending. |
| V2 DBOS ordering | Added switched-workflow ordering, equal-time/duplicate messages and a same-generation kill/restart test; fresh verification pending. |
| Text output | Added cleanup-error text and a rendering test; fresh verification pending. |
