**Verdict: PASS.** 0 blockers, 2 majors, 5 nits. Neither major is a blocker under `docs/ENGINEERING.md` "What counts as passing" or the earlier stream-d reviews. Both should be fixed before a caller is wired.

I wrote nothing, committed nothing, ran no tests or suite, and launched nothing. My evidence comes only from reading the design at `4b64541` and the code at that commit.

---

# Review: stream-d extension-admission design 1. PASS (0 blockers, 2 majors, 5 nits)

**Reviewer:** fresh goldfish, read-only. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier, implementation-readiness and zoom-out.
**Scope:** `8f980b2..4b64541`: the new file `docs/designs/stream-d-extension-admission.md`, plus a 4-line pointer in `docs/designs/stream-d-worker-dispatch.md`. Branch `t3/stream-d-implementation`, worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`.
**Code read:** `factory/run.py:323–364` (`pending_call`), 1060–1300 (writer receipt and resume), 1258–1270 and 1408–1418; `factory/extensions.py` (whole file); `factory/budget.py:138–175` (`reserve_invocation`), 374–400 (`release_uninvoked` and `reconcile_reservations`); `factory/model_runtime.py:247–290` and 360–420; `factory/job_authority.py:15–80`; `factory/diagnosis.py:30–70` and 382–404; `factory/diagnosis_dispatch.py:215–300`; `tests/factory/test_stream_d_extensions.py:1–60`; `tests/factory/test_stream_d_runtime.py:46–60`; and the prior review `docs/reviews/stream-d-worker-dispatch-design-1.md` (B1, B2, M5, M6, N3, and the elephant response and round-2 revision).

## Summary

The design answers the first-admission half of B1, and the order it gives matches the code:

1. Authority (`run.py:331`).
2. A check on the proposal before the lease is requested.
3. The lease (`run.py:332`).
4. The route maximum.
5. A second verification after the lease wait.
6. The unchanged `reserve_invocation`.
7. `admit`.
8. The receipt and `builder_rounds`.
9. `on_admitted`.
10. The `opencode` call.

On money:

- **Attribute bypass removed.** Deleting the `getattr(c, 'active_extension_id')` test (`run.py:338`), the only reference in `factory/` and `tests/`, closes the mutable bypass. Ordinary writers now always get the ordinary check.
- **Forged proposal cannot skip the limit.** It must equal a fresh `extensions.propose` result, including `extension_id`, `round`, `entry` and `exhaustion_id`.
- **B's cumulative commitment still applies.** It is enforced only inside `reserve_invocation`, against `committed_total_usd`, known spending and outstanding reservations (`budget.py:159–161`), and the design leaves that function unchanged.
- **No other ordinary-limit check blocks the extension writer.** The wrapper's fallback reservations (`model_runtime.py:390`) also check against the commitment, not the ordinary limit, because `update_case_budget` sets `limit_usd` from `authority.committed_total_usd`. The modern writer loop has no in-loop ordinary check (`run.py:1267` applies only when `not modern`).

**What happens when admission is refused or interrupted:**

- **Refusal before `admit`:** this falls into the existing `except BaseException` branch. That branch calls `release_uninvoked`, which settles the reservation at zero cost.
- **Process death after reservation:** `reconcile_reservations` books the full maximum. The design states this, which carries over the earlier N3.
- **Failure inside `admit` before history is written:** `_save_case` stages its snapshot copy in a temporary directory, so the failure leaves no history, and the reservation is released.
- **Failure after history is written:** the design keeps the extension ID and refuses a repeat. A repeat cannot get past `verify_proposal`, because `propose` raises `extension_already_active` (`extensions.py:238`). `admit`'s idempotent path for an active row is never reached from this seam.

**Tests.** The tests use the real ledger, router, snapshot copy and reconciler. Only the CLI and transport are substituted. One test mutates state during `await_lease`; the check that kills it is observable, because without the second verification the ledger would contain a reservation row for that lease (released or settled). The test list covers the important failure classifications.

**Scope.** I found no contradiction with current caller semantics. No production caller passes the new argument. The diagnosis dispatcher still stops with `extension_comparison_pending` (`diagnosis_dispatch.py:30`).

**Open items, still open:** active continuation (the remainder of B1), B2, M5 and M6. This seam does not make any of them impossible:

- The new `extension_id` receipt field does nothing until a reader uses it.
- History remains the authority.
- A later reconstruction or continuation path can still reuse the stored round and operation with a new lease, because `reserve_invocation` keys rows by lease.

## Majors

### M1. First admission can inherit an earlier writer's operation UUID (zero-decision gap on money identity)

- **Where:** design step 3 ("Scope the existing operation UUID exactly as today"), lines 29–34; and `run.py:333` (`operation = receipt.get('operation_id') or str(uuid.uuid4())`).
- **What the code does:** the modern writer loop builds `writer_receipt = {**resume_unit, **writer_receipt}` when a pending writer receipt for the same round exists (`run.py:1281–1282`). A pending ordinary writer for round R can be left over if the process died after `admitted()`. If the checkpointed `builder_rounds` is still R-1, `propose` gives round R. The design rejects only receipts marked `completed` or `validated`, so a `pending` receipt that carries operation X is accepted.
- **Consequence:** the first extension then has `writer_operation_id = X`. That operation already owns a settled, conservatively booked ordinary reservation for `builder-R`. Three things go wrong:
  1. `extensions.read`'s check that "the private round cannot be relabelled without its retained operation" (`extensions.py:114–121`) can be satisfied by the pre-extension reservation alone.
  2. Factory-bug waste attribution is grouped by `operation_ids` (`budget.py` `reclassify_factory_bug`), so it would merge ordinary and extension spending.
  3. `admit` refuses an operation only if it is already used by another history row (`extensions.py:275`), not one used by an ordinary writer.
- **Required:** decide this in the design. Either:
  - **(a)** first admission requires a receipt with no `operation_id` and no `phase`, and always generates a fresh UUID. Add a test where a pending receipt carrying an operation refuses before the lease, with the label `extension_reservation_mismatch`; or
  - **(b)** explicitly adopt the pending ordinary operation, and state why the attribution and history binding remain sound.

  Option (a) is smaller and matches "one extension, one operation".
- **Not reachable today**, because there is no production caller. It must be closed before wiring.

### M2. Which refusal label each evidence-read failure gets is incomplete

- **Where:** design lines 41–51.
- **What the code does:** `diagnosis._input_bytes` raises:
  - `ValueError('unsafe input path')` for an ancestor or final-component symlink;
  - `ValueError('nonregular input')` for a file that is not a regular file;
  - `FileNotFoundError` for a missing file;
  - `OSError(ELOOP)` when a final-component symlink appears between the `is_symlink` probe and the `O_NOFOLLOW` open.
- **The gap:** the design maps "missing" to `extension_snapshot_changed`, malformed proposals to `extension_reservation_mismatch`, and other filesystem failures to "propagate as infrastructure". It does not map either `ValueError` case. The test list says "symlinked evidence refuse[s]" without giving a label, and ELOOP would currently propagate as infrastructure.
- **Required:** state one label for symlink and non-regular evidence. `extension_snapshot_changed` would be consistent with `_save_evidence`, `extensions.py:209–210`. Also say whether ELOOP counts as that label. Test the label.
- **Safety:** every branch refuses before reservation, so no option is unsafe. This is a readiness gap only.

## Nits

- **N1. "Read-only" is slightly overstated.** `verify_proposal` calls `propose`, which calls `read(c)`, which rewrites `c.card['extension_history']` (`extensions.py:155`). Say "writes no file" instead. The design runs `read` three times per admission: before the lease, after the wait, and inside `admit`. Each pass re-hashes every retained snapshot tree. The cost line ("two bounded reads of the current case/evidence") should also count the history-verification reads.
- **N2. Trust root for eligibility.** The bypass depends on the card's `diagnosis_state` being `completed`/`close_to_passing` with a valid `_trigger`. It does not depend on the retained `decision.json`. That card comes from B's authenticated restore, and its only producer is `diagnosis_dispatch.apply`, so this is acceptable. State it, so that a future card writer cannot become an ordinary-limit bypass without anyone noticing. The money exposure would still be capped by B's commitment.
- **N3. Ledger state after a failed history publication.** If `admitted()`'s receipt write raises `OSError` after `admit` has published history, the existing handler calls `release_uninvoked`. The admitted row's operation is left with only a settled zero reservation. That is correct accounting and a future continuation can reserve again. Still, add an assertion on the ledger row state to the publication-interruption test, so that an implementer does not "keep" the reservation pending instead.
- **N4. Evidence names that admission itself rewrites.** `validate_snapshot` allows any name under `c.work` except `case/` and `extension-snapshots/`. That includes `attack-state.json`, `extension-history.json` and, in the harness, `ledger.json`, which is in `c.work`. Such a snapshot passes both pre-reservation checks and then fails in `_save_evidence` after reservation, which releases at zero. This is harmless now. Note it for the future stage producer, or forbid those names alongside the M5 receipts.
- **N5. Heilmeier and pointer housekeeping.** The design gives no timeline. Add one line, for example "one implementation increment plus a diff review". When this passes, the pointer in `stream-d-worker-dispatch.md` (lines 429–431) still says "awaiting design review" and should be updated in the same commit as the response.

## Scope confirmation

- **Excluded from this increment and still open, as stated:** B1 active-extension resume, B2 disposable comparison isolation, M5 exact scientific stage receipts, and M6 continuation routing. Nothing in this seam rules them out. The pre-existing case where a pending ordinary writer stays stuck after builder rounds are exhausted is continuation territory, and M1 does not ask for it to be solved here.
- **Murphy register:** no row closes. Stage receipts are authored, and the dispatcher, isolation, live provider and B runtime remain unqualified. `DIAGNOSIS_ENABLED` stays false.
- **Interfaces:** no new public field, auth change, module or dependency. The removed attribute has no other reference.

## Validation boundary

This review covers design readiness only, at `4b64541`, from reading the code at that commit. I ran no tests and no full suite, and I make no claim about either. I made no model, cloud or launch calls, did no decryption, and wrote nothing.

## Elephant response

*(to be completed by the elephant)*

## Elephant resolution

Accepted both majors and all five nits; none rejected. The implementation has
not started. A fresh focused design review will check this amendment first.

- M1: first admission rejects either `operation_id` or `phase` key, including
  null values, before any lease. It generates a fresh operation UUID. The test
  explicitly supplies an already-settled ordinary operation in a pending receipt
  and requires `extension_reservation_mismatch`; ordinary operation adoption is
  not permitted.
- M2: missing, unsafe/symlinked and nonregular evidence, including no-follow-open
  ELOOP, is `extension_snapshot_changed`. The read handler is separate from shape
  validation. Other read I/O remains infrastructure. Tests pin both labels.
- N1: changed the claim to “writes no files,” documented the public projection
  normalization, and included retained-history verification in the cost.
- N2: documented the authenticated-card/current verified `apply` trust root.
  This helper adds no independent decision reader or new diagnosis producer.
- N3: handled publication failures must leave the demonstrably uninvoked
  reservation settled at zero, even with retained history. Added the assertion;
  a process-death test still conservatively books its maximum.
- N4: recorded admission/accounting-file exclusion as a requirement for the
  future scientific stage producer. This seam retains existing snapshot rules.
- N5: added the one-increment-plus-review timeline and updated the parent pointer.

Active-extension recovery, B2 and extension M5/M6 remain open. No Murphy row
closes and no production caller, activation, launch or money authority is added.
