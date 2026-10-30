# Stream D diff review 2: `a3bb9dc..700ab89` (HEAD)

**Verdict: NOT PASS.** One blocker, B1′. It is a new blocker. It has the same failure shape as diff-1 B1: a valid `factory_bug` record is invalidated by a late receipt, and the case total goes to `None`. I reproduced it with a deterministic case.

## Method

- Read the `zoom_out` and `implementation_readiness` personas, both standards, `ENGINEERING.md`, `stream-d.md` and `stream-d-diff-1.md` verbatim.
- Read `interfaces.md` §§2, 3, 5, 7 and §8 via `git show t3/batch-service-control-vm:docs/designs/interfaces.md`.
- Read the full `a3bb9dc..HEAD` diff of `budget.py`, `job_authority.py`, `stream-d.md` and the tests.
- Ran probes against the real `budget.py` and `job_authority.py`, using temp directories under the scratchpad. I made no repo or git edits.
- I did not re-run the test suite. I accepted your report that the 11 focused tests pass.
- I excluded the untracked `factory/diagnosis.py`, `factory/prompts/diagnosis.md` and `tests/factory/test_stream_d_diagnosis.py`.
- I did not flag the intentionally pending wiring: M3, M5 and M7, runtime integration, the diagnosis and extensions wiring, and the Murphy rows. No row is claimed closed, which is correct.

## Prior findings: verified fixed

- **B1, early attribution (`reclassify_factory_bug`).**
  - The refusal path works: reclassifying while another lease of the operation is unsettled raises `waste_operations_pending`.
  - After the final receipt settles, classification succeeds. A later final receipt extends the same record's `event_ids` and amount, and `total_spent_usd` stays numeric.
  - Probe: with a final lease A=$4 and an interrupted lease B=$2, totals were 14, then refused, then 7 (after B's final), then classified at waste 7 and total 7, then waste 8 and total 8 after a late event. Spend stays numeric and does not double count.
  - A new lease on an already-classified operation also behaves. The record becomes a retained, unclassified proposal while that lease is pending. Once it settles, the record extends to cover its events (`['a','b','r1']`).
- **B2, canonical money.**
  - A reservation maximum of `0` is stored as `'0.000000000'`.
  - `1e-7` is stored as `'0.000000100'`, and its `estimated_gap_usd` is stored in the same form.
  - `usd('-0')`, `usd(-0.0)` and `usd('0E-9')` all give a positive-zero decimal. `format(..., '.9f')` gives nine places.
  - `usd` still rejects NaN, bool, `None` and out-of-range values.
- **M1, M2, M4 and M6.**
  - Id-less events stay counted.
  - Malformed operation IDs raise `BudgetError('invalid_operation')`.
  - A missing launch configuration raises `money_wait`.
  - Epoch and ISO deadlines compare as instants.
  - `reserve_invocation` requires a `JobAuthority`.
  - Regressed receipts raise `usage_receipt_regressed`, and missing reservations raise `usage_reservation_missing`.
- **Design record.** `stream-d.md` records the increment-2 obligations accurately and does not overclaim.

## Blocking finding

### B1′. A late receipt extends a `factory_bug` record with different rounding than the validator uses, so the record turns invalid and the case total becomes `None`

**Where**
- `factory/budget.py`, the extension block at the end of `_settle_leaf`. It sets `waste['infrastructure_waste_usd'] = float(sum(event_charge(events[i]) …))`. `event_charge` rounds each event to nine places first.
- `case_spending`'s validator, in the `factory_bug` branch. It checks `usd(record['infrastructure_waste_usd']) == usd(sum(event_costs[i] for i in ids))`. Here `event_costs` holds raw float sums that are rounded once, after summing.

**Repro**
- Real ledger events have costs with more than nine decimal places, so the two roundings can disagree. The probe used a fresh ledger and one final lease.
  1. Settle events `e0=0.1234567894`, `e1=0.2234567894`, `e2=0.3234567894`.
  2. Classify them as waste with amount 0.6703703682. This is accepted: waste 0.670370368, total 0.670370368.
  3. A later final receipt adds `e3=0.5`, and `settle` returns 0.5.
  4. The stored amount is `1.170370367` (a sum of per-event rounded values). The validator expects `usd(1.1703703682)` = `1.170370368`.
  5. The record is invalid, so `unpriced_events` is 1 and both `spent_usd` and `total_spent_usd` are `None`.
  6. The next `reserve_invocation` raises `money_wait`.
- Randomised check: 200 trials of four uniform float costs (three classified, then a late fourth event). 80 of 200 (40%) ended with `total_spent_usd = None` after the late extension.
- No such failure appears when the late receipt adds nothing, and none in the integer-cost tests. The tests only use whole-dollar costs, so they cannot see this.

**Why it blocks**
- It is the same failure as diff-1 B1: a late final receipt permanently poisons the case budget as unknown. This is the Murphy 21 failure again.
- A second record cannot repair it, because operation and event IDs must be disjoint from the first record's.
- It also breaks §8: waste reclassification must be stable and never change the batch total.
- It triggers on ordinary price-derived floats, not on corner cases.

**Guidance**
- Prefer the simplest fix, which also deletes code: do not mutate the record in `settle`. Make `case_spending` derive the classified `event_ids` and amount from the settled reservations of `operation_ids`. The record then only needs to carry the attribution identity (`id`, hashes, `fix_commit`, `operation_ids`), and the extension block and the equality check in the validator go away.
- If the design keeps the stored `event_ids` and amount, use one arithmetic everywhere. Either the validator sums `event_charge` (per-event rounded Decimal), or the extension rounds the float sum once. Also decide what amount the coordinator must supply at initial classification, and document it.
- Add a regression test with sub-nanodollar costs. The probe's values work: `0.1234567894`, `0.2234567894`, `0.3234567894`, then a late `0.5`. Assert that `total_spent_usd` stays numeric, equals the sum of the events, and does not change with classification. Also test the replay and idempotence of `settle`.

## Major findings (fix now, or add to the `stream-d.md` obligations)

### M-A. The original accepted attribution can no longer be replayed after a late extension

- **Where:** `reclassify_factory_bug`, the `existing != record → waste_attribution_mismatch` comparison.
- **Repro:** classify event `a` ($4), then a late final receipt adds `b` ($1). The stored record is now `{a, b}` and $5. A coordinator that crashed after the first call and replays its original `{a}` record gets `waste_attribution_mismatch`.
- **Why it matters:** the helper claims replay-safe idempotence, but replay fails exactly when the late-receipt extension has run. The coordinator would have to treat a mismatch as success.
- **Guidance:** compare only the immutable attribution identity fields (`id`, `diagnosis_sha256`, `fix_commit`, `fix_attribution_sha256`, `operation_ids`) and treat `event_ids` and amount as derived. The B1′ fix above resolves this as well.

### M-B. Negative zero reaches the public card

- **Where:** `case_spending`, where it subtracts the classified costs from `breakdown` and `known`.
- **Repro:** after classifying the only event, `spent_usd` is `-0.0`. The role breakdown can carry the same value.
- **Why it matters:** diff-1 B2 fixed the negative-zero format for persisted reservation strings. This is the same class on the public card. B's consumer rejects negatives, so `-0.0` can go the wrong way depending on how B parses and formats it.
- **Guidance:** normalise with `round(x, 9) + 0.0` (or `abs()` on a zero result) when producing `spent_usd` and `breakdown_by_role`. Add a test that asserts `repr(0.0)`.

### M-C. Raw exceptions escape on malformed waste data

- **Where (reproduced):**
  - `reclassify_factory_bug(path, None)` raises `AttributeError`.
  - `_settle_leaf` calls `waste.get(...)` on every entry of `infrastructure_waste`. A ledger containing a non-dict entry (which `case_spending` tolerates and counts as unpriced) makes `settle` raise `AttributeError`.
- **Where (by reading, not reproduced):** a non-list `operation_ids` or `event_ids` would raise `TypeError` in the `in` checks once reservations exist.
- **Why it matters:** this is the diff-1 M2 class. Callers need a `BudgetError` so they can fail closed.
- **Guidance:** guard with `isinstance` and raise `BudgetError('invalid_waste_attribution')`.

## Nits (optional)

- **N-A. Transient flip of ordinary spend.** While a new lease on a classified operation is pending, the retained proposal is unclassified. Waste drops to 0 and ordinary `spent_usd` rises by the classified amount, then flips back when the lease settles. The batch total is unchanged. This briefly counts waste against the ordinary-diagnosis threshold. Consider noting it in the design, or keeping the already-settled events classified.
- **N-B. `usd` accepts lenient input.** It accepts underscores and surrounding whitespace (`'1_0'` gives 10, `' 5 '` gives 5). The output is canonical, but B's strict regex would not accept those inputs. Only matters if untrusted strings reach `usd`.
- **N-C. Tiny maximums round to zero.** `reserve_invocation` with a maximum below 0.5e-9 (for example `1e-10`) stores a `0.000000000` reservation. Probably should be refused or documented.
- **N-D. `waste` amounts are persisted as JSON floats.** `float(Decimal('0.0000005'))` serialises as `5e-07`. This is not B's channel, but it is a non-fixed-place number on the card, unlike reservations. Say so in the design.
- **N-E. `for_case` reads `c.case_id` and `c.card` directly.** A case object missing either raises `AttributeError`, not `BudgetError`. The other attributes use `getattr`.
- **N-F. Naive ISO deadlines.** `for_case` accepts them through `model_router.epoch`, which reads them in local time. `read` already rejects naive ones. Consistent with A, but worth one line in the docstring.

## Test adequacy

**Covered and sound**
- The early-refusal, late-settle, classify and later-final sequence (`test_premature_waste_refuses_then_late_receipt_remains_numeric`) proves the integer path.
- Small and zero money formats, the `unpriced_invocations` removal, id-less events, malformed operation IDs, full `for_case` bindings per field, and epoch versus fractional-ISO deadlines.
- The tests replay the 58 genuine public-card fixture and use authored receipts, as disclosed. They do not claim real crash artifacts.

**Missing, and needed for B1′**
- Any extension or classification test using fractional costs beyond nine places.
- A test that the `factory_bug` amount and event set stay valid after each of several late receipts.
- A test for replaying the original record after an extension (M-A).
- A test for `-0.0` on the card (M-B).
- A malformed-waste test (M-C).

## Murphy rows

No row is claimed closed, and none should be. Rows 21 and 39 depend on M3 and M7 (increment 2) and on the B1′ fix.

## Required before re-review

1. B1′ with the sub-nanodollar regression test.
2. M-A, M-B and M-C, or a documented reason.
3. Save this review verbatim as `docs/reviews/stream-d-diff-2.md`, with a fixed/rejected ledger below it.

## Elephant response

All findings accepted; none rejected. B1′: retain the design's stored event IDs
and amount, using one _waste_amount calculation for validation and late receipt
extension. Preserve provider precision until the cumulative sum, then round once
to nine places. The coordinator's initial amount is compared in that same unit.
The regression uses the review's three fractional costs, then three late receipts
including a sub-nanodollar cost. It checks numeric totals, unchanged classification
total, settlement replay, and positive zero in ordinary spend/role breakdown.

M-A: attribution replay compares only immutable identity/fix/operation fields;
derived event IDs and amount may have grown. M-B: public ordinary totals and role
values normalize rounded zero to positive zero. M-C: malformed waste objects and
ID containers fail with BudgetError. N-A: already-settled waste stays classified
while a later lease is pending; initial classification still requires all named
operations settled. N-C: maxima and unknown gaps round upward to the nine-place
unit. N-E: missing case/card attributes fail closed. JSON card totals remain
numeric floats for existing readers; only B's channel/reservation strings use
fixed-place decimal formatting (N-D). No rows close.

The first full suite completed 135 scripts with one upload-inventory expectation
failure: job_authority.py and the untracked next-increment diagnosis drafts were
absent from the independent frozen inventory. The drafts were moved outside the
repo; this increment adds job_authority.py to that explicit expectation. The
inventory check now passes. A clean full-suite rerun follows this fix.
