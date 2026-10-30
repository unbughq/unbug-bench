**Verdict: NOTPASS.** One blocking finding (B1). One major finding (M1) that should be fixed or recorded as a design obligation. The reviewed range is `5bc8224..84cf56c`. The later commits, up to 225c5c5, touch only docs and tests, and `git diff 84cf56c..HEAD -- factory` is empty.

I made no edits to the repo, launches, decryptions, credential reads, or writes to main or the restore checkout. Probes and a scratch fix copy are in the scratchpad.

## B1 (blocking). A binding change on a pending or finished stress review renumbers the review and can create a false `rounds_exhausted`

**This is the diff-6 B2 bug on the sibling unit.**
- B2's fix routes only a validated writer to a re-review at round n.
- A stress unit (`actor: stress_tester`) takes the legacy block at `factory/run.py:1146` (`if not awaiting_stress and not modern_writer_unit and (not binding_changed or final_resume or transient_resume or ruling) …`).
- On a modern job, `final_resume` and `ruling` are false, and `provider_wait` does not match `recovery.RETRY`.
- So after a plumbing roll the block is skipped and `start_round` stays at `n + 1`.

**Why it matters**
- Design lines 175 and 815 say an already-started operation retains its ID and counter, and that plumbing rolls onto running cases at the next checkpoint.
- Design line 870 says a stress unit re-reviews at n.

**Repros**
- `probe1b.py`: the stress review `attacker-1` waits on a provider (`provider_wait`). The resume has a changed `attack_binding['prompt']`.
  - Calls: `['builder-1','attacker-1','attacker-2']`.
  - The review of round 1 is renumbered to round 2. The control with no rebind gives `['builder-1','attacker-1','attacker-1']`.
- `probe1c.py`: the same case with `--rounds 1`.
  - The resume raises `stress_review_unresolved:rounds_exhausted`. The pending review never ran.
  - A plumbing change turns a waiting review into a false exhaustion. Once diagnosis and replacement land, that triggers both.
  - The crash-kill variant behaves the same (`probe1.py`).
- `probe2.py`: a review finished with a blocking finding, killed before `loop_freshness`, then resumed with a rebind.
  - Calls: `['builder-1','attacker-1','attacker-2']`. The writer never receives the finding.
  - The control gives `builder-2` the report and problems.
  - The operation and review IDs are not retained either.

**Fix direction (checked on a scratch copy, not applied)**
- I added `modern or` to the outer condition at `run.py:1146`, in a `git archive 84cf56c` copy.
- `probe1c` then re-reviews at round 1 (`attacker-1, attacker-1`).
- `probe2` re-reviews at round 1 and then gives `builder-2` the findings.
- The 16 runtime tests still pass on the copy.
- I did not run the full suite on that copy, so this is a direction, not a verified patch.

**Needed in the design:** a sentence that a pending or completed stress unit with a stale binding re-reviews at round n. This is the readiness gap already noted in diff-6.

## M1 (major). `ordinary_limit_usd` does not survive a relaunch, so the diagnosis trigger moves

**This is partly reasoned from the code.** `probe3.py` simulates the relaunch. I did not run an end-to-end relaunch.

**Evidence from the code**
- `model_runtime.py:228` overwrites `recovery_config.case_budget` with the committed total. In the probe it is 200.
- `ordinary_limit_usd` is stored in the card's `case_budget` and in `recovery_config`.
- `run.py` rebuilds `c.card` and `recovery_config` at startup.
- `inherit_recovery_history` copies only five keys, and `case_budget` is not one of them.
- `coordinator.configuration_args` rebuilds `--case-budget` from `recovery_config.case_budget`. `ordinary_limit_usd` is not in `CONFIG_FIELDS`.

**Result**
- After the first wait and relaunch, `ordinary_limit_usd` falls back to the argv `case_budget`. In `probe3.py` that is 200, not 50.
- The ordinary writer threshold (spent + next maximum > ordinary limit) then triggers at the whole commitment, not at $50.
- Or the coordinator refuses the relaunch: argv `--case-budget 50` against a recovered 200 raises "policy changes original configuration". I did not exercise that branch.

**Ask:** persist `ordinary_limit_usd` from the restored card, or add a design obligation naming this. The tests only cover the single-process case.

## Required contract reads
- ENGINEERING.md and the persona and standard files: read.
- Full `stream-d.md`, including the incremental obligations and the founder's join rule (lines 851–883): read.
- `interfaces.md` §§2/3/5/7: read in the worktree.
- B §8: read with `git show t3/batch-service-control-vm:docs/designs/interfaces.md`, lines 276–403.
  - It does not yet contain the founder's join rule (unchanged commitment, full commitment held, all unknowns mapped, `reconciled_decrease` only for a matching unknown ID or wait ID).
  - That rule is recorded in D's obligations and B owns the landing. This is not a blocker for D.
- `router.md` and `invalid-runs.md`: read in full. I read the invalid-runs execution-validity rules and silent-window sections closely; the rest I skimmed for relevance to D.
- Murphy rows 8, 9, 10, 11, 12, 13, 15, 21, 35 and 39: read. The diff claims none closed, and none is.
- `diff-6` verbatim: read. `diff-5` verbatim and the headings of `diff-1` to `diff-4`: read. I relied on those for the accounting foundation and did not redo it.

## Verified, no defect found

**Diff-6 fixes**
- **B1 fix** (reserve before renewal and credential read): works.
  - The zero exception requires denied, final-known, no events, no booked IDs, no unidentified events and zero delta.
  - The malformed variants still raise `usage_reservation_missing`.
- **B2 fix** (validated writer keeps round n): confirmed for the writer unit only (see B1 above).
- **Popen-success callback:** pre-process failure releases at $0 (`test_pre_process_setup_failure_…`).
- **Streaming-accountant IDs:** `invocation_id` and `lease_id` are stamped on events and on `unpriced_invocations`. Reconcile removes only the matching entry.
- **Batch deadline:** it clamps the timeout. It reports `retired_batch_bound` and not `timeout`.

**Locks and threads**
- **Case lock:** two threads making wrapper-only calls give peak live CLIs 1, with two independent reservations (`probe5.py`).
- **Owner bypass:** it needs the program-set marker, a parent name in `active_model_calls` and a matching pending reservation. The three HTTP tests pass.

**Wait-chain crash windows**
- `probe4.py` kills `resume_provider_wait` after settle and before the pending reset, and after the reset and before the archive.
- Both leave a total of 13.841470815 both before and after the second resume. The continuation is recognised, the live wait is gone and there is one archive.
- This is a new check, because diff-6 noted the tests never kill there.

**Test runs**
- All 16 runtime tests pass.
- With `BENCH` set (as `tests/run.py` does), these also pass: `test_calibration_attempts`, `test_calibration`, `test_calibration_recovery`, `test_calibration_delivery`, `test_exam_responder`, `test_g10_overlap`, `test_budget`, `test_model_runtime`, `test_stream_d`, `test_saved_recovery_decisions`, `test_pilot_recovery`, `test_isolation_timeouts`, `test_recovery_routes`, `test_resume`, `test_restart` and `test_case_budget`.
- I did not run the full `tests/run.py`.
- Run without `BENCH`, some script-style tests fail on environment, not code.

## Test adequacy

**Covered**
- The streaming accountant on the real >$5 ledger.
- The wrapper pre-CLI failure.
- Missing, stale and expired authority.
- The deadline interrupt.
- The $44 plus $12 threshold.
- The writer completion → checkpoint → validation order.
- The three-wait chain for writer and stress.
- The flag-off path.
- Three owner HTTP outcomes.
- The validated-writer rebind.

**Gaps that matter**
- No test for a stress-unit rebind (B1).
- No test for `ordinary_limit_usd` across a restart (M1).
- The stress wait-chain subtest uses a free route (maximum 0), so only the writer subtest checks gap arithmetic.
- No kills inside `resume_provider_wait` (my probe covers two boundaries).
- No test of forged `provider_continuation` archives. The code checks UUID4, the `settled` flag, case, role, batch and job, the ledger `wait_settlements` entry and a null lease.

**Labelling:** the tests honestly use authored bounds, envelopes and config. They claim no real-crash, B/E qualification or row closure.

## Nits
- **Threshold on continuation:** the ordinary threshold applies at the new lease of a continuing writer unit, so a wait L1 → L2 can end in `budget_exhausted` mid-round. Worth one sentence in the design.
- **`>=` versus `>`:** `require_case_budget` uses `>=` and `reserve_invocation` uses `>`. This is diff-6 N6, still open.
- **Fallback lease match:** if a fallback lease is admitted but renewal fails before `before_attempt`, the record's lease is not the receipt's lease. `resume_operation.kind` then reads `crash`, although the unit still continues. I did not run a repro for this one.

## Required before merge
1. Fix B1 and add a stress-rebind regression test (pending and completed-with-findings). The design should state the rule.
2. Fix M1, or record it as an explicit obligation with the coordinator's `--case-budget` binding named.
3. Save this review verbatim as `docs/reviews/stream-d-diff-7.md`, with the fixed and rejected ledger, and run the full suite.

**Probe files** are in `/private/tmp/claude-501/-Users-bugsincode--t3-worktrees-unbug-bench-t3-21bef30c/c244178a-b9ea-4184-bc00-d32cfe925cad/scratchpad/`: `probe1.py`, `probe1b.py`, `probe1c.py`, `probe2.py`, `probe3.py`, `probe4.py`, `probe5.py`. Run each with `uv run --with numpy --with scipy python -B <path>`. The scratch fix copy is in `copy/` in the same directory.

## Elephant response and fixed/rejected ledger

- B1 accepted: pending and completed stress units must re-review at round n after a stale binding, retaining the unit until current findings can become writer feedback. Add both regressions.
- M1 accepted: preserve ordinary_limit_usd across restored-card startup and keep coordinator --case-budget binding distinct from cumulative job authority. Fix and test rather than defer.
- No finding rejected. No Murphy row closure claimed.
- Rebase onto factory-simplify after this completed review as instructed; cite the landed interfaces §8 for the B integration obligations. A fresh review and green full suite are required on the fixed/rebased tree.
