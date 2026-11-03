**Verdict: BLOCKING.** This is goldfish design review round 2 of 2, run in `Mode: REVIEW` and read-only on `t3/isolation-o5b` @ b507211 against baseline 7f1c09e. I used the zoom_out, design_critic and implementation_readiness personas, checked against heilmeier-standard and implementation-readiness-standard. I made no edits, model calls or live actions.

All seven round-1 findings are resolved. One new blocker remains: the main retirement condition never matches the report shape that the pilot's category-mode stress reviewer actually produces.

## Round-1 findings: status

| R1 | Status | Where it was fixed |
|---|---|---|
| 1 Blocker: a cleared request with no metadata holds forever | **Resolved** | Lines 55-63 widen the trigger to fire when `.clearance.json` is present (a symlink counts). They reuse `late_recovery.cleared_stress`, and retirement now requires both artifacts to be absent (lines 43-46). Checked: `read_object` and `sha` reject symlinks with `Refused`, and `Refused` is a `ValueError` (`carry_over.py:43`). The `except` at `extension_package.py:382` catches it, so a dangling or valid symlink falls to `refuse('extension_execution_pending')`. A stale clearance file from a superseded attempt fails `source_sha256` and holds, which is the safe direction. |
| 2 Major: money wording | **Resolved** | Lines 78-82, and exam 4 at lines 144-147, now match `batch_money`/`batch_service`. |
| 3 Major: evaluator and writer residuals | **Resolved** | Lines 101-106 state both residuals and require them in handback. |
| 4, 5 Nits: problem statement and plain lead | **Resolved** | Lines 5-7 and 12-13. |
| 6 Nit: exact calls | **Resolved** | Line 52 names the `_pending` call. It matches `Records.save:197`'s existing InvalidInfra, so `test_invalid_execution_detail_does_not_become_case_failure` keeps its meaning. Lines 83-87 give the status mapping, lines 96-99 the `DIAGNOSIS_ENABLED` setting, and lines 133-134 the `confirm_hits` raise. |
| 7 Nit: cross-batch filter | **Resolved** | Lines 107-108 mark it out of scope. |

## New findings

### 1. Blocker: `complete is True` excludes the real category-mode request-only report, so the pit stop stays

- **Where:**
  - Design line 35 (`complete is True`), the claim at lines 17-19 that it "removes that pit stop", and exam 1 at line 129.
  - Code: `factory/stress_progress.py:13-20, 68, 82, 97, 162-163`, `factory/run.py:1610-1628`, `factory/extension_package.py:384-386`.
- **What the code does:**
  - Modern extension rounds always go through `stress_categories`. The order is fixed: `wrong_fixes`, `case_freshness`, `fairness`, `v2_strategies`.
  - As soon as any category result has blocking entries, `aggregate()` writes `complete = all(categories complete)` and `status='scored'`, then `finish()` returns (`:162-163`).
  - A freshness request naturally comes from `case_freshness`, the second category. `fairness` and `v2_strategies` then never run, so the authenticated report reads:

    `complete: False, blocking: ['[freshness-review] independent verdict required'], freshness_review: [], status: 'scored'`
  - In `write_and_attack` the findings list is non-empty, which skips the `interrupted_review` check. `loop_freshness` returns early (nothing flagged, nothing requested), and the receipt becomes validated and `exhausted`/`rounds_exhausted`.
  - `package.stress` then hits the existing hold (`not result['complete']`), and the proposed conjunction does not fire.
- **Consequences:**
  - Retirement is reachable only when the request comes from the last category in a call that also completes it, or from authored `complete=True` bytes, which is what the current `test_request_only_with_missing_or_empty_metadata_deliberately_holds` uses.
  - The O5b `extension_execution_pending` pit stop stays for the realistic pilot shape.
  - Exam 1 ("completed request-only report through the real writer/category path") can be met only by staging that unrealistic last-category shape, so it would pass without proving the claim.
- **Why relaxing the condition is safe:**
  - The scored-failure path already accepts this completion evidence. `test_completed_category_blocker_wins_over_unfinished_diagnostics_and_replays` scores a `complete=False`, `status='scored'` category blocker.
  - Retirement is terminal and unscored, so the unreviewed categories cannot change a result.
  - Interrupted bytes are already excluded: they carry `status='pending'` and no `review_completed`, and the receipt check at `:367-373` refuses them.
- **Fix (same conjunction, no new mechanism):**
  - Replace `complete is True` with `complete is True or result.get('status') == 'scored'`, keeping the authenticated validated receipt and the report-hash binding.
  - Keep the `review incomplete` and mixed-defect exclusions as written. `freshness_only_clearance` already leaves the sentinel blocking.
- **Exam 1 must also:**
  - emit the request line from the `case_freshness` category, with that category not yet complete, through real `REAL_CATEGORIES`;
  - assert the aggregate has `complete is False` and `status == 'scored'`;
  - assert it retires.
- **Exam 3 must add** a `status: 'pending'`, `complete: False` request-only report with a re-hashed receipt as a hold negative.

### 2. Nit: the unfinished-diagnostic and unfinished-validation exclusions will hold some real shapes

- **Where:** design lines 39-40.
- **What happens:**
  - In category mode, an incomplete `case_freshness` category can carry `unfinished_validation`. The test fixture's default also leaves `diagnostic-budgets/attacker-9/claimed` with an interrupted status.
  - Under the current conjunction, both shapes keep the hold. That is conservative and safe, but it shrinks how often the pit stop is actually removed.
- **Fix:** either say so explicitly as an accepted residual hold, or justify keeping these exclusions for an unscored terminal stop. Scored defects already override both.

## Implementation readiness after fixing finding 1

The design is otherwise ready to implement, with no decisions left to the implementer:
- The placement in `stress` is clear, as are the exact card mutations, the raise label and the status mapping.
- The money assertions and the replay/dispatch settings are specific.
- The test file, fixtures and negative control are named.

Scope is right for the 3-case pilot: no multi-scenario clamps, schema, money, scheduler or new journal.

## Three-line handback for the parent (unresolved blocker)

1. Blocker: the retirement conjunction requires `complete is True`. The real category-mode request-only report is `complete: False, status: 'scored'`, because `stress_progress` stops at the first blocking category (`case_freshness`), so the O5b hold remains.
2. Fix: accept `complete is True or status == 'scored'` under the existing authenticated, validated, exhausted receipt, and keep the sentinel and mixed-defect exclusions.
3. Exams: exam 1 emits the request from `case_freshness` through real categories and asserts `complete False` plus retirement; add a `status: 'pending'` request-only hold negative.

## Implementer disposition

Round-2 blocker handed back to parent under the two-round cap. No production
implementation or third review started. Proposed correction and residual-hold
decision await parent direction.
