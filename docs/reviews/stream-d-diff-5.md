# Stream D diff review 5: `515a6d4..ae17d0d` (HEAD)

**Verdict: PASS.** B1⁗ is fixed at its root and nothing blocks. The saved-card migration is exact and does not hide any change. There are four optional nits.

## Method

- I read the `zoom_out` and `implementation_readiness` personas and `implementation-readiness-standard.md`.
- I read `ENGINEERING.md` and all of `stream-d-diff-4.md`, including its response.
- I read the full `515a6d4..ae17d0d` diff: `budget.py`, both test files and the `stream-d.md` addition. I also read `_settle_leaf`, `reclassify_factory_bug` and the `case_spending` validator in full, not only the hunk.
- I ran only `tests.factory.test_stream_d` and `tests.factory.test_saved_recovery_decisions`: 23 tests, OK. I did not run the full suite, make edits, run git writes, launch anything, decrypt anything or read credentials. The probes are in the scratchpad.

## B1⁗: verified fixed

- **Predicates now match.** The extension at `budget.py:246-251` builds `rows` from operation rows with `state == 'settled'`. The validator at `budget.py:383` requires `set(ids) == {event ids of settled related rows}`. Both use the same set, and the `all(...)` gate is deleted. This is a net deletion, as recommended.
- **The extension is idempotent and monotonic.** `row['event_ids']` only grows through a set union. Settled-to-estimated is refused as `usage_receipt_regressed`. So the settled-row event set never shrinks, and `waste['event_ids']` never empties after `reclassify_factory_bug` accepted it.
- **The new test is a real regression test.** I ran it against `budget.py` from 515a6d4 and it fails. It passes at HEAD. The sequence is L1=$4 classified, L3 pending, L1 grows to $5, then replay gives a delta of 0 and total, waste and ordinary spend of 5, 5 and 0. Settling L3 with $2 gives 7, 7 and 0.
- **A randomised probe found no failures.** I ran 500 seeded trials against the real code, with this set-up:
  - Each trial has 1–2 operations with final leases.
  - Each is classified by `reclassify_factory_bug`, with the amount computed as `usd(sum(event_charge))`.
  - Costs have 1, 9 or 12 decimal places.
  - Then 3–8 random interleaved steps run: new pending lease, growth of a final lease, a non-final estimated settle, a settle to final.

  These checks held in every trial:
  - `total_spent_usd` was never `None` after any step, so there was no `money_wait` trap.
  - `spent_usd` was never negative.
  - After all leases settled, total and waste each equalled the exact round-once sum of every event, within 2e-9.
  - After all leases settled, ordinary spend was exactly 0.
- **No other predicate disagrees.** `reclassify_factory_bug` requires all rows settled, which is correct for first admission. The validator and updater now agree on settled rows. `outstanding_reservations` counts pending rows only and does not touch classification.

## Saved-card migration: verified exact

- The expected snapshot `20261029-recovery-before.json` has `legacy_unattributed` in 40 entries. Exactly three have the value `0`: `6a8a7d`, `cae763` and `055481`. These are the three pinned names. The other 37 are positive and are not touched.
- Each pin is a 64-hex original card hash, and the test asserts it with `assertEqual` before the pop. A different card under the same name therefore fails the test.
- The `.pop('legacy_unattributed')` is wrapped in `assertEqual(..., 0)`, so it fails if the label is missing or non-zero.
- The migration is applied in memory to `expected`, followed by the unchanged `assertEqual(snapshot(), expected)`. Every other field must still match, so any change to an amount or to a recovery, adopter, holder, restart or carry-over decision would fail.
- `git diff 515a6d4..ae17d0d -- tests/factory/fixtures` is empty. Neither the card fixtures nor the frozen before-snapshot is changed.
- The change is correct in kind. A zero label is exactly what the Decimal valuation's `if usd(value)` filter now drops, as the design records for the sub-unit remainder rule. An `assertEqual` on a hash-pinned zero is a precise migration, not a loosening.

## Blockers

None.

## Nits (optional)

- **N1. Estimated-lease path not pinned.** The new test covers growth of a final lease while another lease is pending. It does not cover a non-final (estimated) lease under a classified operation, whose booked events must stay ordinary spend until it settles. My probe covers that path and it holds. One extra assertion would pin it.
- **N2. Silent no-op in the migration loop.** If a pinned name were missing from `expected`, the loop skips it. The final `assertEqual` still catches it, because `snapshot()` would then carry a label that `expected` lacks. A one-line assertion that all three pins were seen would make the failure message clearer.
- **N3. Float equality in tests.** The new test compares `total_spent_usd` with `assertEqual` on floats. It is safe because both sides round the same Decimal. This is diff-4 N5 again.
- **N4. Diff-4 nits still open.** Diff-4 N1–N4 are unchanged: dead derived input, coordinator float, `case_spending` raising on 27-decade spans, and aggregate drift. The response gives a reason for N1. The coordinator rule (round once with `usd`) is now recorded in `stream-d.md`. The rest stay optional.

## Test adequacy

- **Covered:** B1⁗ regression, including the 4→5 growth and the replay delta of 0. Three pinned zero-label cards. The earlier tests are retained.
- **Not claimed and not required:** Murphy rows. No closure is claimed, and none should be until increment 2 (M3, M5, M7 and the short concurrent accountant). The design records these as obligations.
- **Docs:** the `stream-d.md` addition matches the code and the tests, and makes no claim beyond them.

## Required before merge

1. Save this review verbatim as `docs/reviews/stream-d-diff-5.md`, with the elephant response and a fixed/rejected ledger below it. I have not written it. The ledger can read: B1⁗ was fixed in `ae17d0d` and verified here, no finding was rejected, and the nits are optional.
2. The full suite must be green before merge, per `ENGINEERING.md` step 4. You report the third run is in progress. I have not verified it.

## Elephant response

B1⁗ was fixed in ae17d0d and independently verified here. No finding was
rejected. The remaining nits are optional and retained as such. No Murphy row
is closed by this additive increment. The mandatory full suite is still running;
its final result will be recorded before the increment is handed off. No merge,
launch or decryption was performed.

## Validation

`uv run --with numpy --with scipy python -B tests/run.py` completed on the
reviewed accounting tree: **135 scripts, 0 failed**. PYTHONUNBUFFERED=1 was set
only to expose progress. Focused accounting: 17 tests; saved-card compatibility:
6 tests. Original public artifacts and the frozen baseline are unchanged.
The prior full run's isolated fake deletion-receipt timeout did not reproduce:
its unchanged dedicated suite passed in 392.3s, then the complete suite passed.
All blocking findings are fixed and independently verified; no row is closed.

