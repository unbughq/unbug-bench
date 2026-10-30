The diff review fails with **one blocker**. I reproduced it on the branch and confirmed it is not on the base commit. The fix is small. Your rebased suite run was still going when I finished, so I can't report a full-suite result.

I edited and committed nothing. The worktree status is unchanged: only `.stream-d-next/` is untracked. My scratch repro is `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/975f74a7-07ea-4ed6-972f-771e2aecc33c/scratchpad/repro_double_release.py`.

Review text for `docs/reviews/stream-d-diff-11.md`:

---

# Stream D diff review 11: increment 3a (6e7925e..f7ff54a)

**Reviewer:** fresh goldfish, read-only, Mode: REVIEW. Personas: `zoom_out`, `implementation_readiness`. Standard: `implementation-readiness-standard.md`.
**Branch:** `t3/stream-d-implementation`, worktree `t3-21bef30c`, head f7ff54a.
**Reviewed against:** the passed `docs/designs/stream-d.md` (Increment 3 and the "Increment 3a review boundary"); interfaces §§2, 3, 5, 7, 8, including the increment-3 subsection "D coverage, reconciliation, and diagnosis APIs"; Murphy D rows 8, 9, 10, 11, 12, 13, 15, 21, 35, 39.
**Out of scope:** extensions, runner wiring and the remaining migration (all 3b), and the `.stream-d-next/` drafts.

## Verdict: FAIL, 1 blocker

## Blocker

**B1. `release_uninvoked` is no longer idempotent, so a second release now hides the real stop reason.**

- **Where:** `factory/budget.py` `release_uninvoked`. The design line "release_uninvoked refuses non-pending rows" is implemented as `if row['state'] != 'pending' or row['event_ids']: raise`.
- **What goes wrong:** some failure paths release the same lease twice.
  1. `run.pending_call` reserves the lease, then hands it to `opencode` → `ModelRuntime._call`.
  2. If anything fails in `_call` before the route receipt is written, `_call`'s `except BaseException` releases the lease (`factory/model_runtime.py:301-305`, and `:329-333` for a router family change). The row becomes `settled`, gap 0, no events.
  3. The exception reaches `run.pending_call`'s `except BaseException` (`factory/run.py:355-359`). The lease is not in `route_receipts`, so it calls `release_uninvoked` again.
  4. At 6e7925e the second call was a harmless no-op. Now it raises `BudgetError('reservation_already_invoked')`.
  5. That error comes out of a `try/finally`, so it replaces the original exception. Example originals: `money_wait` from a concurrent settlement racing `require_case_budget`, `budget_exhausted`, `role family changed`, `router changed family`, cancellation, or a failure in `reconcile_reservations`.
- **Why it matters:** callers decide what to do from the error string (for example `factory/run.py:3045`, and `budget_exhausted` feeding `diagnosis.exhaustion`). A retryable money wait or a budget exhaustion would become an unrecognised terminal stop. That is a pit stop, and it skips diagnosis. This is the exact failure class rows 8–13 cover. Production dispatch is fail-closed today, but this is a regression in code this increment changed, and 3b would inherit it.
- **Reproduced:** I used the real `RuntimeTests` harness (the 5813be ledger and the job-money fixture). I patched `model_runtime.case_budget_boundary` to raise `BudgetError('money_wait')`, then called `run.pending_call(... 'builder-1' ..., role='writer')`.
  - Head f7ff54a raises `reservation_already_invoked`.
  - A `git archive` export of 6e7925e raises `money_wait`.
- **Fix:** fix it once, in the shared function. An already-`settled` row with no `event_ids` and a zero gap should return without error, because it is exactly what a release produces. Keep refusing `estimated` rows and rows with events, which is what the design rule is for. This keeps both callers correct without touching either one.
- **Required test:** add a runtime test that drives a pre-route failure through `run.pending_call`. Assert three things:
  - the original error identity is kept, for `money_wait` and for a family-change `ValueError`;
  - there is exactly one reservation row, `settled`, gap `0.000000000`, with the total unchanged;
  - `test_release_uninvoked_refuses_estimated_row_and_zero_release_rounding` still passes.

## Prior findings rechecked

- **diff-10 B1 (stale `wait_settlements.lease_ids` on replay): fixed.** Each replay now takes the union of the retained leases and the current reservation-backed leaves. `test_wait_replay_retains_new_lease_provenance` checks three things: the record holds all three leases; the late final lease gets its own decrease with the correct `wait_id`; and the partial lease's coverage `wait_ids` is correct. A further replay leaves the ledger byte-identical. This proves the fix.
- **diff-10 N1 (unreserved zero-usage denial in the lease list): fixed.** Leaves without a reservation are filtered out. `test_unreserved_zero_usage_denial_keeps_coverage_available` proves it.
- **diff-10 N2 (current stop overrides a stale infrastructure marker):** this is accepted as an obligation on 3b's runner. `test_later_budget_exhaustion_uses_its_current_diagnosis` matches the interface text. Not re-raised.

## 3a scope checked, no other blockers

- **Diagnosis projection APIs.**
  - `diagnosis.exhaustion`, `actual_model_work` and `pending_projection` are pure. They read only `card['terminal_stop']` and top-level `diagnosis_state` / `extension_history`, and reuse `recovery.infrastructure_exhausted`.
  - They refuse pause, provider wait, sealed, retired, `G12` pass, and malformed or extra fields.
  - The projection is exactly `{schema_version:1, status:'pending', replacement_eligible}`, and it is `false` when the stop is infrastructure.
  - A bare reservation or a gap alone does not count as model work.
  - The tests' identical-output and no-mutation assertions hold.
- **`diagnosis.py` in the worker manifest:** the manifest test is updated.
- **Coverage.**
  - `usage_coverage` shares `_spending`'s raw Decimal total with `case_spending`.
  - It fails closed on duplicate or shared events, binding mismatches, malformed rows or gaps, unmapped markers, and `unpriced_events != len(unpriced_invocations)`.
  - Repeated markers fold into a single maximum.
  - The output shape and nine-place strings match §8. Nothing is persisted.
  - It returns non-None on all 56 saved cards. The legacy test asserts covered ≥ total.
- **Retained receipts and decreases.**
  - Final receipts are written once per canonical hash: temp file, fsync, replace, then directory fsync, and only before the ledger transaction records the hash. A mismatched existing file or a symlink refuses.
  - A decrease is emitted only on the estimated→final transition, inside the settlement transaction, and only when `released > 0`, with the §8 formula.
  - Unrelated unknown usage does not suppress a decrease.
  - `case_spending` ignores `reconciled_decreases`.
  - Rounding-to-zero emits nothing.
- **Telemetry.** `max_total_calls` is skipped only when `job_authority` is a `JobAuthority`, at both the pre-call and in-loop checks. `max_role_calls` / `call_limit` still apply. The real 2496, 1627 and 1040 ledgers keep their original events and totals and show `model calls: N (telemetry)`.
- **Murphy register:** unchanged, and no row closure is claimed. That is correct: these are authored inputs replayed on saved bytes, which the design says cannot close the rows.

## Nits (optional)

- **N1.** `budget.usage_coverage` imports the private `diagnosis._uuid4`. That makes the money module depend on the diagnosis module. Moving the UUID4 check into `budget` (or importing it the other way round) keeps the money path standalone.
- **N2 (3b obligation, not 3a).** Other cumulative call ceilings still stop authenticated factory cases:
  - `factory/restart.py:87` refuses a resume when `calls >= max_total_calls` (1000 by default), so the 5813be, e15450 and 873d7f cards cannot resume through the planner;
  - `factory/run.py:2905` defaults resumes to 1000;
  - `gate_state.py`, `g11_review.py` and `founder_decisions.CALL_CAP` also cap calls.

  3b's stale-cap migration must retire these for new-schema factory cases. Otherwise the telemetry ruling only holds inside `run_budgeted`.

## Tests run by the reviewer

- `tests/factory/test_stream_d_coverage.py`: 10 tests, OK.
- `tests/factory/test_stream_d_projection.py`: 6 tests, OK.
- `tests/factory/test_stream_d_runtime.py`: 20 tests, OK.
- `tests/factory/test_stream_d.py`: 17 tests, OK.
- B1 repro: FAILS on f7ff54a, passes on 6e7925e.
- Full suite: `/tmp/stream-d-increment3-rebased-suite.log` was still running when I finished. `test-launch-guards.py` had printed only passing checks so far, and the log had reached `tests/bench/test_exam_verifier.py`. The suite must pass before merge (ENGINEERING step 4).

## Result

FAIL until B1 is fixed with its regression test and the full suite passes. After that, a re-review limited to B1 is enough.

## Elephant resolution

B1 accepted. Shared release_uninvoked now treats an already-settled empty zero-gap row as an idempotent release. Estimated rows and rows with events still refuse. Added test_pre_route_failure_preserves_original_error_after_double_release for money_wait and a real family-change ValueError through pending_call. No finding rejected and no Murphy row closed.
