**Verdict: PASS.** No blocking finding. This is goldfish diff review round 1 of 2, `Mode: REVIEW`, read-only, covering `7f1c09e..330c3bd` on `t3/isolation-o5b` (tested production `e3cd178`). I read the zoom_out and implementation_readiness personas, the implementation-readiness standard, `docs/ENGINEERING.md`, the design including "Parent-approved after round 2", and both design reviews. I made no edits, model or HTTP calls, or suite reruns.

## Scope and evidence checks

- **Production edits stay in scope.** Only `factory/extension_package.py` (`stress`, +21/-4) and `factory/batch_status.py` (STOPS entry plus the retired branch) change. `e3cd178..HEAD` touches only report and evidence files, so the tested source is the head source.
- **Hashes match.** The `evidence.json` sha256 values match the current `extension_package.py`, `batch_status.py`, the test file and all three logs. `git show e3cd178:factory/extension_package.py` hashes the same.
- **Full suite.** The log ends "182 test scripts run; 0 failed" and has 182 `==` script headers. The report states the exact `lockf … tests/run.py` command and 2847.271 s including the lock wait. There was no timing rerun and no limit change.
- **Focused tests.** 18 tests ran, OK.
- **Negative control.** The log shows the real case_freshness test failing with `extension_execution_pending` when the branch is removed, which is the original hold.
- **Murphy.** `docs/murphy-register.md` is unchanged. The report says "No Murphy row closes" and the test docstring says "no Murphy closure is claimed". No closure is claimed.

## Code safety against the design (`extension_package.py:378-400`)

- **Checks still run first.** The retirement branch runs after the existing record replay, the receipt actor/phase/pending/round/limit/report/attempt/binding/report-hash checks and the scientific-binding check.
- **The conjunction matches the approved design:**
  - `complete` or `status == 'scored'`;
  - a nonempty original `blocking`;
  - empty `freshness_only_clearance` output, so the `review incomplete` sentinel and mixed defects are excluded;
  - no `freshness_review` and no malformed flag;
  - no `unfinished_validation` and no unfinished diagnostic claim;
  - `exhausted is True` and `rounds_exhausted`;
  - neither `.clearance.json` nor `-writer.json` exists, and symlinks count as present.
- **Card handling matches the design.**
  - `InvalidInfra` is raised before any card change.
  - Stale `failed_gate`, `failed_detail` and `infrastructure_gate` are popped, and `gates` and `gate_results` are emptied.
  - `stress_review`, status `stopped` and `terminal_stop` are set as specified, then `BudgetError('retired_stress_request_only')` is raised.
  - There is no `records.save`, no `extensions.complete` and no outcome.
- **The clearance trigger reuses existing proof.** It is widened by `has_clearance` and still uses `late_recovery.cleared_stress`. A failed proof falls to `extension_execution_pending`, and a pass still goes through the unchanged `ok` / `next_phase` path.
- **Status display.** `batch_status` maps the label to the retired bucket before failed-gate handling, using the specified reason.

## Test coverage against the exams

1. **Exam 1 (category shape).** `test_real_case_freshness_request_retires_unscored_and_replays` covers it.
   - The real `REAL_CATEGORIES` and `REAL_FRESHNESS` run, with `wrong_fixes` complete and clean and the request emitted from an incomplete `case_freshness`.
   - It asserts `complete False`, `status 'scored'` and the coverage flags, then retirement.
   - It also asserts the history stays open, no record is written, stale gate fields are cleared, no gate call happens and reservations are settled.
   - The authored no-flag boundary is asserted, and `confirm_hits` raises `AssertionError`.
2. **Exam 2 (replays).**
   - Two package replays with the card's stop and stress-review fields popped, while `_invoke` raises.
   - Attack-state, report, history and ledger bytes stay unchanged.
   - `finalize_accounting` is idempotent, `diagnosis.exhaustion` is False and `pending_projection` is None.
   - The `DIAGNOSIS_ENABLED=True` dispatch `apply` followed by `package.run` reaches the same guard.
3. **Exam 3 (holds).**
   - These all hold: `status: 'pending'`, `unfinished_validation`, malformed metadata (`[None]`), the sentinel, no exhaustion and the claimed-but-unfinished diagnostic.
   - Invalid infrastructure raises `InvalidInfra` from the new branch; without the branch the fall-through would refuse instead.
   - Nonempty metadata holds, in the renamed test.
   - Existing tests still cover hash and receipt drift.
4. **Exam 4 (recovery, status and money).**
   - Restart and holder recovery are rejected, and the status renders as retired with "0 rejected".
   - B `plan` returns `exhaustion=False`, `pending_projection=None` and an empty queue for both a known total (0.25) and an unknown one (None).
   - `aggregate`, `held_usd`, `known_floor_usd` and authority are unchanged, and `card_total` is None for unknown usage.
5. **Exam 5 (negative control).** Present and genuine.
6. **Exam 6 (clearance proof).**
   - Real `loop_freshness` and `confirm_hits` run with saved HTTP bytes and an authored exclusion, so production code creates the proof.
   - A valid proof passes stress and reaches `run_gates`.
   - A tampered proof holds with no outcome.
   - An orphan writer file, an orphan clearance file and dangling symlinks of each hold.

**Residuals.** The report states them, matching the design: comparison and evaluator scoring, writer forwarding, the label overwrite when diagnosis is disabled, cross-batch export, and the unfinished diagnostic/validation holds. It makes no broad never-score claim.

## Findings (all optional, non-blocking)

1. **Nit: the widened clearance trigger can newly hold a clean report** (`extension_package.py:397`).
   - **What happens:** clearance files are never deleted (`run.py:1127`; `late_recovery` only reads them). If a same-round re-attempt produces a clean report (`blocking == []`) while an older `round-N.clearance.json` is still there, `has_clearance` now forces `cleared_stress`. Its `source_sha256` check fails and the case refuses with `extension_execution_pending`, where before it passed.
   - **Severity:** this fails closed, never scores, and the design approved the trigger as written, so it is not a blocker.
   - **Fix:** use `... or (has_clearance and result['blocking'])`. With no original blocking there is nothing to clear, so a clean report keeps its old behaviour. Add one subtest: a clean report plus a stale clearance file still passes.
2. **Nit: there is no test for a genuine mixed defect on the request-only shape.**
   - **What's missing:** design exam 3 says "Genuine mixed defect remains a stress failure". No test combines the request line with a real defect.
   - **Why it is minor:** the guard (`not cleared_blocking`) is pinned by the sentinel subtest, and a mixed defect falls into the unchanged scored-failure path.
   - **Fix:** add a subtest with `blocking=[request, 'Authored completed-call case defect']` and assert `extension_incomplete` with a failed outcome.
3. **Nit: the retained-artifact assertion skips some files.** Exam 1 compares bytes only for attack-state, the report, history and the ledger.
   - **What's missing:** `attacks/round-9-categories/*` and `diagnostic-budgets/*`, which the design says to retain.
   - **Fix:** optionally add them to `paths`, for example with `extensions.tree(...)`.
4. **Nit: the retirement reason can mislabel the URL form.** `freshness_only_clearance` also matches the form "obtain an independent reviewer verdict … for https://…", whose blocking line itself contains a URL. That form also retires, and the reason "lacks freshness metadata" is accurate only in that `freshness_review` is absent. `loop_freshness` does not use URLs from blocking lines, so the behaviour follows the design.
   - **Fix:** none needed. Optionally note it in the handback.

Murphy closure: none claimed. Verified.

## Implementer disposition

PASS accepted. Optional nits retained without source changes, following the
parent's instruction to hand back immediately on pass. In particular, a stale
clearance beside a clean same-round re-attempt can cause an additional unscored
hold. No second diff review or further implementation started.
