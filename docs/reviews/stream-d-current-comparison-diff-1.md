**BLOCK.** Two blockers are open. Either one stops this from merging.

# Diff review: stream D current-version comparison (round 1)

**Verdict: BLOCK.** Two blockers, three majors and four nits.

Read-only goldfish review in Mode REVIEW. I used the `zoom_out` and `implementation_readiness` personas and `implementation-readiness-standard.md`. I reviewed diff `fe182c2..4d19cff` on `t3/stream-d-gates` against the approved design `docs/designs/stream-d-current-comparison.md`, including its binding rounds 3–5, and against `docs/reviews/stream-d-current-comparison-design-5.md`. `e9eac63` adds only the suite record and docs.

What I ran:
- `tests.factory.test_stream_d_comparison`: 27 tests, OK, 2 skipped (Linux-only).
- One offline probe from `/tmp`, since deleted. It re-ran an existing test with the real `run.public_progress`, pointing `SEALED` at a temporary directory.

I modified no files and made no model calls. The worktree is still clean.

## Blockers

**B1. The real progress publisher rejects every comparison label, so the production producer cannot run a comparison.**
- **Where:**
  - `factory/extension_package.py:509` publishes the label `'comparison'`.
  - `factory/extension_evaluator.py:582` publishes `'comparison:' + stage`.
  - Both go through `run.public_progress` (`factory/run.py:133-141`) to `public_progress.publish`.
  - `publish` accepts only `G1`–`G17`, `early:Gn` or `role:<role>` (`factory/public_progress.py:17-19,49-50`). Anything else raises `ValueError`.
  - `run.public_progress` catches only `OSError`.
- **What happens:**
  - `gate_attempt.execute` calls `publish('running')` first (`gate_attempt.py:26`), before the retry journal.
  - So whenever `case_id` is set, every subsequent entry that is not served by the fast path raises `ValueError` before any attempt.
  - That bypasses the recovery table. Main catches only `BudgetError`/`PauseRequested` (`run.py:~3407`), so this ends as a runner crash.
  - The card is left at `runner_error:comparison_in_progress`. Every resume hits the same producer and fails the same way. That contradicts the design's claim that no unresolved infrastructure fault ends without a route (lines 565-566, 586-588).
- **Reproduced:** `ComparisonTests.test_real_saved_g4_g5_pair_then_next_entry_and_no_reroll`, run with the real `run.public_progress` and `SEALED` pointed at a tmpdir, fails with `ValueError: invalid public progress stage or status` raised from `extension_package.py:509`.
- **Why the suite passed:** `test_stream_d_comparison.py:46` replaces `run.public_progress` with a no-op for every test, and `child_protocol` patches it too (line 277–278). Nothing in the suite exercises this path with the real publisher.
- **Needed:**
  - Either use labels the existing publisher accepts, or extend its allowlist on purpose (it is the public operational surface, so that needs a stated decision). Or route comparison progress somewhere that cannot raise.
  - Add a test that runs subsequent entry with the real `public_progress` and a temporary `SEALED`.

**B2. Several exams the binding design requires are missing, and they cover the new money and process paths.**
The design lists these as required (§8, "Round-1 … added exams", "Round-3 … Additional exams", Round-4 M3). I found no test for them in `tests/` (grep over `tests/` for `start_child`, `active_count`, `reconcile_reservations`, `restart.plan`, `queued_inputs`, `finalize_accounting`, `pending_call`):
1. **Fork thread wait.** "Active thread refuses fork", and "a thread exiting inside 30 seconds permits fork while a longer one consumes an attempt" (lines 483-484, 585-586). The wait loop at `extension_evaluator.py:400-406` has no test. Every test patches `start_child` (test line 79).
2. **Settlement before retry.** "Dead child with a pending reservation and valid retained final usage: settlement precedes retry admission … without a spurious money_wait" (lines 635-638). The `reconcile_reservations` call at `extension_evaluator.py:555` has no test.
3. **Diagnosis handoff.** "Exercise G and stress exhaustion through finalize_accounting -> record_exhaustion -> queued_inputs … included comparison diagnostics, never diagnosis_input_invalid" (lines 523-526).
   - `test_two_child_deaths_queue_stress_diagnosis` and `test_gate_exhaustion_has_valid_owner_marker` (test lines 127-147) set `terminal_stop` by hand and call `record_exhaustion` directly.
   - Neither checks that `queued_inputs` carries the `comparison-diagnostics` files and hashes, which is what the `diagnosis.py` change exists for.
4. **Restart plan.** "Sealed mid-comparison card with recovery.require_restart_stop and restart.plan using saved restore artifacts" (lines 579-581). Only `require_restart_stop(card, [])` runs, on cards captured by an authored checkpoint stub (test lines 106-109). `restart.plan` is never called.
5. **Opt-in route through main.** "Opt-in integration tests showing that 0 reaches the producer and that a pending producer prohibits every writer/admission call" (lines 57-58, 449-450).
   - `test_pending_pair_routes_to_producer_before_writer_admission` (test lines 194-209) calls `apply` and `package.entry` separately. It never goes through main/`admit_extension` and does not forbid `pending_call`.
   - The dispatch `held:` test only asserts that main passes `comparison_route=True`.
   - A real main-path test would very likely have caught B1.
- **Needed:** add these exams with the saved fixtures the design names, or record an explicit, reviewed deferral for each. The implementation report says these areas are exercised. It should not say so until the tests exist.

## Major (should fix; not blocking)

**M1. Scratch can be deleted on a stale checkpoint receipt.** (`extension_package.py:517-526`)
- `evaluator.checkpoint()` calls `checkpoint_progress` with the default `interval=900`. That returns `False` without sealing if a checkpoint ran in the last 15 minutes (`durable_checkpoint.py:23-24`), and the per-stage checkpoints make that likely.
- The code ignores the return value. It checks `c.card['durable_checkpoint']['remote_durable']`, which can be left over from an earlier seal.
- It then moves transcripts and runs `rmtree` on the comparison root even though the retained pair may not yet be remotely durable.
- Design §6 says "after a completed pair and a successful parent checkpoint". Use `evaluator.checkpoint(force=True)` and gate the cleanup on its return value.
- Remote state is unchanged under either behaviour, so I'm not blocking on this.

**M2. The version check after a stage cannot stop a replay.** (`extension_evaluator.py:544-547` against `509-510`)
- The child commits its Records before it replies.
- If the parent's version check then raises `InvalidInfra`, the retry's first line `records.load(stage)` replays that committed record, so the check never affects the result.
- The design also requires a source-version check "before every new invocation" (§3, lines 107-108). `invoke` has none.
- Pinned versions and the private bench copy keep the science consistent, and `compare` re-checks versions before publication, so this is low risk. Either do the check before `pipe.send`, or document that the post-reply check is advisory.

**M3. The Linux fork exams don't exercise the evaluator's real process path.**
- `test_real_g1_g4_g5_in_fork_preserve_parent_globals` forks a test process that runs `child()` over the authored synchronous pipe.
- `test_detached_descendant_is_gone_before_next_phase` calls `close_child` on a hand-built instance.
- No test, even on Linux, goes through `Evaluator.start_child` → fork → the `ready` handshake → `receive` → `close_child` together with subreaper setup and restore.
- This is consistent with "no Linux qualification claimed". But the item-8 Linux obligation should name this full path explicitly, so a pass of these two skipped exams is not read as covering it.

## Nits

- **N1. Pair crash diagnostic is overwritten.** `pair-crash.json` (`extension_package.py:504-506`) is rewritten on each attempt and has no traceback. Stage crashes are numbered and include tracebacks (`extension_evaluator.py:473-479`). After exhaustion, diagnosis sees only the last pair failure.
- **N2. Eligibility checks are duplicated.** `subsequent_entry` repeats `admit_extension`'s eligibility checks inline (`extension_package.py:469-476` against `diagnosis_dispatch.py:463-470`), rather than using the existing rules as the design wording says. The labels are the same, so behaviour is unchanged. It is duplication.
- **N3. Operational effects may never be drained.** Child `operational-effects.json` is merged only in `phase_for` (`extension_evaluator.py:394-395`). After a crash, a relaunch that takes the completed-pair fast path never drains it, and a later `rmtree` drops it. That is lost operational telemetry only, not money.
- **N4. Undesigned change in `run.resume_provider_wait`.** It now uses `accounting_work` (`run.py:331-353`), which the design's list of accounting seams (§6) does not mention. It is behaviour-neutral for the owner, since `accounting_work(c) == c.work`, and it is consistent for the child. Record it in the design or the report.

## What I checked and found consistent with the design

- **Routing** (`diagnosis_dispatch.py:221-446`):
  - `comparison_route` is forwarded on all three `apply` paths (fresh invoke, replay, valid journal).
  - The opt-in bypasses only the different-exhaustion pending hold, and only when `DIAGNOSIS_ENABLED is True`.
  - Without opt-in, the `extension_comparison_pending` hold is unchanged.
  - Same-exhaustion replay, active rows, and the factory-bug and not-converging branches are unchanged.
  - Main opts in (`run.py:3354`).
- **Subsequent entry:**
  - It uses the live `c`.
  - The `freshness.jsonl` digest must equal the outcome's `case_sha256`, otherwise it stops with `extension_snapshot_changed`.
  - It checks the verified current pair before the pair journal.
  - A retained but invalid pair is an evidence stop, never re-run.
  - Only `source_generation` is rebound in the returned outcome.
  - No progress or regression retires the case as `retired_no_progress`.
  - The in-progress marker is set and the exact pre-producer values are restored.
  - Live G3 and preparation markers are cleared in `finally`.
- **Records:** `expected_versions` is used only by the evaluator, and a mismatch maps to `extension_snapshot_changed`. Ordinary Records behave as before, and there is a one-worker gate-cache identity test.
- **Execution override:** it is validated and included in `_configuration`. Receipt bindings and `_load` don't depend on it.
- **Accounting:**
  - The accounting root is used only for reconciliation, receipts and `complete_invocation`.
  - Parent `comparison=True` scopes never call `resume_scope` or `classify`.
  - `ForwardedAttempt` ignores `record_reservation`.
  - Non-factory jobs install `None`.
  - Marks are made durable before the acknowledgement and replayed in the parent's `finally`.
  - `comparison_child_lost` applies only when there was no reply and quiescence was not proved.
  - Reservations are recorded from the ledger delta while the parent scope is active.
- **Retries:** the parent owns attempts with `attempts=2`. Records are checked before the journal and replayed after a lost reply. G exhaustion sets a valid `infrastructure_gate` marker. Stress and pair exhaustion use `stress_validation_exhausted` without a G marker, and the diagnostics index records `scope='pair'` or `scope='stage'`.
- **Process and source isolation:** the child does `setpgid`, applies the seal trap, rebinds `BENCH`/`COMPOSE`, evicts `bench`, `factory_pool` and `claims`, runs the bin-module allowlist check and asserts the `InvalidInfra` class identity. The source copy uses the extracted manifest predicate and materialises safe links. Unsafe links are `InvalidInfra`. The manifest is checked against `c.manifest0` before and after the copy.
- **Scope:**
  - Activation stays false.
  - Extension limits and attribution validators are untouched.
  - No Murphy row is closed. `new-stream-d-current-comparison-1` is added as open.
  - The malformed-history test was replaced as the design specifies.
  - The worker inventory includes `extension_evaluator.py`.
- **Zoom-out:** no new subsystem, queue or launcher. It reuses `gate_attempt`, Records, `factory_waste.Attempt`, `reconcile_reservations` and `checkpoint_progress`.

**Result: BLOCK.** Fix B1, add a test for it with the real publisher, and resolve B2 by adding the missing exams or recording a reviewed deferral for each.

## Implementation disposition (writer)

B1 fixed by a deliberate finite comparison-label extension to the operational
publisher, documented in the design. The full comparison test class now uses the
real publisher in temporary SEALED storage; the receipt test checks published rows.
B2 fixed with all five requested boundary exams: real thread liveness with authored
elapsed time; real reservation/final-receipt settlement before retry; G and stress
exhaustion through finalization and verified queued inputs; real parent checkpoint
helper plus restart.plan over saved practice/ledger bytes and authored ciphertext
transport; and main -> real admission -> pending producer with writer_request and
pending_call forbidden. The producer transport is explicitly authored in the main
seam test; the producer itself runs in the real-publisher comparison tests.
M1 fixed with a forced final checkpoint and cleanup conditional on that call's
remote result, with stale-receipt and forced-publication tests. M2 fixed with source
checks before invocation/replay and send, plus the existing post-reply check.
M3 remains an explicit Linux activation exam requiring the full real evaluator
process path, beyond the two Mac-skipped tests. N4's accounting seam is documented.
N1–N3 remain non-blocking findings. Fresh round-2 review must verify the blocker fixes.
