# Goldfish design review 5 (Codex): stream D item 3, money cleanup

Reviewer: Codex `gpt-6.1-sol`, high reasoning effort, through T3
`delegate_task`. Fresh context, read-only, a different model family from the
writer (Claude), against 45bce00. Final report below, verbatim.

---

**Verdict: FAIL.** Mode: REVIEW. Reviewed the committed design at `45bce00`; drafts were read only for buildability. No files changed and no tests run.

**Blockers**

- **B1 — The non-final monotonic rule does not cover late, already-booked events.** `docs/designs/stream-d.md:1901`; draft `factory/budget.py:268` and `:299`. Consider a reservation estimated at $10 with no recorded event IDs. A late $8 event is already in the ledger, correctly tagged with its lease/invocation, but absent from the reservation’s `event_ids`. This binding is accepted by `_bound_events`. Before settlement, the total includes $8 plus the $10 gap. `_settle_leaf` discovers the event through `before_ids`, but calculates `booked_before` from the narrower `row['event_ids']`. A non-final replay therefore reduces the gap to $2 and the total from $18 to $10, without reconciliation provenance. `batch_accounting.collection_facts` can reject that decrease. Define the late-booking invariant and accounting transition explicitly; either handle this accepted state or reject it before booking.

  The ordinary receipt-import path works: events imported atomically by `_settle_leaf` replace part of the gap while preserving the charged total. The unchanged-event stale-snapshot test does not establish the broader claim.

**Majors**

- **M1 — A legitimate final receipt can remain unable to clear a collection incident.** `factory/batch_holder.py:410`; draft `factory/budget.py:305`; `docs/designs/stream-d.md:1909`. `_extends` requires a `reconciled_decreases` record whenever an estimated reservation becomes settled. The producer emits that record only for a positive release. Scenario: a refused generation contains an estimated reservation whose gap is zero because all gate spend is already booked; a subsequent final receipt confirms exactly that charge. Settlement correctly emits no decrease record, but `_extends` rejects the repaired generation, leaving `accounting_refused`. Specify and test equal-charge finalization through the holder’s incident-recovery path.

- **M2 — Row 21’s proof remains incomplete.** `tests/factory/test_stream_d_runtime.py:394`. The new test replays a lower snapshot through `complete_invocation` and reconciliation with unchanged events. It does not exercise the late-booked-event transition above or provider-wait `settle()` replay for this new rule. Add those transitions on the saved ledger, including collection validation.

**Nits**

- **N1 — Test-module closure documentation is stale.** `tests/factory/test_stream_d_runtime.py:6`. It says only writer-continuation tests close a row; the new design claims rows 8 and 21. Update it when recording closure.

**Round-4 fixes and artifact assessment**

B1’s real-maxima admission correction holds by inspection: both routes use real maxima, with an explicitly authored $100 ordinary envelope. N1’s superseded annotation holds at `docs/designs/stream-d.md:2053`. M1’s unchanged-event stale replay is implemented, but its universal claim fails as described above.

Row 8 has credible saved-artifact coverage for batch jobs: retained practice bytes and the captured 5813be ledger pass through the real accountant, with binding migration checked. Row 21 has substantial saved-artifact coverage, but should remain open pending the settlement cases above. Neither assessment substitutes for running tests.

**Files read**

- `docs/ENGINEERING.md`, `docs/murphy-register.md`, committed `docs/designs/stream-d.md`; money-design reviews 1, 2, 3-Claude and 4-Codex.
- All three requested persona files; Heilmeier, implementation-readiness and zoom-out standards.
- `factory/{budget,model_call_gate,model_runtime,run,diagnosis,batch_holder,batch_accounting,batch,token_prices}.py`.
- `tests/factory/{test_stream_d_runtime,test_stream_d_projection,test_stream_d,test_batch_accounting,test_stream_d_coverage}.py`.

---

## Elephant response

Every finding is accepted and fixed. Nothing was rejected.

- **B1, fixed.** `_settle_leaf` computes `booked_before` over every event
  already bound to the row: its `event_ids` plus ledger events tagged with
  its lease and invocation. That is the row's current charge, the same set
  `before_ids` already discovers. A non-final replay after a late booking
  keeps the total, and a final receipt's `reconciled_decreases` record uses
  the same `booked_before`, so `released == before + estimate - actual`
  still holds for B's collection check.
- **M1, fixed.** `batch_holder._extends` (B-owned, a three-line change)
  accepts estimated → settled without a `reconciled_decreases` record when
  the settled charge is not lower than the estimated charge. Both charges
  are computed the same way: bound events plus the open estimate. A lower
  settled charge still needs the record, so the decrease rule is unchanged.
- **M2, fixed.** `test_batch_accounting.py::
  test_late_booking_and_wait_replay_never_lower_until_final` runs on the
  saved ledger through provider-wait `settle()`: estimate, late booking,
  stale non-final replay, then a final receipt that lowers, equals or
  raises the charge. Each step passes `collection_facts` against the prior
  facts. `test_batch_holder.py::test_equal_or_higher_final_receipt_clears_incident`
  takes a refused generation with an estimated row through the holder's
  incident recovery with an equal and a higher final charge, and checks
  that a lower settled charge without a record still does not extend.
- **N1, fixed.** The test module docstring names the money tests and the
  rows they close.

Red checks ran on a throwaway worktree at 45bce00 with the drafts and the
new tests. With the old `booked_before`, all three late-booking subtests
fail with `unsupported_decrease`. With the committed `_extends`, both
holder subtests fail with `request_refused`. All pass on the change.

A fresh design review 6 follows.
