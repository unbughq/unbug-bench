# Goldfish design review 7 (Codex): stream D item 3, money cleanup

Reviewer: Codex `gpt-6.1-sol`, high reasoning effort, through T3
`delegate_task`. Fresh context, read-only, a different model family from the
writer (Claude), against 80ee396. Final report below, verbatim.

---

**Verdict: FAIL.** Mode: REVIEW. Reviewed the committed design at `80ee396`; implementation drafts were inspected for buildability. No files changed and no tests run.

**Blockers**

- **B1 — The new aggregate release credit can admit an unsupported decrease.** `factory/batch_accounting.py:164`; `docs/designs/stream-d.md:1928`.

  The round-6 scenario now collects correctly, but the stronger claim—“never lets an unsupported decrease through” and “no looser than before”—does not hold.

  Concrete counterexample, excluding unchanged saved-ledger spending:

  1. The prior ACK contains invocation A with $2 booked plus a $4 estimate, and invocation B with a $5 estimate: total **$11**.
  2. Without another ACK, missing-receipt reconciliation raises A’s estimate to $8. A subsequent nonfinal receipt imports $3 more usage, preserving A’s $10 charge as $5 booked plus a $5 estimate.
  3. A final receipt confirms A’s $5 booked charge. `_settle_leaf` legitimately produces a **$5 release**. Relative to the prior ACK, however, A decreased only **$1**.
  4. A corrupted subsequent snapshot also lowers B’s estimate from $5 to $2 without final evidence or a decrease record. All booked events remain append-only. The resulting total is **$7**.
  5. Collection credits `min($5, $4) = $4`, accepting the entire $11 → $7 decrease, including B’s unsupported $3 reduction.

  The previous implementation discarded A’s oversized release and rejected this snapshot. The new check therefore expands acceptance beyond the intended legitimate transition. This does **not** require forging A’s reconciliation record. The unsupported B mutation is precisely an accounting regression the collection guard should detect; `_extends` also permits estimated → estimated without comparing charges (`factory/batch_holder.py:421`).

  Compare reservation charges against the immediately prior ACK’s immutable evidence, including attributed booked growth, so one invocation’s release cannot subsidize another invocation’s unsupported reduction. Add a two-invocation negative control alongside the new positive holder test.

**Majors**

- None separate from B1.

**Nits**

- None.

**Accounting and artifact assessment**

The honest producer transitions inspected are consistent: late bookings contribute to the previous charge; nonfinal replays preserve it; missing receipts can raise estimates; equal/higher final receipts need no release record; and later ACKs stop crediting already-settled invocation IDs. The new holder test covers the reported round-6 failure.

Row 8 has credible saved-artifact coverage for the explicitly scoped batch behavior, using retained practice bytes and the captured ledger with the real accountant. Row 21 has substantial saved-artifact coverage for settlement, retry, admission and collection, but the tests do not establish the collection safety claim because they omit B1’s mixed-invocation negative case. Closure should wait for that correction. These are inspection conclusions, not execution results.

**Files read**

- `docs/ENGINEERING.md`, `docs/murphy-register.md` rows 8/21, committed `docs/designs/stream-d.md`, money-design reviews 1, 2, 3-Claude, 4-Codex, 5-Codex and 6-Codex.
- Requested three persona files; Heilmeier, implementation-readiness and zoom-out standards.
- Relevant portions of `factory/{budget,model_call_gate,model_runtime,run,diagnosis,batch_holder,batch_accounting,batch_money,batch,batch_service,key_holder,coordinator,ttl_continuation,restart,carry_over,gate_state}.py` and `factory/launch.sh`.
- `tests/factory/{test_stream_d_runtime,test_stream_d_projection,test_batch_accounting,test_batch_holder,test_stream_d}.py`.

---

## Elephant response

- **B1, accepted. The round-6 fix is withdrawn and replaced at the
  producer.** The credit `min(release, prior estimate)` measures a release
  from the wrong baseline, so one call's release can cover another call's
  unsupported drop, exactly as the counterexample shows.
  `batch_accounting.py` is reverted to the committed code: a release larger
  than the prior ACK's estimate is again dropped.

  The round-6 problem came from estimates that grow between ACKs. They no
  longer grow. Once a reservation is `estimated`, its charge is already a
  ceiling: the closed gate's bound, or the full maximum when there is no
  snapshot. `_settle_leaf` now keeps that charge for every non-final
  receipt, synthetic reconciliation leaves included. Only booked usage
  above the charge raises it, and then the gap is zero. So an estimated
  row's charge at the next final receipt equals its charge at the last ACK,
  or exceeds it with a zero gap. The release then equals the drop from that
  ACK, and the committed per-invocation check applies unchanged.

  `test_batch_holder.py::test_estimate_frozen_across_resume_then_final_decrease_collects`
  replaces the round-6 test. The first ACK sees a $4 gate estimate and a
  second call's $10 estimate. A resume without the receipt file keeps the
  $4, and the final release is $4, which collects. The negative control
  lowers the second call's estimate to $7 without a final receipt.
  `collection_facts` against the first ACK refuses it with
  `unsupported_decrease`. With the round-6 settle rule, the test fails
  because the estimate grows to $8.

  The `_extends` estimated → estimated case is unchanged on purpose.
  `_extends` only decides whether a refused generation may be cleared. The
  same `collect` call then runs `collection_facts` on the new card, which
  refuses an unsupported decrease, as the negative control shows.

A fresh design review 8 follows.
