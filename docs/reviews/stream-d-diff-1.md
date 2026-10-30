# Stream D diff review 1: `72d5c8f..3da159a`

**Verdict: NOT PASS.** Two blockers, B1 and B2. Both are reproduced below.

- **Method:**
  - Read both personas (`zoom_out`, `implementation_readiness`), the readiness and zoom-out standards, `ENGINEERING.md`, `stream-d.md`, and `interfaces.md` §§2, 3, 5, 7.
  - Read B's §8 from `t3/batch-service-control-vm` with `git show` only.
  - Read the Murphy rows (8–13, 15, 21, 35, 39).
  - Ran the 7 focused tests: OK.
  - Ran seven short probes against the real `budget.py` and `job_authority.py` in temp directories, with no file or git edits.
- **Scope:** I did not flag runtime, diagnosis, extension, or dispatch wiring as missing.
- **Out of scope:** `factory/diagnosis.py` and `factory/prompts/diagnosis.md` are untracked in the worktree. They are not in the diff and I did not review them.

## What holds up

- **Atomic reservations:**
  - `ledger_transaction` takes the same `<ledger>.lock` flock the streaming accountant uses.
  - It does not save when the body raises, so a failed settle or reserve leaves the file untouched.
  - `test_duplicate_reservation_and_parallel_admission` shows exactly one of two racing 6-dollar reservations admitted.
  - A duplicate lease with the same operation, call name and maximum returns the same row. A mismatch is refused.
- **Settlement:**
  - $10 reserved with $5 booked adds a $5 gap, so the total is $10. Replay adds $0.
  - A late final receipt of $8 gives −$2. Replay adds $0.
  - Both results are confirmed by the test and by my probe.
  - An unknown gap is `max(0, reserved maximum − booked)`, not zero.
- **Merged sequential fallback:**
  - Aggregates expand recursively to leaves, and duplicate paths are deduplicated through `seen`.
  - The aggregate `usage_delta` of 500 is never booked.
  - The wait record's `route` and `account` (the next candidate) are ignored.
  - Gaps are settled per lease: $3 + $2 = $5.
- **Zero-denial:**
  - A null-lease, null-call wait books $0 and leaves no reservation.
  - A pending reservation without a receipt stays pending.
  - A lease set with no receipt is refused as `wait_receipt_mismatch`.
- **Malformed path:**
  - `../`, an absolute path, and `usage-receipts/../..` all raise `invalid_usage_receipt`, and the ledger bytes are unchanged.
  - Per-component symlinks are also refused.
- **Reclassification, normal case:**
  - Subtracting the events from the role breakdown and adding them once to waste leaves the total unchanged.
  - The legacy remainder is computed from the full observed sums before the subtraction.
  - The legacy $16 receipt stays single-counted.
- **Stale money:**
  - `job_authority.read` requires an exact key set, an exact schema, uuid4, a nine-place amount, an exact revision, and equality with the launch binding.
  - It requires a UTC-only deadline.
  - Any missing or stale value fails closed to `money_wait`. An expired deadline gives `retired_batch_bound`.
  - It matches B's §8 shape.
- **Row and ID validation:**
  - `usd()` rejects NaN, infinity, negative values and bool.
  - No fixture card has an event without an `id`: 56 of 58 cards have a ledger, and none has an id-less event.

## Blockers (fix before merge)

### B1. A valid `factory_bug` record becomes invalid when a late receipt settles another lease in the same operation

- **Where:** `factory/budget.py:305-306`. The check is `set(ids) == {event ids of rows with state == 'settled' for these operations}`. `estimated_gap_usd` is not part of the classified set either (`:281-285`).
- **Repro:**
  1. One operation has L1 (final, $4) and L2 (interrupted, $2 booked, estimated).
  2. Classify L1's event `a` as waste. This is accepted: spent 10, waste 4, total 14.
  3. L2's final receipt arrives (events b=2 and c=1) and `settle` returns −7.
  4. L2 now has state `settled` with events {b, c}, so the equality fails.
  5. `case_spending` counts an unpriced event, so `total_spent_usd` is `None`.
  6. The next `reserve_invocation` raises `money_wait`.
- **Why it blocks:** this is the Murphy 21 failure again. A late receipt permanently poisons the case budget as unknown. A second record cannot repair it, because operation and event IDs must be disjoint from the first record's (`:300`). It also breaks the §8 rule that waste reclassification is stable.
- **Guidance:**
  - Accept a record only when every reservation row of the named operations is `settled`. Otherwise treat it as not yet classifiable.
  - Add a regression test for "late receipt after classification".

### B2. Reservations and the `estimated_gap_usd` field are persisted in a non-canonical money format

- **Where:** `factory/budget.py:139` (`str(maximum)`) and `:202` (`str(estimate)`).
- **Repro:**
  - `usd(0.0000005)` is stored as `'5.00E-7'`.
  - A zero gap is stored as `'0'` or `'0E-9'`.
  - `'-0'` quantizes to `-0E-9`, which `usd()` does not reject.
- **Why it blocks:**
  - `usd()` is documented as "the batch channel's nine-place, nonnegative decimal money unit".
  - B's regex `(?:0|[1-9][0-9]*)\.[0-9]{9}` would reject these strings.
  - The rows land in the ledger and so in the public card, and persisted formats are costly to migrate later.
- **Guidance:**
  - Format money with `format(x, 'f')` at every write.
  - Make `usd()` normalise `-0` to `0`.
  - Add a test that asserts the stored strings match the nine-place regex.

## Major findings (fix now or record as an explicit later-increment obligation in `stream-d.md`)

- **M1. A ledger event without an `id` crashes with a raw `KeyError`.** `factory/budget.py:145` and `:184` use `{e['id']: e ...}`.
  - A's receipt writer expects id-less events, via `unidentified_events` and `e.get('id')`.
  - A raw `KeyError` is not a `BudgetError`, so callers cannot fail closed or retry.
  - Repro: a ledger with `{'cost':1,'role':'writer'}` and no `id` makes `reserve_invocation` raise `KeyError 'id'`.
  - Use `e.get('id')`. Treat id-less events as unattributed but still counted in totals.
  - Make A's `final_usage_known: false` (set when `unidentified > 0`) widen the gap safely instead of crashing.
- **M2. Malformed inputs escape as non-`BudgetError` exceptions in `reserve_invocation`, `settle` and `for_case`.**
  - **`reserve_invocation`:** `factory/budget.py:122`.
    - The `invalid_operation` line is unreachable for bad input. `uuid.UUID('not-a-uuid')` raises `ValueError`, `None` raises `TypeError`, and `5` raises `AttributeError`.
    - It also accepts a non-v4 UUID and the dashless form, which is then stored non-canonically.
    - Later `operation_ids` comparisons are raw-string, so a dashless operation can never match a canonical `factory_bug` record. That fails closed as unpriced and is hard to diagnose.
    - Require canonical lowercase uuid4, and raise `BudgetError('invalid_operation')` for anything else.
  - **`settle`:** `factory/budget.py:157` and `:220`.
    - `Path(relative)` and `record['call_id']` sit outside the `try`. A `call_id` of `5`, `{}` or `[]` raises `TypeError` rather than `invalid_usage_receipt`.
  - **`_settle_leaf`:** receipt event elements that are not dicts raise `AttributeError` at `.get`.
  - **`for_case`:** `factory/job_authority.py:55` raises `AttributeError` when `authenticated_job_config` is `None`.
  - No ledger write occurs in any of these cases, so safety holds. The exception type is what breaks later integration.
- **M3. The `unpriced_invocations` clearing in `_settle_leaf` is dead code.** `factory/budget.py:206-207`.
  - It removes entries by `invocation_id`, but the streaming accountant at `budget.py:922` appends `{'role','model'}` with no `invocation_id`.
  - Nothing in the repo writes the reservation's `invocation_id` into the accountant.
  - After integration the interrupted call stays unpriced, so Murphy 21 and 39 would not be closed by settlement.
  - Branch coverage is zero. Record the wiring obligation in the design: the wrapper must pass the reservation's `invocation_id` into `_run_budgeted`. Add one test that exercises the removal.
- **M4. `for_case` compares the deadline as a string.** `factory/job_authority.py:57-59`.
  - A's `model_router.metadata` accepts `case.batch_deadline` as an epoch or an ISO string, via `epoch()`.
  - Repro: an epoch float, or ISO with fractional seconds, gives `money_wait` forever even though the instants match.
  - Compare instants (`epoch(authority.batch_deadline) == epoch(c.batch_deadline)`), not strings.
- **M5. The provenance of `c.job_money`, `c.authenticated_job_config`, `c.batch_id`, `c.job_id`, `c.batch_deadline` and `c.source_generation` is undefined.**
  - None of these attributes exists in the repo.
  - If `job_money` and `authenticated_job_config['job_money']` are loaded from the same checkpoint, the `channel != launch_binding` equality proves nothing.
  - B §8 intends the checkpointed copy to be compared with the *authenticated launch configuration*. A stale copy is only refused if the binding is current.
  - Name the exact source of each attribute in the design, or in a docstring on `for_case`, before wiring it.
- **M6. `reserve_invocation` takes an arbitrary `limit_usd`.** `factory/budget.py:119`.
  - The docstring says authority is never created or enlarged here, yet any caller (including tests, which pass 1000) supplies the limit.
  - A card or argv limit could be substituted by mistake.
  - Take a `JobAuthority` (or its `committed_total_usd`) as the only source of the limit. Keep the raw number for tests only.
- **M7. There is no state transition for a reservation that never started or whose worker died.** `factory/budget.py:144-151`.
  - A `pending` row with no receipt counts `maximum_usd` in `outstanding_reservations` indefinitely.
  - `settle` does not release it.
  - The design requires "denied before any CLI → released at $0" and "conservative crash settlement".
  - That is safe against undercharge, but it leaks headroom for the rest of the case. Record the release and abandon transitions as the next increment's first item.

## Nits (optional)

- N1. `case_spending` and `settle` return floats rounded to nine places. Decimal is only used internally, so `settle`'s return value and the public `total_spent_usd` are floats. This is fine at current magnitudes but is not "Decimal totals" end to end.
- N2. `factory_bug` records check only the *shape* of `diagnosis_sha256`, `fix_attribution_sha256` and `fix_commit` (hex lengths). Nothing links them to retained evidence. Acceptable now, but say so in a comment.
- N3. `reserve_invocation` idempotence compares `(operation_id, call_name, maximum)` but not `parent_call_name`.
- N4. `settle` re-runs every leaf even when `record['settled']` is already true. It is idempotent, so this is harmless.
- N5. `settle` ignores `usage_delta`, so a receipt with a delta and no events books nothing. This is consistent with "events are evidence" but differs from the design wording "add missing events/delta".
- N6. `ledger_transaction` always rewrites the file, even for a no-op.
- N7. `_usage_leaves` recursion has no depth bound (only the `seen` set).

## Test adequacy

The tests are real-ledger replays with authored receipts, as disclosed in the docstring.

Covered and sound:
- Totals and the legacy $16 receipt.
- The $10→$8 late replacement.
- The aggregate dedup and the candidate-route fields.
- Null denial and path escape with no write.
- Duplicate reservation and parallel admission.
- The $12→$8+$4 reclassification.

Missing, and needed for B1 and M3:
- A late receipt for another lease in an already-classified operation. This is B1's regression test.
- A test for the `unpriced_invocations` removal.
- A test for the money-format regex (B2).
- A test for an id-less event (M1).
- `for_case` is tested only with absent config. There is no success case, no mismatch per field (batch, job, case, deadline, source_generation), and no `retired_batch_bound` terminal case.
- `usage_reservation_missing` and `usage_receipt_regressed` refusals are not exercised.

## Murphy rows

No row is claimed closed, which is correct. Rows 8, 9, 10, 11, 12, 13, 15, 35 and 39 are untouched by this increment. Row 21 depends on M3 and B1 being fixed.

## Required before re-review

1. B1 and B2, each with a regression test.
2. M1 and M2, or a documented reason.
3. M3 through M7 as explicit obligations, in `stream-d.md` or the increment-2 plan.
4. Save this review verbatim as `docs/reviews/stream-d-diff-1.md`, with a "fixed / rejected" ledger below it.

## Elephant response

All findings accepted; none rejected. B1: initial waste attribution now refuses
until every reservation of its named operations is settled. A later final
receipt updates that same record's event IDs and settled amount, so the ledger
stays numeric and batch spend stays unchanged by classification. The regression
test covers the premature refusal, final settlement, classification and a later
final receipt. B2: persisted reservation/estimate strings use nine fixed decimal
places, including canonical positive zero and small fractional costs.

M1/M2: id-less ledger events remain counted and unattributed; malformed UUIDs,
receipt paths/events and absent launch configuration fail with BudgetError.
Operation IDs are canonical UUID4. M3/M5/M7 are explicit increment-2 obligations
in stream-d.md: wire invocation IDs through the streaming accountant, install
current authority from B's authenticated launch independently of restored copies,
and release never-invoked/settle crashed reservations. The clearing helper has
a focused test; the real accountant integration is not yet claimed.
M4: deadlines compare instants, with successful epoch/fractional-ISO tests and
per-field stale-binding tests. M6: reserve_invocation now accepts JobAuthority,
not a caller-provided numeric ceiling. N2/N3/N6/N7 also addressed: the attribution
trust boundary is documented; parent-call identity participates in idempotence;
no-op transactions do not rewrite; aggregate recursion is bounded. No row closes.
