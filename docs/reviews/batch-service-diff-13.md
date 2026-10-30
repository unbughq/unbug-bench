**Verdict: PASS.** I found no Blocker or Major issues in commit `6a69978` ("Validate D collection accounting and projection proofs while gated"), reviewed in Mode REVIEW as both the zoom-out and implementation-readiness goldfish.

**Scope I confirmed**
- `git diff 9cb25e6..HEAD` and `git diff cfe616f..HEAD` both show no changes to `factory/budget.py` or `factory/diagnosis.py`. The D code is unchanged.
- I re-ran the focused tests here: `test_batch_accounting` and `test_batch_service_d` (21 tests), `test_batch_service` (12) and `test_launch_manifest` (2). All pass. I did not run the full suite; that stays with the parent.
- `DIAGNOSIS_ENABLED = False` (`factory/batch_service.py:21`). The only caller of `collection_facts` is the tests. Nothing in the commit adds an ACK, holder, source grant or adapter enablement. Of the new code, `batch_service` imports only `card_total`.

**Against Increment2b.2 and interfaces.md §8**
1. **Total normalization.** Totals go through `Decimal(str(v))`, rounded up once to nine places. Bool, negative, NaN, infinite, list and object values are refused. A missing, null or total-less `case_budget` counts as unknown. A non-object block is refused. The card total must equal D's `case_spending` total after the same normalization, null included. A higher-precision card that disagrees with D is refused (tested). B does not sum D's subtotals.
2. **API purity and schema.**
   - `_call` passes D a deep copy of the ledger and refuses if the API changes its input, raises, or returns a non-dict. `accounting_api_refused` is tested with authored API doubles.
   - The coverage result needs exact keys, integer schema 1, canonical money strings and UUID4s, sorted unique invocation rows, unique lease strings and sorted unique `wait_ids`.
   - A `usage_coverage` field stored on the card is ignored (tested).
3. **Reservations.** Rows use exactly D's own key set (matches `budget.py:584-592`) plus an optional `estimated_gap_usd`. Each row's lease must equal its key, the state must be pending, estimated or settled, and invocation IDs must be unique across all rows (a duplicate row is tested).
4. **Decrease receipts.**
   - Exact keys and kind; the digest must be lowercase 64-hex; `wait_id` must be null or a UUID4.
   - `released = before + estimate - actual > 0` is checked exactly in integer nanodollars (`batch_money.amount` returns int).
   - Identity is `invocation_id` alone: identical repeats count once and conflicting ones are refused.
   - Every record must match a settled row. Only then does qualification require the ID in the previous map with `released <= previous gap`.
   - All mutation cases refuse with `malformed_reconciliation`.
5. **The P−R−epsilon rule.** epsilon is `2*len(M)+1` nanodollars, an integer that is in the right unit because amounts are integer nanodollars. It applies to every known-P/known-T comparison. The tests cover the boundary exactly, plus one nanodollar over, with a release, with an empty map, and with a map holding only a zero gap.
6. **Null-only coverage.** `usage_coverage` is called only when T is null; a known T calling it fails the test via a patch. `covered_total_usd` is compared straight to the held amount, and the boundary is tested at exactly held and one nanodollar under. A null maximum and a non-numeric `infrastructure_kill` both refuse.
7. **Overrun.** With P and T both known, T is returned even when it exceeds held. With null P, a known T above held refuses with `uncovered_total`. Both are tested.
8. **Map replacement.** The estimated map is rebuilt from the current estimated rows at every checkpoint, zero gaps and null totals included. The null→null→known chain releases exactly once. An estimate created and released within one run contributes nothing; without its receipt, the same drop refuses as `unsupported_decrease`.
9. **The `batch_service` gate.**
   - The adapter-off check now runs before the stored-facts replay. The disabled stored-replay test shows identical journal bytes.
   - A card with no object `diagnosis_state` refuses `legacy_projection_unbound` before the deadline check and before D is imported. This is tested for both known and null legacy totals, with unchanged journal bytes and an empty queue.
   - A malformed `{}` state through real D gives `exhaustion: false`, no projection and no queue, for both known and null totals.
   - Known pending infrastructure queues one `resume/exhaustion` with no child and replays idempotently.
   - Known completed (held) has no queue and no child.
   - Null pending or null completed gives `resume/settlement` only.
   - `_enqueue` now uses `card_total`, so `case_budget: null` no longer throws.
10. **Inventory.** `batch_accounting.py` is in `TRUSTED_FILES` and in the manifest test's expected set.
11. **Test provenance.** The tests use D's public `settle`, `complete_invocation` and `reconcile_reservations` on saved e15450/5813be ledgers, with authored receipts from `test_stream_d` helpers, and never `_settle_leaf`. The `diagnosis_state={}` in the contract fixture is commented as authored. No Murphy row is closed; new-batch-service-3 is added as open.

**Nits (non-blocking)**
1. `_enqueue` (`factory/batch_service.py:256`): a malformed known total, such as a negative or bool value, now raises `invalid_accounting_input` after `_project` has run but before `atomic_json`. It fails closed and nothing is persisted, but no regression test pins it. Add one when the journal is wired.
2. `_normalize` (`factory/batch_accounting.py:24`): `Decimal` also accepts exponent or padded strings such as `"1e3"` and `" 1 "`. This is harmless because the card total must still equal D's normalized total, but the design text says "decimal strings". Tighten it or note it at activation.
