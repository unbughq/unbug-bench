# Goldfish design review 6 (Codex): stream D item 3, money cleanup

Reviewer: Codex `gpt-6.1-sol`, high reasoning effort, through T3
`delegate_task`. Fresh context, read-only, a different model family from the
writer (Claude), against 1397efb. Final report below, verbatim.

---

**Verdict: FAIL.** Mode: REVIEW. Reviewed the committed design at `1397efb`; drafts were inspected for feasibility. No files changed and no tests run.

**Blockers**

- **B1 — Reconciliation can produce a valid final decrease that collection permanently rejects.** `factory/budget.py:415`, `factory/budget.py:308`, `factory/batch_accounting.py:138`; design `docs/designs/stream-d.md:1901`.

  Concrete scenario, amounts relative to the unchanged saved ledger:
  
  1. A $10 reservation has $2 booked and a closed-gate bound of $6. Settlement produces a $4 gap; the host ACK records total $6 and estimated gap $4.
  2. On resume, the supported missing-receipt reconciliation branch supplies a synthetic leaf without a gate snapshot. Settlement raises the gap to $8, charging $10. This intermediate state is never ACKed.
  3. A final receipt confirms the original $2 charge. Settlement correctly records an $8 release.
  4. `collection_facts` discards that release because $8 exceeds the previously ACKed $4 gap. It then rejects the legitimate $6 → $2 decrease as `unsupported_decrease`.

  `_extends` accepts the final generation because a decrease record exists, but collection rejects it. Replaying final settlement cannot repair the record: the reservation is already settled with zero gap.

  Specify how release provenance works when an estimate increases between ACKs—for example, qualifying release credit bounded by the prior ACK’s estimate—or explicitly prevent that supported transition. Add a saved-ledger test spanning the prior ACK, resume reconciliation, final settlement and holder collection.

**Majors**

- None separate from B1.

**Nits**

- None.

**Round-5 fixes**

B1 holds for the reported late-booking case: `booked_before` now includes both listed events and events tagged to the reservation. Non-final replay preserves that charge.

M1 holds: `_extends` compares the same event-plus-gap charge and accepts equal/higher finalization without a decrease record.

M2’s named tests exist and exercise provider-wait replay, late bookings, lower/equal/higher final receipts, and actual holder incident recovery. They do not cover the estimate-growth-between-ACKs scenario above.

N1 holds: the runtime test module docstring now names rows 8 and 21.

**Artifact assessment**

Row 8 has credible saved-artifact coverage for batch jobs: retained practice bytes and the captured 5813be ledger pass through the real accountant, with factory cap selection and binding migration checked.

Row 21 has substantial saved-artifact coverage, including the new settlement and incident tests, but its accounting proof remains incomplete because of B1. It should remain open. These conclusions come from inspection, not test execution.

**Files read**

- `docs/ENGINEERING.md`, `docs/murphy-register.md` rows 8/21, committed `docs/designs/stream-d.md`, money-design reviews 1, 2, 3-Claude, 4-Codex and 5-Codex.
- All three requested personas; Heilmeier, implementation-readiness and zoom-out standards.
- `factory/{budget,model_call_gate,model_runtime,run,diagnosis,batch_holder,batch_accounting}.py`.
- Relevant portions of `factory/{batch,batch_money,key_holder,ttl_continuation,restart,coordinator,gate_state,g11_review,carry_over,durable_checkpoint,restore_ledger}.py` and `factory/launch.sh`.
- `tests/factory/{test_stream_d_runtime,test_stream_d_projection,test_batch_accounting,test_batch_holder,test_stream_d}.py`.

---

## Elephant response

- **B1, accepted and fixed at the collection check.** Any non-final
  evidence can raise an estimate between two ACKs, not only the
  missing-receipt reconciliation: a replayed receipt with no gate snapshot
  falls back to the maximum too. So the fix is not to block that one
  transition. `batch_accounting.collection_facts` (B-owned, two lines) now
  keeps every valid decrease record for an invocation the prior ACK
  estimated, and credits each one up to the estimate that ACK saw, not its
  full release. Bound events are append-only, so a final charge cannot fall
  below what the prior ACK had booked, and the drop from the prior ACK is at
  most its estimate. The credit is never larger than before this change.
  Before, a record was either credited in full when it fit under the prior
  estimate, or dropped. Now an oversized record is credited at the prior
  estimate. `test_batch_holder.py::
  test_estimate_grown_after_ack_then_final_decrease_collects` runs the
  reviewer's scenario through the holder: the first ACK at the $4 gate
  estimate, then resume reconciliation without the receipt file ($8), a
  final receipt releasing $8, and the second collection crediting $4. On
  the committed `batch_accounting.py` it fails with `unsupported_decrease`.
  It passes on the change.

A fresh design review 7 follows.
