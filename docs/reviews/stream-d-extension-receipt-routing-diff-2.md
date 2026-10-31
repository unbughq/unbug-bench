# Goldfish diff review 2: stream D extension receipt routing (`3123ac0..HEAD`)

**PASS.** I checked each of the four blockers myself instead of taking the writer's word for them. Each surviving mutation now makes a new test fail, and it fails at the case meant to catch it. There is no production change since `dea2e22`. The full-suite record matches the source commit and its log. No blocking finding is left open.

## Scope

- **Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-4ac6b632`, branch `t3/stream-d-gates`, HEAD `5c526dc`.
- **Mode:** REVIEW, with personas `zoom_out` and `implementation_readiness`, against `implementation-readiness-standard.md`.
- **Reviewed against:** `docs/designs/stream-d-extension-receipt-routing.md`, and the diff-1 review with its response.
- **Changes since diff-1:**
  - `ec5620a`: tests only, +42/−1 in `tests/factory/test_stream_d_admission.py`.
  - `5c526dc`: the suite record only.
  - `git diff dea2e22..HEAD -- factory/` is empty, so production code is unchanged.
- **What I ran:** I ran the focused test file in a `git archive HEAD` copy under a temp directory: 37 tests, OK. I then ran the mutations in that copy. I modified no repo files, deleted the temp copy afterwards, and did not run the full suite.

## Blocker verification (mutation probes)

| Mutation | What I removed | Result | Test that caught it |
|---|---|---|---|
| **M2** (as diff-1 defined it) | The reservation check (`writer_continuation(c, {**current,'phase':'pending'}, name)`), for finished phases only; pending receipts still checked | 1 FAIL | `test_writer_selector_checks_finished_reservations_binding_and_phase`, line 450: a completed receipt carrying the foreign operation's lease and invocation was not refused |
| M2, stronger | The same check for every phase | 3 FAIL | The new test above, plus the existing damage subtests for `extension_id` and `invocation_id` |
| **M8** | The rule that finished receipts need string lease and invocation (`if False and not (...)`) | 1 FAIL | `test_finished_writer_cannot_borrow_pending_wait_archive_proof` |
| **M1** | The rule that a pending receipt on its original lease keeps its original binding | 1 FAIL | The new finished-reservations test, on the changed binding with a recomputed hash |
| **M5** | The phase allowlist | 1 FAIL | The new finished-reservations test, on `phase='abandoned'` |

**Why each failure is the right one:**

- **M1 and M5 are isolated.** `writer_continuation` (`extensions.py:235-256`) never compares bindings. `binding` is outside the frozen fields, so the frozen-field check misses the M1 change too. The receipt with the recomputed hash also passes `_writer_shape`. That leaves only M1's own check to refuse it.
- **`abandoned` reaches only M5's check.** The receipt has string leases, so it passes the finished-string check. It then passes `writer_continuation`, which is forced to pending. Only the allowlist can refuse it.
- **M8 is isolated by the wait-proof test.** That test first asserts `provider_continuation` is true for the archived wait. So once the M8 rule is removed, a finished receipt with a null lease would be accepted through the forced-pending continuation. That is exactly the gap M8's rule closes.
- **M2's foreign case is a real foreign reservation.** It comes from a real `reserve_invocation` with a fresh operation UUID and `call_name='builder-1'`. `release_uninvoked` keeps the reservation row in the ledger, so the selector refuses on the operation ID, not because the reservation is missing.
- **Nothing is written on refusal.** Each refusal also asserts that the attack file, intent, history and ledger are unchanged at the byte level.

## Prior nits

- **Nit 2 (fixed).** The intent is restored before the `round=True` and `round=2` stress controls. Those controls are now refused on the receipt check, not because the intent is missing.
- **Nit 3 (fixed).** Changing `round` now also updates `report`, so those cases reach the round binding check.

## Evidence

- The record `full-suite-20261031T114459Z-44116c99.json` shows `source_sha` `ec5620a`, exit 0, and "157 test scripts run; 0 failed".
- The uncompressed log's SHA256 is `10fad410…c332`, which matches `log_sha256`.
- The log shows `test_stream_d_admission.py` ran 37 tests, OK, which matches my focused run.
- `ec5620a..HEAD` changes only the record and its log, so the record covers the reviewed code.

## Findings

1. **Nit (test redundancy)** in `test_writer_selector_checks_finished_reservations_binding_and_phase`, the finished `lease_id=None, invocation_id=None` subcase without a wait. Two checks refuse it: the finished-string rule and the pending continuation, which has no wait proof here. So it catches neither mutation alone. It is harmless, because the wait-proof test isolates M8. Optional: drop it or comment it.
2. **Nit (coverage, outside the blockers).** No finished-receipt case uses a reservation with the right operation but a different `call_name`. That check sits in existing `writer_continuation` code that pending receipts already use, so it is not a gap this increment opened. It is optional, and fits better with the package-routing increment.

## Zoom-out / readiness

- **No new mechanism.** The fix adds one small shared assert helper and two tests, with no new module or fixture generator. It runs on the saved practice-case setup that the design names.
- **Scope matches the design.** No Murphy row is claimed. `writer_receipt` still has no production caller. The future package-router obligations are still recorded in the design.

## Objections

None. Blocker 1 from diff-1 is resolved, and it is ready to merge once this review is saved.

## Implementation response

PASS accepted. The fresh reviewer independently reproduced failures for M1, M2, M5 and M8, closing diff-1 blocker 1. Retain the redundant null-without-wait refusal as a boundary control; the archived-wait test supplies independent M8 coverage. Defer the optional right-operation/wrong-call finished-receipt control to package routing, which already owns that integration boundary. No production or test changes follow this review. Both full-suite records are retained. No Murphy row closes. No merge into factory-simplify or push was performed.
