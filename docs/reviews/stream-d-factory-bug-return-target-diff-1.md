**Verdict: the code passes review with no blockers.** One Major test gap should be fixed before merge. Delivery is not ready, because the required full suite failed and the second suite run is still pending.

I reviewed `b75c9b4..94211b6` read-only. I ran no tests and made no writes, and I did not look at the queued second suite. `factory-simplify` is still `b75c9b4`, so nothing newer needs merging. Production code is unchanged since `9cd1a66`; only docs changed after it.

## What I confirmed

- **Scope:**
  - The only production changes are in `factory/diagnosis.py` (+57) and `factory/diagnosis_dispatch.py` (+6/−1).
  - `run.py`/`main` are unchanged, so there is no previous-card override (M1 is honoured).
  - Nothing adds a new router, counter, money authority or retry reset, and nothing changes `DIAGNOSIS_ENABLED`.
- **The record is kept before the decision is returned:**
  - `retain_extension_resume` runs only in `apply`'s enabled close_to_passing branch.
  - It runs after `writer_receipt`/`completed_route` and before the scorecard is written and the extension ID returned (`diagnosis_dispatch.py:256`).
  - An identical record is kept byte-for-byte, a new valid decision replaces it, and a malformed existing record refuses.
  - `registry.atomic_json` already fsyncs the directory.
- **Record reads don't follow links:**
  - All reads go through `_input_bytes`, with exact-key, schema, case and digest checks.
  - Read and parse errors, including `BudgetError` from `extensions.read`, are caught inside `_extension_resume_state` and become `FactoryBugHeldWait('extension_resume_target_invalid')`. They are never relabelled as `factory_bug_resume_io_wait`.
- **Live and frozen copies:** they must match byte-for-byte, `extension-resume.json` is added to `_write_input_tree`, and validation uses a deep copy of the case record (`extensions.read` on the copy, never the live card).
  - `extensions.read` needs only `work`, `ledger` and `card`, all of which the copy provides.
- **Admission order:**
  - The lifetime-limit retirement (three resumes) still runs first on a new admission.
  - The record check then runs on both new and reused admissions, before any new append (`diagnosis.py:562`).
- **The restore happens in the same write that clears the hold:** `admitted_card['diagnosis_state']` is set in the same `atomic_json` as the clear, and `factory_bug_resume_count` is kept.
- **`_dispatch` fall-through:**
  - With no restored close_to_passing state, it returns False exactly as before.
  - Otherwise it rebases `previous`, then runs the existing prepare, lock, reconcile, queued-inputs, journal, replay and apply steps.
  - The journal's family check uses the case's own carried roles (`c.card['roles']`), so replaying in a new batch does not trip it.
  - A retained-artifact failure goes to `invalid(c)`, never to ordinary construction or a second diagnosis.
- **Held cases:** `run.py:3419` maps `FactoryBugHeldWait` to `factory_bug_held` with the wait reason. That is the permanent hold the design documents.
- **Murphy row:** `new-stream-d-current-comparison-1` is still `open` and the register is unchanged. The item-8 checklist line in `docs/designs/stream-d.md:3408` matches the required text exactly.
- **Tests:** the 13 tests cover the design's focused list: retention order, disabled selection, idempotent and replacing records, six corruption faults plus a read denial, reused-admission re-check, both crash points, active-successor recovery, the completed-route seam, and missing artifacts going to input-invalid with no extra call. The labels honestly say the states are authored and the owner transitions are in place.
- **Suite records:** they match the report. The full suite at `9cd1a66` exited 1, with 179 scripts and only `test_isolation_outer_callers.py` failing; all 13 new tests passed in that run. The single-method recheck is correctly labelled as not quiet-host proof.

## Findings

**Major 1: the main thing this change is for is never tested with real extension history.** (`tests/factory/test_stream_d_resume_target.py`)
- **Evidence:**
  - Every real resume in the file happens with an empty extension history: `choose()` selects with no history and returns 0.
  - The only case with history patches `extensions.read` to return a fake row (`test_frozen_record_mismatch_and_missing_post_extension_target_refuse`), and that only tests refusal.
  - So no test ever validates and returns a record against a real, non-empty public history, which is the post-extension case this change exists for. That path runs the real `extensions.read` on the copied card, the snapshot and ledger checks, the public-view lag rule, the `builder_rounds` check, and `_state` with the full history.
- **Why this is not covered by the parent's deferral:** the parent deferred building a new combined fixture. The controls this needs are already used in `test_completed_successor_uses_existing_completed_route`: `hold()`, `replay()`, `admit_active_control(1)` and `extensions.complete(...)`.
- **Requested fix:**
  1. After those steps, call `diagnosis._extension_resume_state(self.c, <held diagnosis>/inputs)` and assert it returns `self.original_state`, using the real `extensions.read`.
  2. Add one negative case with the same real history and the live record removed, asserting `extension_resume_target_invalid`.
  3. Label both as authored snapshots, not as proof of `subsequent_entry`.

**Nit 2: one assertion proves nothing.** `run.writer_feedback(self.c, self.held) is None` in `test_in_place_resume…` holds by construction, because `hold()` itself pops `failed_gate` and `failed_detail`. Delete it, or reword the comment so it doesn't read as M1 evidence.

**Nit 3: `state` points at the live card, not the copy.** At `diagnosis_dispatch.py:314`, `state` refers to `c.card['diagnosis_state']` rather than to `previous`'s copy as the design says. It behaves the same today because `apply` writes identical values. Setting `state = previous['diagnosis_state']` after the deepcopy would match the design.

**Nit 4: refusing a corrupt record happens after other work.** When `retain_extension_resume` refuses during replay, it does so after `completed_route`'s side effects, and it surfaces as a plain stop label rather than a hold. That is acceptable for a corrupted record, but it isn't written down.

## Delivery conditions (not code findings)

- **Full suite:** the required full suite at `9cd1a66` failed in `tests/factory/test_isolation_outer_callers.py` (key_holder, index 0). The targeted recheck does not waive it. The second locked suite is still pending and has not been treated as a pass. There is no merge-readiness claim until a full suite passes or the failure is resolved under the engineering rules.
- **Murphy row:** it stays open. Nothing here claims `subsequent_entry`, pair-attempts or archive/restore qualification; that remains item 8.

## Elephant disposition

Code PASS/no blockers accepted. Fix Major 1 by extending the existing completed-successor unit test: after real admission/completion with authored scientific snapshots, call the real _extension_resume_state against the held frozen root, assert original state and no live-card mutation, then remove the live record and assert the held refusal with the same real history. No subsequent_entry or archive/restore claim is added. Delete Nit 2's tautological feedback assertion. Defer optional Nit 3: production code is unchanged since the reviewed/tested source, and the reviewer confirms identical current behavior. Document Nit 4's ordering/plain evidence stop. No finding is rejected as incorrect.

Delivery update from the parent, after this review began: the key_holder heartbeat failure is a known flake from other lanes and passed the targeted recheck; cancel the queued repeat and use the parent's merge suite as the gate. Repeat cancellation before tests started is committed at abdcdd9, with no suite verdict. Thus the review's now-stale pending-repeat delivery condition is superseded by that explicit parent decision, not by an inferred waiver. No further full suite is run. Focused file and fresh final diff review remain required. Murphy new-stream-d-current-comparison-1 stays open.
