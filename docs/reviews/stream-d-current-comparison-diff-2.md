**PASS.** No blocker is left open. Both round-1 blockers are closed, the two majors (M1, M2) are fixed, and the existing route, attribution and retry tests are unchanged and still pass. The leftovers below are optional.

# Diff review: stream D current-version comparison (round 2)

Fresh goldfish review in Mode REVIEW, read-only, using the `zoom_out` and `implementation_readiness` personas and `implementation-readiness-standard.md`. I reviewed the fix range `e9eac63..0224014`, against the design (including its binding amendments and the "Diff-review round 1 decisions" section), `design-5`, `diff-1` with the writer's dispositions, and the implementation report. HEAD `a9fd746` only adds the suite record and docs.

**Tests I ran** (offline, in the worktree, no files changed, no model or network calls):
- `test_stream_d_comparison`: 34 tests OK, 2 skipped (Linux-only).
- `test_public_progress`: 6 tests OK.
- `test_stream_d_dispatch`: 63 tests OK.

**Suite record checked:**
- The `11ab3a7f` JSON names head `0224014` and tree `edfb1512…`. That tree matches `git rev-parse 0224014^{tree}`.
- The log's sha256 is `bbfdfc31…`, matching the record.
- The log tail reads "170 test scripts run; 0 failed."
- The interrupted record `b6cb3ab3` (head `ae2421c`, exit 137, `scripts: null`) carries an `interruption_reason`. The report does not claim it as a pass.

## Blockers from round 1

**B1, comparison progress labels: closed.**
- `factory/public_progress.py:19` adds one extra pattern. It accepts only `comparison`, `comparison:stress` and `comparison:G1`–`comparison:G17`. Nothing else in the schema changed.
- `tests/factory/test_public_progress.py:76-83` checks all 19 allowed labels and rejects `comparison:private text`, `comparison:G0`, `comparison:G18` and `comparison:role:writer`.
- `test_stream_d_comparison.py:50` no longer replaces `run.public_progress` with a no-op. It points `SEALED` at a temporary directory, so every comparison test now runs the real publisher.
- `:106-108` checks the published `comparison` status and that a `comparison:G5` row exists. Before this fix, that same test failed with `ValueError`.
- The design records this as a deliberate allowlist decision (lines ~680-684).

**B2, the five missing exams: closed, none deferred.**
1. **Fork thread wait** (`test_thread_wait_accepts_quiescence_and_exhausts_without_fork`).
   - It runs the real `start_child` loop against a real `threading.Thread`.
   - A thread that finishes inside the bound lets the fork go ahead (`child.start` called once).
   - A thread still alive past the 30-second deadline (clock is authored) gets to `get_context`, which is set to raise `AssertionError('unsafe fork')`. The case ends `stress_validation_exhausted`, with a journal showing `invalid_attempts == 2`.
   - The process and clock are authored and labelled as such.
2. **Settlement before retry** (`test_dead_child_settles_final_receipt_before_retry_admission`).
   - It makes a real `budget.reserve_invocation` call and writes a final-usage receipt, then the first attempt dies.
   - At the retry, `start_child` sees the reservation already `settled` with a zero gap. That proves `reconcile_reservations` in the `except` at `extension_evaluator.py:557` runs before the next admission.
   - Total spend stays at baseline, with no spurious `money_wait`.
3. **Diagnosis handoff** (`DiagnosisBoundaryTests`, G4 and stress).
   - It runs real `gate_attempt.execute` with 2 attempts, then real `exhausted`, then `run.finalize_accounting`, which moves to a new pending exhaustion.
   - Then it runs `diagnosis.queued_inputs`.
   - It checks the frozen `work/comparison-diagnostics/*` files: the infra-attempts journal and two numbered crash files. Each hash matches the frozen copy, and the status never reaches `diagnosis_input_invalid`.
4. **Restart plan** (`test_real_parent_checkpoint_is_restartable_and_forces_final_publication`).
   - The real `Evaluator.checkpoint` and `checkpoint_progress` run against saved practice bytes. The ciphertext transport is authored.
   - Inside each seal, `restart.plan(public, …)` returns `(case_id, 60, seed)` while the card shows `runner_error:comparison_in_progress`.
5. **Opt-in route through main** (`test_main_routes_zero_to_pending_producer_before_any_writer_call`).
   - It goes through the real main → dispatch → real `admit_extension` path. Unlike the `admit` fault, the `admit-comparison` fault does not stub out admission.
   - That path reaches `extension_package.entry` while the status is `extension_comparison_pending`.
   - `writer_request` and `pending_call` are both set to `forbidden`.
   - The producer here is an authored stop and is labelled. The real producer, with the real publisher, is covered in the comparison tests.

Existing tests are not weakened:
- In the dispatch test, only the expected maps gain a new `admit-comparison` arm. The assertions for the `admit`, `admit-money`, `active`, `execute`, `held:` and `mode:` faults are unchanged.
- The comparison tests only swap the no-op publisher for the real one.

## Majors from round 1

**M1, scratch deleted on a stale receipt: fixed.**
- `extension_evaluator.py:427-430` now returns `advanced and remote_durable`, where `advanced` is the return value of this `checkpoint_progress` call.
- `extension_package.py:517-519` calls `checkpoint(force=True)` and gates deletion on that fresh result.
- `test_stale_remote_receipt_never_deletes_scratch` pre-seeds `remote_durable: True` with a checkpoint that does not advance, and `pair-attempts.json` survives.
- The restart test above expects exactly two seals: the first stage, plus the forced final checkpoint, which the 900-second throttle would otherwise skip. Its bench directory is gone, and since `__exit__` does not remove bench, that comes from the gated `rmtree`.

**M2, version checks before replay: fixed.** `check_versions` now runs:
- at the top of `__call__`, before `phase_for` and before the cached `records.load` (`:583`);
- at the top of `invoke`, before replaying a committed record or calling `case_budget_boundary` (`:515`);
- after `start_child`, before `pipe.send` (`:526`);
- after the reply (`:552`).

`test_retry_checks_versions_before_replaying_committed_record` covers both the invoke-retry path and the callable/cache-entry path.

**M3, Linux process path: recorded as qualification work.** The design and the report both say that Linux activation must exercise the full real `Evaluator.start_child` → fork → `ready` → `receive` → `close_child` → subreaper-restore path. They also say the two Linux-only tests alone are not enough. No Linux coverage is claimed.

**N4, provider-wait accounting seam:** now documented in the design.

## Optional items (non-blocking)

- **O1. One version check sits outside the stage journal.** `extension_evaluator.py:583`: the drift check at the start of `__call__` runs before `gate_attempt.execute`. Drift found there therefore uses up a pair attempt (`pair-attempts.json`) instead of the stage attempt named in the design's table (line 558). The route stays bounded either way: pair exhaustion leads to `stress_validation_exhausted` and diagnosis. Either align the design's wording or move the check inside the stage callable.
- **O2. The restart test could check deletion more directly.** It infers scratch deletion from bench being absent. Asserting that `pair-attempts.json` is gone would mirror the stale-receipt test.
- N1–N3 from round 1 are still open and still optional: the pair crash file is overwritten, the eligibility checks are duplicated, and child operational effects may not be merged after a fast-path relaunch.

## Scope checks

- Activation is still false.
- Extension limits and attribution validators are untouched.
- No Murphy row is closed. `new-stream-d-current-comparison-1` stays open as the deferred factory-bug return target.
- Terminal writer and public-match outcomes are left to the next increment.

**Result: PASS.**

## Writer disposition

Accepted PASS. No code changes follow this review. Optional O1–O2 and round-1 N1–N3 remain recorded above; no additional increment is started. The full suite remains 170 scripts / 0 failures at 0224014. Earlier round-2 attempts ended with network ENOTFOUND and no review verdict. No Murphy rows close; activation remains off.

