**PASS.** I found no blocking issues. There are three optional nits at the end. The fourth commit, 0091cb1, adds only the suite reports.

**What I checked** (b510308..HEAD against `docs/designs/stream-d-row13.md` and its passed review `stream-d-row13-design-1.md`, read-only, Mode: REVIEW, using `zoom_out` and `implementation_readiness` with the implementation-readiness standard)

**zoom_out**
- The fix stays small and adds nothing new. The new report fields go inside the existing `aggregate()` in `factory/stress_progress.py:318-327`. The timeout handling is one `except BudgetError` around `answer()` (`:375-382`), so it sits outside `invoke`'s `finally`. This matches the design-review clarification.
- No execution path, allowance or retry was added or removed. No item-7 routing changed. There is no fresh model call, diagnosis or money change, and the original error is re-raised unchanged.
- Removing the `write_and_attack` barrier is safe:
  - `Ctx.__init__` installs the barrier (`run.py:125`).
  - `stress_categories`, `opencode` and `pending_call` re-install it before every dispatch (`run.py:208,213,400`).
  - So pending publication still drains before any resumed model call.
  - Both production callers of `write_and_attack` (`run.py:560`, `:2978`) pass the real run context.
- The HTTP prose fix only changes the text from `http_5xx` to `http_500–http_599`.

**implementation_readiness / row 13 closure**
- **Real artifacts:** the three named tests use the hash-checked practice case (`invalid-runs-practice.json.gz`, checked against its SHA-256 values) and the 5813be card and ledger. They run through `write_and_attack`, the real `ModelRuntime._call` and the router. The timeout is injected at `_invoke`, the same place where real timeouts already raise `BudgetError('timeout')` (`model_runtime.py:410,628`).
- **Incomplete CLI bytes never score:**
  - `aggregate()` reads only completed category outputs whose hashes are recorded. Partial files are only listed in the index with their path and SHA-256.
  - The `after_categories` case writes an untrusted partial containing `"category_complete":true` and `blocking:["untrusted"]`. The test asserts `blocking == []`, `status == pending` and `complete == False`.
  - The malformed-partial case shows that broken JSON is hashed and never parsed.
- **Coverage, operation and round are kept:**
  - The test asserts exact coverage of the completed categories, unfinished subchecks still pending, and the retained observations.
  - It asserts that the report's `operation_id` and `round` match the receipt, that the receipt is pending with `review_pending`, and that the publication marker is pending.
- **Archive/restore proves the report survives:**
  - The work tree is really archived with tar, deleted and restored. The report is identical after the round trip.
  - A fresh production `Ctx` resumes only the unfinished categories (call count matches).
  - The report becomes `scored` with `complete` true and `stop_reason` cleared. The operation is unchanged, `builder_rounds == 1`, and the completed `*-0.json` bytes are identical.
- **Would the tests catch a regression?** Yes. Removing the new `except` would fail the `stop_reason == 'timeout'` check. Promoting partial bytes into findings would fail the `blocking == []` check.
- **Murphy register:** row 13 is set to `closed`, names exactly these three tests, and is scoped to report loss only. Recovery and live timeout/publication checks stay with row 9 and item 8.
- **Item 7:** nothing leaks into item-7 scope.

**Tests and suite**
- I re-ran the three row-13 tests plus `test_category_kill_resumes_only_unfinished_and_preserves_operation`: 4 passed in 19.9s.
- I did not re-run the full suite. The committed log `stream-d-row13-suite-20261031T120851Z-7ce43f36.log` matches the SHA-256 recorded in its JSON (`f3e44608…`). It records `158 test scripts run; 0 failed.` on 1836d18 and includes the held and retries scripts. HEAD differs from 1836d18 only by the report files.
- The earlier failed run is kept and honestly labelled. The held-test constructor fix in 1836d18 changes test code only.

**Item 8**
- Commit 980d9d8 changes documentation only: `stream-d.md` and the three item-8 review files.
- The response's fixes for M8, M9 and the nits are all present in `stream-d.md`:
  - carrying both the original and the queued replacement to beta-fixed (`:3416-3422`);
  - the new-spend formula (`:3441`);
  - account-2 evidence correlated across both the scenario-1 and scenario-4 windows (`:3558-3559`);
  - 10 minutes of slack and a cleanup cutoff (`:3564-3566`);
  - scenario-6 replays gated on the time left in its window (`:3567`).
- The flag stays off and no spend is authorized. This is consistent with the PASS in `stream-d-item8-design-3.md`.

**Nits (optional)**
1. `stop_reason` is only recorded when `answer()` raises. Stops raised elsewhere in the loop (`stress_validation_exhausted`, `case_changed_during_review`) leave the last report pending with no reason. That is within the design's scope; one line in `aggregate` or the loop could cover them later.
2. `stream-d.md:3561`: "…5 minutes for scenario 7 and 5 minutes for scenario 3 (overriding the 10-minute default above)" reads awkwardly. Saying "10 minutes each for scenarios 1, 2 and 4; 5 for scenario 3" would be clearer. The total of 70 minutes is correct.
3. `status` is `'scored'` whenever `blocking` is non-empty, even if coverage is incomplete. That matches how `finish()` already ends on blocking findings, but one comment saying so would help a reader of the report alone.

## Elephant response

Accepted PASS. Optional nit 2 clarified in the plan's time allocation. Nits 1 and 3 are deferred: timeout report preservation is this increment's scope, and scored blocking findings retain the existing early-finish semantics. No code changed after the passing full suite. Review-report trailing blank-line cleanup changes neither verbatim reports nor their responses.
