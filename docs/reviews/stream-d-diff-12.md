**PASS: B1 is closed.** I made no repo writes, commits or pushes; the worktree still shows only `.stream-d-next/` as untracked. My two exported copies are in `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/72b4f42e-6dc0-4fc4-9e6d-a7b7d2a7e00c/scratchpad/head` and `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/72b4f42e-6dc0-4fc4-9e6d-a7b7d2a7e00c/scratchpad/mut`.

- **The fix works.** The new regression test passes on 9cb25e6. With the 2-line fix taken out, both of its cases fail for the right reason (`reservation_already_invoked` replaces the real error). The test checks everything diff-11 asked for, and the existing estimated-row refusal test still passes.
- **The full suite passed:** 143 test scripts, 0 failed. The log doesn't record which commit it ran on. It shows the runtime file running 21 tests, which matches 9cb25e6 (it was 20 before), so it ran on that commit or later. You may want to note that in the merge record.

Review text for `docs/reviews/stream-d-diff-12.md`:

---

# Stream D diff review 12: B1 re-review (7c7bc7e..9cb25e6)

**Reviewer:** fresh goldfish, read-only, Mode: REVIEW. Personas: `zoom_out`, `implementation_readiness`. Standard: `implementation-readiness-standard.md`.
**Branch:** `t3/stream-d-implementation`, worktree `t3-21bef30c`, head 9cb25e6.
**Scope:** limited to diff-11 B1, as diff-11's Result allows. Three parts:
- `factory/budget.py` `release_uninvoked`;
- `tests/factory/test_stream_d_runtime.py::test_pre_route_failure_preserves_original_error_after_double_release`;
- the interfaces §8 sentence that clarifies idempotent release.

**Context read:** `docs/reviews/stream-d-diff-10.md` and `-11.md`, including their resolutions; the passed `docs/designs/stream-d.md`; interfaces §8.

**Out of scope:**
- the legacy-import proposal edits in the same commit, which have their own design review;
- the untracked `.stream-d-next/` drafts.

The rest of 6e7925e..f7ff54a already passed in review 11 and is not re-reviewed.

## Verdict: PASS, 0 blockers, 0 nits

## B1 (diff-11): closed

**Code.** `release_uninvoked` now returns early only for a row with all of these:
- `state == 'settled'`;
- empty `event_ids`;
- `estimated_gap_usd` equal to zero.

That is exactly the state a release produces. Every other non-pending row, and every row with events, still raises `reservation_already_invoked`. This includes an `estimated` row, whose gap only evidence-backed settlement may release.

The fix is in the shared function, so both unwind paths are covered without touching either caller:
- `ModelRuntime._call`'s `except BaseException` and its router family-change branch (`factory/model_runtime.py` around lines 300–335);
- `run.pending_call`'s `except BaseException` (`factory/run.py` around line 355).

**Interfaces §8.** The sentence now says `release_uninvoked` accepts an already-settled empty zero-gap row as an idempotent no-op and otherwise refuses every non-pending reservation, including an estimated row with no events. This matches the code. The design rule "only settlement releases an estimated gap" is unchanged.

**Regression test.** It drives a real `run.pending_call` on the saved 5813be continuation ledger. It has two subtests:
- `money_wait`: `case_budget_boundary` is patched to raise `BudgetError('money_wait')`.
- Real family change: the writer is pinned to `strong_calibrator`, so `_call` raises `ValueError('role family changed')`.

Each subtest asserts:
- the original error is kept, with the regex anchored to the full message (`^…$`);
- exactly one reservation row exists (by tuple unpacking);
- that row is `('settled', [], '0.000000000')`;
- `case_spending` total equals the baseline, so the total is unchanged.

All three assertions diff-11 required are present.

**Mutation check.** I exported HEAD twice with `git archive` into scratch, and removed only the two added lines from one copy.
- **HEAD:** `test_stream_d_runtime.py` passes 21/21. `test_stream_d_coverage.py` passes 10/10, including `test_release_uninvoked_refuses_estimated_row_and_zero_release_rounding`.
- **Mutant:** both subtests fail. `family_change=True` errors with `reservation_already_invoked` raised while handling `ValueError: role family changed`. `family_change=False` fails with `"^money_wait$" does not match "reservation_already_invoked"`. The coverage file still passes 10/10.

So the test proves B1. The estimated-row refusal is intact.

**Simplicity.** The fix is a two-line guard in the single shared function. It adds no new path, flag or caller-side bookkeeping.

## Full suite

`/tmp/stream-d-increment3-rebased-suite.log` finished with `143 test scripts run; 0 failed.` It was last modified at 05:04:13, 90 seconds after the 9cb25e6 commit time (05:02:43). Its `test_stream_d_runtime.py` section ran 21 tests, which matches HEAD with the new test. f7ff54a had 20. The earlier launcher polling-timeout failure is not present in this run.

The log does not record which commit it ran on, so this attribution is indirect.

## Murphy register

Unchanged, and no row closure is claimed. That is correct for this re-review.

## Result

PASS. Diff-11 B1 is fixed, and the regression test is shown to fail without the fix. Together with review 11, increment 3a has no open blocker.

## Elephant resolution

(none required)

---

## Implementation validation record

PASS accepted. No blocking finding was rejected. Full command: `uv run --with numpy --with scipy python -B tests/run.py`, 143 scripts, zero failures. The run began at f7ff54a; the release-uninvoked fix and its test landed before the runtime file executed (21 tests). This was not a pinned immutable-tree run. The fix's focused test also passed separately, and the reviewer tested an immutable 9cb25e6 export and a failing two-line mutant. No Murphy row closed. Extension/diagnosis runner integration and remaining migration are still outside 3a and incomplete.
