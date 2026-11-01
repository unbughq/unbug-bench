## Verdict: PASS (no blockers)

The fix in `1b05499` correctly refuses an unresolved comparison, and it doesn't refuse a resolved one. It follows the corrected table row in `docs/designs/stream-d-outcome-routes.md`. I found no blocking or major issues, only three optional nits.

**What I checked:**
- **The guard** at `factory/diagnosis_dispatch.py:238-243`:
  - It only runs when no extension is active and the last history row belongs to a different exhaustion.
  - That last row is guaranteed to have an outcome, because `extensions.active()` returned None and `extensions.read()` rejects any non-last row whose outcome is None. So `prior['outcome']['stages']` can't fail.
  - A missing pair or a `pending` result stops with `extension_comparison_pending`. That is a `BudgetError` raised through `stop()`, and `dispatch()` re-raises it unchanged instead of turning it into `diagnosis_input_invalid`.
- **An unresolved comparison can't be skipped silently.** Apply refuses it. Even after the sentinel 0, `admit_extension` and `extensions.propose` check again at the current versions: they refuse on pending, retire on no progress or regression, and require the current snapshot to equal the selected outcome. Today `admit_extension` refuses anyway, because `extension_package.entry` doesn't exist.
- **A resolved comparison isn't over-blocked.** It falls through to the sentinel 0 when `DIAGNOSIS_ENABLED` is on, and to the existing stop when it's off. `test_stream_d_dispatch.py::test_second_extension_active_dispatch_verifies_frozen_completed_history` covers this. The first, broader guard (`579a6a8`) failed that test, and the committed suite log `…140359Z-33a99a55.log:887-915` records it honestly.
- **Untouched paths:**
  - Same-exhaustion recovery still goes through `completed_route` or `writer_receipt` and returns the positive extension ID.
  - Empty history still returns sentinel 0.
  - When `DIAGNOSIS_ENABLED` is off, the stop label is the same as before.
  - All three `apply` callers (`invoke`, the valid-journal branch in `_dispatch`, and `replay`) go through the one guard.
- **Compared with before the merge:** at `8b71a75`, any different exhaustion stopped with `extension_comparison_pending`. This fix is strictly more permissive than that, but only when the prior comparison is resolved. So nothing that was safe before is now unsafe.
- **Tests and records:**
  - No test files changed between `ab2780d` and HEAD.
  - The suite record `…143939Z-90c224cd.json` shows head `1b05499`, exit 0, and the log ends with "168 test scripts run; 0 failed."
  - I re-ran only `PackageTests.test_dispatch_recovers_history_committed_before_card` offline: 1 test, OK.
  - The worktree is clean.

## Findings

**1. Nit: the guard picks its comparison at the old outcome versions, while admission picks at the current versions**
- **Where:** `factory/diagnosis_dispatch.py:240-242`, compared with `factory/extensions.py:397-401` (`propose`).
- **Evidence:** `extension_compare.compare` re-scores at the current bench versions and stores the result with `retain_comparison`, but `row['outcome']` keeps the old versions. Suppose a gate changed during the prior extension and changed again afterwards. The original pair would be pending at the outcome versions, and the only resolved pair would be at the newer versions. Apply would then refuse with `extension_comparison_pending` every time, even though `propose` would accept it.
- **Why it isn't a blocker:** nothing in production calls `compare` or `retain_comparison` (I grepped), so `comparisons` is always empty today. The design also scopes this rule "until a separately reviewed comparison route replaces this boundary."
- **Requested fix:** when the comparison producer gets wired in, make the apply guard choose versions the same way `propose` does (current versions), or remove the guard and rely on admission. You could add a one-line Murphy or design note now so this isn't forgotten.

**2. Nit: the new stop doesn't save the scorecard first**
- **Where:** `factory/diagnosis_dispatch.py:243`.
- **Evidence:** every other `close_to_passing` exit calls `atomic_json(c.work / 'scorecard.json', c.card)` before `stop()`. Before the merge, this case also saved the scorecard and then stopped. The new path raises with the card changed only in memory.
- **Impact:** none that I can see. The `BudgetError` handler in `run.py` (around line 3397) records `terminal_stop`, and `decision.json` is already saved for replay.
- **Requested fix (optional):** save the scorecard before the new `stop`, so this exit matches the others.

**3. Nit: the `replay` path isn't tested directly for the different-exhaustion refusal**
- **Where:** `replay(...)` → `apply(..., resume=True)`.
- **Evidence:** the package test calls `apply` directly, and the dispatch test goes through `invoke`. The guard is shared code with no dependence on `resume`, so the risk is low.
- **Requested fix:** none needed for this change. Add a test if replay gets its own handling for this case later.

**Process:** skipping the design review under the ENGINEERING §1 small, obvious-cause exemption is justified: the code change is 6 lines and the cause is documented in the commit messages. No new Murphy row is needed, because this regression came from a merge test and not from a real run.

## Elephant disposition

PASS recorded; no blocking findings rejected. Optional nits deferred. Nit 1 remains a prerequisite for the separately reviewed current-version comparison producer: align apply's version selection with propose or replace this boundary there. Nits 2/3 require no change for this fix; the existing main checkpoint and shared apply guard retain the reviewed behavior. No test or production source changes after the 168/168 suite pass at 1b05499. No Murphy row closure.
