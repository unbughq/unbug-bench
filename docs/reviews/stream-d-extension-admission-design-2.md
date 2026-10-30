**PASS: 0 blockers, 0 majors, 4 nits.** Both majors from review 1 are fixed, and the amendment adds no contradiction or regression in the seam. I wrote nothing and ran nothing. The text below is ready to save as `docs/reviews/stream-d-extension-admission-design-2.md`.

---

# Review: stream-d extension-admission design 2. PASS (0 blockers, 0 majors, 4 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier, implementation-readiness, zoom-out.

**Scope:** amendment `e7d7daa` to `docs/designs/stream-d-extension-admission.md`. The full change reviewed is `4b64541..e7d7daa`, which also covers:
- the pointer in `docs/designs/stream-d-worker-dispatch.md:429–433`;
- the record `docs/reviews/stream-d-extension-admission-design-1.md`, read verbatim including the elephant resolution.

`docs/reviews/stream-d-diff-28.md` and commit `6e07de0` belong to the earlier diagnosis increment and were not reviewed here. `.stream-d-next/` was excluded.

**Branch and worktree:** `t3/stream-d-implementation` at `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`.

**Code read at `e7d7daa`:**
- `factory/run.py`: 272–317 (`resume_provider_wait`), 323–364 (`pending_call`), 1062–1100 (loading the resume unit) and 1258–1300 (building the writer receipt and the merge at :1281–1282).
- `factory/extensions.py`: 1–320.
- `factory/diagnosis.py`: 382–403 (`_input_bytes`, `_input_inventory`).
- `factory/budget.py`: 138–172 (`reserve_invocation`) and 374–400 (`release_uninvoked`, `reconcile_reservations`).

## Summary

### M1 (operation identity) is fixed

The design now refuses any receipt that has an `operation_id` key or a `phase` key, including a key whose value is null. This is checked before the lease. The branch always generates a fresh UUID (design lines 44–50 and step 3).

Checked against the code:
- **The merge path is caught.** The only way a receipt inherits an earlier operation is the merge at `run.py:1281–1282` (`{**resume_unit, **writer_receipt}`). A loaded schema-2 `resume_unit` always contains `phase` and `operation_id`, because `run.py:1076–1078` checks both. So every merged receipt is refused.
- **An unmerged receipt has neither key.** The fresh receipt built at `run.py:1277–1287` adds neither key until `admitted()` runs.

Attribution stays separate even if the durable `attack-state.json` still holds an unmerged ordinary pending operation X for the same round:
- the extension's reservation row for operation Y and `builder-R` satisfies `extensions.read`'s binding at `extensions.py:114–121` on its own merits;
- X and Y stay separate keys for `reclassify_factory_bug`;
- X's money was already settled by step 1, and a crashed X is booked conservatively by `reconcile_reservations`.

The required test supplies a settled ordinary operation and a null-valued key. It pins `extension_reservation_mismatch`. Ordinary calls keep `receipt.get('operation_id') or uuid4()` unchanged.

### M2 (refusal labels for evidence reads) is fixed

Each error `_input_bytes` can raise now has a label (design lines 68–76):
- **`FileNotFoundError`** is raised by `os.open` (`diagnosis.py:390`) when the file or a parent directory is missing. It maps to `extension_snapshot_changed`.
- **`ValueError('unsafe input path')`** from line 387 or 389 maps to `extension_snapshot_changed`.
- **`ValueError('nonregular input')`** from line 392 maps to `extension_snapshot_changed`. Under `O_RDONLY|O_NONBLOCK`, a FIFO or directory opens and then fails the `S_ISREG` check, so the real-reader controls listed for symlinks and FIFOs work.
- **A leaf symlink that appears after the ancestor probe** makes `O_NOFOLLOW` fail with `ELOOP` on both macOS and Linux. It maps to `extension_snapshot_changed`.
- **`EACCES` and `EIO`** propagate as infrastructure.

Two points about how this is built and tested:
- **Separate handlers.** Shape validation and read handling are kept apart. This prevents a reader's `ValueError` from being relabelled `extension_reservation_mismatch`.
- **ELOOP is injected only at the read boundary.** This is the right way to test a race the real reader cannot produce on demand.

### The nits from review 1 hold

- **N1:** the claim now reads "writes no files". The cost now counts the verification of retained history (lines 198–202).
- **N2:** the trust root is stated (lines 26–30). Eligibility relies on `diagnosis_state` from B's authenticated restored card, or on the current verified `apply`. No new reader of decisions is added.
- **N3:** the "after history" paragraph (lines 133–136) matches the code:
  - Before `opencode` runs, the lease is not in `route_receipts`, so the `except` at `run.py:350–354` calls `release_uninvoked`.
  - That call moves a pending row with no events to `settled` at a cost of `0.000000000` (`budget.py:381`).
  - `extensions.read` checks only that the operation and call name exist, not the row's state. So the settled row still binds the retained operation.
  - The test now asserts the settled row with a gap of zero.
- **N4:** the exclusions for the future scientific stage producer are recorded (lines 32–36), with no widening of current snapshot rules.
- **N5:** the timeline (lines 18–19) and the parent pointer are present.

### No regressions

- **Ordinary path unchanged.** Ordinary writer and stress calls keep their callback order: `on_admitted` runs before `admitted()`. Only the extension branch reorders, and it says so.
- **Second verification still has a killing test.** The local deep copy, the verification after the lease wait, the unchanged `reserve_invocation` and the order `admit` → `admitted()` → `on_admitted` → `opencode` all carry over from design 1, and the second verification is still covered by the `await_lease` mutation test.
- **No other new behaviour.** No new module, field, flag or production caller. `DIAGNOSIS_ENABLED` stays false, and the test asserting no production caller is kept.

### Open items, out of scope

The remainder of B1 (active continuation), B2, M5 and M6 stay open and are not claimed. The amendment does not obstruct them:
- the settled reservation row still binds the operation;
- the inert `extension_id` field waits for a continuation reader;
- `reserve_invocation` keys rows by lease, so continuation can reserve a new lease.

## Nits

**N1. `ENOTDIR` (and `ENXIO`) on an evidence read are treated as infrastructure.** Lines 69–73 and `diagnosis.py:388–390`.
- **What happens:** if a named evidence file's parent directory is replaced by a regular file, `Path.is_symlink()` swallows `ENOTDIR` and returns False. `os.open` then raises `NotADirectoryError`. Under "other filesystem failures propagate as infrastructure", that becomes a retryable infrastructure error for what is really changed evidence. Infrastructure failures are retried, so this state could loop on retries instead of refusing cleanly.
- **Same pattern:** a Unix socket at an evidence path gives `ENXIO` on open.
- **Fix:** map `ENOTDIR` together with `FileNotFoundError` (and optionally `ENXIO` with nonregular) to `extension_snapshot_changed`. Add one real-reader control where a parent directory is replaced by a file.
- **Impact:** it costs no money, because every branch refuses before the lease, and there is no production caller.

**N2. The label for a malformed entry snapshot is ambiguous.** Lines 55–58 and 66–68.
- **The two rules:** "Malformed proposals become `extension_reservation_mismatch`", but "existing eligibility … errors retain their labels".
- **Where they collide:** `propose` → `validate_snapshot` raises `extension_snapshot_invalid` (`extensions.py:43–70`). The implementer must decide whether that error is malformed (and relabelled) or existing (and kept).
- **Fix:** state that it keeps `extension_snapshot_invalid` (my suggestion, since it is the existing label), and pin it in the refusal test.

**N3. The refusal list for receipt keys covers only two keys.** Lines 44–47.
- **Why those two are enough today:** every inherited ordinary receipt carries both `operation_id` and `phase`, so refusing on those two blocks inheritance.
- **What is not covered:** a handcrafted receipt could still carry `resumed_from_wait`, `lease_id`, `invocation_id`, `schema_version` or `extension_id`.
  - `admitted()` overwrites `lease_id`, `invocation_id` and `schema_version`.
  - `step 7` sets `extension_id`.
  - A stale `resumed_from_wait` would survive into the pending receipt, where a later `provider_continuation` reader would see it.
- **Fix:** refuse any receipt containing a key that admission or `admitted()` owns: `schema_version`, `operation_id`, `phase`, `lease_id`, `invocation_id`, `resumed_from_wait`, `extension_id`. This removes a choice the future continuation reader would otherwise have to make.

**N4. Record housekeeping.**
- `docs/reviews/stream-d-extension-admission-design-1.md` still contains the empty heading `## Elephant response *(to be completed by the elephant)*` above `## Elephant resolution`. Fill it or delete it.
- When this review is recorded, update the pointer at `stream-d-worker-dispatch.md:431–433` (currently "awaiting review before implementation") to say design review 2 passed.

## Scope confirmation

- **Murphy register:** no row is closed or claimed.
- **Production code:** none changed in this range. No caller, activation, launch, public authority or money authority is added.
- **Unqualified, as stated:** stage receipts remain authored test controls. The extension dispatcher, real Unix isolation, the live provider and the B runtime remain unqualified.

## Validation boundary

This review covers whether the design is ready to implement, at `e7d7daa`, based only on reading the design, the review record and the code at that commit.

I ran no tests and no full suite, and I make no claim about either. The full-suite rerun of the diagnosis correction is still pending elsewhere. I made no model, cloud or launch calls, did no decryption, used no secrets, did not touch the parent checkout or `.stream-d-next/`, and wrote nothing.

## Elephant response

Accepted PASS and all four nits. N1: ENOTDIR and ENXIO join ELOOP as changed
evidence, with a real parent-replaced-by-file test. N2: malformed entry snapshots
keep `extension_snapshot_invalid`; only malformed proposal envelopes use
`extension_reservation_mismatch`. N3: first receipts refuse all seven named
admission-owned keys, including null values. N4: filled the prior response and
updated the parent pointer. No prior finding is rejected, no Murphy row closes,
and active continuation/B2/M5/M6 remain open. The next step is implementation
and a fresh diff review of this unwired seam.
