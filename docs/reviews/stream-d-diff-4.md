# Stream D diff review 4: `a3bb9dc..515a6d4` (HEAD)

**Verdict: NOT PASS.** There is one blocker, B1⁗. It is narrow: the trigger is unusual, it fails closed, and it clears when the pending lease settles. It is the same class as the earlier blockers, a record check disagreeing with the code that extends the record. The fix is one predicate and deletes code. Nothing else blocks.

The root fix for diff-3 B1‴ holds. One Decimal valuation of raw receipt components now feeds the total, the waste figure and the ordinary spend. I could not break it, and I checked it with probes well beyond your 16 tests.

## Method

- **Read first:**
  - The `zoom_out` and `implementation_readiness` personas and both standards.
  - `ENGINEERING.md` and the whole of `stream-d.md` (not only the new section).
  - `stream-d-diff-1.md`, `-2.md` and `-3.md` verbatim, including the elephant responses.
  - Interfaces §§2, 3, 5, 7 and B's §8, taken with `git show t3/batch-service-control-vm:docs/designs/interfaces.md`.
- **Code and tests:** the full `a3bb9dc..515a6d4` diff of `budget.py` and `job_authority.py`, `stream-d.md`, and all of `test_stream_d.py`.
- **Probes:** Python scripts in the scratchpad against the real `budget.py`, using temporary ledgers. No repo or git edits, no launches, no decryption, no credentials. I ran only the focused `tests.factory.test_stream_d` file (16 tests, OK). I did not run the full suite.
- **Scope:** I did not count missing runtime, diagnosis or extension wiring as findings. M3, M5 and M7 and the explicit increment-2 obligations are recorded accurately in `stream-d.md`. No Murphy row is claimed closed, which is correct.

## Prior objections: verified fixed

**diff-3 B1‴ (the root valuation).**
- I ran 400 randomised trials against the real code. They covered:
  - one to six roles;
  - costs with 10 to 15 decimal places;
  - 30% of ledgers carrying a legacy aggregate remainder;
  - three leases across two operations, then classification of the first operation;
  - a late event on a new lease for the classified operation.
- The result was zero failures on every check:
  - classification never moved `total_spent_usd`;
  - `spent_usd` and every role value were never negative;
  - `total_spent_usd` was never `None`;
  - waste equalled the exact round-once sum of the classified events, including the late one;
  - the late event moved the total by its own charge, within 1.1e-9.
- A ledger of 3,000 sub-nanodollar events, all classified, gave a total of 449.598252373, ordinary spend of 0.0, and no `legacy_unattributed` entry.
- Old against new `case_spending` on all 56 fixture ledgers with a continuation budget: **zero differences** in `spent_usd`, `total_spent_usd`, waste, the unknown counters, or any role value. The change to the public card shape is therefore not a regression for existing readers.
- `total` is computed at `budget.py:361`, before the classified costs are subtracted. `waste` is a sum of subsets of the same exact charges, and `usd` is monotonic. So `known = total - waste` can never be negative. The test for this reads `repr(0.0)` correctly.

**diff-3 M-1, legacy derived price.**
- Initial attribution at 0.3 followed by a late $1 gives total 1.3 and waste 1.3, with ordinary spend 0.0. This matches your regression test.
- `_event_components` now calls `codex_cost` for any model on a legacy subscription event, where the old code did so only for `codex/` models. I checked the behaviour change:
  - `codex_cost` returns `None` for an unknown model, so that event is counted unpriced, which fails closed.
  - An unhashable model or a non-dict `tokens` raises `TypeError` or `AttributeError`, exactly as the old code did. This is not a regression.

**diff-3 M-2, M-3 and N1, N2, N4.**
- A directly constructed expired authority raises `retired_batch_bound` at reserve time.
- Replay of an existing attribution returns before the "all operations settled" check. The test covers it.
- Numeric strings now refused: `' 5 '`, `'1_0'`, `'5.'`, `'.5'`, `'+5'`, `'0x10'` and full-width digits. `True` is also refused.
- The authority channel requires an explicit UTC offset.
- The M-3 concurrency obligation is recorded in `stream-d.md`.

**Earlier rounds, re-probed.**
- Probe: with L1 final and classified, L3 estimated with a booked $2, then L3 final, `event_ids` becomes `['a','c','d']` and waste $7. Total goes 4 → 14 (the gap is counted once) → 7.
- A shared event id with a different cost raises `usage_event_conflict`.
- A second record claiming an already-classified event is refused as `invalid_waste_attribution`, and the ledger is left unchanged.

## Blocker

### B1⁗. The late-receipt extension only runs when every lease of the operation is settled, but the validator needs only the settled leases to agree, so a late event on an earlier lease can turn the total into `None`

**Where**
- `factory/budget.py:248`: `if all(r['state'] == 'settled' for r in rows):` gates the extension of `event_ids` and the amount.
- `factory/budget.py:383`: the validator requires `set(ids) == {event ids of rows whose state == 'settled'}`.
- These are two predicates over different row sets. This is the diff-1 B1 and diff-2 B1′ shape again.

**Repro** (real `budget.py`; the probe is in the scratchpad as `p4.py`)
1. L1 is final with event `a` ($4). Classify `a` as waste: total 4.0, spent 0.0, waste 4.0.
2. Reserve L3 on the same operation. It stays `pending`. This is the "replay lease pending" state that your docs and test cover.
3. A final receipt for L1 arrives with one more event, `b` ($1). `_settle_leaf` explicitly allows a final receipt to grow. Your own fractional test does this three times.
4. L1's `event_ids` is now `[a, b]`. The extension skips because L3 is not settled, so the record still says `[a]`.
5. The validator sees `{a} != {a, b}`. Result: `total_spent_usd = None`, `unpriced_events = 1`, and the next `reserve_invocation` raises `money_wait`.
6. Settling L3, even with an empty final receipt, runs the extension and repairs it: total 5.0, waste 5.0.

**Why it blocks**
- `stream-d.md` and your response both state the invariant: "Existing settled waste stays classified while a replay lease is pending", and a later final receipt extends the record without moving batch spend. Here a reachable in-scope input breaks it.
- The failure is closed and recoverable, so I am not calling it a Murphy 21 re-opening. But an L3 that never settles (a crashed worker; M7's release is not built) keeps the case in `money_wait`. The blocking test is "does the claimed invariant hold", and this one does not.
- Reachability is low. It needs a final receipt that grows after a second lease on the same operation exists. I could not find a code path that produces that in production. The only evidence it is allowed is the code itself and your tests.

**Guidance**
- Use the same predicate in both places. Extend from settled rows only, which is what the validator demands:
  - Replace the `all(...)` gate with `rows = [r for r in … if r['state'] == 'settled']`.
  - Extend whenever the lease just settled is one of them.
- This removes a branch rather than adding one.
- Add a regression test along the lines of `test_late_event_on_final_lease_while_replay_lease_pending`:
  - classify L1;
  - reserve L3 and leave it pending;
  - grow L1's final receipt;
  - assert the total is numeric, equals the sum of the events, and is unchanged by the growth beyond the new event;
  - then settle L3 and assert the same.

Because the change is one predicate with a three-line probe, I would accept a self-check against the probe above for the re-review. Your call whether to start a fresh goldfish.

## Nits (optional)

- **N1. Dead input.** The coordinator's `infrastructure_waste_usd` and `event_ids` are fully derived, and `case_spending` ignores the stored amount when it computes waste. The record carries them only so the validator can compare them against themselves. Dropping both from the accepted input would delete `_waste_amount`'s callers in `_settle_leaf` and one conjunct in the validator. This was diff-2's suggestion, and it stays optional.
- **N2. Coordinator float footgun.** The coordinator supplies a JSON float. A float sum of many events can in principle straddle a half-nanodollar boundary against the exact Decimal sum, and be refused as `invalid_waste_attribution`. The probability is about 1e-7 per attribution and it fails closed. It disappears with N1. Otherwise document that the coordinator should compute `sum(event_charge(e))` and round once.
- **N3. `case_spending` can now raise.** It previously never did. I constructed it with a $1000 event next to a 1e-30 event in one role: the 28-digit Decimal context leaves a 1e-30 negative residue, `usd()` raises `invalid_money`, and `case_spending` raises `BudgetError` instead of returning. Realistic costs span far fewer than 27 decades, so this is purely theoretical. A one-line note is enough.
- **N4. Float aggregate drift.** The "sub-unit aggregate noise creates no legacy charge" rule uses a half-nanodollar threshold. A very large ledger could accumulate more float drift than that. The effect is a phantom nanodollar of ordinary spend that never moves the total, so it is harmless. I did not reproduce it at any realistic size.
- **N5. Float equality in the tests.** The tests compare `total_spent_usd` with `assertEqual` on floats of nine-place values. They pass because both sides round the same Decimal. It is fine, but a later reader might expect `assertAlmostEqual`.

## Test adequacy

**Covered and sound**
- The cited three-role fractions, plus 30 seeded random trials. Each trial also does classification, a late event, replay, and a second-lease replay.
- The legacy `.3 → 1.3` Codex case.
- Canonical money strings, tiny maxima rounding up, and `unpriced_invocations` removal.
- The expired-authority reserve.
- Per-field stale binding in `for_case`.
- Replay of the original attribution after growth, and zero positive-negative values on the card.

**Missing**
- B1⁗'s regression: a growing final lease while another lease on the operation is pending.
- Roles resolved through `models_used` for role-less events, together with classification. I probed this by hand and it behaves, but nothing pins it.
- A ledger with a legacy aggregate remainder plus classification. I probed this too (30% of the 400 trials) and it holds.

I treated "real artifacts" as satisfied for the same reason as before. The 56 fixture ledgers are genuine saved cards, and the new settlement tests use authored receipts. The module docstring discloses this and does not claim a real crash.

## Murphy rows

None is claimed closed, and none should be. Rows 21 and 39 still depend on M3 and M7 in increment 2 and on B1⁗ here.

## Required before re-review

1. B1⁗, with the regression test above.
2. Save this review verbatim as `docs/reviews/stream-d-diff-4.md`, with a fixed/rejected ledger below it. I have not written it; the elephant saves it.

## Elephant response

B1⁗ accepted and fixed exactly as recommended: late attribution derives its event
set from the operation's settled rows, matching the validator's predicate. The
all-rows-settled branch is deleted. The new named regression classifies L1=$4,
leaves L3 pending, grows L1 to $5, and checks numeric total/waste=$5, ordinary=$0,
and replay=$0; settling L3=$2 then gives total/waste=$7 and ordinary=$0.
No finding rejected. The optional schema deletion is not taken because the passed
design explicitly retains event_ids/amount. Coordinator attribution must use
sum(event_charge(event)) and round once with usd(), never a separate float sum.

The completed full suite after Decimal valuation had one compatibility-test
failure: exactly three empty legacy_unattributed:0 labels are now absent. Every
saved amount and recovery decision matches. A separately committed exact migration
pins the three original card hashes and removes only those zero labels from the
in-memory expected projection. Original card fixtures and the frozen snapshot
remain untouched. Its six tests pass, and another full suite is running.
