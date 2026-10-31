# Goldfish diff review: stream D extension receipt routing (`3123ac0..HEAD`)

**BLOCK.** The source code matches the design and I found no correctness defect in it. The problem is the tests. Removing any of four refusal checks the design requires still leaves all 35 focused tests passing. One of those is the reservation binding for finished writer receipts, which this increment exists to provide. The fix is test-only and small.

## Scope

- **Where:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-4ac6b632`, branch `t3/stream-d-gates`.
- **Mode:** REVIEW, with personas `zoom_out` and `implementation_readiness` and `implementation-readiness-standard.md`.
- **Reviewed against:** the design and its two design reviews.
- **Source changes:** `factory/extensions.py` (+100), `factory/run.py` (+4, all inside `pending_call`) and `tests/factory/test_stream_d_admission.py` (+175).
- **What I ran:** only the focused test file, which gives 35 tests, all OK. I did not run the full suite.
- **Mutation probes:** run in a `git archive` copy under a temp directory. I modified no repo files.

## What holds

- **Crash ordering.** `retain_writer` runs after `reserve_invocation` and before `extensions.admit` (`run.py:398`). The intent it saves is exactly what `admitted()` later writes: the same lease, invocation, operation and extension ID, and a binding hash computed the same way. The writer and callback run only after both history and the attack receipt are written.
  - If saving the intent fails, there is no history, no writer and no callback, and the existing `except` path settles the lease. This is tested.
  - Breaking history then attack-state is tested from no predecessor, from a completed writer and from a stress predecessor.
  - After recovery, `pending_call` continues the same operation with no new extension.
- **Immutable intent.** The saved envelope has exactly `{receipt, previous}`. A replay must equal the saved envelope, and the intent is never rebuilt from current files. A receipt already in attack-state must match the intent on every field outside `_WRITER_MUTABLE`, and that list matches the design's list exactly.
  - Recovering twice leaves the attack file, intent, history and ledger unchanged at the byte level, and resets `builder_rounds`.
  - Removing the replay-equality check (M7) or the frozen-field check (M3) fails tests.
- **Same-round stress returns None.** The check runs after active history is verified and before the intent is loaded. It needs a strict `int` round equal to the active round, and it writes nothing.
  - Tested for all three stress phases, a wrong round and a boolean round.
  - Removing the check (M6) fails a test.
  - A predecessor's round must be below the active round, so the rule that predecessor equality wins cannot clash with the same-round stress check.
- **Deleted predecessor.** If the predecessor existed but attack-state is now missing, the selector refuses. Removing that check (M4) fails a test.
- **Malformed input, unsafe paths and I/O errors.** Reads go through `_input_bytes` (no symlinks followed).
  - Missing files, malformed JSON and non-dict values become `extension_reservation_mismatch`.
  - `ELOOP`, `ENOTDIR`, `ENXIO` and `EISDIR` also become that refusal. Permission errors and EIO propagate.
  - Tested: a symlinked intent file, a symlinked attack file, a symlinked parent directory, raw values `null`, `[]`, `{bad` and `{}`, and a missing intent.
- **Durability.** After `mkdir`, `work` is fsynced, and `atomic_json` fsyncs the file and its directory.
- **No new mechanism.** No new module or dependency. The change reuses `writer_intent_valid`, `writer_continuation`, `_input_bytes` and `atomic_json`, and the nested `dispatch` is safe because its lock is an RLock.
- **Scope.**
  - `writer_receipt` has no production caller; `retain_writer`'s only caller is `run.py:398`.
  - No Murphy row is claimed.
  - The `factory/` and `tests/` changes are identical between `dea2e22` and HEAD. The evidence record says exit 0, 157 scripts run and 0 failed, and its `log_sha256` matches the uncompressed log.

## Findings

**1. Blocker (test coverage): four required refusals have no test.** (`factory/extensions.py`, the `writer_receipt` else-branch, against the design's "Change" and "Tests" sections.) In a scratch copy I removed each check below. All 35 tests in `test_stream_d_admission.py` still passed:

- **M2:** completed and validated receipts no longer checked against the operation's reservation (`writer_continuation(c, {**current, 'phase': 'pending'}, name)` skipped for those phases). With this gone, a finished receipt with this operation's ID but a made-up or foreign lease and invocation is accepted. The design names "mismatched reservation" as a required refusal, but the damage test only changes `invocation_id` on a *pending* receipt.
- **M8:** the rule that a finished receipt must have string `lease_id` and `invocation_id` removed.
- **M1:** the rule that a pending receipt still on its original lease and invocation keeps its original `binding` removed. The current test changes `binding` without its hash, so it is caught by the hash-shape check instead and never reaches this rule.
- **M5:** the phase allowlist `pending|completed|validated` removed. A receipt with any other phase is then accepted as if it were pending.

**Fix:** add one damage test (about 15 lines), run without writes, mirroring the existing subTest pattern:

- after `complete_writer`, give the completed and validated receipts the lease and invocation of another operation's reservation, and also set them to `None`;
- on the original pending receipt, change `binding` and recompute a consistent `binding_sha256`;
- set `phase='abandoned'` on an otherwise valid receipt.

Each case must raise `^extension_reservation_mismatch$` and leave the attack file, intent and ledger unchanged at the byte level. Re-run the full suite and commit a new record.

**2. Nit: the wrong-round stress controls fail for the wrong reason.** In `test_writer_selector_leaves_same_round_stress_to_package`, the intent is unlinked first. So the `round=2` and `round=True` stress controls are refused because the intent is missing, not because the receipt is foreign. Keeping the intent for those two controls would show they are refused on the receipt check.

**3. Nit: one damage case fails on the wrong check.** In the damage test, the `round: 2` change on the intent is caught by the report-name check (`round-1.json` ≠ `round-2.json`), not by the round binding. That is acceptable, just indirect.

## Decision

Close finding 1 with tests, re-run the full suite and commit the new record. No change to the source code is needed. Findings 2 and 3 are optional.

## Implementation response

Accepted blocker 1. Add independent refusal controls for finished receipts with a foreign operation reservation, finished null lease/invocation with a valid archived provider continuation, changed pending binding with a recomputed hash, and an unknown phase. Assert receipt/intent/history/ledger bytes remain unchanged. The archived-wait control is needed to isolate the finished-string check from the pending continuation verifier. Also restore intent for the wrong-round stress controls and update report names in altered-round controls (nits 2–3). Production code is unchanged. Re-run the full suite and obtain a fresh diff review; this response does not self-clear the blocker.
