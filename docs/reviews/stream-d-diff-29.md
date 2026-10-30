**PASS: 0 blockers, 0 majors, 2 nits.** The seam matches design 2 and the claims in the commit hold up when tested. I wrote nothing to the worktree. All runs used a `git archive 407c636` export in scratch.

- **Tests:** the 18 admission tests pass in that export (Python 3.14.6, macOS, 4.5 s).
- **Mutants:** 14 of 15 targeted mutants were killed. The one survivor is guarded by an earlier check, so it doesn't count against the tests.
- **Probe:** one probe found nit N1. A receipt with no `binding` field passes the checks before the lease, publishes history, then fails with `KeyError` and uses up an extension ID.
- **Full suite:** not run by me. It is still running in your log.

Text ready to save as `docs/reviews/stream-d-diff-29.md`:

---

# Review: stream-d diff 29. PASS (0 blockers, 0 majors, 2 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`, no history. Personas: zoom_out, implementation_readiness. Standards: zoom-out, implementation-readiness.

**Scope:** `17fa9fe..407c636`, one commit, "Verify first extension admission before writer reservation":
- `factory/extensions.py`: adds `verify_proposal`.
- `factory/run.py`: the `pending_call` extension branch.
- `tests/factory/test_stream_d_admission.py`: 18 tests.
- `docs/designs/stream-d-extension-admission.md`: the EISDIR boundary and the implementation boundary.
- The parent pointer in `stream-d-worker-dispatch.md`.

`.stream-d-next/` was excluded.

**Read:** `docs/ENGINEERING.md`, design reviews 1 and 2 verbatim (including the elephant responses), the full admission design, `run.py:323–383`, and the following in `extensions.py`: `propose`, `admit`, `read`, `verify_proposal`, `_save_case`. Also `diagnosis._input_bytes`, the writer-receipt producers in `run.py` (around lines 1085 and 1311), and the new test file.

## Summary

### Guard order matches design steps 1–8

1. Resume and authority.
2. The receipt contract, then a deep copy of the proposal, then `verify_proposal`, then the round and name checks. All of this runs before `await_lease`.
3. The lease, then a fresh UUID, then the operation is scoped.
4. The maximum, then `verify_proposal` again on the local copy.
5. The unchanged `reserve_invocation`.
6. `extensions.admit`.
7. `receipt['extension_id']`, then `admitted()`. This writes the schema-2 attack receipt and `builder_rounds`.
8. `on_admitted`, then the unchanged `opencode` call with `before_attempt=admitted`.

### Ordinary and stress callers are unchanged

- `on_admitted` still runs before `admitted()`.
- The operation is still reused from the receipt.
- The `except` and `finally` blocks are unchanged.
- `active_extension_id` is gone from `factory/`. Its only remaining reference is the forged-attribute test.

### Money authority is unchanged

- The extension branch skips only the ordinary-limit check, and only after `verify_proposal` succeeds twice.
- The batch's committed total, unknown spending, outstanding reservations and deadline are still enforced by the unchanged `reserve_invocation`. The tests check this with `money_wait` for over-commitment and for unknown spending.
- The fallback path checks the same commitment and does not call `admit` again. The test sees one history row and two reservation rows with the same operation and `builder-1`.

### First-operation identity

- All 7 admission-owned keys are refused before the lease, including null-valued ones. This is tested per key.
- The pending/settled operation the design required in its adoption test is refused.
- The branch always generates a fresh UUID.
- The previous `model_operation_id` is restored after both success and failure.

### Failure classification

| Failure | Label |
|---|---|
| Malformed envelope | `extension_reservation_mismatch` |
| Malformed entry | `extension_snapshot_invalid` |
| Missing or unsafe evidence: `FileNotFoundError`, `ValueError`, `ELOOP`, `ENOTDIR`, `ENXIO`, `EISDIR` | `extension_snapshot_changed` |
| `PermissionError`, `EIO` | Propagated as infrastructure, before any lease |
| Snapshot or publication write errors | Propagated as `OSError` |

- **Shape vs read handlers:** they are separate. A reader's `ValueError` cannot be relabelled as a malformed proposal.
- **EISDIR:** narrow. `os.open` with `O_RDONLY|O_NONBLOCK` succeeds on a directory, and `fdopen` then raises `IsADirectoryError`. The shared reader is unchanged.

### Publication failure and crash accounting

- A failure after history is published, or during the attack-receipt write, keeps one history ID.
- The uninvoked reservation is left `settled` with a gap of `0.000000000`.
- No writer and no callback run.
- A fresh first admission is then refused with `extension_already_active`.
- The captured crash image after reservation is reconciled at the baseline plus the full maximum, with no history created.

### Scope and wiring

- The AST test confirms that no production caller passes `extension_proposal`.
- `DIAGNOSIS_ENABLED` is unchanged.
- No new module, flag, field, launch path or money channel was added.

### Future work is not blocked

- B1 continuation, B2, M5 and M6 remain open and unqualified.
- Nothing here blocks them:
  - the settled reservation row still binds the history operation;
  - `extension_id` in the receipt is inert;
  - `reserve_invocation` keys rows by lease, so continuation can reserve a new lease.

## Mutation evidence

15 single-site mutants were run against the admission module.

**Killed (14):**
- Remove the post-lease `verify_proposal`.
- Remove the pre-lease `verify_proposal`.
- Remove the deep copy.
- Restore the `active_extension_id` bypass.
- Shrink the owned-key set to `{operation_id, phase}`.
- Run `on_admitted` before `admit`.
- Drop `EISDIR`.
- Drop `ENOTDIR`.
- Map every `OSError` to "changed".
- Drop the source-generation check.
- Drop the case-digest check.
- Drop the evidence-hash check.
- Drop the strict-int check on `extension_id`.
- Drop the round/name check.

**Survived (1):** adopt `receipt.get('operation_id')` instead of the fresh UUID. This is unobservable, because the owned-key guard (a killed mutant) already refuses any `operation_id`. Each guard on its own was not required to be killed.

## Nits

### N1. The receipt contract before the lease does not cover `binding`

- **Where:** `run.py:336–339` and `run.py:367`.
- **What happens:** a writer receipt with no `binding` passes every check before reservation. `admit` then publishes history, and `admitted()` raises `KeyError('binding')`.
- **Probe result** (over the same fixtures):
  - one history row is retained;
  - the reservation ends `settled` at zero;
  - there is no writer;
  - the error is reported as a plain `KeyError`;
  - one of the 5 extension IDs is used up until continuation recovery exists.
- **Impact:** there is no production caller, and the writer-loop producers always build `binding`.
- **Suggested fix:** before wiring, add a check for `isinstance(receipt.get('binding'), dict)` (or the exact producer shape) to the pre-lease refusal as `extension_reservation_mismatch`. Alternatively, compute `binding_sha256` before `admit`.

### N2. The fresh-UUID expression is untested on its own

- **What happens:** the adoption guard is proven through the key refusal. The fresh-UUID ternary at `run.py:346` has no separate test, and it survives mutation.
- **Why it's acceptable:** the observable contract (never adopt) holds.
- **Optional fix:** assert that the history operation differs from any `operation_id` an ordinary caller could supply. Alternatively, drop the ternary and rely on the guard.

## Validation boundary

**Ran:**
- `python3 -m unittest tests.factory.test_stream_d_admission` on an export of `407c636` in scratch: 18 tests, OK.
- 15 source mutants against that module, as listed above.
- One extra probe test, for nit N1.

**Did not run:**
- The full suite. The parent is running it on `407c636` in `/tmp/stream-d-admission-suite.log`, and its result is not claimed here.
- The combined 100-test focused run. The parent's log `/tmp/stream-d-admission-focused.log` shows "Ran 100 tests … OK", but I did not reproduce it.

**Not qualified:** stage receipts and money envelopes are authored. The live provider, Unix isolation, B activation, continuation (B1 remainder), B2, M5 and M6 are not qualified. No Murphy row closes.

**Other:** no model, cloud or launch calls; no decryption; no secrets; no writes, commits or merges to the worktree or the parent checkout.

## Elephant response

*(to be completed by the elephant)*

## Elephant resolution

Accepted PASS. N1 is accepted for a small follow-up before any caller is wired:
require a dictionary `binding` in the pre-lease receipt contract, with a control
that missing/non-dictionary binding creates no lease, history or reservation.
The current full suite remains on the reviewed `407c636` source; the follow-up
will receive its own suite and fresh diff review.

N2 is optional and deferred. Keep the explicit fresh-UUID expression because it
states first-admission intent, while the tested owned-key refusal proves the
observable non-adoption contract. No independently redundant guard-killing test
is claimed or required. No finding is rejected. Active continuation, B2, M5 and
M6 remain open; no Murphy row closes and no activation is enabled.
