**Verdict: PASS.** No blocking finding is open for increment 2 (`6abe169..83110d2`). Both review-7 fixes in `233f89f` hold under my own probes as well as the committed tests.

---

# Stream D diff review 9: increment 2, after the review-7 fixes

**Verdict: PASS.** No blocking finding remains. Three non-blocking nits are carried forward, plus the obligations for later increments listed below.

**Scope.** `git diff 6abe169..83110d2` in worktree `t3-21bef30c`. The code changes are in `factory/budget.py`, `coordinator.py`, `exam_responder.py`, `model_runtime.py`, `run.py` and `token_prices.py`. I also checked the test, fixture and source-test changes and the design and review-record additions. I made no edits to the repo, and did no merge, push, launch, decryption or secret read.

**What I read.**
- `tools/egm/agents/zoom_out.md`, `implementation_readiness.md` and the implementation-readiness standard.
- `docs/ENGINEERING.md` and `docs/murphy-register.md`.
- `docs/designs/stream-d.md`: the Increment 2 scope, the B integration obligations, and the Diff-6 and Diff-7 runtime decisions.
- `interfaces.md` §8, which includes the conservative-resume join rule.
- Prior reviews `stream-d-diff-6.md`, `-7.md` and `-8.md`, with their elephant ledgers.

**Read limits.** My tooling truncated the long files, so parts of `stream-d.md` and the Murphy register came through as excerpts. I did not reread `interfaces.md` §§2, 3, 5 and 7, `router.md` or `invalid-runs.md` in full in this pass. I relied on reviews 7 and 8, which record having read them. This review re-checks the fixes and the runtime against §8 and the D design. It is not a fresh contract audit of §§2–7.

## Review-7 fixes checked

### B1 (stress-unit rebind): fixed

`run.py:1162` now enters the saved-review block for every modern unit (`modern or not binding_changed …`). The exhaustion and attempt-limit branch stays gated by `not modern`, so a plumbing rebind can no longer reach `attack_unresolved(…rounds_exhausted)`. At `run.py:1346–1351`, `same_review_unit` keeps `operation_id`, `review_attempt` and `rereviews` for a pending, completed or validated stress unit at round n. Only a pending unit counts as `continuing_review`, so its partial report is kept.

The committed tests cover this (`test_pending_stress_rebind_keeps_round_one_at_ordinary_round_limit` and `test_finished_stress_rebind_rereviews_before_delivering_findings`). I also ran two probes of my own, which subclass the real test fixture and use real module code:

- **`probe_rebind_window.py`: crash inside the re-review window.**
  - Setup: a finished review with a stale binding. The kill lands after `on_admitted` has archived the old report as `round-1-superseded-<hex>.json`, while the receipt still says `validated` with the old binding. Then `reconcile_reservations` runs and the case resumes.
  - Calls: `['builder-1','attacker-1','attacker-1']`. `builder_rounds` stays 1, and `operation_id` and `review_attempt` stay the same.
  - Result: crashing a second time mid-re-review spends no writer round and does not renumber the review.
- **`probe_feedback_source.py`: which report reaches the writer.**
  - Setup: the old-binding report says `OLD-BINDING-DEFECT` and the re-review says `NEW-REVIEW-DEFECT`.
  - The `builder-2` prompt contains only the new finding (`OLD in feedback False`, `NEW in feedback True`).
  - Result: this confirms the design rule that "only the current re-review can supply writer feedback".

### M1 (ordinary threshold across relaunch): fixed

- `inherit_recovery_history` (`run.py:2746–2759`) restores `ordinary_limit_usd`, which is otherwise lost when the card is rebuilt. It refuses a disagreement between the card's `case_budget` and `recovery_config` (`ordinary_limit_mismatch`), and it refuses a value of zero or less.
- `update_case_budget` (`model_runtime.py:213–235`) writes the ordinary value, never the commitment, into `recovery_config.case_budget`. It sets `args.case_budget` to the ordinary value. It takes `limit_usd` only from `JobAuthority`.
- `coordinator.configuration_args` (`coordinator.py:119–121`) binds `--case-budget` to `ordinary_limit_usd` when that field is present. It skips `max_cost` for the new profile, and it repairs cards from the earlier runtime that stored 200 in `recovery_config.case_budget`.
- `test_ordinary_limit_survives_card_rebuild_and_coordinator_binding` covers the $50 threshold against a $200 commitment, the erroneous legacy value, and the mismatch refusal.
- I grepped for every other consumer of `args.case_budget`. `founder_ruling.py:113` and `late_rehearsal.py:34` now see the ordinary value. That matches their semantics: a per-case allowance and a rehearsal ceiling.

### Review 8 (source-test migration)

Narrow, and unchanged since it passed.

## Runtime checks against the design and §8 (no defect found)

- **Reservation before work.** Wrapper calls reserve before `running()`, renewal and the credential re-read (diff-6 B1). `_settle_leaf` books an unreserved receipt at $0 only when the receipt is explicitly `denied` and final-known, with no events or IDs and a zero delta. Anything else still raises `usage_reservation_missing`.
- **The Popen `on_started` callback** separates a CLI setup failure (released at $0) from an interrupted process. Interrupted unknown usage is mapped in `unpriced_invocations` with the invocation and lease IDs, which matches the §8 conservative-resume requirement.
- **Factory `run_budgeted`.**
  - It requires a `JobAuthority`, an `invocation_id` and a `lease_id`, and a `max_cost` of `None`. It rejects a raw numeric limit.
  - It clamps the timeout to the absolute deadline and reports `retired_batch_bound`. Its stop-first list includes that label.
  - `require_case_budget`/`check_limits` gate on `total_spent_usd` plus outstanding reservations against the commitment, and raise `money_wait`. That is the label B collects under §8.
- **Dispatch.** One case RLock. The owner can bypass it only when it holds the program-set marker, its parent call is live, and the parent's reservation is pending. `prepare_dispatch` is used in `owner_server`.
- **Prices.** `PAID_PRICES` is the single shared table, and the `opencode_config` values match the `6abe169` literals exactly. The ×2, ×1.5 and ×2.2 factors are documented as the existing receipt tariffs (diff-6 N2). `ENFORCED_ROUTE_BOUNDS` ships empty, so production dispatch fails closed with `route_maximum_unknown` until E/A qualify the bounds.
- **Murphy rows.** No row closure is claimed, and the register and `interfaces.md` are unchanged in this range.

## Non-blocking nits (carried forward)

1. **N6 from diffs 6 and 7, still open.** `require_case_budget` uses `>=` while `reserve_invocation` and `check_limits` use `>`, so a free route is refused at exactly zero headroom. This errs on the conservative side.
2. **Diff-7 fallback-lease nit, untested.** If a fallback lease is admitted and renewal fails before `before_attempt`, the receipt's lease differs from the wait record's lease. `resume_operation.kind` then reads `crash` although the unit continues. The money path is unaffected; only the label is wrong. Add a test when the legacy receipt migration lands.
3. **`update_case_budget` overwrites `c.args.case_budget` on every call.** That is correct now, because `configuration_args` already binds the argv value to it. It does mean `args.case_budget` can no longer stand for an effective limit anywhere. Any later code that reads it as a commitment would be wrong. The design already says the effective limit comes only from `JobAuthority`.

## Tests run (in the worktree, `BENCH=$PWD uv run --with numpy --with scipy python -B …`)

- `tests/factory/test_stream_d_runtime.py`: 19 tests, OK.
- `tests/factory/test_coordinator.py`: PASS.
- `tests/factory/test_invalid_runs.py`: 34 tests, OK.
- `tests/factory/test_budget.py`: 39 tests, OK (1 skipped).
- `tests/factory/test_stream_d.py`: 17 tests, OK.
- Probes `probe_rebind_window.py` and `probe_feedback_source.py`: both pass. They are outside the repo, in `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/2ed179de-7518-4b1f-81f1-9fd7d37bd376/scratchpad/probe/`. Run each with `… python -B <probe> <worktree>`.

I did not rerun the full suite. The elephant's 139 scripts with 0 failures at `83110d2` stands as their record, not mine.

**Test gap worth adding later.** The window-crash re-review (my first probe) is a cheap regression test. Consider promoting it into `test_stream_d_runtime.py`.

## Obligations for later increments (not blockers here)

- **Diagnosis, extensions and stage snapshots.** Diagnosis must use the content-free D eligibility/projection API and the ordinary same-owner resume. B's increment2b must deliver acknowledged source transitions, collection proofs and replacement derivation before resume or adapter enablement.
- **Unknown total at launch.** An exhausted owner whose total was unknown at launch must checkpoint and exit after settlement with no model call. B must acknowledge it before a dependent replacement or diagnosis can run.
- **`reconciled_decrease`.** It is acceptable only when it matches an earlier `unpriced_invocations` ID or `wait_id`.
- **Legacy receipt and import migration**, including the `resume_operation.kind` labelling (nit 2).
- **Removing stale allowances and caps across launch, resume and audit.** The legacy `not modern` branches in `write_and_attack` must stay unreachable for authenticated jobs until then.
- **Scientific binding and gate-version migration**, including the saved-card fingerprint exam.
- **E/A qualification of `ENFORCED_ROUTE_BOUNDS`**, plus B/E lifecycle qualification against §8.
- **Real crash and capped-call closure exams for Murphy rows 8–13, 15, 21, 35 and 39.** None closes on this increment.

## Elephant resolution

- PASS accepted for increment 2, 6abe169..83110d2. Review-7 B1 and M1 are independently verified fixed; no blocking finding is open and none is rejected.
- The review's read limits are retained verbatim. This is a runtime/fix review against the passed design and §8, with the prior contract reads recorded in review 7; it is not claimed as a new full contract audit.
- Nits remain non-blocking: exact-zero free-route headroom, fallback wait/crash telemetry, and args.case_budget being the ordinary threshold. Increment 3 retains effective authority exclusively in JobAuthority.
- No Murphy row closes. Real-artifact crash/capped-call exams and B/E/A rollout qualification remain outstanding.
- The required full-suite rerun follows the review request on the unchanged 83110d2 production/test tree. Its final result will be appended before handoff.

## Full-suite validation

`uv run --with numpy --with scipy python -B tests/run.py` completed after
review 9 was requested: **139 scripts, 0 failed**, exit 0. The production/test
tree was unchanged from 83110d2. Log:
`/tmp/stream-d-increment-2-review9-suite.log`. Only documentation was edited
while this run executed. No Murphy row is claimed closed.

