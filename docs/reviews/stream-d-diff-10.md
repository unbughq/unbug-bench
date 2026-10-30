**BLOCKER** on 8b8ece6. One defect in the receipt that `settle()` emits when it replays a wait; everything else in the 3a scope passes. Review text for `docs/reviews/stream-d-diff-10.md`:

---

# Stream D diff review 10 — increment 3a (goldfish, read-only)

**Reviewed:** branch `t3/stream-d-implementation`, worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`, diff `6055678..8b8ece6` (one commit: `8b8ece6 Add D coverage and diagnosis projections with cumulative call telemetry`).
**Scope:** increment 3a only:
- the pure `diagnosis.exhaustion`, `actual_model_work` and `pending_projection`
- `budget.usage_coverage` sharing one raw Decimal valuation with `case_spending`
- `reconciled_decreases`, with final receipts retained by hash and emitted once
- cumulative `max_total_calls` as telemetry for authenticated factory jobs

Extension admission, snapshots, stale-cap/import/scientific migration, B enablement and Murphy row closure belong to 3b or later. None is claimed here.
**Verdict: BLOCKER** (1 Blocker, 2 Nits).

## Blocker

**B1. A replayed wait can emit a `reconciled_decrease` whose `wait_id` names a wait that does not list that lease.**
- **Where:** `factory/budget.py` `settle()`. The `setdefault` line that writes `wait_settlements[identity]` interacts with the new `_settle_leaf(..., wait_id)` record.
- **Contract:** interfaces §8 says `wait_id` is null for crash/late-receipt reconciliation, "otherwise a retained wait_settlements ID naming the same lease". Coverage `wait_ids` likewise come from the wait records that name a lease.
- **What happens:** on a repeat settle of the same wait, `settle()` also picks up other pending or estimated leases that now have a receipt file. Their decrease records get `wait_id=identity`. But `setdefault` keeps the first settle's `lease_ids`, so the wait never lists the new lease.
- **Reproduced:**
  1. Reserve L1 and L2.
  2. `reconcile_reservations` excluding L1, which leaves L2 estimated with a $10 gap.
  3. Settle wait W with a partial L1 receipt. W's `lease_ids` = [L1].
  4. Write a final L2 receipt ($2) and settle W again.
  5. Result: a `reconciled_decrease` for L2 with `wait_id=W` and `released_usd` 8.000000000, while `wait_settlements[W].lease_ids` is still [L1].
- **Impact:** B checks the record's shape, owner and lineage. It gets a record that either breaks the wait/lease invariant (refuse) or carries false provenance. The same root cause hides W from `usage_coverage().wait_ids` for any still-pending lease picked up on replay.
- **Fix:** in `settle()`, merge `lease_ids` on replay (sorted union of the old and current leaves) instead of `setdefault`. Alternatively, emit `wait_id=None` for leaves outside the retained wait record. Add a regression test for the sequence above.

## Nits

**N1. A denied receipt with no reservation row permanently blocks coverage.**
- **Where:** `usage_coverage`, the `wait_settlements` check that every listed lease is in `rows`.
- `_settle_leaf` deliberately accepts a denied, zero-usage, final receipt with no reservation row. `settle()` then records that lease in `wait_settlements`, and `usage_coverage` returns None for that ledger from then on.
- This fails closed, so no money is at risk, but it blocks the conservative resume. Probe: one such denied lease in a wait → coverage None.
- In factory jobs this needs `reserve_invocation` itself to fail, so it is rare. Either keep zero-usage denied leases out of `lease_ids`, or skip unknown leases when building `wait_ids`.

**N2. A leftover `infrastructure_gate.exhausted` marker plus a non-infrastructure `diagnosis_state.stop` gives `replacement_eligible: true`.**
- **Where:** `diagnosis.pending_projection`.
- This matches the clause "a valid diagnosis_state.stop identifies the current exhaustion", and the test covers it on purpose (the fresh ID wins). But §8 also says that when the infrastructure helper triggers, `stop` is literally `infrastructure_exhausted`.
- So this card shape relies on the 3b runner archiving the old gate marker before a factory-bug resume. Make sure 3b tests that archive step; 3a needs no change.

## Checked and passing

**Diagnosis APIs are pure.**
- No generation reference: `diagnosis.py` reads only the input card plus `recovery.infrastructure_exhausted`.
- Repeated calls leave the card byte-identical, including when `sha256` is added.
- `actual_model_work` is true only for a retained event or an `unpriced_invocations` entry. Bare denied, settled or estimated reservations and crash gaps count as zero work. Cost-0 free events, subscription events and unpriced events count as work. A non-dict entry fails closed to false.

**The parent ruling holds.** `replacement_eligible` exists only inside a PRESENT pending record:
- completed `diagnosis_state` (any outcome) → None
- completed infrastructure diagnosis → None, even though `exhaustion` and `actual_model_work` are both true (tested)
- active extension → None
- malformed `diagnosis_state` → None
- `provider_wait`, `paused`, `ttl_retired`, retired, sealed, G12 pass → None
- a bare `diagnosis_pending` label without a valid pending state → None

`late_defect_needs_ruling` requires integer `builder_rounds >= rounds > 0` and no active history entry (G12 is excluded). `extension_incomplete` requires a completed outcome hash.

**Coverage follows the §8 contract.**
- One-charge rule: `booked_total` = raw total − all once-counted gaps; covered = raw booked + raw remaining gaps, rounded up once. A streamed $3 under a $10 maximum adds exactly $10 (tested).
- Repeated unknown markers fold into one row.
- The unpriced count is compared against the raw marker list length.
- These return None:
  - a marker naming a missing or settled row
  - a duplicate event ID
  - an event claimed by two rows
  - partial or conflicting event metadata (probe: an event with only `invocation_id` → None)
  - a null `maximum_usd`
  - a nonnumeric `infrastructure_kill`
  - a null aggregate cost
- Unknown fields in a reservation row fail closed.
- `case_spending` is a thin wrapper over the same `_spending`, and the shared code adds no tariff of its own.
- Inputs are not mutated.

**Saved ledgers sweep.** I ran `usage_coverage` over all 58 saved cards in the fixture (`beaf4962…`). It returned non-None on every ledger, with covered ≥ `total_spent_usd` and differences only at the nine-place round-up. That includes the legacy unbound-event ledgers 5813be and e15450.

**Decrease receipts.**
- At most one record per invocation, emitted only when the row was estimated with a gap > 0 and a final receipt settles it.
- `released_usd` is computed from the three nine-place strings.
- Nothing is emitted when release rounds to zero, on a sub-nanodollar re-estimate, or when a pending marker settles.
- An unrelated unknown marker does not suppress the record.
- Growing final receipts and replays add no second record.
- `case_spending` ignores both `reconciled_decreases` and `usage_coverage`.
- The retained file under `usage-receipts/final/<sha>.json` is written atomically (fsync of the file and its directory) before the ledger commit. It refuses symlinks and differing bytes at an existing hash, and survives later receipts.
- `release_uninvoked` refuses estimated rows.

**Telemetry.**
- The `total_call_limit` check is skipped only when `job_authority` is a `JobAuthority`. Non-factory and exam paths keep the cap (`test_budget.py:316`).
- Per-invocation `max_calls` still raises `call_limit`.
- The real 5813be (2496), e15450 (1627) and 873d7f (1040) ledgers go past their counts with the original events and totals kept.
- The scorecard shows `model calls: N (telemetry)` for batch cards.

**Tests and evidence.**
- I ran the three test files directly: coverage 8/8, projection 6/6, runtime 20/20 OK. Run through `-m unittest` with file paths they don't load (0.000s errors); run as files they pass.
- The tests disclose authored process envelopes, config and lifecycle markers. No real model or cloud was used.
- The `launch_manifest` worker set adds `factory/diagnosis.py`.
- I did not run the full suite. Its last lines at review time (still running) were OK.

**Scope boundary.** The design's "Increment 3a review boundary" claims no B enablement, route maxima, extension admission, import authority or row closure. The code matches that.

---

My probe script is `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/bcf02b31-d4d4-4370-bb8d-43a01b11d8c3/scratchpad/probe1.py`. I made no repo writes, commits or pushes.

## Elephant resolution

B1 accepted: settlement now unions retained lease IDs with all newly settled reservation-backed leaves on replay. The regression `test_wait_replay_retains_new_lease_provenance` checks the decrease receipt, partial coverage wait IDs, and idempotent replay on a saved ledger.
N1 fixed: unreserved zero-usage denied leaves are excluded from wait lease IDs; `test_unreserved_zero_usage_denial_keeps_coverage_available` proves coverage remains available.
N2 remains a 3b runner obligation; no change to the reviewed current-exhaustion contract. No finding rejected and no Murphy row closed.
