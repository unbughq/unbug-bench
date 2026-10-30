# Stream D diff review 3: `a3bb9dc..3e545fe` (HEAD)

**Verdict: NOT PASS.** There is one blocker, B1‴. It is the third round in which two money calculations in `budget.py` disagree at sub-nanodollar precision. This time the disagreement is between the ledger totals and the per-event sums. All three prior blockers (diff-1 B1/B2, diff-2 B1′) and M-A, M-B and M-C are fixed for their reproduced cases. Beyond the one blocker there are three majors, none of them a regression of an earlier fix, and a short nit list.

## Method

- **Read first:** the `zoom_out` and `implementation_readiness` personas, both standards, `ENGINEERING.md`, `stream-d.md`, and `stream-d-diff-1.md` and `stream-d-diff-2.md` in full.
- **Interfaces:** §8 from `git show t3/batch-service-control-vm:docs/designs/interfaces.md`.
- **Code and tests:** the `budget.py`, `job_authority.py` and `test_stream_d.py` changes, and the one-line change in `test_launch_manifest.py`.
- **Probes:** short Python scripts in the scratchpad, using temp ledgers. No repo, git, launch, decryption or credential actions.
- **Tests run:** `tests/factory/test_stream_d.py` (13 pass) and `tests.tools.test_launch_manifest` (2 pass). I did not start the full suite.
- **Scope:** I did not count missing runtime, diagnosis, extension or wiring as findings. M3, M5 and M7 are recorded in `stream-d.md` and not claimed closed. No Murphy row is claimed closed, which is correct.

## Prior objections: verified fixed

- **diff-1 B1, premature `factory_bug`:**
  - Attribution is refused with `waste_operations_pending` until every named reservation is settled.
  - A later final receipt extends the same record.
  - In integer-cost cases the total stays numeric and unchanged. The sequence in `test_premature_waste_refuses_then_late_receipt_remains_numeric` holds.
- **diff-1 B2, canonical money:**
  - Reservation maxima and estimated gaps are stored as nine-place strings.
  - `0`, `'-0'` and `'0E-9'` give `0.000000000`.
  - `1e-7` gives `0.000000100`.
- **M1/M2:**
  - Id-less events are counted and unattributed.
  - Malformed, dashless and non-v4 operation IDs raise `invalid_operation`.
  - `call_id` values of `5`, `{}` and `[]` raise `invalid_usage_receipt`.
  - A missing launch config, or `None`, raises `money_wait`.
- **M4:**
  - Epoch and fractional ISO deadlines compare as instants.
  - A mismatch of `batch`, `job`, `case`, `source_generation` or deadline raises `money_wait`.
  - `terminal_stop == retired_batch_bound` stays terminal.
- **M6:** `reserve_invocation` requires a `JobAuthority` object. But see M-2 below.
- **diff-2 B1′, original repro:** with `.1234567894`, `.2234567894`, `.3234567894` and a late `.5`, the record stays valid, the total stays numeric, `settle` is idempotent, and the original attribution record replays (M-A). This also held in a randomised check: 200 trials, single role, one late event, `total_spent_usd` never `None`, the original record always replayed.
- **M-B:** a rounded zero is positive zero (`repr 0.0`) for `spent_usd` and the role breakdown.
- **M-C:** `None` and non-dict waste entries, and non-list `operation_ids`, raise `invalid_waste_attribution`.
- **N-A, N-C, N-E:**
  - Settled waste stays classified while a new lease on the operation is pending (probe: waste 4, spent 0, total 4).
  - Maxima and gaps round up (`1e-10` gives `0.000000001`).
  - A missing `case_id` or `card` raises `money_wait`.
- **Unknown gaps, stale authority and idempotence:**
  - A gap is `max(0, max − booked)`, rounded up, and counted once in the total, not also in the pending reservations.
  - A final receipt clears the estimate; replay adds $0; a regressed receipt raises `usage_receipt_regressed`.
  - A stale or mismatched `job_money` fails closed.
- **Inventory test:** `job_authority.py` is in the worker-upload expectation and the focused test passes.

## Blocker

### B1‴. Ledger totals and event sums use different rounding, so classification can leave a negative or phantom `spent_usd` and move the batch total

**Where**
- `factory/budget.py:215-216`, in `_settle_leaf`. It books a late event into the ledger aggregate as `float(usd(ledger[key]) + usd(event[key]))`. That rounds the whole running aggregate half-up to nine places on every late event.
- `case_spending` subtracts the classified events at their raw float costs (`event_costs`). It also takes the legacy remainder from `ledger total − observed raw sum`.
- Two different roundings therefore feed one subtraction.

**Repro** (probes in the scratchpad: `probe.py`, `probe2.py`, `probe3.py`; real `budget.py`)
1. Settle `e0=.1234567894`, `e1=.2234567894`, `e2=.3234567894` under three roles (writer, reviewer, tester), then classify them with the validator-accepted amount `.6703703682`.
2. The classified waste is `0.670370368` and the total is unchanged at `0.670370367`. But the public card's `spent_usd` is **−1e-09**.
3. In 300 randomised three-role trials, 45 ended with a negative `spent_usd`.
4. With one role and the same three events, the total moves from `0.670370367` to `0.670370368` on classification.
5. With one role and a late fourth event, 31 of 200 trials leave `spent_usd = +1e-09`, as a phantom `legacy_unattributed` entry, after full classification. In the probe, `infrastructure_waste_usd` was 1.386130825 against a total of 1.386130826.
6. The size is at most a few nanodollars.

**Why it blocks**
- This is the same defect class that blocked diff-1 B1 and diff-2 B1′, now at a third boundary.
- diff-2 set the bar: the total "stays numeric, equals the sum of the events, and does not change with classification". The elephant's response also claims positive zero for public ordinary spend. Neither holds once event costs carry more than nine places.
- A negative `spent_usd` on the public card contradicts `usd()`, the stated "nonnegative" money unit. §8 says B "rejects negative … values", and older cards go to B through `spent_usd + infrastructure_waste_usd`.
- The elephant's regression test passes only because its chosen values happen not to expose this. Its single-role values do not trigger it.

**Guidance**
- Use one valuation. Prefer deleting code: stop re-quantizing the running aggregate in `_settle_leaf`. Add the event's raw charge to the aggregate, as the streaming accountant does at `budget.py:674-678`. Then subtract classified events from the aggregate they were booked into.
- If you keep the rounding, clamp `spent_usd` and the role breakdown at ≥ 0 and assert `total_after == total_before`. That hides the symptom, so treat it as the second-best choice.
- Add a regression test with sub-nanodollar costs across two or more roles, with and without a late event. Assert `spent_usd ≥ 0`, no `legacy_unattributed` residue, and `total_after == total_before`.

## Major findings

- **M-1. Late extension and validator value events differently for legacy derived-price events** (`budget.py:237` against the validator at `:336`). This is a second sub-nanodollar disagreement of the B1′ shape.
  - `_settle_leaf` passes raw ledger events to `_waste_amount`. The validator passes `indexed_events`, which carry the read-time Codex estimate.
  - Repro: a legacy event with `priced: subscription`, a Codex model and tokens but no cost fields, referenced by a reservation. Classify it at 0.3, then settle a late `lg2` of $1.
  - The extension stores 1.0 and the validator expects 1.3. The record turns invalid and `total_spent_usd` goes to `None`.
  - It needs a legacy event tied to a reservation via `booked_event_ids`, so it is narrow. It matters for the import and reconcile flows behind Murphy 21 and 39.
  - The same single-valuation fix as B1‴ covers it. Add a test.
- **M-2. `reserve_invocation` never rechecks authority freshness, and `JobAuthority` is publicly constructible.** M6 is a type check only.
  - Probe: `JobAuthority(..., batch_deadline='2020-01-01T00:00:00Z')` was admitted and reserved $5.
  - `read` and `for_case` check the deadline once, when called.
  - Either recheck the deadline at reserve time, or record in `stream-d.md` that increment 2 must call `for_case(c)` immediately before every `reserve_invocation` and never hold an authority across calls. The current design text does not say this.
- **M-3. New increment-2 obligation, not recorded: the reservation lock blocks behind a running serial invocation.** `ledger_transaction` takes `<ledger>.lock`. The default `run_budgeted` (`concurrent_roles` false, `model_runtime.py:463`) holds that same lock for the whole CLI session.
  - Probe: `reserve_invocation` blocked for more than 2 seconds while another handle held the lock, and succeeded after release.
  - The design's G10 nested owner "reserves independently after admission" while the tester's serial call is live. That would deadlock until the tester times out.
  - Record the obligation. Choices for the next increment are a concurrent accountant for G10 calls, or a short-lived reservation file separate from the whole-session lock.

## Nits (optional)

- **N1.** `reclassify_factory_bug` checks "all named operations settled" (`:295`) before the existing-record replay check (`:297`). A replay of an already-recorded attribution raises `waste_operations_pending` while a new lease on the operation is pending, instead of returning idempotently. It fails closed. Until the M7 release path exists, a crashed pending lease would keep the coordinator from confirming its own record. Moving the existing-record check first is one line.
- **N2.** `usd()` still accepts `' 5 '` and `'1_0'`. This is diff-2 N-B, not claimed fixed.
- **N3.** `reserve_invocation` rounds `maximum` up, but `usd(maximum_usd)` is called first for validation and rounds half-up. It is harmless, but the first call is redundant for finiteness checks. Consider one parse.
- **N4.** `JobAuthority.batch_deadline` is a raw string, and `epoch()` handles naive ISO in local time (diff-2 N-F). It is still undocumented in `for_case`.

## Test adequacy

**Covered and sound**
- Late receipt, replay and zero-denial paths.
- The fractional-cost regression for the integer-to-nine-place case on one role.
- `unpriced_invocations` removal.
- `for_case` per-field staleness.
- Malformed waste and tiny maxima.

**Missing**
- Multi-role classification with sub-nanodollar costs (B1‴).
- A legacy derived-price event followed by a late receipt (M-1).
- Reserve with an expired authority (M-2).
- Replay of an existing attribution while a lease is pending (N1).

## Murphy rows

No row is claimed closed, and none should be. Rows 21 and 39 still need M3 and M7 (increment 2) and the B1‴ fix.

## Required before re-review

1. B1‴ with the multi-role sub-nanodollar regression test.
2. M-1, M-2 and M-3, each fixed or recorded as an explicit obligation in `stream-d.md`.
3. Save this review verbatim as `docs/reviews/stream-d-diff-3.md`, with a fixed/rejected ledger below it. I have not written it; the elephant saves it.

## Elephant response

All findings accepted; none rejected. B1‴: replaced the parallel float/role
valuation in case_spending with one Decimal valuation of raw receipt components.
Settlement adds raw amounts to existing aggregates as the streaming accountant
does. Role rounding cannot feed the cumulative total. Total/waste round once
at the public money boundary; ordinary spend is their nonnegative difference.
Sub-unit aggregate floating noise creates no legacy charge. Regression covers
the cited three-role fractions and 30 deterministic randomized three-role cases,
each with classification, a late event, and replay while another lease is pending.
No total moves on classification and no phantom legacy_unattributed entry remains.

M-1: event_charge and case_spending share _event_components, including the legacy
Codex derived estimate. Its .3 -> 1.3 late-receipt regression stays numeric and
fully classified. M-2: reserve_invocation rechecks expiry, covered with a directly
constructed expired authority; the immediate for_case/revision check remains an
explicit runtime obligation. M-3: recorded the concurrent accountant requirement
for new-schema calls; the RLock serializes model work while ledger locks are short
and the G10 owner can reserve independently. N1: replay checks immutable identity
before requiring all new reservations settled. N2: loose numeric strings with
spaces/underscores are refused. N4: the authority channel requires explicit UTC;
case metadata continues to follow A's epoch/ISO contract. No rows close.
