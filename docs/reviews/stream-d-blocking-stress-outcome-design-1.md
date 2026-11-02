**NOT PASS.** One blocker and three nits. Design round 1 of 2, read-only on `t3/stream-d-implementation` @ 7a8dbb0 (design content as of 4cc2ddd).

**What holds.** The proposed predicate does what the design claims for its stated cases:
- **Writer loop already reaches package stress.** `run.py:1623-1628` keeps findings even when `complete` is False, writes `exhausted=True` and `stop_reason=rounds_exhausted` (`:1641-1646`), and `extension_package.run` catches that stop and calls `stress()`. The only obstacle is the refusal at `extension_package.py:293`, as the design says.
- **Category engine already lets a blocker win.** In `stress_progress.py:64,97,162`, a blocker wins over an unfinished diagnostic and over incomplete coverage. Interrupted calls keep only `*-partial-*` bytes, which `aggregate()` never reads (`:89-91`, `:139-146`).
- **Sentinel and legacy handling are exact.** `findings` copies `extension_evaluator.py:217` and `run.py:1623`. `classify` already moves `validation unfinished:` items out of blocking (`attack_findings.py:17`). Refusing when there are no findings but `blocking` is non-empty correctly covers a lone `review incomplete`.
- **`review_pending is False` breaks no current caller.** Every real receipt that reaches `stress()` ends with it False (`run.py:1617`). It matches `extension_public_match.py:51`.
- **`Records.save` accepts the failure as a scored result.** `comparison._pending` (`extension_compare.py:98`) does not look at `complete` or `unfinished_validation`.
- **Crash replay works.** It works after the stress record (`Records.load` comes first) and after outcome publication (`extensions._save_case` re-checks an existing directory, `:178`).
- **Test plan is practical.** `stress_categories` can be captured before `RuntimeTests.setUp` patches it (`test_stream_d_runtime.py:86`). Category output goes through `config['category_output']` and the checkpoint uses `c.stress_checkpoint = lambda: True`, as `test_stream_d_retries.py:48,224` already does.

### Findings

**1. Blocker: a real finding plus an excluded freshness request leaves the extension pending forever.**
- **Where:** design lines 45-46 ("Keep the existing freshness clearance branch before deciding…") and table row 78; code `extension_package.py:288-291`, `run.py:1135-1136`, `late_recovery.py:104-116`.
- **What happens:**
  1. The attacker lists a URL in `freshness_review` (the category schema requires the list, and `case_freshness/public_search` will often fill it). Its blocking findings are real defects, not request lines.
  2. `loop_freshness` finds the URL excluded. Because `freshness_only_clearance` removes nothing, it returns at `run.py:1136` and writes no `-writer.json` and no `.clearance.json`.
  3. The writer loop then exhausts normally and package `stress()` runs.
  4. `stress()` sees `result['freshness_review']` and calls `cleared_stress`.
  5. `read_object` on the missing clearance raises `Refused`, a `ValueError` subclass, which becomes `extension_execution_pending`.
  6. On resume the saved exhausted receipt goes straight back to `stress()`, so this repeats every time. That is a permanent human stop on a valid scored failure, and the design's objective (lines 5-7) is false for it. It already affects complete blocking failures too.
- **Why the fix is safe:** clearance can only remove exact request lines (`cleared_stress` requires `parsed == freshness_only_clearance(original)`). Any finding that is not a request line therefore survives clearance, and the verdict is fail either way. Reaching `stress()` through `rounds_exhausted` also means the last `loop_freshness` neither raised `freshness_public_match` nor `freshness_unresolved`.
- **Fix:** in `stress()`, compute `real = [v for v in freshness_only_clearance(result)['blocking'] if v.strip().lower() != 'review incomplete']` before the freshness branch.
  - Call `cleared_stress` only when `real` is empty, i.e. only when clearance could change the verdict.
  - Otherwise skip it and keep the authenticated original report, unrewritten, as the detail.
  - `findings` and all later predicates stay as designed.
  - Change table row 78 to read: "Unresolved/unverified freshness when clearance would decide the verdict".
- **Tests:**
  - Positive: real blocker plus a non-empty `freshness_review` that the real `loop_freshness` excludes (only `confirm_hits` stubbed as a labelled control) should give stress fail and a completed outcome.
  - Negative: request-only blocking with no clearance file should still give `extension_execution_pending`.
- **Alternative:** if the elephant keeps the parent's "freshness retained as-is" scope, the design must state this stop explicitly in the table and add a test that asserts it. The objective's claim cannot stay unqualified either way.

**2. Nit: the test setup should say which `ExecutionTests` patches the new file keeps.**
- **Where:** design lines 105-111.
- **Issue:** `ExecutionTests.setUp` makes `loop_freshness` a no-op, and makes `early_review` and others raise (`test_stream_d_execution.py:74-79`).
- **Fix:** name the patches the new file keeps. `loop_freshness` must be real, or an explicitly labelled control, for the freshness cases (finding 1 and the "unresolved freshness" negative).

**3. Nit: a report holding only a legacy unfinished label is marked scored.**
- **Where:** `stress_progress.py:82,97,162`.
- **Issue:** `aggregate()` counts `blocking` before classification, so output that contains only a `validation unfinished:` item gets `status='scored'` and calls `completed()`. Package `stress()` and the writer loop (`run.py:1625`) still refuse it, so this is not a hole.
- **Fix:** none needed in this slice. The planned "legacy unfinished label" negative test should assert that the receipt is marked completed while history stays open, so the behaviour is pinned.

**4. Nit: the objective section is hard for a newcomer to read.**
- **Where:** design lines 9-23.
- **Issue:** the Heilmeier objective leans on internal names ("lane 1 slice 2", "remaining-item-7", "Murphy 9").
- **Fix:** add one plain sentence before them: "When the stress reviewer has finished a call and found a real defect, record a failure and send it to diagnosis instead of waiting forever."

All other standard items are present: cost, timeline, risks, exams, the file list (one production function plus one new test file) and a single phase. The two downstream guards, the `InvalidInfra` path, the comparison-pending path and the stop propagation are all unchanged and correct. Nothing was left for the implementer to decide apart from finding 1.

### Skipped checks and risks
- I ran no tests and inspected no saved 5813be or practice artifacts beyond the fixture loaders. Feasibility of the real category engine under `RuntimeTests` (publication dispatch, `c.stress_checkpoint`) is inferred from `test_stream_d_retries.py`, not run.
- I did not read `finalize_accounting` or the diagnosis-queue internals, so "one pending diagnosis ID" is unverified.
- I did not review the accepted public-match slice, the lane-2 entry path (`observe_stress`) or parent accf0bc, as instructed.
- How often attackers fill `freshness_review` in real runs is not measured. Finding 1's severity rests on the category schema requiring the list and on the `public_search` subcheck, not on observed frequency.

## Elephant disposition

B1 accepted, no rejection: compute surviving defect findings through freshness_only_clearance before deciding whether clearance is necessary. When a completed real defect decides failure, retain the original authenticated report; clearance must still authenticate any verdict it could change. Add real loop_freshness exclusion-without-clearance coverage and a request-only missing-clearance refusal. N1–N3 accepted: name fixture patches, pin the completed legacy-label/no-outcome boundary, and add the plain objective sentence. Fresh final design review required before implementation.
