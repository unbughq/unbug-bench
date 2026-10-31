# Goldfish design review 8 (Codex): stream D item 3, money cleanup

Reviewer: Codex `gpt-6.1-sol`, high reasoning effort, through T3
`delegate_task`. Fresh context, read-only, a different model family from the
writer (Claude), against 315a0c2. Final report below, verbatim.

---

**Verdict: FAIL.** Mode: REVIEW. Reviewed the committed design at `315a0c2`; drafts were inspected for feasibility. No files changed and no tests run.

**Blockers**

- **B1 — Late bookings still grow an estimated charge between ACKs.** `docs/designs/stream-d.md:1901`; `factory/budget.py:269`, `factory/budget.py:304`; `factory/batch_accounting.py:138`.

  Excluding unchanged saved-ledger spending:

  1. The prior ACK contains A with $2 booked plus a $4 estimate, and B with a $10 estimate: total **$16**.
  2. A late $3 booking enters the ledger tagged to A. Its gap remains $4, so A’s charge becomes $9. Non-final replay preserves this: `booked_before` now includes $5, and the formula retains the $4 gap.
  3. A final receipt confirms A’s $5 booked usage. Settlement records a **$4 release**, although A dropped only **$1 relative to the ACK**.
  4. A subsequent snapshot also incorrectly lowers B’s estimate to $7. Its total is **$12**.
  5. Collection accepts the $4 aggregate decrease because A’s $4 release fits the prior ACK’s $4 estimate. B’s unsupported $3 reduction passes.

  `_extends` also permits these transitions. The frozen-charge premise therefore fails for explicitly supported late bookings, preserving round 7’s cross-invocation subsidy problem. Define and enforce charge preservation across booking ingestion, or validate decreases against per-invocation ACK evidence.

- **B2 — Later final receipts leave excessive historical release credit.** `factory/budget.py:308`; `factory/batch_accounting.py:131`; `tests/factory/test_batch_accounting.py:81`.

  Even without B1: ACK A at $6 ($2 booked, $4 estimated), then finalize at $2, recording a $4 release. Before another ACK, a later final receipt adds $3 usage. This supported settled-to-settled transition raises A to $5 but retains the original $4 release record: `previous_gap` is now zero, so settlement neither updates nor invalidates it.

  With B initially estimated at $10 and incorrectly reduced to $7, collection again accepts $16 → $12 using the stale $4 release, although A’s current legitimate decrease is only $1. `_releases` checks the record’s arithmetic and settled state, without reconciling its `actual_charge_usd` against current attributed bookings. Fixing estimated-state growth alone cannot establish the claimed ACK invariant.

**Majors**

- None independent of these blockers. The tests omit both failing collection sequences.

**Nits**

- None.

**Accounting and artifact assessment**

The closed gate is a sound conservative spending bound under its configured pricing contracts: requests reserve before forwarding; closure retains unfinished holds, rejects new requests, and prevents late completion from refunding retained holds. Freezing that ceiling does not itself permit unbooked spending above it.

The release/ACK reasoning is nevertheless false. Pending reconciliation, unchanged-evidence replay, and equal/higher finalization do not resolve the two cases above.

Row 8 has credible saved-artifact coverage for batch jobs: retained practice bytes and the captured 5813be ledger exercise the real accountant and binding migration. Row 21 has substantial coverage but cannot close yet. The late-booking test ACKs the intermediate increase (`test_batch_accounting.py:98`), while the frozen-estimate negative control adds no late booking (`test_batch_holder.py:282`). The later-final-receipt test checks growth only after replacing the ACK’s estimate map.

**Files read**

- `docs/ENGINEERING.md`, Murphy-register rows 8/21, committed `docs/designs/stream-d.md`, money-design reviews 1–7.
- Requested three personas; Heilmeier, implementation-readiness and zoom-out standards.
- Relevant portions of `factory/{budget,model_call_gate,model_runtime,run,diagnosis,batch_holder,batch_accounting,batch_money}.py`; draft diffs for `factory/batch.py`.
- `tests/factory/{test_stream_d_runtime,test_stream_d_projection,test_batch_accounting,test_batch_holder,test_stream_d}.py`.

---

## Elephant response

Both blockers are rejected as outside this increment. Under
`docs/ENGINEERING.md` section 1, the rejection goes to a second goldfish
from a different model family; its verdict is recorded below.

- **B1, rejected: the state is not produced by D.** The scenario needs a
  booking tagged to A after A is estimated, made outside `_settle_leaf`.
  D's only other booking path is the streaming accountant in
  `_run_budgeted` (`budget.py` `subscription_usage` and `consume_codex`).
  It appends each event and its row `event_ids` entry in the same save,
  and only while the process runs. `complete_invocation`, which first
  estimates the row, runs after the process ends. `settle` and
  `reconcile_reservations` run only from `run.resume_provider_wait`, which
  refuses while any call is active (`usage_reconciliation_while_active`).
  Every later event therefore enters through `_settle_leaf`, which keeps an
  estimated charge, so the release equals the drop from the last ACK. A
  ledger written by anything else is outside D's producer contract, and
  guarding against it is B's collection guard's job, as in B2.
- **B2, rejected: it predates this increment and is B's.** A settled row
  that grows through a later final receipt after its decrease record, before
  the next ACK, keeps that record. The record's credit can then cover a
  sibling's corrupted estimate. That is true on the committed code, which
  allows settled-to-settled growth by design
  (`test_batch_accounting.py::test_estimate_release_replay_then_growing_receipt`).
  The item-3 change neither creates nor widens it: final-receipt settlement
  and B's check are unchanged. Hardening the guard means checking each
  invocation against the prior ACK's own evidence, which needs per-invocation
  booked amounts in B's stored facts. That is a B schema change, handed to B
  in the stream report.
- **Overclaim fixed.** The design said B's check is now exact and that a
  release always equals the drop from the last ACK. It now states the D
  producer invariant and names B's known limits.

## Second goldfish (fresh Claude, adjudication)

Reviewer: a fresh Claude `general-purpose` subagent, read-only, a
different model family from the first goldfish (Codex), against 0617cae.
Final report below, verbatim.

---

**Verdicts:** REJECTION UPHELD for B1 and for B2. But the text the author used to reject B1, which the design repeats, contains a false premise that must be corrected. I rate that as Major, not blocking.

**B1: REJECTION UPHELD**

1. **Factual claim.** Mostly true, but the stated reasoning is wrong.
   - The accountant books only inside `_run_budgeted`, which runs synchronously (`model_runtime.py:640`). Each event is tagged and added to the row's `event_ids` in one save (`budget.py:930-932`, `1072-1074`). The process is stopped before the call returns.
   - `complete_invocation` runs after `_invoke` returns (`model_runtime.py:466-467`).
   - The rejection says `reconcile_reservations` runs "only from `run.resume_provider_wait`". That is false. It also runs:
     - at the start of every factory `_call` (`model_runtime.py:324-327`), excluding only active call names and the call's own lease;
     - in `finalize_accounting` (`run.py:2870-2875`), with no active-call guard and no dispatch lock;
     - in `diagnosis_dispatch.py:289-292`, which is guarded.
   - The `_call` path is still safe:
     - a call's name is active from before its process starts until after `run_budgeted` returns (`model_runtime.py:408-412`);
     - `run_budgeted` refuses a row that is not pending (`budget.py:805-807`).
   - The `finalize_accounting` path is not fully safe. An exam owner child call runs on a daemon HTTP thread that is not joined (`exam_responder.py:176-191`). If it is still running, `finalize_accounting` can estimate its row. The child's cancelled exit path then books partial usage, tagged, onto that estimated row (`budget.py:1230-1245` through `subscription_usage`).
   - This does not reach B1's harm. B1 also needs a final receipt that writes a release record. Cancel is always set before `finalize_accounting`, so the child ends `interrupted` and its receipt is non-final (`model_runtime.py:451-457`). The per-lease receipt is written once and never rewritten. The charge can grow, but no release record can subsidise another call.
2. **Scope.** Rows 8 and 21 need no hardening of B's guard against ledgers that D's own code never writes. Out of scope.

**B2: REJECTION UPHELD**

1. **Factual claim.** True.
   - `batch_accounting.py` is unchanged against both HEAD and `4f9f931`.
   - `_releases` checks a record's arithmetic and settled state only. It never compares the record against current bookings (`batch_accounting.py:131-139`).
   - Credit is counted across all calls together (`:160-163`).
   - Growth from settled to settled skips the record branch, because `previous_gap` is 0 (`budget.py:263`, `308`).
   - The committed test shows that growth (`test_batch_accounting.py:65-86`), driven by a receipt the test itself rewrites.
   - D never makes a second final receipt for a lease. The per-lease receipt is written once (`model_runtime.py:450`), leases are not reused (`budget.py:157-161`, `805-807`), and wait aggregates reuse the per-lease receipts (`run.py:255-261`).
   - The increment does make more rows `estimated` at a collection. But it adds no path that gives them a later final receipt, so the hole does not get wider.
2. **Scope.** Out of scope. The design now says B's check is unchanged and names B's known limits.

**New issue from the rejection text and the narrowed claim (Major, not blocking)**

Design, `_settle_leaf` paragraph:
- It says "`settle`/`reconcile_reservations` run only on resume with no active call". That is false (call sites above).
- It says "So D never grows an estimate between two collections". That is false in the `finalize_accounting` and owner-child race above. The growth is harmless to B, because it has no release record.
- Fix: state the true reasons, which are per-call exclusion, the pending check, and that a call still running at `finalize_accounting` ends non-final. Or pass `exclude_calls=c.active_model_calls` in `finalize_accounting`, which is one line.
- Smaller inconsistency: the late-booking test drives a transition the text says D never produces. That is fine as a defensive test, but it should be labelled as one.

**Files read**
- `docs/ENGINEERING.md` sections 1–2, `tools/egm/agents/zoom_out.md`, `tools/egm/agents/design_critic.md`
- `docs/designs/stream-d.md` (third increment), `docs/reviews/stream-d-money-design-6-codex.md`, `-7-codex.md`, `-8-codex.md`
- `factory/budget.py`, `factory/model_runtime.py`, `factory/run.py`, `factory/batch_accounting.py`, `factory/batch_holder.py`, `factory/diagnosis_dispatch.py`, `factory/exam_responder.py`, `factory/gate_pipeline.py`
- `tests/factory/test_batch_accounting.py` at HEAD
- Diffs against HEAD and `4f9f931`

---

## Elephant response to the second goldfish

B1 and B2 are dropped. The Major is accepted and fixed in the design text:
the `_settle_leaf` paragraph now names the real reasons (the pending check
in `run_budgeted`, the per-call exclusion in `_call`'s reconcile, the
active-call refusal on resume) and the one exception (the exam-owner child
still running at `finalize_accounting`, which ends non-final and never
writes a release record). The late-booking test is labelled defensive. The
one-line `exclude_calls` alternative is not taken: it would leave that row
pending on the final card, which changes the card for no gain. The B
hardening (per-invocation ACK evidence) is handed to B in the stream report.
